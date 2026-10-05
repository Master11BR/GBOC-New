"""
GBOC Agent — Inventário enviado ao Servidor Central.

Monta, a partir do banco local do Agente, um retrato completo e SEGURO para o Server:

  * repositories   — dados do repositório + tamanho real (storage_usage_history),
                     quantidade de snapshots e espaço livre/total do disco de destino.
                     Senhas e chaves NUNCA são enviadas.
  * tasks          — agendamento, motor, repositório, origem, retenção, última execução.
                     Scripts pré/pós não são enviados (podem conter credenciais).
  * task_executions — execuções dos últimos 30 dias (até 1000) com nome da tarefa,
                     velocidade, dados novos, arquivos novos/alterados e snapshot.
  * restores, verifications (integridade + SureBackup), job_failures, volumes do host.

É usado pela sincronização periódica HTTP (/api/v1/sync/inventory — funciona mesmo sem
WebSocket) e pela sincronização completa via WebSocket.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {"password", "motor_password", "cloud_password", "encryption_password",
                  "secret_key", "access_key", "api_key", "token", "passphrase", "pre_script", "post_script"}


def _ser(v: Any) -> Any:
    if isinstance(v, (datetime, date, dtime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        try:
            return bytes(v).decode("utf-8")
        except UnicodeDecodeError:
            return bytes(v).decode("cp1252", errors="replace")
    return v


def _rows(cur, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        out = []
        for r in cur.fetchall():
            d = dict(r) if isinstance(r, dict) else dict(zip(cols, r))
            out.append({k: _ser(v) for k, v in d.items() if k not in SENSITIVE_KEYS})
        return out
    except Exception as exc:
        logger.debug(f"[INVENTÁRIO] consulta ignorada: {exc}")
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return []


def _json_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except Exception:
            return [p.strip() for p in value.split(",") if p.strip()]
    return []


def _disk_of(path: Optional[str]) -> Dict[str, Optional[int]]:
    """Espaço total/livre do disco onde fica o repositório (somente caminhos locais existentes)."""
    if not path or "://" in str(path):
        return {"capacity_bytes": None, "free_bytes": None}
    try:
        import shutil
        p = str(path)
        while p and not os.path.exists(p):
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
        if p and os.path.exists(p):
            u = shutil.disk_usage(p)
            return {"capacity_bytes": int(u.total), "free_bytes": int(u.free)}
    except Exception:
        pass
    return {"capacity_bytes": None, "free_bytes": None}


def _volumes() -> List[Dict[str, Any]]:
    out = []
    try:
        import psutil
        seen = set()
        for part in psutil.disk_partitions(all=False):
            if (part.mountpoint in seen or "cdrom" in (part.opts or "") or not part.fstype
                    or part.fstype.lower() in ("squashfs", "overlay", "tmpfs", "devtmpfs", "iso9660", "udf")):
                continue
            seen.add(part.mountpoint)
            try:
                u = psutil.disk_usage(part.mountpoint)
            except Exception:
                continue
            if u.total <= 0:
                continue
            out.append({"mountpoint": part.mountpoint, "fstype": part.fstype,
                        "total_bytes": int(u.total), "used_bytes": int(u.used), "free_bytes": int(u.free)})
    except Exception as exc:
        logger.debug(f"[INVENTÁRIO] volumes indisponíveis: {exc}")
    return out[:40]


def build_inventory(conn, days: int = 30, max_executions: int = 1000) -> Dict[str, Any]:
    """Coleta o inventário a partir de uma conexão do banco do Agente."""
    cur = conn.cursor()
    since = (datetime.now() - timedelta(days=days))

    repos = _rows(cur, """
        SELECT id, name, type, path, engine, status, enabled, initialized, config, created_at, updated_at
        FROM repositories ORDER BY id
    """)
    sizes = {}
    for s in _rows(cur, """
        SELECT DISTINCT ON (repository_id) repository_id, repository_name, size_bytes, snapshot_count, recorded_at
        FROM storage_usage_history ORDER BY repository_id, recorded_at DESC
    """):
        sizes[str(s.get("repository_id"))] = s
    for r in repos:
        cfg = r.pop("config", None)
        target = r.get("path")
        try:
            c = json.loads(cfg) if isinstance(cfg, str) and cfg.strip() else (cfg or {})
            if isinstance(c, dict):
                target = c.get("bucket") if (r.get("type") or "local") != "local" and c.get("bucket") else target
                r["provider"] = c.get("provider") or c.get("cloud_provider")
        except Exception:
            pass
        s = sizes.get(str(r.get("id"))) or {}
        r["size_bytes"] = s.get("size_bytes")
        r["snapshot_count"] = s.get("snapshot_count")
        r["size_recorded_at"] = s.get("recorded_at")
        r.update(_disk_of(r.get("path")) if (r.get("type") or "local") == "local" else
                 {"capacity_bytes": None, "free_bytes": None})
        r["target"] = target

    repo_names = {r.get("id"): r.get("name") for r in repos}

    tasks = _rows(cur, """
        SELECT id, name, repository_id, status, type, engine, source_paths, schedule_enabled, schedule_cron,
               enabled, retention_days, retention_weekly, retention_monthly, retention_yearly,
               retry_enabled, retry_max_attempts, created_at, updated_at, last_run, last_status
        FROM tasks ORDER BY id
    """)
    task_names = {}
    for t in tasks:
        t["source_paths"] = _json_list(t.get("source_paths"))
        t["repository_name"] = repo_names.get(t.get("repository_id"))
        task_names[t.get("id")] = t.get("name")

    execs = _rows(cur, """
        SELECT id, task_id, status, started_at, completed_at, duration_seconds, bytes_processed, files_processed,
               error_message, snapshot_id, files_total, bytes_total, avg_speed_bytes_per_sec, compression_ratio,
               files_new, files_changed, files_unmodified, bytes_added
        FROM task_executions WHERE started_at >= %s ORDER BY started_at DESC LIMIT %s
    """, (since, max_executions))
    task_repo = {t.get("id"): t.get("repository_name") for t in tasks}
    for e in execs:
        e["task_name"] = task_names.get(e.get("task_id"))
        e["repository_name"] = task_repo.get(e.get("task_id"))
        if e.get("error_message"):
            e["error_message"] = str(e["error_message"])[:2000]

    restores = _rows(cur, """
        SELECT id, repository_id, snapshot_id, status, target_path, total_files, files_restored, bytes_restored,
               duration_seconds, error_message, created_at
        FROM restore_history WHERE created_at >= %s ORDER BY created_at DESC LIMIT 300
    """, (since - timedelta(days=60),))
    for r in restores:
        r["repository_name"] = repo_names.get(r.get("repository_id"))

    verifications = []
    for v in _rows(cur, """
        SELECT id, repository_id, engine, status, started_at, finished_at, result_summary, errors_found
        FROM integrity_checks ORDER BY started_at DESC NULLS LAST LIMIT 200
    """):
        verifications.append({"kind": "integrity", "ext_id": v.get("id"),
                              "subject": repo_names.get(v.get("repository_id")) or f"Repositório {v.get('repository_id')}",
                              "status": v.get("status"), "started_at": v.get("started_at"),
                              "finished_at": v.get("finished_at"), "errors_found": v.get("errors_found"),
                              "summary": (v.get("result_summary") or "")[:500]})
    for v in _rows(cur, """
        SELECT id, task_id, snapshot_id, status, boot_time_seconds, network_check, app_check, verified_at
        FROM surebackup_verifications ORDER BY verified_at DESC NULLS LAST LIMIT 200
    """):
        verifications.append({"kind": "surebackup", "ext_id": v.get("id"),
                              "subject": task_names.get(v.get("task_id")) or f"Tarefa {v.get('task_id')}",
                              "status": v.get("status"), "started_at": v.get("verified_at"),
                              "finished_at": v.get("verified_at"), "errors_found": None,
                              "summary": f"boot={v.get('boot_time_seconds')}s rede={v.get('network_check')} app={v.get('app_check')}"})

    restore_tests = _rows(cur, """
        SELECT id, repository_id, repository_name, engine, task_id, task_name, snapshot_id, snapshot_time, status,
               files_tested, files_ok, files_hash_verified, bytes_restored, duration_seconds, error_message,
               evidence_hash, details, triggered_by, started_at, completed_at
        FROM restore_tests WHERE started_at >= %s ORDER BY started_at DESC LIMIT 200
    """, (since - timedelta(days=60),))
    for t in restore_tests:
        if isinstance(t.get("details"), str):
            try:
                t["details"] = json.loads(t["details"])
            except ValueError:
                t["details"] = []
        verifications.append({"kind": "restore_test", "ext_id": t.get("id"),
                              "subject": t.get("repository_name") or f"Repositório {t.get('repository_id')}",
                              "status": "completed" if t.get("status") == "passed" else t.get("status"),
                              "started_at": t.get("started_at"), "finished_at": t.get("completed_at"),
                              "errors_found": max(0, int(t.get("files_tested") or 0) - int(t.get("files_ok") or 0)),
                              "summary": f"{t.get('files_ok') or 0}/{t.get('files_tested') or 0} arquivos conferidos, "
                                         f"{t.get('files_hash_verified') or 0} por hash, {t.get('duration_seconds') or 0}s"})

    failures = _rows(cur, """
        SELECT id, task_id, task_name, failure_reason, retry_count, max_retries, status, escalated,
               first_failed_at, last_retried_at, resolved_at
        FROM job_failure_log WHERE first_failed_at >= %s OR resolved_at IS NULL
        ORDER BY first_failed_at DESC LIMIT 300
    """, (since,))
    for f in failures:
        if f.get("failure_reason"):
            f["failure_reason"] = str(f["failure_reason"])[:1000]

    replication = _rows(cur, """
        SELECT id, name, source_repo_id, dest_type, mode, status, enabled, schedule_cron, last_run, total_bytes
        FROM replication_policies ORDER BY id
    """)
    for rp in replication:
        rp["source_repository_name"] = repo_names.get(rp.get("source_repo_id"))

    try:
        cur.close()
    except Exception:
        pass

    operation, immutability = {}, []
    try:
        from engines import operation_settings as _ops
        _d = _ops.load(force=True)
        operation = {"maintenance_windows": _d.get(_ops.KEY_WINDOWS) or [], "bandwidth": _d.get(_ops.KEY_BANDWIDTH) or {},
                     "central_policy": _d.get(_ops.KEY_POLICY)}
    except Exception as exc:
        logger.debug(f"[INVENTÁRIO] operação: {exc}")
    try:
        from engines import immutability as _imm
        immutability = [{"repo_id": r["id"], "name": r["name"], "type": r["type"], "engine": r["engine"],
                         "mode": r["policy"]["mode"], "days": r["policy"]["days"], "lock_mode": r["policy"]["lock_mode"],
                         "last_check": r["policy"].get("last_check"), "supported_modes": r["supported_modes"]}
                        for r in _imm.overview()]
    except Exception as exc:
        logger.debug(f"[INVENTÁRIO] imutabilidade: {exc}")

    return {
        "schema": 1,
        "collected_at": datetime.now().isoformat(),
        "window_days": days,
        "repositories": repos,
        "tasks": tasks,
        "task_executions": execs,
        "restores": restores,
        "verifications": verifications,
        "restore_tests": restore_tests,
        "operation": operation,
        "immutability": immutability,
        "job_failures": failures,
        "replication": replication,
        "volumes": _volumes(),
    }


def sanitize_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove campos sensíveis de linhas já coletadas (compatibilidade com a sync antiga)."""
    return [{k: v for k, v in (r or {}).items() if k not in SENSITIVE_KEYS} for r in (rows or [])]
