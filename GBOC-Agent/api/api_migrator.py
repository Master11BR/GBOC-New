# GBOC Agent v14.0.0 Full Stable Enterprise Edition
# Module: API Router do Migrador Universal de Motores de Backup (api_migrator.py)

import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from engines.engine_migrator import migrator_engine

logger = logging.getLogger("gboc_api_migrator")
router = APIRouter(prefix="/api/v1/migrator", tags=["Engine Migrator"])

@router.get("/discover")
async def discover_engines_endpoint():
    """Varre e descobre tarefas, repositórios e senhas de motores legados/externos no agente."""
    try:
        data = migrator_engine.discover_engines()
        return JSONResponse(data)
    except Exception as e:
        logger.error(f"❌ Erro ao descobrir motores no agente: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/execute")
async def execute_migration_endpoint(request: Request):
    """Executa a conversão automatizada de tarefas e repositórios para o Motor Nativo GBOC (FastCDC v4)."""
    try:
        body = await request.json()
        selected_tasks = body.get("selected_task_ids", [])
        selected_repos = body.get("selected_repo_ids", [])
        target_params = body.get("target_params", {})

        result = migrator_engine.execute_migration(selected_tasks, selected_repos, target_params)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"❌ Erro ao executar migração para motor nativo: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
