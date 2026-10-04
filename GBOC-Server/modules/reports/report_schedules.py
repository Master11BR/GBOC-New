"""
GBOC Server — Agendamento de relatórios por e-mail.

Substitui a lista fixa de agendamentos de exemplo por agendamentos reais:
  * tabela report_schedules (relatório, frequência, horário, período, agente/cliente, destinatários);
  * verificação a cada minuto em segundo plano; envio do relatório em HTML (anexo, pronto para
    imprimir/PDF) + CSV usando o SMTP de Configurações > Notificações;
  * "Enviar agora" para testar e histórico do último envio.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import threading
import time
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("gboc_report_schedules")
router = APIRouter(prefix="/api/v1/reports/schedules", tags=["Relatórios - Agendamentos"])

_SCHEMA = """
CREATE TABLE IF NOT EXISTS report_schedules (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    report_code VARCHAR(20) NOT NULL,
    frequency VARCHAR(10) NOT NULL DEFAULT 'weekly',
    hour SMALLINT NOT NULL DEFAULT 8,
    minute SMALLINT NOT NULL DEFAULT 0,
    weekday SMALLINT DEFAULT 0,
    day_of_month SMALLINT DEFAULT 1,
    days INTEGER NOT NULL DEFAULT 30,
    agent_id TEXT,
    tenant_id TEXT,
    recipients TEXT NOT NULL,
    attach_csv BOOLEAN DEFAULT TRUE,
    enabled BOOLEAN DEFAULT TRUE,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
    last_run_at TIMESTAMP,
    last_status TEXT,
    last_error TEXT
)"""
_ready = False
_lock = threading.Lock()
FREQS = {"daily": "Diário", "weekly": "Semanal", "monthly": "Mensal"}
WEEKDAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def _db():
    from database import db_manager
    return db_manager


def _exec(sql: str, params: tuple = (), fetch: bool = True) -> List[Dict[str, Any]]:
    from psycopg2.extras import RealDictCursor
    dbm = _db()
    conn = dbm.get_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()] if (fetch and cur.description) else []
        conn.commit()
        cur.close()
        return rows
    except Exception:
        conn.rollback()
        raise
    finally:
        dbm.release_connection(conn)


def ensure_schema() -> None:
    global _ready
    if _ready:
        return
    with _lock:
        if not _ready:
            _exec(_SCHEMA, fetch=False)
            _ready = True


def _describe(s: Dict[str, Any]) -> str:
    hhmm = f"{int(s.get('hour') or 0):02d}:{int(s.get('minute') or 0):02d}"
    f = s.get("frequency")
    if f == "daily":
        return f"Diário às {hhmm}"
    if f == "weekly":
        return f"Semanal ({WEEKDAYS[int(s.get('weekday') or 0) % 7]}) às {hhmm}"
    return f"Mensal (dia {int(s.get('day_of_month') or 1)}) às {hhmm}"


def next_run(s: Dict[str, Any], after: Optional[datetime] = None) -> datetime:
    now = after or datetime.now()
    h, m = int(s.get("hour") or 0), int(s.get("minute") or 0)
    cand = now.replace(hour=h, minute=m, second=0, microsecond=0)
    f = s.get("frequency")
    if f == "daily":
        return cand if cand > now else cand + timedelta(days=1)
    if f == "weekly":
        wd = int(s.get("weekday") or 0) % 7
        delta = (wd - now.weekday()) % 7
        cand = cand + timedelta(days=delta)
        return cand if cand > now else cand + timedelta(days=7)
    dom = max(1, min(28, int(s.get("day_of_month") or 1)))
    cand = cand.replace(day=dom)
    if cand <= now:
        y, mo = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
        cand = cand.replace(year=y, month=mo)
    return cand


def _serialize(s: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in s.items()}
    out["description"] = _describe(s)
    out["next_run_at"] = next_run(s).isoformat() if s.get("enabled") else None
    return out


def _smtp_config() -> Dict[str, str]:
    rows = _exec("SELECT key, value FROM server_settings WHERE category = 'notifications'")
    return {r["key"]: r["value"] for r in rows}


def _send(schedule: Dict[str, Any]) -> Dict[str, Any]:
    """Gera o relatório e envia por e-mail. Retorna {status, message}."""
    from modules.reports import report_core as rc
    from modules.reports.report_source_server import ServerReportSource

    cfg = _smtp_config()
    host, user = cfg.get("smtp_host", ""), cfg.get("smtp_username", "")
    if not host:
        raise RuntimeError("SMTP não configurado (Configurações > Notificações).")
    recipients = [r.strip() for r in str(schedule.get("recipients") or "").replace(";", ",").split(",") if r.strip()]
    if not recipients:
        raise RuntimeError("Nenhum destinatário informado.")
    agent_ids = [a for a in str(schedule.get("agent_id") or "").split(",") if a.strip()] or None
    with ServerReportSource() as src:
        rep = rc.build_report(src, schedule["report_code"], days=int(schedule.get("days") or 30),
                              agent_ids=agent_ids, tenant_id=schedule.get("tenant_id") or None)
    html_doc = rc.render_html(rep)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    msg = MIMEMultipart()
    msg["Subject"] = f"[GBOC] {rep['code']} {rep['title']} — {rep['scope']}"
    msg["From"] = cfg.get("smtp_from") or user or "gboc@localhost"
    msg["To"] = ", ".join(recipients)
    kp = "".join(f"<li><b>{rc.esc(k['label'])}:</b> {rc.esc(k['value'])}</li>" for k in rep.get("kpis", []))
    fd = "".join(f"<li>{rc.esc(f['text'])}</li>" for f in rep.get("findings", []))
    body = (f"<p>Segue o relatório <b>{rc.esc(rep['title'])}</b> ({rc.esc(rep['scope'])}, últimos {rep['period']['days']} dias).</p>"
            f"<ul>{kp}</ul>" + (f"<p><b>Constatações</b></p><ul>{fd}</ul>" if fd else "") +
            "<p>O relatório completo, com gráficos e detalhamento, está no anexo HTML (abra e use Imprimir → Salvar como PDF).</p>"
            f"<p style='color:#777;font-size:12px'>Agendamento: {rc.esc(schedule.get('name'))} · {rc.esc(_describe(schedule))}</p>")
    msg.attach(MIMEText(body, "html", "utf-8"))
    att = MIMEApplication(html_doc.encode("utf-8"), _subtype="html")
    att.add_header("Content-Disposition", "attachment", filename=f"GBOC_{rep['code']}_{stamp}.html")
    msg.attach(att)
    if schedule.get("attach_csv", True):
        c = MIMEApplication(rc.render_csv(rep).encode("utf-8-sig"), _subtype="csv")
        c.add_header("Content-Disposition", "attachment", filename=f"GBOC_{rep['code']}_{stamp}.csv")
        msg.attach(c)
    port = int(cfg.get("smtp_port") or 587)
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            if user:
                s.login(user, cfg.get("smtp_password", ""))
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            try:
                s.starttls()
            except smtplib.SMTPNotSupportedError:
                pass
            if user:
                s.login(user, cfg.get("smtp_password", ""))
            s.send_message(msg)
    return {"status": "sent", "message": f"Enviado para {len(recipients)} destinatário(s)."}


def _run_and_record(schedule: Dict[str, Any]) -> Dict[str, Any]:
    try:
        res = _send(schedule)
        _exec("UPDATE report_schedules SET last_run_at=LOCALTIMESTAMP, last_status='sent', last_error=NULL WHERE id=%s",
              (schedule["id"],), fetch=False)
        return res
    except Exception as e:
        logger.warning(f"[AGENDAMENTO] Relatório '{schedule.get('name')}' não enviado: {e}")
        _exec("UPDATE report_schedules SET last_run_at=LOCALTIMESTAMP, last_status='error', last_error=%s WHERE id=%s",
              (str(e)[:1000], schedule["id"]), fetch=False)
        return {"status": "error", "message": str(e)}


def scheduler_loop() -> None:
    time.sleep(60)
    while True:
        try:
            ensure_schema()
            now = datetime.now()
            for s in _exec("SELECT * FROM report_schedules WHERE enabled = TRUE"):
                last = s.get("last_run_at")
                # Momento agendado mais recente (anterior a agora); envia se ainda não foi enviado depois dele
                prev = next_run(s, after=now - timedelta(days=32))
                while True:
                    nxt = next_run(s, after=prev)
                    if nxt > now:
                        break
                    prev = nxt
                created = s.get("created_at") or now
                due = (prev <= now and prev >= created and (now - prev) < timedelta(hours=6)
                       and (last is None or last < prev))
                if due:
                    _run_and_record(s)
        except Exception as e:
            logger.warning(f"[AGENDAMENTO] Verificação falhou: {e}")
        time.sleep(60)


def start_scheduler() -> None:
    threading.Thread(target=scheduler_loop, name="gboc-report-schedules", daemon=True).start()


def _validate(body: Dict[str, Any]) -> Dict[str, Any]:
    from modules.reports import report_core as rc
    spec = rc.find_report(body.get("report_code") or body.get("report_id"))
    if not spec:
        raise HTTPException(400, "Relatório inválido.")
    freq = body.get("frequency") or "weekly"
    if freq not in FREQS:
        raise HTTPException(400, "Frequência inválida (daily, weekly ou monthly).")
    recipients = str(body.get("recipients") or "").strip()
    if not recipients or "@" not in recipients:
        raise HTTPException(400, "Informe ao menos um e-mail de destino.")
    try:
        hour = int(body.get("hour", 8))
        minute = int(body.get("minute", 0))
        days = int(body.get("days", 30))
    except (TypeError, ValueError):
        raise HTTPException(400, "Horário/período inválido.")
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 1 <= days <= 730):
        raise HTTPException(400, "Horário/período fora do intervalo.")
    return {"name": (body.get("name") or spec["name"])[:200], "report_code": spec["code"], "frequency": freq,
            "hour": hour, "minute": minute, "weekday": int(body.get("weekday") or 0) % 7,
            "day_of_month": max(1, min(28, int(body.get("day_of_month") or 1))), "days": days,
            "agent_id": (body.get("agent_id") or None), "tenant_id": (body.get("tenant_id") or None),
            "recipients": recipients[:2000], "attach_csv": bool(body.get("attach_csv", True)),
            "enabled": bool(body.get("enabled", True))}


def _user(request: Request) -> str:
    u = getattr(request.state, "user", None) or {}
    return (u.get("username") if isinstance(u, dict) else None) or "?"


@router.get("")
async def list_schedules():
    await asyncio.to_thread(ensure_schema)
    rows = await asyncio.to_thread(_exec, "SELECT * FROM report_schedules ORDER BY id")
    return {"status": "success", "schedules": [_serialize(r) for r in rows]}


@router.post("")
async def create_schedule(request: Request):
    body = await request.json()
    v = _validate(body or {})
    await asyncio.to_thread(ensure_schema)
    rows = await asyncio.to_thread(_exec, """
        INSERT INTO report_schedules (name, report_code, frequency, hour, minute, weekday, day_of_month, days, agent_id,
            tenant_id, recipients, attach_csv, enabled, created_by)
        VALUES (%(name)s, %(report_code)s, %(frequency)s, %(hour)s, %(minute)s, %(weekday)s, %(day_of_month)s, %(days)s,
            %(agent_id)s, %(tenant_id)s, %(recipients)s, %(attach_csv)s, %(enabled)s, %(created_by)s) RETURNING *""",
        {**v, "created_by": _user(request)})
    return {"status": "success", "schedule": _serialize(rows[0])}


@router.put("/{schedule_id}")
async def update_schedule(schedule_id: int, request: Request):
    body = await request.json()
    v = _validate(body or {})
    rows = await asyncio.to_thread(_exec, """
        UPDATE report_schedules SET name=%(name)s, report_code=%(report_code)s, frequency=%(frequency)s, hour=%(hour)s,
            minute=%(minute)s, weekday=%(weekday)s, day_of_month=%(day_of_month)s, days=%(days)s, agent_id=%(agent_id)s,
            tenant_id=%(tenant_id)s, recipients=%(recipients)s, attach_csv=%(attach_csv)s, enabled=%(enabled)s
        WHERE id=%(id)s RETURNING *""", {**v, "id": schedule_id})
    if not rows:
        raise HTTPException(404, "Agendamento não encontrado.")
    return {"status": "success", "schedule": _serialize(rows[0])}


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: int):
    await asyncio.to_thread(_exec, "DELETE FROM report_schedules WHERE id=%s", (schedule_id,), False)
    return {"status": "success"}


@router.post("/{schedule_id}/run")
async def run_schedule_now(schedule_id: int):
    rows = await asyncio.to_thread(_exec, "SELECT * FROM report_schedules WHERE id=%s", (schedule_id,))
    if not rows:
        raise HTTPException(404, "Agendamento não encontrado.")
    res = await asyncio.to_thread(_run_and_record, rows[0])
    code = 200 if res.get("status") == "sent" else 502
    return JSONResponse({"status": "success" if code == 200 else "error", **res}, status_code=code)
