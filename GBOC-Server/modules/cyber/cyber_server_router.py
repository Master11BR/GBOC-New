# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: Cyber Cleanroom & ITIL Central Server Router
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("cyber_server_router")

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


router = APIRouter(prefix="/api/v1/server/cyber", tags=["Cyber Cleanroom & ITIL Central"])


class CleanroomTriggerRequest(BaseModel):
    agent_id: str
    target_path: Optional[str] = None


class ITILWebhookRequest(BaseModel):
    agent_id: str
    incident_title: str
    severity: str = "medium"  # "low" | "medium" | "high" | "critical"


@router.get("/threats")
async def cyber_global_threats():
    """
    Lista de todas as ameaças detectadas por todos os agentes
    (Shannon Entropy anomalies, YARA matches, ransomware events).
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        # Eventos de sistema com tipo ransomware / threat / anomaly
        cur.execute("""
            SELECT
                se.event_id,
                se.event_type,
                se.message,
                se.agent_hostname,
                se.created_at,
                se.is_read
            FROM system_events se
            WHERE se.event_type IN ('ransomware', 'threat', 'anomaly', 'malware', 'cyber', 'entropy_alert', 'yara_match')
            ORDER BY se.created_at DESC
            LIMIT 200
        """)
        threats = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

        # Contagem de agentes afetados
        affected_agents = list({t["agent_hostname"] for t in threats if t.get("agent_hostname")})

        cur.close()
        return {
            "status": "success",
            "threat_count": len(threats),
            "affected_agents": len(affected_agents),
            "affected_agent_hostnames": affected_agents,
            "threats": threats,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.post("/cleanroom/trigger")
async def trigger_remote_cleanroom(req: CleanroomTriggerRequest):
    """
    Aciona o Cyber Cleanroom (Shannon Entropy + YARA scan) em um agente remoto via WebSocket.
    """
    try:
        command = json.dumps({
            "command": "cyber.cleanroom",
            "target_path": req.target_path,
            "issued_at": datetime.now().isoformat()
        })
        mgr = get_manager()
        if mgr:
            await mgr.send_personal_message(command, req.agent_id)
        else:
            raise HTTPException(status_code=503, detail="Connection manager não disponível")
        return {
            "status": "success",
            "message": f"Cyber Cleanroom acionado no agente '{req.agent_id}'",
            "target_path": req.target_path
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/itil/incidents")
async def itil_incidents_global():
    """
    Lista incidentes ITSM (ServiceNow / Jira) abertos por falhas de backup.
    Agrega system_events de tipo 'backup_failed' ou 'error' como incidentes.
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                se.event_id,
                se.event_type,
                se.message,
                se.agent_hostname,
                se.created_at,
                se.is_read
            FROM system_events se
            WHERE se.event_type IN ('backup_failed', 'error', 'alert', 'critical')
              AND se.is_read = FALSE
            ORDER BY se.created_at DESC
            LIMIT 100
        """)
        incidents = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        cur.close()
        return {
            "status": "success",
            "open_incidents": len(incidents),
            "incidents": incidents,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.post("/itil/webhook")
async def itil_manual_webhook(req: ITILWebhookRequest):
    """
    Dispara um webhook ITIL manualmente para um incidente de backup.
    """
    try:
        # A webhook real é configurada no ITIL SSO Engine do agente
        command = json.dumps({
            "command": "itil.webhook",
            "incident_title": req.incident_title,
            "severity": req.severity,
            "issued_at": datetime.now().isoformat()
        })
        mgr = get_manager()
        if mgr:
            await mgr.send_personal_message(command, req.agent_id)
        else:
            raise HTTPException(status_code=503, detail="Connection manager não disponível")
        return {
            "status": "success",
            "message": f"Webhook ITIL disparado no agente '{req.agent_id}'",
            "incident_title": req.incident_title,
            "severity": req.severity
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/threats/{event_id}/acknowledge")
async def acknowledge_threat(event_id: int):
    """Marca uma ameaça/evento como lida (acknowledged)."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE system_events SET is_read = TRUE WHERE event_id = %s",
            (event_id,)
        )
        conn.commit()
        cur.close()
        return {"status": "success", "event_id": event_id, "acknowledged": True}
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)
