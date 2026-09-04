# GBOC System v14.0.0 Enterprise Edition
# Module: Preemptive Alerts Router

import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("gboc_alerts_module")
router = APIRouter(prefix="/api/v1/server/alerts", tags=["Alertas"])

@router.get("/overview")
async def get_alerts_overview():
    """Retorna a lista de alertas preemptivos ativos."""
    return JSONResponse({
        "status": "success",
        "alerts": []
    })
