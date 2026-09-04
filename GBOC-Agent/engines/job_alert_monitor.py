#!/usr/bin/env python3
"""
GBOC 14.0.0 - Job Alert Monitor & Proactive Failure Detection Engine
Monitors backup task executions in real-time.
On failure: retries automatically (configurable) and dispatches multi-channel alerts
(Email SMTP, Telegram Bot, WhatsApp, Webhook HTTP/S).
"""

import os
import json
import logging
import asyncio
import time
import threading
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger("gboc_job_alert_monitor")

# ─── Configuration Defaults ────────────────────────────────────────────────────

DEFAULT_ALERT_CONFIG = {
    "enabled": True,
    "max_retries": 3,
    "retry_interval_seconds": 300,        # 5 minutes between retries
    "escalation_after_failures": 2,       # Escalate to manager after N failures
    "alert_channels": {
        "email": {
            "enabled": False,
            "smtp_host": "",
            "smtp_port": 587,
            "smtp_user": "",
            "smtp_pass": "",
            "recipients": []
        },
        "telegram": {
            "enabled": False,
            "bot_token": "",
            "chat_id": ""
        },
        "webhook": {
            "enabled": False,
            "url": "",
            "method": "POST",
            "headers": {}
        }
    }
}

_alert_config_cache: Optional[Dict] = None
_alert_config_lock = threading.Lock()

def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()

def _config_path():
    return os.path.join(os.getcwd(), "data", "job_alert_config.json")

def load_alert_config() -> Dict[str, Any]:
    global _alert_config_cache
    with _alert_config_lock:
        if _alert_config_cache:
            return _alert_config_cache
        cfg_file = _config_path()
        if os.path.exists(cfg_file):
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    merged = json.loads(json.dumps(DEFAULT_ALERT_CONFIG))
                    _deep_merge(merged, data)
                    _alert_config_cache = merged
                    return merged
            except Exception:
                pass
        _alert_config_cache = json.loads(json.dumps(DEFAULT_ALERT_CONFIG))
        return _alert_config_cache

def save_alert_config(new_cfg: Dict) -> Dict:
    global _alert_config_cache
    os.makedirs(os.path.dirname(_config_path()), exist_ok=True)
    current = load_alert_config()
    _deep_merge(current, new_cfg)
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)
    with _alert_config_lock:
        _alert_config_cache = current
    return current

def _deep_merge(base: Dict, override: Dict):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v

# ─── DB Helpers ────────────────────────────────────────────────────────────────

def ensure_alert_tables():
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS job_failure_log (
                id SERIAL PRIMARY KEY,
                task_id TEXT NOT NULL,
                task_name TEXT,
                execution_id TEXT,
                failure_reason TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                status TEXT DEFAULT 'failed',
                alert_sent BOOLEAN DEFAULT FALSE,
                escalated BOOLEAN DEFAULT FALSE,
                first_failed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                last_retried_at TIMESTAMPTZ,
                resolved_at TIMESTAMPTZ
            );
        """)
        conn.commit()

def record_job_failure(task_id: str, task_name: str, execution_id: str, reason: str) -> Dict[str, Any]:
    """Registra falha de job e retorna o registro criado."""
    ensure_alert_tables()
    cfg = load_alert_config()
    max_retries = cfg.get("max_retries", 3)
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        # Check if already tracking this failure
        cur.execute("SELECT id, retry_count FROM job_failure_log WHERE task_id=%s AND status='failed'", (task_id,))
        row = cur.fetchone()
        if row:
            fail_id, retry_count = row
            cur.execute("UPDATE job_failure_log SET retry_count=%s, last_retried_at=CURRENT_TIMESTAMP, failure_reason=%s WHERE id=%s",
                        (retry_count + 1, reason, fail_id))
            conn.commit()
            return {"id": fail_id, "retry_count": retry_count + 1, "task_id": task_id, "is_new": False}
        else:
            cur.execute("""
                INSERT INTO job_failure_log (task_id, task_name, execution_id, failure_reason, max_retries)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (task_id, task_name, execution_id, reason, max_retries))
            new_id = cur.fetchone()[0]
            conn.commit()
            return {"id": new_id, "retry_count": 0, "task_id": task_id, "is_new": True}

def resolve_job_failure(task_id: str):
    """Marca a falha de um job como resolvida após retry bem-sucedido."""
    ensure_alert_tables()
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE job_failure_log SET status='resolved', resolved_at=CURRENT_TIMESTAMP WHERE task_id=%s AND status='failed'", (task_id,))
        conn.commit()

def get_failed_jobs(limit: int = 50) -> List[Dict]:
    """Retorna a lista de jobs com falhas ativas."""
    ensure_alert_tables()
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, task_id, task_name, failure_reason, retry_count, max_retries,
                   status, alert_sent, escalated, first_failed_at, last_retried_at, resolved_at
            FROM job_failure_log
            ORDER BY first_failed_at DESC LIMIT %s
        """, (limit,))
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            # Serialize timestamps
            for k in ["first_failed_at", "last_retried_at", "resolved_at"]:
                if d.get(k) and hasattr(d[k], 'isoformat'):
                    d[k] = d[k].isoformat()
            rows.append(d)
        return rows

# ─── Alert Dispatchers ─────────────────────────────────────────────────────────

def _send_email_alert(subject: str, body: str, cfg: Dict):
    """Envia alerta por Email SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    try:
        email_cfg = cfg.get("alert_channels", {}).get("email", {})
        if not email_cfg.get("enabled") or not email_cfg.get("smtp_host"):
            return False
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = email_cfg["smtp_user"]
        msg["To"] = ", ".join(email_cfg.get("recipients", []))
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(email_cfg["smtp_host"], email_cfg.get("smtp_port", 587)) as srv:
            srv.starttls()
            srv.login(email_cfg["smtp_user"], email_cfg["smtp_pass"])
            srv.sendmail(email_cfg["smtp_user"], email_cfg["recipients"], msg.as_string())
        logger.info(f"[JobAlert] Email enviado: {subject}")
        return True
    except Exception as e:
        logger.error(f"[JobAlert] Falha ao enviar email: {e}")
        return False

