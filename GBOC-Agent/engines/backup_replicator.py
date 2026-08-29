#!/usr/bin/env python3
"""
GBOC 13.2.0 - Backup Replicator Engine
Copies backups from one repository to another (3-2-1 rule enforcement).
Supports cross-engine replication, integrity verification after copy, scheduling.
"""

import logging
import os
import json
import shutil
import subprocess
import hashlib
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
    """Create replication tables if not exists."""
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS replication_policies (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                source_repo_id INTEGER NOT NULL,
                target_repo_id INTEGER NOT NULL,
                enabled BOOLEAN DEFAULT TRUE,
                schedule_cron TEXT DEFAULT '0 2 * * *',
                verify_after_copy BOOLEAN DEFAULT TRUE,
                last_run TIMESTAMPTZ,
                next_run TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS replication_history (
                id SERIAL PRIMARY KEY,
                policy_id INTEGER REFERENCES replication_policies(id) ON DELETE SET NULL,
                source_repo TEXT,
                target_repo TEXT,
                status TEXT DEFAULT 'running',
                bytes_copied BIGINT DEFAULT 0,
                files_copied INTEGER DEFAULT 0,
                duration_seconds INTEGER DEFAULT 0,
                verify_status TEXT,
                error_message TEXT,
                started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMPTZ
            );
        """)
        conn.commit()


# ─── CRUD ─────────────────────────────────────────────────────────

def list_policies() -> List[Dict]:
    ensure_tables()
    return _query("""
        SELECT rp.*,
               sr.name AS source_repo_name, sr.engine AS source_engine,
               tr.name AS target_repo_name, tr.engine AS target_engine
        FROM replication_policies rp
        LEFT JOIN repositories sr ON sr.id = rp.source_repo_id
        LEFT JOIN repositories tr ON tr.id = rp.target_repo_id
        ORDER BY rp.id
    """)


def get_policy(policy_id: int) -> Optional[Dict]:
    ensure_tables()
    return _query_one("""
        SELECT rp.*,
               sr.name AS source_repo_name, sr.engine AS source_engine,
               tr.name AS target_repo_name, tr.engine AS target_engine
        FROM replication_policies rp
        LEFT JOIN repositories sr ON sr.id = rp.source_repo_id
        LEFT JOIN repositories tr ON tr.id = rp.target_repo_id
        WHERE rp.id = %s
    """, (policy_id,))


def create_policy(data: Dict) -> Dict:
    ensure_tables()
    # Validate repos exist
    source = _query_one("SELECT id FROM repositories WHERE id = %s", (data['source_repo_id'],))
    target = _query_one("SELECT id FROM repositories WHERE id = %s", (data['target_repo_id'],))
    if not source:
        raise ValueError(f"Source repository {data['source_repo_id']} not found")
    if not target:
        raise ValueError(f"Target repository {data['target_repo_id']} not found")
    if data['source_repo_id'] == data['target_repo_id']:
        raise ValueError("Source and target repositories must be different")

    pid = _execute_returning("""
        INSERT INTO replication_policies (name, source_repo_id, target_repo_id, enabled, schedule_cron, verify_after_copy)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    """, (data['name'], data['source_repo_id'], data['target_repo_id'],
          data.get('enabled', True), data.get('schedule_cron', '0 2 * * *'),
          data.get('verify_after_copy', True)))
    return get_policy(pid)


def update_policy(policy_id: int, data: Dict) -> Dict:
    ensure_tables()
    fields, params = [], []
    for key in ('name', 'source_repo_id', 'target_repo_id', 'enabled', 'schedule_cron', 'verify_after_copy'):
        if key in data and data[key] is not None:
            fields.append(f"{key} = %s")
            params.append(data[key])
    if fields:
        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(policy_id)
        _execute(f"UPDATE replication_policies SET {', '.join(fields)} WHERE id = %s", tuple(params))
    return get_policy(policy_id)


def delete_policy(policy_id: int):
    ensure_tables()
    _execute("DELETE FROM replication_policies WHERE id = %s", (policy_id,))


# ─── Replication execution ────────────────────────────────────────

def _get_repo_path(repo: Dict) -> str:
    """Extract the local path from a repository config."""
    path = repo.get('path', repo.get('repo_path', ''))
    if not path:
        config = repo.get('config', {})
        if isinstance(config, str):
            config = json.loads(config)
        path = config.get('path', config.get('repo_path', ''))
    return path


def _hash_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _replicate_local(source_path: str, target_path: str) -> Dict:
    """Copy files from source to target using rsync or shutil."""
    bytes_copied = 0
    files_copied = 0

    # Try rsync first (faster, supports resume)
    if shutil.which('rsync'):
        try:
            result = subprocess.run(
                ['rsync', '-av', '--stats', f'{source_path}/', f'{target_path}/'],
                capture_output=True, text=True, timeout=7200
            )
            if result.returncode == 0:
                # Parse rsync stats
                for line in result.stdout.split('\n'):
                    if 'Number of regular files transferred' in line:
                        try:
                            files_copied = int(line.split(':')[1].strip().replace(',', ''))
                        except (ValueError, IndexError):
                            pass
                    elif 'Total transferred file size' in line:
                        try:
                            size_str = line.split(':')[1].strip().split()[0].replace(',', '')
                            bytes_copied = int(size_str)
                        except (ValueError, IndexError):
                            pass
                return {'bytes_copied': bytes_copied, 'files_copied': files_copied}
            else:
                logger.warning(f"rsync failed: {result.stderr}")
        except Exception as e:
            logger.warning(f"rsync failed, falling back to shutil: {e}")

    # Fallback to shutil
    os.makedirs(target_path, exist_ok=True)
    for root, dirs, files in os.walk(source_path):
        rel_root = os.path.relpath(root, source_path)
        dest_root = os.path.join(target_path, rel_root)
        os.makedirs(dest_root, exist_ok=True)
        for fname in files:
            src = os.path.join(root, fname)
            dst = os.path.join(dest_root, fname)
            try:
                shutil.copy2(src, dst)
                bytes_copied += os.path.getsize(src)
                files_copied += 1
            except (OSError, PermissionError) as e:
                logger.warning(f"Could not copy {src}: {e}")

    return {'bytes_copied': bytes_copied, 'files_copied': files_copied}


def _verify_replication(source_path: str, target_path: str, max_files: int = 100) -> Dict:
    """Verify a sample of files match between source and target."""
    verified = 0
    mismatched = 0
    missing = 0
    count = 0

    for root, dirs, files in os.walk(source_path):
        for fname in files:
            if count >= max_files:
                break
            src = os.path.join(root, fname)
            rel = os.path.relpath(src, source_path)
            dst = os.path.join(target_path, rel)
            if not os.path.exists(dst):
                missing += 1
            elif _hash_file(src) == _hash_file(dst):
                verified += 1
            else:
                mismatched += 1
            count += 1

    status = 'verified' if (mismatched == 0 and missing == 0) else 'failed'
    return {
        'status': status,
        'files_checked': count,
        'verified': verified,
        'mismatched': mismatched,
        'missing': missing
    }


def run_replication(policy_id: int) -> Dict:
    """Execute a replication policy."""
    ensure_tables()
    policy = get_policy(policy_id)
    if not policy:
        raise ValueError(f"Policy {policy_id} not found")

    source_repo = _query_one("SELECT * FROM repositories WHERE id = %s", (policy['source_repo_id'],))
    target_repo = _query_one("SELECT * FROM repositories WHERE id = %s", (policy['target_repo_id'],))

    if not source_repo or not target_repo:
        raise ValueError("Source or target repository not found")

    source_path = _get_repo_path(source_repo)
    target_path = _get_repo_path(target_repo)

    if not source_path or not os.path.isdir(source_path):
        raise ValueError(f"Source path not accessible: {source_path}")

    # Record start
    hist_id = _execute_returning("""
        INSERT INTO replication_history (policy_id, source_repo, target_repo, status)
        VALUES (%s, %s, %s, 'running') RETURNING id
    """, (policy_id, source_repo.get('name', ''), target_repo.get('name', '')))

    start = time.time()

    try:
        # Execute copy
        copy_result = _replicate_local(source_path, target_path)
        duration = int(time.time() - start)

        # Verify if requested
        verify_result = None
        if policy.get('verify_after_copy', True):
            verify_result = _verify_replication(source_path, target_path)

        # Update history
        _execute("""
            UPDATE replication_history
            SET status = 'completed', bytes_copied = %s, files_copied = %s,
                duration_seconds = %s, verify_status = %s, completed_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (copy_result['bytes_copied'], copy_result['files_copied'],
              duration, verify_result.get('status') if verify_result else None, hist_id))

        # Update policy last_run
        _execute("UPDATE replication_policies SET last_run = CURRENT_TIMESTAMP WHERE id = %s", (policy_id,))

        return {
            'history_id': hist_id,
            'policy_id': policy_id,
            'status': 'completed',
            'copy': copy_result,
            'verify': verify_result,
            'duration_seconds': duration
        }

    except Exception as e:
        duration = int(time.time() - start)
        _execute("""
            UPDATE replication_history
            SET status = 'failed', duration_seconds = %s, error_message = %s, completed_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (duration, str(e)[:500], hist_id))
        raise


def get_history(policy_id: Optional[int] = None, limit: int = 20) -> List[Dict]:
    ensure_tables()
    if policy_id:
        return _query("""
            SELECT * FROM replication_history WHERE policy_id = %s ORDER BY started_at DESC LIMIT %s
        """, (policy_id, limit))
    return _query("SELECT * FROM replication_history ORDER BY started_at DESC LIMIT %s", (limit,))


def get_321_status() -> Dict[str, Any]:
    """Check 3-2-1 rule compliance for all tasks."""
    ensure_tables()
    tasks = _query("SELECT id, name, repository_id FROM tasks WHERE enabled = true")
    repos = _query("SELECT id, name, engine, repo_type FROM repositories")
    policies = _query("SELECT source_repo_id, target_repo_id FROM replication_policies WHERE enabled = true")

    repo_map = {r['id']: r for r in repos}
    replication_targets = {}
    for p in policies:
        src = p['source_repo_id']
        tgt = p['target_repo_id']
        if src not in replication_targets:
            replication_targets[src] = []
        replication_targets[src].append(tgt)

    results = []
    for task in tasks:
        repo_id = task.get('repository_id')
        copies = 1  # Original
        media_types = set()
        offsite = False

        if repo_id and repo_id in repo_map:
            media_types.add(repo_map[repo_id].get('repo_type', 'local'))
            # Check replicas
            replica_ids = replication_targets.get(repo_id, [])
            for rid in replica_ids:
                if rid in repo_map:
                    copies += 1
                    rtype = repo_map[rid].get('repo_type', 'local')
                    media_types.add(rtype)
                    if rtype in ('s3', 'cloud', 'azure', 'gcs', 'remote', 'sftp'):
                        offsite = True

        rule_3 = copies >= 3
        rule_2 = len(media_types) >= 2
        rule_1 = offsite
        compliant = rule_3 and rule_2 and rule_1

        results.append({
            'task_id': task['id'],
            'task_name': task['name'],
            'copies': copies,
            'media_types': list(media_types),
            'has_offsite': offsite,
            'rule_3_copies': rule_3,
            'rule_2_media': rule_2,
            'rule_1_offsite': rule_1,
            'compliant': compliant
        })

    total = len(results)
    compliant_count = sum(1 for r in results if r['compliant'])

    return {
        'tasks': results,
        'summary': {
            'total_tasks': total,
            'compliant': compliant_count,
            'non_compliant': total - compliant_count,
            'compliance_percent': round(compliant_count / total * 100, 1) if total > 0 else 0
        }
    }

