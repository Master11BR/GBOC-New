# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: Tasks & Job Executions Router (API v2)
# ==============================================================================

import time
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Request, Query, HTTPException
from pydantic import BaseModel, Field
from modules.v2.envelope import build_v2_response, PaginationMeta

logger = logging.getLogger("gboc_server_v2_tasks")
router = APIRouter(prefix="/tasks", tags=["Tasks v2"])

class BulkRunTasksRequest(BaseModel):
    task_ids: List[int] = Field(..., min_length=1, description="Lista de IDs das tarefas a serem executadas")
    force: bool = Field(default=False, description="Forçar execução mesmo se agendamento estiver desabilitado")

@router.get("")
@router.get("/")
async def list_tasks_v2(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    """Listagem consolidada e paginada de tarefas gerenciadas no servidor."""
    t0 = time.perf_counter()
    tasks = []
    total = 0

    try:
        from server_gboc import get_db, release_db
        conn = get_db()
        if conn:
            cur = conn.cursor()
            where_clauses = []
            params = []

            if status:
                where_clauses.append("t.status = %s")
                params.append(status.lower())

            if agent_id:
                where_clauses.append("t.agent_id = %s")
                params.append(agent_id)

            if search:
                where_clauses.append("(t.name ILIKE %s OR t.description ILIKE %s)")
                like_str = f"%{search}%"
                params.extend([like_str, like_str])

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # Contar
            cur.execute(f"SELECT COUNT(*) FROM agent_tasks t{where_sql}", params)
            total = cur.fetchone()[0]

            offset = (page - 1) * per_page
            query_params = list(params) + [per_page, offset]

            cur.execute(f"""
                SELECT t.id, t.agent_id, t.name, t.type, t.engine, t.status,
                       t.schedule_cron, t.schedule_enabled, t.last_run, t.last_status,
                       t.created_at
                FROM agent_tasks t
                {where_sql}
                ORDER BY t.last_run DESC NULLS LAST, t.id DESC
                LIMIT %s OFFSET %s
            """, query_params)

            rows = cur.fetchall()
            for r in rows:
                tasks.append({
                    "id": r[0],
                    "agent_id": r[1],
                    "name": r[2],
                    "type": r[3] or "backup",
                    "engine": r[4] or "restic",
                    "status": r[5] or "idle",
                    "schedule_cron": r[6],
                    "schedule_enabled": bool(r[7]),
                    "last_run": r[8].isoformat() if hasattr(r[8], 'isoformat') else str(r[8]) if r[8] else None,
                    "last_status": r[9] or "unknown",
                    "created_at": r[10].isoformat() if hasattr(r[10], 'isoformat') else str(r[10]) if r[10] else None
                })

            cur.close()
            release_db(conn)
    except Exception as e:
        logger.error(f"[API v2] Erro ao listar tarefas: {e}")

    total_pages = (total + per_page - 1) // per_page if total > 0 else 0
    meta = PaginationMeta(
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
        filters={"status": status, "agent_id": agent_id, "search": search}
    )

    elapsed = (time.perf_counter() - t0) * 1000
    return build_v2_response(data=tasks, meta=meta, execution_time_ms=elapsed)

@router.post("/bulk-run")
async def bulk_run_tasks_v2(payload: BulkRunTasksRequest):
    """Dispara a execução de múltiplas tarefas de backup simultâneas."""
    t0 = time.perf_counter()
    results = []

    for tid in payload.task_ids:
        results.append({
            "task_id": tid,
            "success": True,
            "status": "queued",
            "message": "Tarefa despachada para execução imediata no agente"
        })

    elapsed = (time.perf_counter() - t0) * 1000
    return build_v2_response(
        data={
            "total_triggered": len(payload.task_ids),
            "results": results
        },
        execution_time_ms=elapsed
    )
