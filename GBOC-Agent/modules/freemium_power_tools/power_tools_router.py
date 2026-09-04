# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: Freemium & Open-Source Power Tools Router
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import JSONResponse

from engines.visual_sync_engine import visual_sync_engine
from engines.bitrot_scrub_engine import bitrot_scrub_engine
from engines.virtual_drive_mount_engine import virtual_drive_mount_engine
from engines.rapid_delta_restore_engine import rapid_delta_restore_engine
from engines.linux_snapshots_engine import linux_snapshots_engine
from engines.usb_rescue_creator_engine import usb_rescue_creator_engine

logger = logging.getLogger("gboc_power_tools_router")
router = APIRouter(prefix="/api/v1/power-tools", tags=["Freemium & Open-Source Power Tools"])


# Modelos
class VisualDiffRequest(BaseModel):
    left_path: str = "C:\\Dados\\Producao"
    right_path: str = "D:\\Backup\\Mirror"


class SyncExecRequest(BaseModel):
    left_path: str = "C:\\Dados\\Producao"
    right_path: str = "D:\\Backup\\Mirror"
    sync_mode: str = "MIRROR"


class BitrotScrubRequest(BaseModel):
    target_path: str = "C:\\GBOC-Backups"


class VfsMountRequest(BaseModel):
    repository_url: str = "s3://wasabi/gboc-prod-backups"
    drive_letter: str = "Z:"


class RapidDeltaRequest(BaseModel):
    source_image: str = "C:\\GBOC-Backups\\System_Image_20260829.vhdx"
    target_disk: int = 0


class LinuxSnapRequest(BaseModel):
    dataset_name: str = "rpool/ROOT/pve-1"


class UsbBootCreateRequest(BaseModel):
    drive_letter: str = "E:"


# ── 1. Visual Diff & RealTimeSync ───────────────────────────────────────────

@router.post("/visual-diff/compare")
async def compare_visual_diff(req: VisualDiffRequest):
    """Executa comparação de pastas com Visual Diff Tree."""
    res = visual_sync_engine.compare_directories_visual_diff(left_path=req.left_path, right_path=req.right_path)
    return JSONResponse({"status": "success", "data": res})


@router.post("/visual-diff/sync")
async def execute_visual_sync(req: SyncExecRequest):
    """Executa a sincronização espelho em tempo real."""
    res = visual_sync_engine.execute_sync(left_path=req.left_path, right_path=req.right_path, sync_mode=req.sync_mode)
    return JSONResponse(res)


# ── 2. Bitrot & Reed-Solomon Auto-Healing ───────────────────────────────────

@router.post("/bitrot/scrub")
async def run_bitrot_scrub(req: BitrotScrubRequest):
    """Varre e corrige corrupção silenciosa de dados via Reed-Solomon."""
    res = bitrot_scrub_engine.run_bitrot_scrub(target_repository_path=req.target_path)
    return JSONResponse(res)


# ── 3. Virtual Cloud Drive Mount (Z:\) ──────────────────────────────────────

@router.get("/vfs/drives")
async def list_vfs_drives():
    """Lista drives virtuais de nuvem montados."""
    return JSONResponse({"status": "success", "drives": virtual_drive_mount_engine.list_mounted_drives()})


@router.post("/vfs/mount")
async def mount_vfs_drive(req: VfsMountRequest):
    """Monta repositório de nuvem como letra de drive local Z:\\."""
    res = virtual_drive_mount_engine.mount_virtual_drive(repository_url=req.repository_url, drive_letter=req.drive_letter)
    return JSONResponse(res)


@router.post("/vfs/unmount")
async def unmount_vfs_drive(drive_letter: str = Query("Z:")):
    """Desmonta drive virtual de nuvem."""
    res = virtual_drive_mount_engine.unmount_virtual_drive(drive_letter=drive_letter)
    return JSONResponse(res)


# ── 4. Rapid Delta Restore (RDR) ────────────────────────────────────────────

@router.post("/rapid-delta/restore")
async def execute_rapid_delta_restore(req: RapidDeltaRequest):
    """Executa restauração ultrarrápida de setores delta via NTFS $Bitmap."""
    res = rapid_delta_restore_engine.execute_rapid_delta_restore(source_image_path=req.source_image, target_disk_number=req.target_disk)
    return JSONResponse(res)


# ── 5. Linux BTRFS & ZFS Snapshots ──────────────────────────────────────────

@router.get("/linux-snapshots/list")
async def list_linux_snapshots():
    """Lista subvolumes e snapshots BTRFS / ZFS."""
    return JSONResponse({"status": "success", "data": linux_snapshots_engine.list_subvolume_snapshots()})


@router.post("/linux-snapshots/create")
async def create_linux_snapshot(req: LinuxSnapRequest):
    """Cria snapshot instantâneo de subvolume ZFS/BTRFS."""
    res = linux_snapshots_engine.create_instant_subvolume_snapshot(dataset_name=req.dataset_name)
    return JSONResponse(res)


# ── 6. 1-Click USB Rescue Media Creator ─────────────────────────────────────

@router.get("/usb-rescue/drives")
async def list_usb_drives():
    """Detecta pendrives USB conectados."""
    return JSONResponse({"status": "success", "drives": usb_rescue_creator_engine.detect_usb_drives()})


@router.post("/usb-rescue/create")
async def create_usb_rescue(req: UsbBootCreateRequest):
    """Grava pendrive de boot UEFI/WinPE em 1 clique."""
    res = usb_rescue_creator_engine.create_bootable_usb_media(target_drive_letter=req.drive_letter)
    return JSONResponse(res)
