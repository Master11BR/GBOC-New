"""
GBOC Server — Alertas proativos (avisar ANTES do problema virar incidente).

A cada ciclo (padrão 5 min) o Server avalia os dados reais com os mesmos critérios dos relatórios
(report_core) e abre/atualiza/encerra alertas:
  * repositório que esgota em até N dias (tendência de crescimento) e disco acima de N%;
  * volume do servidor protegido acima de N%;
  * RPO estourado há mais de N horas (ou tarefa que nunca concluiu backup);
  * N falhas seguidas na mesma tarefa;
  * agente sem comunicação há mais de N minutos;
  * teste de restauração reprovado (gerado pelo módulo de testes de restauração).

Notificação por e-mail (SMTP de Configurações > Notificações), Microsoft Teams (webhook do canal,
cartão adaptável) e webhook genérico. Um alerta novo notifica uma vez; enquanto continuar aberto e
não reconhecido, é lembrado a cada "repetir a cada N horas"; ao normalizar é encerrado (aviso opcional).
Também é registrado na Central de Alertas (system_events).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("gboc_proactive_alerts")
router = APIRouter(prefix="/api/v1/proactive-alerts", tags=["Alertas proativos"])

# rule_type: (rótulo, limiar padrão, unidade, severidade padrão, relatório de apoio, avaliado no ciclo?)
RULES: Dict[str, Tuple[str, Optional[float], str, str, str, bool]] = {
    "disk_full_days": ("Repositório esgota em até N dias", 7, "dias", "critical", "REP-06", True),
    "repo_usage_pct": ("Disco do repositório acima de N%", 90, "%", "warning", "REP-06", True),
    "volume_usage_pct": ("Volume do servidor protegido acima de N%", 90, "%", "warning", "REP-06", True),
    "rpo_breach_hours": ("RPO estourado há mais de N horas", 2, "horas", "critical", "REP-02", True),
    "consecutive_failures": ("N falhas seguidas na mesma tarefa", 3, "falhas", "critical", "REP-04", True),
    "agent_offline_minutes": ("Agente sem comunicação há mais de N minutos", 60, "min", "critical", "REP-05", True),
    "restore_test_failed": ("Teste de restauração reprovado", None, "", "critical", "REP-09", False),
    "license_expiring": ("Licença do GBOC vence em até N dias (ou acima do limite)", 30, "dias", "warning", "", True),
}
SEV_LABEL = {"critical": "Crítico", "warning": "Aviso"}

SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS proactive_alert_rules (
        rule_type VARCHAR(40) PRIMARY KEY,
        enabled BOOLEAN DEFAULT TRUE,
        threshold DOUBLE PRECISION,
        severity VARCHAR(10) DEFAULT 'warning',
        notify_email BOOLEAN DEFAULT TRUE,
        notify_teams BOOLEAN DEFAULT TRUE,
        notify_webhook BOOLEAN DEFAULT FALSE,
        repeat_hours INTEGER DEFAULT 24,
        notify_resolved BOOLEAN DEFAULT TRUE,
        updated_at TIMESTAMP DEFAULT LOCALTIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS proactive_alert_events (
        id SERIAL PRIMARY KEY,
        rule_type VARCHAR(40) NOT NULL,
        entity_key TEXT NOT NULL,
        agent_id TEXT,
        severity VARCHAR(10),
        title TEXT,
        message TEXT,
        report_code VARCHAR(10),
        status VARCHAR(15) NOT NULL DEFAULT 'open',
        first_seen TIMESTAMP DEFAULT LOCALTIMESTAMP,
        last_seen TIMESTAMP DEFAULT LOCALTIMESTAMP,
        last_notified_at TIMESTAMP,
        notify_count INTEGER DEFAULT 0,
        last_notify_error TEXT,
        acknowledged_by TEXT,
        acknowledged_at TIMESTAMP,
        resolved_at TIMESTAMP
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_proactive_alert_open ON proactive_alert_events(rule_type, entity_key)
       WHERE status <> 'resolved'""",
    "CREATE INDEX IF NOT EXISTS idx_proactive_alert_seen ON proactive_alert_events(last_seen DESC)",
]
SETTINGS_DEFAULTS = {
    "recipients": "",            # vazio = e-mail de destino de Configurações > Notificações
    "teams_webhook_url": "",
    "interval_minutes": "5",
    "enabled": "true",
}
_ready = False
_lock = threading.Lock()
_eval_lock = threading.Lock()
_last_eval: Dict[str, Any] = {}


