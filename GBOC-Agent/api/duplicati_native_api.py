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


@router.get("/backups/{backup_id}/filesets")
async def list_backup_filesets(backup_id: str) -> Dict[str, Any]:
    """Lista snapshots / pontos de recuperação de um backup do Duplicati."""
    service = get_duplicati_native_service()
    snapshots = service.list_filesets(backup_id)
    return {
        "status": "success",
        "backup_id": backup_id,
        "count": len(snapshots),
        "snapshots": snapshots
    }


# ── Controle de Jobs ──────────────────────────────────────────────────────────

@router.get("/progress")
async def get_progress() -> Dict[str, Any]:
    """Estado de progresso atual do Duplicati."""
    service = get_duplicati_native_service()
    result = service.get_progress()
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result)
    return result


@router.get("/serverstate")
async def get_server_state() -> Dict[str, Any]:
    """Estado do servidor Duplicati (scheduled, running, paused...)."""
    service = get_duplicati_native_service()
    result = service.get_server_state()
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result)
    return result


@router.post("/backups/{backup_id}/run")
async def run_backup(backup_id: str) -> Dict[str, Any]:
    """Inicia um job de backup manualmente."""
    service = get_duplicati_native_service()
    result = service.run_backup(backup_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result)
    return result


@router.post("/backups/{backup_id}/stop")
async def stop_backup(backup_id: str, abort: bool = False) -> Dict[str, Any]:
    """Para ou aborta um job de backup em execução. Use abort=true para forçar."""
    service = get_duplicati_native_service()
    result = service.stop_backup(backup_id, abort=abort)
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result)
    return result


@router.get("/backups/{backup_id}/log")
async def get_backup_log(backup_id: str, page_size: int = 20) -> Dict[str, Any]:
    """Log de execuções de um job específico."""
    service = get_duplicati_native_service()
    result = service.get_backup_log(backup_id, page_size=page_size)
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result)
    return result


@router.post("/server/pause")
async def pause_server() -> Dict[str, Any]:
    """Pausa o agendador do Duplicati."""
    service = get_duplicati_native_service()
    result = service.pause_server()
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result)
    return result


@router.post("/server/resume")
async def resume_server() -> Dict[str, Any]:
    """Retoma o agendador do Duplicati."""
    service = get_duplicati_native_service()
    result = service.resume_server()
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result)
    return result


# ── Agendamento ───────────────────────────────────────────────────────────────

@router.post("/backups/{backup_id}/schedule")
async def set_schedule(backup_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Define ou atualiza o agendamento automático de um job de backup.

    Corpo esperado:
    ```json
    {
      "time": "02:00",
      "repeat": "1D",
      "allowed_days": ["mon","tue","wed","thu","fri"],
      "tags": []
    }
    ```
    """
    service = get_duplicati_native_service()
    result = service.set_schedule(backup_id, payload)
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result)
    return result


# ── Restauração ───────────────────────────────────────────────────────────────

@router.post("/backups/{backup_id}/restore")
async def restore_backup(backup_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Inicia a restauração de arquivos de um backup.

    Corpo esperado:
    ```json
    {
      "restore_path": "C:\\RestoreDir",
      "paths": [],
      "overwrite": false,
      "time": "now",
      "passphrase": ""
    }
    ```
    """
    service = get_duplicati_native_service()
    result = service.restore_backup(backup_id, payload)
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result)
    return result


# ── Resultado da última execução ──────────────────────────────────────────────

@router.get("/backups/{backup_id}/lastresult")
async def get_last_result(backup_id: str) -> Dict[str, Any]:
    """Retorna o ParsedResult e erros da última execução do backup."""
    service = get_duplicati_native_service()
    result = service.get_last_result(backup_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result)
    return result
