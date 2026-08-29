#!/usr/bin/env python3
"""
GBOC 13.2.0 - Database Backup API
CRUD for database connections, trigger backup/restore, test-restore sandbox, replication.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging
from decimal import Decimal
from datetime import datetime
import json

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/database-backup", tags=["DatabaseBackup"])


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


# ─── Models ────────────────────────────────────────────────────────

class ConnectionCreate(BaseModel):
    name: str
    db_type: str = "postgresql"
    host: str = "localhost"
    port: int = 5432
    database_name: str
    username: str = ""
    password: str = ""
    options: Dict[str, Any] = {}


class ConnectionUpdate(BaseModel):
    name: Optional[str] = None
    db_type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database_name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


# ─── Connections ───────────────────────────────────────────────────

@router.get("/connections")
async def list_connections():
    from engines.database_backup import list_connections
    return {"connections": _clean(list_connections())}


@router.post("/connections")
async def create_connection(body: ConnectionCreate):
    from engines.database_backup import create_connection
    result = create_connection(body.dict())
    return {"connection": _clean(result)}


@router.put("/connections/{conn_id}")
async def update_connection(conn_id: int, body: ConnectionUpdate):
    from engines.database_backup import get_connection, update_connection
    existing = get_connection(conn_id)
    if not existing:
        raise HTTPException(404, "Conexão não encontrada")
    merged = {**existing, **{k: v for k, v in body.dict().items() if v is not None}}
    result = update_connection(conn_id, merged)
    return {"connection": _clean(result)}


@router.delete("/connections/{conn_id}")
async def delete_connection(conn_id: int):
    from engines.database_backup import delete_connection
    delete_connection(conn_id)
    return {"deleted": True}


@router.post("/connections/{conn_id}/test")
async def test_connection(conn_id: int):
    from engines.database_backup import test_connection
    return _clean(test_connection(conn_id))


# ─── Backup Operations ────────────────────────────────────────────

@router.post("/connections/{conn_id}/backup")
async def trigger_backup(conn_id: int, output_dir: Optional[str] = None):
    from engines.database_backup import run_database_backup
    result = run_database_backup(conn_id, output_dir)
    if not result.get('success'):
        raise HTTPException(500, result.get('error', 'Backup failed'))
    return _clean(result)


@router.get("/backups")
async def list_backups(connection_id: Optional[int] = None, limit: int = 50):
    from engines.database_backup import list_backups
    return {"backups": _clean(list_backups(connection_id, limit))}


@router.delete("/backups/{backup_id}")
async def delete_backup(backup_id: int):
    from engines.database_backup import delete_backup
    return delete_backup(backup_id)


# ─── Restore Operations ───────────────────────────────────────────

@router.post("/backups/{backup_id}/restore")
async def restore_backup(backup_id: int, target_conn_id: Optional[int] = None):
    from engines.database_backup import restore_database
    result = restore_database(backup_id, target_conn_id)
    if not result.get('success'):
        raise HTTPException(500, result.get('error', 'Restore failed'))
    return _clean(result)


@router.post("/backups/{backup_id}/test-restore")
async def test_restore(backup_id: int):
    from engines.database_backup import test_restore
    result = test_restore(backup_id)
    return _clean(result)


# ─── Replication ───────────────────────────────────────────────────

class ReplicateRequest(BaseModel):
    target_dir: str


@router.post("/backups/{backup_id}/replicate")
async def replicate_backup(backup_id: int, body: ReplicateRequest):
    from engines.database_backup import replicate_backup
    result = replicate_backup(backup_id, body.target_dir)
    if not result.get('success'):
        raise HTTPException(500, result.get('error', 'Replication failed'))
    return _clean(result)


# ─── Statistics ────────────────────────────────────────────────────

@router.get("/statistics")
async def backup_statistics():
    from engines.database_backup import _query
    total = _query("SELECT count(*) as cnt FROM database_backups")[0]['cnt']
    ok = _query("SELECT count(*) as cnt FROM database_backups WHERE status='completed'")[0]['cnt']
    failed = _query("SELECT count(*) as cnt FROM database_backups WHERE status='failed'")[0]['cnt']
    size = _query("SELECT COALESCE(SUM(file_size),0) as total FROM database_backups WHERE status='completed'")[0]['total']
    conns = _query("SELECT count(*) as cnt FROM database_connections")[0]['cnt']

    return _clean({
        "total_backups": total,
        "completed": ok,
        "failed": failed,
        "total_size_bytes": size,
        "connections": conns,
        "success_rate": round(ok / total * 100, 1) if total else 0
    })