def _db_exec(sql: str, params: Any = (), fetch: bool = True) -> List[Dict[str, Any]]:
    from modules.reports.report_schedules import _exec
    return _exec(sql, params, fetch)


def ensure_schema() -> None:
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        for sql in SCHEMA_SQL:
            _db_exec(sql, fetch=False)
        for rt, (_label, thr, _unit, sev, _rep, _ev) in RULES.items():
            _db_exec("""INSERT INTO proactive_alert_rules (rule_type, threshold, severity) VALUES (%s, %s, %s)
                        ON CONFLICT (rule_type) DO NOTHING""", (rt, thr, sev), False)
        for k, v in SETTINGS_DEFAULTS.items():
            _db_exec("""INSERT INTO server_settings (category, key, value) SELECT 'proactive_alerts', %s, %s
                        WHERE NOT EXISTS (SELECT 1 FROM server_settings WHERE category='proactive_alerts' AND key=%s)""",
                     (k, v, k), False)
        _ready = True


def get_settings() -> Dict[str, str]:
    ensure_schema()
    rows = _db_exec("SELECT key, value FROM server_settings WHERE category='proactive_alerts'")
    out = dict(SETTINGS_DEFAULTS)
    out.update({r["key"]: r["value"] or "" for r in rows})
    return out


def get_rules() -> Dict[str, Dict[str, Any]]:
    ensure_schema()
    rows = _db_exec("SELECT * FROM proactive_alert_rules")
    out = {}
    for r in rows:
        meta = RULES.get(r["rule_type"])
        if not meta:
            continue
        r = dict(r)
        r.update(label=meta[0], unit=meta[2], report=meta[4], evaluated=meta[5], has_threshold=meta[1] is not None)
        if hasattr(r.get("updated_at"), "isoformat"):
            r["updated_at"] = r["updated_at"].isoformat(sep=" ")
        out[r["rule_type"]] = r
    return out


# ───────────────────────── avaliação ─────────────────────────

