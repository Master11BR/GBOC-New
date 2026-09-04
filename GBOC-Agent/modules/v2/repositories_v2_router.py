# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: Repositories Router (API v2 - Agent)
# ==============================================================================

import time
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query
from modules.v2.envelope import build_v2_response, PaginationMeta

logger = logging.getLogger("gboc_agent_v2_repos")
router = APIRouter(prefix="/repositories", tags=["Repositories v2"])

@router.get("")
@router.get("/")
async def list_repositories_v2(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    type: Optional[str] = Query(None, description="local ou cloud"),
    engine: Optional[str] = Query(None, description="restic, kopia, duplicati, s3, b2")
):
    """Listagem consolidada de repositórios do agente com paginação e envelope v2."""
    t0 = time.perf_counter()
    repos = []
    total = 0

    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        if core and hasattr(core, 'repository_manager') and core.repository_manager:
            all_repos = core.repository_manager.list_repositories()
            
            # Filtros
            filtered = []
            for r in all_repos:
                if type and r.get("type") != type:
                    continue
                if engine and r.get("engine") != engine:
                    continue
                filtered.append(r)
                
            total = len(filtered)
            offset = (page - 1) * per_page
            repos = filtered[offset:offset + per_page]
    except Exception as e:
        logger.error(f"[API v2] Erro ao listar repositórios no agente: {e}")

    total_pages = (total + per_page - 1) // per_page if total > 0 else 0
    meta = PaginationMeta(
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
        filters={"type": type, "engine": engine}
    )

    elapsed = (time.perf_counter() - t0) * 1000
    return build_v2_response(data=repos, meta=meta, execution_time_ms=elapsed)
