#!/usr/bin/env python3
"""
GBOC Server — Central de Jobs com Falha (agentes + o próprio servidor).

As falhas vêm do banco (modules/job_alert/failures.py) — antes vinham de uma lista em memória que
nenhum agente alimentava e a tela mostrava sempre 0.

  GET  /api/v1/server/jobs/failed?days=&start=&end=&agent_id=&tenant_id=&origin=agent|server&only_active=
  GET  /api/v1/server/jobs/history?days=&agent_id=&tenant_id=
  POST /api/v1/server/jobs/resolve/{key}      reconhecer (some das ativas até uma falha mais nova)
  POST /api/v1/server/jobs/unresolve/{key}
  POST /api/v1/server/jobs/report             (compatibilidade) agente informa falha → agent_job_failures
  POST /api/v1/server/jobs/test-alert         envia um alerta de teste pelos canais dos Alertas proativos
"""
import asyncio
import zlib
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from modules.job_alert import failures as fl

router = APIRouter(prefix="/api/v1/server/jobs", tags=["Server Job Alert Monitor"])

_server_alert_config: Dict = {
    "escalation_after_failures": 2,
    "notify_on_recovery": True,
}


def _user(request: Request) -> str:
    return str((getattr(request.state, "user", None) or {}).get("username") or "")


def _require_write(request: Request) -> None:
    role = str((getattr(request.state, "user", None) or {}).get("role") or "").lower()
    if role and role not in ("admin", "superadmin", "administrator", "operator"):
        raise HTTPException(403, "Seu perfil não pode reconhecer falhas")


@router.get("/failed")
async def list_failed_jobs(days: int = Query(30, ge=0, le=3650), start: Optional[str] = None, end: Optional[str] = None,
                           agent_id: Optional[str] = None, tenant_id: Optional[str] = None,
                           origin: Optional[str] = Query(None, pattern="^(agent|server)?$"),
                           only_active: bool = False, limit: int = Query(1000, ge=1, le=5000)):
    """Falhas reais de agentes e do servidor: ativas primeiro, depois recuperadas/reconhecidas do período."""
    try:
        data = await asyncio.to_thread(fl.collect, days, start, end, agent_id, tenant_id, origin, not only_active)
    except ValueError as e:
        raise HTTPException(400, str(e))
    items = data["failures"][:limit]
    return JSONResponse({"status": "success", "total_failures": data["kpis"]["active"], "kpis": data["kpis"],
                         "period": data["period"], "failures": items}, )


@router.get("/history")
async def failed_history(days: int = Query(30, ge=0, le=3650), agent_id: Optional[str] = None, tenant_id: Optional[str] = None,
                         limit: int = Query(500, ge=1, le=5000)):
    rows = await asyncio.to_thread(fl.history, days, agent_id, tenant_id, limit)
    return JSONResponse({"status": "success", "executions": rows})


@router.post("/resolve/{key:path}")
async def resolve_job_failure(key: str, request: Request):
    """Reconhece a falha: sai da lista de ativas até acontecer uma falha mais nova do mesmo item."""
    _require_write(request)
    note = None
    try:
        note = (await request.json() or {}).get("note")
    except Exception:
        pass
    await asyncio.to_thread(fl.acknowledge, key, _user(request), note)
    return JSONResponse({"status": "success", "message": "Falha reconhecida."})


@router.post("/unresolve/{key:path}")
async def unresolve_job_failure(key: str, request: Request):
    _require_write(request)
    await asyncio.to_thread(fl.unacknowledge, key)
    return JSONResponse({"status": "success"})


@router.post("/report")
async def report_job_failure(request: Request):
    """Compatibilidade: agente informa uma falha de job (gravada em agent_job_failures)."""
    body = await request.json()
    agent_id = body.get("agent_id")
    if not agent_id:
        raise HTTPException(400, "agent_id obrigatório")
    from modules.reports.report_schedules import _exec
    ext = zlib.crc32(f"{agent_id}:{body.get('task_id')}".encode()) % 2_000_000_000
    await asyncio.to_thread(_exec, """
        INSERT INTO agent_job_failures (agent_id, ext_id, task_id, task_name, failure_reason, retry_count, max_retries, status, escalated,
                                        first_failed_at, last_retried_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'failed', FALSE, %s, %s)
        ON CONFLICT (agent_id, ext_id) DO UPDATE SET failure_reason = EXCLUDED.failure_reason, retry_count = EXCLUDED.retry_count,
            last_retried_at = EXCLUDED.last_retried_at, status = 'failed', synced_at = LOCALTIMESTAMP""",
                            (agent_id, ext, str(body.get("task_id") or ""), body.get("task_name") or body.get("task_id"),
                             body.get("reason") or "Erro não especificado", int(body.get("retry_count") or 1),
                             int(body.get("max_retries") or 3), body.get("timestamp") or datetime.now(), datetime.now()), False)
    return JSONResponse({"status": "success"})


@router.get("/alert-config")
async def get_alert_config():
    return JSONResponse({"status": "success", "config": _server_alert_config,
                         "note": "Canais e regras de envio ficam em Alertas e Falhas > Alertas proativos > Regras e canais."})


@router.post("/alert-config")
async def save_alert_config(request: Request):
    body = await request.json()
    _server_alert_config.update({k: v for k, v in body.items() if k in _server_alert_config})
    return JSONResponse({"status": "success", "config": _server_alert_config})


@router.post("/test-alert")
async def test_alert_channel(request: Request):
    """Envia um alerta de teste de verdade pelo canal configurado nos Alertas proativos (antes só respondia sucesso)."""
    try:
        from modules.alerts import proactive_alerts as pa
    except Exception as e:
        raise HTTPException(503, f"Módulo de alertas proativos não carregado: {e}")
    try:
        b = await request.json() or {}
    except Exception:
        b = {}
    settings = await asyncio.to_thread(pa.get_settings) if hasattr(pa, "get_settings") else {}
    ch = b.get("channel") or next((c for c in ("email", "teams", "webhook") if (settings or {}).get(f"{c}_enabled")), "email")
    sample = [{"id": 0, "severity": "warning", "status": "open", "title": "Mensagem de teste do GBOC Server (Jobs com Falha)",
               "message": "Se você recebeu esta mensagem, o canal de alertas está funcionando.",
               "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M"), "report_code": "—"}]
    res = await asyncio.to_thread(pa._send_channels, [("Teste", sample)], {ch}, "[GBOC] Teste de alertas")
    if not str(res.get(ch, "")).startswith("enviado"):
        raise HTTPException(502, f"Falha no canal {ch}: {res.get(ch)}")
    return JSONResponse({"status": "success", "message": f"Alerta de teste enviado por {ch}.", "result": res})
