# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Module: SaaS, Kubernetes, Storage Arrays, Cleanroom, Cloud Failover & ITIL Router
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import logging
from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import JSONResponse

from engines.saas_protection_engine import saas_protection_engine
from engines.kubernetes_backup_engine import k8s_backup_engine
from engines.storage_array_engine import storage_array_engine
from engines.cyber_cleanroom_engine import cyber_cleanroom_engine
from engines.cloud_failover_engine import cloud_failover_engine
from engines.itil_sso_engine import itil_sso_engine

logger = logging.getLogger("gboc_saas_cloud_router")
router = APIRouter(prefix="/api/v1/saas-cloud", tags=["SaaS, K8s, Storage Arrays & Cloud Failover"])


# Modelos Pydantic
class SaasBackupRequest(BaseModel):
    provider: str = "microsoft_365"
    services: Optional[List[str]] = None


class K8sBackupRequest(BaseModel):
    namespace: str = "production-apps"
    include_pvcs: bool = True


class StorageArraySnapRequest(BaseModel):
    array_id: str = "netapp-01"
    volume_or_lun: str = "vol_sql_prod_data"


class CleanroomScanRequest(BaseModel):
    snapshot_id: str = "SNAP_SQL_PROD_20260829"


class CloudFailoverRequest(BaseModel):
    provider: str = "AWS" # "AWS" ou "Azure"
    backup_image_path: str = "C:\\GBOC-Backups\\DR_System_20260829.vhdx"
    instance_type: str = "t3.xlarge"
    region: str = "us-east-1"


class ItilTestRequest(BaseModel):
    system_type: str = "servicenow"


# ── 1. SaaS Cloud-Native Endpoints ──────────────────────────────────────────

@router.get("/saas/tenants")
async def get_saas_tenants():
    """Retorna status e conexões de tenants SaaS (M365, Google Workspace, Entra ID)."""
    return JSONResponse({"status": "success", "data": saas_protection_engine.get_saas_tenants_status()})


@router.post("/saas/backup")
async def start_saas_backup(req: SaasBackupRequest):
    """Inicia backup de Microsoft 365 ou Google Workspace."""
    res = saas_protection_engine.start_saas_backup(provider=req.provider, services=req.services)
    return JSONResponse(res)


@router.get("/saas/status/{job_id}")
async def get_saas_job_status(job_id: str):
    """Retorna status de um job de backup SaaS."""
    status = saas_protection_engine.get_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job SaaS não encontrado")
    return JSONResponse({"status": "success", "job": status})


# ── 2. Kubernetes Endpoints ─────────────────────────────────────────────────

@router.get("/k8s/inventory")
async def get_k8s_inventory():
    """Retorna namespaces, PVCs e storage classes do cluster Kubernetes."""
    return JSONResponse({"status": "success", "data": k8s_backup_engine.get_cluster_inventory()})


@router.post("/k8s/backup")
async def start_k8s_backup(req: K8sBackupRequest):
    """Inicia backup de Namespace Kubernetes e CSI Volume Snapshots."""
    res = k8s_backup_engine.start_k8s_backup(namespace=req.namespace, include_pvcs=req.include_pvcs)
    return JSONResponse(res)


@router.get("/k8s/status/{job_id}")
async def get_k8s_job_status(job_id: str):
    """Retorna status de um job de backup Kubernetes."""
    status = k8s_backup_engine.get_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job K8s não encontrado")
    return JSONResponse({"status": "success", "job": status})


# ── 3. Storage Hardware Arrays Endpoints ────────────────────────────────────

@router.get("/storage-arrays/list")
async def list_storage_arrays():
    """Retorna a lista de arrays de storage SAN/NAS configurados (NetApp, Pure, Dell, HPE)."""
    return JSONResponse({"status": "success", "arrays": storage_array_engine.list_storage_arrays()})


@router.post("/storage-arrays/snapshot")
async def trigger_hardware_snapshot(req: StorageArraySnapRequest):
    """Dispara um snapshot de hardware instantâneo (< 2s) no storage."""
    res = storage_array_engine.trigger_hardware_snapshot(array_id=req.array_id, volume_or_lun=req.volume_or_lun)
    return JSONResponse(res)


# ── 4. Cyber Cleanroom & Shannon Entropy Endpoints ──────────────────────────

@router.post("/cleanroom/scan")
async def scan_cyber_cleanroom(req: CleanroomScanRequest):
    """Executa varredura de Entropia de Shannon e regras YARA no snapshot."""
    res = cyber_cleanroom_engine.scan_snapshot_entropy_and_yara(snapshot_id=req.snapshot_id)
    return JSONResponse(res)


# ── 5. Multi-Cloud Direct Failover Endpoints ────────────────────────────────

@router.post("/cloud-failover/launch")
async def launch_cloud_failover(req: CloudFailoverRequest):
    """Executa o 1-Click Failover para AWS EC2 ou Azure VM."""
    if req.provider.upper() == "AWS":
        res = cloud_failover_engine.launch_aws_ec2_failover(
            backup_image_path=req.backup_image_path,
            instance_type=req.instance_type,
            region=req.region
        )
    else:
        res = cloud_failover_engine.launch_azure_vm_failover(
            backup_image_path=req.backup_image_path,
            vm_size="Standard_D4s_v5",
            region="brazilsouth"
        )
    return JSONResponse(res)


# ── 6. ITIL & SSO Endpoints ─────────────────────────────────────────────────

@router.get("/itil/status")
async def get_itil_status():
    """Retorna status das integrações ServiceNow, Jira e SSO SAML/OIDC."""
    return JSONResponse({"status": "success", "data": itil_sso_engine.itil_integrations})


@router.post("/itil/test-incident")
async def test_itil_incident(req: ItilTestRequest):
    """Dispara webhook de teste para ServiceNow ou Jira."""
    res = itil_sso_engine.trigger_test_incident(system_type=req.system_type)
    return JSONResponse(res)