def _conditions(rules: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Situações que justificam alerta agora, calculadas sobre os dados reais."""
    from modules.reports import report_core as rc
    from modules.reports.report_source_server import ServerReportSource

    def on(rt):
        r = rules.get(rt)
        return r if r and r.get("enabled") else None

    out: List[Dict[str, Any]] = []
    with ServerReportSource() as src:
        ctx = rc.ReportContext(src, days=30)
        host = ctx.host

        r = on("agent_offline_minutes")
        if r:
            lim = float(r.get("threshold") or 60)
            for a in ctx.agents:
                hb = rc.to_dt(a.get("last_heartbeat"))
                if hb and (ctx.end - hb).total_seconds() > lim * 60:
                    out.append({"rule_type": "agent_offline_minutes", "entity_key": a["agent_id"], "agent_id": a["agent_id"],
                                "title": f"Agente {host(a['agent_id'])} sem comunicação",
                                "message": f"Último contato em {rc.fmt_dt(hb)} (há {rc.fmt_age_hours((ctx.end - hb).total_seconds() / 3600)}). "
                                           "Verifique se o serviço do agente e a rede estão ativos."})
        offline = {x["agent_id"] for x in out}

        r = on("rpo_breach_hours")
        if r:
            extra = float(r.get("threshold") or 0)
            for x in rc._task_rpo_rows(ctx):
                t = x["task"]
                aid = t.get("agent_id")
                key = f"{aid}:{t.get('task_id')}"
                if x["age_h"] is None:
                    out.append({"rule_type": "rpo_breach_hours", "entity_key": key, "agent_id": aid,
                                "title": f"{host(aid)} / {t.get('name')}: nenhum backup com sucesso",
                                "message": "A tarefa está ativa e nunca concluiu um backup com sucesso no período analisado."})
                elif x["age_h"] > x["target_h"] + extra:
                    out.append({"rule_type": "rpo_breach_hours", "entity_key": key, "agent_id": aid,
                                "title": f"{host(aid)} / {t.get('name')}: RPO estourado",
                                "message": f"Último backup válido há {rc.fmt_age_hours(x['age_h'])} — alvo {rc.fmt_age_hours(x['target_h'])}"
                                           f" (estourado há {rc.fmt_age_hours(x['age_h'] - x['target_h'])})."
                                           + (" O agente está sem comunicação." if aid in offline else "")})

        r = on("consecutive_failures")
        if r:
            lim = int(r.get("threshold") or 3)
            for t in ctx.active_tasks:
                n = ctx.failure_streak(t)
                if n >= lim:
                    last = ctx.last_run(t) or {}
                    cat, action = rc.classify_error(last.get("error"))
                    out.append({"rule_type": "consecutive_failures", "entity_key": f"{t.get('agent_id')}:{t.get('task_id')}",
                                "agent_id": t.get("agent_id"),
                                "title": f"{host(t.get('agent_id'))} / {t.get('name')}: {n} falhas seguidas",
                                "message": f"Causa provável: {cat}. {action} Último erro: {str(last.get('error') or '—')[:300]}"})

        rd, ru = on("disk_full_days"), on("repo_usage_pct")
        if rd or ru:
            for g in rc._repo_growth(ctx):
                rp = g["repo"]
                aid = rp.get("agent_id")
                key = f"{aid}:{rp.get('repo_id')}"
                if rd and g["days_full"] is not None and g["days_full"] <= float(rd.get("threshold") or 7):
                    out.append({"rule_type": "disk_full_days", "entity_key": key, "agent_id": aid,
                                "title": f"{host(aid)} / {rp.get('name')}: espaço acaba em {max(0, g['days_full']):.0f} dia(s)",
                                "message": f"Livre: {rc.fmt_bytes(g['free'])}; crescimento {rc.fmt_bytes(g['slope'])}/dia ({g['method']}). "
                                           "Amplie o armazenamento, ajuste a retenção ou mova dados antigos."})
                if ru and g["used_pct"] is not None and g["used_pct"] >= float(ru.get("threshold") or 90):
                    out.append({"rule_type": "repo_usage_pct", "entity_key": key, "agent_id": aid,
                                "title": f"{host(aid)} / {rp.get('name')}: disco {g['used_pct']:.0f}% ocupado",
                                "message": f"Livre: {rc.fmt_bytes(g['free'])} de {rc.fmt_bytes(g['cap'])}."})

        r = on("volume_usage_pct")
        if r:
            lim = float(r.get("threshold") or 90)
            for v in ctx.volumes:
                tot, used = rc.to_float(v.get("total_bytes")), rc.to_float(v.get("used_bytes"))
                if tot and used is not None and tot >= 1024 ** 3 and used / tot * 100 >= lim:
                    aid = v.get("agent_id")
                    out.append({"rule_type": "volume_usage_pct", "entity_key": f"{aid}:{v.get('mountpoint')}", "agent_id": aid,
                                "title": f"{host(aid)}: volume {v.get('mountpoint')} {used / tot * 100:.0f}% ocupado",
                                "message": f"Livre: {rc.fmt_bytes(tot - used)} de {rc.fmt_bytes(tot)}."})
    r = on("license_expiring")
    if r:
        try:
            from modules.multitenant.licensing import status as lic_status
            st = lic_status()
            if st.get("enforced") and (st["state"] in ("grace", "expired") or
                                       (st.get("days_left") is not None and st["days_left"] <= float(r.get("threshold") or 30))):
                out.append({"rule_type": "license_expiring", "entity_key": f"license:{st.get('license_id')}", "agent_id": None,
                            "title": "Licença do GBOC Server " + ("vencida" if st["state"] in ("grace", "expired") else "perto do vencimento"),
                            "message": st["message"]})
            if st.get("over_limit"):
                out.append({"rule_type": "license_expiring", "entity_key": f"license-over:{st.get('license_id')}", "agent_id": None,
                            "title": "Agentes acima do limite da licença", "message": st["message"]})
        except Exception as e:
            logger.debug(f"licença: {e}")
    for c in out:
        rule = rules[c["rule_type"]]
        c["severity"] = rule.get("severity") or RULES[c["rule_type"]][3]
        c["report_code"] = RULES[c["rule_type"]][4]
    return out


def _hostname(agent_id: Optional[str]) -> str:
    if not agent_id:
        return ""
    rows = _db_exec("SELECT hostname FROM agents WHERE agent_id=%s", (agent_id,))
    return (rows[0]["hostname"] if rows else None) or agent_id


def _log_event(ev: Dict[str, Any], resolved: bool = False) -> None:
    """Espelha na Central de Alertas (system_events)."""
    try:
        etype = "info" if resolved else ("alert_critical" if ev.get("severity") == "critical" else "warning")
        text = ("[Normalizado] " if resolved else "[Alerta proativo] ") + f"{ev.get('title')} — {ev.get('message') or ''}"
        _db_exec("INSERT INTO system_events (event_type, message, agent_hostname) VALUES (%s, %s, %s)",
                 (etype, text[:2000], _hostname(ev.get("agent_id"))[:255]), False)
    except Exception as e:
        logger.debug(f"system_events: {e}")


def _upsert(cond: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    rows = _db_exec("""SELECT * FROM proactive_alert_events WHERE rule_type=%s AND entity_key=%s AND status <> 'resolved'""",
                    (cond["rule_type"], cond["entity_key"]))
    if rows:
        ev = _db_exec("""UPDATE proactive_alert_events SET last_seen=LOCALTIMESTAMP, title=%s, message=%s, severity=%s
                         WHERE id=%s RETURNING *""", (cond["title"], cond["message"], cond["severity"], rows[0]["id"]))[0]
        return ev, False
    ev = _db_exec("""INSERT INTO proactive_alert_events (rule_type, entity_key, agent_id, severity, title, message, report_code)
                     VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                  (cond["rule_type"], cond["entity_key"], cond.get("agent_id"), cond["severity"], cond["title"],
                   cond.get("message"), cond.get("report_code")))[0]
    _log_event(ev)
    return ev, True


