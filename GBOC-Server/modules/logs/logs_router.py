# GBOC System v13.0.0 Enterprise Edition
# Module: Server Audit Logs Router

import logging
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

try:
    from database import db_manager
    def get_db(): return db_manager.get_connection()
    def release_db(conn): db_manager.release_connection(conn)
except Exception:
    def get_db(): return None
    def release_db(conn): pass

try:
    from psycopg2.extras import RealDictCursor
except Exception:
    RealDictCursor = None

logger = logging.getLogger("gboc_logs_module")
router = APIRouter(prefix="/api/v1/logs", tags=["Logs & Auditoria"])

@router.get("")
async def get_logs_list(
    level: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500)
):
    """Retorna os logs de auditoria e eventos reais do sistema e agentes."""
    conn = None
    cur = None
    try:
        conn = get_db()
        if not conn:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "message": "Banco de dados não disponível", "logs": []}
            )

        if RealDictCursor:
            cur = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cur = conn.cursor()

        conditions = []
        params = []

        if level:
            conditions.append("UPPER(al.level) = UPPER(%s)")
            params.append(level)
        if agent_id:
            conditions.append("al.agent_id = %s")
            params.append(agent_id)
        if source:
            conditions.append("al.source ILIKE %s")
            params.append(f"%{source}%")
        if search:
            conditions.append("(al.message ILIKE %s OR al.details ILIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
            SELECT al.id, al.agent_id, al.level, al.source, al.message, al.details,
                   al.timestamp, a.hostname as agent_name
            FROM agent_logs al
            LEFT JOIN agents a ON al.agent_id = a.agent_id
            {where_clause}
            ORDER BY al.timestamp DESC
            LIMIT %s
        """
        cur.execute(query, params + [limit])
        rows = cur.fetchall()

        logs = []
        for r in rows:
            row_dict = dict(r) if hasattr(r, 'keys') else {
                "id": r[0], "agent_id": r[1], "level": r[2], "source": r[3],
                "message": r[4], "details": r[5], "timestamp": r[6], "agent_name": r[7]
            }
            if row_dict.get("timestamp") and hasattr(row_dict["timestamp"], "isoformat"):
                row_dict["timestamp"] = row_dict["timestamp"].isoformat()
            elif row_dict.get("timestamp"):
                row_dict["timestamp"] = str(row_dict["timestamp"])
            logs.append(row_dict)

        return JSONResponse({"status": "success", "logs": logs, "count": len(logs)})
    except Exception as e:
        logger.error(f"[LOGS MODULE] Erro ao buscar logs: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Erro ao consultar logs: {str(e)}", "logs": []}
        )
    finally:
        if cur:
            try: cur.close()
            except Exception: pass
        if conn:
            release_db(conn)

