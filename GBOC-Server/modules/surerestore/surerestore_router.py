# ==============================================================================
# GBOC System v14.6.0 Enterprise Edition
# Module: SureRestore Sandbox Verification Router
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import logging
from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("gboc_surerestore_module")
router = APIRouter(prefix="/api/v1/surerestore", tags=["SureRestore Sandbox"])


@router.post("/verify")
async def run_surerestore_verification(request: Request):
    """
    A verificação SureRestore precisa rodar NO AGENTE (onde estão o backup e o Hyper-V),
    que pode estar em outra máquina. O Servidor Central não executa nem simula o boot.

    Enquanto não houver credencial servidor→agente para disparar o Virtual Lab remotamente,
    este endpoint retorna 501 com a orientação, em vez de um resultado presumido.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    agent_id = (body or {}).get("agent_id")
    return JSONResponse(
        {
            "status": "unavailable",
            "overall_state": "Inconclusivo",
            "agent_id": agent_id,
            "error": {
                "code": "SURERESTORE_RUNS_ON_AGENT",
                "message": ("A verificação de boot em sandbox é executada no próprio agente "
                            "(Disaster Recovery > Laboratório Isolado no painel do agente). "
                            "O disparo remoto pelo Servidor Central ainda não está disponível."),
            },
            "timestamp": datetime.now().isoformat(),
        },
        status_code=501,
    )
