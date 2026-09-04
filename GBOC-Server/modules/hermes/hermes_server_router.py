# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: Hermes Central Hub — Server-Side (Central WebSocket Hub & Queue Stats)
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================
"""
Hermes Central Hub — GBOC Server

O GBOC Server funciona como o hub central de todos os agentes Hermes.
Responsabilidades:
  - Receber e persister o burst sync dos agentes após reconexão offline
  - Expor visão global de filas offline, conectividade e mesh topology
  - Ordenar operações de auto-cura remotas a agentes específicos
  - Agregar estatísticas de todos os agentes no banco PostgreSQL
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("hermes_server_router")

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


router = APIRouter(prefix="/api/v1/server/hermes", tags=["Hermes Central Hub"])


# ==============================================================================
# Modelos
# ==============================================================================

class HermesHealCommand(BaseModel):
    action: str  # "vss" | "disk" | "services"
    service_names: Optional[List[str]] = None


class BurstSyncPayload(BaseModel):
    agent_id: str
    messages: List[Dict[str, Any]]


# ==============================================================================
# Endpoints
# ==============================================================================

@router.get("/agents")
async def hermes_all_agents():
    """
    Lista todos os agentes registrados com seu status de conectividade
    e estatísticas de fila offline (se disponíveis).
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                a.agent_id,
                a.hostname,
                a.ip_address,
                a.status,
                a.last_heartbeat,
                a.agent_version,
                hs.pending_messages,
                hs.last_burst_sync_at,
                hs.mesh_peers_online,
                hs.throttle_mbps,
                hs.heal_events_count
            FROM agents a
            LEFT JOIN hermes_agent_stats hs ON hs.agent_id = a.agent_id
            ORDER BY a.last_heartbeat DESC NULLS LAST
        """)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        agents = [dict(zip(cols, row)) for row in rows]
        cur.close()
        return {
            "status": "success",
            "agent_count": len(agents),
            "agents": agents,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"[HERMES SERVER] Erro ao listar agentes: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.get("/queue/stats")
async def hermes_queue_stats_global():
    """
    Estatísticas globais de filas offline de todos os agentes conectados.
    Inclui totais de mensagens pendentes e histórico de burst syncs.
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) AS total_agents,
                SUM(COALESCE(pending_messages, 0)) AS total_pending,
                SUM(COALESCE(burst_sync_count, 0)) AS total_burst_syncs,
                MAX(last_burst_sync_at) AS last_burst_sync_any
            FROM hermes_agent_stats
        """)
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        stats = dict(zip(cols, row)) if row else {}

        cur.execute("""
            SELECT agent_id, hostname, pending_messages, last_burst_sync_at, throttle_mbps
            FROM hermes_agent_stats
            JOIN agents USING (agent_id)
            WHERE pending_messages > 0
            ORDER BY pending_messages DESC
            LIMIT 20
        """)
        agents_with_queue = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        cur.close()
        return {
            "status": "success",
            "global": stats,
            "agents_with_pending_queue": agents_with_queue,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"[HERMES SERVER] Erro nas estatísticas de fila: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.get("/mesh")
async def hermes_global_mesh():
    """
    Topologia global da rede mesh de todos os agentes.
    Combina dados de todos os agentes para uma visão de rede unificada.
    """
    # A topologia real é distribuída — o servidor agrega o que os agentes reportam
    # via heartbeat e o campo available_tools / jobs_summary
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT agent_id, hostname, ip_address, status, last_heartbeat,
                   COALESCE(mesh_peers_online, 0) AS mesh_peers_online
            FROM agents a
            LEFT JOIN hermes_agent_stats hs USING (agent_id)
            WHERE status = 'online'
            ORDER BY hostname
        """)
        nodes = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        cur.close()
        return {
            "status": "success",
            "node_count": len(nodes),
            "nodes": nodes,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"[HERMES SERVER] Erro ao obter mesh global: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.post("/heal/{agent_id}")
async def hermes_remote_heal(agent_id: str, cmd: HermesHealCommand):
    """
    Envia um comando de auto-cura remota a um agente específico via WebSocket.
    O agente Hermes executa o reparo e reporta o resultado de volta ao servidor.
    """
    try:
        command_payload = json.dumps({
            "command": "hermes.heal",
            "action": cmd.action,
            "service_names": cmd.service_names,
            "issued_at": datetime.now().isoformat()
        })
        mgr = get_manager()
        if mgr:
            await mgr.send_personal_message(command_payload, agent_id)
        else:
            raise HTTPException(status_code=503, detail="Connection manager não disponível")
        return {
            "status": "success",
            "message": f"Comando de auto-cura '{cmd.action}' enviado ao agente '{agent_id}'",
            "agent_id": agent_id,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao enviar comando: {e}")


@router.post("/burst-sync")
async def hermes_receive_burst_sync(payload: BurstSyncPayload):
    """
    Endpoint chamado pelo agente Hermes durante o Burst Sync após reconexão offline.
    Persiste as mensagens da fila offline do agente no banco PostgreSQL central.
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        stored = 0
        for msg in payload.messages:
            try:
                cur.execute("""
                    INSERT INTO hermes_burst_sync_log
                        (agent_id, sequence_number, event_type, payload_json, synced_at)
                    VALUES (%s, %s, %s, %s, LOCALTIMESTAMP)
                    ON CONFLICT (agent_id, sequence_number) DO NOTHING
                """, (
                    payload.agent_id,
                    msg.get("sequence_number"),
                    msg.get("event_type", "unknown"),
                    json.dumps(msg.get("payload", {}))
                ))
                stored += 1
            except Exception as me:
                logger.warning(f"[HERMES SERVER] Erro ao persistir msg seq={msg.get('sequence_number')}: {me}")
                conn.rollback()

        # Atualizar stats do agente
        cur.execute("""
            INSERT INTO hermes_agent_stats (agent_id, last_burst_sync_at, burst_sync_count, pending_messages)
            VALUES (%s, LOCALTIMESTAMP, 1, 0)
            ON CONFLICT (agent_id) DO UPDATE SET
                last_burst_sync_at = LOCALTIMESTAMP,
                burst_sync_count = COALESCE(hermes_agent_stats.burst_sync_count, 0) + 1,
                pending_messages = 0
        """, (payload.agent_id,))

        conn.commit()
        cur.close()
        return {
            "status": "success",
            "agent_id": payload.agent_id,
            "messages_received": len(payload.messages),
            "messages_stored": stored,
            "acked_sequences": [m.get("sequence_number") for m in payload.messages if m.get("sequence_number")]
        }
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"[HERMES SERVER] Erro no burst sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_db(conn)


@router.post("/agents/{agent_id}/stats")
async def update_hermes_agent_stats(agent_id: str, request: Request):
    """
    Atualiza as estatísticas Hermes de um agente específico (enviado pelo próprio agente no heartbeat).
    """
    conn = None
    try:
        body = await request.json()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO hermes_agent_stats
                (agent_id, pending_messages, mesh_peers_online, throttle_mbps, heal_events_count, updated_at)
            VALUES (%s, %s, %s, %s, %s, LOCALTIMESTAMP)
            ON CONFLICT (agent_id) DO UPDATE SET
                pending_messages = EXCLUDED.pending_messages,
                mesh_peers_online = EXCLUDED.mesh_peers_online,
                throttle_mbps = EXCLUDED.throttle_mbps,
                heal_events_count = EXCLUDED.heal_events_count,
                updated_at = LOCALTIMESTAMP
        """, (
            agent_id,
            body.get("pending_messages", 0),
            body.get("mesh_peers_online", 0),
            body.get("throttle_mbps", 0),
            body.get("heal_events_count", 0)
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
