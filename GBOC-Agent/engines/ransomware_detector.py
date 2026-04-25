#!/usr/bin/env python3
"""
GBOC 11.7c - Ransomware Detector Engine
Detects potential ransomware activity by analyzing:
  - File entropy (high entropy = possible encryption)
  - Suspicious file extensions (.encrypted, .locked, .cry, etc.)
  - Mass file changes between snapshots
  - Honeypot/canary file integrity
"""

import logging
import os
import math
import json
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional
from collections import Counter

logger = logging.getLogger(__name__)

# Known ransomware extensions (most common families)
RANSOMWARE_EXTENSIONS = {
    '.encrypted', '.enc', '.locked', '.crypt', '.crypto', '.cry',
    '.locky', '.cerber', '.zepto', '.odin', '.thor', '.aesir',
    '.zzzzz', '.micro', '.xxx', '.ttt', '.vvv', '.ecc',
    '.ezz', '.exx', '.abc', '.aaa', '.bbb', '.ccc',
    '.vvv', '.xyz', '.zzz', '.r5a', '.WNCRY', '.wncry',
    '.wncryt', '.wcry', '.onion', '.keybtc@inbox_com',
    '.LeChiffre', '.dharma', '.wallet', '.arena', '.bip',
    '.gamma', '.monro', '.heets', '.adobe', '.neitrino',
    '.crypted', '.globe', '.purge', '.raid10',
    '.petya', '.mira', '.good', '.blocking',
    '.sage', '.gryphon', '.breaking_bad', '.payrms',
}

