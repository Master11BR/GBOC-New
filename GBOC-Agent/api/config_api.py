#!/usr/bin/env python3
"""
GBOC 11.7c - Configuration Export/Import API
Export/import system configuration, versioned snapshots, diff between configs.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging
import json
import io
from decimal import Decimal
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/config", tags=["Configuration"])


class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        return super().default(o)


def _clean(obj):
    return json.loads(json.dumps(obj, cls=_Enc))


# ─── Models ───────────────────────────────────────────────────────

class SnapshotCreate(BaseModel):
    name: str
    description: str = ""


class ImportRequest(BaseModel):
    config_data: Dict[str, Any]
    dry_run: bool = True


class DiffRequest(BaseModel):
    snapshot_a_id: int
    snapshot_b_id: int


# ─── Export ───────────────────────────────────────────────────────

@router.get("/export")
async def export_config(include_sensitive: bool = False):
    """Export the full system configuration as JSON."""
    from engines.config_manager import export_config as _export
    config = _export(include_sensitive=include_sensitive)
    return _clean(config)


@router.get("/export/download")
async def export_config_download(include_sensitive: bool = False):
    """Download configuration as a JSON file."""
    from engines.config_manager import export_config as _export
    config = _export(include_sensitive=include_sensitive)
    content = json.dumps(config, cls=_Enc, indent=2, ensure_ascii=False)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return StreamingResponse(
        io.BytesIO(content.encode('utf-8')),
        media_type='application/json',
        headers={'Content-Disposition': f'attachment; filename="gboc_config_{timestamp}.json"'}
    )


# ─── Import ───────────────────────────────────────────────────────

@router.post("/import")
async def import_config(body: ImportRequest):
    """Import a configuration from JSON data.
    Use dry_run=true to preview changes without applying them."""
    from engines.config_manager import import_config as _import
    result = _import(body.config_data, dry_run=body.dry_run)
    return _clean(result)


@router.post("/import/upload")
async def import_config_upload(file: UploadFile = File(...), dry_run: bool = True):
    """Import configuration from an uploaded JSON file."""
    try:
        content = await file.read()
        config_data = json.loads(content.decode('utf-8'))
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON file: {e}")
    except Exception as e:
        raise HTTPException(400, f"Error reading file: {e}")

    from engines.config_manager import import_config as _import
    result = _import(config_data, dry_run=dry_run)
    return _clean(result)


# ─── Snapshots ────────────────────────────────────────────────────

@router.get("/snapshots")
async def list_snapshots():
    """List all configuration snapshots."""
    from engines.config_manager import list_snapshots
    return {"snapshots": _clean(list_snapshots())}


@router.post("/snapshots")
async def create_snapshot(body: SnapshotCreate):
    """Create a new configuration snapshot (point-in-time backup of config)."""
    from engines.config_manager import save_snapshot
    result = save_snapshot(body.name, body.description)
    return _clean(result)


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot(snapshot_id: int):
    """Get a specific snapshot with full configuration data."""
    from engines.config_manager import get_snapshot as _get
    snap = _get(snapshot_id)
    if not snap:
        raise HTTPException(404, "Snapshot not found")
    return {"snapshot": _clean(snap)}


@router.delete("/snapshots/{snapshot_id}")
async def delete_snapshot(snapshot_id: int):
    """Delete a configuration snapshot."""
    from engines.config_manager import get_snapshot as _get, delete_snapshot as _del
    if not _get(snapshot_id):
        raise HTTPException(404, "Snapshot not found")
    _del(snapshot_id)
    return {"deleted": True}


@router.get("/snapshots/{snapshot_id}/download")
async def download_snapshot(snapshot_id: int):
    """Download a snapshot as a JSON file."""
    from engines.config_manager import get_snapshot as _get
    snap = _get(snapshot_id)
    if not snap:
        raise HTTPException(404, "Snapshot not found")
    config_data = snap.get('config_data', {})
    content = json.dumps(config_data, cls=_Enc, indent=2, ensure_ascii=False)
    return StreamingResponse(
        io.BytesIO(content.encode('utf-8')),
        media_type='application/json',
        headers={'Content-Disposition': f'attachment; filename="gboc_snapshot_{snapshot_id}.json"'}
    )


# ─── Diff ─────────────────────────────────────────────────────────

@router.post("/diff")
async def diff_snapshots(body: DiffRequest):
    """Compare two configuration snapshots."""
    from engines.config_manager import get_snapshot as _get, diff_configs
    snap_a = _get(body.snapshot_a_id)
    snap_b = _get(body.snapshot_b_id)
    if not snap_a:
        raise HTTPException(404, f"Snapshot {body.snapshot_a_id} not found")
    if not snap_b:
        raise HTTPException(404, f"Snapshot {body.snapshot_b_id} not found")

    result = diff_configs(snap_a.get('config_data', {}), snap_b.get('config_data', {}))
    result['snapshot_a'] = {'id': body.snapshot_a_id, 'name': snap_a.get('name'), 'created_at': snap_a.get('created_at')}
    result['snapshot_b'] = {'id': body.snapshot_b_id, 'name': snap_b.get('name'), 'created_at': snap_b.get('created_at')}
    return _clean(result)


@router.get("/diff/current/{snapshot_id}")
async def diff_current_vs_snapshot(snapshot_id: int):
    """Compare current configuration against a saved snapshot."""
    from engines.config_manager import get_snapshot as _get, export_config as _export, diff_configs
    snap = _get(snapshot_id)
    if not snap:
        raise HTTPException(404, "Snapshot not found")
    current = _export(include_sensitive=False)
    result = diff_configs(snap.get('config_data', {}), current)
    result['snapshot'] = {'id': snapshot_id, 'name': snap.get('name'), 'created_at': snap.get('created_at')}
    result['compared_to'] = 'current_config'
    return _clean(result)

