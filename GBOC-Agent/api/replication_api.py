#!/usr/bin/env python3
"""
GBOC 11.7c - Replication API
CRUD for replication policies, trigger replication, 3-2-1 status, history.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging
import json
from decimal import Decimal
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/replication", tags=["Replication"])


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

class PolicyCreate(BaseModel):
    name: str
    source_repo_id: int
    target_repo_id: int
    enabled: bool = True
    schedule_cron: str = "0 2 * * *"
    verify_after_copy: bool = True


class PolicyUpdate(BaseModel):
    name: Optional[str] = None
    source_repo_id: Optional[int] = None
    target_repo_id: Optional[int] = None
    enabled: Optional[bool] = None
    schedule_cron: Optional[str] = None
    verify_after_copy: Optional[bool] = None


# ─── CRUD ─────────────────────────────────────────────────────────

@router.get("/policies")
async def list_policies():
    """List all replication policies."""
    from engines.backup_replicator import list_policies
    return {"policies": _clean(list_policies())}


@router.get("/policies/{policy_id}")
async def get_policy(policy_id: int):
    """Get a specific replication policy."""
    from engines.backup_replicator import get_policy as _get
    policy = _get(policy_id)
    if not policy:
        raise HTTPException(404, "Policy not found")
    return {"policy": _clean(policy)}


@router.post("/policies")
async def create_policy(body: PolicyCreate):
    """Create a new replication policy."""
    from engines.backup_replicator import create_policy
    try:
        result = create_policy(body.dict())
        return {"policy": _clean(result)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/policies/{policy_id}")
async def update_policy(policy_id: int, body: PolicyUpdate):
    """Update a replication policy."""
    from engines.backup_replicator import get_policy as _get, update_policy as _update
    if not _get(policy_id):
        raise HTTPException(404, "Policy not found")
    result = _update(policy_id, {k: v for k, v in body.dict().items() if v is not None})
    return {"policy": _clean(result)}


@router.delete("/policies/{policy_id}")
async def delete_policy(policy_id: int):
    """Delete a replication policy."""
    from engines.backup_replicator import get_policy as _get, delete_policy as _del
    if not _get(policy_id):
        raise HTTPException(404, "Policy not found")
    _del(policy_id)
    return {"deleted": True}


# ─── Execution ────────────────────────────────────────────────────

@router.post("/policies/{policy_id}/run")
async def trigger_replication(policy_id: int):
    """Trigger replication for a policy."""
    from engines.backup_replicator import get_policy as _get, run_replication
    if not _get(policy_id):
        raise HTTPException(404, "Policy not found")
    try:
        result = run_replication(policy_id)
        return _clean(result)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Replication failed: {e}")


# ─── History & Status ─────────────────────────────────────────────

@router.get("/history")
async def replication_history(policy_id: Optional[int] = None, limit: int = 20):
    """Get replication execution history."""
    from engines.backup_replicator import get_history
    return {"history": _clean(get_history(policy_id, limit))}


@router.get("/321-status")
async def three_two_one_status():
    """Check 3-2-1 rule compliance for all backup tasks."""
    from engines.backup_replicator import get_321_status
    return _clean(get_321_status())


# ─── Aliases for frontend compatibility (rules = policies) ────────

@router.get("/stats")
async def replication_stats():
    """Aggregated replication statistics."""
    try:
        from engines.backup_replicator import list_policies, get_history
        policies = list_policies()
        history = get_history(None, 100)
        syncing = sum(1 for p in policies if p.get('status') == 'syncing')
        total_bytes = sum(h.get('bytes_transferred', 0) or 0 for h in history)
        errors_24h = sum(1 for h in history
                         if h.get('status') == 'error' and h.get('completed_at')
                         and (datetime.now() - datetime.fromisoformat(str(h['completed_at']))).total_seconds() < 86400)
        return {
            "total_rules": len(policies),
            "syncing": syncing,
            "total_bytes_replicated": total_bytes,
            "errors_24h": errors_24h,
        }
    except Exception as e:
        logger.warning(f"Replication stats fallback: {e}")
        return {"total_rules": 0, "syncing": 0, "total_bytes_replicated": 0, "errors_24h": 0}


@router.get("/rules")
async def list_rules():
    """Alias: list replication rules (= policies with extra fields for UI)."""
    from engines.backup_replicator import list_policies
    policies = list_policies()
    rules = []
    for p in policies:
        rules.append({
            "id": p.get("id"),
            "name": p.get("name", ""),
            "source_repo": p.get("source_repo_id"),
            "source_name": p.get("source_name", ""),
            "dest_type": p.get("dest_type", "local"),
            "dest_path": p.get("dest_path", ""),
            "frequency": p.get("schedule_cron", ""),
            "mode": p.get("mode", "full"),
            "status": p.get("status", "idle"),
            "total_bytes": p.get("total_bytes", 0),
            "last_sync": p.get("last_run"),
            "enabled": p.get("enabled", True),
        })
    return {"rules": _clean(rules)}


class RuleCreate(BaseModel):
    name: str
    source_repo: int
    dest_type: str = "local"
    dest_path: str = ""
    frequency: str = "0 2 * * *"
    mode: str = "full"


@router.post("/rules")
async def create_rule(body: RuleCreate):
    """Create a replication rule (wraps policy create)."""
    from engines.backup_replicator import create_policy
    try:
        result = create_policy({
            "name": body.name,
            "source_repo_id": body.source_repo,
            "target_repo_id": 0,
            "dest_type": body.dest_type,
            "dest_path": body.dest_path,
            "schedule_cron": body.frequency,
            "mode": body.mode,
            "enabled": True,
        })
        return _clean(result)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/rules/{rule_id}/sync")
async def trigger_rule_sync(rule_id: int):
    """Trigger sync for a replication rule."""
    from engines.backup_replicator import get_policy as _get, run_replication
    if not _get(rule_id):
        raise HTTPException(404, "Rule not found")
    try:
        result = run_replication(rule_id)
        return _clean({"message": "Sincronização iniciada", **result})
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int):
    """Delete a replication rule."""
    from engines.backup_replicator import get_policy as _get, delete_policy as _del
    if not _get(rule_id):
        raise HTTPException(404, "Rule not found")
    _del(rule_id)
    return {"deleted": True}

