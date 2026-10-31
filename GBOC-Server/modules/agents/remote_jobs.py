"""
GBOC Server — Console remoto: jobs sobre a API do agente.

Cada chamada à API do agente vira um JOB persistido (tabela remote_jobs):
  * agente conectado  -> executa agora (WebSocket, com fallback HTTP do túnel);
  * agente offline    -> fica na FILA e é executada quando o agente reconectar;
  * operação longa    -> o cliente recebe o job_id e consulta o resultado depois (sem timeout de HTTP);
  * jobs na fila há mais de QUEUE_TTL não são executados (expirados), para não disparar ações antigas.

Rotas:
  POST   /api/v1/agents/{id}/remote/jobs              — cria o job (body: method, path, query, body, timeout)
  GET    /api/v1/agents/{id}/remote/jobs              — lista os jobs do agente (?status=&limit=)
  GET    /api/v1/agents/{id}/remote/jobs/{job_id}     — status e resultado
  DELETE /api/v1/agents/{id}/remote/jobs/{job_id}     — cancela um job ainda na fila

Mesmas regras do túnel: só caminhos api/..., bloqueio de desligamento, escrita só para admin/operator, auditoria.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("gboc_remote_jobs")
router = APIRouter(prefix="/api/v1/agents", tags=["Console remoto"])

QUEUE_TTL = timedelta(hours=24)
MAX_RESULT_CHARS = 1_000_000
PREVIEW_CHARS = 200_000
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_schema_ready = False


def _db():
    from database import db_manager
    return db_manager


def _ensure_table() -> None:
    global _schema_ready
    if _schema_ready:
        return
    dbm = _db()
    conn = dbm.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS remote_jobs (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                query JSONB,
                body JSONB,
                status TEXT NOT NULL,
                created_by TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                http_status INTEGER,
                channel TEXT,
                result JSONB,
                truncated BOOLEAN NOT NULL DEFAULT FALSE,
                error TEXT,
                timeout DOUBLE PRECISION
            )""")
        cur.execute("ALTER TABLE remote_jobs ADD COLUMN IF NOT EXISTS timeout DOUBLE PRECISION")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_remote_jobs_agent_status ON remote_jobs (agent_id, status, created_at)")
        conn.commit()
        cur.close()
        _schema_ready = True
    finally:
        dbm.release_connection(conn)


def _run_sql(sql: str, params: tuple = (), fetch: Optional[str] = None):
    """fetch: None (sem retorno), 'one' ou 'all'. Retorna linhas como dict."""
    from psycopg2.extras import RealDictCursor
    _ensure_table()
    dbm = _db()
    conn = dbm.get_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        out = None
        if fetch == "one":
            r = cur.fetchone()
            out = dict(r) if r else None
        elif fetch == "all":
            out = [dict(r) for r in cur.fetchall()]
        conn.commit()
        cur.close()
        return out
    finally:
        dbm.release_connection(conn)


def _jsonable(rows):
    if isinstance(rows, list):
        return [_jsonable(r) for r in rows]
    if isinstance(rows, dict):
        return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in rows.items()}
    return rows


def _manager():
    from modules.agents.remote_mgmt import _manager as _rm_manager
    return _rm_manager()


def _is_connected(agent_id: str) -> bool:
    try:
        return agent_id in _manager().active_connections
    except Exception:
        return False


def _set_fields(job_id: str, **fields) -> None:
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        if k in ("query", "body", "result") and v is not None:
            v = json.dumps(v, default=str, ensure_ascii=False)
        cols.append(f"{k} = %s")
        vals.append(v)
    _run_sql(f"UPDATE remote_jobs SET {', '.join(cols)} WHERE id = %s", tuple(vals) + (job_id,))


