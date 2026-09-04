# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: Hermes Agent Router — REST API for the Hermes Edge Agent
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from engines.hermes_queue_engine import hermes_queue_engine
from engines.hermes_self_heal_engine import hermes_self_heal_engine
from engines.hermes_mesh_engine import hermes_mesh_engine
from engines.hermes_bandwidth_engine import hermes_bandwidth_engine

logger = logging.getLogger("hermes_router")
router = APIRouter(prefix="/api/v1/hermes", tags=["Hermes Agent"])


# ==============================================================================
# Modelos
# ==============================================================================

class ThrottleRequest(BaseModel):
    mbps: Optional[float] = None  # None = modo automático


class VSSRepairRequest(BaseModel):
    pass


class DiskGuardRequest(BaseModel):
    target_path: Optional[str] = None


class ServiceWatchdogRequest(BaseModel):
    service_names: Optional[list] = None


class QueueFlushRequest(BaseModel):
    max_batch: int = 500


# ==============================================================================
# Status Global do Hermes
# ==============================================================================

@router.get("/status")
async def hermes_status():
    """
    Retorna o status consolidado de todos os pilares do Hermes Agent.
    """
    try:
        return {
            "status": "operational",
            "agent": "Hermes Edge Agent v14.0.0",
            "pillars": {
                "store_and_forward_queue": hermes_queue_engine.get_status(),
                "self_healing_watchdog": hermes_self_heal_engine.get_status(),
                "p2p_lan_mesh": hermes_mesh_engine.get_status(),
                "bandwidth_control": hermes_bandwidth_engine.get_status()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# Pilar 1 — Fila Offline (Store-and-Forward)
# ==============================================================================

@router.get("/queue/status")
async def queue_status():
    """Status detalhado da fila offline do Hermes."""
    try:
        return hermes_queue_engine.get_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/flush")
async def queue_flush(req: QueueFlushRequest):
    """
    Retorna o próximo lote de mensagens pendentes na fila offline para entrega.
    Utilizado pelo Hermes WebSocket Engine para burst sync ao servidor.
    """
    try:
        batch = hermes_queue_engine.get_pending_batch(max_count=req.max_batch)
        return {
            "status": "success",
            "batch_size": len(batch),
            "messages": batch
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/ack")
async def queue_ack(request: Request):
    """Confirma a entrega de mensagens ao servidor (ack por sequence_number)."""
    try:
        body = await request.json()
        sequence_numbers = body.get("sequence_numbers", [])
        if not sequence_numbers:
            raise HTTPException(status_code=400, detail="sequence_numbers não informados")
        acked = hermes_queue_engine.ack_messages(sequence_numbers)
        return {"status": "success", "acked_count": acked}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/gc")
async def queue_gc():
    """Executa o garbage collector da fila offline (remove mensagens acked antigas)."""
    try:
        removed = hermes_queue_engine.run_gc()
        return {"status": "success", "records_removed": removed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# Pilar 2 — Auto-Cura (Self-Healing Watchdog)
# ==============================================================================

@router.post("/self-heal/vss")
async def heal_vss():
    """
    Detecta e repara VSS Writers problemáticos (Failed / Waiting for completion).
    Executa o reparo sem reiniciar o servidor host.
    """
    try:
        result = hermes_self_heal_engine.repair_vss_writers()
        return {"status": "success", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/self-heal/disk")
async def heal_disk(req: DiskGuardRequest):
    """
    Executa o disk guard manual: verifica o espaço em disco e expurga
    arquivos temporários seguros se o uso estiver acima do limiar crítico.
    """
    try:
        result = hermes_self_heal_engine.run_disk_guard(target_path=req.target_path)
        return {"status": "success", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/self-heal/services")
async def heal_services(req: ServiceWatchdogRequest):
    """
    Verifica e reinicia serviços críticos do Windows se estiverem parados
    (vss, swprv, schedule, lanmanworkstation por padrão).
    """
    try:
        result = hermes_self_heal_engine.check_and_restart_services(
            service_names=req.service_names
        )
        return {"status": "success", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/self-heal/log")
async def heal_log(limit: int = 100):
    """Retorna o histórico de eventos de auto-cura executados pelo Hermes."""
    try:
        events = hermes_self_heal_engine.get_heal_log(limit=limit)
        return {
            "status": "success",
            "event_count": len(events),
            "events": events
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# Pilar 3 — P2P LAN Mesh
# ==============================================================================

@router.get("/mesh/topology")
async def mesh_topology():
    """Retorna a topologia completa da rede mesh P2P de agentes GBOC na LAN."""
    try:
        return hermes_mesh_engine.get_topology()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mesh/discover")
async def mesh_discover():
    """
    Executa uma varredura imediata de agentes GBOC na sub-rede local via mDNS/UDP.
    Aguarda 5 segundos por respostas antes de retornar a lista de peers encontrados.
    """
    try:
        result = hermes_mesh_engine.discover_now()
        return {"status": "success", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# Pilar 4 — Controle de Bandwidth Adaptativo
# ==============================================================================

@router.get("/bandwidth/profile")
async def bandwidth_profile():
    """
    Retorna o perfil de largura de banda aprendido pelo Hermes (heatmap 7d × 24h)
    com o throttle recomendado para cada hora da semana.
    """
    try:
        return hermes_bandwidth_engine.get_bandwidth_profile()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bandwidth/throttle")
async def bandwidth_set_throttle(req: ThrottleRequest):
    """
    Define o limite de bandwidth para backups manualmente.
    Passe mbps=null para retornar ao modo automático adaptativo.
    """
    try:
        result = hermes_bandwidth_engine.set_manual_throttle(req.mbps)
        return {"status": "success", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bandwidth/estimate")
async def bandwidth_estimate(size_mb: float = 1024.0):
    """
    Estima o tempo de transferência para um backup de tamanho informado
    com base no throttle atual do Hermes.
    """
    try:
        size_bytes = int(size_mb * 1024 * 1024)
        result = hermes_bandwidth_engine.estimate_transfer_duration(size_bytes)
        return {"status": "success", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
