#!/usr/bin/env python3
"""
GBOC Agent 15.0.0 - API OVERVIEW (STATUS DETALHADO)
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
_OVERVIEW_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}

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
    now_mono = time.monotonic()
    if _OVERVIEW_CACHE["data"] is not None and (now_mono - _OVERVIEW_CACHE["ts"]) < 2.0:
        return _OVERVIEW_CACHE["data"]
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
                        backup_health_score = round((ok_7d / total_7d) * 100) if total_7d else None  # sem execucoes em 7 dias: sem nota (antes 100)
            except Exception as db_err:
                logger.warning(f"Erro ao consultar banco no overview: {db_err}")

        # 4. Engines
        engines = _detect_engines_detailed()

        # 5. Ligação com o Servidor Central (antes "Online" fixo no código)
        try:
            from core.server_client import central_client
            server_link = central_client.link_state() if central_client else {"state": "not_configured", "connected": False}
        except Exception as _sl_err:
            server_link = {"state": "error", "connected": False, "detail": f"Falha ao consultar a ligação com o Servidor Central: {str(_sl_err)[:180]}"}

        elapsed_ms = round((time.perf_counter() - request_start) * 1000, 2)
        logger.debug(f"[PERF] GET /api/overview concluído em {elapsed_ms} ms")

        payload = {
            "status": "online",
            "gboc_version": "15.0.0",
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
                "uptime_seconds": uptime_seconds,
                "gboc_version": "15.0.0"
            }
        }
        _OVERVIEW_CACHE["data"] = payload
        _OVERVIEW_CACHE["ts"] = time.monotonic()
        return payload
        
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


# ==============================================================================
# MAPA DO SISTEMA — Origens → Tarefas → Repositórios → Destinos (dados reais)
# ==============================================================================

import json as _json
import re as _re
from datetime import timedelta as _timedelta

_OK_STATUSES = ("completed", "success")
_FAIL_STATUSES = ("failed", "error", "interrupted", "cancelled", "stopped")
_CRON_LOOKAHEAD_HOURS = 8 * 24
_LATE_TOLERANCE = _timedelta(minutes=60)
# Gravidade para agregar o status (maior = pior / mais relevante)
_STATUS_RANK = {"ok": 0, "never": 1, "paused": 1, "manual": 1, "running": 2, "late": 3, "error": 4}


def _parse_source_paths(raw) -> list:
    """Mesmo formato aceito por api.tasks._normalize_source_paths (lista JSON ou texto separado por ; / quebra de linha)."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(p).strip() for p in raw if str(p).strip()]
    text = str(raw).strip()
    if not text:
        return []
    try:
        parsed = _json.loads(text)
        if isinstance(parsed, list):
            return [str(p).strip() for p in parsed if str(p).strip()]
        if isinstance(parsed, str):
            text = parsed
    except (ValueError, TypeError):
        pass
    parts = []
    for line in text.replace("\r", "\n").split("\n"):
        parts.extend(line.split(";"))
    return [p.strip() for p in parts if p.strip()]


def _cron_fields(cron_expr):
    parts = (cron_expr or "").strip().split()
    return parts if len(parts) >= 5 else None


def _cron_hour_matches(parts, dt) -> bool:
    from engines.scheduler import _match_cron_field
    return (_match_cron_field(parts[1], dt.hour) and _match_cron_field(parts[2], dt.day)
            and _match_cron_field(parts[3], dt.month) and _match_cron_field(parts[4], dt.weekday()))


def _cron_neighbor(cron_expr, now: datetime, forward: bool):
    """Próxima (forward) ou última (backward) execução prevista, com a MESMA semântica do engines.scheduler
    (dia da semana 0 = segunda). Varre por hora e só desce para minutos quando a hora casa."""
    parts = _cron_fields(cron_expr)
    if not parts:
        return None
    try:
        from engines.scheduler import _match_cron_field
        base = now.replace(minute=0, second=0, microsecond=0)
        step = 1 if forward else -1
        for h in range(0, _CRON_LOOKAHEAD_HOURS + 1):
            hour_dt = base + _timedelta(hours=h * step)
            if not _cron_hour_matches(parts, hour_dt):
                continue
            minutes = range(60) if forward else range(59, -1, -1)
            for m in minutes:
                cand = hour_dt.replace(minute=m)
                if forward and cand <= now:
                    continue
                if not forward and cand > now:
                    continue
                if _match_cron_field(parts[0], m):
                    return cand
    except (ValueError, IndexError, ImportError) as e:
        logger.debug(f"[SYSTEM-MAP] cron inválido '{cron_expr}': {e}")
    return None