def _validate(method: str, path: str, role: str) -> Optional[str]:
    from modules.agents.remote_mgmt import _WRITE_ROLES, _BLOCKED
    if method not in _METHODS:
        return "Método não permitido"
    path = path.lstrip("/")
    if not path.startswith("api/") or ".." in path:
        return "Somente rotas da API do agente (api/...)"
    if path.rstrip("/") in _BLOCKED:
        return "Desligamento remoto do agente não é permitido."
    if method != "GET" and role not in _WRITE_ROLES:
        return "Seu perfil não pode executar ações remotas (requer admin ou operator)."
    return None


async def _execute(job_id: str) -> None:
    """Executa um job pelo túnel. Se o agente não responder, o job volta para a fila."""
    from modules.agents.remote_mgmt import agent_call
    row = await asyncio.to_thread(_run_sql, "SELECT * FROM remote_jobs WHERE id = %s", (job_id,), "one")
    if not row or row["status"] in ("done", "error", "cancelled", "expired"):
        return
    query = row.get("query") or None
    body = row.get("body")
    now = datetime.now(timezone.utc)
    await asyncio.to_thread(_set_fields, job_id, status="running", started_at=now)
    try:
        res = await agent_call(row["agent_id"], row["method"], row["path"], query=query, body=body,
                               timeout=float(row.get("timeout") or 120.0))
    except Exception as e:
        res = {"status_code": 502, "channel": None, "body": {"message": str(e)}}
    if res.get("channel") is None:
        # agente inalcançável agora: continua na fila para a próxima reconexão
        await asyncio.to_thread(_set_fields, job_id, status="queued", error="Agente inacessível; aguardando reconexão")
        return
    payload = res.get("body")
    truncated = False
    text = json.dumps(payload, default=str, ensure_ascii=False) if not isinstance(payload, str) else payload
    if len(text) > MAX_RESULT_CHARS:
        truncated = True
        payload = {"preview": text[:PREVIEW_CHARS], "original_chars": len(text)}
    ok = int(res.get("status_code") or 500) < 400
    await asyncio.to_thread(
        _set_fields, job_id, status="done" if ok else "error", finished_at=datetime.now(timezone.utc),
        http_status=int(res.get("status_code") or 500), channel=res.get("channel"), result=payload,
        truncated=truncated, error=None if ok else str((payload or {}).get("message") if isinstance(payload, dict) else payload)[:2000])


def _spawn(job_id: str) -> None:
    try:
        asyncio.get_running_loop().create_task(_execute(job_id))
    except RuntimeError:
        logger.warning("Sem event loop ativo para executar o job %s", job_id)


async def flush_queue(agent_id: str) -> int:
    """Chamado quando o agente (re)conecta: executa os jobs enfileirados, em ordem de criação."""
    now = datetime.now(timezone.utc)
    rows = await asyncio.to_thread(
        _run_sql, "SELECT id, created_at FROM remote_jobs WHERE agent_id = %s AND status = 'queued' ORDER BY created_at",
        (agent_id,), "all")
    ran = 0
    for r in rows or []:
        if now - r["created_at"] > QUEUE_TTL:
            await asyncio.to_thread(_set_fields, r["id"], status="expired", error="Expirado na fila (mais de 24 h)")
            continue
        await _execute(r["id"])
        ran += 1
    if ran:
        logger.info("Fila remota do agente %s: %d job(s) executado(s)", agent_id, ran)
    return ran


def _audit(request: Request, agent_id: str, action: str, ok: bool, details: str) -> None:
    from modules.agents.remote_mgmt import _audit as _rm_audit
    _rm_audit(request, agent_id, action, ok, details)


def _user(request: Request) -> str:
    return str(((getattr(request.state, "user", None) or {}).get("username")) or "")


def _role(request: Request) -> str:
    return str(((getattr(request.state, "user", None) or {}).get("role")) or "").lower()


