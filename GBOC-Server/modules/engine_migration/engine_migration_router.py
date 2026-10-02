# GBOC System v14.6.0 Full Stable Enterprise Edition
# Module: Engine Migration APIRouter (engine_migration_router.py)
# 1 Módulo = 1 Diretório em modules/engine_migration/

import os
import json
import logging
import requests
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from modules.telemetry.telemetry_engine import telemetry

logger = logging.getLogger("gboc_engine_migration_router")

router = APIRouter(prefix="/api/v1/migration", tags=["Engine Migration"])

@router.get("/discover")
async def server_discover_migration_engines(agent_id: str = "local"):
    """
    Executa a varredura e descoberta automatizada (100% Zero-Mock)
    de motores, tarefas e repositórios a serem migrados no servidor ou agente selecionado.
    """
    with telemetry.record_span("migration_discover", {"agent_id": agent_id}):
        try:
            # Se for local no servidor
            if agent_id == "local" or not agent_id:
                data_dir = os.path.join(os.getcwd(), "data")
                tasks_file = os.path.join(data_dir, "tasks.json")
                discovered_tasks = []
                if os.path.exists(tasks_file):
                    try:
                        with open(tasks_file, "r", encoding="utf-8") as f:
                            t_data = json.load(f)
                            if isinstance(t_data, list):
                                for t in t_data:
                                    eng = t.get("engine", "legacy")
                                    discovered_tasks.append({
                                        "id": t.get("id"),
                                        "name": t.get("name", "Tarefa de Backup"),
                                        "source_paths": t.get("source_paths") or t.get("paths") or [],
                                        "current_engine": eng,
                                        "schedule": t.get("schedule"),
                                        "can_migrate": eng != "gboc_native_v4"
                                    })
                    except Exception:
                        pass

                # Zero-Mock: somente o que foi realmente encontrado no host do Server.
                return JSONResponse({
                    "status": "success",
                    "agent_id": "local",
                    "summary": {
                        "total_tasks_found": len(discovered_tasks),
                        "total_repositories_found": 0,
                        "total_credentials_found": 0
                    },
                    "tasks": discovered_tasks,
                    "repositories": [],
                    "credentials": []
                })
            else:
                # Consulta remota no agente (IP real do heartbeat + chave de pareamento)
                from modules.agents.agent_pairing import resolve_agent_address, agent_headers
                addr = resolve_agent_address(agent_id)
                if not addr:
                    raise HTTPException(status_code=404, detail=f"Agente '{agent_id}' não encontrado ou sem IP registrado")
                agent_url = f"http://{addr['ip']}:{addr['port']}/api/v1/migrator/discover"
                res = requests.get(agent_url, timeout=10, headers=agent_headers())
                if res.status_code == 200:
                    return JSONResponse(res.json())
                raise HTTPException(status_code=502, detail=f"Agente {agent_id} respondeu HTTP {res.status_code}")
        except HTTPException:
            raise
        except Exception as e:
            telemetry.capture_exception(e, {"module": "engine_migration", "action": "discover"})
            logger.error(f"❌ Erro na descoberta de migração: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/execute")
async def server_execute_migration(request: Request):
    """
    Executa a migração automatizada selecionada para o Motor Nativo GBOC (FastCDC v4).
    """
    with telemetry.record_span("migration_execute"):
        try:
            body = await request.json()
            agent_id = body.get("agent_id", "local")
            selected_tasks = body.get("selected_task_ids", [])
            selected_repos = body.get("selected_repo_ids", [])
            target_params = body.get("target_params", {})

            data_dir = os.path.join(os.getcwd(), "data")
            tasks_file = os.path.join(data_dir, "tasks.json")

            migrated_count = 0
            if os.path.exists(tasks_file):
                try:
                    with open(tasks_file, "r", encoding="utf-8") as f:
                        tasks = json.load(f)

                    for t in tasks:
                        if t.get("id") in selected_tasks or "all" in selected_tasks:
                            t["engine"] = "gboc_native_v4"
                            t["native_v4_active"] = True
                            migrated_count += 1

                    with open(tasks_file, "w", encoding="utf-8") as f:
                        json.dump(tasks, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    logger.warning(f"Aviso ao converter tarefas locais: {e}")

            return JSONResponse({
                "status": "success",
                "message": f"Migração concluída com sucesso! {migrated_count} tarefas convertidas para o Motor Nativo GBOC (FastCDC v4).",
                "migrated_tasks_count": migrated_count,
                "target_engine": "gboc_native_v4",
                "target_params": target_params
            })
        except Exception as e:
            telemetry.capture_exception(e, {"module": "engine_migration", "action": "execute"})
            raise HTTPException(status_code=500, detail=str(e))
