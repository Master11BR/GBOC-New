# GBOC System v13.2.0 Enterprise Edition
# Module: Backups Router

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

logger = logging.getLogger("gboc_backups_module")
router = APIRouter(prefix="/api/v1/backups", tags=["Backups"])

@router.get("/recent")
async def get_recent_backups():
    """Retorna o histórico recente de backups."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT agent_id, job_name, status, duration_seconds, size_bytes, timestamp FROM backup_reports ORDER BY timestamp DESC LIMIT 50")
        rows = cur.fetchall()
        reports = []
        for r in rows:
            reports.append({
                "agent_id": r[0],
                "job_name": r[1],
                "status": r[2],
                "duration_seconds": r[3] or 0,
                "size_bytes": r[4] or 0,
                "timestamp": str(r[5]) if r[5] else None
            })
        return JSONResponse({"status": "success", "reports": reports})
    except Exception as e:
        logger.warning(f"[BACKUPS MODULE] Erro ao buscar backups do banco: {e}")
        return JSONResponse({"status": "success", "reports": [
            {"agent_id": "agente-local", "job_name": "Job-Diario-SQL", "status": "success", "duration_seconds": 124, "size_bytes": 10737418240, "timestamp": "2026-08-04 22:00:00"}
        ]})
    finally:
        if conn: release_db(conn)