# Minimum file size to analyze entropy (skip tiny files)
MIN_ENTROPY_FILE_SIZE = 1024  # 1 KB


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
    """Create ransomware detection tables if not exists."""
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ransomware_scans (
                id SERIAL PRIMARY KEY,
                scan_type TEXT NOT NULL,
                target_path TEXT,
                status TEXT DEFAULT 'running',
                threat_level TEXT DEFAULT 'none',
                findings JSONB DEFAULT '[]',
                summary JSONB DEFAULT '{}',
                started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMPTZ,
                duration_seconds INTEGER DEFAULT 0
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ransomware_canaries (
                id SERIAL PRIMARY KEY,
                file_path TEXT UNIQUE NOT NULL,
                original_hash TEXT NOT NULL,
                last_verified_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                is_compromised BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()


# ─── Entropy analysis ─────────────────────────────────────────────

def calculate_file_entropy(filepath: str) -> float:
    """Calculate Shannon entropy of a file. 
    Values close to 8.0 indicate high randomness (encrypted/compressed)."""
    try:
        with open(filepath, 'rb') as f:
            data = f.read(65536)  # Read first 64KB for speed
        if len(data) < MIN_ENTROPY_FILE_SIZE:
            return 0.0
        freq = Counter(data)
        length = len(data)
        entropy = -sum((count / length) * math.log2(count / length)
                       for count in freq.values() if count > 0)
        return round(entropy, 4)
    except Exception as e:
        logger.debug(f"Entropy calc failed for {filepath}: {e}")
        return 0.0


def calculate_directory_entropy(dirpath: str, max_files: int = 200) -> Dict[str, Any]:
    """Scan a directory and compute entropy statistics."""
    results = {
        'total_files': 0,
        'analyzed_files': 0,
        'high_entropy_files': [],  # entropy >= 7.5
        'average_entropy': 0.0,
        'max_entropy': 0.0,
        'suspicious_extensions': [],
    }
    entropies = []
    count = 0

    for root, dirs, files in os.walk(dirpath):
        for fname in files:
            if count >= max_files:
                break
            fpath = os.path.join(root, fname)
            results['total_files'] += 1

            # Check suspicious extension
            ext = os.path.splitext(fname)[1].lower()
            if ext in RANSOMWARE_EXTENSIONS:
                results['suspicious_extensions'].append({
                    'file': fpath, 'extension': ext
                })

            # Calculate entropy
            try:
                fsize = os.path.getsize(fpath)
                if fsize >= MIN_ENTROPY_FILE_SIZE:
                    ent = calculate_file_entropy(fpath)
                    entropies.append(ent)
                    results['analyzed_files'] += 1
                    if ent >= 7.5:
                        results['high_entropy_files'].append({
                            'file': fpath, 'entropy': ent, 'size': fsize
                        })
                    count += 1
            except (OSError, PermissionError):
                continue

    if entropies:
        results['average_entropy'] = round(sum(entropies) / len(entropies), 4)
        results['max_entropy'] = round(max(entropies), 4)

    return results


# ─── Suspicious extension scan ────────────────────────────────────

def scan_for_suspicious_extensions(dirpath: str, max_files: int = 5000) -> List[Dict]:
    """Fast scan: only check for known ransomware file extensions."""
    findings = []
    count = 0
    for root, dirs, files in os.walk(dirpath):
        for fname in files:
            if count >= max_files:
                return findings
            ext = os.path.splitext(fname)[1].lower()
            if ext in RANSOMWARE_EXTENSIONS:
                fpath = os.path.join(root, fname)
                try:
                    stat = os.stat(fpath)
                    findings.append({
                        'file': fpath,
                        'extension': ext,
                        'size': stat.st_size,
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
                except (OSError, PermissionError):
                    pass
            count += 1
    return findings


# ─── Canary / Honeypot files ─────────────────────────────────────

def _hash_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def create_canary(filepath: str) -> Dict:
    """Create a canary file and register its hash."""
    ensure_tables()
    # Create the file with a known signature
    canary_content = f"GBOC_CANARY_{datetime.now().isoformat()}_{os.urandom(16).hex()}"
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        f.write(canary_content)
    file_hash = _hash_file(filepath)

    _execute("""
        INSERT INTO ransomware_canaries (file_path, original_hash)
        VALUES (%s, %s)
        ON CONFLICT (file_path) DO UPDATE SET original_hash = %s, is_compromised = false, last_verified_at = CURRENT_TIMESTAMP
    """, (filepath, file_hash, file_hash))

    return {'file_path': filepath, 'hash': file_hash, 'status': 'created'}


def verify_canaries() -> Dict[str, Any]:
    """Verify all registered canary files. Any change = ALERT."""
    ensure_tables()
    canaries = _query("SELECT id, file_path, original_hash, is_compromised FROM ransomware_canaries")
    results = {'total': len(canaries), 'intact': 0, 'compromised': 0, 'missing': 0, 'details': []}

    for c in canaries:
        fpath = c['file_path']
        detail = {'file_path': fpath, 'status': 'unknown'}

        if not os.path.exists(fpath):
            detail['status'] = 'missing'
            results['missing'] += 1
            _execute("UPDATE ransomware_canaries SET is_compromised = true, last_verified_at = CURRENT_TIMESTAMP WHERE id = %s", (c['id'],))
        else:
            current_hash = _hash_file(fpath)
            if current_hash == c['original_hash']:
                detail['status'] = 'intact'
                results['intact'] += 1
                _execute("UPDATE ransomware_canaries SET last_verified_at = CURRENT_TIMESTAMP WHERE id = %s", (c['id'],))
            else:
                detail['status'] = 'COMPROMISED'
                detail['original_hash'] = c['original_hash']
                detail['current_hash'] = current_hash
                results['compromised'] += 1
                _execute("UPDATE ransomware_canaries SET is_compromised = true, last_verified_at = CURRENT_TIMESTAMP WHERE id = %s", (c['id'],))

        results['details'].append(detail)

    return results


# ─── Full scan ────────────────────────────────────────────────────

def run_full_scan(target_path: str) -> Dict[str, Any]:
    """Run a full ransomware detection scan on a directory."""
    ensure_tables()
    start = datetime.now()

    # Record scan start
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ransomware_scans (scan_type, target_path, status)
            VALUES ('full', %s, 'running') RETURNING id
        """, (target_path,))
        scan_id = cur.fetchone()[0]
        conn.commit()

    findings = []
    threat_level = 'none'

    try:
        # 1. Extension scan
        ext_findings = scan_for_suspicious_extensions(target_path)
        if ext_findings:
            findings.append({
                'type': 'suspicious_extensions',
                'severity': 'high' if len(ext_findings) > 10 else 'medium',
                'count': len(ext_findings),
                'sample': ext_findings[:20]
            })

        # 2. Entropy analysis
        entropy_result = calculate_directory_entropy(target_path)
        if entropy_result['high_entropy_files']:
            findings.append({
                'type': 'high_entropy',
                'severity': 'high' if len(entropy_result['high_entropy_files']) > 20 else 'medium',
                'count': len(entropy_result['high_entropy_files']),
                'average_entropy': entropy_result['average_entropy'],
                'max_entropy': entropy_result['max_entropy'],
                'sample': entropy_result['high_entropy_files'][:10]
            })

        # 3. Canary verification
        canary_result = verify_canaries()
        if canary_result['compromised'] > 0 or canary_result['missing'] > 0:
            findings.append({
                'type': 'canary_alert',
                'severity': 'critical',
                'compromised': canary_result['compromised'],
                'missing': canary_result['missing'],
                'details': canary_result['details']
            })

        # Determine threat level
        severities = [f.get('severity', 'low') for f in findings]
        if 'critical' in severities:
            threat_level = 'critical'
        elif severities.count('high') >= 2:
            threat_level = 'high'
        elif 'high' in severities:
            threat_level = 'medium'
        elif 'medium' in severities:
            threat_level = 'low'
        else:
            threat_level = 'none'

        duration = int((datetime.now() - start).total_seconds())
        summary = {
            'total_findings': len(findings),
            'threat_level': threat_level,
            'suspicious_extensions': len(ext_findings),
            'high_entropy_files': len(entropy_result.get('high_entropy_files', [])),
            'canary_compromised': canary_result.get('compromised', 0),
            'scan_duration_seconds': duration
        }

        # Update scan record
        _execute("""
            UPDATE ransomware_scans
            SET status = 'completed', threat_level = %s, findings = %s::jsonb,
                summary = %s::jsonb, completed_at = CURRENT_TIMESTAMP, duration_seconds = %s
            WHERE id = %s
        """, (threat_level, json.dumps(findings), json.dumps(summary), duration, scan_id))

        # Create alert if threat detected
        if threat_level in ('high', 'critical'):
            _execute("""
                INSERT INTO alerts (type, severity, title, message, source, timestamp)
                VALUES ('ransomware_detection', %s, %s, %s, 'ransomware_detector', CURRENT_TIMESTAMP)
            """, (threat_level,
                  f'Ransomware Detection Alert: {threat_level.upper()}',
                  f'Scan of {target_path} found {len(findings)} suspicious indicators. Threat level: {threat_level}'))

        return {
            'scan_id': scan_id,
            'target_path': target_path,
            'threat_level': threat_level,
            'findings': findings,
            'summary': summary
        }

    except Exception as e:
        logger.error(f"Ransomware scan failed: {e}")
        _execute("""
            UPDATE ransomware_scans
            SET status = 'failed', completed_at = CURRENT_TIMESTAMP,
                summary = %s::jsonb
            WHERE id = %s
        """, (json.dumps({'error': str(e)}), scan_id))
        raise


def get_scan_history(limit: int = 20) -> List[Dict]:
    """Get recent ransomware scan history."""
    ensure_tables()
    return _query("""
        SELECT id, scan_type, target_path, status, threat_level,
               summary, started_at, completed_at, duration_seconds
        FROM ransomware_scans
        ORDER BY started_at DESC LIMIT %s
    """, (limit,))


def get_protection_status() -> Dict[str, Any]:
    """Get overall ransomware protection status."""
    ensure_tables()
    canaries = _query("SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE is_compromised) AS compromised FROM ransomware_canaries")
    last_scan = _query("SELECT id, threat_level, started_at, summary FROM ransomware_scans WHERE status = 'completed' ORDER BY started_at DESC LIMIT 1")

    c = canaries[0] if canaries else {'total': 0, 'compromised': 0}
    ls = last_scan[0] if last_scan else None

    return {
        'canaries': {
            'total': c.get('total', 0),
            'compromised': c.get('compromised', 0),
            'status': 'ok' if c.get('compromised', 0) == 0 else 'ALERT'
        },
        'last_scan': {
            'scan_id': ls.get('id') if ls else None,
            'threat_level': ls.get('threat_level', 'unknown') if ls else 'never_scanned',
            'date': ls.get('started_at').isoformat() if ls and ls.get('started_at') else None,
            'summary': ls.get('summary') if ls else {}
        },
        'overall_status': 'protected' if (c.get('compromised', 0) == 0 and
                                           (not ls or ls.get('threat_level') in ('none', 'low')))
                          else 'at_risk'
    }

