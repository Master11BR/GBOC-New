# ==============================================================================
# GBOC System v14.8.1 Enterprise Edition
# Module: Flagship Reports — coleta de dados reais e construtores (Server)
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================
"""
Construtores dos 8 relatórios Flagship do GBOC Server.

Regras (AI_RULES.md §11 / ARCHITECTURE_POLICIES.md §6):
  * Fonte exclusiva: PostgreSQL do Servidor Central (dados sincronizados pelos agentes).
    O Servidor pode estar em outra máquina — nenhuma métrica do host do servidor é
    apresentada como se fosse do agente.
  * Nenhum valor presumido: sem amostra, o indicador é "N/D"/"SEM DADOS" e o motivo é exibido.
  * Todo texto vindo do banco é escapado antes de entrar em trechos HTML (narrativas).
"""

from __future__ import annotations

import html
import logging
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger(__name__)

PERIOD_DAYS = 30
RECENT_BACKUP_HOURS = 48
SUCCESS = ("completed", "success", "ok")
FAILED = ("failed", "error")


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _pct(part: float, total: float) -> float | None:
    return round(part * 100.0 / total, 1) if total else None


def _fmt_pct(value: float | None) -> str:
    return f"{value}%" if value is not None else "N/D"


def _fmt_dt(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    return str(value) if value else "—"


def _fmt_age(value: datetime | None, now: datetime) -> str:
    if not isinstance(value, datetime):
        return "nunca"
    hours = (now - value).total_seconds() / 3600
    return f"{hours:.1f} h" if hours < 48 else f"{hours / 24:.1f} dias"


def _fmt_gb(num_bytes: float | None) -> str:
    if num_bytes is None:
        return "N/D"
    return f"{num_bytes / 1024 ** 3:,.2f} GB"


def _status(value: float | None, ok: float, warn: float, higher_is_better: bool = True) -> str:
    if value is None:
        return "SEM DADOS"
    if not higher_is_better:
        value, ok, warn = -value, -ok, -warn
    return "CONFORME" if value >= ok else ("ATENÇÃO" if value >= warn else "CRÍTICO")


def _score_status(score: float | None) -> str:
    if score is None:
        return "N/D"
    return "OK" if score >= 85 else ("ATENÇÃO" if score >= 70 else "CRÍTICO")


def _delta(kind: str, text: str) -> dict[str, str]:
    icon, cls = {"up": ("↑", "delta-up"), "down": ("↓", "delta-down")}.get(kind, ("→", "delta-neutral"))
    return {"type": {"up": "improvement", "down": "deterioration"}.get(kind, "neutral"),
            "icon": icon, "class": cls, "text": text}


# ──────────────────────────────────────────────────────────────────────────────
# Coleta
# ──────────────────────────────────────────────────────────────────────────────

def _safe_query(cur, conn, sql: str, params: tuple = ()) -> list[tuple]:
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception as err:
        logger.warning(f"[Flagship] consulta ignorada ({err.__class__.__name__}): {str(err)[:160]}")
        try:
            conn.rollback()
        except Exception:
            pass
        return []


def collect_server_report_data(db_getter: Callable[[], tuple[Any, Any]], days: int = PERIOD_DAYS) -> dict[str, Any]:
    data: dict[str, Any] = {
        "available": False, "error": "", "now": datetime.now(), "days": days,
        "agents": [], "executions": [], "tasks": [], "repositories": [], "storage_latest": [],
        "storage_series": [], "canaries": {}, "guardian": {}, "shield": {}, "local_protection": {},
        "incidents": [], "rw_events": [], "integrity": {}, "audit": [], "offline_minutes": 10,
    }
    conn, mgr = None, None
    try:
        conn, mgr = db_getter()
    except Exception as err:
        data["error"] = f"Banco indisponível: {err.__class__.__name__}"
        return data
    if not conn:
        data["error"] = "Conexão com o PostgreSQL indisponível."
        return data

    try:
        cur = conn.cursor()
        rows = _safe_query(cur, conn, "SELECT value FROM server_settings WHERE category='sync' AND key='agent_offline_threshold_minutes'")
        if rows and str(rows[0][0]).isdigit():
            data["offline_minutes"] = int(rows[0][0])

        for r in _safe_query(cur, conn, """
                SELECT agent_id, COALESCE(hostname, agent_id), ip_address, os_info, agent_version,
                       registered_at, last_heartbeat
                FROM agents ORDER BY hostname"""):
            data["agents"].append({"agent_id": r[0], "hostname": r[1], "ip": r[2], "os": r[3], "version": r[4],
                                   "registered_at": r[5], "last_heartbeat": r[6]})

        for r in _safe_query(cur, conn, """
                SELECT e.agent_id, COALESCE(a.hostname, e.agent_id), e.task_id,
                       COALESCE(NULLIF(t.name, ''), 'Task #' || e.task_id::text),
                       LOWER(COALESCE(e.status, '')), e.started_at, e.completed_at,
                       COALESCE(e.duration_seconds, 0), COALESCE(e.bytes_processed, 0),
                       COALESCE(e.files_processed, 0), e.error_message
                FROM agent_task_executions e
                LEFT JOIN agents a ON a.agent_id = e.agent_id
                LEFT JOIN agent_tasks t ON t.agent_id = e.agent_id AND t.task_id = e.task_id
                WHERE e.started_at >= LOCALTIMESTAMP - make_interval(days => %s)
                ORDER BY e.started_at""", (days,)):
            data["executions"].append({"agent_id": r[0], "hostname": r[1], "task_id": r[2], "task": r[3], "status": r[4],
                                       "start": r[5], "end": r[6], "duration": float(r[7] or 0),
                                       "bytes": int(r[8] or 0), "files": int(r[9] or 0), "error": r[10]})

        for r in _safe_query(cur, conn, """
                SELECT t.agent_id, COALESCE(a.hostname, t.agent_id), t.task_id, t.name, t.status, t.updated_at
                FROM agent_tasks t LEFT JOIN agents a ON a.agent_id = t.agent_id"""):
            data["tasks"].append({"agent_id": r[0], "hostname": r[1], "task_id": r[2], "name": r[3] or f"Task #{r[2]}",
                                  "status": r[4], "updated_at": r[5]})

        for r in _safe_query(cur, conn, """
                SELECT r.agent_id, COALESCE(a.hostname, r.agent_id), r.name, r.engine, r.type, r.status,
                       r.last_backup, COALESCE(r.total_backups, 0)
                FROM agent_repositories r LEFT JOIN agents a ON a.agent_id = r.agent_id ORDER BY r.name"""):
            data["repositories"].append({"agent_id": r[0], "hostname": r[1], "name": r[2], "engine": r[3], "type": r[4],
                                         "status": r[5], "last_backup": r[6], "total_backups": int(r[7] or 0)})

        for r in _safe_query(cur, conn, """
                SELECT DISTINCT ON (repository_id) repository_id, repository_name, engine, path,
                       size_bytes, snapshot_count, recorded_at
                FROM storage_usage_history ORDER BY repository_id, recorded_at DESC"""):
            data["storage_latest"].append({"repository_id": r[0], "name": r[1], "engine": r[2], "path": r[3],
                                           "size_bytes": int(r[4] or 0), "snapshots": int(r[5] or 0), "recorded_at": r[6]})

        for r in _safe_query(cur, conn, """
                SELECT d, SUM(sz) FROM (
                    SELECT DISTINCT ON (repository_id, recorded_at::date) recorded_at::date AS d, size_bytes AS sz
                    FROM storage_usage_history
                    WHERE recorded_at >= NOW() - make_interval(days => %s)
                    ORDER BY repository_id, recorded_at::date, recorded_at DESC
                ) t GROUP BY d ORDER BY d""", (days,)):
            data["storage_series"].append((r[0], int(r[1] or 0)))

        import json as _json
        for r in _safe_query(cur, conn, """
                SELECT DISTINCT ON (agent_id, snapshot_type) agent_id, snapshot_type, payload_json, created_at
                FROM ransomware_agent_snapshots
                WHERE snapshot_type IN ('canaries', 'guardian', 'shield', 'local_protection')
                ORDER BY agent_id, snapshot_type, id DESC"""):
            try:
                payload = _json.loads(r[2]) if r[2] else {}
            except ValueError:
                payload = {}
            data[r[1]][r[0]] = {"payload": payload if isinstance(payload, dict) else {}, "at": r[3]}

        for r in _safe_query(cur, conn, """
                SELECT i.agent_id, COALESCE(a.hostname, i.agent_id), i.status, COALESCE(i.detected_at, i.created_at), i.resolved_at
                FROM ransomware_central_incidents i LEFT JOIN agents a ON a.agent_id = i.agent_id
                WHERE COALESCE(i.detected_at, i.created_at) >= LOCALTIMESTAMP - make_interval(days => %s)
                   OR LOWER(COALESCE(i.status, '')) <> 'resolved'""", (days,)):
            data["incidents"].append({"agent_id": r[0], "hostname": r[1], "status": (r[2] or "").lower(),
                                      "detected_at": r[3], "resolved_at": r[4]})

        for r in _safe_query(cur, conn, """
                SELECT COALESCE(agent_hostname, agent_id), event_type, message, COALESCE(event_time, created_at)
                FROM ransomware_central_events
                WHERE COALESCE(event_time, created_at) >= LOCALTIMESTAMP - make_interval(days => %s)
                ORDER BY COALESCE(event_time, created_at) DESC LIMIT 20""", (days,)):
            data["rw_events"].append({"hostname": r[0], "type": r[1], "message": r[2], "at": r[3]})

        for r in _safe_query(cur, conn, """
                SELECT p.agent_id, COALESCE(a.hostname, p.agent_id), p.last_scrub_at, p.integrity_health_pct,
                       p.corrupted_blocks, p.repaired_blocks
                FROM power_tools_agent_stats p LEFT JOIN agents a ON a.agent_id = p.agent_id"""):
            data["integrity"][r[0]] = {"hostname": r[1], "last_scrub": r[2],
                                       "health": float(r[3]) if r[3] is not None and r[2] else None,
                                       "corrupted": int(r[4] or 0), "repaired": int(r[5] or 0)}

        for r in _safe_query(cur, conn, """
                SELECT action, COUNT(*) FROM server_auth_audit
                WHERE timestamp >= LOCALTIMESTAMP - make_interval(days => %s) GROUP BY action ORDER BY 2 DESC""", (days,)):
            data["audit"].append((r[0], int(r[1])))

        cur.close()
        data["available"] = True
    except Exception as err:
        logger.error(f"[Flagship] falha na coleta: {err}")
        data["error"] = f"Falha na consulta ao banco: {err.__class__.__name__}"
    finally:
        try:
            if mgr and conn:
                mgr.release_connection(conn)
        except Exception:
            pass

    now = data["now"]
    for a in data["agents"]:
        hb = a.get("last_heartbeat")
        a["online"] = isinstance(hb, datetime) and (now - hb) <= timedelta(minutes=data["offline_minutes"])
    return data


# ──────────────────────────────────────────────────────────────────────────────
# Agregações
# ──────────────────────────────────────────────────────────────────────────────

def _finished(execs: list[dict]) -> list[dict]:
    return [e for e in execs if e["status"] in SUCCESS + FAILED]


def _per_agent(data: dict) -> list[dict]:
    now = data["now"]
    by_agent: dict[str, list[dict]] = defaultdict(list)
    for e in data["executions"]:
        by_agent[e["agent_id"]].append(e)
    rows = []
    for a in data["agents"]:
        ex = by_agent.get(a["agent_id"], [])
        fin = _finished(ex)
        ok = [e for e in fin if e["status"] in SUCCESS]
        last_ok = max((e["end"] or e["start"] for e in ok if (e["end"] or e["start"])), default=None)
        recent = isinstance(last_ok, datetime) and (now - last_ok) <= timedelta(hours=RECENT_BACKUP_HOURS)
        rows.append({**a, "executions": len(ex), "finished": len(fin), "success": len(ok),
                     "failed": len(fin) - len(ok), "success_rate": _pct(len(ok), len(fin)),
                     "last_success": last_ok, "recent_backup": recent})
    return rows


def _per_task(data: dict) -> list[dict]:
    now = data["now"]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for e in data["executions"]:
        groups[(e["agent_id"], e["task_id"])].append(e)
    known = {(t["agent_id"], t["task_id"]): t for t in data["tasks"]}
    keys = set(groups) | set(known)
    out = []
    for key in keys:
        ex = sorted(groups.get(key, []), key=lambda e: e["start"] or now)
        ok_times = [e["end"] or e["start"] for e in ex if e["status"] in SUCCESS and (e["end"] or e["start"])]
        intervals = [(b - a).total_seconds() / 60 for a, b in zip(ok_times, ok_times[1:]) if b > a]
        median_min = statistics.median(intervals) if intervals else None
        last_ok = ok_times[-1] if ok_times else None
        age_min = (now - last_ok).total_seconds() / 60 if last_ok else None
        fin = _finished(ex)
        failed = [e for e in fin if e["status"] in FAILED]
        meta = known.get(key, {})
        name = (ex[-1]["task"] if ex else None) or meta.get("name") or f"Task #{key[1]}"
        host = (ex[-1]["hostname"] if ex else None) or meta.get("hostname") or key[0]
        if last_ok is None:
            cls = "NÃO CONFORME" if fin else "SEM DADOS"
        elif median_min is None:
            cls = "SEM DADOS"
        elif age_min <= 2 * median_min:
            cls = "CONFORME"
        elif age_min <= 4 * median_min:
            cls = "EM RISCO"
        else:
            cls = "NÃO CONFORME"
        durations = [e["duration"] for e in fin if e["duration"] > 0]
        out.append({"agent_id": key[0], "hostname": host, "task_id": key[1], "name": name,
                    "executions": len(ex), "failed": len(failed), "success_rate": _pct(len(fin) - len(failed), len(fin)),
                    "median_interval_min": median_min, "max_interval_min": max(intervals) if intervals else None,
                    "last_success": last_ok, "age_min": age_min, "classification": cls,
                    "last_error": next((e["error"] for e in reversed(ex) if e["status"] in FAILED and e["error"]), None),
                    "avg_duration": statistics.mean(durations) if durations else None})
    return sorted(out, key=lambda t: (t["hostname"] or "", t["name"] or ""))


def _base_unavailable(report: dict, data: dict) -> bool:
    if data["available"]:
        return False
    report.update({"score_value": "N/D", "score_status": "N/D", "score_delta": "Dados indisponíveis"})
    report["delta"] = [_delta("down", f"Não foi possível ler o banco do Servidor Central: {data['error']}")]
    report["kpi_cards"] = [{"label": "Fonte de dados", "value": "Indisponível", "target": "PostgreSQL", "status": "CRÍTICO"}]
    report["recommended_actions"] = [{"priority": "ALTA", "action": "Verificar o serviço PostgreSQL do Servidor Central.",
                                      "owner": "Administrador", "deadline": "Imediato"}]
    return True


def _no_agents(report: dict, data: dict) -> bool:
    if data["agents"]:
        return False
    report.update({"score_value": "N/D", "score_status": "N/D", "score_delta": "Nenhum agente registrado"})
    report["delta"] = [_delta("neutral", "Nenhum agente está registrado no Servidor Central — não há dados para este relatório.")]
    report["kpi_cards"] = [{"label": "Agentes registrados", "value": "0", "target": "≥ 1", "status": "SEM DADOS"}]
    report["recommended_actions"] = [{"priority": "MÉDIA", "action": "Registrar os agentes no Servidor Central (Configurações > Agentes).",
                                      "owner": "Administrador de Backup", "deadline": "—"}]
    return True


# ──────────────────────────────────────────────────────────────────────────────
# REP-F1 Protection Scorecard
# ──────────────────────────────────────────────────────────────────────────────

def build_f1(report: dict, data: dict) -> None:
    if _base_unavailable(report, data) or _no_agents(report, data):
        return
    now = data["now"]
    agents = _per_agent(data)
    fin = _finished(data["executions"])
    ok = [e for e in fin if e["status"] in SUCCESS]
    success_rate = _pct(len(ok), len(fin))
    coverage = _pct(sum(1 for a in agents if a["recent_backup"]), len(agents))
    online = _pct(sum(1 for a in agents if a["online"]), len(agents))
    parts = [(success_rate, 0.40), (coverage, 0.35), (online, 0.25)]
    known = [(v, w) for v, w in parts if v is not None]
    score = round(sum(v * w for v, w in known) / sum(w for _, w in known)) if known else None

    report.update({"score_value": score if score is not None else "N/D", "score_status": _score_status(score),
                   "score_delta": f"{len(fin)} execuções finalizadas em {data['days']} dias"})
    report["score_composition"] = [
        {"label": "Taxa de sucesso", "value": _fmt_pct(success_rate), "weight": "40%", "bar_pct": success_rate or 0},
        {"label": f"Ativos com backup ≤ {RECENT_BACKUP_HOURS}h", "value": _fmt_pct(coverage), "weight": "35%", "bar_pct": coverage or 0},
        {"label": "Agentes com heartbeat", "value": _fmt_pct(online), "weight": "25%", "bar_pct": online or 0},
    ]
    stale = [a for a in agents if not a["recent_backup"]]
    failed_total = len(fin) - len(ok)
    report["delta"] = [
        _delta("up" if not stale else "down",
               f"{len(agents) - len(stale)} de {len(agents)} agentes com backup bem-sucedido nas últimas {RECENT_BACKUP_HOURS}h."),
        _delta("down" if failed_total else "up", f"{failed_total} execução(ões) com falha no período."),
        _delta("neutral", f"Volume processado no período: {_fmt_gb(sum(e['bytes'] for e in ok))}."),
    ]
    report["kpi_cards"] = [
        {"label": "Taxa de Sucesso", "value": _fmt_pct(success_rate), "target": "Meta: ≥ 99%", "status": _status(success_rate, 99, 95)},
        {"label": "Ativos Protegidos (48h)", "value": f"{len(agents) - len(stale)} / {len(agents)}", "target": "Meta: 100%", "status": _status(coverage, 100, 80)},
        {"label": "Agentes Online", "value": f"{sum(1 for a in agents if a['online'])} / {len(agents)}", "target": f"Heartbeat ≤ {data['offline_minutes']} min", "status": _status(online, 100, 80)},
        {"label": "Falhas no Período", "value": str(failed_total), "target": "Meta: 0", "status": "CONFORME" if failed_total == 0 else "ATENÇÃO"},
    ]
    rows = [[a["hostname"], "OK" if a["online"] else "OFFLINE", _fmt_dt(a["last_success"]), _fmt_age(a["last_success"], now),
             str(a["executions"]), str(a["failed"]), _fmt_pct(a["success_rate"]),
             "CONFORME" if a["recent_backup"] else "NÃO CONFORME"] for a in agents]
    report["sections"].append({
        "title": "Proteção por Agente",
        "narrative": f"Situação real de cada um dos <strong>{len(agents)}</strong> agentes registrados, a partir das execuções sincronizadas.",
        "table_headers": ["Agente", "Heartbeat", "Último Backup OK", "Idade", "Execuções", "Falhas", "Sucesso", "Status (≤48h)"],
        "table_rows": rows,
        "ai_inline": (f"{len(stale)} agente(s) sem backup bem-sucedido nas últimas {RECENT_BACKUP_HOURS}h: "
                      + ", ".join(_e(a["hostname"]) for a in stale[:10]) + "." if stale
                      else "Todos os agentes possuem backup bem-sucedido recente."),
    })
    actions = []
    if stale:
        actions.append({"priority": "ALTA", "action": "Verificar agendamentos e falhas dos agentes sem backup recente: "
                        + ", ".join(a["hostname"] for a in stale[:10]) + ".", "owner": "Administrador de Backup", "deadline": "24 horas"})
    offline = [a["hostname"] for a in agents if not a["online"]]
    if offline:
        actions.append({"priority": "ALTA", "action": "Restabelecer a comunicação com os agentes sem heartbeat: " + ", ".join(offline[:10]) + ".",
                        "owner": "Suporte / NOC", "deadline": "24 horas"})
    if failed_total:
        actions.append({"priority": "MÉDIA", "action": "Analisar as execuções com falha (relatório REP-F2).", "owner": "Engenharia de Backup", "deadline": "3 dias"})
    report["recommended_actions"] = actions


# ──────────────────────────────────────────────────────────────────────────────
# REP-F2 Operational Performance
# ──────────────────────────────────────────────────────────────────────────────

def build_f2(report: dict, data: dict) -> None:
    if _base_unavailable(report, data) or _no_agents(report, data):
        return
    now = data["now"]
    fin = _finished(data["executions"])
    last7 = [e for e in fin if e["start"] and e["start"] >= now - timedelta(days=7)]
    ok7 = [e for e in last7 if e["status"] in SUCCESS]
    rate7 = _pct(len(ok7), len(last7))
    ok_all = [e for e in fin if e["status"] in SUCCESS and e["duration"] > 0]
    throughput = (sum(e["bytes"] for e in ok_all) / sum(e["duration"] for e in ok_all) / 1048576) if ok_all else None
    avg_dur = statistics.mean(e["duration"] for e in ok_all) if ok_all else None
    score = round(rate7) if rate7 is not None else None

    report.update({"score_value": score if score is not None else "N/D", "score_status": _score_status(score),
                   "score_delta": f"{len(last7)} execuções nos últimos 7 dias"})
    report["score_composition"] = [
        {"label": "Sucesso 7 dias", "value": _fmt_pct(rate7), "weight": "100%", "bar_pct": rate7 or 0},
    ]
    report["kpi_cards"] = [
        {"label": "Execuções (30 dias)", "value": str(len(fin)), "target": "Finalizadas", "status": "CONFORME" if fin else "SEM DADOS"},
        {"label": "Sucesso (7 dias)", "value": _fmt_pct(rate7), "target": "Meta: ≥ 99%", "status": _status(rate7, 99, 95)},
        {"label": "Throughput Médio", "value": f"{throughput:.1f} MB/s" if throughput else "N/D", "target": "Volume / duração", "status": "CONFORME" if throughput else "SEM DADOS"},
        {"label": "Duração Média", "value": f"{avg_dur / 60:.1f} min" if avg_dur else "N/D", "target": "Execuções OK", "status": "CONFORME" if avg_dur else "SEM DADOS"},
    ]
    per_day = Counter((e["start"].date() for e in fin if e["start"]))
    fails_day = Counter((e["start"].date() for e in fin if e["start"] and e["status"] in FAILED))
    report["delta"] = [
        _delta("neutral", f"Média de {len(fin) / max(1, len(per_day)):.1f} execuções/dia em {len(per_day)} dia(s) com atividade."),
        _delta("down" if fails_day else "up", f"Dias com falha: {len(fails_day)} de {len(per_day)}."),
    ]
    tasks = _per_task(data)
    report["sections"].append({
        "title": "Desempenho por Tarefa",
        "narrative": "Valores individuais calculados a partir das execuções reais sincronizadas (sem médias globais).",
        "table_headers": ["Agente", "Tarefa", "Execuções", "Falhas", "Sucesso", "Duração Média", "Última Falha"],
        "table_rows": [[t["hostname"], t["name"], str(t["executions"]), str(t["failed"]), _fmt_pct(t["success_rate"]),
                        f"{t['avg_duration'] / 60:.1f} min" if t["avg_duration"] else "—",
                        (t["last_error"] or "—")[:160]] for t in tasks if t["executions"]],
        "ai_inline": "Classificação automática a partir do histórico de execuções do período.",
    })
    reasons = Counter(((e["error"] or "sem mensagem de erro").strip().splitlines()[0][:100]) for e in fin if e["status"] in FAILED)
    report["sections"].append({
        "title": "Principais Causas de Falha",
        "narrative": "Agrupamento pela primeira linha da mensagem de erro registrada pelo agente.",
        "table_headers": ["Mensagem de erro", "Ocorrências"],
        "table_rows": [[msg, str(n)] for msg, n in reasons.most_common(10)],
        "ai_inline": (f"A causa mais frequente responde por {reasons.most_common(1)[0][1]} de {sum(reasons.values())} falhas."
                      if reasons else "Nenhuma falha registrada no período."),
    })
    worst = [t for t in tasks if t["failed"]]
    worst.sort(key=lambda t: t["failed"], reverse=True)
    report["recommended_actions"] = [
        {"priority": "ALTA", "action": f"Corrigir a tarefa '{t['name']}' em {t['hostname']} ({t['failed']} falhas).",
         "owner": "Engenharia de Backup", "deadline": "3 dias"} for t in worst[:3]
    ]


# ──────────────────────────────────────────────────────────────────────────────
# REP-F3 Storage Intelligence
# ──────────────────────────────────────────────────────────────────────────────

def build_f3(report: dict, data: dict, usd_info: dict, cost_usd_per_tb: float | None) -> None:
    if _base_unavailable(report, data) or _no_agents(report, data):
        return
    from modules.reports.ai_predictive import capacity_model
    now = data["now"]
    storage = data["storage_latest"]
    stored = sum(s["size_bytes"] for s in storage) if storage else None
    series = data["storage_series"]
    points = [{"start": datetime.combine(d, datetime.min.time()), "bytes": max(0, b - prev), "status": "completed"}
              for (d, b), (_, prev) in zip(series[1:], series[:-1])]
    cap = capacity_model(points, []) if points else None
    repos = data["repositories"]
    healthy = sum(1 for r in repos if isinstance(r["last_backup"], datetime) and now - r["last_backup"] <= timedelta(hours=RECENT_BACKUP_HOURS))
    repo_health = _pct(healthy, len(repos))
    score = round(repo_health) if repo_health is not None else None

    report.update({"score_value": score if score is not None else "N/D", "score_status": _score_status(score),
                   "score_delta": f"{len(repos)} repositório(s) sincronizado(s)"})
    report["score_composition"] = [
        {"label": f"Repositórios com backup ≤ {RECENT_BACKUP_HOURS}h", "value": _fmt_pct(repo_health), "weight": "100%", "bar_pct": repo_health or 0},
    ]
    monthly_brl = None
    if stored is not None and cost_usd_per_tb:
        monthly_brl = stored / 1024 ** 4 * cost_usd_per_tb * usd_info["rate"]
    report["kpi_cards"] = [
        {"label": "Volume Armazenado", "value": _fmt_gb(stored), "target": "Último registro por repositório", "status": "CONFORME" if stored is not None else "SEM DADOS"},
        {"label": "Crescimento", "value": f"{cap['growth_gb_day']} GB/dia" if cap and cap.get("growth_gb_day") is not None else "N/D",
         "target": "Regressão linear (30 dias)", "status": "CONFORME" if cap and cap["status"] != "UNAVAILABLE" else "SEM DADOS"},
        {"label": "Repositórios Saudáveis", "value": f"{healthy} / {len(repos)}" if repos else "N/D", "target": "Meta: 100%", "status": _status(repo_health, 100, 80)},
        {"label": "Custo Cloud Estimado", "value": f"R$ {monthly_brl:,.2f}/mês" if monthly_brl is not None else "N/D",
         "target": f"Preço configurado: US$ {cost_usd_per_tb}/TB", "status": "CONFORME" if monthly_brl is not None else "SEM DADOS"},
    ]
    report["delta"] = [_delta("neutral", cap["detail"] if cap else "Sem histórico de ocupação (storage_usage_history) para calcular crescimento.")]
    if not usd_info.get("live"):
        report["delta"].append(_delta("down", f"Cotação USD/BRL ao vivo indisponível; usado último valor conhecido ({usd_info['rate']:.2f})."))
    report["sections"].append({
        "title": "Repositórios Sincronizados pelos Agentes",
        "narrative": "Dados de <code>agent_repositories</code> enviados por cada agente.",
        "table_headers": ["Agente", "Repositório", "Motor", "Tipo", "Status", "Último Backup", "Backups", "Situação"],
        "table_rows": [[r["hostname"], r["name"] or "—", r["engine"] or "—", r["type"] or "—", r["status"] or "—",
                        _fmt_dt(r["last_backup"]), str(r["total_backups"]),
                        "CONFORME" if isinstance(r["last_backup"], datetime) and now - r["last_backup"] <= timedelta(hours=RECENT_BACKUP_HOURS) else "ATENÇÃO"]
                       for r in repos],
        "ai_inline": f"{len(repos) - healthy} repositório(s) sem backup nas últimas {RECENT_BACKUP_HOURS}h." if repos else "Nenhum repositório sincronizado.",
    })
    if storage:
        report["sections"].append({
            "title": "Ocupação por Repositório (último registro)",
            "narrative": "Tamanho e quantidade de snapshots coletados pelo monitor de storage.",
            "table_headers": ["Repositório", "Motor", "Caminho", "Tamanho", "Snapshots", "Registrado em"],
            "table_rows": [[s["name"] or s["repository_id"], s["engine"] or "—", s["path"] or "—", _fmt_gb(s["size_bytes"]),
                            str(s["snapshots"]), _fmt_dt(s["recorded_at"])] for s in storage],
            "ai_inline": "Custos exibidos são estimativas pelo preço por TB configurado em Configurações > Relatórios.",
        })
    actions = []
    if repos and healthy < len(repos):
        actions.append({"priority": "ALTA", "action": "Investigar repositórios sem backup recente.", "owner": "Administrador de Storage", "deadline": "48 horas"})
    if not storage:
        actions.append({"priority": "MÉDIA", "action": "Habilitar o Monitor de Storage para registrar a ocupação dos repositórios.", "owner": "Administrador de Backup", "deadline": "7 dias"})
    report["recommended_actions"] = actions


# ──────────────────────────────────────────────────────────────────────────────
# REP-F4 Security & Resilience
# ──────────────────────────────────────────────────────────────────────────────

def _canary_counts(payload: dict) -> tuple[int, int]:
    items = payload.get("canaries") or []
    if not isinstance(items, list):
        return 0, 0
    comp = sum(1 for c in items if isinstance(c, dict) and (c.get("is_compromised") or str(c.get("status", "")).lower() in ("compromised", "alert")))
    return len(items), comp


def build_f4(report: dict, data: dict) -> None:
    if _base_unavailable(report, data) or _no_agents(report, data):
        return
    rows, total_c, total_comp, guarded, with_snapshot = [], 0, 0, 0, 0
    open_inc = [i for i in data["incidents"] if i["status"] != "resolved"]
    for a in data["agents"]:
        aid = a["agent_id"]
        c, comp = _canary_counts(data["canaries"].get(aid, {}).get("payload", {}))
        g = data["guardian"].get(aid)
        sh = data["shield"].get(aid, {}).get("payload", {}).get("config", {}) or {}
        lp = data["local_protection"].get(aid, {}).get("payload", {})
        integ = data["integrity"].get(aid, {})
        has_any = any(aid in data[k] for k in ("canaries", "guardian", "shield", "local_protection"))
        with_snapshot += 1 if has_any else 0
        running = bool(g and g["payload"].get("running"))
        guarded += 1 if running else 0
        total_c += c
        total_comp += comp
        inc = sum(1 for i in open_inc if i["agent_id"] == aid)
        rows.append([a["hostname"],
                     "ATIVO" if running else ("INATIVO" if g else "SEM DADOS"),
                     f"{c - comp}/{c}" if c else "0",
                     "ATIVO" if sh.get("vss_guard_enabled") else ("INATIVO" if sh else "SEM DADOS"),
                     ("ATIVO" if lp.get("av_active") else "INATIVO") if lp else "SEM DADOS",
                     f"{integ['health']:.1f}%" if integ.get("health") is not None else "N/D",
                     str(inc), "CRÍTICO" if (comp or inc) else ("CONFORME" if running else "ATENÇÃO")])
    if not with_snapshot:
        score = None
    else:
        score = 100 - min(100, total_comp * 30 + len(open_inc) * 20 + (len(data["agents"]) - guarded) * 10)
    report.update({"score_value": score if score is not None else "N/D", "score_status": _score_status(score),
                   "score_delta": f"{len(open_inc)} incidente(s) em aberto"})
    report["score_composition"] = [
        {"label": "Guardian ativo", "value": f"{guarded}/{len(data['agents'])}", "weight": "10 pts/agente", "bar_pct": _pct(guarded, len(data["agents"])) or 0},
        {"label": "Canários íntegros", "value": f"{total_c - total_comp}/{total_c}" if total_c else "0 implantados", "weight": "30 pts/comprometido", "bar_pct": _pct(total_c - total_comp, total_c) or 0},
        {"label": "Incidentes abertos", "value": str(len(open_inc)), "weight": "20 pts/incidente", "bar_pct": 0 if open_inc else 100},
    ]
    report["kpi_cards"] = [
        {"label": "Resilience Score", "value": f"{score} / 100" if score is not None else "N/D", "target": "Meta: ≥ 85", "status": _status(score, 85, 70)},
        {"label": "Canários Comprometidos", "value": str(total_comp), "target": "Meta: 0", "status": "CRÍTICO" if total_comp else ("CONFORME" if total_c else "SEM DADOS")},
        {"label": "Incidentes Abertos", "value": str(len(open_inc)), "target": "Meta: 0", "status": "CRÍTICO" if open_inc else "CONFORME"},
        {"label": "Agentes com Guardian", "value": f"{guarded} / {len(data['agents'])}", "target": "Meta: 100%", "status": _status(_pct(guarded, len(data["agents"])), 100, 80)},
    ]
    report["delta"] = [
        _delta("neutral" if with_snapshot else "down", f"{with_snapshot} de {len(data['agents'])} agentes enviaram status do Ransomware Guardian ao servidor."),
        _delta("down" if total_comp or open_inc else "up", f"{total_comp} canário(s) comprometido(s) e {len(open_inc)} incidente(s) aberto(s)."),
    ]
    report["sections"].append({
        "title": "Defesas por Agente (último status sincronizado)",
        "narrative": "Status enviado por cada agente ao Ransomware Guardian central. 'SEM DADOS' indica que o agente ainda não reportou.",
        "table_headers": ["Agente", "Guardian", "Canários íntegros", "VSS Guard", "Antivírus", "Integridade (scrub)", "Incidentes abertos", "Situação"],
        "table_rows": rows,
        "ai_inline": "Score: 100 − 30 por canário comprometido − 20 por incidente aberto − 10 por agente sem Guardian ativo.",
    })
    if data["rw_events"]:
        report["sections"].append({
            "title": "Eventos de Segurança Recentes",
            "narrative": "Últimos eventos registrados em <code>ransomware_central_events</code>.",
            "table_headers": ["Data/Hora", "Agente", "Tipo", "Mensagem"],
            "table_rows": [[_fmt_dt(ev["at"]), ev["hostname"], ev["type"] or "—", (ev["message"] or "")[:160]] for ev in data["rw_events"]],
            "ai_inline": f"{len(data['rw_events'])} evento(s) no período.",
        })
    actions = []
    if total_comp or open_inc:
        actions.append({"priority": "ALTA", "action": "Tratar os canários comprometidos/incidentes abertos e validar pontos de restauração limpos.", "owner": "SOC", "deadline": "Imediato"})
    no_guard = [a["hostname"] for a, r in zip(data["agents"], rows) if r[1] != "ATIVO"]
    if no_guard:
        actions.append({"priority": "MÉDIA", "action": "Ativar o Ransomware Guardian em: " + ", ".join(no_guard[:10]) + ".", "owner": "Segurança", "deadline": "7 dias"})
    report["recommended_actions"] = actions


# ──────────────────────────────────────────────────────────────────────────────
# REP-F5 Compliance & Governance
# ──────────────────────────────────────────────────────────────────────────────

def build_f5(report: dict, data: dict) -> None:
    if _base_unavailable(report, data) or _no_agents(report, data):
        return
    now = data["now"]
    tasks = _per_task(data)
    evaluated = [t for t in tasks if t["classification"] != "SEM DADOS"]
    conform = [t for t in evaluated if t["classification"] == "CONFORME"]
    pct = _pct(len(conform), len(evaluated))
    score = round(pct) if pct is not None else None
    risky = [t for t in evaluated if t["classification"] != "CONFORME"]
    report.update({"score_value": score if score is not None else "N/D", "score_status": _score_status(score),
                   "score_delta": f"{len(evaluated)} de {len(tasks)} tarefas com histórico suficiente"})
    report["score_composition"] = [
        {"label": "Tarefas dentro do RPO observado", "value": _fmt_pct(pct), "weight": "100%", "bar_pct": pct or 0},
    ]
    audit = dict(data["audit"])
    failed_logins = sum(n for act, n in data["audit"] if "fail" in (act or "").lower() or "falha" in (act or "").lower())
    report["kpi_cards"] = [
        {"label": "Conformidade RPO", "value": _fmt_pct(pct), "target": "Meta: ≥ 95%", "status": _status(pct, 95, 85)},
        {"label": "Tarefas em Risco", "value": str(len(risky)), "target": "Meta: 0", "status": "CONFORME" if not risky else "ATENÇÃO"},
        {"label": "Eventos de Auditoria", "value": str(sum(audit.values())), "target": f"Últimos {data['days']} dias", "status": "CONFORME" if audit else "SEM DADOS"},
        {"label": "Falhas de Login", "value": str(failed_logins), "target": "Monitorar", "status": "CONFORME" if failed_logins == 0 else "ATENÇÃO"},
    ]
    report["delta"] = [
        _delta("neutral", "RPO de cada tarefa inferido pelo intervalo mediano entre backups bem-sucedidos (não há RPO contratual cadastrado)."),
        _delta("down" if risky else "up", f"{len(risky)} tarefa(s) com o último backup acima de 2× o intervalo habitual."),
    ]

    def _m(v):
        return f"{v:.0f} min" if v is not None else "—"

    report["sections"].append({
        "title": "Auditoria de RPO por Tarefa",
        "narrative": "Classificação: CONFORME (idade ≤ 2× intervalo mediano), EM RISCO (≤ 4×), NÃO CONFORME (> 4× ou sem sucesso no período).",
        "table_headers": ["Agente", "Tarefa", "Intervalo Mediano", "Maior Intervalo", "Último Sucesso", "Idade", "Classificação"],
        "table_rows": [[t["hostname"], t["name"], _m(t["median_interval_min"]), _m(t["max_interval_min"]),
                        _fmt_dt(t["last_success"]), _fmt_age(t["last_success"], now), t["classification"]] for t in tasks],
        "ai_inline": (f"{len(risky)} tarefa(s) fora do padrão: " + ", ".join(_e(t["name"]) for t in risky[:8]) + ".") if risky else "Todas as tarefas avaliadas estão dentro do intervalo habitual.",
    })
    if data["audit"]:
        report["sections"].append({
            "title": "Trilha de Auditoria do Servidor",
            "narrative": "Ações registradas em <code>server_auth_audit</code> no período.",
            "table_headers": ["Ação", "Ocorrências"],
            "table_rows": [[act or "—", str(n)] for act, n in data["audit"]],
            "ai_inline": f"{failed_logins} tentativa(s) de login malsucedida(s) no período.",
        })
    report["recommended_actions"] = [
        {"priority": "ALTA" if t["classification"] == "NÃO CONFORME" else "MÉDIA",
         "action": f"Regularizar '{t['name']}' em {t['hostname']} (último sucesso: {_fmt_dt(t['last_success'])}).",
         "owner": "Administrador de Backup", "deadline": "24 horas" if t["classification"] == "NÃO CONFORME" else "3 dias"}
        for t in risky[:5]
    ]


# ──────────────────────────────────────────────────────────────────────────────
# REP-F7 FinOps & TCO
# ──────────────────────────────────────────────────────────────────────────────

def build_f7(report: dict, data: dict, usd_info: dict, cost_usd_per_tb: float | None) -> None:
    if _base_unavailable(report, data) or _no_agents(report, data):
        return
    storage = data["storage_latest"]
    stored = sum(s["size_bytes"] for s in storage) if storage else None
    rate = usd_info["rate"]
    price_ok = bool(cost_usd_per_tb)
    monthly_usd = stored / 1024 ** 4 * cost_usd_per_tb if stored is not None and price_ok else None
    report.update({"score_value": "N/D", "score_status": "N/D",
                   "score_delta": f"Custo mensal estimado: R$ {monthly_usd * rate:,.2f}" if monthly_usd is not None else "Sem volume registrado"})
    report["kpi_cards"] = [
        {"label": "Volume Armazenado", "value": _fmt_gb(stored), "target": "storage_usage_history", "status": "CONFORME" if stored is not None else "SEM DADOS"},
        {"label": "Preço por TB (config.)", "value": f"US$ {cost_usd_per_tb:.2f}" if price_ok else "N/D", "target": "Configurações > Relatórios", "status": "CONFORME" if price_ok else "SEM DADOS"},
        {"label": "Custo Mensal (USD)", "value": f"US$ {monthly_usd:,.2f}" if monthly_usd is not None else "N/D", "target": "Volume × preço", "status": "CONFORME" if monthly_usd is not None else "SEM DADOS"},
        {"label": "Custo Mensal (BRL)", "value": f"R$ {monthly_usd * rate:,.2f}" if monthly_usd is not None else "N/D", "target": f"USD/BRL {rate:.2f} ({usd_info['source']})", "status": "CONFORME" if monthly_usd is not None else "SEM DADOS"},
    ]
    report["delta"] = [
        _delta("neutral", f"Cotação: 1 USD = R$ {rate:.2f} — fonte: {usd_info['source']}" + ("" if usd_info.get("live") else " (último valor conhecido; consulta ao vivo indisponível)") + "."),
        _delta("neutral", "Economia/ROI frente a outras soluções não é calculado: exige custos de referência que não estão cadastrados."),
    ]
    if storage and price_ok:
        report["sections"].append({
            "title": "Custo Estimado por Repositório",
            "narrative": "Estimativa = tamanho atual × preço por TB configurado × cotação.",
            "table_headers": ["Repositório", "Motor", "Tamanho", "US$/mês", "R$/mês"],
            "table_rows": [[s["name"] or s["repository_id"], s["engine"] or "—", _fmt_gb(s["size_bytes"]),
                            f"{s['size_bytes'] / 1024 ** 4 * cost_usd_per_tb:,.2f}",
                            f"{s['size_bytes'] / 1024 ** 4 * cost_usd_per_tb * rate:,.2f}"] for s in storage],
            "ai_inline": "Para custos por tenant/agente, associe os repositórios aos agentes no Monitor de Storage.",
        })
    actions = []
    if not storage:
        actions.append({"priority": "MÉDIA", "action": "Habilitar o Monitor de Storage para registrar o volume armazenado.", "owner": "FinOps / Backup", "deadline": "7 dias"})
    if not price_ok:
        actions.append({"priority": "MÉDIA", "action": "Configurar o preço por TB em Configurações > Relatórios.", "owner": "FinOps", "deadline": "7 dias"})
    report["recommended_actions"] = actions


# ──────────────────────────────────────────────────────────────────────────────
# REP-F8 Disaster Recovery Readiness
# ──────────────────────────────────────────────────────────────────────────────

def build_f8(report: dict, data: dict) -> None:
    if _base_unavailable(report, data) or _no_agents(report, data):
        return
    now = data["now"]
    agents = _per_agent(data)
    repos_by_agent = Counter(r["agent_id"] for r in data["repositories"])
    rows, scores = [], []
    for a in agents:
        checks = {
            "backup_24h": isinstance(a["last_success"], datetime) and now - a["last_success"] <= timedelta(hours=24),
            "repositorio": repos_by_agent.get(a["agent_id"], 0) > 0,
            "online": a["online"],
            "integridade": (data["integrity"].get(a["agent_id"], {}).get("health") or 0) >= 99,
        }
        s = round(sum(checks.values()) * 100 / len(checks))
        scores.append(s)
        rows.append([a["hostname"], _fmt_age(a["last_success"], now), "OK" if checks["backup_24h"] else "ATENÇÃO",
                     str(repos_by_agent.get(a["agent_id"], 0)), "OK" if checks["online"] else "OFFLINE",
                     "OK" if checks["integridade"] else ("N/D" if a["agent_id"] not in data["integrity"] else "ATENÇÃO"),
                     f"{s}%", "CONFORME" if s == 100 else ("EM RISCO" if s >= 50 else "CRÍTICO")])
    score = round(statistics.mean(scores)) if scores else None
    ready = sum(1 for s in scores if s == 100)
    report.update({"score_value": score if score is not None else "N/D", "score_status": _score_status(score),
                   "score_delta": f"{ready} de {len(agents)} agentes prontos"})
    report["score_composition"] = [
        {"label": "Backup OK ≤ 24h (RPO real)", "value": f"{sum(1 for r in rows if r[2] == 'OK')}/{len(rows)}", "weight": "25%", "bar_pct": _pct(sum(1 for r in rows if r[2] == 'OK'), len(rows)) or 0},
        {"label": "Repositório configurado", "value": f"{sum(1 for a in agents if repos_by_agent.get(a['agent_id']))}/{len(rows)}", "weight": "25%", "bar_pct": _pct(sum(1 for a in agents if repos_by_agent.get(a['agent_id'])), len(rows)) or 0},
        {"label": "Agente com heartbeat", "value": f"{sum(1 for a in agents if a['online'])}/{len(rows)}", "weight": "25%", "bar_pct": _pct(sum(1 for a in agents if a['online']), len(rows)) or 0},
        {"label": "Integridade verificada ≥ 99%", "value": f"{sum(1 for r in rows if r[5] == 'OK')}/{len(rows)}", "weight": "25%", "bar_pct": _pct(sum(1 for r in rows if r[5] == 'OK'), len(rows)) or 0},
    ]
    report["kpi_cards"] = [
        {"label": "DR Readiness Score", "value": f"{score} / 100" if score is not None else "N/D", "target": "Meta: ≥ 80", "status": _status(score, 80, 60)},
        {"label": "Agentes Prontos", "value": f"{ready} / {len(agents)}", "target": "Meta: 100%", "status": _status(_pct(ready, len(agents)), 100, 70)},
        {"label": "RTO Real", "value": "Não medido", "target": "Requer testes de restauração/SureRestore registrados", "status": "SEM DADOS"},
    ]
    report["delta"] = [
        _delta("neutral", "RPO real = idade do último backup bem-sucedido de cada agente."),
        _delta("down", "RTO não é estimado: o servidor ainda não recebe resultados de testes de restauração dos agentes."),
    ]
    report["sections"].append({
        "title": "Matriz de Prontidão por Agente",
        "narrative": "Cada agente recebe 25% por critério atendido (backup ≤ 24h, repositório, heartbeat, integridade ≥ 99%).",
        "table_headers": ["Agente", "RPO Real", "Backup ≤ 24h", "Repositórios", "Heartbeat", "Integridade", "Prontidão", "Status"],
        "table_rows": rows,
        "ai_inline": f"{len(agents) - ready} agente(s) com pendências de prontidão." if len(agents) - ready else "Todos os agentes atendem aos critérios de prontidão.",
    })
    pend = [r[0] for r in rows if r[-1] != "CONFORME"]
    actions = []
    if pend:
        actions.append({"priority": "ALTA", "action": "Resolver as pendências de prontidão de: " + ", ".join(pend[:10]) + ".", "owner": "Arquiteto de DR", "deadline": "7 dias"})
    actions.append({"priority": "MÉDIA", "action": "Executar e registrar testes de restauração (SureRestore) para permitir medir o RTO real.", "owner": "Arquiteto de DR", "deadline": "30 dias"})
    report["recommended_actions"] = actions
