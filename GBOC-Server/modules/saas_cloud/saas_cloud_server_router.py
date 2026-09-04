# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: SaaS & Cloud Central Server Router
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

logger = logging.getLogger("saas_cloud_server_router")

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


router = APIRouter(prefix="/api/v1/server/saas", tags=["SaaS & Cloud Central"])


class FailoverTriggerRequest(BaseModel):
    agent_id: str
    cloud_provider: str  # "aws" | "azure" | "gcp"
    source_instance_id: str
    target_region: Optional[str] = None


@router.get("/protection/status")
async def saas_protection_global_status():
    """
    Status centralizado de proteção SaaS de todos os agentes.
    Agrega dados de M365, Google Workspace, Entra ID de cada agente.
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        # Relatórios de backup do tipo saas
        cur.execute("""
            SELECT
                a.agent_id,
                a.hostname,
                a.status AS agent_status,
                br.backup_type,
                COUNT(br.report_id) AS backup_count_7d,
                MAX(br.created_at) AS last_backup,
                MAX(CASE WHEN br.status = 'success' THEN br.created_at END) AS last_success,
                SUM(CASE WHEN br.status = 'error' THEN 1 ELSE 0 END) AS errors_7d
            FROM agents a
            LEFT JOIN backup_reports br ON br.agent_id = a.agent_id
                AND br.backup_type IN ('m365', 'google_workspace', 'saas', 'teams', 'sharepoint')
                AND br.created_at > LOCALTIMESTAMP - INTERVAL '7 days'
            GROUP BY a.agent_id, a.hostname, a.status, br.backup_type
            ORDER BY a.hostname
        """)
        rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        cur.close()
        return {
            "status": "success",
            "saas_entries": len(rows),
            "saas_protection": rows,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.get("/kubernetes/pvcs")
async def kubernetes_pvcs_global():
    """
    Status dos backups de Persistent Volume Claims (PVCs) Kubernetes por cluster/agente.
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                a.agent_id,
                a.hostname,
                COUNT(br.report_id) AS pvc_backups_7d,
                MAX(CASE WHEN br.status = 'success' THEN br.created_at END) AS last_pvc_backup,
                SUM(CASE WHEN br.status = 'error' THEN 1 ELSE 0 END) AS errors_7d
            FROM agents a
            LEFT JOIN backup_reports br ON br.agent_id = a.agent_id
                AND br.backup_type IN ('kubernetes', 'k8s', 'pvc')
                AND br.created_at > LOCALTIMESTAMP - INTERVAL '7 days'
            GROUP BY a.agent_id, a.hostname
            ORDER BY a.hostname
        """)
        rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        cur.close()
        return {
            "status": "success",
            "kubernetes_agents": len(rows),
            "kubernetes_pvcs": rows,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.get("/cloud-failover/status")
async def cloud_failover_status():
    """
    Status de failovers multi-cloud ativos e histórico recente.
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT agent_id, hostname, status, last_heartbeat
            FROM agents
            WHERE status = 'online'
            ORDER BY hostname
        """)
        agents = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        cur.close()
        return {
            "status": "success",
            "agents_online": len(agents),
            "failover_ready_agents": agents,
            "cloud_providers_supported": ["AWS EC2", "Azure VM", "GCP Compute"],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.post("/cloud-failover/trigger")
async def trigger_cloud_failover(req: FailoverTriggerRequest):
    """
    Aciona 1-Click Cloud Failover em um agente remoto via WebSocket.
    """
    try:
        command = json.dumps({
            "command": "cloud.failover",
            "cloud_provider": req.cloud_provider,
            "source_instance_id": req.source_instance_id,
            "target_region": req.target_region,
            "issued_at": datetime.now().isoformat()
        })
        mgr = get_manager()
        if mgr:
            await mgr.send_personal_message(command, req.agent_id)
        else:
            raise HTTPException(status_code=503, detail="Connection manager não disponível")
        return {
            "status": "success",
            "message": f"Failover {req.cloud_provider} iniciado no agente '{req.agent_id}'",
            "details": req.dict()
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
