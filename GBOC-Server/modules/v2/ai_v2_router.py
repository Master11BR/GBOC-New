# ==============================================================================
# GBOC System v14.7.3 Enterprise Edition
# Module: Server AI Copilot Assistant Router (API v2 - Server)
# ==============================================================================

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from modules.ai_assistant.ai_assistant_router import (
    _require_admin,
    _require_auth,
    collect_host_telemetry,
    compute_health_score,
    health_status,
    load_server_ai_config,
    query_server_ai_assistant,
    save_server_ai_config,
)
from modules.ai_assistant import ai_providers as aip
from modules.v2.envelope import build_v2_response

logger = logging.getLogger("gboc_server_v2_ai")
router = APIRouter(prefix="/ai", tags=["Server AI Copilot v2"])

# Tempo máximo para o diagnóstico por LLM antes de responder com a heurística (segundos).
DIAGNOSE_LLM_TIMEOUT = 90.0


def _elapsed(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)


def _error(t0: float, code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        build_v2_response(success=False, error={"code": code, "message": message}, execution_time_ms=_elapsed(t0)),
        status_code=status_code,
    )


class ServerQueryRequestV2(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000, description="Pergunta técnica sobre o ambiente GBOC")
    provider: Optional[str] = Field(None, description="Override de provedor (ex: ollama_local, deepseek, groq)")


class ServerConfigRequestV2(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    deepseek_model: Optional[str] = None
    groq_api_key: Optional[str] = None
    groq_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    claude_api_key: Optional[str] = None
    claude_model: Optional[str] = None
    grok_api_key: Optional[str] = None
    kimi_api_key: Optional[str] = None
    mistral_api_key: Optional[str] = None
    cohere_api_key: Optional[str] = None
    task_history_limit: Optional[int] = None


@router.post("/query")
async def server_chat_ai_v2(body: ServerQueryRequestV2, request: Request):
    """Envia pergunta para o GBOC Server Copilot (padrão v2)."""
    t0 = time.perf_counter()
    _require_auth(request)
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="O prompt não pode ser vazio")
    try:
        result = await run_in_threadpool(query_server_ai_assistant, body.prompt, body.provider)
    except Exception as e:
        logger.exception(f"Erro na consulta AI Server v2: {e}")
        return _error(t0, "AI_QUERY_FAILED", "Erro interno ao processar a consulta de IA.", 500)
    if result.get("status") != "success":
        return _error(t0, "AI_QUERY_INVALID", result.get("message", "Consulta inválida."), 400)
    return build_v2_response(data=result, execution_time_ms=_elapsed(t0))


@router.get("/config")
async def get_server_ai_config_v2(request: Request):
    """Retorna configuração de IA do servidor central (chaves mascaradas)."""
    t0 = time.perf_counter()
    _require_auth(request)
    return build_v2_response(data={"config": aip.mask_config(load_server_ai_config())}, execution_time_ms=_elapsed(t0))


@router.post("/config")
async def update_server_ai_config_v2(body: ServerConfigRequestV2, request: Request):
    """Atualiza as configurações de IA do Servidor Central (somente administradores)."""
    t0 = time.perf_counter()
    _require_admin(request)
    try:
        saved = save_server_ai_config(body.model_dump(exclude_unset=True))
    except (ValueError, TypeError) as e:
        return _error(t0, "AI_CONFIG_INVALID", str(e), 400)
    except OSError as e:
        logger.error(f"Falha ao gravar configuração de IA (v2): {e}")
        return _error(t0, "AI_CONFIG_SAVE_ERROR", "Falha ao gravar a configuração de IA no disco.", 500)
    return build_v2_response(data={"message": "Configurações de IA salvas com sucesso", "config": saved},
                             execution_time_ms=_elapsed(t0))


@router.post("/diagnose")
async def server_ai_diagnose_v2(request: Request):
    """Diagnóstico por IA do Servidor Central com telemetria real do host (v2)."""
    t0 = time.perf_counter()
    _require_auth(request)
    try:
        body = await request.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    error_context = body.get("error_context") or body.get("module") or ""

    from modules.ai_assistant.ai_diagnostic_engine import server_ai_diagnostic_engine

    telemetry = await run_in_threadpool(collect_host_telemetry)
    try:
        ai_res = await asyncio.wait_for(
            server_ai_diagnostic_engine.analyze_error(error_context, system_logs=body.get("logs"), telemetry=telemetry),
            timeout=DIAGNOSE_LLM_TIMEOUT,
        )
    except asyncio.TimeoutError:
        ai_res = server_ai_diagnostic_engine._rule_based_ai_analysis(error_context, telemetry=telemetry)
        ai_res.update({
            "is_llm_real": False, "provider": "Heurística GBOC Server", "model": "gboc-heuristic",
            "llm_error": f"O provedor de IA não respondeu em {DIAGNOSE_LLM_TIMEOUT:.0f}s.",
        })
    except Exception as e:
        logger.exception(f"Falha no diagnóstico de IA v2: {e}")
        return _error(t0, "AI_DIAGNOSE_FAILED", "Falha interna ao executar o diagnóstico.", 500)

    score = compute_health_score(telemetry)
    return build_v2_response(
        data={
            "status": health_status(score),
            "health_score": score,
            "ai_insights": ai_res.get("analysis", ""),
            "result": ai_res,
            "telemetry": telemetry,
        },
        execution_time_ms=_elapsed(t0),
    )
