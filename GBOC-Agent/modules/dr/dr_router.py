# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: Agent Disaster Recovery Router
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import JSONResponse

from engines.disaster_recovery_engine import dr_engine
from engines.universal_restore import universal_restore_engine
from engines.ad_granular_explorer import ad_granular_explorer
from engines.instant_vm_boot import instant_vm_boot_engine
from engines.virtual_lab_engine import virtual_lab_engine

logger = logging.getLogger("gboc_agent_dr")
router = APIRouter(prefix="/api/v1/dr", tags=["Agent Disaster Recovery"])


class P2VRequest(BaseModel):
    disk_number: int
    target_path: str
    format_type: str = "VHDX"
    is_dynamic: bool = True


class SystemStateRequest(BaseModel):
    target_folder: Optional[str] = None
    include_ad: bool = True


class BootMediaRequest(BaseModel):
    media_type: str = "winpe"
    embed_drivers: bool = True


class UniversalRestoreRequest(BaseModel):
    target_volume: str
    drivers_folder: Optional[str] = None


class AdRestoreObjectRequest(BaseModel):
    object_dn: str
    object_type: str = "User"
    password_reset: Optional[str] = None


class InstantVmStartRequest(BaseModel):
    source_vhdx_path: str
    vm_name: Optional[str] = None
    memory_mb: int = 4096
    cpu_cores: int = 2
    hypervisor: str = "Hyper-V"


class VirtualLabTestRequest(BaseModel):
    snapshot_id: str
    vm_name: Optional[str] = None


# ── Discos & Diagnóstico ──────────────────────────────────────────────────────

