# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: Remote Agents Router (API v2)
# ==============================================================================

import time
import json
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Request, Query, HTTPException, Body
from pydantic import BaseModel, Field
from modules.v2.envelope import build_v2_response, PaginationMeta

logger = logging.getLogger("gboc_server_v2_agents")
router = APIRouter(prefix="/agents", tags=["Agents v2"])

class BulkActionRequest(BaseModel):
    agent_ids: List[str] = Field(..., min_length=1, description="Lista de IDs dos agentes")
    action: str = Field(..., description="Ação a ser executada: ping, sync, health_check, restart_service")
    parameters: Optional[Dict[str, Any]] = None

@router.get("")
@router.get("/")
async def list_agents_v2(
    page: int = Query(1, ge=1, description="Número da página"),
    per_page: int = Query(20, ge=1, le=100, description="Itens por página"),
    status: Optional[str] = Query(None, description="Filtrar por status: online, offline, degraded"),
    search: Optional[str] = Query(None, description="Buscar por hostname, IP ou ID"),
    sort: Optional[str] = Query("-last_heartbeat", description="Campo de ordenação (+/-campo)")
):
    """Listagem paginada e filtrada de agentes gerenciados com metadados ricos."""
    t0 = time.perf_counter()
    
    agents = []
    total = 0
    
    try:
        from server_gboc import get_db, release_db
        conn = get_db()
        if conn:
            cur = conn.cursor()
            
            # Query base
            where_clauses = []
            params = []
            
            if status:
                where_clauses.append("status = %s")
                params.append(status.lower())
                
            if search:
                where_clauses.append("(hostname ILIKE %s OR ip_address ILIKE %s OR agent_id ILIKE %s)")
                like_term = f"%{search}%"
                params.extend([like_term, like_term, like_term])
                
            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            
            # Contagem total
            cur.execute(f"SELECT COUNT(*) FROM agents{where_sql}", params)
            total = cur.fetchone()[0]
            
            # Ordenação
            order_sql = " ORDER BY last_heartbeat DESC"
            if sort:
                direction = "DESC" if sort.startswith("-") else "ASC"
                clean_field = sort.lstrip("+-")
                allowed_sorts = {
                    "hostname": "hostname",
                    "status": "status",
                    "last_heartbeat": "last_heartbeat",
                    "agent_version": "agent_version",
                    "registered_at": "registered_at",
                    "cpu_usage": "cpu_usage",
                    "ram_usage": "ram_usage"
                }
                if clean_field in allowed_sorts:
                    order_sql = f" ORDER BY {allowed_sorts[clean_field]} {direction}"
                    
            offset = (page - 1) * per_page
            query_params = list(params) + [per_page, offset]
            
            cur.execute(f"""
                SELECT agent_id, hostname, ip_address, os_info, agent_version,
                       available_tools, last_heartbeat, status, cpu_usage, ram_usage,
                       disk_usage, jobs_count, registered_at
                FROM agents
                {where_sql}
                {order_sql}
                LIMIT %s OFFSET %s
            """, query_params)
            
            rows = cur.fetchall()
            for r in rows:
                agents.append({
                    "agent_id": r[0],
                    "hostname": r[1],
                    "ip_address": r[2],
                    "os_info": r[3],
                    "agent_version": r[4],
                    "available_tools": r[5],
                    "last_heartbeat": r[6].isoformat() if hasattr(r[6], 'isoformat') else str(r[6]) if r[6] else None,
                    "status": r[7] or "offline",
                    "cpu_usage": float(r[8]) if r[8] is not None else None,
                    "ram_usage": float(r[9]) if r[9] is not None else None,
                    "disk_usage": float(r[10]) if r[10] is not None else None,
                    "jobs_count": int(r[11]) if r[11] is not None else 0,
                    "registered_at": r[12].isoformat() if hasattr(r[12], 'isoformat') else str(r[12]) if r[12] else None
                })
                
            cur.close()
            release_db(conn)
    except Exception as e:
        logger.error(f"[API v2] Erro ao listar agentes: {e}")

    total_pages = (total + per_page - 1) // per_page if total > 0 else 0
    meta = PaginationMeta(
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
        sort=sort,
        filters={"status": status, "search": search}
    )
    
    elapsed = (time.perf_counter() - t0) * 1000
    return build_v2_response(data=agents, meta=meta, execution_time_ms=elapsed)

@router.get("/{agent_id}")
async def get_agent_detail_v2(agent_id: str):
    """Retorna dados detalhados e status em tempo real de um agente específico."""
    t0 = time.perf_counter()
    
    agent_data = None
    try:
        from server_gboc import get_db, release_db
        conn = get_db()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT agent_id, hostname, ip_address, os_info, agent_version,
                       available_tools, last_heartbeat, status, cpu_usage, ram_usage,
                       disk_usage, jobs_count, registered_at
                FROM agents
                WHERE agent_id = %s
            """, (agent_id,))
            r = cur.fetchone()
            if r:
                # Verificar se está conectado no WebSocket do servidor
                is_ws_online = False
                try:
                    from server_gboc import manager
                    is_ws_online = agent_id in manager.active_connections
                except Exception:
                    pass

                agent_data = {
                    "agent_id": r[0],
                    "hostname": r[1],
                    "ip_address": r[2],
                    "os_info": r[3],
                    "agent_version": r[4],
                    "available_tools": r[5],
                    "last_heartbeat": r[6].isoformat() if hasattr(r[6], 'isoformat') else str(r[6]) if r[6] else None,
                    "status": "online" if is_ws_online else (r[7] or "offline"),
                    "is_websocket_connected": is_ws_online,
                    "cpu_usage": float(r[8]) if r[8] is not None else None,
                    "ram_usage": float(r[9]) if r[9] is not None else None,
                    "disk_usage": float(r[10]) if r[10] is not None else None,
                    "jobs_count": int(r[11]) if r[11] is not None else 0,
                    "registered_at": r[12].isoformat() if hasattr(r[12], 'isoformat') else str(r[12]) if r[12] else None
                }
            cur.close()
            release_db(conn)
    except Exception as e:
        logger.error(f"[API v2] Erro ao obter detalhes do agente {agent_id}: {e}")

    if not agent_data:
        raise HTTPException(status_code=404, detail=f"Agente com ID '{agent_id}' não encontrado.")

    elapsed = (time.perf_counter() - t0) * 1000
    return build_v2_response(data=agent_data, execution_time_ms=elapsed)

@router.post("/bulk-action")
async def execute_bulk_agent_action_v2(payload: BulkActionRequest):
    """Executa ações em lote em múltiplos agentes com relatório de resultado individual."""
    t0 = time.perf_counter()
    results = []
    
    for aid in payload.agent_ids:
        action_res = {
            "agent_id": aid,
            "action": payload.action,
            "success": True,
            "message": f"Ação '{payload.action}' despachada com sucesso"
        }
        try:
            from server_gboc import manager
            if aid in manager.active_connections:
                await manager.send_personal_message(json.dumps({
                    "type": "command",
                    "action": payload.action,
                    "parameters": payload.parameters or {}
                }), aid)
                action_res["status"] = "dispatched"
            else:
                action_res["status"] = "queued_offline"
                action_res["message"] = "Agente offline no momento; ação enfileirada"
        except Exception as ex:
            action_res["success"] = False
            action_res["status"] = "error"
            action_res["message"] = str(ex)
            
        results.append(action_res)
        
    elapsed = (time.perf_counter() - t0) * 1000
    return build_v2_response(
        data={
            "total_requested": len(payload.agent_ids),
            "action": payload.action,
            "results": results
        },
        execution_time_ms=elapsed
    )
