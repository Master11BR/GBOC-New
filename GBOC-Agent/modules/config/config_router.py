# GBOC System v13.2.0 Enterprise Edition
# Module: Agent Config Router

import logging
from fastapi import APIRouter

logger = logging.getLogger("gboc_agent_config")
router = APIRouter(prefix="/api/v1/agent/config", tags=["Agent Config"])

@router.get("")
async def get_agent_config():
    """Retorna as configurações locais do agente."""
    return {
        "status": "success",
        "agent_version": "v13.2.0 Enterprise",
        "server_url": "http://127.0.0.1:8000",
        "sync_interval_seconds": 30
    }
