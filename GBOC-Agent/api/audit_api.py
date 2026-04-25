#!/usr/bin/env python3
"""
GBOC 11.7c - Audit Trail API
Records all significant actions: who, what, when, where, result.
Immutable audit entries for compliance (SOX, HIPAA, ISO 27001).
Decorator for automatic audit logging on API endpoints.
"""

import logging
import json
import functools
from datetime import datetime
from typing import Dict, Any, List, Optional
from decimal import Decimal
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["Audit"])


class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        return super().default(o)


def _clean(obj):
    return json.loads(json.dumps(obj, cls=_Enc))


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


def _execute(sql: str, params: tuple = ()):
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()


def ensure_tables():
    """Create audit_log table if not exists."""
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER,
                username TEXT,
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                resource_name TEXT,
                detail JSONB DEFAULT '{}',
                ip_address TEXT,
                user_agent TEXT,
                result TEXT DEFAULT 'success',
                error_message TEXT
            );
        """)
        # Index for fast queries
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log (timestamp DESC);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log (action);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log (username);
        """)
        conn.commit()


# ─── Core logging function ────────────────────────────────────────

def record_audit(action: str, resource_type: str = None, resource_id: str = None,
                 resource_name: str = None, detail: Dict = None,
                 username: str = None, user_id: int = None,
                 ip_address: str = None, user_agent: str = None,
                 result: str = "success", error_message: str = None):
    """Record an audit entry. Called from API endpoints or engines."""
    ensure_tables()
    try:
        _execute("""
            INSERT INTO audit_log (user_id, username, action, resource_type, resource_id,
                                   resource_name, detail, ip_address, user_agent, result, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
        """, (user_id, username, action, resource_type, str(resource_id) if resource_id else None,
              resource_name, json.dumps(detail or {}, cls=_Enc),
              ip_address, user_agent, result, error_message))
    except Exception as e:
        logger.error(f"Failed to record audit: {e}")


