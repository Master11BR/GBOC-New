# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: CDP Central Server Router
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("cdp_server_router")

def get_db():
    mod = sys.modules.get("server_gboc") or sys.modules.get("__main__")
    if mod and hasattr(mod, "get_db"):
        return mod.get_db()
    try:
        from server_gboc import get_db as _gdb
        return _gdb()
    except Exception:
        from gboc_server import get_db as _gdb
        return _gdb()


def release_db(conn):
    mod = sys.modules.get("server_gboc") or sys.modules.get("__main__")
    if mod and hasattr(mod, "release_db"):
        return mod.release_db(conn)
    try:
        from server_gboc import release_db as _rdb
        return _rdb(conn)
    except Exception:
        from gboc_server import release_db as _rdb
        return _rdb(conn)


def get_manager():
    mod = sys.modules.get("server_gboc") or sys.modules.get("__main__")
    if mod and hasattr(mod, "manager"):
        return mod.manager
    try:
        from server_gboc import manager as _mgr
        return _mgr
    except Exception:
        from gboc_server import manager as _mgr
        return _mgr


router = APIRouter(prefix="/api/v1/server/cdp", tags=["CDP & Enterprise DB Central"])


class RemoteRollbackRequest(BaseModel):
    agent_id: str
    target_point_in_time: str  # ISO datetime
    database_name: Optional[str] = None


@router.get("/status")
async def cdp_global_status():
    """
    Status CDP de todos os agentes: RPO atual, última captura de micro-journal,
    e status de bancos enterprise (Oracle RMAN, SAP HANA, IBM DB2).
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        # Recuperar últimas execuções de backup por agente para calcular RPO real
        cur.execute("""
            SELECT
                a.agent_id,
                a.hostname,
                a.status,
                a.last_heartbeat,
                MAX(br.end_time) AS last_backup_end,
                MIN(EXTRACT(EPOCH FROM (LOCALTIMESTAMP - br.end_time)) / 60) AS rpo_minutes_approx,
                COUNT(CASE WHEN br.status = 'success' THEN 1 END) AS success_count_24h
            FROM agents a
            LEFT JOIN backup_reports br ON br.agent_id = a.agent_id
                AND br.created_at > LOCALTIMESTAMP - INTERVAL '24 hours'
            WHERE a.status = 'online'
            GROUP BY a.agent_id, a.hostname, a.status, a.last_heartbeat
            ORDER BY rpo_minutes_approx ASC NULLS LAST
        """)
        agents_cdp = []
        for row in cur.fetchall():
            cols = [d[0] for d in cur.description]
            agent = dict(zip(cols, row))
            rpo = agent.get("rpo_minutes_approx")
            agent["rpo_status"] = (
                "critical" if rpo is None or rpo > 240 else
                "warning" if rpo > 60 else
                "good"
            )
            agents_cdp.append(agent)
        cur.close()
        return {
            "status": "success",
            "cdp_enabled_agents": len(agents_cdp),
            "agents": agents_cdp,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.get("/databases")
async def cdp_databases_status():
    """
    Status dos backups de bancos enterprise por agente.
    Agrupa os relatórios de backup por tipo (Oracle, HANA, DB2, PostgreSQL, MSSQL).
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                a.agent_id,
                a.hostname,
                br.backup_type,
                COUNT(br.report_id) AS backup_count,
                MAX(br.created_at) AS last_backup,
                MAX(CASE WHEN br.status = 'success' THEN br.created_at END) AS last_success,
                SUM(CASE WHEN br.status = 'error' THEN 1 ELSE 0 END) AS error_count
            FROM agents a
            JOIN backup_reports br ON br.agent_id = a.agent_id
            WHERE br.backup_type IN ('oracle_rman', 'sap_hana', 'ibm_db2', 'postgresql', 'mssql', 'database')
            GROUP BY a.agent_id, a.hostname, br.backup_type
            ORDER BY a.hostname, br.backup_type
        """)
        rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        cur.close()
        return {
            "status": "success",
            "database_backup_entries": len(rows),
            "databases": rows,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.post("/rollback")
async def cdp_remote_rollback(req: RemoteRollbackRequest):
    """
    Solicita um rollback Point-in-Time a um agente remoto via WebSocket.
    """
    try:
        command = json.dumps({
            "command": "cdp.rollback",
            "target_point_in_time": req.target_point_in_time,
            "database_name": req.database_name,
            "issued_at": datetime.now().isoformat()
        })
        mgr = get_manager()
        if mgr:
            await mgr.send_personal_message(command, req.agent_id)
        else:
            raise HTTPException(status_code=503, detail="Connection manager não disponível")
        return {
            "status": "success",
            "message": f"Comando de rollback CDP enviado ao agente '{req.agent_id}'",
            "target_point_in_time": req.target_point_in_time,
            "issued_at": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