def evaluate(notify: bool = True) -> Dict[str, Any]:
    """Um ciclo completo: abre, atualiza, lembra e encerra alertas e envia as notificações agrupadas."""
    if not _eval_lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        ensure_schema()
        rules = get_rules()
        conds = _conditions(rules)
        now = datetime.now()
        new, reminders, resolved = [], [], []
        seen = set()
        for c in conds:
            ev, created = _upsert(c)
            seen.add((c["rule_type"], c["entity_key"]))
            rule = rules[c["rule_type"]]
            if created:
                new.append((ev, rule))
            elif ev["status"] == "open":
                last = ev.get("last_notified_at")
                rep = int(rule.get("repeat_hours") or 0)
                if rep > 0 and last and now - last >= timedelta(hours=rep):
                    reminders.append((ev, rule))
        evaluated = [rt for rt, meta in RULES.items() if meta[5]]
        for ev in _db_exec("""SELECT * FROM proactive_alert_events WHERE status <> 'resolved' AND rule_type = ANY(%s)""", (evaluated,)):
            if (ev["rule_type"], ev["entity_key"]) not in seen:
                rule = rules.get(ev["rule_type"]) or {}
                ev = _db_exec("""UPDATE proactive_alert_events SET status='resolved', resolved_at=LOCALTIMESTAMP WHERE id=%s RETURNING *""",
                              (ev["id"],))[0]
                if not rule.get("enabled"):
                    continue            # regra desativada: encerra sem avisar "normalizado"
                _log_event(ev, resolved=True)
                if rule.get("notify_resolved"):
                    resolved.append((ev, rule))
        sent = dispatch(new, reminders, resolved) if notify else {}
        summary = {"status": "success", "evaluated_at": now.isoformat(sep=" ", timespec="seconds"), "conditions": len(conds),
                   "new": len(new), "reminders": len(reminders), "resolved": len(resolved), "notifications": sent}
        _last_eval.clear()
        _last_eval.update(summary)
        return summary
    finally:
        _eval_lock.release()


def raise_external_alert(rule_type: str, entity_key: str, agent_id: Optional[str], severity: str, title: str,
                         message: str) -> None:
    """Alerta originado por outro módulo (ex.: teste de restauração reprovado)."""
    ensure_schema()
    rules = get_rules()
    rule = rules.get(rule_type)
    if not rule or not rule.get("enabled"):
        return
    ev, created = _upsert({"rule_type": rule_type, "entity_key": entity_key, "agent_id": agent_id,
                           "severity": rule.get("severity") or severity, "title": title, "message": message,
                           "report_code": RULES[rule_type][4]})
    dispatch([(ev, rule)] if created else [], [] if created else [(ev, rule)], [])