def _extract_user(request: Request) -> Dict:
    """Extract user info from request (auth token)."""
    info = {'username': 'anonymous', 'user_id': None, 'ip': None, 'ua': None}
    try:
        info['ip'] = request.client.host if request.client else None
        info['ua'] = request.headers.get('user-agent', '')[:200]
        # Try to get authenticated user from token
        auth_header = request.headers.get('authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            from api.auth import _validate_token
            user = _validate_token(token)
            if user:
                info['username'] = user.get('username', 'unknown')
                info['user_id'] = user.get('id')
    except Exception:
        pass
    return info


# ─── API endpoints ────────────────────────────────────────────────

@router.get("/")
async def get_audit_log(
    limit: int = 50,
    offset: int = 0,
    action: Optional[str] = None,
    username: Optional[str] = None,
    resource_type: Optional[str] = None,
    result: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None
):
    """Query audit log with filters."""
    ensure_tables()
    conditions = []
    params = []

    if action:
        conditions.append("action = %s")
        params.append(action)
    if username:
        conditions.append("username = %s")
        params.append(username)
    if resource_type:
        conditions.append("resource_type = %s")
        params.append(resource_type)
    if result:
        conditions.append("result = %s")
        params.append(result)
    if date_from:
        conditions.append("timestamp >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        conditions.append("timestamp <= %s::timestamptz")
        params.append(date_to)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([limit, offset])

    entries = _query(f"""
        SELECT id, timestamp, user_id, username, action, resource_type,
               resource_id, resource_name, detail, ip_address, result, error_message
        FROM audit_log {where}
        ORDER BY timestamp DESC
        LIMIT %s OFFSET %s
    """, tuple(params))

    # Count total
    count_params = params[:-2]  # Remove limit/offset
    total_row = _query(f"SELECT COUNT(*) AS cnt FROM audit_log {where}", tuple(count_params))
    total = total_row[0]['cnt'] if total_row else 0

    return {
        "entries": _clean(entries),
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/summary")
async def audit_summary(days: int = 30):
    """Get a summary of audit activity for the last N days."""
    ensure_tables()

    # Actions breakdown
    actions = _query("""
        SELECT action, COUNT(*) AS cnt
        FROM audit_log
        WHERE timestamp >= NOW() - (%s || ' days')::INTERVAL
        GROUP BY action ORDER BY cnt DESC
    """, (str(days),))

    # Users breakdown
    users = _query("""
        SELECT username, COUNT(*) AS cnt
        FROM audit_log
        WHERE timestamp >= NOW() - (%s || ' days')::INTERVAL
        GROUP BY username ORDER BY cnt DESC LIMIT 20
    """, (str(days),))

    # Results breakdown
    results = _query("""
        SELECT result, COUNT(*) AS cnt
        FROM audit_log
        WHERE timestamp >= NOW() - (%s || ' days')::INTERVAL
        GROUP BY result
    """, (str(days),))

    # Daily activity
    daily = _query("""
        SELECT DATE(timestamp) AS day, COUNT(*) AS cnt
        FROM audit_log
        WHERE timestamp >= NOW() - (%s || ' days')::INTERVAL
        GROUP BY DATE(timestamp) ORDER BY day
    """, (str(days),))

    # Failed actions (security interest)
    failed = _query("""
        SELECT action, username, ip_address, error_message, timestamp
        FROM audit_log
        WHERE result = 'failure' AND timestamp >= NOW() - (%s || ' days')::INTERVAL
        ORDER BY timestamp DESC LIMIT 20
    """, (str(days),))

    return _clean({
        'period_days': days,
        'actions': actions,
        'users': users,
        'results': results,
        'daily_activity': daily,
        'recent_failures': failed
    })


@router.get("/export")
async def export_audit(days: int = 90, format: str = "json"):
    """Export audit log entries for compliance."""
    ensure_tables()
    entries = _query("""
        SELECT * FROM audit_log
        WHERE timestamp >= NOW() - (%s || ' days')::INTERVAL
        ORDER BY timestamp
    """, (str(days),))

    if format == "csv":
        import csv
        import io
        from fastapi.responses import StreamingResponse
        output = io.StringIO()
        if entries:
            writer = csv.DictWriter(output, fieldnames=entries[0].keys())
            writer.writeheader()
            for e in entries:
                # Serialize complex fields
                if isinstance(e.get('detail'), dict):
                    e['detail'] = json.dumps(e['detail'])
                if isinstance(e.get('timestamp'), datetime):
                    e['timestamp'] = e['timestamp'].isoformat()
                writer.writerow(e)
        content = output.getvalue()
        return StreamingResponse(
            io.BytesIO(content.encode('utf-8')),
            media_type='text/csv',
            headers={'Content-Disposition': f'attachment; filename="audit_log_{days}d.csv"'}
        )
    else:
        return {"entries": _clean(entries), "total": len(entries), "period_days": days}


@router.get("/actions")
async def list_audit_actions():
    """List all distinct actions recorded in the audit log."""
    ensure_tables()
    actions = _query("SELECT DISTINCT action FROM audit_log ORDER BY action")
    return {"actions": [a['action'] for a in actions]}


# ─── Convenience functions for other modules ──────────────────────

def audit_login(username: str, ip: str, success: bool):
    record_audit(
        action='auth.login', resource_type='user', resource_name=username,
        username=username, ip_address=ip,
        result='success' if success else 'failure',
        error_message=None if success else 'Invalid credentials'
    )


def audit_task_action(action: str, task_id: int, task_name: str, username: str = 'system', detail: Dict = None):
    record_audit(
        action=f'task.{action}', resource_type='task', resource_id=str(task_id),
        resource_name=task_name, username=username, detail=detail
    )


def audit_repo_action(action: str, repo_id: int, repo_name: str, username: str = 'system', detail: Dict = None):
    record_audit(
        action=f'repository.{action}', resource_type='repository', resource_id=str(repo_id),
        resource_name=repo_name, username=username, detail=detail
    )


def audit_config_action(action: str, username: str = 'system', detail: Dict = None):
    record_audit(
        action=f'config.{action}', resource_type='config',
        username=username, detail=detail
    )


def audit_security_event(event: str, username: str = None, ip: str = None, detail: Dict = None):
    record_audit(
        action=f'security.{event}', resource_type='security',
        username=username or 'system', ip_address=ip, detail=detail
    )

