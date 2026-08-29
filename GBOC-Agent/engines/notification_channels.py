#!/usr/bin/env python3
"""
GBOC 13.2.0 - Notification Channels Engine
Multi-channel notification delivery: Slack, Teams, Discord, Telegram, custom webhooks.
Each channel has its own payload format and delivery logic.
"""

import logging
import json
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=4)


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


def _query(sql: str, params: tuple = ()) -> List[Dict]:
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _query_one(sql: str, params: tuple = ()) -> Optional[Dict]:
    rows = _query(sql, params)
    return rows[0] if rows else None


def _execute(sql: str, params: tuple = ()):
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()


def _execute_returning(sql: str, params: tuple = ()):
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else None


def ensure_tables():
    """Create notification channels tables if not exists."""
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_channels (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                channel_type TEXT NOT NULL,
                config JSONB NOT NULL DEFAULT '{}',
                enabled BOOLEAN DEFAULT TRUE,
                events JSONB DEFAULT '["backup_failed","ransomware_alert"]',
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_history (
                id SERIAL PRIMARY KEY,
                channel_id INTEGER REFERENCES notification_channels(id) ON DELETE SET NULL,
                channel_type TEXT,
                event TEXT,
                status TEXT DEFAULT 'sent',
                payload JSONB DEFAULT '{}',
                response_code INTEGER,
                error_message TEXT,
                sent_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()


# ─── CRUD ─────────────────────────────────────────────────────────

def list_channels() -> List[Dict]:
    ensure_tables()
    return _query("SELECT id, name, channel_type, config, enabled, events, created_at, updated_at FROM notification_channels ORDER BY id")


def get_channel(channel_id: int) -> Optional[Dict]:
    ensure_tables()
    return _query_one("SELECT * FROM notification_channels WHERE id = %s", (channel_id,))


def create_channel(data: Dict) -> Dict:
    ensure_tables()
    cid = _execute_returning("""
        INSERT INTO notification_channels (name, channel_type, config, enabled, events)
        VALUES (%s, %s, %s::jsonb, %s, %s::jsonb) RETURNING id
    """, (data['name'], data['channel_type'],
          json.dumps(data.get('config', {})),
          data.get('enabled', True),
          json.dumps(data.get('events', ['backup_failed', 'ransomware_alert']))))
    return get_channel(cid)


def update_channel(channel_id: int, data: Dict) -> Dict:
    ensure_tables()
    fields = []
    params = []
    for key in ('name', 'channel_type', 'enabled'):
        if key in data and data[key] is not None:
            fields.append(f"{key} = %s")
            params.append(data[key])
    if 'config' in data and data['config'] is not None:
        fields.append("config = %s::jsonb")
        params.append(json.dumps(data['config']))
    if 'events' in data and data['events'] is not None:
        fields.append("events = %s::jsonb")
        params.append(json.dumps(data['events']))
    if fields:
        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(channel_id)
        _execute(f"UPDATE notification_channels SET {', '.join(fields)} WHERE id = %s", tuple(params))
    return get_channel(channel_id)


def delete_channel(channel_id: int):
    ensure_tables()
    _execute("DELETE FROM notification_channels WHERE id = %s", (channel_id,))


# ─── Delivery engines ─────────────────────────────────────────────

def _http_post(url: str, payload: str, headers: Dict[str, str], timeout: int = 30) -> Dict:
    """Generic HTTP POST helper."""
    try:
        data = payload.encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {'status': 'sent', 'code': resp.status}
    except urllib.error.HTTPError as e:
        return {'status': 'error', 'code': e.code, 'error': str(e)}
    except Exception as e:
        return {'status': 'error', 'code': 0, 'error': str(e)}


def _build_slack_payload(event: str, data: Dict) -> str:
    """Build Slack Block Kit message."""
    title = data.get('title', event)
    message = data.get('message', '')
    color = '#e74c3c' if 'fail' in event or 'alert' in event else '#2ecc71'
    task = data.get('task_name', '')
    engine = data.get('engine', '')

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"GBOC: {title}", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": message}},
    ]
    if task or engine:
        fields = []
        if task:
            fields.append({"type": "mrkdwn", "text": f"*Task:* {task}"})
        if engine:
            fields.append({"type": "mrkdwn", "text": f"*Engine:* {engine}"})
        blocks.append({"type": "section", "fields": fields})

    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": f":clock1: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
    ]})

    return json.dumps({
        "attachments": [{"color": color, "blocks": blocks}]
    })


def _build_teams_payload(event: str, data: Dict) -> str:
    """Build Microsoft Teams Adaptive Card (webhook)."""
    title = data.get('title', event)
    message = data.get('message', '')
    color = 'attention' if 'fail' in event or 'alert' in event else 'good'

    facts = []
    if data.get('task_name'):
        facts.append({"title": "Task", "value": data['task_name']})
    if data.get('engine'):
        facts.append({"title": "Engine", "value": data['engine']})
    facts.append({"title": "Time", "value": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

    card = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {"type": "TextBlock", "text": f"GBOC: {title}", "weight": "bolder", "size": "medium", "color": color},
                    {"type": "TextBlock", "text": message, "wrap": True},
                    {"type": "FactSet", "facts": facts}
                ]
            }
        }]
    }
    return json.dumps(card)


