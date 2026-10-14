#!/usr/bin/env python3
"""
GBOC 14.8.1 - Configuration Manager Engine
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

_TASK_RUNTIME_COLS = {'id', 'repository_id', 'status', 'created_at', 'updated_at', 'last_run', 'last_status'}
_REPO_SECRET_COLS = ('password', 'motor_password', 'cloud_password', 'encryption_password')
_SECRET_HINTS = ('password', 'secret', 'token', 'account_key', 'api_key')


# Próprios deste computador: a chave que assina as sessões de login e as preferências da recuperação automática
# (a chave de recuperação vai criptografada com a chave local, inútil em outra instalação)
_LOCAL_ONLY_SETTINGS = {'auth_secret_key', 'config_recovery'}


def _is_secret_col(col: str) -> bool:
    c = (col or '').lower()
    return any(h in c for h in _SECRET_HINTS)


def _export_repository(r: Dict[str, Any], include_secrets: bool) -> Dict[str, Any]:
    """Repositório sem segredos (arquivo de configuração) ou com eles (pacote de recuperação criptografado).
    A cópia criptografada local (secret_enc) nunca sai: depende da chave deste computador."""
    raw = r.get('config')
    try:
        cfg = json.loads(raw) if isinstance(raw, str) and raw else (raw or {})
    except (ValueError, TypeError):
        cfg = {}
    out = {'name': r.get('name'), 'type': r.get('type'), 'repo_type': r.get('type'), 'engine': r.get('engine'),
           'path': r.get('path'), 'enabled': r.get('enabled'),
           'config': {k: v for k, v in cfg.items() if k != 'secret_enc'}}
    if include_secrets:
        from engines import repo_secrets
        out['secrets'] = {
            'cloud_secret': repo_secrets.secret_from_config(cfg) or (r.get('cloud_password') or ''),
            **{c: r.get(c) for c in _REPO_SECRET_COLS if r.get(c)},
        }
    return out


def export_config(include_sensitive: bool = False, include_secrets: bool = False) -> Dict[str, Any]:
    """Export the full system configuration as a dictionary.
    include_secrets: inclui chaves e senhas dos repositórios — SÓ para o pacote de recuperação criptografado."""
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

    # Repositórios e tarefas: todas as colunas de configuração (antes só algumas, e as tarefas perdiam
    # retenção, repetição e scripts). A tarefa aponta para o repositório pelo NOME (o id muda na importação).
    for r in _query("SELECT * FROM repositories ORDER BY id"):
        config['repositories'].append(_export_repository(r, include_secrets))
    repo_names = {r['id']: r['name'] for r in _query("SELECT id, name FROM repositories")}
    for t in _query("SELECT * FROM tasks ORDER BY id"):
        item = {k: v for k, v in t.items()
                if k not in _TASK_RUNTIME_COLS and (include_secrets or not _is_secret_col(k))}
        item['repository'] = repo_names.get(t.get('repository_id'))
        config['tasks'].append(item)

    # Settings
    settings_rows = _query("SELECT key, value FROM settings")
    for s in settings_rows:
        if s['key'] in _LOCAL_ONLY_SETTINGS:
            continue
        try:
            val = json.loads(s['value'])
        except (json.JSONDecodeError, TypeError):
            val = s['value']
        if not include_sensitive and isinstance(val, dict):
            val = {k: v for k, v in val.items() if not _is_secret_col(k)}
        config['settings'][s['key']] = val

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
        # Guardar o gerenciador de contexto: é ele que devolve a conexão ao pool no final.
        # Antes chamava-se conn.__exit__ (da conexão psycopg2), que não devolve nada — a conexão ficava
        # presa nesta thread e o pool perdia uma conexão a cada importação.
        _conn_cm = core.get_db_connection()
        conn = _conn_cm.__enter__()
        cur = conn.cursor()

    try:
        # Repositórios (antes gravava na coluna inexistente "repo_type" e a importação falhava)
        from engines import repo_secrets
        repo_ids: Dict[str, int] = {}
        for repo in config_data.get('repositories', []):
            name = (repo.get('name') or '').strip()
            existing = _query("SELECT id FROM repositories WHERE name = %s", (name,))
            if existing:
                repo_ids[name] = existing[0]['id']
                report['repositories']['skip'] += 1
                report['warnings'].append(f"Repository '{name}' already exists, skipping")
                continue
            report['repositories']['add'] += 1
            secrets = repo.get('secrets') or {}
            cfg = dict(repo.get('config') or {}) if isinstance(repo.get('config'), dict) else {}
            cfg.pop('secret_enc', None)
            if secrets.get('cloud_secret'):
                cfg['secret_enc'] = repo_secrets.encrypt(secrets['cloud_secret'])   # chave deste computador
            elif str(repo.get('type') or repo.get('repo_type') or 'local').lower() != 'local':
                report['warnings'].append(f"Repository '{name}': informe a chave secreta da nuvem em Repositórios > Editar")
            if dry_run:
                repo_ids[name] = -1     # será criado; só para a simulação das tarefas
            else:
                cur.execute("""
                    INSERT INTO repositories (name, type, engine, path, config, enabled, password, motor_password,
                                              cloud_password, encryption_password, status, initialized, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id
                """, (name, repo.get('type') or repo.get('repo_type') or 'local', repo.get('engine'), repo.get('path'),
                      json.dumps(cfg), repo.get('enabled', True) is not False,
                      secrets.get('password') or secrets.get('motor_password'), secrets.get('motor_password'),
                      secrets.get('cloud_secret') or secrets.get('cloud_password'),
                      secrets.get('encryption_password') or secrets.get('motor_password')))
                repo_ids[name] = cur.fetchone()[0]

        # Tarefas: todas as colunas conhecidas pelo banco atual; repositório resolvido pelo nome
        task_cols = {row['column_name'] for row in _query(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'tasks'")} - _TASK_RUNTIME_COLS
        for task in config_data.get('tasks', []):
            name = (task.get('name') or '').strip()
            existing = _query("SELECT id FROM tasks WHERE name = %s", (name,))
            if existing:
                report['tasks']['skip'] += 1
                report['warnings'].append(f"Task '{name}' already exists, skipping")
                continue
            repo_id = repo_ids.get(task.get('repository'))
            if task.get('repository') and repo_id is None and not dry_run:
                found = _query("SELECT id FROM repositories WHERE name = %s", (task.get('repository'),))
                repo_id = found[0]['id'] if found else None
            if task.get('repository') and repo_id is None:
                report['warnings'].append(f"Task '{name}': repositório '{task.get('repository')}' não encontrado")
            report['tasks']['add'] += 1
            if not dry_run:
                row = {k: v for k, v in task.items() if k in task_cols}
                row['repository_id'] = repo_id
                cols = list(row)
                cur.execute(f"INSERT INTO tasks ({', '.join(cols)}, status, created_at, updated_at) "
                            f"VALUES ({', '.join(['%s'] * len(cols))}, 'idle', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                            [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()])

        # Settings
        for key, value in config_data.get('settings', {}).items():
            if key in _LOCAL_ONLY_SETTINGS:
                continue
            report['settings']['update'] += 1
            if not dry_run:
                val_str = json.dumps(value) if not isinstance(value, str) else value
                cur.execute("""
                    INSERT INTO settings (key, value) VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = %s
                """, (key, val_str, val_str))

        # SMTP (só no pacote com dados sensíveis e se este Agente ainda não tiver SMTP configurado)
        smtp = config_data.get('smtp')
        if isinstance(smtp, dict) and smtp.get('password'):
            try:
                cols = {row['column_name'] for row in _query(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'smtp_config'")}
                has = bool(cols) and bool(_query("SELECT 1 FROM smtp_config LIMIT 1"))
            except Exception:
                cols, has = set(), True
            if cols and not has:
                report['smtp'] = 'add'
                if not dry_run:
                    smtp = dict(smtp)          # há duas versões da tabela: coluna server ou host
                    smtp.setdefault('server', smtp.get('host'))
                    smtp.setdefault('host', smtp.get('server'))
                    row = {k: v for k, v in smtp.items() if k in cols and k not in ('id', 'updated_at')}
                    cur.execute("SAVEPOINT gboc_smtp")
                    try:
                        cur.execute(f"INSERT INTO smtp_config ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))})",
                                    list(row.values()))
                        cur.execute("RELEASE SAVEPOINT gboc_smtp")
                    except Exception as e:
                        cur.execute("ROLLBACK TO SAVEPOINT gboc_smtp")
                        report['warnings'].append(f"SMTP não importado: {e}")
            elif cols:
                report['warnings'].append("SMTP já configurado neste Agente, mantido")

        # Report schedules
        for sched in config_data.get('report_schedules', []):
            if _query("SELECT 1 FROM information_schema.tables WHERE table_name = 'report_schedules'") and \
                    _query("SELECT 1 FROM report_schedules WHERE name = %s", (sched.get('name'),)):
                continue                      # já existe (antes duplicava a cada importação)
            report['report_schedules']['add'] += 1
            if not dry_run:
                cur.execute("SAVEPOINT gboc_sched")
                try:
                    cur.execute("""
                        INSERT INTO report_schedules (name, report_type, format, period_days, cron_expression, email_to, enabled)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (sched.get('name'), sched.get('report_type'), sched.get('format', 'html'),
                          sched.get('period_days', 30), sched.get('cron_expression', '0 8 * * 1'),
                          sched.get('email_to', ''), sched.get('enabled', True)))
                    cur.execute("RELEASE SAVEPOINT gboc_sched")
                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT gboc_sched")
                    report['warnings'].append(f"Agendamento de relatório '{sched.get('name')}' não importado: {e}")

        if not dry_run:
            conn.commit()
            _conn_cm.__exit__(None, None, None)

    except Exception as e:
        report['errors'].append(str(e))
        if not dry_run:
            try:
                conn.rollback()
                _conn_cm.__exit__(None, None, None)
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

