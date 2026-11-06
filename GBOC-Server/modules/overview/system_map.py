"""
GBOC Server — Mapa do Sistema (todos os Agentes).

GET /api/v1/dashboard/system-map[?agent_id=...]

Monta, a partir do inventário que os Agentes sincronizam (agent_tasks, agent_repositories,
agent_task_executions, agent_volumes, agent_restore_tests), o grafo:
    Pastas de origem → Tarefas → Repositórios → Destinos
com status de cada nó, tamanho real dos repositórios, discos, próximas execuções e problemas.
Destinos em nuvem são agrupados por provedor + bucket, então dois Agentes que gravam no mesmo
bucket aparecem ligados ao mesmo nó.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gboc_system_map")

OK_STATUSES = ("completed", "success")
FAIL_STATUSES = ("failed", "error", "interrupted", "cancelled", "stopped")
CRON_LOOKAHEAD_HOURS = 8 * 24
LATE_TOLERANCE = timedelta(minutes=60)
INVENTORY_STALE = timedelta(hours=2)
RESTORE_TEST_STALE = timedelta(days=30)
STATUS_RANK = {"ok": 0, "never": 1, "paused": 1, "manual": 1, "offline": 2, "running": 2, "late": 3, "error": 4}
STATE_LABEL = {"ok": "Em dia", "running": "Executando", "late": "Atrasado", "error": "Cópia incompleta",
               "never": "Nunca executou", "paused": "Pausada", "manual": "Manual", "offline": "Agente offline"}
CLOUD_WORDS = ("s3", "b2", "wasabi", "azure", "gcs", "sftp", "rclone", "minio", "seaweed", "garage", "r2", "cloud")


# ── Cron: mesma semântica do agendador do Agente (engines/scheduler.py: dia da semana 0 = segunda) ──
def _match_cron_field(field: str, value: int) -> bool:
    if field == "*":
        return True
    if field.startswith("*/"):
        return value % int(field[2:]) == 0
    for part in field.split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            if int(lo) <= value <= int(hi):
                return True
        elif int(part) == value:
            return True
    return False


def cron_neighbor(cron_expr: Optional[str], now: datetime, forward: bool) -> Optional[datetime]:
    """Próxima (forward) ou última (backward) execução prevista. Varre por hora e só desce aos minutos quando a hora casa."""
    parts = (cron_expr or "").strip().split()
    if len(parts) < 5:
        return None
    try:
        base = now.replace(minute=0, second=0, microsecond=0)
        step = 1 if forward else -1
        for h in range(CRON_LOOKAHEAD_HOURS + 1):
            hdt = base + timedelta(hours=h * step)
            if not (_match_cron_field(parts[1], hdt.hour) and _match_cron_field(parts[2], hdt.day)
                    and _match_cron_field(parts[3], hdt.month) and _match_cron_field(parts[4], hdt.weekday())):
                continue
            for m in (range(60) if forward else range(59, -1, -1)):
                cand = hdt.replace(minute=m)
                if (forward and cand <= now) or (not forward and cand > now):
                    continue
                if _match_cron_field(parts[0], m):
                    return cand
    except (ValueError, IndexError) as e:
        logger.debug(f"[SYSTEM-MAP] cron inválido '{cron_expr}': {e}")
    return None


# ── Utilitários ─────────────────────────────────────────────────────────────
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


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def parse_source_paths(raw) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(p).strip() for p in raw if str(p).strip()]
    text = str(raw).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(p).strip() for p in parsed if str(p).strip()]
        if isinstance(parsed, str):
            text = parsed
    except (ValueError, TypeError):
        pass
    parts: List[str] = []
    for line in text.replace("\r", "\n").split("\n"):
        parts.extend(line.split(";"))
    return [p.strip() for p in parts if p.strip()]


def volume_root(path: str) -> Optional[str]:
    if not path:
        return None
    p = path.strip().strip('"')
    m = re.match(r"^([A-Za-z]):", p)
    if m:
        return f"{m.group(1).upper()}:\\"
    m = re.match(r"^(\\\\|//)([^\\/]+)[\\/]([^\\/]+)", p)
    if m:
        return f"\\\\{m.group(2)}\\{m.group(3)}"
    return "/" if p.startswith("/") else None


def _match_volume(path: str, volumes: List[dict]) -> Optional[dict]:
    """Volume (agent_volumes) que contém o caminho: maior ponto de montagem que é prefixo."""
    norm = path.replace("/", "\\").lower() if re.match(r"^[A-Za-z]:", path) else path
    best = None
    for v in volumes:
        mp = str(v.get("mountpoint") or "")
        mpn = mp.replace("/", "\\").lower() if re.match(r"^[A-Za-z]:", mp) else mp
        if not mpn:
            continue
        if norm == mpn.rstrip("\\/") or norm.startswith(mpn if mpn.endswith(("\\", "/")) else mpn + ("\\" if "\\" in mpn else "/")):
            if best is None or len(mpn) > len(str(best.get("mountpoint"))):
                best = v
    return best


def worst(states) -> str:
    states = [s for s in states if s]
    if not states:
        return "never"
    if "error" in states:
        return "error"
    if "running" in states:
        return "running"
    return max(states, key=lambda s: STATUS_RANK.get(s, 0))


def destination_of(repo: dict, hostname: str) -> dict:
    rtype = str(repo.get("type") or "local").lower()
    engine = str(repo.get("engine") or "").lower()
    path = str(repo.get("path") or "")
    target = str(repo.get("target") or "")
    provider = str(repo.get("provider") or "").lower()
    is_cloud = (rtype not in ("local", "")) or any(w in provider for w in CLOUD_WORDS) \
        or bool(re.match(r"^(s3|b2|azure|gs|sftp|rclone|wasabi):", path, re.I))
    if not is_cloud:
        root = volume_root(path)
        return {"key": f"local:{repo['agent_id']}:{(root or path).lower()}", "kind": "local",
                "label": f"{hostname} · Disco {root}" if root else f"{hostname} · Disco local",
                "detail": path or "caminho não configurado"}
    if not provider:
        m = re.match(r"^([a-z0-9]+):", path, re.I)
        provider = (m.group(1) if m else (rtype if rtype not in ("cloud", "local") else engine)).lower()
    if "wasabi" in (path + target).lower():
        provider = "wasabi"
    bucket = target if target and target != path else ""
    if not bucket:
        m = re.match(r"^[a-z0-9]+:(?://[^/]+/)?([^/:]+)", path, re.I)
        bucket = m.group(1) if m else ""
    return {"key": f"cloud:{provider}:{bucket}".lower(), "kind": "cloud",
            "label": provider.upper() if provider else "Nuvem",
            "detail": " · ".join(x for x in (provider, bucket) if x) or "nuvem", "bucket": bucket or None}


def _task_state(t: dict, last_exec: Optional[dict], last_ok, now: datetime) -> dict:
    enabled = t.get("enabled")
    enabled = True if enabled is None else bool(enabled)
    cron = t.get("schedule_cron") if (t.get("schedule_enabled") and t.get("schedule_cron")) else None
    next_run = cron_neighbor(cron, now, True) if (cron and enabled) else None
    prev_slot = cron_neighbor(cron, now, False) if (cron and enabled) else None
    exec_status = str((last_exec or {}).get("status") or t.get("last_status") or "").lower()
    has_run = bool(last_exec) or bool(t.get("last_run"))
    if str(t.get("status") or "").lower() == "running" or exec_status == "running":
        state, label = "running", "Executando"
    elif not enabled:
        state, label = "paused", "Pausada"
    elif not has_run:
        state, label = "never", "Nunca executou"
    elif exec_status in FAIL_STATUSES:
        state, label = "error", "Com erro" if exec_status in ("failed", "error") else "Cópia incompleta"
    elif prev_slot and (last_ok is None or last_ok < prev_slot - LATE_TOLERANCE) and prev_slot < now - LATE_TOLERANCE:
        state, label = "late", "Atrasado"
    elif not cron:
        state, label = ("ok", "Manual · Em dia") if exec_status in OK_STATUSES else ("manual", "Manual")
    else:
        state, label = "ok", "Em dia"
    return {"state": state, "label": label, "next_run": next_run, "expected_last": prev_slot}


def _fetch(cur, sql: str, params=()) -> List[dict]:
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def _offline_threshold() -> int:
    try:
        from modules.agents.agent_presence import threshold_minutes
        return int(threshold_minutes())
    except Exception as e:
        logger.debug(f"[SYSTEM-MAP] limite de presença padrão: {e}")
        return 10


# ── Montagem ───────────────────────────────────────────────────────────────
def build_system_map(conn, agent_id: Optional[str] = None) -> Dict[str, Any]:
    from psycopg2.extras import RealDictCursor
    t0 = time.perf_counter()
    now = datetime.now()
    try:
        from modules.agents.inventory_sync import ensure_schema
        ensure_schema(conn)
    except Exception as e:
        logger.debug(f"[SYSTEM-MAP] ensure_schema: {e}")

    flt, params = ("AND agent_id = %s", (agent_id,)) if agent_id else ("", ())
    cur = conn.cursor(cursor_factory=RealDictCursor)
    agents_all = _fetch(cur, "SELECT agent_id, hostname, last_heartbeat, agent_version FROM agents ORDER BY hostname")
    tasks = _fetch(cur, f"""SELECT agent_id, task_id, name, status, task_type, engine, repository_id, source_paths,
                                   schedule_cron, schedule_enabled, enabled, last_run, last_status
                            FROM agent_tasks WHERE removed_at IS NULL {flt} ORDER BY agent_id, task_id""", params)
    repos = _fetch(cur, f"""SELECT agent_id, repo_id, name, engine, type, status, path, target, provider, size_bytes,
                                   snapshot_count, free_bytes, capacity_bytes, size_recorded_at
                            FROM agent_repositories WHERE removed_at IS NULL {flt} ORDER BY agent_id, repo_id""", params)
    last_exec = {(r["agent_id"], r["task_id"]): r for r in _fetch(cur, f"""
        SELECT DISTINCT ON (agent_id, task_id) agent_id, task_id, status, started_at, completed_at, error_message, bytes_processed
        FROM agent_task_executions WHERE task_id IS NOT NULL {flt}
        ORDER BY agent_id, task_id, started_at DESC NULLS LAST, execution_id DESC""", params)}
    last_ok = {(r["agent_id"], r["task_id"]): r for r in _fetch(cur, f"""
        SELECT DISTINCT ON (agent_id, task_id) agent_id, task_id, COALESCE(completed_at, started_at) AS at, bytes_processed
        FROM agent_task_executions WHERE status IN ('completed', 'success') AND task_id IS NOT NULL {flt}
        ORDER BY agent_id, task_id, COALESCE(completed_at, started_at) DESC NULLS LAST""", params)}
    volumes = _fetch(cur, f"SELECT agent_id, mountpoint, total_bytes, used_bytes, free_bytes FROM agent_volumes WHERE TRUE {flt}", params)
    inv_status = {r["agent_id"]: r for r in _fetch(cur, "SELECT agent_id, last_inventory_at FROM agent_inventory_status")}
    try:
        restore_tests = {r["agent_id"]: r for r in _fetch(cur, f"""
            SELECT DISTINCT ON (agent_id) agent_id, status, repository_name, started_at, completed_at, error_message
            FROM agent_restore_tests WHERE TRUE {flt} ORDER BY agent_id, COALESCE(completed_at, started_at) DESC NULLS LAST""", params)}
    except Exception as e:
        conn.rollback()
        logger.debug(f"[SYSTEM-MAP] agent_restore_tests indisponível: {e}")
        restore_tests = {}
    cur.close()

    offline_min = _offline_threshold()
    agent_info: Dict[str, dict] = {}
    for a in agents_all:
        hb = _naive(a.get("last_heartbeat"))
        agent_info[a["agent_id"]] = {"agent_id": a["agent_id"], "hostname": a.get("hostname") or a["agent_id"],
                                     "online": bool(hb and hb > now - timedelta(minutes=offline_min)),
                                     "last_heartbeat": _iso(hb), "version": a.get("agent_version")}
    host = lambda aid: (agent_info.get(aid) or {}).get("hostname") or aid
    vols_by_agent: Dict[str, List[dict]] = {}
    for v in volumes:
        vols_by_agent.setdefault(v["agent_id"], []).append(v)

    edges: List[List[str]] = []
    issues: List[dict] = []
    upcoming: List[dict] = []
    sources: Dict[str, dict] = {}
    task_nodes: List[dict] = []

    for t in tasks:
        aid, tid = t["agent_id"], t["task_id"]
        le = last_exec.get((aid, tid))
        lo = last_ok.get((aid, tid)) or {}
        lok_at = _naive(lo.get("at"))
        st = _task_state(t, le, lok_at, now)
        if not (agent_info.get(aid) or {}).get("online") and st["state"] == "running":
            st.update(state="offline", label="Agente offline")
        node_id = f"task:{aid}:{tid}"
        paths = parse_source_paths(t.get("source_paths"))
        last_err = (le or {}).get("error_message") if st["state"] == "error" else None
        task_nodes.append({
            "id": node_id, "agent_id": aid, "hostname": host(aid), "task_id": tid, "name": t.get("name") or f"Tarefa {tid}",
            "type": t.get("task_type") or "backup", "engine": t.get("engine"),
            "state": st["state"], "label": st["label"], "next_run": _iso(st["next_run"]),
            "expected_last": _iso(st["expected_last"]), "last_ok": _iso(lok_at), "last_error": last_err,
            "last_run": _iso(_naive((le or {}).get("started_at")) or _naive(t.get("last_run"))),
            "protected_bytes": int(lo.get("bytes_processed") or 0), "sources": paths,
        })
        if t.get("repository_id") is not None:
            edges.append([node_id, f"repo:{aid}:{t['repository_id']}"])
        for p in paths:
            key = p.rstrip("\\/").lower() or p.lower()
            sid = f"src:{aid}:{key}"
            s = sources.setdefault(sid, {"id": sid, "agent_id": aid, "hostname": host(aid), "path": p,
                                         "tasks": [], "states": [], "last_attempt": None})
            s["tasks"].append(node_id)
            s["states"].append(st["state"])
            la = _naive((le or {}).get("started_at"))
            if la and (s["last_attempt"] is None or la > s["last_attempt"]):
                s["last_attempt"] = la
            edges.append([sid, node_id])
        name = f"{host(aid)} · {t.get('name')}"
        if st["next_run"]:
            upcoming.append({"agent_id": aid, "hostname": host(aid), "name": t.get("name"), "type": t.get("task_type") or "backup", "at": st["next_run"]})
        if st["state"] == "error":
            issues.append({"severity": "error", "agent_id": aid, "text": f"{name}: última execução terminou como "
                           f"'{(le or {}).get('status') or t.get('last_status')}'" + (f" — {str(last_err)[:180]}" if last_err else "")})
        elif st["state"] == "late":
            issues.append({"severity": "warning", "agent_id": aid,
                           "text": f"{name}: execução prevista em {st['expected_last'].strftime('%d/%m %H:%M')} não concluiu com sucesso"})
        elif st["state"] == "never":
            issues.append({"severity": "info", "agent_id": aid, "text": f"{name}: nunca foi executada"})
        if not paths:
            issues.append({"severity": "warning", "agent_id": aid, "text": f"{name}: sem pastas de origem configuradas"})
        if t.get("repository_id") is None:
            issues.append({"severity": "warning", "agent_id": aid, "text": f"{name}: sem repositório de destino"})

    repo_nodes: List[dict] = []
    dests: Dict[str, dict] = {}
    for r in repos:
        aid, rid = r["agent_id"], r["repo_id"]
        node_id = f"repo:{aid}:{rid}"
        rtasks = [n for n in task_nodes if n["agent_id"] == aid and [n["id"], node_id] in edges]
        state = worst([n["state"] for n in rtasks]) if rtasks else "never"
        d = destination_of(r, host(aid))
        dn = dests.setdefault(d["key"], {"id": f"dst:{d['key']}", "kind": d["kind"], "label": d["label"],
                                         "detail": d["detail"], "repos": [], "states": [], "agents": set(),
                                         "size_bytes": 0, "free_bytes": None, "capacity_bytes": None})
        dn["repos"].append(node_id)
        dn["states"].append(state)
        dn["agents"].add(host(aid))
        dn["size_bytes"] += int(r.get("size_bytes") or 0)
        if d["kind"] == "local" and r.get("capacity_bytes"):
            dn["free_bytes"], dn["capacity_bytes"] = r.get("free_bytes"), r.get("capacity_bytes")
        edges.append([node_id, dn["id"]])
        repo_nodes.append({
            "id": node_id, "agent_id": aid, "hostname": host(aid), "repo_id": rid, "name": r.get("name") or f"Repositório {rid}",
            "engine": r.get("engine"), "type": r.get("type"), "bucket": d.get("bucket"), "destination": dn["id"],
            "destination_detail": d["detail"], "tasks": [n["id"] for n in rtasks],
            "state": state, "label": STATE_LABEL.get(state, state) if rtasks else "Sem tarefas",
            "size_bytes": r.get("size_bytes"), "snapshot_count": r.get("snapshot_count"),
            "size_recorded_at": _iso(_naive(r.get("size_recorded_at"))),
            "protected_bytes": sum(n["protected_bytes"] for n in rtasks),
            "free_bytes": r.get("free_bytes"), "capacity_bytes": r.get("capacity_bytes"),
        })
        if not rtasks:
            issues.append({"severity": "info", "agent_id": aid, "text": f"{host(aid)} · repositório {r.get('name')}: nenhuma tarefa grava nele"})
        cap, free = r.get("capacity_bytes"), r.get("free_bytes")
        if cap and free is not None and cap > 0 and (1 - free / cap) >= 0.9:
            issues.append({"severity": "warning", "agent_id": aid,
                           "text": f"{host(aid)} · destino de {r.get('name')} com {round((1 - free / cap) * 100)}% ocupado"})

    dest_nodes = []
    for dn in dests.values():
        st = worst(dn.pop("states"))
        dn["state"], dn["agents"] = st, sorted(dn["agents"])
        dest_nodes.append(dn)

    # Pastas de origem + volumes por Agente
    source_nodes, comp = [], {}
    for s in sources.values():
        st = worst(s["states"])
        source_nodes.append({"id": s["id"], "agent_id": s["agent_id"], "hostname": s["hostname"], "path": s["path"],
                             "tasks": s["tasks"], "state": st, "label": STATE_LABEL.get(st, st),
                             "last_attempt": _iso(s["last_attempt"])})
        v = _match_volume(s["path"], vols_by_agent.get(s["agent_id"], []))
        key = (s["agent_id"], (v or {}).get("mountpoint") or volume_root(s["path"]) or s["path"])
        c = comp.setdefault(key, {"agent_id": s["agent_id"], "hostname": s["hostname"], "root": key[1], "sources": 0,
                                  "total": (v or {}).get("total_bytes"), "free": (v or {}).get("free_bytes"),
                                  "used": (v or {}).get("used_bytes")})
        c["sources"] += 1
    for c in comp.values():
        c["percent"] = round(c["used"] / c["total"] * 100, 1) if c.get("total") and c.get("used") is not None else None
        if c["percent"] is not None and c["percent"] >= 90:
            issues.append({"severity": "warning", "agent_id": c["agent_id"], "text": f"{c['hostname']} · volume {c['root']} com {c['percent']:.0f}% ocupado"})

    # Agentes: presença, inventário e teste de recuperação
    shown = {agent_id} if agent_id else {n["agent_id"] for n in task_nodes + repo_nodes} | set(agent_info)
    agents_out, restore_out = [], []
    for aid in sorted(shown, key=lambda x: host(x).lower()):
        info = agent_info.get(aid)
        if not info:
            continue
        inv = _naive((inv_status.get(aid) or {}).get("last_inventory_at"))
        agents_out.append({**info, "last_inventory_at": _iso(inv)})
        if not info["online"]:
            hb = info["last_heartbeat"]
            issues.append({"severity": "error", "agent_id": aid, "text": f"Agente {info['hostname']} offline"
                           + (f" — último contato {datetime.fromisoformat(hb).strftime('%d/%m %H:%M')}" if hb else " — nunca enviou heartbeat")})
        elif inv is None:
            issues.append({"severity": "warning", "agent_id": aid, "text": f"Agente {info['hostname']}: inventário ainda não sincronizado"})
        elif inv < now - INVENTORY_STALE:
            issues.append({"severity": "warning", "agent_id": aid,
                           "text": f"Agente {info['hostname']}: inventário desatualizado (última sincronização {inv.strftime('%d/%m %H:%M')})"})
        rt = restore_tests.get(aid)
        if rt:
            at = _naive(rt.get("completed_at") or rt.get("started_at"))
            restore_out.append({"agent_id": aid, "hostname": info["hostname"], "status": rt.get("status"),
                                "repository_name": rt.get("repository_name"), "at": _iso(at)})
            if str(rt.get("status") or "").lower() not in OK_STATUSES + ("passed", "ok", "running"):
                issues.append({"severity": "error", "agent_id": aid, "text": f"{info['hostname']}: último teste de recuperação "
                               f"terminou como '{rt.get('status')}'" + (f" — {str(rt.get('error_message'))[:160]}" if rt.get("error_message") else "")})
            elif at and at < now - RESTORE_TEST_STALE:
                issues.append({"severity": "warning", "agent_id": aid,
                               "text": f"{info['hostname']}: último teste de recuperação há mais de 30 dias ({at.strftime('%d/%m/%Y')})"})
        elif repo_nodes and any(r["agent_id"] == aid for r in repo_nodes):
            restore_out.append({"agent_id": aid, "hostname": info["hostname"], "status": None, "at": None})
            issues.append({"severity": "info", "agent_id": aid, "text": f"{info['hostname']}: nenhum teste de recuperação registrado"})

    upcoming.sort(key=lambda x: x["at"])
    sev = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: sev.get(i["severity"], 3))
    return {
        "status": "success", "generated_at": now.isoformat(), "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
        "scope": agent_id or "all",
        "agents": agents_out,
        "agents_all": [{"agent_id": a["agent_id"], "hostname": a["hostname"], "online": a["online"]}
                       for a in sorted(agent_info.values(), key=lambda x: x["hostname"].lower())],
        "sources": sorted(source_nodes, key=lambda x: (x["hostname"].lower(), x["path"].lower())),
        "tasks": task_nodes, "repositories": repo_nodes, "destinations": dest_nodes, "edges": edges,
        "volumes": sorted(comp.values(), key=lambda c: (c["hostname"].lower(), str(c["root"]))),
        "restore_tests": restore_out,
        "upcoming": [{**u, "at": _iso(u["at"])} for u in upcoming[:10]],
        "issues": issues[:40],
    }
