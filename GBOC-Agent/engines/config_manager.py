#!/usr/bin/env python3
"""
GBOC 13.2.0 - Configuration Manager Engine
Export/import entire system configuration (tasks, repositories, settings, schedules, policies).
Supports JSON/YAML formats, versioned snapshots, diff between configs.
"""

import logging
import os
import json
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


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


def _execute_returning(sql: str, params: tuple = ()):
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else None


def ensure_tables():
    """Create config snapshots table if not exists."""
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS config_snapshots (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                config_data JSONB NOT NULL,
                config_hash TEXT NOT NULL,
                version TEXT,
                created_by TEXT DEFAULT 'system',
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()


class _Enc(json.JSONEncoder):
    """JSON encoder that handles datetime and Decimal."""
    def default(self, o):
        from decimal import Decimal
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        return super().default(o)


# ─── Export ───────────────────────────────────────────────────────

def export_config(include_sensitive: bool = False) -> Dict[str, Any]:
    """Export the full system configuration as a dictionary."""
    from shared_core import GBOC_VERSION

    config = {
        '_meta': {
            'gboc_version': GBOC_VERSION,
            'exported_at': datetime.now().isoformat(),
            'format_version': '1.1'
        },
        'repositories': [],
        'tasks': [],
        'settings': {},
        'smtp': None,
        'report_schedules': [],
        'notification_channels': [],
        'replication_policies': [],
    }

    # Repositories (schema real)
    repos = _query("SELECT id, name, engine, type, path, config, created_at FROM repositories")
    for r in repos:
        repo_data = {
            'name': r.get('name'),
            'engine': r.get('engine'),
            'repo_type': r.get('type'),
            'path': r.get('path'),
            'config': r.get('config'),
        }
        if not include_sensitive and isinstance(repo_data.get('config'), dict):
            for key in ('password', 'secret_key', 'access_key', 'token', 'aws_secret_key', 'b2_account_key'):
                if key in repo_data['config']:
                    repo_data['config'][key] = '***REDACTED***'
        config['repositories'].append(repo_data)

    # Tasks (schema real)
    tasks = _query("""
        SELECT id, name, engine, repository_id, source_paths,
               schedule_enabled, schedule_cron, enabled,
               retry_max_attempts, retention_days
        FROM tasks
    """)
    for t in tasks:
        config['tasks'].append({
            'name': t.get('name'),
            'engine': t.get('engine'),
            'repository_id': t.get('repository_id'),
            'source_paths': t.get('source_paths'),
            'schedule_enabled': t.get('schedule_enabled'),
            'schedule_cron': t.get('schedule_cron'),
            'enabled': t.get('enabled'),
            'retry_max_attempts': t.get('retry_max_attempts'),
            'retention_days': t.get('retention_days'),
        })

    # Settings
    settings_rows = _query("SELECT key, value FROM settings")
    for s in settings_rows:
        try:
            config['settings'][s['key']] = json.loads(s['value'])
        except (json.JSONDecodeError, TypeError):
            config['settings'][s['key']] = s['value']

    # SMTP config (resiliente)
    try:
        smtp = _query("SELECT * FROM smtp_config WHERE id = 1")
        if smtp:
            smtp_data = smtp[0]
            if not include_sensitive:
                smtp_data.pop('password', None)
            config['smtp'] = smtp_data
    except Exception:
        config['smtp'] = None

    # Report schedules
    try:
        schedules = _query("SELECT name, report_type, format, period_days, cron_expression, email_to, enabled FROM report_schedules")
        config['report_schedules'] = schedules
    except Exception:
        pass

    # Notification channels
    try:
        channels = _query("SELECT name, channel_type, config, enabled, events FROM notification_channels")
        for ch in channels:
            if not include_sensitive and isinstance(ch.get('config'), dict):
                for key in ('bot_token', 'webhook_url'):
                    if key in ch['config']:
                        ch['config'][key] = '***REDACTED***'
        config['notification_channels'] = channels
    except Exception:
        pass

    # Replication policies
    try:
        policies = _query("SELECT name, source_repo_id, target_repo_id, enabled, schedule_cron, verify_after_copy FROM replication_policies")
        config['replication_policies'] = policies
    except Exception:
        pass

    return config


def save_snapshot(name: str, description: str = "", created_by: str = "system") -> Dict:
    """Export current config and save as a versioned snapshot."""
    ensure_tables()
    config_data = export_config(include_sensitive=False)
    config_json = json.dumps(config_data, cls=_Enc, sort_keys=True)
    config_hash = hashlib.sha256(config_json.encode()).hexdigest()[:16]

    from shared_core import GBOC_VERSION
    snap_id = _execute_returning("""
        INSERT INTO config_snapshots (name, description, config_data, config_hash, version, created_by)
        VALUES (%s, %s, %s::jsonb, %s, %s, %s) RETURNING id
    """, (name, description, config_json, config_hash, GBOC_VERSION, created_by))

    return {
        'id': snap_id,
        'name': name,
        'config_hash': config_hash,
        'version': GBOC_VERSION,
        'created_at': datetime.now().isoformat()
    }


def list_snapshots() -> List[Dict]:
    ensure_tables()
    return _query("""
        SELECT id, name, description, config_hash, version, created_by, created_at
        FROM config_snapshots ORDER BY created_at DESC
    """)


def get_snapshot(snapshot_id: int) -> Optional[Dict]:
    ensure_tables()
    row = _query("SELECT * FROM config_snapshots WHERE id = %s", (snapshot_id,))
    return row[0] if row else None


def delete_snapshot(snapshot_id: int):
    ensure_tables()
    _execute("DELETE FROM config_snapshots WHERE id = %s", (snapshot_id,))


# ─── Import ───────────────────────────────────────────────────────

def import_config(config_data: Dict, dry_run: bool = True) -> Dict[str, Any]:
    """Import a configuration. 
    dry_run=True: only validate and show changes, don't apply.
    dry_run=False: apply changes to the database.
    """
    report = {
        'dry_run': dry_run,
        'repositories': {'add': 0, 'update': 0, 'skip': 0},
        'tasks': {'add': 0, 'update': 0, 'skip': 0},
        'settings': {'update': 0},
        'report_schedules': {'add': 0},
        'warnings': [],
        'errors': []
    }

    if not dry_run:
        core = _get_core()
        conn = core.get_db_connection().__enter__()
        cur = conn.cursor()

    try:
        # Repositories
        for repo in config_data.get('repositories', []):
            existing = _query("SELECT id FROM repositories WHERE name = %s", (repo.get('name', ''),))
            if existing:
                report['repositories']['skip'] += 1
                report['warnings'].append(f"Repository '{repo.get('name')}' already exists, skipping")
            else:
                report['repositories']['add'] += 1
                if not dry_run:
                    cur.execute("""
                        INSERT INTO repositories (name, engine, repo_type, path, config, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """, (repo.get('name'), repo.get('engine'), repo.get('repo_type'),
                          repo.get('path'), json.dumps(repo.get('config', {}))))

        # Tasks
        for task in config_data.get('tasks', []):
            existing = _query("SELECT id FROM tasks WHERE name = %s", (task.get('name', ''),))
            if existing:
                report['tasks']['skip'] += 1
                report['warnings'].append(f"Task '{task.get('name')}' already exists, skipping")
            else:
                report['tasks']['add'] += 1
                if not dry_run:
                    cur.execute("""
                        INSERT INTO tasks (name, engine, source_path, schedule, schedule_type,
                                           schedule_interval, enabled, max_retries, retention_days, priority,
                                           created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """, (task.get('name'), task.get('engine'), task.get('source_path'),
                          task.get('schedule'), task.get('schedule_type'),
                          task.get('schedule_interval'), task.get('enabled', True),
                          task.get('max_retries', 3), task.get('retention_days', 30),
                          task.get('priority', 0)))

        # Settings
        for key, value in config_data.get('settings', {}).items():
            report['settings']['update'] += 1
            if not dry_run:
                val_str = json.dumps(value) if not isinstance(value, str) else value
                cur.execute("""
                    INSERT INTO settings (key, value) VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = %s
                """, (key, val_str, val_str))

        # Report schedules
        for sched in config_data.get('report_schedules', []):
            report['report_schedules']['add'] += 1
            if not dry_run:
                cur.execute("""
                    INSERT INTO report_schedules (name, report_type, format, period_days, cron_expression, email_to, enabled)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (sched.get('name'), sched.get('report_type'), sched.get('format', 'html'),
                      sched.get('period_days', 30), sched.get('cron_expression', '0 8 * * 1'),
                      sched.get('email_to', ''), sched.get('enabled', True)))

        if not dry_run:
            conn.commit()
            conn.__exit__(None, None, None)

    except Exception as e:
        report['errors'].append(str(e))
        if not dry_run:
            try:
                conn.rollback()
                conn.__exit__(None, None, None)
            except Exception:
                pass

    return report


# ─── Diff ─────────────────────────────────────────────────────────

def diff_configs(config_a: Dict, config_b: Dict) -> Dict[str, Any]:
    """Compare two config exports and show differences."""
    diffs = {
        'repositories': {'added': [], 'removed': [], 'changed': []},
        'tasks': {'added': [], 'removed': [], 'changed': []},
        'settings': {'added': [], 'removed': [], 'changed': []},
    }

    # Compare repositories by name
    names_a = {r.get('name'): r for r in config_a.get('repositories', [])}
    names_b = {r.get('name'): r for r in config_b.get('repositories', [])}
    diffs['repositories']['added'] = [n for n in names_b if n not in names_a]
    diffs['repositories']['removed'] = [n for n in names_a if n not in names_b]
    for name in set(names_a) & set(names_b):
        if json.dumps(names_a[name], sort_keys=True, cls=_Enc) != json.dumps(names_b[name], sort_keys=True, cls=_Enc):
            diffs['repositories']['changed'].append(name)

    # Compare tasks by name
    tnames_a = {t.get('name'): t for t in config_a.get('tasks', [])}
    tnames_b = {t.get('name'): t for t in config_b.get('tasks', [])}
    diffs['tasks']['added'] = [n for n in tnames_b if n not in tnames_a]
    diffs['tasks']['removed'] = [n for n in tnames_a if n not in tnames_b]
    for name in set(tnames_a) & set(tnames_b):
        if json.dumps(tnames_a[name], sort_keys=True, cls=_Enc) != json.dumps(tnames_b[name], sort_keys=True, cls=_Enc):
            diffs['tasks']['changed'].append(name)

    # Compare settings by key
    sa = config_a.get('settings', {})
    sb = config_b.get('settings', {})
    diffs['settings']['added'] = [k for k in sb if k not in sa]
    diffs['settings']['removed'] = [k for k in sa if k not in sb]
    for k in set(sa) & set(sb):
        if json.dumps(sa[k], sort_keys=True, cls=_Enc) != json.dumps(sb[k], sort_keys=True, cls=_Enc):
            diffs['settings']['changed'].append(k)

    # Summary
    total_changes = sum(
        len(v['added']) + len(v['removed']) + len(v['changed'])
        for v in diffs.values()
    )
    diffs['summary'] = {
        'total_changes': total_changes,
        'is_identical': total_changes == 0
    }

    return diffs