@router.get("/disks")
async def list_physical_disks():
    """Retorna a lista de discos físicos e partições reais do host."""
    try:
        disks = dr_engine.get_physical_disks()
        return JSONResponse({"status": "success", "disks": disks, "total": len(disks)})
    except Exception as e:
        logger.error(f"Erro ao listar discos físicos: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e), "disks": []})


@router.get("/system-info")
async def get_system_dr_info():
    """Retorna diagnóstico de Disaster Recovery, Active Directory e status de VSS Writers."""
    try:
        info = dr_engine.get_system_dr_info()
        return JSONResponse({"status": "success", "data": info})
    except Exception as e:
        logger.error(f"Erro ao obter informações de DR do sistema: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.get("/readiness")
async def get_dr_readiness():
    """Retorna o DR Readiness Score e auditoria de conformidade."""
    try:
        readiness = dr_engine.calculate_dr_readiness()
        return JSONResponse({"status": "success", "readiness": readiness})
    except Exception as e:
        logger.error(f"Erro ao calcular prontidão de DR: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


# ── P2V, System State & Mídia de Boot ─────────────────────────────────────────

@router.post("/p2v/start")
async def start_p2v(req: P2VRequest):
    """Inicia processo de conversão P2V (Physical-to-Virtual) para VHDX."""
    try:
        res = dr_engine.start_p2v_conversion(
            disk_number=req.disk_number,
            target_path=req.target_path,
            format_type=req.format_type,
            is_dynamic=req.is_dynamic
        )
        return JSONResponse(res)
    except Exception as e:
        logger.error(f"Erro ao iniciar P2V: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.get("/p2v/status/{job_id}")
@router.get("/job/status/{job_id}")
async def get_dr_job_status(job_id: str):
    """Retorna status, progresso e streaming de logs de uma tarefa de DR."""
    status = dr_engine.get_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Tarefa de DR não encontrada")
    return JSONResponse({"status": "success", "job": status})


@router.post("/job/cancel/{job_id}")
async def cancel_dr_job(job_id: str):
    """Cancela uma operação ativa de DR."""
    success = dr_engine.cancel_job(job_id)
    if success:
        return JSONResponse({"status": "success", "message": f"Tarefa {job_id} cancelada com sucesso"})
    return JSONResponse(status_code=400, content={"status": "error", "message": "Não foi possível cancelar a tarefa ou ela já foi finalizada"})


@router.post("/system-state/start")
async def start_system_state_backup(req: SystemStateRequest):
    """Inicia backup a quente do System State e Active Directory."""
    try:
        res = dr_engine.start_system_state_backup(
            target_folder=req.target_folder,
            include_ad=req.include_ad
        )
        return JSONResponse(res)
    except Exception as e:
        logger.error(f"Erro ao iniciar backup System State: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/boot-media/build")
async def build_boot_media(req: BootMediaRequest):
    """Inicia criação do GBOC Recovery Environment ISO e extração de drivers nativos."""
    try:
        res = dr_engine.start_boot_media_build(
            media_type=req.media_type,
            embed_drivers=req.embed_drivers
        )
        return JSONResponse(res)
    except Exception as e:
        logger.error(f"Erro ao iniciar criação da mídia de boot: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


# ── Universal Hardware Restore ───────────────────────────────────────────────

@router.post("/universal-restore/inject")
async def inject_universal_restore(req: UniversalRestoreRequest):
    """Injeta drivers e ativa serviços críticos de boot na hive de registro offline."""
    try:
        res = universal_restore_engine.inject_drivers_and_fix_hal(
            target_volume=req.target_volume,
            drivers_folder=req.drivers_folder
        )
        return JSONResponse(res)
    except Exception as e:
        logger.error(f"Erro no Universal Restore: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


# ── Active Directory Granular Explorer ───────────────────────────────────────

@router.get("/ad-explorer/objects")
async def list_ad_objects(filter: str = Query("all"), search: str = Query("")):
    """Pesquisa objetos granulares do Active Directory (Usuários, Grupos, GPOs)."""
    try:
        res = ad_granular_explorer.list_ad_objects_from_live_or_snapshot(
            filter_type=filter,
            search_query=search
        )
        return JSONResponse(res)
    except Exception as e:
        logger.error(f"Erro ao consultar objetos do AD: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e), "objects": []})


@router.post("/ad-explorer/restore-object")
async def restore_ad_object(req: AdRestoreObjectRequest):
    """Restaura granularmente um objeto no Active Directory (Item-Level Restore)."""
    try:
        res = ad_granular_explorer.restore_granular_ad_object(
            object_dn=req.object_dn,
            object_type=req.object_type,
            password_reset=req.password_reset
        )
        return JSONResponse(res)
    except Exception as e:
        logger.error(f"Erro na restauração granular de objeto do AD: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


# ── Instant VM Boot ──────────────────────────────────────────────────────────

@router.post("/instant-vm/start")
async def start_instant_vm(req: InstantVmStartRequest):
    """Inicializa instantaneamente uma VM a partir de um arquivo VHDX com camada CoW."""
    try:
        res = instant_vm_boot_engine.start_instant_vm(
            source_vhdx_path=req.source_vhdx_path,
            vm_name=req.vm_name,
            memory_mb=req.memory_mb,
            cpu_cores=req.cpu_cores,
            hypervisor=req.hypervisor
        )
        return JSONResponse({"status": "success", "instance": res})
    except Exception as e:
        logger.error(f"Erro no Instant VM Boot: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.get("/instant-vm/list")
async def list_instant_vms():
    """Lista todas as VMs instantâneas ativas."""
    vms = instant_vm_boot_engine.list_instant_vms()
    return JSONResponse({"status": "success", "instances": vms, "count": len(vms)})


@router.post("/instant-vm/stop/{instance_id}")
async def stop_instant_vm(instance_id: str):
    """Para e desaloca uma VM instantânea."""
    success = instant_vm_boot_engine.stop_instant_vm(instance_id)
    if success:
        return JSONResponse({"status": "success", "message": f"Instância {instance_id} finalizada com sucesso."})
    return JSONResponse(status_code=404, content={"status": "error", "message": "Instância não encontrada."})


# ── Virtual Lab Sandbox ──────────────────────────────────────────────────────

@router.post("/virtual-lab/test")
async def run_virtual_lab_test(req: VirtualLabTestRequest):
    """Executa verificação automatizada de boot em Virtual Lab com rede isolada anti-colisão."""
    try:
        res = virtual_lab_engine.run_isolated_boot_verification(
            snapshot_id=req.snapshot_id,
            vm_name=req.vm_name
        )
        return JSONResponse(res)
    except Exception as e:
        logger.error(f"Erro no Virtual Lab: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


# ── Exportar Runbook ─────────────────────────────────────────────────────────

@router.post("/export")
async def export_dr_plan(request: Request):
    """Exporta o plano consolidado de Disaster Recovery do agente."""
    readiness = dr_engine.calculate_dr_readiness()
    disks = dr_engine.get_physical_disks()
    sys_info = dr_engine.get_system_dr_info()
    return JSONResponse({
        "status": "success",
        "message": "Plano de DR exportado com sucesso.",
        "dr_plan": {
            "version": "14.0.0 Enterprise",
            "system": sys_info,
            "disks": disks,
            "readiness": readiness,
            "generated_at": datetime.now().isoformat()
        }
    })
