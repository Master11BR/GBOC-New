# ==============================================================================
# GBOC System v14.7.3 Enterprise Edition
# Module: AI Copilot Assistant Router (API v2 - Agent)
# ==============================================================================

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.ai_api import ConfigRequest, build_node_diagnosis, require_ai_user
from modules.v2.envelope import build_v2_response

logger = logging.getLogger("gboc_agent_v2_ai")
router = APIRouter(prefix="/ai", tags=["AI Copilot v2"])


def _elapsed(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)


def _error(t0: float, code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        build_v2_response(success=False, error={"code": code, "message": message}, execution_time_ms=_elapsed(t0)),
        status_code=status_code,
    )


class QueryRequestV2(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000, description="Prompt ou pergunta para a IA")
    provider: Optional[str] = Field(None, description="Provedor específico ou override")


@router.post("/query")
async def chat_with_ai_v2(body: QueryRequestV2, request: Request):
    """Envia pergunta para o GBOC Copilot (padrão v2)."""
    t0 = time.perf_counter()
    require_ai_user(request)
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="O prompt não pode ser vazio")
    try:
        from engines.ai_assistant import query_ai_assistant
        result = await run_in_threadpool(query_ai_assistant, body.prompt, body.provider)
    except Exception as e:
        logger.exception(f"Erro na consulta AI v2: {e}")
        return _error(t0, "AI_QUERY_FAILED", "Erro interno ao processar a consulta de IA.", 500)
    if result.get("status") != "success":
        return _error(t0, "AI_QUERY_INVALID", result.get("message", "Consulta inválida."), 400)
    return build_v2_response(data=result, execution_time_ms=_elapsed(t0))


@router.get("/config")
async def get_ai_config_v2(request: Request):
    """Retorna a configuração dos provedores de IA (chaves mascaradas)."""
    t0 = time.perf_counter()
    require_ai_user(request)
    from engines.ai_assistant import load_ai_config
    from engines.ai_providers import mask_config
    return build_v2_response(data={"config": mask_config(load_ai_config())}, execution_time_ms=_elapsed(t0))


@router.post("/config")
async def update_ai_config_v2(body: ConfigRequest, request: Request):
    """Atualiza as configurações de IA (somente administradores)."""
    t0 = time.perf_counter()
    require_ai_user(request, admin=True)
    try:
        from engines.ai_assistant import save_ai_config
        updated = save_ai_config(body.model_dump(exclude_unset=True))
    except (ValueError, TypeError) as e:
        return _error(t0, "AI_CONFIG_INVALID", str(e), 400)
    except OSError as e:
        logger.error(f"Falha ao gravar configuração de IA (v2): {e}")
        return _error(t0, "AI_CONFIG_SAVE_ERROR", "Falha ao gravar a configuração de IA no disco.", 500)
    return build_v2_response(data={"message": "Configurações de IA salvas com sucesso", "config": updated},
                             execution_time_ms=_elapsed(t0))


@router.post("/diagnose")
async def agent_ai_diagnose_v2(request: Request):
    """Diagnóstico de saúde do nó com telemetria real (v2). Valores enviados pelo cliente são ignorados."""
    t0 = time.perf_counter()
    require_ai_user(request)
    from engines.ai_diagnostic_engine import collect_host_telemetry
    telemetry = await run_in_threadpool(collect_host_telemetry)
    diag = await run_in_threadpool(build_node_diagnosis, telemetry)
    return build_v2_response(
        data={
            "status": diag["status"],
            "health_score": diag["health_score"],
            "analysis": diag["analysis"],
            "ai_insights": diag["analysis"],
            "telemetry": telemetry,
        },
        execution_time_ms=_elapsed(t0),
    )
