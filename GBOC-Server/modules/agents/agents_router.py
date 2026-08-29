# GBOC System v13.2.0 Enterprise Edition
# Module: Agents Router (Multi-Tenant filtered list)

import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

try:
    from database import db_manager
    def get_db(): return db_manager.get_connection()
    def release_db(conn): db_manager.release_connection(conn)
except Exception:
    def get_db(): return None
    def release_db(conn): pass

logger = logging.getLogger("gboc_agents_module")
router = APIRouter(prefix="/api/v1/agents", tags=["Agentes"])

def _get_current_user_from_req(request: Request) -> Optional[Dict[str, Any]]:
    """Obtém o usuário logado com base no token da requisição."""
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.cookies.get("gboc_server_token")
    
    if not token:
        return None
        
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT u.id, u.username, u.display_name, u.role, u.tenant_id
            FROM server_auth_tokens t
            JOIN server_auth_users u ON t.user_id = u.id
            WHERE t.token = %s AND t.expires_at > LOCALTIMESTAMP
        """, (token,))
        row = cur.fetchone()
        cur.close()
        if row:
            return {"id": row[0], "username": row[1], "display_name": row[2], "role": row[3], "tenant_id": row[4]}
    except Exception as e:
        logger.warning(f"[AGENTS MODULE] Erro ao autenticar via token local: {e}")
    finally:
        if conn: release_db(conn)
    return None

@router.get("")
async def get_agents_list(request: Request):
    """Retorna a lista de agentes cadastrados, filtrados pelo tenant_id do usuário logado se aplicável."""
    conn = None
    try:
        u = _get_current_user_from_req(request)
        tenant_id = u.get("tenant_id") if u else None

        conn = get_db()
        cur = conn.cursor()
        if tenant_id:
            cur.execute("""
                SELECT agent_id, hostname, ip_address, os_info, agent_version, registered_at, last_heartbeat, status, cpu_usage, ram_usage, disk_usage, jobs_count 
                FROM agents 
                WHERE tenant_id = %s
                ORDER BY registered_at DESC
            """, (tenant_id,))
        else:
            cur.execute("""
                SELECT agent_id, hostname, ip_address, os_info, agent_version, registered_at, last_heartbeat, status, cpu_usage, ram_usage, disk_usage, jobs_count 
                FROM agents 
                ORDER BY registered_at DESC
            """)
            
        rows = cur.fetchall()
        agents = []
        for r in rows:
            agents.append({
                "agent_id": r[0],
                "hostname": r[1],
                "ip_address": r[2],
                "os_info": r[3],
                "agent_version": r[4],
                "registered_at": str(r[5]) if r[5] else None,
                "last_heartbeat": str(r[6]) if r[6] else None,
                "status": r[7] or "offline",
                "cpu_usage": r[8] or 0,
                "ram_usage": r[9] or 0,
                "disk_usage": r[10] or 0,
                "jobs_count": r[11] or 0
            })
        return JSONResponse({"status": "success", "agents": agents})
    except Exception as e:
        logger.error(f"[AGENTS MODULE] Erro ao listar agentes: {e}")
        return JSONResponse({"status": "success", "agents": []})
    finally:
        if conn: release_db(conn)
