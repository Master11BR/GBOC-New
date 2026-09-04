#!/usr/bin/env python3
"""
GBOC 14.0.0 - Database Backup Engine
Supports PostgreSQL (pg_dump), MySQL (mysqldump), SQLite (file copy).
Backup, restore, test-restore, listing.
"""

import logging
import subprocess
import os
import shutil
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


def _query(sql: str, params: tuple = ()) -> List[Dict]:
    core = _get_core()
    with core.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        cols = [d[0] for d in cursor.description] if cursor.description else []
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _execute(sql: str, params: tuple = ()):
    core = _get_core()
    with core.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()


def _execute_returning(sql: str, params: tuple = ()) -> Optional[Dict]:
    core = _get_core()
    with core.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        if cursor.description:
            cols = [d[0] for d in cursor.description]
            row = cursor.fetchone()
            return dict(zip(cols, row)) if row else None
        return None


# ─── Connection Management ─────────────────────────────────────────

def list_connections() -> List[Dict]:
    return _query("SELECT * FROM database_connections ORDER BY name")


def get_connection(conn_id: int) -> Optional[Dict]:
    rows = _query("SELECT * FROM database_connections WHERE id = %s", (conn_id,))
    return rows[0] if rows else None


def create_connection(data: Dict) -> Dict:
    return _execute_returning("""
        INSERT INTO database_connections (name, db_type, host, port, database_name, username, password, options, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        RETURNING *
    """, (
        data['name'], data['db_type'], data.get('host', 'localhost'),
        data.get('port', 5432), data['database_name'],
        data.get('username', ''), data.get('password', ''),
        json.dumps(data.get('options', {}))
    ))


def update_connection(conn_id: int, data: Dict) -> Dict:
    return _execute_returning("""
        UPDATE database_connections
        SET name=%s, db_type=%s, host=%s, port=%s, database_name=%s,
            username=%s, password=%s, options=%s, updated_at=NOW()
        WHERE id=%s RETURNING *
    """, (
        data['name'], data['db_type'], data.get('host', 'localhost'),
        data.get('port', 5432), data['database_name'],
        data.get('username', ''), data.get('password', ''),
        json.dumps(data.get('options', {})),
        conn_id
    ))


def delete_connection(conn_id: int):
    _execute("DELETE FROM database_connections WHERE id = %s", (conn_id,))