def resolve_external(rule_type: str, entity_key: str) -> None:
    ensure_schema()
    rows = _db_exec("""UPDATE proactive_alert_events SET status='resolved', resolved_at=LOCALTIMESTAMP
                       WHERE rule_type=%s AND entity_key=%s AND status <> 'resolved' RETURNING *""", (rule_type, entity_key))
    rule = get_rules().get(rule_type) or {}
    for ev in rows:
        _log_event(ev, resolved=True)
    if rows and rule.get("notify_resolved"):
        dispatch([], [], [(ev, rule) for ev in rows])


# ───────────────────────── notificação ─────────────────────────

def _recipients(settings: Dict[str, str]) -> List[str]:
    raw = settings.get("recipients") or ""
    if not raw.strip():
        rows = _db_exec("SELECT value FROM server_settings WHERE category='notifications' AND key='smtp_to'")
        raw = rows[0]["value"] if rows else ""
    return [r.strip() for r in str(raw).replace(";", ",").split(",") if "@" in r]


def _esc(v: Any) -> str:
    return str(v or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _email_html(groups: List[Tuple[str, List[Dict[str, Any]]]]) -> str:
    color = {"critical": "#b42323", "warning": "#9a6400"}
    parts = ["<div style='font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#222'>",
             "<h2 style='margin:0 0 12px'>GBOC — Alertas proativos</h2>"]
    for title, evs in groups:
        if not evs:
            continue
        parts.append(f"<h3 style='margin:16px 0 6px'>{_esc(title)} ({len(evs)})</h3><table style='border-collapse:collapse;width:100%'>")
        for e in evs:
            sev = e.get("severity") or "warning"
            tag = "Normalizado" if e.get("status") == "resolved" else SEV_LABEL.get(sev, sev)
            c = "#0a7a0a" if e.get("status") == "resolved" else color.get(sev, "#333")
            parts.append(f"<tr><td style='padding:6px 8px;border-bottom:1px solid #eee;white-space:nowrap;color:{c};font-weight:600'>"
                         f"{_esc(tag)}</td><td style='padding:6px 8px;border-bottom:1px solid #eee'><b>{_esc(e.get('title'))}</b><br>"
                         f"<span style='color:#555'>{_esc(e.get('message'))}</span><br><span style='color:#888;font-size:12px'>"
                         f"Desde {_esc(str(e.get('first_seen'))[:16])}" + (f" · relatório de apoio {_esc(e.get('report_code'))}" if e.get('report_code') else "") + "</span></td></tr>")
        parts.append("</table>")
    parts.append("<p style='color:#888;font-size:12px;margin-top:16px'>Reconheça os alertas em GBOC Server → Central de Alertas → "
                 "Alertas proativos para parar os lembretes.</p></div>")
    return "".join(parts)


def _teams_card(groups: List[Tuple[str, List[Dict[str, Any]]]]) -> Dict[str, Any]:
    body: List[Dict[str, Any]] = [{"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": "GBOC — Alertas proativos"}]
    for title, evs in groups:
        if not evs:
            continue
        body.append({"type": "TextBlock", "weight": "Bolder", "spacing": "Medium", "text": f"{title} ({len(evs)})"})
        for e in evs[:25]:
            resolved = e.get("status") == "resolved"
            body.append({"type": "TextBlock", "wrap": True, "spacing": "Small",
                         "color": "Good" if resolved else ("Attention" if e.get("severity") == "critical" else "Warning"),
                         "text": f"**{'Normalizado' if resolved else SEV_LABEL.get(e.get('severity'), '')}** · {e.get('title')}"})
            if e.get("message") and not resolved:
                body.append({"type": "TextBlock", "wrap": True, "isSubtle": True, "spacing": "None", "text": str(e["message"])[:400]})
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
            "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
                        "version": "1.4", "msteams": {"width": "Full"}, "body": body}}]}


def _post_json(url: str, payload: Dict[str, Any]) -> None:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status >= 400:
            raise RuntimeError(f"HTTP {r.status}")


