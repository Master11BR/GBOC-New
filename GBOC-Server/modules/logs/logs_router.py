# GBOC System v14.7.3 Enterprise Edition
# Module: Server Audit Logs Router
# Modular Architecture: modules/logs/logs_router.py

import logging
from typing import Optional
from fastapi import APIRouter, Query, Request
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


@router.get("/stats")
async def get_logs_stats():
    """Estatísticas reais dos logs sincronizados dos agentes e servidor."""
    conn = None
    cur = None
    try:
        conn = get_db()
        if not conn:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "message": "Banco de dados não disponível"}
            )

        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE UPPER(level) IN ('ERROR', 'CRITICAL', 'FATAL') OR message ILIKE '%[error]%' OR message ILIKE '%falha%') as errors,
                COUNT(*) FILTER (WHERE UPPER(level) = 'WARNING' OR message ILIKE '%[warn%' OR message ILIKE '%alerta%') as warnings,
                COUNT(*) FILTER (WHERE UPPER(level) IN ('SUCCESS', 'OK') OR message ILIKE '%sucess%' OR message ILIKE '%conclui%') as success,
                COUNT(*) FILTER (WHERE UPPER(level) = 'INFO' AND NOT (
                    message ILIKE '%[error]%' OR message ILIKE '%falha%' OR
                    message ILIKE '%[warn%' OR message ILIKE '%alerta%' OR
                    message ILIKE '%sucess%' OR message ILIKE '%conclui%'
                )) as info,
                COUNT(DISTINCT agent_id) as agents_with_logs,
                MIN(timestamp) as oldest,
                MAX(timestamp) as newest
            FROM agent_logs
            WHERE timestamp >= (LOCALTIMESTAMP - INTERVAL '30 days')
        """)
        stats = cur.fetchone()
        res = dict(stats) if hasattr(stats, 'keys') else {}
        for k in ['oldest', 'newest']:
            if res.get(k) and hasattr(res[k], 'isoformat'):
                res[k] = res[k].isoformat()
            elif res.get(k):
                res[k] = str(res[k])

        return {"status": "success", **res}
    except Exception as e:
        logger.error(f"[LOGS MODULE] Erro ao obter estatísticas: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
    finally:
        if cur:
            try: cur.close()
            except Exception: pass
        if conn:
            release_db(conn)


@router.get("")
async def get_logs_list(
    level: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    type: Optional[str] = Query(None, description="all | success | info | warning | error"),
    hours: Optional[int] = Query(None, ge=1, le=8760),
    limit: int = Query(300, ge=1, le=1000)
):
    """Retorna os logs reais dos agentes e servidor com suporte completo a filtros."""
    conn = None
    cur = None
    try:
        conn = get_db()
        if not conn:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "message": "Banco de dados não disponível", "logs": []}
            )

        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()

        conditions = []
        params = []

        if hours:
            conditions.append(f"al.timestamp >= (LOCALTIMESTAMP - INTERVAL '{int(hours)} hours')")

        if level:
            conditions.append("UPPER(al.level) = UPPER(%s)")
            params.append(level)

        t = (type or "").strip().lower()
        if t == "error":
            conditions.append("(al.level ILIKE 'err%%' OR al.level ILIKE 'crit%%' OR al.level ILIKE 'fatal%%' OR al.message ILIKE '%%[error]%%' OR al.message ILIKE '%%[critical]%%' OR al.message ILIKE '%%falha%%' OR al.message ILIKE '%%error:%%')")
        elif t == "warning":
            conditions.append("(al.level ILIKE 'warn%%' OR al.message ILIKE '%%[warning]%%' OR al.message ILIKE '%%[warn]%%' OR al.message ILIKE '%%alerta%%' OR al.message ILIKE '%%threshold=%%')")
        elif t == "success":
            conditions.append("(al.level ILIKE 'succ%%' OR UPPER(al.level) = 'OK' OR al.message ILIKE '%%[success]%%' OR al.message ILIKE '%%[ok]%%' OR al.message ILIKE '%%sucesso%%' OR al.message ILIKE '%%concluíd%%' OR al.message ILIKE '%%concluido%%')")
        elif t == "info":
            conditions.append("(NOT (al.level ILIKE 'err%%' OR al.level ILIKE 'crit%%' OR al.level ILIKE 'fatal%%' OR al.level ILIKE 'warn%%' OR al.level ILIKE 'succ%%' OR UPPER(al.level) = 'OK' OR al.message ILIKE '%%[error]%%' OR al.message ILIKE '%%falha%%' OR al.message ILIKE '%%[warning]%%' OR al.message ILIKE '%%[warn]%%' OR al.message ILIKE '%%alerta%%' OR al.message ILIKE '%%[success]%%' OR al.message ILIKE '%%sucesso%%' OR al.message ILIKE '%%concluíd%%' OR al.message ILIKE '%%concluido%%'))")

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
                   al.timestamp, COALESCE(a.hostname, al.agent_id, 'Servidor') as agent_name
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

        return JSONResponse({
            "status": "success",
            "logs": logs,
            "count": len(logs),
            "total": len(logs)
        })
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


@router.get("/agents/{agent_id}")
async def get_agent_logs_by_id(
    agent_id: str,
    level: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    hours: int = Query(168, ge=1, le=8760)
):
    """Consulta logs específicos de um determinado agente."""
    conn = None
    cur = None
    try:
        conn = get_db()
        if not conn:
            return JSONResponse(status_code=503, content={"status": "error", "message": "Banco de dados não disponível", "logs": []})

        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        conditions = ["agent_id = %s", f"timestamp >= (LOCALTIMESTAMP - INTERVAL '{int(hours)} hours')"]
        params = [agent_id]
        if level:
            conditions.append("UPPER(level) = UPPER(%s)")
            params.append(level)

        where = " AND ".join(conditions)
        cur.execute(f"""
            SELECT id, level, source, message, details, timestamp
            FROM agent_logs WHERE {where}
            ORDER BY timestamp DESC LIMIT %s
        """, params + [limit])
        logs = cur.fetchall()
        serialized = []
        for log in logs:
            ld = dict(log) if hasattr(log, 'keys') else {}
            if ld.get('timestamp') and hasattr(ld['timestamp'], 'isoformat'):
                ld['timestamp'] = ld['timestamp'].isoformat()
            elif ld.get('timestamp'):
                ld['timestamp'] = str(ld['timestamp'])
            serialized.append(ld)

        return {"status": "success", "logs": serialized, "total": len(serialized), "agent_id": agent_id}
    except Exception as e:
        logger.error(f"[LOGS MODULE] Erro ao consultar logs do agente {agent_id}: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e), "logs": []})
    finally:
        if cur:
            try: cur.close()
            except Exception: pass
        if conn:
            release_db(conn)