def test_connection(conn_id: int) -> Dict:
    conn_data = get_connection(conn_id)
    if not conn_data:
        return {"success": False, "error": "Conexão não encontrada"}

    db_type = conn_data.get('db_type', 'postgresql')

    try:
        if db_type == 'postgresql':
            import psycopg2
            c = psycopg2.connect(
                host=conn_data.get('host', 'localhost'),
                port=conn_data.get('port', 5432),
                database=conn_data.get('database_name'),
                user=conn_data.get('username'),
                password=conn_data.get('password'),
                connect_timeout=10
            )
            cur = c.cursor()
            cur.execute("SELECT version()")
            ver = cur.fetchone()[0]
            c.close()
            return {"success": True, "version": ver}

        elif db_type == 'mysql':
            result = subprocess.run(
                ['mysql', '-h', conn_data.get('host', 'localhost'),
                 '-P', str(conn_data.get('port', 3306)),
                 '-u', conn_data.get('username', 'root'),
                 f"-p{conn_data.get('password', '')}",
                 '-e', 'SELECT VERSION()'],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                return {"success": True, "version": result.stdout.strip()}
            return {"success": False, "error": result.stderr.strip()}

        elif db_type == 'sqlite':
            db_path = conn_data.get('database_name', '')
            if os.path.exists(db_path):
                return {"success": True, "version": "SQLite3", "size": os.path.getsize(db_path)}
            return {"success": False, "error": f"Arquivo não encontrado: {db_path}"}

        return {"success": False, "error": f"Tipo não suportado: {db_type}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── Backup Execution ──────────────────────────────────────────────

def run_database_backup(conn_id: int, output_dir: str = None) -> Dict:
    conn_data = get_connection(conn_id)
    if not conn_data:
        return {"success": False, "error": "Conexão não encontrada"}

    db_type = conn_data.get('db_type', 'postgresql')
    db_name = conn_data.get('database_name', 'unknown')

    if not output_dir:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backups', 'database')
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{db_name}_{timestamp}.sql"
    filepath = os.path.join(output_dir, filename)

    start = time.time()
    record = _execute_returning("""
        INSERT INTO database_backups (connection_id, filename, status, started_at)
        VALUES (%s, %s, 'running', NOW()) RETURNING id
    """, (conn_id, filename))
    backup_id = record['id'] if record else None

    try:
        if db_type == 'postgresql':
            result = _backup_postgresql(conn_data, filepath)
        elif db_type == 'mysql':
            result = _backup_mysql(conn_data, filepath)
        elif db_type == 'sqlite':
            result = _backup_sqlite(conn_data, filepath)
        else:
            result = {"success": False, "error": f"Tipo não suportado: {db_type}"}

        duration = int(time.time() - start)
        file_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0

        if backup_id:
            if result.get('success'):
                _execute("""
                    UPDATE database_backups
                    SET status='completed', completed_at=NOW(), duration_seconds=%s,
                        file_size=%s, file_path=%s
                    WHERE id=%s
                """, (duration, file_size, filepath, backup_id))
            else:
                _execute("""
                    UPDATE database_backups
                    SET status='failed', completed_at=NOW(), duration_seconds=%s,
                        error_message=%s
                    WHERE id=%s
                """, (duration, result.get('error', 'Unknown error'), backup_id))

        result['backup_id'] = backup_id
        result['filename'] = filename
        result['filepath'] = filepath
        result['file_size'] = file_size
        result['duration_seconds'] = duration
        return result

    except Exception as e:
        logger.error(f"Database backup failed: {e}")
        if backup_id:
            _execute("UPDATE database_backups SET status='failed', error_message=%s WHERE id=%s",
                     (str(e), backup_id))
        return {"success": False, "error": str(e)}


def _backup_postgresql(conn_data: Dict, filepath: str) -> Dict:
    env = os.environ.copy()
    env['PGPASSWORD'] = conn_data.get('password', '')

    cmd = [
        'pg_dump',
        '-h', conn_data.get('host', 'localhost'),
        '-p', str(conn_data.get('port', 5432)),
        '-U', conn_data.get('username', 'postgres'),
        '-d', conn_data.get('database_name'),
        '-F', 'c',
        '-f', filepath
    ]

    options = conn_data.get('options', {})
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except Exception:
            options = {}

    if options.get('schema_only'):
        cmd.append('--schema-only')
    if options.get('data_only'):
        cmd.append('--data-only')
    if options.get('compress'):
        cmd.extend(['-Z', str(options.get('compress_level', 6))])

    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
    if result.returncode == 0:
        return {"success": True, "output": result.stdout}
    return {"success": False, "error": result.stderr.strip() or f"Exit code {result.returncode}"}


def _backup_mysql(conn_data: Dict, filepath: str) -> Dict:
    cmd = [
        'mysqldump',
        '-h', conn_data.get('host', 'localhost'),
        '-P', str(conn_data.get('port', 3306)),
        '-u', conn_data.get('username', 'root'),
        f"-p{conn_data.get('password', '')}",
        '--single-transaction',
        '--routines',
        '--triggers',
        conn_data.get('database_name'),
    ]

    with open(filepath, 'w') as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True, timeout=3600)

    if result.returncode == 0:
        return {"success": True}
    return {"success": False, "error": result.stderr.strip()}


def _backup_sqlite(conn_data: Dict, filepath: str) -> Dict:
    src = conn_data.get('database_name', '')
    if not os.path.exists(src):
        return {"success": False, "error": f"Arquivo SQLite não encontrado: {src}"}

    try:
        import sqlite3
        source_conn = sqlite3.connect(src)
        dest_conn = sqlite3.connect(filepath)
        source_conn.backup(dest_conn)
        dest_conn.close()
        source_conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── Restore ───────────────────────────────────────────────────────

def restore_database(backup_id: int, target_conn_id: int = None) -> Dict:
    rows = _query("SELECT * FROM database_backups WHERE id = %s", (backup_id,))
    if not rows:
        return {"success": False, "error": "Backup não encontrado"}

    backup = rows[0]
    filepath = backup.get('file_path', '')
    if not os.path.exists(filepath):
        return {"success": False, "error": f"Arquivo de backup não encontrado: {filepath}"}

    cid = target_conn_id or backup.get('connection_id')
    conn_data = get_connection(cid)
    if not conn_data:
        return {"success": False, "error": "Conexão de destino não encontrada"}

    db_type = conn_data.get('db_type', 'postgresql')

    try:
        if db_type == 'postgresql':
            return _restore_postgresql(conn_data, filepath)
        elif db_type == 'mysql':
            return _restore_mysql(conn_data, filepath)
        elif db_type == 'sqlite':
            return _restore_sqlite(conn_data, filepath)
        return {"success": False, "error": f"Tipo não suportado: {db_type}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _restore_postgresql(conn_data: Dict, filepath: str) -> Dict:
    env = os.environ.copy()
    env['PGPASSWORD'] = conn_data.get('password', '')
    cmd = [
        'pg_restore',
        '-h', conn_data.get('host', 'localhost'),
        '-p', str(conn_data.get('port', 5432)),
        '-U', conn_data.get('username', 'postgres'),
        '-d', conn_data.get('database_name'),
        '--clean', '--if-exists',
        filepath
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
    if result.returncode == 0:
        return {"success": True, "output": result.stdout}
    return {"success": False, "error": result.stderr.strip()}


def _restore_mysql(conn_data: Dict, filepath: str) -> Dict:
    cmd = [
        'mysql',
        '-h', conn_data.get('host', 'localhost'),
        '-P', str(conn_data.get('port', 3306)),
        '-u', conn_data.get('username', 'root'),
        f"-p{conn_data.get('password', '')}",
        conn_data.get('database_name'),
    ]
    with open(filepath, 'r') as f:
        result = subprocess.run(cmd, stdin=f, stderr=subprocess.PIPE, text=True, timeout=3600)
    if result.returncode == 0:
        return {"success": True}
    return {"success": False, "error": result.stderr.strip()}


def _restore_sqlite(conn_data: Dict, filepath: str) -> Dict:
    dest = conn_data.get('database_name', '')
    try:
        if os.path.exists(dest):
            shutil.copy2(dest, dest + '.bak')
        shutil.copy2(filepath, dest)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── Test Restore (Sandbox) ───────────────────────────────────────

def test_restore(backup_id: int) -> Dict:
    rows = _query("SELECT * FROM database_backups WHERE id = %s", (backup_id,))
    if not rows:
        return {"success": False, "error": "Backup não encontrado"}

    backup = rows[0]
    filepath = backup.get('file_path', '')
    if not os.path.exists(filepath):
        return {"success": False, "error": "Arquivo não encontrado"}

    cid = backup.get('connection_id')
    conn_data = get_connection(cid)
    if not conn_data:
        return {"success": False, "error": "Conexão não encontrada"}

    db_type = conn_data.get('db_type', 'postgresql')
    test_db = f"gboc_test_restore_{int(time.time())}"
    start = time.time()

    try:
        if db_type == 'postgresql':
            return _test_restore_pg(conn_data, filepath, test_db, start)
        elif db_type == 'sqlite':
            tmp = filepath + '.test_restore.db'
            try:
                shutil.copy2(filepath, tmp)
                import sqlite3
                c = sqlite3.connect(tmp)
                tables = c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
                c.close()
                return {"success": True, "test_db": tmp, "tables": tables,
                        "duration_seconds": int(time.time() - start)}
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

        return {"success": False, "error": f"Test restore não suportado para {db_type}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _test_restore_pg(conn_data: Dict, filepath: str, test_db: str, start: float) -> Dict:
    import psycopg2
    env = os.environ.copy()
    env['PGPASSWORD'] = conn_data.get('password', '')
    host = conn_data.get('host', 'localhost')
    port = str(conn_data.get('port', 5432))
    user = conn_data.get('username', 'postgres')

    try:
        # Create temp DB
        conn = psycopg2.connect(host=host, port=int(port), user=user,
                                password=conn_data.get('password', ''), database='postgres')
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(f'CREATE DATABASE "{test_db}"')
        conn.close()

        # Restore into temp DB
        cmd = ['pg_restore', '-h', host, '-p', port, '-U', user, '-d', test_db,
               '--no-owner', '--no-privileges', filepath]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)

        # Verify
        conn2 = psycopg2.connect(host=host, port=int(port), user=user,
                                 password=conn_data.get('password', ''), database=test_db)
        cur2 = conn2.cursor()
        cur2.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        tables = cur2.fetchone()[0]
        conn2.close()

        return {"success": True, "test_db": test_db, "tables_restored": tables,
                "duration_seconds": int(time.time() - start)}
    finally:
        # Cleanup temp DB
        try:
            conn3 = psycopg2.connect(host=host, port=int(port), user=user,
                                     password=conn_data.get('password', ''), database='postgres')
            conn3.autocommit = True
            cur3 = conn3.cursor()
            cur3.execute(f'DROP DATABASE IF EXISTS "{test_db}"')
            conn3.close()
        except Exception:
            pass


# ─── Backup History ────────────────────────────────────────────────

def list_backups(conn_id: int = None, limit: int = 50) -> List[Dict]:
    if conn_id:
        return _query("""
            SELECT db.*, dc.name as connection_name, dc.db_type
            FROM database_backups db
            LEFT JOIN database_connections dc ON db.connection_id = dc.id
            WHERE db.connection_id = %s
            ORDER BY db.started_at DESC LIMIT %s
        """, (conn_id, limit))
    return _query("""
        SELECT db.*, dc.name as connection_name, dc.db_type
        FROM database_backups db
        LEFT JOIN database_connections dc ON db.connection_id = dc.id
        ORDER BY db.started_at DESC LIMIT %s
    """, (limit,))


def delete_backup(backup_id: int) -> Dict:
    rows = _query("SELECT file_path FROM database_backups WHERE id = %s", (backup_id,))
    if rows and rows[0].get('file_path'):
        fp = rows[0]['file_path']
        if os.path.exists(fp):
            os.remove(fp)
    _execute("DELETE FROM database_backups WHERE id = %s", (backup_id,))
    return {"deleted": True}


# ─── Replication (Copy backup to another location) ─────────────────

def replicate_backup(backup_id: int, target_dir: str) -> Dict:
    rows = _query("SELECT * FROM database_backups WHERE id = %s", (backup_id,))
    if not rows:
        return {"success": False, "error": "Backup não encontrado"}

    src = rows[0].get('file_path', '')
    if not os.path.exists(src):
        return {"success": False, "error": "Arquivo não encontrado"}

    os.makedirs(target_dir, exist_ok=True)
    dest = os.path.join(target_dir, os.path.basename(src))

    try:
        shutil.copy2(src, dest)
        return {"success": True, "source": src, "destination": dest,
                "size": os.path.getsize(dest)}
    except Exception as e:
        return {"success": False, "error": str(e)}

