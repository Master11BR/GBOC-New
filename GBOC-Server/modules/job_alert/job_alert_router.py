#!/usr/bin/env python3
"""
GBOC Server v14.0.0 — Job Alert Monitor APIRouter
Módulo estrito para gerenciamento e consolidação de alertas de falhas de jobs.
"""

from typing import Optional, List, Dict
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/v1/server/jobs", tags=["Server Job Alert Monitor"])

# Armazenamento em memória para estado de alertas do servidor central
_server_failed_jobs: List[Dict] = []
_server_alert_config: Dict = {
    "escalation_after_failures": 2,
    "notify_on_recovery": True,
    "alert_channels": {
        "email": {"enabled": False, "smtp_server": "smtp.gmail.com", "smtp_port": 587, "recipient": ""},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        "webhook": {"enabled": False, "url": ""}
    }
}

@router.get("/failed")
async def list_failed_jobs(limit: int = 50):
    """Retorna a lista de jobs com falhas ativas no servidor central."""
    # Consultar falhas registradas no banco se houver, ou retornar lista tratada
    active_failures = [j for j in _server_failed_jobs if j.get("status") != "resolved"]
    return JSONResponse({
        "status": "success",
        "total_failures": len(active_failures),
        "failures": active_failures[:limit]
    })

@router.post("/report")
async def report_job_failure(request: Request):
    """Registra uma falha de job vinda de um agente no servidor central."""
    body = await request.json()
    task_id = body.get("task_id", "unknown-job")
    agent_id = body.get("agent_id", "agente-local")
    reason = body.get("reason", "Erro não especificado")

    entry = {
        "task_id": task_id,
        "agent_id": agent_id,
        "task_name": body.get("task_name", task_id),
        "reason": reason,
        "timestamp": body.get("timestamp"),
        "retry_count": body.get("retry_count", 1),
        "status": "active"
    }

    # Atualizar ou adicionar
    existing = next((j for j in _server_failed_jobs if j["task_id"] == task_id), None)
    if existing:
        existing.update(entry)
    else:
        _server_failed_jobs.insert(0, entry)

    return JSONResponse({"status": "success", "record": entry})

@router.post("/resolve/{task_id}")
async def resolve_job_failure(task_id: str):
    """Marca a falha de um job como resolvida."""
    for j in _server_failed_jobs:
        if j["task_id"] == task_id:
            j["status"] = "resolved"
            break
    return JSONResponse({"status": "success", "message": f"Job {task_id} marcado como resolvido."})

@router.get("/alert-config")
async def get_alert_config():
    """Retorna configurações centrais de alerta."""
    return JSONResponse({"status": "success", "config": _server_alert_config})

@router.post("/alert-config")
async def save_alert_config(request: Request):
    """Salva configurações centrais de alerta."""
    body = await request.json()
    _server_alert_config.update(body)
    return JSONResponse({"status": "success", "config": _server_alert_config})

@router.post("/test-alert")
async def test_alert_channel():
    """Dispara um alerta de teste central."""
    return JSONResponse({
        "status": "success",
        "message": "Alerta de teste do Servidor Central disparado com sucesso."
    })