def _send_channels(groups: List[Tuple[str, List[Dict[str, Any]]]], channels: set, subject: str) -> Dict[str, str]:
    settings = get_settings()
    out: Dict[str, str] = {}
    if "email" in channels:
        try:
            rcpt = _recipients(settings)
            if not rcpt:
                raise RuntimeError("Nenhum destinatário configurado")
            from modules.reports.report_schedules import send_html_mail
            send_html_mail(subject, _email_html(groups), rcpt)
            out["email"] = f"enviado ({len(rcpt)})"
        except Exception as e:
            out["email"] = f"erro: {e}"
    if "teams" in channels:
        url = (settings.get("teams_webhook_url") or "").strip()
        if url:
            try:
                _post_json(url, _teams_card(groups))
                out["teams"] = "enviado"
            except Exception as e:
                out["teams"] = f"erro: {e}"
        else:
            out["teams"] = "não configurado"
    if "webhook" in channels:
        rows = _db_exec("SELECT key, value FROM server_settings WHERE category='notifications' AND key IN ('webhook_url','webhook_enabled')")
        cfg = {r["key"]: r["value"] for r in rows}
        if cfg.get("webhook_url"):
            try:
                lines = [f"{t}: " + "; ".join(e.get("title") or "" for e in evs) for t, evs in groups if evs]
                _post_json(cfg["webhook_url"], {"text": f"🔔 *{subject}*\n" + "\n".join(lines), "subject": subject,
                                                "alerts": [{k: str(v) for k, v in e.items() if k in ("title", "message", "severity", "status", "agent_id")}
                                                           for _t, evs in groups for e in evs]})
                out["webhook"] = "enviado"
            except Exception as e:
                out["webhook"] = f"erro: {e}"
        else:
            out["webhook"] = "não configurado"
    return out


def dispatch(new: List[tuple], reminders: List[tuple], resolved: List[tuple]) -> Dict[str, Any]:
    """Agrupa por canal: um e-mail/cartão por ciclo com novos, lembretes e normalizados."""
    settings = get_settings()
    if str(settings.get("enabled", "true")).lower() == "false":
        return {"status": "notificações desativadas"}
    per_channel: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: {"new": [], "rem": [], "res": []})
    for bucket, items in (("new", new), ("rem", reminders), ("res", resolved)):
        for ev, rule in items:
            for ch, flag in (("email", "notify_email"), ("teams", "notify_teams"), ("webhook", "notify_webhook")):
                if rule.get(flag):
                    per_channel[ch][bucket].append(ev)
    results: Dict[str, Any] = {}
    # canais com o mesmo conteúdo são enviados juntos
    combos: Dict[str, set] = defaultdict(set)
    for ch, b in per_channel.items():
        sig = json.dumps({k: sorted(e["id"] for e in v) for k, v in b.items()})
        combos[sig].add(ch)
    for sig, chans in combos.items():
        b = per_channel[next(iter(chans))]
        if not (b["new"] or b["rem"] or b["res"]):
            continue
        crit = sum(1 for e in b["new"] + b["rem"] if e.get("severity") == "critical")
        subject = (f"[GBOC] {len(b['new'])} novo(s) alerta(s)" if b["new"] else
                   f"[GBOC] {len(b['rem'])} alerta(s) ainda ativo(s)" if b["rem"] else
                   f"[GBOC] {len(b['res'])} alerta(s) normalizado(s)") + (f" — {crit} crítico(s)" if crit else "")
        groups = [("Novos alertas", b["new"]), ("Ainda ativos (lembrete)", b["rem"]), ("Normalizados", b["res"])]
        res = _send_channels(groups, chans, subject)
        results.update(res)
        ok_any = any(str(v).startswith("enviado") for v in res.values())
        err = "; ".join(f"{k}: {v}" for k, v in res.items() if not str(v).startswith("enviado")) or None
        ids = [e["id"] for e in b["new"] + b["rem"]]
        if ids:
            _db_exec(f"""UPDATE proactive_alert_events SET last_notified_at = CASE WHEN %s THEN LOCALTIMESTAMP ELSE last_notified_at END,
                         notify_count = notify_count + CASE WHEN %s THEN 1 ELSE 0 END, last_notify_error=%s WHERE id = ANY(%s)""",
                     (ok_any, ok_any, err, ids), False)
    # alertas novos sem canal habilitado também contam como "notificados" (para não virar lembrete imediato)
    pending_new = [ev["id"] for ev, _r in new]
    if pending_new:
        _db_exec("""UPDATE proactive_alert_events SET last_notified_at = COALESCE(last_notified_at, LOCALTIMESTAMP)
                    WHERE id = ANY(%s)""", (pending_new,), False)
    return results


