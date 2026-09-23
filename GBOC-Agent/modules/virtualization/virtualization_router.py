# ==============================================================================
# GBOC System v14.6.0 Enterprise Edition
# Module: Virtualization Management Router (VMware ESXi, Hyper-V RCT & Proxmox)
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import asyncio
import logging
from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from engines.vmware_hypervisor_engine import vmware_engine, hyperv_engine

logger = logging.getLogger("gboc_virtualization_router")
router = APIRouter(prefix="/api/v1/virtualization", tags=["Virtualization & Agentless Hypervisor"])


class VmwareConnectRequest(BaseModel):
    host: str
    user: str = "administrator@vsphere.local"
    password: str = ""
    port: int = 443
    ignore_ssl: bool = True


class HypervCheckpointRequest(BaseModel):
    vm_name: str


@router.post("/vmware/connect")
async def connect_vmware(req: VmwareConnectRequest):
    """Testa autenticação real com VMware vCenter ou ESXi."""
    res = await asyncio.to_thread(
        vmware_engine.test_vmware_connection,
        host=req.host,
        user=req.user,
        password=req.password,
        port=req.port,
        ignore_ssl=req.ignore_ssl
    )
    if res.get("status") != "success":
        return JSONResponse(status_code=400, content=res)
    return JSONResponse(res)


@router.post("/vmware/vms")
async def list_vmware_vms(req: VmwareConnectRequest):
    """Lista o inventário real de máquinas virtuais do host VMware vCenter / ESXi."""
    res = await asyncio.to_thread(
        vmware_engine.list_vmware_vms,
        host=req.host,
        user=req.user,
        password=req.password,
        port=req.port,
        ignore_ssl=req.ignore_ssl
    )
    if res.get("status") != "success":
        return JSONResponse(status_code=400, content=res)
    return JSONResponse(res)


@router.get("/hyperv/status")
async def get_hyperv_status(refresh: bool = False):
    """Verifica se o Hyper-V (vmms) está operacional no host de forma não-bloqueante."""
    status = await asyncio.to_thread(hyperv_engine.check_hyperv_installed, force_refresh=refresh)
    return JSONResponse(status)


@router.get("/hyperv/vms")
async def list_hyperv_vms(refresh: bool = False):
    """Lista todas as máquinas virtuais Hyper-V reais no host com discos e RCT de forma não-bloqueante."""
    res = await asyncio.to_thread(hyperv_engine.list_hyperv_vms, force_refresh=refresh)
    return JSONResponse(res)


@router.post("/hyperv/checkpoint")
async def create_hyperv_checkpoint(req: HypervCheckpointRequest):
    """Cria Production Checkpoint consistente no Hyper-V sem instalar agente na VM."""
    res = await asyncio.to_thread(hyperv_engine.create_agentless_rct_checkpoint, req.vm_name)
    if res.get("status") != "success":
        return JSONResponse(status_code=400, content=res)
    return JSONResponse(res)


@router.get("/inventory")
async def get_consolidated_inventory(refresh: bool = False):
    """
    Retorna o inventário consolidado de hipervisores ativos no ambiente local.
    Zero-Mock: Consulta o estado real do Hyper-V local de forma assíncrona.
    """
    hv_status = await asyncio.to_thread(hyperv_engine.check_hyperv_installed, force_refresh=refresh)
    if hv_status.get("installed") and hv_status.get("running"):
        vms_resp = await asyncio.to_thread(hyperv_engine.list_hyperv_vms, force_refresh=refresh)
        hv_vms = vms_resp.get("vms", [])
    else:
        hv_vms = []

    return JSONResponse({
        "status": "success",
        "hypervisors": {
            "hyperv": {
                "installed": hv_status.get("installed", False),
                "running": hv_status.get("running", False),
                "vms_count": len(hv_vms),
                "vms": hv_vms
            },
            "vmware": {
                "configured": False,
                "message": "Conecte-se a um vCenter/ESXi para listar máquinas virtuais VMware."
            }
        },
        "total_vms": len(hv_vms)
    })
