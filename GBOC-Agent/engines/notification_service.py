#!/usr/bin/env python3
"""
GBOC Agent - Notification Service
Centralized notification system: email (SMTP), webhook, and database alerts.
Called from task_manager on backup completion/failure.
"""

import logging
import json
import smtplib
from datetime import datetime
from typing import Dict, Optional, List
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2)


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


def _load_smtp_config() -> Optional[Dict]:
    try:
        core = _get_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT server, port, username, password, use_tls, from_email, from_name FROM smtp_config WHERE id = 1")
            row = cur.fetchone()
            if row:
                return {
                    'server': row[0], 'port': row[1], 'username': row[2],
                    'password': row[3], 'use_tls': row[4], 'from_email': row[5], 'from_name': row[6]
                }
    except Exception as e:
        logger.debug(f"No SMTP config available: {e}")
    return None


def _load_notification_settings() -> Dict:
    try:
        core = _get_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key = 'notification_settings'")
            row = cur.fetchone()
            if row:
                return json.loads(row[0])
    except Exception:
        pass
    return {
        'notify_enabled': True,
        'notify_failure': True,
        'notify_success': False,
        'email_enabled': False,
        'email_to': '',
        'email_backup_failure': True,
        'email_backup_success': False,
        'webhook_enabled': False,
        'webhook_url': ''
    }


def _build_failure_email_html(task_name, error_msg, execution_id, engine, duration_seconds=0):
    now = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    dur = f"{duration_seconds // 60}m {duration_seconds % 60}s" if duration_seconds else "N/A"
    return f"""<html><body style="font-family:'Segoe UI',Tahoma,sans-serif;margin:0;padding:20px;background:#1a1a2e;color:#e0e0e0;">
<div style="max-width:600px;margin:0 auto;background:#16213e;border-radius:12px;overflow:hidden;border:1px solid #2a2a4a;">
<div style="background:linear-gradient(135deg,#e53e3e,#c53030);padding:20px 24px;color:white;">
<h2 style="margin:0;font-size:1.2em;">⚠️ Falha no Backup — GBOC Agent</h2></div>
<div style="padding:24px;">
<table style="width:100%;border-collapse:collapse;">
<tr><td style="padding:8px 0;color:#a0aec0;width:130px;">Tarefa:</td><td style="padding:8px 0;color:#fff;font-weight:600;">{task_name}</td></tr>
<tr><td style="padding:8px 0;color:#a0aec0;">Motor:</td><td style="padding:8px 0;color:#fff;">{engine}</td></tr>
<tr><td style="padding:8px 0;color:#a0aec0;">Execução ID:</td><td style="padding:8px 0;color:#fff;">#{execution_id}</td></tr>
<tr><td style="padding:8px 0;color:#a0aec0;">Duração:</td><td style="padding:8px 0;color:#fff;">{dur}</td></tr>
<tr><td style="padding:8px 0;color:#a0aec0;">Data/Hora:</td><td style="padding:8px 0;color:#fff;">{now}</td></tr>
</table>
<div style="margin-top:16px;padding:12px 16px;background:rgba(245,101,101,.1);border:1px solid rgba(245,101,101,.3);border-radius:8px;">
<strong style="color:#f56565;">Erro:</strong>
<p style="color:#feb2b2;margin:8px 0 0;font-size:0.9em;white-space:pre-wrap;">{error_msg}</p></div>
<p style="margin-top:20px;color:#a0aec0;font-size:0.8em;">Acesse o painel GBOC para mais detalhes.</p></div>
<div style="padding:12px 24px;background:#0f1629;text-align:center;color:#4a5568;font-size:0.75em;">GBOC Backup System — Notificação Automática</div>
</div></body></html>"""


def _build_success_email_html(task_name, execution_id, engine, files_count=0, bytes_count=0, duration_seconds=0):
    now = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    dur = f"{duration_seconds // 60}m {duration_seconds % 60}s" if duration_seconds else "N/A"
    def fmt(b):
        if b >= 1073741824: return f"{b/1073741824:.1f} GB"
        if b >= 1048576: return f"{b/1048576:.1f} MB"
        if b >= 1024: return f"{b/1024:.1f} KB"
        return f"{b} B"
    return f"""<html><body style="font-family:'Segoe UI',Tahoma,sans-serif;margin:0;padding:20px;background:#1a1a2e;color:#e0e0e0;">
<div style="max-width:600px;margin:0 auto;background:#16213e;border-radius:12px;overflow:hidden;border:1px solid #2a2a4a;">
<div style="background:linear-gradient(135deg,#38a169,#2f855a);padding:20px 24px;color:white;">
<h2 style="margin:0;font-size:1.2em;">✅ Backup Concluído — GBOC Agent</h2></div>
<div style="padding:24px;">
<table style="width:100%;border-collapse:collapse;">
<tr><td style="padding:8px 0;color:#a0aec0;width:130px;">Tarefa:</td><td style="padding:8px 0;color:#fff;font-weight:600;">{task_name}</td></tr>
<tr><td style="padding:8px 0;color:#a0aec0;">Motor:</td><td style="padding:8px 0;color:#fff;">{engine}</td></tr>
<tr><td style="padding:8px 0;color:#a0aec0;">Arquivos:</td><td style="padding:8px 0;color:#fff;">{files_count:,}</td></tr>
<tr><td style="padding:8px 0;color:#a0aec0;">Tamanho:</td><td style="padding:8px 0;color:#fff;">{fmt(bytes_count)}</td></tr>
<tr><td style="padding:8px 0;color:#a0aec0;">Duração:</td><td style="padding:8px 0;color:#fff;">{dur}</td></tr>
<tr><td style="padding:8px 0;color:#a0aec0;">Data/Hora:</td><td style="padding:8px 0;color:#fff;">{now}</td></tr>
</table></div>
<div style="padding:12px 24px;background:#0f1629;text-align:center;color:#4a5568;font-size:0.75em;">GBOC Backup System — Notificação Automática</div>
</div></body></html>"""


