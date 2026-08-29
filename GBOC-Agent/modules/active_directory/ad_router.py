# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Module: Active Directory Dedicated Backup & Recovery Router
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import JSONResponse

from engines.ad_backup_engine import ad_backup_engine
from engines.ad_granular_explorer import ad_granular_explorer

logger = logging.getLogger("gboc_ad_module")
router = APIRouter(prefix="/api/v1/active-directory", tags=["Active Directory Dedicated Backup"])


class AdBackupStartRequest(BaseModel):
    backup_name: Optional[str] = None
    include_sysvol: bool = True
    include_registry: bool = True
    include_dns: bool = True


class AdRestoreStartRequest(BaseModel):
    snapshot_name: str
    restore_mode: str = "non-authoritative"
    restore_sysvol: bool = True
    restore_registry: bool = True


class AdGranularRestoreRequest(BaseModel):
    object_dn: str
    object_type: str = "User"
    password_reset: Optional[str] = None


class AuthoritativeScriptRequest(BaseModel):
    target_ou_dn: str


@router.get("/topology")
async def get_ad_topology():
    """Retorna topologia completa do Active Directory (Floresta, Domínio, FSMO Roles)."""
    try:
        top = ad_backup_engine.get_ad_topology()
        return JSONResponse({"status": "success", "topology": top})
    except Exception as e:
        logger.error(f"Erro ao obter topologia do AD: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.get("/health")
async def get_ad_health():
    """Retorna saúde do Active Directory, status de replicação e compartilhamentos."""
    try:
        health = ad_backup_engine.get_ad_health()
        return JSONResponse({"status": "success", "health": health})
    except Exception as e:
        logger.error(f"Erro ao consultar saúde do AD: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/backup/start")
async def start_ad_backup(req: AdBackupStartRequest):
    """Inicia processo de backup a quente do Active Directory (NTDS, SYSVOL, Registry)."""
    try:
        res = ad_backup_engine.start_ad_backup(
            backup_name=req.backup_name,
            include_sysvol=req.include_sysvol,
            include_registry=req.include_registry,
            include_dns=req.include_dns
        )
        return JSONResponse(res)
    except Exception as e:
        logger.error(f"Erro ao iniciar backup do AD: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/restore/start")
async def start_ad_restore(req: AdRestoreStartRequest):
    """Inicia processo de restauração do Active Directory (Não-Autoritativa ou DSRM Staging)."""
    try:
        res = ad_backup_engine.start_ad_restore(
            snapshot_name=req.snapshot_name,
            restore_mode=req.restore_mode,
            restore_sysvol=req.restore_sysvol,
            restore_registry=req.restore_registry
        )
        return JSONResponse(res)
    except Exception as e:
        logger.error(f"Erro ao iniciar restauração do AD: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.get("/backup/status/{job_id}")
@router.get("/restore/status/{job_id}")
async def get_ad_job_status(job_id: str):
    """Retorna status e progresso em tempo real de uma tarefa de backup ou restore do AD."""
    status = ad_backup_engine.get_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Tarefa do Active Directory não encontrada")
    return JSONResponse({"status": "success", "job": status})


@router.get("/backup/history")
async def list_ad_backup_history():
    """Retorna o histórico de backups do Active Directory disponíveis em disco."""
    try:
        history = ad_backup_engine.list_ad_backup_history()
        return JSONResponse({"status": "success", "history": history, "total": len(history)})
    except Exception as e:
        logger.error(f"Erro ao listar histórico de backups do AD: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e), "history": []})


@router.delete("/backup/snapshot/{snapshot_name}")
async def delete_ad_snapshot(snapshot_name: str):
    """Exclui um snapshot de backup do Active Directory."""
    success = ad_backup_engine.delete_ad_snapshot(snapshot_name)
    if success:
        return JSONResponse({"status": "success", "message": f"Snapshot '{snapshot_name}' excluído com sucesso."})
    return JSONResponse(status_code=404, content={"status": "error", "message": "Snapshot não encontrado."})


@router.get("/objects")
async def list_ad_objects(filter: str = Query("all"), search: str = Query("")):
    """Pesquisa objetos granulares do Active Directory (Usuários, Grupos, OUs, GPOs)."""
    try:
        res = ad_granular_explorer.list_ad_objects_from_live_or_snapshot(
            filter_type=filter,
            search_query=search
        )
        return JSONResponse(res)
    except Exception as e:
        logger.error(f"Erro ao pesquisar objetos do AD: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e), "objects": []})


@router.post("/objects/restore")
async def restore_ad_object(req: AdGranularRestoreRequest):
    """Restauração granular de um objeto específico no Active Directory (Item-Level Restore)."""
    try:
        res = ad_granular_explorer.restore_granular_ad_object(
            object_dn=req.object_dn,
            object_type=req.object_type,
            password_reset=req.password_reset
        )
        return JSONResponse(res)
    except Exception as e:
        logger.error(f"Erro ao restaurar objeto do AD: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/authoritative-script")
async def generate_authoritative_restore_script(req: AuthoritativeScriptRequest):
    """Gera script ntdsutil e guia para restauração autoritativa de OU."""
    try:
        res = ad_backup_engine.generate_authoritative_restore_script(req.target_ou_dn)
        return JSONResponse({"status": "success", "data": res})
    except Exception as e:
        logger.error(f"Erro ao gerar script de restauração autoritativa: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
