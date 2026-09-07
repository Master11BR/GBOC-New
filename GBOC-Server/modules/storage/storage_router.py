#!/usr/bin/env python3
"""
GBOC Server v14.0.0 — Storage Usage & Growth Monitor APIRouter
Módulo estrito para gerenciamento de armazenamento centralizado.
"""

import shutil
import os
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

try:
    from database import db_manager
    def get_db(): return db_manager.get_connection()
    def release_db(conn): db_manager.release_connection(conn)
except Exception:
    def get_db(): return None
    def release_db(conn): pass

try:
    from psycopg2.extras import RealDictCursor
except Exception:
    RealDictCursor = None

logger = logging.getLogger("gboc_storage_module")

router = APIRouter(prefix="/api/v1/server/storage", tags=["Server Storage Monitor"])

def _get_server_storage_stats():
    """Obtém dados reais de armazenamento dos discos e diretórios do servidor."""
    stats = []
    base_paths = [os.getcwd(), os.path.abspath("/"), "C:\\" if os.name == 'nt' else "/"]
    visited = set()

    for p in base_paths:
        try:
            norm = os.path.abspath(p).upper()
            if norm in visited or not os.path.exists(p):
                continue
            visited.add(norm)

            total, used, free = shutil.disk_usage(p)
            stats.append({
                "repository_id": f"srv-disk-{len(stats)+1}",
                "name": f"Disco Local ({p})",
                "path": p,
                "total_bytes": total,
                "used_bytes": used,
                "free_bytes": free,
                "used_percent": round((used / total) * 100, 2) if total > 0 else 0,
                "total_gb": round(total / (1024**3), 2),
                "used_gb": round(used / (1024**3), 2),
                "free_gb": round(free / (1024**3), 2),
                "status": "healthy" if (free / total) > 0.10 else "warning"
            })
        except Exception:
            continue
    return stats

@router.get("/overview")
async def get_storage_overview():
    """Retorna o uso atual de armazenamento no servidor e nos motores (Local vs. Nuvem)."""
    stats = _get_server_storage_stats()
    total_capacity = sum(s["total_gb"] for s in stats)
    total_used = sum(s["used_gb"] for s in stats)
    total_free = sum(s["free_gb"] for s in stats)

    # Coletar estatísticas agregadas por motor se o módulo de monitoramento do agente estiver disponível
    by_engine = []
    try:
        from engines.storage_monitor import get_storage_summary_by_engine
        summary = get_storage_summary_by_engine()
        by_engine = summary.get("by_engine", [])
        if summary.get("repositories"):
            for r in summary["repositories"]:
                stats.append({
                    "repository_id": r.get("repository_id"),
                    "name": r.get("repository_name"),
                    "engine": r.get("engine", "native"),
                    "path": r.get("path"),
                    "total_gb": r.get("destination_gb") or r.get("local_gb") or 0,
                    "used_gb": r.get("local_gb") or 0,
                    "free_gb": 0,
                    "used_percent": 100 if r.get("local_gb") else 0,
                    "destination_type": r.get("destination_type"),
                    "destination_path": r.get("destination_path"),
                    "destination_gb": r.get("destination_gb", 0),
                    "status": "healthy"
                })
    except Exception:
        by_engine = [{
            "engine": "native",
            "display_name": "Motor Nativo GBOC",
            "repo_count": len(stats),
            "local_bytes": int(total_used * (1024**3)),
            "local_gb": round(total_used, 2),
            "cloud_bytes": 0,
            "cloud_gb": 0.0,
            "local_repo_bytes": int(total_used * (1024**3)),
            "local_repo_gb": round(total_used, 2),
            "destination_bytes": int(total_used * (1024**3)),
            "destination_gb": round(total_used, 2)
        }]

    return JSONResponse({
        "status": "success",
        "summary": {
            "total_capacity_gb": round(total_capacity, 2),
            "total_used_gb": round(total_used, 2),
            "total_free_gb": round(total_free, 2),
            "used_percent": round((total_used / total_capacity) * 100, 2) if total_capacity > 0 else 0
        },
        "by_engine": by_engine,
        "repositories": stats
    })

@router.get("/history")
async def get_storage_history(days: int = 30):
    """Retorna histórico real de crescimento de dados coletado pelo sistema."""
    days_limit = min(days, 90)
    history = []
    conn = None
    try:
        conn = get_db()
        if not conn:
            raise RuntimeError("Conexão com o banco de dados indisponível")
        
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        cur.execute("""
            SELECT recorded_at, size_bytes, repository_name
            FROM storage_usage_history
            WHERE recorded_at >= NOW() - INTERVAL '%s days'
            ORDER BY recorded_at ASC
        """, (days_limit,))
        rows = cur.fetchall()
        for r in rows:
            if isinstance(r, dict):
                rec_at = r.get("recorded_at")
                sz_bytes = r.get("size_bytes")
                repo_name = r.get("repository_name")
            else:
                rec_at = r[0]
                sz_bytes = r[1]
                repo_name = r[2]
            history.append({
                "timestamp": rec_at.isoformat() if hasattr(rec_at, 'isoformat') else str(rec_at),
                "used_gb": round((sz_bytes or 0) / (1024**3), 2),
                "repository_name": repo_name
            })
        cur.close()
    except Exception as e:
        logger.warning(f"Histórico DB indisponível, usando leitura de volumes locais: {e}")
        # Fallback 100% Real Data: Leitura empírica atual dos discos do host
        stats = _get_server_storage_stats()
        base_used = sum(s["used_gb"] for s in stats)
        history = [{
            "timestamp": datetime.now().isoformat(),
            "used_gb": round(base_used, 2),
            "repository_name": "Volumes Locais"
        }]
    finally:
        if conn:
            release_db(conn)

    return JSONResponse({
        "status": "success",
        "days": days_limit,
        "history": history
    })

@router.post("/scan")
async def scan_storage():
    """Executa varredura de discos no servidor central."""
    stats = _get_server_storage_stats()
    return JSONResponse({
        "status": "success",
        "message": "Varredura de armazenamento concluída com sucesso.",
        "scanned_count": len(stats),
        "repositories": stats
    })
