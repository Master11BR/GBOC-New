# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Module: Power Tools Central Server Router
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

logger = logging.getLogger("power_tools_server_router")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from server_gboc import get_db, release_db, manager
except Exception:
    from gboc_server import get_db, release_db, manager

router = APIRouter(prefix="/api/v1/server/power-tools", tags=["Power Tools Central"])


class RemoteScrubRequest(BaseModel):
    agent_id: str
    target_path: Optional[str] = None


class RemoteRDRRequest(BaseModel):
    agent_id: str
    source_image: str
    target_disk: int = 0


class RemoteUSBRequest(BaseModel):
    agent_id: str
    drive_letter: str


@router.get("/bitrot/status")
async def bitrot_global_status():
    """
    Status de integridade contra bitrot de todos os agentes conectados.
    Agrega os últimos resultados de scrubbing de cada agente.
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        # Agentes online e seu último backup de verificação
        cur.execute("""
            SELECT
                a.agent_id,
                a.hostname,
                a.status,
                a.last_heartbeat,
                pt.last_scrub_at,
                pt.integrity_health_pct,
                pt.corrupted_blocks,
                pt.repaired_blocks
            FROM agents a
            LEFT JOIN power_tools_agent_stats pt ON pt.agent_id = a.agent_id
            ORDER BY pt.integrity_health_pct ASC NULLS LAST, a.hostname
        """)
        agents = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        cur.close()

        # Identificar agentes com problemas de integridade
        at_risk = [a for a in agents if a.get("integrity_health_pct") is not None and a["integrity_health_pct"] < 95]
        return {
            "status": "success",
            "total_agents": len(agents),
            "agents_at_risk": len(at_risk),
            "agents": agents,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.post("/bitrot/trigger")
async def trigger_remote_scrub(req: RemoteScrubRequest):
    """
    Aciona remotamente um Bitrot Scrub em um agente específico via WebSocket.
    """
    try:
        command = json.dumps({
            "command": "power_tools.bitrot_scrub",
            "target_path": req.target_path,
            "issued_at": datetime.now().isoformat()
        })
        await manager.send_personal_message(command, req.agent_id)
        return {
            "status": "success",
            "message": f"Bitrot Scrub acionado remotamente no agente '{req.agent_id}'",
            "target_path": req.target_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rdr/status")
async def rdr_global_status():
    """
    Status dos Rapid Delta Restores em andamento em todos os agentes.
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                a.agent_id,
                a.hostname,
                a.status,
                pt.last_rdr_at,
                pt.last_rdr_time_saved_pct,
                pt.last_rdr_sectors_written
            FROM agents a
            LEFT JOIN power_tools_agent_stats pt ON pt.agent_id = a.agent_id
            ORDER BY pt.last_rdr_at DESC NULLS LAST
        """)
        agents = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        cur.close()
        return {
            "status": "success",
            "agents": agents,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.post("/rdr/trigger")
async def trigger_remote_rdr(req: RemoteRDRRequest):
    """
    Aciona remotamente um Rapid Delta Restore em um agente específico.
    """
    try:
        command = json.dumps({
            "command": "power_tools.rdr",
            "source_image": req.source_image,
            "target_disk": req.target_disk,
            "issued_at": datetime.now().isoformat()
        })
        await manager.send_personal_message(command, req.agent_id)
        return {
            "status": "success",
            "message": f"RDR acionado no agente '{req.agent_id}'",
            "source_image": req.source_image,
            "target_disk": req.target_disk
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/usb/create")
async def trigger_remote_usb_creation(req: RemoteUSBRequest):
    """
    Aciona remotamente a criação de USB Rescue Media em um agente específico.
    """
    try:
        command = json.dumps({
            "command": "power_tools.usb_rescue",
            "drive_letter": req.drive_letter,
            "issued_at": datetime.now().isoformat()
        })
        await manager.send_personal_message(command, req.agent_id)
        return {
            "status": "success",
            "message": f"Criação de USB Rescue acionada no agente '{req.agent_id}'",
            "drive_letter": req.drive_letter
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents/{agent_id}/stats")
async def update_power_tools_stats(agent_id: str, request: Request):
    """
    Recebe e persiste estatísticas de Power Tools de um agente específico.
    """
    conn = None
    try:
        body = await request.json()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO power_tools_agent_stats
                (agent_id, last_scrub_at, integrity_health_pct, corrupted_blocks, repaired_blocks,
                 last_rdr_at, last_rdr_time_saved_pct, last_rdr_sectors_written, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, LOCALTIMESTAMP)
            ON CONFLICT (agent_id) DO UPDATE SET
                last_scrub_at = COALESCE(EXCLUDED.last_scrub_at, power_tools_agent_stats.last_scrub_at),
                integrity_health_pct = COALESCE(EXCLUDED.integrity_health_pct, power_tools_agent_stats.integrity_health_pct),
                corrupted_blocks = COALESCE(EXCLUDED.corrupted_blocks, power_tools_agent_stats.corrupted_blocks),
                repaired_blocks = COALESCE(EXCLUDED.repaired_blocks, power_tools_agent_stats.repaired_blocks),
                last_rdr_at = COALESCE(EXCLUDED.last_rdr_at, power_tools_agent_stats.last_rdr_at),
                last_rdr_time_saved_pct = COALESCE(EXCLUDED.last_rdr_time_saved_pct, power_tools_agent_stats.last_rdr_time_saved_pct),
                last_rdr_sectors_written = COALESCE(EXCLUDED.last_rdr_sectors_written, power_tools_agent_stats.last_rdr_sectors_written),
                updated_at = LOCALTIMESTAMP
        """, (
            agent_id,
            body.get("last_scrub_at"),
            body.get("integrity_health_pct"),
            body.get("corrupted_blocks"),
            body.get("repaired_blocks"),
            body.get("last_rdr_at"),
            body.get("last_rdr_time_saved_pct"),
            body.get("last_rdr_sectors_written")
        ))
        conn.commit()
        cur.close()
        return {"status": "success"}
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)
