#!/usr/bin/env python3
# ==============================================================================
# GBOC System v14.7.6 Enterprise Edition
# Module: Flagship Reports — coleta de dados reais e construtores (Agent)
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================
"""
Construtores dos relatórios Flagship do GBOC Agent (REP-F1..F5, F7, F8).

Fonte: banco PostgreSQL do próprio Agente e telemetria da máquina onde o Agente roda.
Nenhum valor presumido (AI_RULES.md §11): sem amostra, o indicador é "N/D".
Saída no formato do renderizador do Agente: score, kpis, delta, analytical_summary,
tables [{title, headers, rows}] e recommended_actions.
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

PERIOD_DAYS = 30
RECENT_HOURS = 48
SUCCESS = ("completed", "success", "ok")
FAILED = ("failed", "error")


def _naive(v: Any) -> Any:
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.astimezone().replace(tzinfo=None)
    return v


def _pct(part: float, total: float) -> float | None:
    return round(part * 100.0 / total, 1) if total else None


def _fp(v: float | None) -> str:
    return f"{v}%" if v is not None else "N/D"


def _dt(v: Any) -> str:
    v = _naive(v)
    return v.strftime("%d/%m/%Y %H:%M") if isinstance(v, datetime) else (str(v) if v else "—")


def _age(v: Any, now: datetime) -> str:
    v = _naive(v)
    if not isinstance(v, datetime):
        return "nunca"
    h = (now - v).total_seconds() / 3600
    return f"{h:.1f} h" if h < 48 else f"{h / 24:.1f} dias"


def _gb(b: float | None) -> str:
    return f"{b / 1024 ** 3:,.2f} GB" if b is not None else "N/D"


def _st(v: float | None, ok: float, warn: float) -> str:
    if v is None:
        return "N/D"
    return "OK" if v >= ok else ("ATENÇÃO" if v >= warn else "CRÍTICO")


def _d(kind: str, text: str) -> dict[str, str]:
    return {"type": {"up": "improvement", "down": "warning"}.get(kind, "trend"),
            "icon": {"up": "↑", "down": "↓"}.get(kind, "→"), "text": text}


def _q(cur, conn, sql: str, params: tuple = ()) -> list[tuple]:
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception as err:
        logger.warning(f"[Flagship Agent] consulta ignorada: {str(err)[:160]}")
        try:
            conn.rollback()
        except Exception:
            pass
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Coleta
# ──────────────────────────────────────────────────────────────────────────────

def collect_agent_report_data(days: int = PERIOD_DAYS) -> dict[str, Any]:
    data: dict[str, Any] = {"available": False, "error": "", "now": datetime.now(), "days": days,
                            "tasks": [], "executions": [], "repositories": [], "storage": [], "storage_series": [],
                            "canaries": [], "incidents": [], "last_scan": None, "restores": [], "surebackup": [],
                            "integrity": [], "audit": [], "disks": [], "protection": None}
    try:
        from shared_core import get_shared_core
        with get_shared_core().get_db_connection() as conn:
            cur = conn.cursor()
            for r in _q(cur, conn, """SELECT t.id, t.name, t.engine, t.type, t.enabled, t.schedule_enabled, t.schedule_cron,
                                             t.retention_days, r.name
                                      FROM tasks t LEFT JOIN repositories r ON r.id = t.repository_id ORDER BY t.name"""):
                data["tasks"].append({"id": r[0], "name": r[1] or f"Tarefa #{r[0]}", "engine": r[2], "type": r[3],
                                      "enabled": bool(r[4]), "scheduled": bool(r[5]), "cron": r[6],
                                      "retention_days": r[7], "repository": r[8]})
            names = {t["id"]: t["name"] for t in data["tasks"]}
            for r in _q(cur, conn, """SELECT task_id, LOWER(COALESCE(status,'')), started_at, completed_at,
                                             COALESCE(duration_seconds,0), COALESCE(bytes_processed,0),
                                             COALESCE(bytes_added,0), error_message
                                      FROM task_executions WHERE started_at >= NOW() - make_interval(days => %s)
                                      ORDER BY started_at""", (days,)):
                data["executions"].append({"task_id": r[0], "task": names.get(r[0], f"Tarefa #{r[0]}"), "status": r[1],
                                           "start": _naive(r[2]), "end": _naive(r[3]), "duration": float(r[4] or 0),
                                           "bytes": int(r[5] or 0), "added": int(r[6] or 0), "error": r[7]})
            for r in _q(cur, conn, """SELECT id, name, type, path, engine, status, enabled, initialized,
                                             (COALESCE(encryption_password,'') <> '' OR COALESCE(password,'') <> '')
                                      FROM repositories ORDER BY name"""):
                data["repositories"].append({"id": r[0], "name": r[1], "type": r[2], "path": r[3], "engine": r[4],
                                             "status": r[5], "enabled": bool(r[6]), "initialized": bool(r[7]),
                                             "encrypted": bool(r[8])})
            for r in _q(cur, conn, """SELECT DISTINCT ON (repository_id) repository_id, repository_name, engine,
                                             size_bytes, snapshot_count, recorded_at
                                      FROM storage_usage_history ORDER BY repository_id, recorded_at DESC"""):
                data["storage"].append({"id": r[0], "name": r[1], "engine": r[2], "size": int(r[3] or 0),
                                        "snapshots": int(r[4] or 0), "at": _naive(r[5])})
            for r in _q(cur, conn, """SELECT d, SUM(sz) FROM (
                                          SELECT DISTINCT ON (repository_id, recorded_at::date) recorded_at::date d, size_bytes sz
                                          FROM storage_usage_history WHERE recorded_at >= NOW() - make_interval(days => %s)
                                          ORDER BY repository_id, recorded_at::date, recorded_at DESC) t
                                      GROUP BY d ORDER BY d""", (days,)):
                data["storage_series"].append((r[0], int(r[1] or 0)))
            for r in _q(cur, conn, "SELECT file_path, is_compromised, last_verified_at FROM ransomware_canaries"):
                data["canaries"].append({"path": r[0], "compromised": bool(r[1]), "verified": _naive(r[2])})
            for r in _q(cur, conn, """SELECT detected_at, status, resolved_at FROM ransomware_incidents
                                      WHERE detected_at >= NOW() - make_interval(days => %s) OR COALESCE(status,'') <> 'resolved'""", (days,)):
                data["incidents"].append({"at": _naive(r[0]), "status": (r[1] or "").lower(), "resolved": _naive(r[2])})
            rows = _q(cur, conn, "SELECT threat_level, started_at FROM ransomware_scans WHERE status='completed' ORDER BY started_at DESC LIMIT 1")
            if rows:
                data["last_scan"] = {"threat": rows[0][0], "at": _naive(rows[0][1])}
            for r in _q(cur, conn, """SELECT snapshot_id, LOWER(COALESCE(status,'')), COALESCE(duration_seconds,0),
                                             COALESCE(bytes_restored,0), error_message, created_at
                                      FROM restore_history WHERE created_at >= NOW() - make_interval(days => %s)
                                      ORDER BY created_at DESC""", (days,)):
                data["restores"].append({"snapshot": r[0], "status": r[1], "duration": int(r[2] or 0),
                                         "bytes": int(r[3] or 0), "error": r[4], "at": _naive(r[5])})
            for r in _q(cur, conn, """SELECT target_name, LOWER(COALESCE(status,'')), boot_verified, services_verified,
                                             COALESCE(boot_time_seconds,0), started_at
                                      FROM surebackup_verifications ORDER BY started_at DESC LIMIT 20"""):
                data["surebackup"].append({"target": r[0], "status": r[1], "boot": bool(r[2]), "services": bool(r[3]),
                                           "boot_time": int(r[4] or 0), "at": _naive(r[5])})
            for r in _q(cur, conn, """SELECT DISTINCT ON (repository_id) repository_id, LOWER(COALESCE(status,'')),
                                             COALESCE(errors_found,0), finished_at
                                      FROM integrity_checks ORDER BY repository_id, started_at DESC"""):
                data["integrity"].append({"repository_id": r[0], "status": r[1], "errors": int(r[2] or 0), "at": _naive(r[3])})
            for r in _q(cur, conn, """SELECT action, COALESCE(result,'success'), COUNT(*) FROM audit_log
                                      WHERE timestamp >= NOW() - make_interval(days => %s) GROUP BY 1,2 ORDER BY 3 DESC""", (days,)):
                data["audit"].append((r[0], r[1], int(r[2])))
            cur.close()
        data["available"] = True
    except Exception as err:
        logger.error(f"[Flagship Agent] falha na coleta: {err}")
        data["error"] = f"Banco do Agente indisponível ({err.__class__.__name__})"

    try:
        import psutil
        for p in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(p.mountpoint)
                data["disks"].append({"mount": p.mountpoint, "total": u.total, "used": u.used, "percent": u.percent})
            except OSError:
                continue
    except Exception as err:
        logger.warning(f"[Flagship Agent] telemetria de discos indisponível: {err}")

    try:
        from engines.ransomware_detector import get_protection_status
        data["protection"] = get_protection_status()
    except Exception as err:
        logger.warning(f"[Flagship Agent] status de proteção indisponível: {err}")
    return data


def _unavailable(data: dict, score_key: str) -> dict | None:
    if data["available"]:
        return None
    return {score_key: None,
            "kpis": [{"label": "Fonte de dados", "value": "Indisponível", "target": "PostgreSQL do Agente", "status": "CRÍTICO"}],
            "delta": [_d("down", data["error"])],
            "analytical_summary": f"Relatório não gerado: {data['error']}.",
            "tables": [],
            "recommended_actions": [{"priority": "ALTA", "description": "Verificar o banco PostgreSQL do Agente.",
                                     "owner": "Administrador", "deadline": "Imediato"}]}


def _per_task(data: dict) -> list[dict]:
    now = data["now"]
    groups: dict[Any, list[dict]] = defaultdict(list)
    for e in data["executions"]:
        groups[e["task_id"]].append(e)
    out = []
    for t in data["tasks"]:
        ex = groups.get(t["id"], [])
        fin = [e for e in ex if e["status"] in SUCCESS + FAILED]
        ok = [e for e in fin if e["status"] in SUCCESS]
        ok_times = [e["end"] or e["start"] for e in ok if (e["end"] or e["start"])]
        intervals = [(b - a).total_seconds() / 60 for a, b in zip(ok_times, ok_times[1:]) if b > a]
        med = statistics.median(intervals) if intervals else None
        last_ok = ok_times[-1] if ok_times else None
        age = (now - last_ok).total_seconds() / 60 if last_ok else None
        if last_ok is None:
            cls = "NÃO CONFORME" if fin else ("N/D" if t["enabled"] else "DESABILITADA")
        elif med is None:
            cls = "N/D"
        else:
            cls = "CONFORME" if age <= 2 * med else ("EM RISCO" if age <= 4 * med else "NÃO CONFORME")
        durs = [e["duration"] for e in ok if e["duration"] > 0]
        out.append({**t, "executions": len(ex), "finished": len(fin), "success": len(ok), "failed": len(fin) - len(ok),
                    "rate": _pct(len(ok), len(fin)), "last_ok": last_ok, "median_min": med,
                    "class": cls, "avg_dur": statistics.mean(durs) if durs else None,
                    "last_error": next((e["error"] for e in reversed(ex) if e["status"] in FAILED and e["error"]), None)})
    return out


# ──────────────────────────────────────────────────────────────────────────────
# F1 — Protection Scorecard
# ──────────────────────────────────────────────────────────────────────────────

def protection(data: dict) -> dict:
    if (u := _unavailable(data, "protection_score")):
        return u
    now = data["now"]
    tasks = _per_task(data)
    enabled = [t for t in tasks if t["enabled"]]
    fin = [e for e in data["executions"] if e["status"] in SUCCESS + FAILED]
    ok = [e for e in fin if e["status"] in SUCCESS]
    rate = _pct(len(ok), len(fin))
    recent = [t for t in enabled if t["last_ok"] and now - t["last_ok"] <= timedelta(hours=RECENT_HOURS)]
    coverage = _pct(len(recent), len(enabled))
    restores_ok = [r for r in data["restores"] if r["status"] in SUCCESS]
    known = [(v, w) for v, w in ((rate, 0.5), (coverage, 0.5)) if v is not None]
    score = round(sum(v * w for v, w in known) / sum(w for _, w in known)) if known else None
    comp = sum(1 for c in data["canaries"] if c["compromised"])
    return {
        "protection_score": score,
        "kpis": [
            {"label": "Taxa de Sucesso (30d)", "value": _fp(rate), "target": "≥ 99%", "status": _st(rate, 99, 95)},
            {"label": f"Tarefas com backup ≤ {RECENT_HOURS}h", "value": f"{len(recent)} / {len(enabled)}", "target": "100%", "status": _st(coverage, 100, 80)},
            {"label": "Falhas no Período", "value": str(len(fin) - len(ok)), "target": "0", "status": "OK" if len(fin) == len(ok) else "ATENÇÃO"},
            {"label": "Restores Testados (30d)", "value": f"{len(restores_ok)} OK de {len(data['restores'])}", "target": "≥ 1 por mês",
             "status": "OK" if restores_ok else "ATENÇÃO"},
            {"label": "Canários", "value": f"{len(data['canaries']) - comp}/{len(data['canaries'])} íntegros" if data["canaries"] else "Nenhum implantado",
             "target": "0 comprometidos", "status": "CRÍTICO" if comp else ("OK" if data["canaries"] else "N/D")},
        ],
        "delta": [
            _d("up" if coverage == 100 else "down", f"{len(recent)} de {len(enabled)} tarefas habilitadas com backup bem-sucedido nas últimas {RECENT_HOURS}h."),
            _d("down" if len(fin) - len(ok) else "up", f"{len(fin) - len(ok)} execução(ões) com falha em {data['days']} dias."),
            _d("neutral", f"Volume processado com sucesso: {_gb(sum(e['bytes'] for e in ok))}."),
        ],
        "analytical_summary": (f"Score = média ponderada da taxa de sucesso (50%) e da cobertura de tarefas com backup recente (50%). "
                               f"{len(tasks)} tarefa(s) cadastrada(s), {len(fin)} execução(ões) finalizada(s) no período."),
        "tables": [{
            "title": "Proteção por Tarefa",
            "headers": ["Tarefa", "Motor", "Repositório", "Último Backup OK", "Idade", "Execuções", "Falhas", "Sucesso", "Status"],
            "rows": [[t["name"], t["engine"] or "—", t["repository"] or "—", _dt(t["last_ok"]), _age(t["last_ok"], now),
                      t["executions"], t["failed"], _fp(t["rate"]),
                      "DESABILITADA" if not t["enabled"] else ("CONFORME" if t in recent else "ATENÇÃO")] for t in tasks],
        }],
        "recommended_actions": (
            [{"priority": "ALTA", "description": "Verificar tarefas sem backup recente: " + ", ".join(t["name"] for t in enabled if t not in recent)[:300],
              "owner": "Administrador de Backup", "deadline": "24 horas"}] if len(recent) < len(enabled) else [])
            + ([] if restores_ok else [{"priority": "MÉDIA", "description": "Executar e registrar um teste de restauração.",
                                        "owner": "Administrador de Backup", "deadline": "7 dias"}]),
    }


# ──────────────────────────────────────────────────────────────────────────────
# F2 — Operational Performance
# ──────────────────────────────────────────────────────────────────────────────

def operational(data: dict) -> dict:
    if (u := _unavailable(data, "operational_score")):
        return u
    now = data["now"]
    fin = [e for e in data["executions"] if e["status"] in SUCCESS + FAILED]
    last7 = [e for e in fin if e["start"] and e["start"] >= now - timedelta(days=7)]
    rate7 = _pct(sum(1 for e in last7 if e["status"] in SUCCESS), len(last7))
    ok = [e for e in fin if e["status"] in SUCCESS and e["duration"] > 0]
    tput = sum(e["bytes"] for e in ok) / sum(e["duration"] for e in ok) / 1048576 if ok else None
    reasons = Counter((e["error"] or "sem mensagem de erro").strip().splitlines()[0][:100] for e in fin if e["status"] in FAILED)
    tasks = [t for t in _per_task(data) if t["executions"]]
    return {
        "operational_score": round(rate7) if rate7 is not None else None,
        "kpis": [
            {"label": "Execuções (30d)", "value": str(len(fin)), "target": "Finalizadas", "status": "OK" if fin else "N/D"},
            {"label": "Sucesso (7d)", "value": _fp(rate7), "target": "≥ 99%", "status": _st(rate7, 99, 95)},
            {"label": "Throughput Médio", "value": f"{tput:.1f} MB/s" if tput else "N/D", "target": "Volume/duração", "status": "OK" if tput else "N/D"},
            {"label": "Duração Média", "value": f"{statistics.mean(e['duration'] for e in ok) / 60:.1f} min" if ok else "N/D", "target": "Execuções OK", "status": "OK" if ok else "N/D"},
        ],
        "delta": [_d("down" if reasons else "up", f"{sum(reasons.values())} falha(s) em {len(reasons)} causa(s) distinta(s).")],
        "analytical_summary": "Métricas calculadas por tarefa a partir das execuções registradas no Agente (sem médias globais presumidas).",
        "tables": [
            {"title": "Desempenho por Tarefa",
             "headers": ["Tarefa", "Execuções", "Falhas", "Sucesso", "Duração Média", "Última Falha"],
             "rows": [[t["name"], t["executions"], t["failed"], _fp(t["rate"]),
                       f"{t['avg_dur'] / 60:.1f} min" if t["avg_dur"] else "—", (t["last_error"] or "—")[:160]] for t in tasks]},
            {"title": "Principais Causas de Falha", "headers": ["Mensagem", "Ocorrências"],
             "rows": [[m, n] for m, n in reasons.most_common(10)]},
        ],
        "recommended_actions": [{"priority": "ALTA", "description": f"Corrigir '{t['name']}' ({t['failed']} falhas). Último erro: {(t['last_error'] or '—')[:120]}",
                                 "owner": "Engenharia de Backup", "deadline": "3 dias"}
                                for t in sorted(tasks, key=lambda x: x["failed"], reverse=True)[:3] if t["failed"]],
    }


# ──────────────────────────────────────────────────────────────────────────────
# F3 — Storage Intelligence
# ──────────────────────────────────────────────────────────────────────────────

def storage(data: dict, cost_usd_per_tb: float | None, usd_rate: float, usd_live: bool) -> dict:
    if (u := _unavailable(data, "storage_health_pct")):
        return u
    from engines.ai_predictive import capacity_model
    disks = [{"total_gb": d["total"] / 1024 ** 3, "used_gb": d["used"] / 1024 ** 3} for d in data["disks"]]
    added = [{"start": e["start"], "bytes": e["added"], "status": e["status"]} for e in data["executions"]]
    cap = capacity_model(added, disks)
    total = sum(d["total"] for d in data["disks"]) or None
    used = sum(d["used"] for d in data["disks"]) if data["disks"] else None
    occ = round(used * 100 / total, 1) if total else None
    stored = sum(s["size"] for s in data["storage"]) if data["storage"] else None
    monthly = stored / 1024 ** 4 * cost_usd_per_tb * usd_rate if stored is not None and cost_usd_per_tb else None
    sizes = {s["name"]: s for s in data["storage"]}
    return {
        "storage_health_pct": occ,
        "kpis": [
            {"label": "Ocupação dos Discos do Host", "value": _fp(occ), "target": "< 80%", "status": "N/D" if occ is None else ("OK" if occ < 80 else ("ATENÇÃO" if occ < 90 else "CRÍTICO"))},
            {"label": "Esgotamento Projetado", "value": f"{cap['days_to_exhaustion']} dias" if cap.get("days_to_exhaustion") is not None else ("Sem crescimento" if cap["status"] != "UNAVAILABLE" else "N/D"),
             "target": "> 60 dias", "status": {"OPERACIONAL": "OK", "ALERTA": "ATENÇÃO"}.get(cap["status"], "N/D")},
            {"label": "Volume nos Repositórios", "value": _gb(stored), "target": "Monitor de Storage", "status": "OK" if stored is not None else "N/D"},
            {"label": "Custo Cloud Estimado", "value": f"R$ {monthly:,.2f}/mês" if monthly is not None else "N/D",
             "target": f"US$ {cost_usd_per_tb}/TB × {usd_rate:.2f}" + ("" if usd_live else " (cotação de referência)"), "status": "OK" if monthly is not None else "N/D"},
        ],
        "delta": [_d("neutral", cap["detail"])],
        "analytical_summary": "Ocupação e projeção calculadas com os discos reais da máquina do Agente e o volume efetivamente adicionado pelas execuções.",
        "tables": [
            {"title": "Repositórios", "headers": ["Repositório", "Tipo", "Motor", "Status", "Criptografado", "Tamanho", "Snapshots", "Medido em"],
             "rows": [[r["name"], r["type"] or "—", r["engine"] or "—", r["status"] or "—", "SIM" if r["encrypted"] else "NÃO",
                       _gb(sizes[r["name"]]["size"]) if r["name"] in sizes else "N/D",
                       sizes[r["name"]]["snapshots"] if r["name"] in sizes else "N/D",
                       _dt(sizes[r["name"]]["at"]) if r["name"] in sizes else "—"] for r in data["repositories"]]},
            {"title": "Discos do Host", "headers": ["Ponto de Montagem", "Total", "Usado", "Ocupação"],
             "rows": [[d["mount"], _gb(d["total"]), _gb(d["used"]), f"{d['percent']}%"] for d in data["disks"]]},
        ],
        "recommended_actions": ([{"priority": "ALTA", "description": "Ampliar o storage ou revisar a retenção: esgotamento projetado em menos de 60 dias.",
                                  "owner": "Administrador de Storage", "deadline": "7 dias"}] if cap["status"] == "ALERTA" else [])
                               + ([{"priority": "MÉDIA", "description": "Habilitar o Monitor de Storage para medir o tamanho dos repositórios.",
                                    "owner": "Administrador de Backup", "deadline": "7 dias"}] if not data["storage"] else []),
    }


# ──────────────────────────────────────────────────────────────────────────────
# F4 — Security & Resilience
# ──────────────────────────────────────────────────────────────────────────────

def security(data: dict) -> dict:
    if (u := _unavailable(data, "threat_score")):
        return u
    canaries = data["canaries"]
    comp = sum(1 for c in canaries if c["compromised"])
    open_inc = [i for i in data["incidents"] if i["status"] != "resolved"]
    tools = (data["protection"] or {}).get("integrated_tools", {}) or {}
    installed = [k for k, v in tools.items() if isinstance(v, dict) and v.get("installed")]
    scan = data["last_scan"]
    has_signal = bool(canaries or data["incidents"] or scan or tools)
    threat = min(100, comp * 30 + len(open_inc) * 20 + (0 if canaries else 10)
                 + (20 if scan and scan["threat"] not in ("none", "low") else 0)) if has_signal else None
    encrypted = sum(1 for r in data["repositories"] if r["encrypted"])
    return {
        "threat_score": threat,
        "kpis": [
            {"label": "Threat Score", "value": f"{threat}/100" if threat is not None else "N/D", "target": "< 25",
             "status": "N/D" if threat is None else ("OK" if threat < 25 else ("ATENÇÃO" if threat < 50 else "CRÍTICO"))},
            {"label": "Canários", "value": f"{len(canaries) - comp}/{len(canaries)} íntegros" if canaries else "Nenhum implantado", "target": "0 comprometidos",
             "status": "CRÍTICO" if comp else ("OK" if canaries else "ATENÇÃO")},
            {"label": "Incidentes Abertos", "value": str(len(open_inc)), "target": "0", "status": "CRÍTICO" if open_inc else "OK"},
            {"label": "Repositórios Criptografados", "value": f"{encrypted}/{len(data['repositories'])}", "target": "100%",
             "status": _st(_pct(encrypted, len(data["repositories"])), 100, 80)},
            {"label": "Último Scan", "value": f"{scan['threat']} ({_dt(scan['at'])})" if scan else "Nunca executado", "target": "Semanal", "status": "OK" if scan else "ATENÇÃO"},
        ],
        "delta": [_d("down" if comp or open_inc else "up", f"{comp} canário(s) comprometido(s), {len(open_inc)} incidente(s) aberto(s)."),
                  _d("neutral", f"Ferramentas de segurança detectadas: {', '.join(installed) or 'nenhuma'}.")],
        "analytical_summary": "Threat score = 30 por canário comprometido + 20 por incidente aberto + 10 sem canários + 20 se o último scan indicou ameaça.",
        "tables": [
            {"title": "Canários", "headers": ["Arquivo", "Situação", "Última Verificação"],
             "rows": [[c["path"], "CRÍTICO" if c["compromised"] else "OK", _dt(c["verified"])] for c in canaries]},
            {"title": "Incidentes (30 dias ou abertos)", "headers": ["Detectado em", "Status", "Resolvido em"],
             "rows": [[_dt(i["at"]), i["status"] or "—", _dt(i["resolved"])] for i in data["incidents"]]},
        ],
        "recommended_actions": ([{"priority": "ALTA", "description": "Tratar canários comprometidos/incidentes e validar pontos de restauração limpos.", "owner": "SOC", "deadline": "Imediato"}] if comp or open_inc else [])
                               + ([{"priority": "MÉDIA", "description": "Implantar canários do Ransomware Guardian.", "owner": "Segurança", "deadline": "7 dias"}] if not canaries else [])
                               + ([{"priority": "MÉDIA", "description": "Habilitar criptografia nos repositórios sem senha.", "owner": "Segurança", "deadline": "14 dias"}] if encrypted < len(data["repositories"]) else []),
    }


# ──────────────────────────────────────────────────────────────────────────────
# F5 — Compliance & Governance
# ──────────────────────────────────────────────────────────────────────────────

def compliance(data: dict) -> dict:
    if (u := _unavailable(data, "compliance_score")):
        return u
    now = data["now"]
    tasks = _per_task(data)
    evaluated = [t for t in tasks if t["class"] in ("CONFORME", "EM RISCO", "NÃO CONFORME")]
    conf = [t for t in evaluated if t["class"] == "CONFORME"]
    pct = _pct(len(conf), len(evaluated))
    no_ret = [t for t in tasks if not t["retention_days"]]
    failed_actions = sum(n for _, res, n in data["audit"] if res not in ("success", "ok"))
    return {
        "compliance_score": round(pct) if pct is not None else None,
        "kpis": [
            {"label": "Conformidade RPO", "value": _fp(pct), "target": "≥ 95%", "status": _st(pct, 95, 85)},
            {"label": "Tarefas em Risco", "value": str(len(evaluated) - len(conf)), "target": "0", "status": "OK" if len(conf) == len(evaluated) else "ATENÇÃO"},
            {"label": "Tarefas sem Retenção", "value": str(len(no_ret)), "target": "0", "status": "OK" if not no_ret else "ATENÇÃO"},
            {"label": "Eventos de Auditoria (30d)", "value": str(sum(n for *_, n in data["audit"])), "target": f"{failed_actions} com falha", "status": "OK" if data["audit"] else "N/D"},
        ],
        "delta": [_d("neutral", "RPO inferido pelo intervalo mediano entre backups bem-sucedidos (não há RPO contratual cadastrado).")],
        "analytical_summary": "CONFORME: idade do último backup ≤ 2× o intervalo habitual; EM RISCO: ≤ 4×; NÃO CONFORME: acima disso ou sem sucesso no período.",
        "tables": [
            {"title": "Auditoria de RPO por Tarefa",
             "headers": ["Tarefa", "Agendamento", "Retenção (dias)", "Intervalo Mediano", "Último Sucesso", "Idade", "Classificação"],
             "rows": [[t["name"], t["cron"] or ("Manual" if not t["scheduled"] else "—"), t["retention_days"] or "—",
                       f"{t['median_min']:.0f} min" if t["median_min"] else "—", _dt(t["last_ok"]), _age(t["last_ok"], now), t["class"]] for t in tasks]},
            {"title": "Trilha de Auditoria", "headers": ["Ação", "Resultado", "Ocorrências"],
             "rows": [[a, r, n] for a, r, n in data["audit"]]},
        ],
        "recommended_actions": [{"priority": "ALTA" if t["class"] == "NÃO CONFORME" else "MÉDIA",
                                 "description": f"Regularizar '{t['name']}' (último sucesso: {_dt(t['last_ok'])}).",
                                 "owner": "Administrador de Backup", "deadline": "24 horas" if t["class"] == "NÃO CONFORME" else "3 dias"}
                                for t in evaluated if t["class"] != "CONFORME"][:5],
    }


# ──────────────────────────────────────────────────────────────────────────────
# F7 — FinOps
# ──────────────────────────────────────────────────────────────────────────────

def finops(data: dict, cost_usd_per_tb: float | None, usd_rate: float, usd_live: bool) -> dict:
    if (u := _unavailable(data, "finops_score")):
        return u
    stored = sum(s["size"] for s in data["storage"]) if data["storage"] else None
    usd = stored / 1024 ** 4 * cost_usd_per_tb if stored is not None and cost_usd_per_tb else None
    src = "cotação ao vivo" if usd_live else "cotação de referência (consulta ao vivo indisponível)"
    return {
        "finops_score": None,
        "kpis": [
            {"label": "Volume Armazenado", "value": _gb(stored), "target": "Monitor de Storage", "status": "OK" if stored is not None else "N/D"},
            {"label": "Custo Mensal (USD)", "value": f"US$ {usd:,.2f}" if usd is not None else "N/D", "target": f"US$ {cost_usd_per_tb}/TB (config.)", "status": "OK" if usd is not None else "N/D"},
            {"label": "Custo Mensal (BRL)", "value": f"R$ {usd * usd_rate:,.2f}" if usd is not None else "N/D", "target": f"USD/BRL {usd_rate:.2f} ({src})", "status": "OK" if usd is not None else "N/D"},
        ],
        "delta": [_d("neutral", "Economia/ROI não calculados: exigem custos de referência que não estão cadastrados.")],
        "analytical_summary": "Estimativa = volume medido × preço por TB configurado × cotação USD/BRL.",
        "tables": [{"title": "Custo por Repositório", "headers": ["Repositório", "Tamanho", "US$/mês", "R$/mês"],
                    "rows": [[s["name"], _gb(s["size"]),
                              f"{s['size'] / 1024 ** 4 * cost_usd_per_tb:,.2f}" if cost_usd_per_tb else "N/D",
                              f"{s['size'] / 1024 ** 4 * cost_usd_per_tb * usd_rate:,.2f}" if cost_usd_per_tb else "N/D"] for s in data["storage"]]}],
        "recommended_actions": [] if data["storage"] else [{"priority": "MÉDIA", "description": "Habilitar o Monitor de Storage para medir o volume armazenado.", "owner": "FinOps", "deadline": "7 dias"}],
    }


# ──────────────────────────────────────────────────────────────────────────────
# F8 — Disaster Recovery Readiness
# ──────────────────────────────────────────────────────────────────────────────

def dr_readiness(data: dict) -> dict:
    if (u := _unavailable(data, "dr_readiness_score")):
        return u
    now = data["now"]
    tasks = [t for t in _per_task(data) if t["enabled"]]
    restores_ok = [r for r in data["restores"] if r["status"] in SUCCESS and r["duration"] > 0]
    rto = statistics.median(r["duration"] for r in restores_ok) if restores_ok else None
    sb_ok = [s for s in data["surebackup"] if s["boot"]]
    integ_ok = [i for i in data["integrity"] if i["status"] in ("completed", "success", "ok", "passed") and i["errors"] == 0]
    criteria = {
        "Backup ≤ 24h em todas as tarefas": bool(tasks) and all(t["last_ok"] and now - t["last_ok"] <= timedelta(hours=24) for t in tasks),
        "Restore testado (30d)": bool(restores_ok),
        "Boot verificado (SureBackup)": bool(sb_ok),
        "Integridade de repositório sem erros": bool(integ_ok) and len(integ_ok) == len(data["integrity"]),
    }
    score = round(sum(criteria.values()) * 100 / len(criteria))
    return {
        "dr_readiness_score": score,
        "kpis": [
            {"label": "DR Readiness Score", "value": f"{score} / 100", "target": "≥ 80", "status": _st(score, 80, 50)},
            {"label": "RTO Real (mediana)", "value": f"{rto / 60:.1f} min" if rto else "Não medido", "target": "restore_history", "status": "OK" if rto else "N/D"},
            {"label": "Restores OK (30d)", "value": f"{len(restores_ok)} de {len(data['restores'])}", "target": "≥ 1", "status": "OK" if restores_ok else "ATENÇÃO"},
            {"label": "Boot Verificado", "value": f"{len(sb_ok)} de {len(data['surebackup'])}" if data["surebackup"] else "Nunca executado", "target": "≥ 1", "status": "OK" if sb_ok else "ATENÇÃO"},
        ],
        "delta": [_d("up" if ok else "down", f"{name}: {'atendido' if ok else 'pendente'}.") for name, ok in criteria.items()],
        "analytical_summary": "Score = 25 pontos por critério atendido. RTO = mediana da duração das restaurações bem-sucedidas registradas.",
        "tables": [
            {"title": "RPO Real por Tarefa", "headers": ["Tarefa", "Último Backup OK", "RPO Real", "Status"],
             "rows": [[t["name"], _dt(t["last_ok"]), _age(t["last_ok"], now),
                       "CONFORME" if t["last_ok"] and now - t["last_ok"] <= timedelta(hours=24) else "ATENÇÃO"] for t in tasks]},
            {"title": "Restaurações (30 dias)", "headers": ["Data", "Snapshot", "Status", "Duração", "Volume", "Erro"],
             "rows": [[_dt(r["at"]), r["snapshot"] or "—", r["status"], f"{r['duration']} s", _gb(r["bytes"]), (r["error"] or "—")[:120]] for r in data["restores"]]},
        ],
        "recommended_actions": [{"priority": "ALTA" if "Backup" in n else "MÉDIA", "description": f"Atender o critério de DR: {n}.",
                                 "owner": "Arquiteto de DR", "deadline": "7 dias"} for n, ok in criteria.items() if not ok],
    }
