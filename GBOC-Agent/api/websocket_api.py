#!/usr/bin/env python3
"""
GBOC 13.2.0 - WebSocket API
Real-time event broadcasting for backup progress, alerts, system metrics.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Set, Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])


class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        return super().default(o)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self):
        self.active: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self.active.add(ws)
        logger.info(f"[WS] Client connected. Total: {len(self.active)}")

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            self.active.discard(ws)
        logger.info(f"[WS] Client disconnected. Total: {len(self.active)}")

    async def broadcast(self, event: str, data: Dict[str, Any] = None):
        msg = json.dumps({"event": event, "data": data or {}, "timestamp": datetime.now().isoformat()}, cls=_Enc)
        dead = []
        async with self._lock:
            for ws in self.active:
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.active.discard(ws)

    @property
    def count(self) -> int:
        return len(self.active)


# Singleton
manager = ConnectionManager()


def get_ws_manager() -> ConnectionManager:
    return manager


# ─── WebSocket Endpoint ────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Send welcome
        await ws.send_text(json.dumps({
            "event": "connected",
            "data": {"message": "GBOC WebSocket connected", "clients": manager.count},
            "timestamp": datetime.now().isoformat()
        }))

        while True:
            try:
                text = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                msg = json.loads(text)
                cmd = msg.get("command")

                if cmd == "ping":
                    await ws.send_text(json.dumps({"event": "pong", "timestamp": datetime.now().isoformat()}))

                elif cmd == "subscribe":
                    # Future: channel-based subscriptions
                    await ws.send_text(json.dumps({
                        "event": "subscribed",
                        "data": {"channels": msg.get("channels", ["all"])},
                        "timestamp": datetime.now().isoformat()
                    }))

                elif cmd == "get_metrics":
                    metrics = _collect_live_metrics()
                    await ws.send_text(json.dumps({"event": "metrics", "data": metrics, "timestamp": datetime.now().isoformat()}, cls=_Enc))

            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await ws.send_text(json.dumps({"event": "heartbeat", "timestamp": datetime.now().isoformat()}))
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"[WS] Error: {e}")
    finally:
        await manager.disconnect(ws)


# ─── REST endpoint for stats ──────────────────────────────────────

@router.get("/api/websocket/status")
async def ws_status():
    return {"active_connections": manager.count}


# ─── Helpers ──────────────────────────────────────────────────────

def _collect_live_metrics() -> Dict:
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        return {
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_used_gb": round(mem.used / (1024**3), 2),
            "memory_total_gb": round(mem.total / (1024**3), 2),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024**3), 2),
        }
    except Exception:
        return {}


# ─── Broadcast helpers (called from other modules) ────────────────

async def broadcast_backup_started(task_id: int, task_name: str, engine: str):
    await manager.broadcast("backup_started", {
        "task_id": task_id, "task_name": task_name, "engine": engine
    })


async def broadcast_backup_progress(task_id: int, progress: int, current_file: str = ""):
    await manager.broadcast("backup_progress", {
        "task_id": task_id, "progress": progress, "current_file": current_file
    })


async def broadcast_backup_completed(task_id: int, task_name: str, success: bool, duration: int = 0):
    await manager.broadcast("backup_completed", {
        "task_id": task_id, "task_name": task_name, "success": success, "duration": duration
    })


async def broadcast_alert(alert_type: str, severity: str, message: str):
    await manager.broadcast("alert", {
        "type": alert_type, "severity": severity, "message": message
    })


async def broadcast_metrics(metrics: Dict):
    await manager.broadcast("metrics", metrics)

