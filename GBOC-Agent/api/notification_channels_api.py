#!/usr/bin/env python3
"""
GBOC 14.0.0 - Notification Channels API
CRUD for Slack, Teams, Discord, Telegram, custom webhooks.
Test delivery, delivery history.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import logging
import json
from decimal import Decimal
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/notification-channels", tags=["NotificationChannels"])


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

class ChannelCreate(BaseModel):
    name: str
    channel_type: str  # slack, teams, discord, telegram, webhook
    config: Dict[str, Any] = {}
    enabled: bool = True
    events: List[str] = ["backup_failed", "ransomware_alert"]


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    channel_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    events: Optional[List[str]] = None


# ─── CRUD ─────────────────────────────────────────────────────────

@router.get("/")
async def list_channels():
    """List all notification channels."""
    from engines.notification_channels import list_channels
    return {"channels": _clean(list_channels())}


@router.get("/{channel_id}")
async def get_channel(channel_id: int):
    """Get a specific notification channel."""
    from engines.notification_channels import get_channel as _get
    ch = _get(channel_id)
    if not ch:
        raise HTTPException(404, "Channel not found")
    return {"channel": _clean(ch)}


@router.post("/")
async def create_channel(body: ChannelCreate):
    """Create a new notification channel."""
    valid_types = ['slack', 'teams', 'discord', 'telegram', 'webhook']
    if body.channel_type not in valid_types:
        raise HTTPException(400, f"Invalid channel_type. Must be one of: {valid_types}")
    from engines.notification_channels import create_channel
    result = create_channel(body.dict())
    return {"channel": _clean(result)}


@router.put("/{channel_id}")
async def update_channel(channel_id: int, body: ChannelUpdate):
    """Update a notification channel."""
    from engines.notification_channels import get_channel as _get, update_channel as _update
    if not _get(channel_id):
        raise HTTPException(404, "Channel not found")
    result = _update(channel_id, {k: v for k, v in body.dict().items() if v is not None})
    return {"channel": _clean(result)}


@router.delete("/{channel_id}")
async def delete_channel(channel_id: int):
    """Delete a notification channel."""
    from engines.notification_channels import get_channel as _get, delete_channel as _del
    if not _get(channel_id):
        raise HTTPException(404, "Channel not found")
    _del(channel_id)
    return {"deleted": True}


# ─── Test & History ───────────────────────────────────────────────

@router.post("/{channel_id}/test")
async def test_channel(channel_id: int):
    """Send a test notification to a channel."""
    from engines.notification_channels import test_channel as _test
    result = _test(channel_id)
    if result.get('status') == 'error' and result.get('error') == 'Channel not found':
        raise HTTPException(404, "Channel not found")
    return _clean(result)


@router.get("/history/all")
async def notification_history(limit: int = 50):
    """Get notification delivery history."""
    from engines.notification_channels import get_history
    return {"history": _clean(get_history(limit))}