def _send_email_sync(smtp_config, to_emails, subject, html_body):
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = f"{smtp_config['from_name']} <{smtp_config['from_email']}>"
        msg['To'] = ', '.join(to_emails)
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body, 'html'))
        if smtp_config.get('use_tls', True):
            s = smtplib.SMTP(smtp_config['server'], smtp_config['port'], timeout=30)
            s.ehlo()
            s.starttls()
        else:
            s = smtplib.SMTP_SSL(smtp_config['server'], smtp_config['port'], timeout=30)
        s.login(smtp_config['username'], smtp_config['password'])
        s.sendmail(smtp_config['from_email'], to_emails, msg.as_string())
        s.quit()
        logger.info(f"✅ Email notification sent to {', '.join(to_emails)}")
    except Exception as e:
        logger.error(f"❌ Failed to send email: {e}")


def _send_webhook_sync(url, payload):
    try:
        import urllib.request
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            logger.info(f"✅ Webhook sent: {resp.status}")
    except Exception as e:
        logger.error(f"❌ Webhook failed: {e}")


def notify_backup_completed(task_name, execution_id, engine, snapshot_id=None,
                            files_count=0, bytes_count=0, duration_seconds=0):
    try:
        settings = _load_notification_settings()
        if not settings.get('notify_enabled', True) or not settings.get('notify_success', False):
            return
        if settings.get('email_enabled') and settings.get('email_backup_success'):
            smtp_config = _load_smtp_config()
            to_emails = [e.strip() for e in settings.get('email_to', '').split(',') if e.strip()]
            if smtp_config and to_emails:
                subject = f"✅ Backup Concluído: {task_name}"
                html = _build_success_email_html(task_name, execution_id, engine, files_count, bytes_count, duration_seconds)
                _executor.submit(_send_email_sync, smtp_config, to_emails, subject, html)
        if settings.get('webhook_enabled') and settings.get('webhook_url'):
            payload = {'event': 'backup_success', 'task_name': task_name, 'execution_id': execution_id,
                       'engine': engine, 'snapshot_id': snapshot_id, 'timestamp': datetime.now().isoformat()}
            _executor.submit(_send_webhook_sync, settings['webhook_url'], payload)
        # Broadcast to notification channels (Slack, Teams, Discord, Telegram, etc.)
        try:
            from engines.notification_channels import broadcast
            broadcast('backup_success', {
                'title': f'Backup Completed: {task_name}',
                'message': f'Backup completed successfully. Files: {files_count:,}, Duration: {duration_seconds}s',
                'task_name': task_name, 'engine': engine, 'execution_id': execution_id
            })
        except Exception as ch_err:
            logger.debug(f"Channels broadcast skipped: {ch_err}")
    except Exception as e:
        logger.error(f"Error in notify_backup_completed: {e}")


def notify_backup_failed(task_name, execution_id, engine, error_message, duration_seconds=0):
    try:
        settings = _load_notification_settings()
        if not settings.get('notify_enabled', True):
            return
        # Record alert in DB
        try:
            core = _get_core()
            with core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO alerts (type, severity, title, message, source, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, ('backup_failure', 'critical', f'Falha no Backup: {task_name}',
                      error_message[:500], engine, datetime.now().isoformat()))
                conn.commit()
        except Exception as e:
            logger.debug(f"Could not record alert: {e}")
        # Email
        if settings.get('email_enabled') and settings.get('email_backup_failure', True):
            smtp_config = _load_smtp_config()
            to_emails = [e.strip() for e in settings.get('email_to', '').split(',') if e.strip()]
            if smtp_config and to_emails:
                subject = f"⚠️ Falha no Backup: {task_name}"
                html = _build_failure_email_html(task_name, error_message, execution_id, engine, duration_seconds)
                _executor.submit(_send_email_sync, smtp_config, to_emails, subject, html)
        # Webhook
        if settings.get('webhook_enabled') and settings.get('webhook_url'):
            payload = {'event': 'backup_failed', 'task_name': task_name, 'execution_id': execution_id,
                       'engine': engine, 'error': error_message, 'timestamp': datetime.now().isoformat()}
            _executor.submit(_send_webhook_sync, settings['webhook_url'], payload)
        # Broadcast to notification channels (Slack, Teams, Discord, Telegram, etc.)
        try:
            from engines.notification_channels import broadcast
            broadcast('backup_failed', {
                'title': f'Backup Failed: {task_name}',
                'message': f'Error: {error_message[:200]}',
                'task_name': task_name, 'engine': engine, 'execution_id': execution_id
            })
        except Exception as ch_err:
            logger.debug(f"Channels broadcast skipped: {ch_err}")
    except Exception as e:
        logger.error(f"Error in notify_backup_failed: {e}")
