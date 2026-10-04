# GBOC System v14.6.0 Full Stable Enterprise Edition
# Module: Engine Migration APIRouter (engine_migration_router.py)
# 1 Módulo = 1 Diretório em modules/engine_migration/

import os
import json
import asyncio
import logging
import requests
import urllib3
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from modules.telemetry.telemetry_engine import telemetry

logger = logging.getLogger("gboc_engine_migration_router")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

router = APIRouter(prefix="/api/v1/migration", tags=["Engine Migration"])

def _agent_call(method: str, agent_id: str, path: str, body: Dict[str, Any] = None, timeout: float = 30.0):
    """Chama o Agente remoto (IP do heartbeat + chave de pareamento). Tenta HTTP e HTTPS."""
    from modules.agents.agent_pairing import resolve_agent_address, agent_headers
    addr = resolve_agent_address(agent_id)
    if not addr:
        raise HTTPException(status_code=404, detail=f"Agente '{agent_id}' não encontrado ou sem IP registrado")
    last = None
    for scheme in ("http", "https"):
        url = f"{scheme}://{addr['ip']}:{addr['port']}{path}"
        try:
            res = requests.request(method, url, json=body, headers=agent_headers(), timeout=timeout, verify=False)
        except requests.RequestException as exc:
            last = str(exc)
            continue
        if res.status_code == 401:
            raise HTTPException(status_code=502, detail="O Agente recusou a chave de pareamento. Configure a chave do Server no Agente.")
        if res.status_code == 404:
            raise HTTPException(status_code=502, detail="Agente sem suporte à migração de motores — atualize o GBOC Agent.")
        try:
            data = res.json()
        except ValueError:
            data = {"detail": res.text[:300]}
        if res.status_code >= 400:
            raise HTTPException(status_code=502, detail=data.get("detail") or data.get("message") or f"Agente respondeu HTTP {res.status_code}")
        return data
    raise HTTPException(status_code=503, detail=f"Agente '{agent_id}' inacessível: {last}")


async def _agent_call_async(method: str, agent_id: str, path: str, body: Dict[str, Any] = None, timeout: float = 60.0):
    """Mesma semântica de _agent_call, usando o canal do Gerenciamento Remoto (WebSocket do agente
    quando conectado — funciona atrás de NAT — ou HTTP direto)."""
    from modules.agents.remote_mgmt import agent_call
    res = await agent_call(agent_id, method, path, body=body, timeout=timeout)
    code, data = res["status_code"], res["body"]
    if not isinstance(data, dict):
        data = {"detail": str(data)[:300]}
    if code == 401:
        raise HTTPException(status_code=502, detail="O Agente recusou a chave de pareamento. Configure a chave do Server no Agente.")
    if code == 404:
        raise HTTPException(status_code=502, detail="Agente sem suporte à migração de motores — atualize o GBOC Agent.")
    if code >= 400:
        raise HTTPException(status_code=502 if code != 503 else 503,
                            detail=data.get("detail") or data.get("message") or f"Agente respondeu HTTP {code}")
    return data


@router.get("/agents")
async def migration_agents():
    """Agentes disponíveis para migração (a migração sempre ocorre no Agente dono das tarefas)."""
    from database import db_manager
    conn = db_manager.get_connection()
    if conn is None:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível")
    try:
        cur = conn.cursor()
        cur.execute("SELECT agent_id, hostname, ip_address, status FROM agents ORDER BY hostname")
        rows = [{"agent_id": r[0], "hostname": r[1] or r[0], "ip_address": r[2], "status": r[3]} for r in cur.fetchall()]
        cur.close()
        return {"status": "success", "agents": rows}
    finally:
        db_manager.release_connection(conn)


@router.get("/discover")
async def server_discover_migration_engines(agent_id: str = ""):
    """Descoberta real no Agente selecionado: tarefas, repositórios e motores do banco do Agente."""
    with telemetry.record_span("migration_discover", {"agent_id": agent_id}):
        if not agent_id or agent_id == "local":
            raise HTTPException(status_code=400, detail="Selecione um agente: as tarefas de backup ficam no Agente, não no Servidor Central.")
        data = await _agent_call_async("GET", agent_id, "/api/v1/migrator/discover")
        data["agent_id"] = agent_id
        return JSONResponse(data)


@router.post("/execute")
async def server_execute_migration(request: Request):
    """Executa a migração no Agente selecionado (troca o motor das tarefas para o Motor Nativo GBOC)."""
    with telemetry.record_span("migration_execute"):
        body = await request.json()
        agent_id = body.get("agent_id") or ""
        if not agent_id or agent_id == "local":
            raise HTTPException(status_code=400, detail="Selecione um agente.")
        user = getattr(request.state, "user", None) or {}
        if (user.get("role") or "").lower() not in ("admin", "superadmin", "administrator", "operator"):
            raise HTTPException(status_code=403, detail="Seu perfil não pode executar migrações (requer admin ou operator).")
        params = dict(body.get("target_params") or {})
        params["requested_by"] = user.get("username") or "gboc-server"
        payload = {
            "selected_task_ids": body.get("selected_task_ids") or [],
            "selected_repo_ids": body.get("selected_repo_ids") or [],
            "target_params": params,
        }
        data = await _agent_call_async("POST", agent_id, "/api/v1/migrator/execute", payload, 120.0)
        logger.info(f"Migração de motores no agente {agent_id}: {data.get('message')}")
        return JSONResponse(data)
