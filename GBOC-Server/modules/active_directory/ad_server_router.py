# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: Server Active Directory Central Router
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse

try:
    from database import db_manager
    def get_db(): return db_manager.get_connection()
    def release_db(conn): db_manager.release_connection(conn)
except Exception:
    def get_db(): return None
    def release_db(conn): pass

logger = logging.getLogger("gboc_server_ad_module")
router = APIRouter(prefix="/api/v1/active-directory", tags=["Central Active Directory Management"])


@router.get("/summary")
async def get_ad_central_summary():
    """Retorna o resumo central de Controladores de Domínio e backups do Active Directory."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Buscar agentes identificados como Controladores de Domínio ou Windows Server
        cur.execute("SELECT agent_id, hostname, ip_address, status, os_type, last_seen FROM agents WHERE os_type ILIKE '%Windows%' OR os_type ILIKE '%Server%' ORDER BY last_seen DESC LIMIT 50")
        rows = cur.fetchall()
        
        controllers = []
        for r in rows:
            controllers.append({
                "agent_id": r[0],
                "hostname": r[1],
                "ip_address": r[2],
                "status": r[3],
                "os_type": r[4],
                "last_seen": str(r[5]) if r[5] else None
            })
            
        return JSONResponse({
            "status": "success",
            "controllers_count": len(controllers),
            "controllers": controllers
        })
    except Exception as e:
        logger.warning(f"[SERVER AD MODULE] Erro ao consultar controladores do banco: {e}")
        return JSONResponse({"status": "success", "controllers_count": 0, "controllers": []})
    finally:
        if conn: release_db(conn)