@router.post("/{agent_id}/remote/jobs")
async def create_job(agent_id: str, request: Request):
    from modules.agents.remote_mgmt import _agent_row
    try:
        req = json.loads((await request.body()).decode("utf-8") or "{}")
    except Exception:
        return JSONResponse({"status": "error", "message": "Corpo JSON inválido"}, status_code=400)
    method = str(req.get("method") or "GET").upper()
    path = str(req.get("path") or "")
    err = _validate(method, path, _role(request))
    if err:
        return JSONResponse({"status": "error", "message": err}, status_code=403 if "perfil" in err or "Desligamento" in err else 400)
    row = await asyncio.to_thread(_agent_row, agent_id)
    if not row:
        return JSONResponse({"status": "error", "message": "Agente não encontrado"}, status_code=404)
    job_id = uuid.uuid4().hex
    timeout = max(10.0, min(float(req.get("timeout") or 120), 1800.0))
    await asyncio.to_thread(
        _run_sql,
        """INSERT INTO remote_jobs (id, agent_id, method, path, query, body, status, created_by, timeout)
           VALUES (%s, %s, %s, %s, %s, %s, 'queued', %s, %s)""",
        (job_id, agent_id, method, path.lstrip("/"),
         json.dumps(req.get("query") or {}, default=str), json.dumps(req.get("body"), default=str) if req.get("body") is not None else None,
         _user(request), timeout))
    connected = _is_connected(agent_id)
    if connected:
        _spawn(job_id)
    _audit(request, agent_id, f"JOB {method} /{path.lstrip('/')}", True, f"job={job_id} agora={connected}")
    return JSONResponse({"status": "success", "job_id": job_id,
                         "job_status": "running" if connected else "queued",
                         "message": "Executando agora." if connected else
                         "Agente offline: o job ficou na fila e será executado na reconexão (até 24 h)."},
                        status_code=202)


@router.get("/{agent_id}/remote/jobs")
async def list_jobs(agent_id: str, status: Optional[str] = None, limit: int = 50):
    limit = max(1, min(int(limit), 200))
    if status:
        rows = await asyncio.to_thread(
            _run_sql, "SELECT id, method, path, status, created_by, created_at, finished_at, http_status, channel, error "
                      "FROM remote_jobs WHERE agent_id = %s AND status = %s ORDER BY created_at DESC LIMIT %s",
            (agent_id, status, limit), "all")
    else:
        rows = await asyncio.to_thread(
            _run_sql, "SELECT id, method, path, status, created_by, created_at, finished_at, http_status, channel, error "
                      "FROM remote_jobs WHERE agent_id = %s ORDER BY created_at DESC LIMIT %s",
            (agent_id, limit), "all")
    return {"status": "success", "connected": _is_connected(agent_id), "jobs": _jsonable(rows or [])}


@router.get("/{agent_id}/remote/jobs/{job_id}")
async def get_job(agent_id: str, job_id: str):
    row = await asyncio.to_thread(_run_sql, "SELECT * FROM remote_jobs WHERE id = %s AND agent_id = %s",
                                  (job_id, agent_id), "one")
    if not row:
        return JSONResponse({"status": "error", "message": "Job não encontrado"}, status_code=404)
    return {"status": "success", "job": _jsonable(row)}


@router.delete("/{agent_id}/remote/jobs/{job_id}")
async def cancel_job(agent_id: str, job_id: str, request: Request):
    if _role(request) not in ("admin", "superadmin", "administrator", "operator"):
        return JSONResponse({"status": "error", "message": "Requer admin ou operator."}, status_code=403)
    row = await asyncio.to_thread(
        _run_sql, "UPDATE remote_jobs SET status = 'cancelled', finished_at = NOW() "
                  "WHERE id = %s AND agent_id = %s AND status = 'queued' RETURNING id",
        (job_id, agent_id), "one")
    if not row:
        return JSONResponse({"status": "error", "message": "Só é possível cancelar jobs na fila."}, status_code=409)
    _audit(request, agent_id, "JOB CANCELADO", True, f"job={job_id}")
    return {"status": "success", "message": "Job cancelado"}
