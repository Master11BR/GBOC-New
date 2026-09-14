# ==============================================================================
# GBOC System v14.1.0 Enterprise Edition
# Module: Server AI Copilot Assistant Router (API v2 - Server)
# ==============================================================================

import time
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from modules.v2.envelope import build_v2_response

logger = logging.getLogger("gboc_server_v2_ai")
router = APIRouter(prefix="/ai", tags=["Server AI Copilot v2"])


class ServerQueryRequestV2(BaseModel):
    prompt: str = Field(..., min_length=1, description="Pergunta técnica sobre o ambiente GBOC")
    provider: Optional[str] = Field(None, description="Override de provedor (ex: ollama_local, deepseek, groq_free)")


class ServerConfigRequestV2(BaseModel):
    provider: Optional[str] = None
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    groq_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None


@router.post("/query")
async def server_chat_ai_v2(body: ServerQueryRequestV2):
    """Envia pergunta para o assistente de IA generativa GBOC Server Copilot (padrão v2)."""
    t0 = time.perf_counter()
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="O prompt não pode ser vazio")

    try:
        from modules.ai_assistant.ai_assistant_router import query_server_ai_assistant
        result = query_server_ai_assistant(body.prompt, provider_override=body.provider)
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return build_v2_response(data=result, execution_time_ms=elapsed)
    except Exception as e:
        logger.error(f"Erro na consulta AI Server v2: {e}")
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return build_v2_response(
            success=False,
            error={"code": "AI_QUERY_FAILED", "message": str(e)},
            execution_time_ms=elapsed
        )


@router.get("/config")
async def get_server_ai_config_v2():
    """Retorna configuração de IA do servidor central no padrão v2."""
    t0 = time.perf_counter()
    try:
        from modules.ai_assistant.ai_assistant_router import load_server_ai_config
        cfg = load_server_ai_config()
        for k in ["groq_api_key", "gemini_api_key", "openai_api_key", "deepseek_api_key"]:
            if cfg.get(k):
                val = cfg[k]
                cfg[k] = val[:4] + "..." + val[-4:] if len(val) > 8 else "***"
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return build_v2_response(data={"config": cfg}, execution_time_ms=elapsed)
    except Exception as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return build_v2_response(
            success=False,
            error={"code": "AI_CONFIG_ERROR", "message": str(e)},
            execution_time_ms=elapsed
        )


@router.post("/config")
async def update_server_ai_config_v2(body: ServerConfigRequestV2):
    """Atualiza as configurações de IA do Servidor Central no padrão v2."""
    t0 = time.perf_counter()
    try:
        from modules.ai_assistant.ai_assistant_router import save_server_ai_config
        saved = save_server_ai_config(body.dict(exclude_unset=True))
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return build_v2_response(
            data={"message": "Configurações de IA salvas com sucesso", "config": saved},
            execution_time_ms=elapsed
        )
    except Exception as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return build_v2_response(
            success=False,
            error={"code": "AI_CONFIG_SAVE_ERROR", "message": str(e)},
            execution_time_ms=elapsed
        )


@router.post("/diagnose")
async def server_ai_diagnose_v2(request: Request):
    """Diagnóstico preditivo por IA para qualquer módulo do Servidor Central (v2)."""
    t0 = time.perf_counter()
    try:
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass

        error_context = body.get("error_context") or body.get("module") or ""

        import psutil
        import platform
        cpu = psutil.cpu_percent(interval=0.05) if hasattr(psutil, 'cpu_percent') else 0.0
        ram = psutil.virtual_memory().percent if hasattr(psutil, 'virtual_memory') else 0.0
        disk = psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/").percent if hasattr(psutil, 'disk_usage') else 0.0

        telemetry = {
            "cpu_percent": cpu,
            "ram_percent": ram,
            "disk_percent": disk,
            "platform": platform.system()
        }

        import asyncio
        ai_res = None
        try:
            from modules.ai_assistant.ai_diagnostic_engine import server_ai_diagnostic_engine
            ai_res = await asyncio.wait_for(server_ai_diagnostic_engine.analyze_error(error_context, system_logs=body.get("logs")), timeout=3.5)
        except Exception:
            pass

        if not ai_res or not ai_res.get("analysis") or "Diagnóstico geral" in str(ai_res.get("analysis")):
            from modules.ai_assistant.ai_diagnostic_engine import server_ai_diagnostic_engine
            ai_res = server_ai_diagnostic_engine._rule_based_ai_analysis(error_context, telemetry=telemetry)

        health_score = max(40, min(100, int(100 - (cpu * 0.15 + ram * 0.25 + (disk if disk > 85 else 0) * 0.4))))

        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return build_v2_response(
            data={
                "status": "HEALTHY" if health_score >= 80 else "WARNING" if health_score >= 60 else "CRITICAL",
                "health_score": health_score,
                "ai_insights": ai_res.get("analysis", "Diagnóstico processado com sucesso."),
                "result": ai_res,
                "telemetry": telemetry
            },
            execution_time_ms=elapsed
        )
    except Exception as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return build_v2_response(
            success=False,
            error={"code": "AI_DIAGNOSE_FAILED", "message": str(e)},
            execution_time_ms=elapsed
        )
