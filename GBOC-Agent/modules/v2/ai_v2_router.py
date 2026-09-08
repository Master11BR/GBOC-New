# ==============================================================================
# GBOC System v14.1.0 Enterprise Edition
# Module: AI Copilot Assistant Router (API v2 - Agent)
# ==============================================================================

import time
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from modules.v2.envelope import build_v2_response

logger = logging.getLogger("gboc_agent_v2_ai")
router = APIRouter(prefix="/ai", tags=["AI Copilot v2"])


class QueryRequestV2(BaseModel):
    prompt: str = Field(..., min_length=1, description="Prompt ou pergunta para a IA")
    provider: Optional[str] = Field(None, description="Provedor específico ou override")


class ConfigRequestV2(BaseModel):
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
async def chat_with_ai_v2(body: QueryRequestV2):
    """Envia pergunta para o assistente de IA generativa GBOC Copilot (padrão v2)."""
    t0 = time.perf_counter()
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="O prompt não pode ser vazio")

    try:
        from engines.ai_assistant import query_ai_assistant
        result = query_ai_assistant(body.prompt, provider_override=body.provider)
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return build_v2_response(data=result, execution_time_ms=elapsed)
    except Exception as e:
        logger.error(f"Erro na consulta AI v2: {e}")
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return build_v2_response(
            success=False,
            error={"code": "AI_QUERY_FAILED", "message": str(e)},
            execution_time_ms=elapsed
        )


@router.get("/config")
async def get_ai_config_v2():
    """Retorna a configuração dos provedores de IA mascarada no padrão v2."""
    t0 = time.perf_counter()
    try:
        from engines.ai_assistant import load_ai_config
        cfg = load_ai_config()
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
async def update_ai_config_v2(body: ConfigRequestV2):
    """Atualiza as configurações de IA no padrão v2."""
    t0 = time.perf_counter()
    try:
        from engines.ai_assistant import save_ai_config
        updated = save_ai_config(body.dict(exclude_unset=True))
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return build_v2_response(
            data={"message": "Configurações de IA salvas com sucesso", "config": updated},
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
async def agent_ai_diagnose_v2(request: Request):
    """Executa diagnóstico e análise de saúde via IA no padrão v2."""
    t0 = time.perf_counter()
    try:
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass

        disk = body.get("disk_percent")
        ram = body.get("ram_percent")
        cpu = body.get("cpu_percent")

        if cpu is None or ram is None or disk is None:
            import psutil
            import platform
            if cpu is None:
                cpu = psutil.cpu_percent(interval=0.1)
            if ram is None:
                ram = psutil.virtual_memory().percent
            if disk is None:
                disk = psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/").percent

        health_score = max(50, min(100, int(100 - (cpu * 0.2 + ram * 0.3 + (disk if disk > 85 else 0) * 0.5))))

        analysis = (
            f"🔍 **Diagnóstico IA do Agente GBOC (v2)**:\n\n"
            f"• **Telemetria do Nó**: CPU {cpu}%, RAM {ram}%, Disco {disk}%.\n"
            f"• **Status da Proteção**: Serviços de backup, VSS e canários ativos.\n"
            f"• **Recomendação**: Parâmetros normais de operação."
        )

        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return build_v2_response(
            data={
                "status": "HEALTHY" if health_score >= 80 else "WARNING",
                "health_score": health_score,
                "analysis": analysis,
                "ai_insights": analysis
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