# ───────────────────────── agendador ─────────────────────────

async def scheduler_loop() -> None:
    await asyncio.sleep(120)
    while True:
        interval = 5
        try:
            st = await asyncio.to_thread(get_settings)
            interval = max(1, min(240, int(float(st.get("interval_minutes") or 5))))
            await asyncio.to_thread(evaluate, True)
        except Exception as e:
            logger.warning(f"[ALERTAS] Avaliação falhou: {e}")
        await asyncio.sleep(interval * 60)


def start_scheduler() -> None:
    asyncio.get_event_loop().create_task(scheduler_loop())


# ───────────────────────── rotas ─────────────────────────

def _require_admin(request: Request) -> None:
    role = (((getattr(request.state, "user", None) or {}).get("role")) or "").lower()
    if role and role not in ("admin", "superadmin", "administrator", "operator"):
        raise HTTPException(403, "Requer perfil admin ou operator.")


def _ser(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v.isoformat(sep=" ", timespec="seconds") if hasattr(v, "isoformat") else v) for k, v in r.items()}


@router.get("/rules")
async def list_rules():
    rules = await asyncio.to_thread(get_rules)
    order = list(RULES)
    return {"status": "success", "rules": sorted(rules.values(), key=lambda r: order.index(r["rule_type"]))}


@router.put("/rules")
async def update_rules(request: Request):
    _require_admin(request)
    body = await request.json()
    items = body.get("rules") if isinstance(body, dict) else body
    if not isinstance(items, list):
        raise HTTPException(400, "Envie {rules: [...]}")
    await asyncio.to_thread(ensure_schema)
    for it in items:
        rt = it.get("rule_type")
        if rt not in RULES:
            continue
        thr = it.get("threshold")
        if RULES[rt][1] is not None:
            try:
                thr = float(thr)
            except (TypeError, ValueError):
                raise HTTPException(400, f"Limite inválido em '{RULES[rt][0]}'")
            if thr < 0 or (RULES[rt][2] == "%" and thr > 100):
                raise HTTPException(400, f"Limite fora do intervalo em '{RULES[rt][0]}'")
        else:
            thr = None
        sev = it.get("severity") if it.get("severity") in SEV_LABEL else RULES[rt][3]
        await asyncio.to_thread(_db_exec, """UPDATE proactive_alert_rules SET enabled=%s, threshold=%s, severity=%s, notify_email=%s,
                notify_teams=%s, notify_webhook=%s, repeat_hours=%s, notify_resolved=%s, updated_at=LOCALTIMESTAMP WHERE rule_type=%s""",
            (bool(it.get("enabled", True)), thr, sev, bool(it.get("notify_email", True)), bool(it.get("notify_teams", True)),
             bool(it.get("notify_webhook", False)), max(0, min(720, int(it.get("repeat_hours") or 0))),
             bool(it.get("notify_resolved", True)), rt), False)
    return await list_rules()


@router.get("/settings")
async def read_settings():
    s = await asyncio.to_thread(get_settings)
    url = s.get("teams_webhook_url") or ""
    masked = (url[:38] + "…" + url[-6:]) if len(url) > 50 else url
    return {"status": "success", "settings": {**s, "teams_webhook_url": masked, "teams_configured": bool(url)},
            "default_recipients": await asyncio.to_thread(_recipients, {"recipients": ""}), "last_evaluation": dict(_last_eval)}


