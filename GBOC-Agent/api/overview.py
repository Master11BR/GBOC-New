#!/usr/bin/env python3
"""
GBOC Agent 13.2.0 - API OVERVIEW (STATUS DETALHADO)
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

@router.get("/")
async def get_overview() -> Dict[str, Any]:
    request_start = time.perf_counter()
    try:
        # 1. Métricas de Sistema
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        
        try:
            disk = psutil.disk_usage('C:\\' if platform.system() == 'Windows' else '/')
        except:
            disk = type('obj', (object,), {'percent': 0, 'free': 0})
            
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime_seconds = (datetime.now() - boot_time).total_seconds()
        
        # 2. Rede
        hostname = socket.gethostname()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except:
            local_ip = "127.0.0.1"

        # 3. Banco (AGORA COM CONTAGEM DE STATUS)
        repo_count = 0
        task_count = 0
        running_tasks = 0 # Nova variável
        total_backups = 0
        
        if get_shared_core:
            try:
                core = get_shared_core()
                with core.get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM repositories")
                    repo_count = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM tasks WHERE enabled = true")
                    task_count = cur.fetchone()[0]
                    # Conta tarefas rodando
                    cur.execute("SELECT COUNT(*) FROM tasks WHERE status='running'")
                    running_tasks = cur.fetchone()[0]
                    try:
                        cur.execute("SELECT COUNT(*) FROM task_executions")
                        total_backups = cur.fetchone()[0]
                    except: pass
            except Exception as db_err:
                logger.warning(f"Erro ao consultar banco: {db_err}")

        total_data_gb = 0
        backup_health_score = None
        if get_shared_core:
            try:
                core = get_shared_core()
                with core.get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COALESCE(SUM(bytes_processed), 0) FROM task_executions WHERE status = 'completed'")
                    total_bytes = cur.fetchone()[0]
                    total_data_gb = round(total_bytes / (1024**3), 2) if total_bytes else 0

                    # Score rápido de backup (últimos 7 dias), evitando cálculo pesado.
                    cur.execute("""
                        SELECT COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE status IN ('completed','success')) AS ok
                        FROM task_executions
                        WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
                    """)
                    row = cur.fetchone()
                    total_7d = row[0] if row else 0
                    ok_7d = row[1] if row else 0
                    backup_health_score = round((ok_7d / total_7d) * 100) if total_7d else 100
            except Exception:
                pass

        # 4. Engines
        engines = _detect_engines_detailed()

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
                "sync_status": "Online"
            },
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
