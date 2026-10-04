"""
GBOC Server — Recebimento do inventário dos Agentes.

POST /api/v1/sync/inventory  (chave de pareamento do agente — rota de ingestão)

Grava, de forma idempotente, os dados que alimentam relatórios, gráficos e o
Gerenciamento Remoto:
  agent_tasks            (+ agendamento, motor, repositório, origem, retenção, última execução)
  agent_repositories     (+ caminho/destino, tamanho, snapshots, espaço livre e total)
  agent_repo_size_history (série histórica de tamanho → crescimento e previsão de esgotamento)
  agent_task_executions  (+ nome da tarefa, repositório, dados novos, velocidade, arquivos novos/alterados)
  agent_restore_history, agent_verifications, agent_job_failures, agent_volumes
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("gboc_inventory_sync")
router = APIRouter(tags=["Sincronização de Inventário"])

_schema_lock = threading.Lock()
_schema_ready = False

SCHEMA_SQL = [
    # Colunas novas em tabelas existentes
    "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS engine VARCHAR(50)",
    "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS task_type VARCHAR(50)",
    "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS repository_id INTEGER",
    "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS repository_name TEXT",
    "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_paths TEXT",
    "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS schedule_cron VARCHAR(100)",
    "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS schedule_enabled BOOLEAN",
    "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS enabled BOOLEAN",
    "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS retention_policy TEXT",
    "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS last_run TIMESTAMP",
    "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS last_status VARCHAR(50)",
    "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS removed_at TIMESTAMP",

    "ALTER TABLE agent_repositories ADD COLUMN IF NOT EXISTS path TEXT",
    "ALTER TABLE agent_repositories ADD COLUMN IF NOT EXISTS target TEXT",
    "ALTER TABLE agent_repositories ADD COLUMN IF NOT EXISTS provider VARCHAR(100)",
    "ALTER TABLE agent_repositories ADD COLUMN IF NOT EXISTS size_bytes BIGINT",
    "ALTER TABLE agent_repositories ADD COLUMN IF NOT EXISTS snapshot_count INTEGER",
    "ALTER TABLE agent_repositories ADD COLUMN IF NOT EXISTS free_bytes BIGINT",
    "ALTER TABLE agent_repositories ADD COLUMN IF NOT EXISTS capacity_bytes BIGINT",
    "ALTER TABLE agent_repositories ADD COLUMN IF NOT EXISTS size_recorded_at TIMESTAMP",
    "ALTER TABLE agent_repositories ADD COLUMN IF NOT EXISTS initialized BOOLEAN",
    "ALTER TABLE agent_repositories ADD COLUMN IF NOT EXISTS removed_at TIMESTAMP",

    "ALTER TABLE agent_task_executions ADD COLUMN IF NOT EXISTS task_name TEXT",
    "ALTER TABLE agent_task_executions ADD COLUMN IF NOT EXISTS repository_name TEXT",
    "ALTER TABLE agent_task_executions ADD COLUMN IF NOT EXISTS bytes_added BIGINT",
    "ALTER TABLE agent_task_executions ADD COLUMN IF NOT EXISTS avg_speed_bps DOUBLE PRECISION",
    "ALTER TABLE agent_task_executions ADD COLUMN IF NOT EXISTS files_new INTEGER",
    "ALTER TABLE agent_task_executions ADD COLUMN IF NOT EXISTS files_changed INTEGER",
    "ALTER TABLE agent_task_executions ADD COLUMN IF NOT EXISTS snapshot_id TEXT",

    """CREATE TABLE IF NOT EXISTS agent_repo_size_history (
        id SERIAL PRIMARY KEY,
        agent_id VARCHAR(255) NOT NULL,
        repo_id INTEGER NOT NULL,
        repo_name TEXT,
        size_bytes BIGINT,
        snapshot_count INTEGER,
        free_bytes BIGINT,
        capacity_bytes BIGINT,
        recorded_at TIMESTAMP DEFAULT LOCALTIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS idx_repo_size_hist ON agent_repo_size_history (agent_id, repo_id, recorded_at)",

    """CREATE TABLE IF NOT EXISTS agent_restore_history (
        id SERIAL PRIMARY KEY,
        agent_id VARCHAR(255) NOT NULL,
        restore_id INTEGER NOT NULL,
        repository_name TEXT,
        snapshot_id TEXT,
        status VARCHAR(50),
        target_path TEXT,
        total_files INTEGER,
        files_restored INTEGER,
        bytes_restored BIGINT,
        duration_seconds INTEGER,
        error_message TEXT,
        created_at TIMESTAMP,
        synced_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
        UNIQUE (agent_id, restore_id)
    )""",

    """CREATE TABLE IF NOT EXISTS agent_verifications (
        id SERIAL PRIMARY KEY,
        agent_id VARCHAR(255) NOT NULL,
        kind VARCHAR(30) NOT NULL,
        ext_id INTEGER NOT NULL,
        subject TEXT,
        status VARCHAR(50),
        started_at TIMESTAMP,
        finished_at TIMESTAMP,
        errors_found INTEGER,
        summary TEXT,
        synced_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
        UNIQUE (agent_id, kind, ext_id)
    )""",

    """CREATE TABLE IF NOT EXISTS agent_job_failures (
        id SERIAL PRIMARY KEY,
        agent_id VARCHAR(255) NOT NULL,
        ext_id INTEGER NOT NULL,
        task_id VARCHAR(100),
        task_name TEXT,
        failure_reason TEXT,
        retry_count INTEGER,
        max_retries INTEGER,
        status VARCHAR(50),
        escalated BOOLEAN,
        first_failed_at TIMESTAMP,
        last_retried_at TIMESTAMP,
        resolved_at TIMESTAMP,
        synced_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
        UNIQUE (agent_id, ext_id)
    )""",

    """CREATE TABLE IF NOT EXISTS agent_volumes (
        agent_id VARCHAR(255) NOT NULL,
        mountpoint TEXT NOT NULL,
        fstype VARCHAR(50),
        total_bytes BIGINT,
        used_bytes BIGINT,
        free_bytes BIGINT,
        updated_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
        PRIMARY KEY (agent_id, mountpoint)
    )""",

    """CREATE TABLE IF NOT EXISTS agent_replication (
        agent_id VARCHAR(255) NOT NULL,
        policy_id INTEGER NOT NULL,
        name TEXT,
        source_repository_name TEXT,
        dest_type VARCHAR(50),
        mode VARCHAR(50),
        status VARCHAR(50),
        enabled BOOLEAN,
        schedule_cron VARCHAR(100),
        last_run TIMESTAMP,
        total_bytes BIGINT,
        updated_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
        PRIMARY KEY (agent_id, policy_id)
    )""",

    """CREATE TABLE IF NOT EXISTS agent_inventory_status (
        agent_id VARCHAR(255) PRIMARY KEY,
        last_inventory_at TIMESTAMP,
        collected_at TIMESTAMP,
        tasks INTEGER, repositories INTEGER, executions INTEGER,
        agent_version VARCHAR(50)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ate_started ON agent_task_executions (started_at)",
    "CREATE INDEX IF NOT EXISTS idx_ate_agent_started ON agent_task_executions (agent_id, started_at)",
]


def _db():
    from database import db_manager
    return db_manager


def ensure_schema(conn=None) -> None:
    """Cria/ajusta as tabelas uma vez por processo (idempotente)."""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        own = conn is None
        dbm = _db()
        if own:
            conn = dbm.get_connection()
        try:
            cur = conn.cursor()
            for sql in SCHEMA_SQL:
                try:
                    cur.execute(sql)
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    logger.warning(f"[INVENTÁRIO] Ajuste de schema ignorado ({exc}): {sql[:80]}")
            cur.close()
            _schema_ready = True
        finally:
            if own:
                dbm.release_connection(conn)


def _ts(v: Any) -> Optional[str]:
    if not v:
        return None
    s = str(v)
    # Normaliza "2026-10-04T06:35:11+00:00" → mantém; PostgreSQL converte para TIMESTAMP local
    return s


def _int(v: Any) -> Optional[int]:
    try:
        return None if v is None or v == "" else int(float(v))
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _retention(t: Dict[str, Any]) -> str:
    parts = []
    for key, label in (("retention_days", "d"), ("retention_weekly", "s"), ("retention_monthly", "m"), ("retention_yearly", "a")):
        v = _int(t.get(key))
        if v:
            parts.append(f"{v}{label}")
    return " / ".join(parts)


def store_inventory(conn, agent_id: str, inv: Dict[str, Any]) -> Dict[str, int]:
    """Grava o inventário (transação única). Retorna contagens."""
    ensure_schema(conn)
    from psycopg2.extras import execute_values
    cur = conn.cursor()
    counts: Dict[str, int] = {}

    tasks = inv.get("tasks") or []
    seen_tasks = []
    for t in tasks:
        tid = _int(t.get("id"))
        if tid is None:
            continue
        seen_tasks.append(tid)
        vals = (t.get("name"), t.get("status") or t.get("last_status") or "idle", _ts(t.get("updated_at")),
                t.get("engine"), t.get("type"), _int(t.get("repository_id")), t.get("repository_name"),
                json.dumps(t.get("source_paths") or [], ensure_ascii=False), t.get("schedule_cron"),
                t.get("schedule_enabled"), t.get("enabled"), _retention(t), _ts(t.get("last_run")), t.get("last_status"))
        cur.execute("""
            UPDATE agent_tasks SET name=%s, status=%s, updated_at=COALESCE(%s::timestamp, updated_at), engine=%s, task_type=%s,
                   repository_id=%s, repository_name=%s, source_paths=%s, schedule_cron=%s, schedule_enabled=%s,
                   enabled=%s, retention_policy=%s, last_run=%s, last_status=%s, removed_at=NULL, synced_at=CURRENT_TIMESTAMP
            WHERE agent_id=%s AND task_id=%s
        """, vals + (agent_id, tid))
        if cur.rowcount == 0:
            cur.execute("""
                INSERT INTO agent_tasks (agent_id, task_id, name, status, created_at, updated_at, engine, task_type,
                    repository_id, repository_name, source_paths, schedule_cron, schedule_enabled, enabled,
                    retention_policy, last_run, last_status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (agent_id, tid, vals[0], vals[1], _ts(t.get("created_at")), vals[2]) + vals[3:])
    if seen_tasks:
        cur.execute("UPDATE agent_tasks SET removed_at=COALESCE(removed_at, LOCALTIMESTAMP) WHERE agent_id=%s AND NOT (task_id = ANY(%s))",
                    (agent_id, seen_tasks))
    counts["tasks"] = len(seen_tasks)

    repos = inv.get("repositories") or []
    seen_repos = []
    for r in repos:
        rid = _int(r.get("id"))
        if rid is None:
            continue
        seen_repos.append(rid)
        size, snaps = _int(r.get("size_bytes")), _int(r.get("snapshot_count"))
        free, cap = _int(r.get("free_bytes")), _int(r.get("capacity_bytes"))
        cur.execute("""
            INSERT INTO agent_repositories (agent_id, repo_id, name, engine, type, status, path, target, provider,
                size_bytes, snapshot_count, free_bytes, capacity_bytes, size_recorded_at, initialized, removed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL)
            ON CONFLICT (agent_id, repo_id) DO UPDATE SET
                name=EXCLUDED.name, engine=EXCLUDED.engine, type=EXCLUDED.type, status=EXCLUDED.status,
                path=EXCLUDED.path, target=EXCLUDED.target, provider=EXCLUDED.provider,
                size_bytes=COALESCE(EXCLUDED.size_bytes, agent_repositories.size_bytes),
                snapshot_count=COALESCE(EXCLUDED.snapshot_count, agent_repositories.snapshot_count),
                free_bytes=EXCLUDED.free_bytes, capacity_bytes=EXCLUDED.capacity_bytes,
                size_recorded_at=COALESCE(EXCLUDED.size_recorded_at, agent_repositories.size_recorded_at),
                initialized=EXCLUDED.initialized, removed_at=NULL, synced_at=CURRENT_TIMESTAMP
        """, (agent_id, rid, r.get("name"), r.get("engine") or "gboc_native", r.get("type") or "local",
              r.get("status") or "active", r.get("path"), r.get("target"), r.get("provider"),
              size, snaps, free, cap, _ts(r.get("size_recorded_at")), r.get("initialized")))
        # Série histórica: grava quando muda ou a cada 6 h (base para crescimento/previsão)
        if size is not None or free is not None:
            cur.execute("""
                SELECT size_bytes, free_bytes, recorded_at FROM agent_repo_size_history
                WHERE agent_id=%s AND repo_id=%s ORDER BY recorded_at DESC LIMIT 1
            """, (agent_id, rid))
            last = cur.fetchone()
            if (not last or last[0] != size or (last[2] and (datetime.now() - last[2]).total_seconds() > 6 * 3600)):
                cur.execute("""
                    INSERT INTO agent_repo_size_history (agent_id, repo_id, repo_name, size_bytes, snapshot_count, free_bytes, capacity_bytes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """, (agent_id, rid, r.get("name"), size, snaps, free, cap))
    if seen_repos:
        cur.execute("UPDATE agent_repositories SET removed_at=COALESCE(removed_at, LOCALTIMESTAMP) WHERE agent_id=%s AND NOT (repo_id = ANY(%s))",
                    (agent_id, seen_repos))
    counts["repositories"] = len(seen_repos)

    execs = []
    for e in inv.get("task_executions") or []:
        eid = _int(e.get("id"))
        if eid is None:
            continue
        execs.append((agent_id, _int(e.get("task_id")), eid, e.get("status"), _ts(e.get("started_at")),
                      _ts(e.get("completed_at")), _float(e.get("duration_seconds")), _int(e.get("files_processed")) or 0,
                      _int(e.get("bytes_processed")) or 0, (e.get("error_message") or None), e.get("task_name"),
                      e.get("repository_name"), _int(e.get("bytes_added")), _float(e.get("avg_speed_bytes_per_sec")),
                      _int(e.get("files_new")), _int(e.get("files_changed")), e.get("snapshot_id")))
    if execs:
        execute_values(cur, """
            INSERT INTO agent_task_executions (agent_id, task_id, execution_id, status, started_at, completed_at,
                duration_seconds, files_processed, bytes_processed, error_message, task_name, repository_name,
                bytes_added, avg_speed_bps, files_new, files_changed, snapshot_id)
            VALUES %s
            ON CONFLICT (agent_id, task_id, execution_id) DO UPDATE SET
                status=EXCLUDED.status, started_at=EXCLUDED.started_at, completed_at=EXCLUDED.completed_at,
                duration_seconds=EXCLUDED.duration_seconds, files_processed=EXCLUDED.files_processed,
                bytes_processed=EXCLUDED.bytes_processed, error_message=EXCLUDED.error_message,
                task_name=EXCLUDED.task_name, repository_name=EXCLUDED.repository_name, bytes_added=EXCLUDED.bytes_added,
                avg_speed_bps=EXCLUDED.avg_speed_bps, files_new=EXCLUDED.files_new, files_changed=EXCLUDED.files_changed,
                snapshot_id=EXCLUDED.snapshot_id, synced_at=CURRENT_TIMESTAMP
        """, execs, page_size=500)
    counts["executions"] = len(execs)

    rows = [(agent_id, _int(r.get("id")), r.get("repository_name"), r.get("snapshot_id"), r.get("status"), r.get("target_path"),
             _int(r.get("total_files")), _int(r.get("files_restored")), _int(r.get("bytes_restored")),
             _int(r.get("duration_seconds")), r.get("error_message"), _ts(r.get("created_at")))
            for r in inv.get("restores") or [] if _int(r.get("id")) is not None]
    if rows:
        execute_values(cur, """
            INSERT INTO agent_restore_history (agent_id, restore_id, repository_name, snapshot_id, status, target_path,
                total_files, files_restored, bytes_restored, duration_seconds, error_message, created_at)
            VALUES %s ON CONFLICT (agent_id, restore_id) DO UPDATE SET status=EXCLUDED.status,
                files_restored=EXCLUDED.files_restored, bytes_restored=EXCLUDED.bytes_restored,
                duration_seconds=EXCLUDED.duration_seconds, error_message=EXCLUDED.error_message, synced_at=LOCALTIMESTAMP
        """, rows)
    counts["restores"] = len(rows)

    rows = [(agent_id, v.get("kind"), _int(v.get("ext_id")), v.get("subject"), v.get("status"), _ts(v.get("started_at")),
             _ts(v.get("finished_at")), _int(v.get("errors_found")), v.get("summary"))
            for v in inv.get("verifications") or [] if _int(v.get("ext_id")) is not None and v.get("kind")]
    if rows:
        execute_values(cur, """
            INSERT INTO agent_verifications (agent_id, kind, ext_id, subject, status, started_at, finished_at, errors_found, summary)
            VALUES %s ON CONFLICT (agent_id, kind, ext_id) DO UPDATE SET status=EXCLUDED.status,
                finished_at=EXCLUDED.finished_at, errors_found=EXCLUDED.errors_found, summary=EXCLUDED.summary, synced_at=LOCALTIMESTAMP
        """, rows)
    counts["verifications"] = len(rows)

    rows = [(agent_id, _int(f.get("id")), str(f.get("task_id") or ""), f.get("task_name"), f.get("failure_reason"),
             _int(f.get("retry_count")), _int(f.get("max_retries")), f.get("status"), f.get("escalated"),
             _ts(f.get("first_failed_at")), _ts(f.get("last_retried_at")), _ts(f.get("resolved_at")))
            for f in inv.get("job_failures") or [] if _int(f.get("id")) is not None]
    if rows:
        execute_values(cur, """
            INSERT INTO agent_job_failures (agent_id, ext_id, task_id, task_name, failure_reason, retry_count, max_retries,
                status, escalated, first_failed_at, last_retried_at, resolved_at)
            VALUES %s ON CONFLICT (agent_id, ext_id) DO UPDATE SET failure_reason=EXCLUDED.failure_reason,
                retry_count=EXCLUDED.retry_count, status=EXCLUDED.status, escalated=EXCLUDED.escalated,
                last_retried_at=EXCLUDED.last_retried_at, resolved_at=EXCLUDED.resolved_at, synced_at=LOCALTIMESTAMP
        """, rows)
    counts["job_failures"] = len(rows)

    if "replication" in inv:
        cur.execute("DELETE FROM agent_replication WHERE agent_id=%s", (agent_id,))
        rows = [(agent_id, _int(rp.get("id")), rp.get("name"), rp.get("source_repository_name"), rp.get("dest_type"),
                 rp.get("mode"), rp.get("status"), rp.get("enabled"), rp.get("schedule_cron"), _ts(rp.get("last_run")),
                 _int(rp.get("total_bytes"))) for rp in inv.get("replication") or [] if _int(rp.get("id")) is not None]
        if rows:
            execute_values(cur, """
                INSERT INTO agent_replication (agent_id, policy_id, name, source_repository_name, dest_type, mode, status,
                    enabled, schedule_cron, last_run, total_bytes) VALUES %s
            """, rows)
        counts["replication"] = len(rows)

    vols = inv.get("volumes") or []
    if vols:
        cur.execute("DELETE FROM agent_volumes WHERE agent_id=%s", (agent_id,))
        execute_values(cur, """
            INSERT INTO agent_volumes (agent_id, mountpoint, fstype, total_bytes, used_bytes, free_bytes) VALUES %s
        """, [(agent_id, v.get("mountpoint"), v.get("fstype"), _int(v.get("total_bytes")), _int(v.get("used_bytes")),
               _int(v.get("free_bytes"))) for v in vols if v.get("mountpoint")])
    counts["volumes"] = len(vols)

    cur.execute("""
        INSERT INTO agent_inventory_status (agent_id, last_inventory_at, collected_at, tasks, repositories, executions)
        VALUES (%s, LOCALTIMESTAMP, %s, %s, %s, %s)
        ON CONFLICT (agent_id) DO UPDATE SET last_inventory_at=LOCALTIMESTAMP, collected_at=EXCLUDED.collected_at,
            tasks=EXCLUDED.tasks, repositories=EXCLUDED.repositories, executions=EXCLUDED.executions
    """, (agent_id, _ts(inv.get("collected_at")), counts["tasks"], counts["repositories"], counts["executions"]))
    cur.close()
    return counts


def _store_sync(agent_id: str, inv: Dict[str, Any]) -> Dict[str, int]:
    dbm = _db()
    conn = dbm.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM agents WHERE agent_id=%s", (agent_id,))
        if not cur.fetchone():
            cur.close()
            raise LookupError("Agente não registrado no Server (aguarde o primeiro heartbeat)")
        cur.close()
        counts = store_inventory(conn, agent_id, inv)
        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        dbm.release_connection(conn)


@router.post("/api/v1/sync/inventory")
async def receive_inventory(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "JSON inválido"}, status_code=400)
    agent_id = str((body or {}).get("agent_id") or "").strip()
    inv = (body or {}).get("inventory")
    if not agent_id or not isinstance(inv, dict):
        return JSONResponse({"status": "error", "message": "agent_id e inventory são obrigatórios"}, status_code=400)
    try:
        counts = await asyncio.to_thread(_store_sync, agent_id, inv)
        return {"status": "success", "stored": counts}
    except LookupError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=409)
    except Exception as e:
        logger.error(f"[INVENTÁRIO] Falha ao gravar inventário do agente {agent_id}: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
