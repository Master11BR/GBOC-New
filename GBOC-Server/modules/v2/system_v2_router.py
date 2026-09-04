# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: System & Telemetry Router (API v2)
# ==============================================================================

import time
import os
import sys
import platform
import asyncio
import json
from typing import Optional
from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse
from modules.v2.envelope import build_v2_response

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

router = APIRouter(prefix="/system", tags=["System v2"])

_SERVER_START_TIME = time.time()

def _get_host_telemetry():
    """Coleta métricas 100% reais do host operacional."""
    uptime_sec = int(time.time() - _SERVER_START_TIME)
    
    cpu_percent = psutil.cpu_percent(interval=0.1) if PSUTIL_AVAILABLE else 0.0
    cpu_count = psutil.cpu_count(logical=True) if PSUTIL_AVAILABLE else 1
    
    memory_data = {}
    if PSUTIL_AVAILABLE:
        vm = psutil.virtual_memory()
        memory_data = {
            "total_bytes": vm.total,
            "total_gb": round(vm.total / (1024**3), 2),
            "used_bytes": vm.used,
            "used_gb": round(vm.used / (1024**3), 2),
            "free_gb": round(vm.available / (1024**3), 2),
            "percent": vm.percent
        }
    
    disk_data = []
    if PSUTIL_AVAILABLE:
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disk_data.append({
                    "mountpoint": part.mountpoint,
                    "device": part.device,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "percent": usage.percent
                })
            except Exception:
                continue

    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "os_arch": platform.machine(),
        "python_version": platform.python_version(),
        "uptime_seconds": uptime_sec,
        "cpu": {
            "percent": cpu_percent,
            "cores": cpu_count
        },
        "memory": memory_data,
        "disks": disk_data
    }

@router.get("/version")
async def get_system_version_v2(request: Request):
    """Retorna metadados completos de versão SemVer 2.0 dentro do envelope v2."""
    t0 = time.perf_counter()
    try:
        from version_control import get_version_info
        v_info = get_version_info()
    except Exception:
        v_info = {"raw_version": "14.0.0", "semver": "14.0.0"}
    
    elapsed = (time.perf_counter() - t0) * 1000
    return build_v2_response(data=v_info, execution_time_ms=elapsed)

@router.get("/info")
async def get_system_info_v2(request: Request):
    """Retorna a telemetria em tempo real do servidor e ambiente operacional."""
    t0 = time.perf_counter()
    telemetry = _get_host_telemetry()
    
    # Obter contagem de conexões de banco e agentes ativos se disponível
    active_agents = 0
    try:
        from server_gboc import manager
        active_agents = len(manager.active_connections)
    except Exception:
        pass

    try:
        from version_control import get_version_info
        telemetry["version"] = get_version_info()
    except Exception:
        telemetry["version"] = {"raw_version": "14.0.0"}
        
    telemetry["active_websocket_agents"] = active_agents
    
    elapsed = (time.perf_counter() - t0) * 1000
    return build_v2_response(data=telemetry, execution_time_ms=elapsed)

@router.get("/health")
async def get_system_health_v2(request: Request):
    """Diagnóstico abrangente de saúde do sistema com latência do banco de dados."""
    t0 = time.perf_counter()
    
    db_status = "unknown"
    db_latency_ms = None
    
    try:
        from server_gboc import get_db, release_db
        db_t0 = time.perf_counter()
        conn = get_db()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            release_db(conn)
            db_latency_ms = round((time.perf_counter() - db_t0) * 1000, 2)
            db_status = "healthy"
        else:
            db_status = "unavailable"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    health_data = {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "database": {
            "status": db_status,
            "latency_ms": db_latency_ms
        },
        "host": {
            "cpu_ok": psutil.cpu_percent() < 95 if PSUTIL_AVAILABLE else True,
            "memory_ok": (psutil.virtual_memory().percent < 95) if PSUTIL_AVAILABLE else True
        }
    }
    
    elapsed = (time.perf_counter() - t0) * 1000
    return build_v2_response(data=health_data, execution_time_ms=elapsed)

@router.get("/stream")
async def stream_system_telemetry_v2(interval: int = Query(2, ge=1, le=60)):
    """Server-Sent Events (SSE) stream para telemetria em tempo real."""
    async def event_generator():
        while True:
            t0 = time.perf_counter()
            telemetry = _get_host_telemetry()
            elapsed = (time.perf_counter() - t0) * 1000
            payload = build_v2_response(data=telemetry, execution_time_ms=elapsed)
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(interval)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