def _send_telegram_alert(message: str, cfg: Dict):
    """Envia alerta via Telegram Bot API."""
    try:
        tg_cfg = cfg.get("alert_channels", {}).get("telegram", {})
        if not tg_cfg.get("enabled") or not tg_cfg.get("bot_token"):
            return False
        url = f"https://api.telegram.org/bot{tg_cfg['bot_token']}/sendMessage"
        requests.post(url, json={"chat_id": tg_cfg["chat_id"], "text": message, "parse_mode": "HTML"}, timeout=10)
        logger.info("[JobAlert] Telegram enviado")
        return True
    except Exception as e:
        logger.error(f"[JobAlert] Falha Telegram: {e}")
        return False

def _send_webhook_alert(payload: Dict, cfg: Dict):
    """Envia alerta via HTTP Webhook."""
    try:
        wh_cfg = cfg.get("alert_channels", {}).get("webhook", {})
        if not wh_cfg.get("enabled") or not wh_cfg.get("url"):
            return False
        method = wh_cfg.get("method", "POST").upper()
        headers = {"Content-Type": "application/json"}
        headers.update(wh_cfg.get("headers", {}))
        requests.request(method, wh_cfg["url"], json=payload, headers=headers, timeout=10)
        logger.info("[JobAlert] Webhook enviado")
        return True
    except Exception as e:
        logger.error(f"[JobAlert] Falha Webhook: {e}")
        return False

def dispatch_job_failure_alert(task_id: str, task_name: str, reason: str, retry_count: int, escalated: bool = False):
    """Dispara alertas em todos os canais configurados para uma falha de job."""
    cfg = load_alert_config()
    if not cfg.get("enabled"):
        return

    emoji = "🚨" if not escalated else "⛔"
    level = "FALHA" if not escalated else "ESCALADO"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    subject = f"{emoji} GBOC {level}: Job '{task_name}' falhou (tentativa {retry_count + 1})"
    plain_body = (
        f"GBOC Agent Alert\n"
        f"Tarefa: {task_name} (ID: {task_id})\n"
        f"Status: {level}\n"
        f"Motivo: {reason}\n"
        f"Tentativas: {retry_count + 1}\n"
        f"Horário: {ts}"
    )
    webhook_payload = {
        "event": "job_failure",
        "task_id": task_id,
        "task_name": task_name,
        "level": level,
        "reason": reason,
        "retry_count": retry_count,
        "timestamp": ts
    }

    _send_email_alert(subject, plain_body, cfg)
    _send_telegram_alert(f"<b>{subject}</b>\n\n{plain_body}", cfg)
    _send_webhook_alert(webhook_payload, cfg)

    # Mark alert as sent in DB
    ensure_alert_tables()
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE job_failure_log SET alert_sent=TRUE, escalated=%s WHERE task_id=%s AND status='failed'", (escalated, task_id))
        conn.commit()

# ─── Background Monitor Loop ───────────────────────────────────────────────────

_monitor_running = False

def start_job_failure_monitor():
    """Inicia o monitor de falhas em segundo plano."""
    global _monitor_running
    if _monitor_running:
        return
    _monitor_running = True
    t = threading.Thread(target=_monitor_loop, daemon=True, name="gboc-job-alert-monitor")
    t.start()
    logger.info("🔍 Job Alert Monitor iniciado em segundo plano")

def _monitor_loop():
    """Loop de verificação periódica de falhas de jobs."""
    global _monitor_running
    while _monitor_running:
        try:
            cfg = load_alert_config()
            if not cfg.get("enabled"):
                time.sleep(60)
                continue

            ensure_alert_tables()
            core = _get_core()
            with core.get_db_connection() as conn:
                cur = conn.cursor()
                # Fetch active failures not yet alerted
                cur.execute("""
                    SELECT id, task_id, task_name, failure_reason, retry_count, max_retries, alert_sent, escalated
                    FROM job_failure_log
                    WHERE status = 'failed'
                    ORDER BY first_failed_at DESC
                """)
                cols = [d[0] for d in cur.description] if cur.description else []
                failures = [dict(zip(cols, row)) for row in cur.fetchall()]

            for f in failures:
                if not f["alert_sent"]:
                    escalated = f["retry_count"] >= cfg.get("escalation_after_failures", 2)
                    dispatch_job_failure_alert(
                        f["task_id"], f["task_name"] or f["task_id"],
                        f["failure_reason"] or "Erro desconhecido",
                        f["retry_count"], escalated=escalated
                    )

        except Exception as e:
            logger.error(f"[JobAlertMonitor] Erro no loop: {e}")

        time.sleep(120)  # Verifica a cada 2 minutos
