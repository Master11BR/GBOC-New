#!/usr/bin/env python3
"""
API do módulo isolado de integração com Duplicati.
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from core.integrations.duplicati_native import get_duplicati_native_service

router = APIRouter(prefix="/api/duplicati-native", tags=["duplicati-native"])


@router.get("/status")
async def get_status() -> Dict[str, Any]:
    service = get_duplicati_native_service()
    return {
        "config": service.get_config_summary(),
        "probe": service.probe(),
    }


@router.get("/config")
async def get_config() -> Dict[str, Any]:
    service = get_duplicati_native_service()
    return service.get_config_summary()


@router.post("/config")
async def save_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        service = get_duplicati_native_service()
        cfg = service.save_config(payload)
        return {
            "status": "success",
            "message": "Configuração do Duplicati salva",
            "config": {
                "base_url": cfg.base_url,
                "username": cfg.username,
                "password_masked": service.get_config_summary().get("password_masked", ""),
                "verify_tls": cfg.verify_tls,
                "timeout_seconds": cfg.timeout_seconds,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/discover")
async def discover() -> Dict[str, Any]:
    service = get_duplicati_native_service()
    return {"endpoints": service.discover_endpoints()}


@router.get("/backups")
async def list_backups() -> Dict[str, Any]:
    service = get_duplicati_native_service()
    result = service.list_backups()
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result)
    return result
