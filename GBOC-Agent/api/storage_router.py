#!/usr/bin/env python3
"""GBOC 13.2.0 - Storage Usage & Growth Monitor API Router"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from typing import Optional

router = APIRouter(prefix="/api/v1/storage", tags=["Storage Monitor"])

@router.get("/usage")
async def get_current_usage():
    """Retorna o uso atual de todos os repositórios ativos com dados reais do sistema de arquivos."""
    from engines.storage_monitor import collect_repository_sizes
    data = collect_repository_sizes()
    return JSONResponse({"status": "success", "repositories": data})

@router.get("/history")
async def get_history(days: int = 30, repository_id: Optional[str] = None):
    """Retorna o histórico de crescimento de armazenamento (até 90 dias)."""
    from engines.storage_monitor import get_storage_history
    history = get_storage_history(repository_id=repository_id, days=min(days, 90))
    return JSONResponse({"status": "success", "history": history, "days": days})

@router.get("/config")
async def get_config():
    """Retorna configuração atual de alertas de armazenamento."""
    from engines.storage_monitor import get_storage_config
    return JSONResponse({"status": "success", "config": get_storage_config()})

@router.post("/config")
async def save_config(request: Request):
    """Salva configuração de alertas de armazenamento (threshold GB, crescimento %, intervalo de scan)."""
    body = await request.json()
    from engines.storage_monitor import save_storage_config
    saved = save_storage_config(body)
    return JSONResponse({"status": "success", "config": saved})

@router.post("/scan")
async def trigger_scan():
    """Força um scan imediato dos tamanhos de repositório."""
    from engines.storage_monitor import collect_repository_sizes
    data = collect_repository_sizes()
    return JSONResponse({"status": "success", "scanned": len(data), "repositories": data})
