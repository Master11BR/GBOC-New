#!/usr/bin/env python3
"""
API do controle de rede e de carga dos backups (agendado + automático + proteção da máquina) e do vigia de
travamento. As regras de horário (limitar/pausar) continuam em /api/agent-ops/operation; aqui também podem
ser gravadas pelo campo "bandwidth".
"""
import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/network", tags=["Controle de rede"])


def _full_status() -> Dict[str, Any]:
    from engines import network_governor as ng
    from engines import operation_settings as ops
    out = {"status": "success", "governor": ng.governor.status(), "config": ng.load_config(),
           "bandwidth": (ops.load(force=True).get(ops.KEY_BANDWIDTH) or {"default_mbps": 0, "rules": []})}
    try:
        from engines import backup_consistency as bc
        out["consistency"] = {**bc.load_config(), "admin": bc.is_admin()}
    except Exception:
        out["consistency"] = None
    try:
        from core import hang_watchdog
        out["watchdog"] = hang_watchdog.status()
    except Exception:
        out["watchdog"] = None
    return out


@router.get("/status")
async def network_status() -> Dict[str, Any]:
    return await asyncio.to_thread(_full_status)


@router.put("/config")
async def network_config(request: Request) -> Dict[str, Any]:
    """{"config": {...modo, auto, resource...}, "bandwidth": {"default_mbps", "rules": [{days,start,end,mbps|action:"pause"}]}}"""
    from engines import network_governor as ng
    from engines import operation_settings as ops
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON inválido")
    try:
        if "bandwidth" in body:
            await asyncio.to_thread(ops.save, None, body["bandwidth"])
        if "config" in body:
            await asyncio.to_thread(ng.save_config, body["config"])
        if "consistency" in body:
            from engines import backup_consistency as bc
            await asyncio.to_thread(bc.save_config, body["consistency"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    await asyncio.to_thread(ng.governor.tick)
    return await asyncio.to_thread(_full_status)


@router.post("/pause")
async def network_pause(request: Request) -> Dict[str, Any]:
    """Pausa manual dos backups por {"minutes": N} (expira sozinha)."""
    from engines import network_governor as ng
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        minutes = float((body or {}).get("minutes") or 60)
    except (TypeError, ValueError):
        raise HTTPException(400, "minutes inválido")
    await asyncio.to_thread(ng.governor.pause_manual, minutes)
    return await asyncio.to_thread(_full_status)


@router.post("/resume")
async def network_resume() -> Dict[str, Any]:
    from engines import network_governor as ng
    await asyncio.to_thread(ng.governor.resume_manual)
    return await asyncio.to_thread(_full_status)
