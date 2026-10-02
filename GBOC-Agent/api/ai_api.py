#!/usr/bin/env python3
"""
GBOC 14.7.4 - GBOC Copilot AI Assistant API (Agent)
Chat multi-provedor, configuração de provedores e diagnóstico do nó com telemetria real.

Observação de segurança: os prefixos /api/ai e /api/v1/ai não são mais públicos no
middleware; além disso cada endpoint valida a sessão explicitamente (defesa em profundidade).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["GBOC Copilot AI"])
router_v1 = APIRouter(prefix="/api/v1/ai", tags=["GBOC Copilot AI v1"])

ADMIN_ROLES = frozenset({"admin", "administrator", "superadmin"})


def require_ai_user(request: Request, admin: bool = False) -> dict[str, Any]:
    """Exige sessão válida do Agente; com admin=True exige perfil administrador."""
    from api.auth import get_current_user, is_auth_enabled

    if not is_auth_enabled():
        raise HTTPException(status_code=401, detail="Configuração inicial de autenticação necessária.")
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Autenticação necessária.")
    if admin:
        role = _get_user_role(user.get("user_id"))
        if (role or "").lower() not in ADMIN_ROLES:
            raise HTTPException(status_code=403, detail="Permissão negada: somente administradores podem alterar a IA.")
    return user


def _get_user_role(user_id: Any) -> Optional[str]:
    if user_id is None:
        return None
    try:
        from shared_core import get_shared_core
        with get_shared_core().get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT role FROM auth_users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            cur.close()
            return row[0] if row else None
    except Exception as e:
        logger.error(f"Falha ao consultar perfil do usuário {user_id}: {e}")
        return None


class QueryRequest(BaseModel):
    prompt: str = Field(..., max_length=8000)
    provider: Optional[str] = None


class ConfigRequest(BaseModel):
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
    custom_endpoint: Optional[str] = None


@router.post("/query")
@router_v1.post("/query")
async def chat_with_ai(body: QueryRequest, request: Request):
    """Envia pergunta para o assistente de IA generativa GBOC Copilot."""
    require_ai_user(request)
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="O prompt da pergunta não pode ser vazio")
    from engines.ai_assistant import query_ai_assistant
    result = await run_in_threadpool(query_ai_assistant, body.prompt, body.provider)
    return JSONResponse(result, status_code=200 if result.get("status") == "success" else 400)


@router.get("/config")
@router_v1.get("/config")
async def get_ai_provider_config(request: Request):
    """Retorna as configurações atuais dos provedores de IA (chaves mascaradas)."""
    require_ai_user(request)
    from engines.ai_assistant import load_ai_config
    from engines.ai_providers import DEFAULT_MODELS, mask_config
    return {"status": "success", "config": mask_config(load_ai_config()), "default_models": DEFAULT_MODELS}


@router.post("/config")
@router_v1.post("/config")
async def update_ai_provider_config(body: ConfigRequest, request: Request):
    """Atualiza as configurações do provedor de IA (somente administradores)."""
    require_ai_user(request, admin=True)
    from engines.ai_assistant import save_ai_config
    try:
        updated = save_ai_config(body.model_dump(exclude_unset=True))
    except (ValueError, TypeError) as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except OSError as e:
        logger.error(f"Falha ao gravar configuração de IA: {e}")
        return JSONResponse({"status": "error", "message": "Falha ao gravar a configuração de IA no disco."}, status_code=500)
    return {"status": "success", "message": "Configurações de IA atualizadas com sucesso", "config": updated}


def build_node_diagnosis(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Diagnóstico do nó baseado somente em telemetria real e no estado real de proteção."""
    if not telemetry.get("available"):
        return {"status": "UNAVAILABLE", "health_score": None,
                "analysis": f"ℹ️ Telemetria do nó indisponível: {telemetry.get('error', 'motivo desconhecido')}."}
    cpu, ram, disk = telemetry["cpu_percent"], telemetry["ram_percent"], telemetry["disk_percent"]
    score = max(0, min(100, int(100 - (cpu * 0.2 + ram * 0.3 + (disk if disk > 85 else 0) * 0.5))))

    from engines.ai_assistant import collect_agent_operational_data
    ops = collect_agent_operational_data()
    lines = [
        "🔍 **Diagnóstico do Agente GBOC (telemetria real)**",
        f"• CPU {cpu}% • RAM {ram}% • Disco {disk}%",
    ]
    if ops.get("available"):
        lines.append(f"• Execuções 7 dias: {ops['executions_7d']} ({ops['failed_7d']} falhas, {ops['failed_24h']} nas últimas 24h).")
    else:
        lines.append(f"• Execuções: indisponível ({ops.get('error', '')}).")
    rw = ops.get("ransomware", {})
    if rw.get("available"):
        lines.append(f"• Canários ransomware: {rw['canaries_total']} implantados, {rw['canaries_compromised']} comprometidos.")
    else:
        lines.append("• Proteção ransomware: status indisponível.")
    if ops.get("failed_24h"):
        score = max(0, score - min(30, ops["failed_24h"] * 5))
        lines.append("• Recomendação: investigue as falhas recentes em **Falhas de Jobs**.")
    status = "HEALTHY" if score >= 80 else "WARNING" if score >= 60 else "CRITICAL"
    return {"status": status, "health_score": score, "analysis": "\n".join(lines), "operations": ops}


@router.post("/diagnose")
@router_v1.post("/diagnose")
async def agent_ai_diagnose(request: Request):
    """Diagnóstico da saúde do nó do Agente com telemetria real (sem valores presumidos)."""
    require_ai_user(request)
    from engines.ai_diagnostic_engine import collect_host_telemetry
    telemetry = await run_in_threadpool(collect_host_telemetry)
    diag = await run_in_threadpool(build_node_diagnosis, telemetry)
    return JSONResponse({
        "status": diag["status"],
        "health_score": diag["health_score"],
        "analysis": diag["analysis"],
        "ai_insights": diag["analysis"],
        "telemetry": telemetry,
        "result": {"is_llm_real": False, "analysis": diag["analysis"]},
    })


@router.post("/auto_fix")
@router_v1.post("/auto_fix")
async def agent_ai_auto_fix(request: Request):
    """Não há remediação automática implementada: responde com erro explícito em vez de simular sucesso."""
    require_ai_user(request)
    return JSONResponse(
        {
            "status": "unavailable",
            "fixed": False,
            "error": {
                "code": "AUTO_FIX_NOT_IMPLEMENTED",
                "message": "Nenhuma remediação automática foi executada. Use a solução indicada no diagnóstico "
                           "ou o reparo do módulo Diagnóstico.",
            },
        },
        status_code=501,
    )
