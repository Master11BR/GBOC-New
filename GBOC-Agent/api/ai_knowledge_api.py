#!/usr/bin/env python3
"""
GBOC Agent - API da base de conhecimento da IA (RAG local), casos de diagnóstico, tokens MCP e fine-tuning.
Prefixo: /api/ai-knowledge
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.ai_api import require_ai_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai-knowledge", tags=["IA: RAG, MCP e Fine-tuning"])

try:
    from engines import ai_rag as _rag_boot
    _rag_boot.start_scheduler()
except Exception as _boot_err:  # não impede o Agente de subir
    logger.warning(f"[RAG] Agendador não iniciado: {_boot_err}")


# ── Status / configuração ────────────────────────────────────────────────────

@router.get("/status")
async def knowledge_status(request: Request):
    require_ai_user(request)
    from engines import ai_rag, ai_cases, mcp_server
    from engines.ai_diagnostic_engine import ai_diagnostic_engine
    rag = await run_in_threadpool(ai_rag.stats)
    cfg = ai_diagnostic_engine.config
    return {
        "status": "success",
        "rag": rag,
        "cases": await run_in_threadpool(ai_cases.counts),
        "config": {
            "rag_enabled": cfg.get("rag_enabled", True) is not False,
            "rag_embedding_provider": cfg.get("rag_embedding_provider") or "auto",
            "rag_embedding_model": cfg.get("rag_embedding_model") or "",
            "rag_reindex_hours": cfg.get("rag_reindex_hours") or 6,
            "rag_execution_days": cfg.get("rag_execution_days") or 90,
            "auto_diagnose_errors": cfg.get("auto_diagnose_errors", True) is not False,
            "mcp_enabled": cfg.get("mcp_enabled", True) is not False,
            "finetune_local_enabled": cfg.get("finetune_local_enabled", False) is True,
            "provider": cfg.get("provider"),
            "ollama_model": cfg.get("ollama_model") or cfg.get("model"),
        },
        "mcp": {"tools": [{"name": n, "role": t["role"], "description": t["def"]["description"]}
                          for n, t in mcp_server.TOOLS.items()],
                "path": "/api/mcp"},
    }


class KnowledgeConfig(BaseModel):
    rag_enabled: Optional[bool] = None
    rag_embedding_provider: Optional[str] = None
    rag_embedding_model: Optional[str] = None
    rag_reindex_hours: Optional[float] = None
    rag_execution_days: Optional[int] = None
    auto_diagnose_errors: Optional[bool] = None
    mcp_enabled: Optional[bool] = None
    finetune_local_enabled: Optional[bool] = None


@router.post("/config")
async def knowledge_config(body: KnowledgeConfig, request: Request):
    require_ai_user(request, admin=True)
    from engines.ai_diagnostic_engine import ai_diagnostic_engine
    try:
        saved = ai_diagnostic_engine.save_config(body.model_dump(exclude_none=True))
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Reavalia o ambiente: o que foi ativado e não é suportado aqui volta explicado na resposta
    from engines import ai_capabilities
    caps = await run_in_threadpool(ai_capabilities.evaluate, True)
    return {"status": "success", "config": {k: saved.get(k) for k in body.model_dump(exclude_none=True)},
            "capabilities": caps}


@router.get("/capabilities")
async def knowledge_capabilities(request: Request, refresh: bool = False):
    """Estado real de cada recurso de IA neste host (ativo, parcial, indisponível/impossível ou desligado)."""
    require_ai_user(request)
    from engines import ai_capabilities
    return {"status": "success", **await run_in_threadpool(ai_capabilities.evaluate, refresh)}


# ── RAG ──────────────────────────────────────────────────────────────────────

class ReindexRequest(BaseModel):
    sources: Optional[list[str]] = None


@router.post("/reindex")
async def knowledge_reindex(body: ReindexRequest, request: Request):
    require_ai_user(request, admin=True)
    from engines import ai_rag
    started = ai_rag.reindex_async(body.sources or None)
    if not started:
        return {"status": "busy", "message": "Indexação já em andamento."}
    return {"status": "started", "message": "Indexação iniciada em segundo plano."}


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    sources: Optional[list[str]] = None
    k: int = Field(8, ge=1, le=30)


@router.post("/search")
async def knowledge_search(body: SearchRequest, request: Request):
    require_ai_user(request)
    from engines import ai_rag
    return {"status": "success", **await run_in_threadpool(ai_rag.search, body.query, body.k, body.sources)}


# ── Casos de diagnóstico ─────────────────────────────────────────────────────

@router.get("/cases")
async def list_cases(request: Request, feedback: Optional[str] = None, limit: int = 100, offset: int = 0):
    require_ai_user(request)
    from engines import ai_cases
    rows = await run_in_threadpool(ai_cases.list_cases, max(1, min(500, limit)), feedback, max(0, offset))
    return {"status": "success", "cases": rows, "counts": await run_in_threadpool(ai_cases.counts)}


class FeedbackRequest(BaseModel):
    feedback: str
    note: Optional[str] = None
    solution: Optional[str] = None
    cause: Optional[str] = None


@router.post("/cases/{case_id}/feedback")
async def case_feedback(case_id: int, body: FeedbackRequest, request: Request):
    user = require_ai_user(request)
    from engines import ai_cases
    try:
        case = await run_in_threadpool(ai_cases.set_feedback, case_id, body.feedback, body.note, body.solution,
                                       body.cause, user.get("username"))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "case": case}


@router.get("/cases/{case_id}/recovery")
async def case_recovery(case_id: int, request: Request):
    require_ai_user(request)
    from engines import ai_cases
    case = await run_in_threadpool(ai_cases.get_case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Caso não encontrado.")
    return {"status": "success", "task_recovered": await run_in_threadpool(ai_cases.task_recovered_after, case)}


# ── Tokens MCP ───────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    role: str = "read"


@router.get("/mcp/tokens")
async def mcp_tokens(request: Request):
    require_ai_user(request, admin=True)
    from engines import mcp_server
    return {"status": "success", "tokens": await run_in_threadpool(mcp_server.list_tokens)}


@router.post("/mcp/tokens")
async def mcp_token_create(body: TokenRequest, request: Request):
    user = require_ai_user(request, admin=True)
    from engines import mcp_server
    res = await run_in_threadpool(mcp_server.create_token, body.name, body.role, user.get("username"))
    try:
        from api.audit_api import record_audit
        record_audit("mcp.token.create", resource_type="mcp_token", resource_id=str(res["id"]),
                     resource_name=res["name"], detail={"role": res["role"]}, username=user.get("username"))
    except Exception:
        pass
    return {"status": "success", **res}


@router.delete("/mcp/tokens/{token_id}")
async def mcp_token_revoke(token_id: int, request: Request):
    user = require_ai_user(request, admin=True)
    from engines import mcp_server
    if not await run_in_threadpool(mcp_server.revoke_token, token_id):
        raise HTTPException(status_code=404, detail="Token não encontrado.")
    try:
        from api.audit_api import record_audit
        record_audit("mcp.token.revoke", resource_type="mcp_token", resource_id=str(token_id), username=user.get("username"))
    except Exception:
        pass
    return {"status": "success"}


# ── Fine-tuning ──────────────────────────────────────────────────────────────

@router.get("/finetune/summary")
async def finetune_summary(request: Request):
    require_ai_user(request)
    from engines import ai_finetune
    return {"status": "success", **await run_in_threadpool(ai_finetune.summary)}


class DatasetRequest(BaseModel):
    mode: str = "verified"


@router.post("/finetune/dataset")
async def finetune_dataset(body: DatasetRequest, request: Request):
    require_ai_user(request, admin=True)
    from engines import ai_finetune
    try:
        res = await run_in_threadpool(ai_finetune.build_dataset, body.mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "dataset": res}


@router.get("/finetune/datasets/{filename}")
async def finetune_download(filename: str, request: Request):
    require_ai_user(request, admin=True)
    from engines import ai_finetune
    try:
        path = ai_finetune.dataset_file(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset não encontrado.")
    return FileResponse(str(path), media_type="application/jsonl", filename=path.name)


class ImportRequest(BaseModel):
    model_name: str
    file_path: str
    kind: str = "gguf"
    base_model: Optional[str] = None
    set_default: bool = False


@router.post("/finetune/import")
async def finetune_import(body: ImportRequest, request: Request):
    require_ai_user(request, admin=True)
    from engines import ai_finetune
    if body.kind not in ("gguf", "adapter"):
        raise HTTPException(status_code=400, detail="kind deve ser 'gguf' ou 'adapter'.")
    started = ai_finetune.import_async(model_name=body.model_name, file_path=body.file_path, kind=body.kind,
                                       base_model=body.base_model, set_default=body.set_default)
    if not started:
        return {"status": "busy", "message": "Já existe uma importação em andamento."}
    return {"status": "started", "message": "Importação iniciada. Acompanhe o andamento nesta tela."}


class TrainRequest(BaseModel):
    dataset: str
    base_model: Optional[str] = None
    epochs: float = Field(3.0, ge=0.5, le=20)
    export_gguf: bool = True


@router.post("/finetune/train")
async def finetune_train(body: TrainRequest, request: Request):
    """Treino LoRA local — só inicia se o treino local estiver ativado E o ambiente atender (GPU NVIDIA + CUDA + Unsloth)."""
    require_ai_user(request, admin=True)
    from engines import ai_finetune
    try:
        return await run_in_threadpool(ai_finetune.train_local, body.dataset, body.base_model, body.epochs, body.export_gguf)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=409, detail=str(e))
