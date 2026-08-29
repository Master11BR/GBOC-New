#!/usr/bin/env python3
"""
GBOC 13.2.0 - Storage Usage & Repository Growth Monitor
Tracks physical size of all Restic / Kopia / Duplicati repositories and local paths.
Generates growth trend data and fires alerts when thresholds are exceeded.
"""

import os
import sys
import json
import logging
import shutil
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger("gboc_storage_monitor")

DEFAULT_STORAGE_CONFIG = {
    "alert_threshold_gb": 0,            # 0 = disabled
    "alert_growth_pct_per_week": 0,     # 0 = disabled
    "scan_interval_hours": 6,
    "history_days": 90
}

_monitor_thread: Optional[threading.Thread] = None
_monitor_running = False

def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()

def ensure_storage_tables():
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS storage_usage_history (
                id SERIAL PRIMARY KEY,
                repository_id TEXT NOT NULL,
                repository_name TEXT,
                engine TEXT DEFAULT 'unknown',
                path TEXT,
                size_bytes BIGINT DEFAULT 0,
                snapshot_count INTEGER DEFAULT 0,
                recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS storage_alert_config (
                id INTEGER PRIMARY KEY DEFAULT 1,
                alert_threshold_gb REAL DEFAULT 0,
                alert_growth_pct_per_week REAL DEFAULT 0,
                scan_interval_hours INTEGER DEFAULT 6,
                history_days INTEGER DEFAULT 90,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

def _get_dir_size_bytes(path: str) -> int:
    """Retorna tamanho real em bytes de um diretório."""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for fn in filenames:
                try:
                    fp = os.path.join(dirpath, fn)
                    total += os.path.getsize(fp)
                except (OSError, FileNotFoundError):
                    pass
    except Exception:
        pass
    return total

def _get_restic_stats(repo_path: str) -> Dict[str, Any]:
    """Obtém estatísticas reais de um repositório Restic via CLI."""
    import subprocess, shutil as sh
    restic_bin = sh.which("restic")
    if not restic_bin or not os.path.isdir(repo_path):
        return {"size_bytes": _get_dir_size_bytes(repo_path), "snapshot_count": 0, "method": "dir_scan"}
    try:
        env = os.environ.copy()
        env["RESTIC_REPOSITORY"] = repo_path
        env.setdefault("RESTIC_PASSWORD", "")
        res = subprocess.run([restic_bin, "stats", "--json", "--no-lock"], capture_output=True, text=True, timeout=30, env=env)
        if res.returncode == 0:
            d = json.loads(res.stdout)
            return {
                "size_bytes": d.get("total_size", 0),
                "snapshot_count": d.get("total_file_count", 0),
                "method": "restic_stats"
            }
    except Exception:
        pass
    return {"size_bytes": _get_dir_size_bytes(repo_path), "snapshot_count": 0, "method": "dir_scan"}

def collect_repository_sizes() -> List[Dict[str, Any]]:
    """Coleta o tamanho real de todos os repositórios cadastrados no banco."""
    ensure_storage_tables()
    results = []
    try:
        core = _get_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name, engine, path, status FROM repositories WHERE status = 'active'")
            cols = [d[0] for d in cur.description] if cur.description else []
            repos = [dict(zip(cols, row)) for row in cur.fetchall()]

        for repo in repos:
            repo_path = repo.get("path") or repo.get("location") or ""
            engine = (repo.get("engine") or "unknown").lower()
            stats = {"size_bytes": 0, "snapshot_count": 0}

            if repo_path and os.path.exists(repo_path):
                if engine in ("restic",):
                    stats = _get_restic_stats(repo_path)
                else:
                    stats["size_bytes"] = _get_dir_size_bytes(repo_path)

            entry = {
                "repository_id": str(repo.get("id", "")),
                "repository_name": repo.get("name", ""),
                "engine": engine,
                "path": repo_path,
                "size_bytes": stats["size_bytes"],
                "size_gb": round(stats["size_bytes"] / (1024 ** 3), 3),
                "snapshot_count": stats.get("snapshot_count", 0),
                "recorded_at": datetime.now().isoformat()
            }
            results.append(entry)

            # Persist to history
            try:
                with core.get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO storage_usage_history (repository_id, repository_name, engine, path, size_bytes, snapshot_count)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (entry["repository_id"], entry["repository_name"], engine, repo_path,
                          entry["size_bytes"], entry["snapshot_count"]))
                    conn.commit()
            except Exception as e:
                logger.error(f"[StorageMonitor] Erro ao persistir histórico: {e}")

    except Exception as e:
        logger.error(f"[StorageMonitor] Erro ao coletar tamanhos: {e}")

    return results

def get_storage_history(repository_id: Optional[str] = None, days: int = 30) -> List[Dict]:
    """Retorna o histórico de uso de armazenamento por repositório."""
    ensure_storage_tables()
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        if repository_id:
            cur.execute("""
                SELECT repository_id, repository_name, engine, size_bytes, snapshot_count, recorded_at
                FROM storage_usage_history
                WHERE repository_id = %s AND recorded_at >= NOW() - INTERVAL '%s days'
                ORDER BY recorded_at ASC
            """, (repository_id, days))
        else:
            cur.execute("""
                SELECT DISTINCT ON (repository_id) repository_id, repository_name, engine, size_bytes, snapshot_count, recorded_at
                FROM storage_usage_history
                WHERE recorded_at >= NOW() - INTERVAL '%s days'
                ORDER BY repository_id, recorded_at DESC
            """, (days,))
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            if d.get("recorded_at") and hasattr(d["recorded_at"], 'isoformat'):
                d["recorded_at"] = d["recorded_at"].isoformat()
            d["size_gb"] = round((d.get("size_bytes") or 0) / (1024**3), 3)
            rows.append(d)
        return rows

def get_storage_config() -> Dict:
    ensure_storage_tables()
    try:
        core = _get_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT alert_threshold_gb, alert_growth_pct_per_week, scan_interval_hours, history_days FROM storage_alert_config WHERE id=1")
            row = cur.fetchone()
            if row:
                return {"alert_threshold_gb": row[0], "alert_growth_pct_per_week": row[1], "scan_interval_hours": row[2], "history_days": row[3]}
    except Exception:
        pass
    return DEFAULT_STORAGE_CONFIG.copy()

def save_storage_config(cfg: Dict) -> Dict:
    ensure_storage_tables()
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO storage_alert_config (id, alert_threshold_gb, alert_growth_pct_per_week, scan_interval_hours, history_days, updated_at)
            VALUES (1, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET
                alert_threshold_gb = EXCLUDED.alert_threshold_gb,
                alert_growth_pct_per_week = EXCLUDED.alert_growth_pct_per_week,
                scan_interval_hours = EXCLUDED.scan_interval_hours,
                history_days = EXCLUDED.history_days,
                updated_at = CURRENT_TIMESTAMP
        """, (cfg.get("alert_threshold_gb", 0), cfg.get("alert_growth_pct_per_week", 0),
              cfg.get("scan_interval_hours", 6), cfg.get("history_days", 90)))
        conn.commit()
    return get_storage_config()

def start_storage_monitor():
    """Inicia o monitor de crescimento de armazenamento em segundo plano."""
    global _monitor_thread, _monitor_running
    if _monitor_running:
        return
    _monitor_running = True
    _monitor_thread = threading.Thread(target=_storage_monitor_loop, daemon=True, name="gboc-storage-monitor")
    _monitor_thread.start()
    logger.info("📦 Storage Growth Monitor iniciado em segundo plano")

def _storage_monitor_loop():
    global _monitor_running
    while _monitor_running:
        try:
            cfg = get_storage_config()
            collect_repository_sizes()
            interval_secs = (cfg.get("scan_interval_hours") or 6) * 3600
        except Exception as e:
            logger.error(f"[StorageMonitor] Erro no loop: {e}")
            interval_secs = 3600
        time.sleep(interval_secs)