def _build_discord_payload(event: str, data: Dict) -> str:
    """Build Discord embed message."""
    title = data.get('title', event)
    message = data.get('message', '')
    color = 0xe74c3c if 'fail' in event or 'alert' in event else 0x2ecc71

    embed = {
        "title": f"GBOC: {title}",
        "description": message,
        "color": color,
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "GBOC Backup System"},
        "fields": []
    }
    if data.get('task_name'):
        embed['fields'].append({"name": "Task", "value": data['task_name'], "inline": True})
    if data.get('engine'):
        embed['fields'].append({"name": "Engine", "value": data['engine'], "inline": True})

    return json.dumps({"embeds": [embed]})


def _build_telegram_payload(event: str, data: Dict, chat_id: str) -> str:
    """Build Telegram Bot API message."""
    title = data.get('title', event)
    message = data.get('message', '')
    icon = '🚨' if 'fail' in event or 'alert' in event else '✅'

    text = f"{icon} *GBOC: {title}*\n\n{message}"
    if data.get('task_name'):
        text += f"\n*Task:* {data['task_name']}"
    if data.get('engine'):
        text += f"\n*Engine:* {data['engine']}"
    text += f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    return json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    })


def _build_generic_webhook_payload(event: str, data: Dict) -> str:
    """Build generic JSON webhook payload."""
    return json.dumps({
        "source": "gboc-agent",
        "event": event,
        "timestamp": datetime.now().isoformat(),
        "data": data
    })


# ─── Send to a single channel ─────────────────────────────────────

def send_to_channel(channel: Dict, event: str, data: Dict) -> Dict:
    """Send a notification to a specific channel. Returns delivery result."""
    ctype = channel.get('channel_type', 'webhook')
    config = channel.get('config', {})

    if ctype == 'slack':
        url = config.get('webhook_url', '')
        payload = _build_slack_payload(event, data)
        headers = {'Content-Type': 'application/json'}
    elif ctype == 'teams':
        url = config.get('webhook_url', '')
        payload = _build_teams_payload(event, data)
        headers = {'Content-Type': 'application/json'}
    elif ctype == 'discord':
        url = config.get('webhook_url', '')
        payload = _build_discord_payload(event, data)
        headers = {'Content-Type': 'application/json'}
    elif ctype == 'telegram':
        bot_token = config.get('bot_token', '')
        chat_id = config.get('chat_id', '')
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = _build_telegram_payload(event, data, chat_id)
        headers = {'Content-Type': 'application/json'}
    else:
        # Generic webhook
        url = config.get('webhook_url', config.get('url', ''))
        payload = _build_generic_webhook_payload(event, data)
        headers = config.get('headers', {'Content-Type': 'application/json'})

    if not url:
        return {'status': 'error', 'error': 'No URL configured'}

    result = _http_post(url, payload, headers)

    # Record in history
    try:
        _execute("""
            INSERT INTO notification_history (channel_id, channel_type, event, status, payload, response_code, error_message)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
        """, (channel.get('id'), ctype, event, result.get('status', 'unknown'),
              json.dumps({'event': event, 'data_keys': list(data.keys())}),
              result.get('code', 0), result.get('error')))
    except Exception as e:
        logger.debug(f"Could not record notification history: {e}")

    return result


# ─── Broadcast to all matching channels ───────────────────────────

def broadcast(event: str, data: Dict):
    """Send notification to all enabled channels that subscribe to this event type."""
    ensure_tables()
    channels = _query("SELECT * FROM notification_channels WHERE enabled = true")

    for ch in channels:
        events = ch.get('events', [])
        if isinstance(events, str):
            events = json.loads(events)
        # Check if channel subscribes to this event (or to 'all')
        if event in events or 'all' in events or '*' in events:
            _executor.submit(_safe_send, ch, event, data)


def _safe_send(channel, event, data):
    """Thread-safe send wrapper."""
    try:
        result = send_to_channel(channel, event, data)
        if result.get('status') == 'error':
            logger.warning(f"Notification to {channel.get('name')} failed: {result.get('error')}")
        else:
            logger.info(f"Notification sent to {channel.get('name')} ({channel.get('channel_type')})")
    except Exception as e:
        logger.error(f"Error sending to channel {channel.get('name')}: {e}")


def test_channel(channel_id: int) -> Dict:
    """Send a test notification to a channel."""
    ch = get_channel(channel_id)
    if not ch:
        return {'status': 'error', 'error': 'Channel not found'}

    test_data = {
        'title': 'Test Notification',
        'message': 'This is a test notification from GBOC Agent. If you see this, the channel is configured correctly!',
        'task_name': 'test_task',
        'engine': 'test_engine'
    }
    return send_to_channel(ch, 'test', test_data)


def get_history(limit: int = 50) -> List[Dict]:
    """Get notification delivery history."""
    ensure_tables()
    return _query("""
        SELECT nh.id, nh.channel_id, nc.name AS channel_name, nh.channel_type,
               nh.event, nh.status, nh.response_code, nh.error_message, nh.sent_at
        FROM notification_history nh
        LEFT JOIN notification_channels nc ON nc.id = nh.channel_id
        ORDER BY nh.sent_at DESC LIMIT %s
    """, (limit,))

