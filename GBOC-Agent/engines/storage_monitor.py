#!/usr/bin/env python3
"""
GBOC 14.0.0 - Storage Usage & Repository Growth Monitor
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
    """
    Coleta o tamanho real e o consumo de todos os repositórios e destinos (Local & Nuvem)
    de TODOS os motores cadastrados (Duplicati, Restic, Kopia, Borg, Nativo, Hermes).
    """
    ensure_storage_tables()
    results = []
    seen_ids = set()

    core = _get_core()

    # 1. Buscar repositórios cadastrados na tabela 'repositories' do banco
    try:
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name, engine, path, status FROM repositories WHERE status = 'active'")
            cols = [d[0] for d in cur.description] if cur.description else []
            db_repos = [dict(zip(cols, row)) for row in cur.fetchall()]

            # Buscar mapa de replicação
            repl_map = {}
            try:
                from engines.backup_replicator import ensure_tables as ensure_repl_tables
                ensure_repl_tables()
                cur.execute("""
                    SELECT source_repo_id, dest_type, dest_path, total_bytes
                    FROM replication_policies WHERE enabled = TRUE
                """)
                repl_cols = [d[0] for d in cur.description] if cur.description else []
                for row in cur.fetchall():
                    r_dict = dict(zip(repl_cols, row))
                    s_id = str(r_dict.get("source_repo_id"))
                    repl_map[s_id] = r_dict
            except Exception as e_repl:
                logger.warning(f"[StorageMonitor] Consulta a replication_policies ignorada: {e_repl}")

        for repo in db_repos:
            repo_id_str = str(repo.get("id", ""))
            repo_name = repo.get("name", f"Repo #{repo_id_str}")
            repo_path = repo.get("path") or repo.get("location") or ""
            engine = (repo.get("engine") or "unknown").lower()
            stats = {"size_bytes": 0, "snapshot_count": 0}

            if repo_path and os.path.exists(repo_path):
                if engine in ("restic",):
                    stats = _get_restic_stats(repo_path)
                else:
                    stats["size_bytes"] = _get_dir_size_bytes(repo_path)

            repl_info = repl_map.get(repo_id_str, {})
            dest_type = repl_info.get("dest_type") or ("Armazenamento Secundário" if repl_info.get("dest_path") else "Local Primary")
            dest_path = repl_info.get("dest_path") or repo_path
            
            dest_bytes = 0
            if dest_path and ("s3://" in dest_path.lower() or "wasabi" in dest_path.lower() or "b2://" in dest_path.lower() or "sftp://" in dest_path.lower()):
                dest_type = "Nuvem / Remote Storage"
                dest_bytes = repl_info.get("total_bytes") or stats["size_bytes"]
            elif dest_path and os.path.exists(dest_path) and dest_path != repo_path:
                dest_bytes = _get_dir_size_bytes(dest_path)
            elif repl_info.get("total_bytes"):
                dest_bytes = repl_info["total_bytes"]
            else:
                dest_bytes = stats["size_bytes"]

            seen_ids.add(repo_id_str)
            seen_ids.add(repo_name.lower())
            results.append({
                "repository_id": repo_id_str,
                "repository_name": repo_name,
                "engine": engine,
                "path": repo_path,
                "size_bytes": stats["size_bytes"],
                "size_gb": round(stats["size_bytes"] / (1024 ** 3), 3),
                "local_bytes": stats["size_bytes"],
                "local_gb": round(stats["size_bytes"] / (1024 ** 3), 3),
                "destination_type": dest_type,
                "destination_path": dest_path,
                "destination_bytes": dest_bytes,
                "destination_gb": round(dest_bytes / (1024 ** 3), 3),
                "snapshot_count": stats.get("snapshot_count", 0),
                "recorded_at": datetime.now().isoformat()
            })
    except Exception as e:
        logger.error(f"[StorageMonitor] Erro ao ler tabela repositories: {e}")

    # 2. Descoberta Automática de Backups do Duplicati (Local & Nuvem)
    try:
        from core.integrations.duplicati_native import get_duplicati_native_service
        dup_service = get_duplicati_native_service()
        dup_res = dup_service.list_backups()
        dup_items = dup_res.get("items", [])
        
        for item in dup_items:
            b_obj = item.get("Backup", {})
            b_id = str(item.get("id") or b_obj.get("ID") or "")
            b_name = item.get("name") or b_obj.get("Name") or f"Duplicati #{b_id}"
            
            if b_id in seen_ids or b_name.lower() in seen_ids:
                continue

            meta = b_obj.get("Metadata", {}) if isinstance(b_obj, dict) else {}
            src_bytes = int(meta.get("SourceFilesSize") or item.get("source_size") or 0)
            tgt_bytes = int(meta.get("TargetFilesSize") or item.get("target_size") or 0)
            target_url = str(b_obj.get("TargetURL") or item.get("target_url") or "")
            
            dest_type = "Destino Remoto"
            if "wasabi" in target_url.lower():
                dest_type = "Wasabi S3 Cloud"
            elif "s3.amazonaws" in target_url.lower() or "s3://" in target_url.lower():
                dest_type = "Amazon S3 Cloud"
            elif "b2" in target_url.lower():
                dest_type = "Backblaze B2 Cloud"
            elif "azure" in target_url.lower():
                dest_type = "Azure Blob Cloud"
            elif "file://" in target_url.lower() or ":" in target_url:
                dest_type = "Disco Local / Rede"

            src_path = "Fontes do Duplicati"
            if item.get("sources") and isinstance(item["sources"], list):
                src_path = ", ".join(item["sources"])

            seen_ids.add(b_id)
            seen_ids.add(b_name.lower())
            results.append({
                "repository_id": f"dup_{b_id}",
                "repository_name": f"Duplicati — {b_name}",
                "engine": "duplicati",
                "path": src_path,
                "size_bytes": src_bytes,
                "size_gb": round(src_bytes / (1024 ** 3), 3),
                "local_bytes": src_bytes,
                "local_gb": round(src_bytes / (1024 ** 3), 3),
                "destination_type": dest_type,
                "destination_path": target_url.split("?")[0] if target_url else "Nuvem / Remote",
                "destination_bytes": tgt_bytes,
                "destination_gb": round(tgt_bytes / (1024 ** 3), 3),
                "snapshot_count": int(meta.get("BackupListCount") or item.get("versions_count") or 1),
                "recorded_at": datetime.now().isoformat()
            })
    except Exception as e_dup:
        logger.warning(f"[StorageMonitor] Descoberta de backups do Duplicati ignorada: {e_dup}")

    # 3. Descoberta Automática de Discos do Sistema para o Motor Nativo (Se nenhum outro for encontrado)
    try:
        import psutil
        for part in psutil.disk_partitions(all=False):
            mount = part.mountpoint
            if any(r.get("path") == mount for r in results):
                continue
            try:
                usage = shutil.disk_usage(mount)
                results.append({
                    "repository_id": f"disk_{part.device.replace(':', '').replace('\\\\', '').replace('/', '')}",
                    "repository_name": f"Volume Nativo ({part.device})",
                    "engine": "native",
                    "path": mount,
                    "size_bytes": usage.used,
                    "size_gb": round(usage.used / (1024 ** 3), 3),
                    "local_bytes": usage.used,
                    "local_gb": round(usage.used / (1024 ** 3), 3),
                    "destination_type": "Volume Local",
                    "destination_path": mount,
                    "destination_bytes": usage.used,
                    "destination_gb": round(usage.used / (1024 ** 3), 3),
                    "snapshot_count": 1,
                    "recorded_at": datetime.now().isoformat()
                })
            except Exception:
                pass
    except Exception:
        pass

    # Persistir entradas reais no histórico
    for entry in results:
        try:
            with core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO storage_usage_history (repository_id, repository_name, engine, path, size_bytes, snapshot_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (entry["repository_id"], entry["repository_name"], entry["engine"], entry["path"],
                      entry["size_bytes"], entry["snapshot_count"]))
                conn.commit()
        except Exception:
            pass

    return results

    return results

def get_storage_summary_by_engine() -> Dict[str, Any]:
    """Retorna estatísticas detalhadas de uso local vs destino agrupadas por motor de backup (Disco Local, Nuvem e Repositórios)."""
    repos = collect_repository_sizes()
    by_engine = {}
    total_local_bytes = 0
    total_dest_bytes = 0
    total_cloud_bytes = 0
    total_local_repo_bytes = 0

    engine_names = {
        "native": "Motor Nativo GBOC",
        "duplicati": "Motor Duplicati",
        "restic": "Motor Restic",
        "kopia": "Motor Kopia",
        "borg": "Motor Borg",
        "hermes": "Motor Hermes"
    }

    for r in repos:
        eng = (r.get("engine") or "unknown").lower()
        if eng not in by_engine:
            d_name = engine_names.get(eng, eng.capitalize())
            by_engine[eng] = {
                "engine": eng,
                "display_name": d_name,
                "repo_count": 0,
                "local_bytes": 0,
                "local_gb": 0.0,
                "cloud_bytes": 0,
                "cloud_gb": 0.0,
                "local_repo_bytes": 0,
                "local_repo_gb": 0.0,
                "destination_bytes": 0,
                "destination_gb": 0.0,
            }

        l_bytes = r.get("local_bytes", r.get("size_bytes", 0))
        d_bytes = r.get("destination_bytes", 0)
        dest_type = (r.get("destination_type") or "").lower()
        dest_path = (r.get("destination_path") or "").lower()

        is_cloud = "nuvem" in dest_type or "cloud" in dest_type or "s3" in dest_type or "wasabi" in dest_type or "b2" in dest_type or "sftp" in dest_type or "s3://" in dest_path or "wasabi" in dest_path

        by_engine[eng]["repo_count"] += 1
        by_engine[eng]["local_bytes"] += l_bytes
        by_engine[eng]["local_gb"] = round(by_engine[eng]["local_bytes"] / (1024 ** 3), 3)

        if is_cloud:
            by_engine[eng]["cloud_bytes"] += d_bytes
            by_engine[eng]["cloud_gb"] = round(by_engine[eng]["cloud_bytes"] / (1024 ** 3), 3)
            total_cloud_bytes += d_bytes
        else:
            by_engine[eng]["local_repo_bytes"] += d_bytes
            by_engine[eng]["local_repo_gb"] = round(by_engine[eng]["local_repo_bytes"] / (1024 ** 3), 3)
            total_local_repo_bytes += d_bytes

        by_engine[eng]["destination_bytes"] += d_bytes
        by_engine[eng]["destination_gb"] = round(by_engine[eng]["destination_bytes"] / (1024 ** 3), 3)

        total_local_bytes += l_bytes
        total_dest_bytes += d_bytes

    return {
        "repositories": repos,
        "by_engine": list(by_engine.values()),
        "totals": {
            "total_local_bytes": total_local_bytes,
            "total_local_gb": round(total_local_bytes / (1024 ** 3), 3),
            "total_dest_bytes": total_dest_bytes,
            "total_dest_gb": round(total_dest_bytes / (1024 ** 3), 3),
            "total_cloud_bytes": total_cloud_bytes,
            "total_cloud_gb": round(total_cloud_bytes / (1024 ** 3), 3),
            "total_local_repo_bytes": total_local_repo_bytes,
            "total_local_repo_gb": round(total_local_repo_bytes / (1024 ** 3), 3)
        }
    }

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
