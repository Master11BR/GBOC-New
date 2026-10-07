#!/usr/bin/env python3
"""
GBOC Agent 14.8.1 - API OVERVIEW (STATUS DETALHADO)
Adiciona contagem de tarefas em execução vs paradas.
"""

from fastapi import APIRouter
from typing import Dict, Any
import psutil
import logging
from datetime import datetime
import os
import platform
import socket
import sys
import time

# Hack de importação
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

try:
    from shared_core import get_shared_core
except ImportError:
    get_shared_core = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/overview", tags=["overview"])

_LOCAL_IP_CACHE = {"ip": "127.0.0.1", "ts": 0.0}

def _get_cached_local_ip() -> str:
    now = time.monotonic()
    if now - _LOCAL_IP_CACHE["ts"] < 60.0:
        return _LOCAL_IP_CACHE["ip"]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"
    _LOCAL_IP_CACHE.update(ip=ip, ts=now)
    return ip

@router.get("/")
def get_overview() -> Dict[str, Any]:
    request_start = time.perf_counter()
    try:
        # 1. Métricas de Sistema (sem intervalo bloqueante, consumindo amostrador de background)
        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        
        try:
            disk = psutil.disk_usage('C:\\' if platform.system() == 'Windows' else '/')
        except:
            disk = type('obj', (object,), {'percent': 0, 'free': 0})
            
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime_seconds = (datetime.now() - boot_time).total_seconds()
        
        # 2. Rede (com cache)
        hostname = socket.gethostname()
        local_ip = _get_cached_local_ip()

        # 3. Banco (Consulta única agregada para máxima performance)
        repo_count = 0
        task_count = 0
        running_tasks = 0
        total_backups = 0
        total_data_gb = 0
        backup_health_score = None
        
        if get_shared_core:
            try:
                core = get_shared_core()
                with core.get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT 
                            (SELECT COUNT(*) FROM repositories) AS repo_count,
                            (SELECT COUNT(*) FROM tasks WHERE enabled = true) AS task_count,
                            (SELECT COUNT(*) FROM tasks WHERE status = 'running') AS running_tasks,
                            (SELECT COUNT(*) FROM task_executions) AS total_backups,
                            (SELECT COALESCE(SUM(bytes_processed), 0) FROM task_executions WHERE status = 'completed') AS total_bytes,
                            (SELECT COUNT(*) FROM task_executions WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '7 days') AS total_7d,
                            (SELECT COUNT(*) FROM task_executions WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '7 days' AND status IN ('completed', 'success')) AS ok_7d
                    """)
                    row = cur.fetchone()
                    if row:
                        repo_count = row[0] or 0
                        task_count = row[1] or 0
                        running_tasks = row[2] or 0
                        total_backups = row[3] or 0
                        total_bytes = row[4] or 0
                        total_7d = row[5] or 0
                        ok_7d = row[6] or 0
                        total_data_gb = round(total_bytes / (1024**3), 2) if total_bytes else 0
                        backup_health_score = round((ok_7d / total_7d) * 100) if total_7d else 100
            except Exception as db_err:
                logger.warning(f"Erro ao consultar banco no overview: {db_err}")

        # 4. Engines
        engines = _detect_engines_detailed()

        # 5. Ligação com o Servidor Central (antes "Online" fixo no código)
        try:
            from core.server_client import central_client
            server_link = central_client.link_state() if central_client else {"state": "not_configured", "connected": False}
        except Exception as _sl_err:
            server_link = {"state": "unknown", "connected": False, "detail": str(_sl_err)[:200]}

        elapsed_ms = round((time.perf_counter() - request_start) * 1000, 2)
        logger.info(f"[PERF] GET /api/overview concluído em {elapsed_ms} ms")

        return {
            "status": "online",
            "timestamp": datetime.now().isoformat(),
            "health_score": _calculate_health(cpu_percent, memory.percent, disk.percent, backup_health_score),
            
            "system_metrics": {
                "cpu": {"usage_percent": round(cpu_percent, 1)},
                "memory": {"percent": round(memory.percent, 1), "total": memory.total, "used": memory.used},
                "disk": {"total_usage_percent": round(disk.percent, 1), "total_free_gb": round(disk.free / (1024**3), 1)}
            },
            "overview_summary": {
                "repositories": repo_count,
                "tasks": task_count,
                "running": running_tasks, # Enviando para o front
                "idle": task_count - running_tasks
            },
            "network_info": {
                "local_ip": local_ip,
                "hostname": hostname,
                "sync_status": "Online" if server_link.get("connected") else "Offline"
            },
            "server_sync": server_link,
            "engines_status": {
                "installed": len([e for e in engines if e['detected']]),
                "list": [e['name'] for e in engines if e['detected']]
            },
            "backup_stats": {
                "total_backups": total_backups,
                "total_data_gb": total_data_gb
            },
            "system_info": {
                "platform": f"{platform.system()} {platform.release()}",
                "version": platform.version(),
                "uptime_seconds": uptime_seconds
            }
        }
        
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - request_start) * 1000, 2)
        logger.error(f"[PERF] GET /api/overview falhou após {elapsed_ms} ms: {e}")
        return {"status": "error", "message": str(e)}

def _detect_engines_detailed():
    try:
        from engines.engine_paths import detect_all_engines
        return detect_all_engines()
    except ImportError:
        import shutil
        engine_list = ["restic", "kopia", "duplicati", "borg", "rclone"]
        results = []
        for name in engine_list:
            path = shutil.which(name)
            if not path and platform.system() == "Windows": path = shutil.which(f"{name}.exe")
            results.append({"name": name, "detected": path is not None})
        return results

def _calculate_health(cpu, mem, disk, backup_score=None):
    """Calcula health score unificado de forma leve para respostas rápidas."""
    # Score base de recursos do sistema (peso 40%)
    sys_score = 100
    if cpu > 80: sys_score -= 30
    elif cpu > 60: sys_score -= 10
    if mem > 85: sys_score -= 30
    elif mem > 70: sys_score -= 10
    if disk > 90: sys_score -= 30
    elif disk > 80: sys_score -= 10
    sys_score = max(0, sys_score)

    if backup_score is not None:
        return round(sys_score * 0.4 + backup_score * 0.6)
    return max(0, sys_score)
