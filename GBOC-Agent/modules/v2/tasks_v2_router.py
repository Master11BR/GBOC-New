# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Module: Tasks Router (API v2 - Agent)
# ==============================================================================

import time
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from modules.v2.envelope import build_v2_response, PaginationMeta

logger = logging.getLogger("gboc_agent_v2_tasks")
router = APIRouter(prefix="/tasks", tags=["Tasks v2"])

class BulkRunRequest(BaseModel):
    task_ids: List[int] = Field(..., min_length=1)

@router.get("")
@router.get("/")
async def list_tasks_v2(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    engine: Optional[str] = Query(None)
):
    """Listagem de tarefas de backup locais no agente com paginação e envelope v2."""
    t0 = time.perf_counter()
    tasks = []
    total = 0

    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        if core and hasattr(core, 'task_manager') and core.task_manager:
            all_tasks = core.task_manager.list_tasks()
            filtered = []
            for t in all_tasks:
                if status and t.get("status") != status:
                    continue
                if engine and t.get("engine") != engine:
                    continue
                filtered.append(t)
                
            total = len(filtered)
            offset = (page - 1) * per_page
            tasks = filtered[offset:offset + per_page]
    except Exception as e:
        logger.error(f"[API v2] Erro ao listar tarefas no agente: {e}")

    total_pages = (total + per_page - 1) // per_page if total > 0 else 0
    meta = PaginationMeta(
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
        filters={"status": status, "engine": engine}
    )

    elapsed = (time.perf_counter() - t0) * 1000
    return build_v2_response(data=tasks, meta=meta, execution_time_ms=elapsed)

@router.post("/bulk-run")
async def bulk_run_agent_tasks_v2(payload: BulkRunRequest):
    """Executa múltiplas tarefas no agente em uma única chamada."""
    t0 = time.perf_counter()
    results = []

    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        for tid in payload.task_ids:
            res_item = {"task_id": tid, "success": True, "message": "Execução iniciada"}
            if core and hasattr(core, 'task_manager') and core.task_manager:
                try:
                    core.task_manager.run_task(tid)
                except Exception as ex:
                    res_item["success"] = False
                    res_item["message"] = str(ex)
            results.append(res_item)
    except Exception as e:
        logger.error(f"[API v2] Erro ao disparar tarefas em lote: {e}")

    elapsed = (time.perf_counter() - t0) * 1000
    return build_v2_response(data={"results": results}, execution_time_ms=elapsed)