def _naive(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _iso(dt):
    return dt.isoformat() if dt else None


def _parse_config(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = _json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _volume_root(path: str):
    """Raiz do volume de um caminho: 'C:\\' no Windows, ponto de montagem no Linux, compartilhamento em UNC."""
    if not path:
        return None
    p = path.strip().strip('"')
    m = _re.match(r"^([A-Za-z]):", p)
    if m:
        return f"{m.group(1).upper()}:\\"
    m = _re.match(r"^(\\\\|//)([^\\/]+)[\\/]([^\\/]+)", p)
    if m:
        return f"\\\\{m.group(2)}\\{m.group(3)}"
    if p.startswith("/"):
        best = "/"
        try:
            for part in psutil.disk_partitions(all=False):
                mp = part.mountpoint
                if p == mp or p.startswith(mp.rstrip("/") + "/"):
                    if len(mp) > len(best):
                        best = mp
        except Exception as e:
            logger.debug(f"[SYSTEM-MAP] disk_partitions: {e}")
        return best
    return None


def _destination_of(repo: dict) -> dict:
    """Agrupa o repositório pelo local físico onde os dados ficam."""
    cfg = _parse_config(repo.get("config"))
    rtype = str(repo.get("type") or "local").lower()
    engine = str(repo.get("engine") or "").lower()
    path = str(repo.get("path") or cfg.get("path") or "")
    provider = str(cfg.get("provider") or cfg.get("cloud_provider") or cfg.get("repo_type") or "").lower()
    bucket = cfg.get("bucket") or repo.get("bucket")
    endpoint = cfg.get("endpoint") or repo.get("endpoint")

    cloud_words = ("s3", "b2", "wasabi", "azure", "gcs", "sftp", "rclone", "minio", "seaweed", "garage", "r2")
    is_cloud = rtype not in ("local", "") or any(w in provider for w in cloud_words) \
        or bool(bucket) or bool(_re.match(r"^(s3|b2|azure|gs|sftp|rclone|wasabi):", path, _re.I))

    if not is_cloud:
        root = _volume_root(path)
        label = f"Disco {root}" if root else "Disco local"
        return {"key": f"local:{(root or path).lower()}", "kind": "local", "label": label,
                "detail": path or "caminho não configurado"}

    if not provider:
        m = _re.match(r"^([a-z0-9]+):", path, _re.I)
        provider = (m.group(1) if m else (rtype if rtype not in ("cloud", "local") else engine)).lower()
    if endpoint and "wasabi" in str(endpoint).lower():
        provider = "wasabi"
    host = ""
    if endpoint:
        host = _re.sub(r"^https?://", "", str(endpoint)).split("/")[0]
    detail = " · ".join(x for x in [provider, host] if x) or "nuvem"
    label = provider.upper() if provider else "Nuvem"
    return {"key": f"cloud:{provider}:{host}".lower(), "kind": "cloud", "label": label, "detail": detail,
            "bucket": bucket}


def _task_state(task: dict, last_exec: dict, last_ok, now: datetime) -> dict:
    enabled = task.get("enabled")
    enabled = True if enabled is None else bool(enabled) and str(enabled).lower() not in ("0", "false")
    schedule_on = bool(task.get("schedule_enabled")) and bool(task.get("schedule_cron"))
    cron = task.get("schedule_cron") if schedule_on else None
    next_run = _cron_neighbor(cron, now, forward=True) if (cron and enabled) else None
    prev_slot = _cron_neighbor(cron, now, forward=False) if (cron and enabled) else None

    exec_status = str((last_exec or {}).get("status") or "").lower()
    task_status = str(task.get("status") or "").lower()
    progress = (last_exec or {}).get("progress")

    if task_status == "running" or exec_status == "running":
        state, label = "running", "Executando"
    elif not enabled:
        state, label = "paused", "Pausada"
    elif not last_exec:
        state, label = "never", "Nunca executou"
    elif exec_status in _FAIL_STATUSES:
        state, label = "error", "Com erro" if exec_status in ("failed", "error") else "Cópia incompleta"
    elif prev_slot and (last_ok is None or last_ok < prev_slot - _LATE_TOLERANCE) and prev_slot < now - _LATE_TOLERANCE:
        state, label = "late", "Atrasado"
    elif not cron:
        state, label = "manual", "Manual · Em dia" if exec_status in _OK_STATUSES else "Manual"
        if exec_status in _OK_STATUSES:
            state = "ok"
    else:
        state, label = "ok", "Em dia"

    return {"state": state, "label": label, "next_run": next_run, "expected_last": prev_slot,
            "progress": progress if state == "running" else None}


def _worst(states):
    states = [s for s in states if s]
    if not states:
        return "never"
    # Execução em andamento é o que o usuário quer ver primeiro quando não há erro
    if "error" in states:
        return "error"
    if "running" in states:
        return "running"
    return max(states, key=lambda s: _STATUS_RANK.get(s, 0))


_STATE_LABEL = {"ok": "Em dia", "running": "Executando", "late": "Atrasado", "error": "Cópia incompleta",
                "never": "Nunca executou", "paused": "Pausada", "manual": "Manual"}


def _rows(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/system-map")
def get_system_map() -> Dict[str, Any]:
    """Grafo real de proteção: pastas de origem → tarefas → repositórios → destinos, com saúde e discos."""
    t0 = time.perf_counter()
    if not get_shared_core:
        return {"status": "error", "message": "Núcleo do Agente indisponível (shared_core não carregou)."}
    now = datetime.now()
    try:
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM tasks ORDER BY id")
            tasks = _rows(cur)
            cur.execute("SELECT * FROM repositories ORDER BY id")
            repos = _rows(cur)
            cur.execute("""
                SELECT e.task_id, e.status, e.started_at, e.completed_at, e.error_message, e.progress,
                       e.bytes_total, e.bytes_processed, e.files_total, e.files_processed
                FROM task_executions e
                JOIN (SELECT task_id, MAX(id) AS mid FROM task_executions GROUP BY task_id) m ON e.id = m.mid
            """)
            last_exec = {r["task_id"]: r for r in _rows(cur)}
            cur.execute("""
                SELECT task_id, MAX(COALESCE(completed_at, started_at)) AS last_ok,
                       MAX(bytes_total) AS max_bytes_total
                FROM task_executions WHERE status IN ('completed', 'success') GROUP BY task_id
            """)
            ok_info = {r["task_id"]: r for r in _rows(cur)}
            cur.execute("""
                SELECT e.task_id, e.bytes_total, e.bytes_processed
                FROM task_executions e
                JOIN (SELECT task_id, MAX(id) AS mid FROM task_executions
                      WHERE status IN ('completed', 'success') GROUP BY task_id) m ON e.id = m.mid
            """)
            last_ok_exec = {r["task_id"]: r for r in _rows(cur)}
    except Exception as e:
        logger.error(f"[SYSTEM-MAP] Falha ao consultar o banco: {e}", exc_info=True)
        return {"status": "error", "message": f"Falha ao consultar o banco do Agente: {str(e)[:200]}"}

    # ── Tarefas ──
    task_nodes, sources, issues, upcoming = [], {}, [], []
    for t in tasks:
        tid = t.get("id")
        le = last_exec.get(tid)
        last_ok = _naive((ok_info.get(tid) or {}).get("last_ok"))
        st = _task_state(t, le, last_ok, now)
        paths = _parse_source_paths(t.get("source_paths"))
        lok = last_ok_exec.get(tid) or {}
        protected_bytes = int(lok.get("bytes_total") or lok.get("bytes_processed") or 0)
        node = {
            "id": f"task:{tid}", "task_id": tid, "name": t.get("name") or f"Tarefa {tid}",
            "type": t.get("type") or "backup", "engine": t.get("engine"),
            "repository_id": t.get("repository_id"),
            "state": st["state"], "label": st["label"], "progress": st["progress"],
            "schedule_cron": t.get("schedule_cron") if t.get("schedule_enabled") else None,
            "next_run": _iso(st["next_run"]), "expected_last": _iso(st["expected_last"]),
            "last_run": _iso(_naive((le or {}).get("started_at")) or _naive(t.get("last_run"))),
            "last_ok": _iso(last_ok), "last_error": (le or {}).get("error_message") if st["state"] == "error" else None,
            "protected_bytes": protected_bytes, "sources": paths,
        }
        task_nodes.append(node)
        for p in paths:
            key = p.rstrip("\\/").lower() or p.lower()
            s = sources.setdefault(key, {"id": f"src:{key}", "path": p, "tasks": [], "states": [], "last_attempt": None})
            s["tasks"].append(node["id"])
            s["states"].append(st["state"])
            la = _naive((le or {}).get("started_at"))
            if la and (s["last_attempt"] is None or la > s["last_attempt"]):
                s["last_attempt"] = la
        if st["next_run"]:
            upcoming.append({"task_id": tid, "name": node["name"], "type": node["type"], "at": st["next_run"]})
        if st["state"] == "error":
            issues.append({"severity": "error", "task_id": tid,
                           "text": f"{node['name']}: última execução terminou como '{(le or {}).get('status')}'"
                                   + (f" — {str(node['last_error'])[:180]}" if node["last_error"] else "")})
        elif st["state"] == "late":
            issues.append({"severity": "warning", "task_id": tid,
                           "text": f"{node['name']}: execução prevista em {st['expected_last'].strftime('%d/%m %H:%M')} não concluiu com sucesso"})
        elif st["state"] == "never" and t.get("enabled") not in (False, 0):
            issues.append({"severity": "info", "task_id": tid, "text": f"{node['name']}: nunca foi executada"})
        if not paths:
            issues.append({"severity": "warning", "task_id": tid, "text": f"{node['name']}: sem pastas de origem configuradas"})
        if not t.get("repository_id"):
            issues.append({"severity": "warning", "task_id": tid, "text": f"{node['name']}: sem repositório de destino"})

    # ── Repositórios e destinos ──
    repo_nodes, dest_nodes = [], {}
    for r in repos:
        rid = r.get("id")
        rtasks = [n for n in task_nodes if n["repository_id"] == rid]
        state = _worst([n["state"] for n in rtasks]) if rtasks else "never"
        dest = _destination_of(r)
        d = dest_nodes.setdefault(dest["key"], {"id": f"dst:{dest['key']}", "kind": dest["kind"], "label": dest["label"],
                                                 "detail": dest["detail"], "repos": [], "states": []})
        d["repos"].append(f"repo:{rid}")
        d["states"].append(state)
        protected = sum(n["protected_bytes"] for n in rtasks)
        repo_nodes.append({
            "id": f"repo:{rid}", "repo_id": rid, "name": r.get("name") or f"Repositório {rid}",
            "engine": r.get("engine"), "type": r.get("type"), "bucket": dest.get("bucket"),
            "destination": d["id"], "tasks": [n["id"] for n in rtasks],
            "state": state, "label": _STATE_LABEL.get(state, state) if rtasks else "Sem tarefas",
            "protected_bytes": protected,
        })
        if not rtasks:
            issues.append({"severity": "info", "repo_id": rid, "text": f"Repositório {r.get('name')}: nenhuma tarefa grava nele"})

    for d in dest_nodes.values():
        st = _worst(d.pop("states"))
        d["state"], d["label_state"] = st, _STATE_LABEL.get(st, st)
        if d["kind"] == "local":
            root = d["label"].replace("Disco ", "")
            try:
                u = psutil.disk_usage(root)
                d["disk"] = {"total": u.total, "free": u.free, "percent": u.percent}
                if u.percent >= 90:
                    issues.append({"severity": "warning", "text": f"Destino {d['label']} com {u.percent:.0f}% ocupado"})
            except Exception as e:
                logger.debug(f"[SYSTEM-MAP] disk_usage destino {root}: {e}")

    # ── Pastas de origem e volumes ──
    source_nodes, volumes = [], {}
    for s in sources.values():
        st = _worst(s["states"])
        exists = os.path.exists(s["path"])
        root = _volume_root(s["path"])
        source_nodes.append({"id": s["id"], "path": s["path"], "tasks": s["tasks"], "state": st,
                             "label": _STATE_LABEL.get(st, st) if exists else "Pasta não encontrada",
                             "exists": exists, "volume": root, "last_attempt": _iso(s["last_attempt"])})
        if not exists:
            issues.append({"severity": "warning", "text": f"Pasta de origem não encontrada neste computador: {s['path']}"})
        if root:
            v = volumes.setdefault(root, {"root": root, "sources": 0})
            v["sources"] += 1
    for root, v in volumes.items():
        try:
            u = psutil.disk_usage(root)
            v.update(total=u.total, free=u.free, used=u.used, percent=u.percent)
        except Exception as e:
            v["error"] = f"Volume inacessível: {str(e)[:120]}"

    upcoming.sort(key=lambda x: x["at"])
    sev = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: sev.get(i["severity"], 3))
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(f"[PERF] GET /api/overview/system-map concluído em {elapsed_ms} ms")
    return {
        "status": "success", "generated_at": now.isoformat(), "elapsed_ms": elapsed_ms,
        "sources": sorted(source_nodes, key=lambda x: x["path"].lower()),
        "tasks": task_nodes, "repositories": repo_nodes, "destinations": list(dest_nodes.values()),
        "volumes": sorted(volumes.values(), key=lambda v: v["root"]),
        "upcoming": [{**u, "at": _iso(u["at"])} for u in upcoming[:8]],
        "issues": issues[:30],
    }
