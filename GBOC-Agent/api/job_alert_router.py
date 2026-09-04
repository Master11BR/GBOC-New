#!/usr/bin/env python3
"""GBOC 14.0.0 - Job Alert Monitor API Router"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from typing import Optional

router = APIRouter(prefix="/api/v1/jobs", tags=["Job Alert Monitor"])

@router.get("/failed")
async def list_failed_jobs(limit: int = 50):
    """Retorna a lista de jobs com falhas ativas e histórico."""
    from engines.job_alert_monitor import get_failed_jobs
    return JSONResponse({"status": "success", "failures": get_failed_jobs(limit)})

@router.post("/failure")
async def report_job_failure(request: Request):
    """Registra uma nova falha de job e dispara alertas nos canais configurados."""
    body = await request.json()
    task_id = body.get("task_id", "unknown")
    task_name = body.get("task_name", task_id)
    execution_id = body.get("execution_id", "")
    reason = body.get("reason", "Erro não especificado")

    from engines.job_alert_monitor import record_job_failure, dispatch_job_failure_alert, load_alert_config
    rec = record_job_failure(task_id, task_name, execution_id, reason)
    cfg = load_alert_config()
    escalated = rec["retry_count"] >= cfg.get("escalation_after_failures", 2)
    dispatch_job_failure_alert(task_id, task_name, reason, rec["retry_count"], escalated)
    return JSONResponse({"status": "success", "record": rec, "escalated": escalated})

@router.post("/resolve/{task_id}")
async def resolve_job(task_id: str):
    """Marca uma falha de job como resolvida."""
    from engines.job_alert_monitor import resolve_job_failure
    resolve_job_failure(task_id)
    return JSONResponse({"status": "success", "message": f"Job {task_id} marcado como resolvido"})

@router.get("/alert-config")
async def get_alert_config():
    """Retorna configurações de alerta."""
    from engines.job_alert_monitor import load_alert_config
    cfg = load_alert_config()
    # Mask passwords
    if cfg.get("alert_channels", {}).get("email", {}).get("smtp_pass"):
        cfg["alert_channels"]["email"]["smtp_pass"] = "***"
    if cfg.get("alert_channels", {}).get("telegram", {}).get("bot_token"):
        tok = cfg["alert_channels"]["telegram"]["bot_token"]
        cfg["alert_channels"]["telegram"]["bot_token"] = tok[:6] + "..." if len(tok) > 6 else "***"
    return JSONResponse({"status": "success", "config": cfg})

@router.post("/alert-config")
async def save_alert_config(request: Request):
    """Atualiza configurações de alerta (canais, retries, escalação)."""
    body = await request.json()
    from engines.job_alert_monitor import save_alert_config
    saved = save_alert_config(body)
    return JSONResponse({"status": "success", "config": saved})

@router.post("/test-alert")
async def test_alert_channel(request: Request):
    """Dispara um alerta de teste em todos os canais configurados."""
    from engines.job_alert_monitor import dispatch_job_failure_alert
    dispatch_job_failure_alert(
        task_id="test-job-001",
        task_name="Tarefa de Teste",
        reason="Este é um alerta de TESTE do GBOC Copilot — canal funcionando corretamente.",
        retry_count=0,
        escalated=False
    )
    return JSONResponse({"status": "success", "message": "Alerta de teste enviado para todos os canais ativos"})