@router.put("/settings")
async def write_settings(request: Request):
    _require_admin(request)
    b = await request.json() or {}
    await asyncio.to_thread(ensure_schema)
    updates = {}
    if "recipients" in b:
        bad = [r for r in str(b["recipients"]).replace(";", ",").split(",") if r.strip() and "@" not in r]
        if bad:
            raise HTTPException(400, f"E-mail inválido: {bad[0].strip()}")
        updates["recipients"] = str(b["recipients"])[:2000]
    if "teams_webhook_url" in b and "…" not in str(b["teams_webhook_url"]):
        url = str(b["teams_webhook_url"]).strip()
        if url and not url.lower().startswith("https://"):
            raise HTTPException(400, "A URL do webhook do Teams deve começar com https://")
        updates["teams_webhook_url"] = url
    if "interval_minutes" in b:
        updates["interval_minutes"] = str(max(1, min(240, int(b["interval_minutes"]))))
    if "enabled" in b:
        updates["enabled"] = "true" if b["enabled"] else "false"
    for k, v in updates.items():
        await asyncio.to_thread(_db_exec, "UPDATE server_settings SET value=%s WHERE category='proactive_alerts' AND key=%s", (v, k), False)
    return await read_settings()


@router.post("/test")
async def test_channel(request: Request):
    _require_admin(request)
    b = await request.json() or {}
    ch = b.get("channel") or "email"
    if ch not in ("email", "teams", "webhook"):
        raise HTTPException(400, "Canal inválido")
    sample = [{"id": 0, "severity": "warning", "status": "open", "title": "Mensagem de teste do GBOC Server",
               "message": "Se você recebeu esta mensagem, o canal de alertas proativos está funcionando.",
               "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M"), "report_code": "—"}]
    res = await asyncio.to_thread(_send_channels, [("Teste", sample)], {ch}, "[GBOC] Teste de alertas proativos")
    ok = str(res.get(ch, "")).startswith("enviado")
    if not ok:
        raise HTTPException(502, f"Falha no canal {ch}: {res.get(ch)}")
    return {"status": "success", "result": res}


@router.post("/evaluate")
async def evaluate_now(request: Request):
    _require_admin(request)
    return await asyncio.to_thread(evaluate, True)


@router.get("/events")
async def list_events(status: str = "open", days: int = 30, limit: int = 300):
    await asyncio.to_thread(ensure_schema)
    if status == "open":
        cl, params = "e.status <> 'resolved'", ()
    else:
        cl, params = "e.last_seen >= %s", (datetime.now() - timedelta(days=max(1, min(days, 365))),)
    rows = await asyncio.to_thread(_db_exec, f"""
        SELECT e.*, a.hostname FROM proactive_alert_events e LEFT JOIN agents a ON a.agent_id = e.agent_id
        WHERE {cl} ORDER BY (e.status = 'resolved'), CASE e.severity WHEN 'critical' THEN 0 ELSE 1 END, e.first_seen DESC
        LIMIT %s""", params + (max(1, min(limit, 2000)),))
    counts = await asyncio.to_thread(_db_exec, """SELECT severity, COUNT(*) AS n FROM proactive_alert_events
                                                   WHERE status <> 'resolved' GROUP BY severity""")
    return {"status": "success", "events": [_ser(r) for r in rows],
            "open": {r["severity"]: r["n"] for r in counts}, "last_evaluation": dict(_last_eval)}


def _user(request: Request) -> str:
    u = getattr(request.state, "user", None) or {}
    return (u.get("username") if isinstance(u, dict) else None) or "?"


@router.post("/events/{event_id}/ack")
async def ack_event(event_id: int, request: Request):
    rows = await asyncio.to_thread(_db_exec, """UPDATE proactive_alert_events SET status='acknowledged', acknowledged_by=%s,
                                                 acknowledged_at=LOCALTIMESTAMP WHERE id=%s AND status='open' RETURNING *""",
                                   (_user(request), event_id))
    if not rows:
        raise HTTPException(404, "Alerta não encontrado ou já reconhecido/encerrado.")
    return {"status": "success", "event": _ser(rows[0])}


@router.post("/events/{event_id}/resolve")
async def resolve_event(event_id: int, request: Request):
    rows = await asyncio.to_thread(_db_exec, """UPDATE proactive_alert_events SET status='resolved', resolved_at=LOCALTIMESTAMP,
                                                 acknowledged_by=COALESCE(acknowledged_by, %s) WHERE id=%s AND status <> 'resolved'
                                                 RETURNING *""", (_user(request), event_id))
    if not rows:
        raise HTTPException(404, "Alerta não encontrado ou já encerrado.")
    return {"status": "success", "event": _ser(rows[0])}
