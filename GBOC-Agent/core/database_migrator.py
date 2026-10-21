#!/usr/bin/env python3
"""
GBOC Agent - Database Migrator
"""
import logging
import os
import sys

# Add the parent directory to the path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re as _re


def _split_top_level(body):
    """Divide a lista de colunas de um CREATE TABLE pelas vírgulas de nível superior."""
    parts, depth, cur, quoted = [], 0, [], False
    for ch in body:
        if ch == "'":
            quoted = not quoted
        elif not quoted and ch == '(':
            depth += 1
        elif not quoted and ch == ')':
            depth -= 1
        if ch == ',' and depth == 0 and not quoted:
            parts.append(''.join(cur)); cur = []
        else:
            cur.append(ch)
    if ''.join(cur).strip():
        parts.append(''.join(cur))
    return [x.strip() for x in parts if x.strip()]


_CREATE_RE = _re.compile(r'CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+("?[\w.]+"?)\s*\((.*)\)\s*;?\s*$', _re.I | _re.S)
_CONSTRAINT_PREFIXES = ('PRIMARY KEY', 'UNIQUE', 'FOREIGN KEY', 'CONSTRAINT', 'CHECK', 'EXCLUDE')


def _missing_column_statements(create_sql):
    """Para um CREATE TABLE IF NOT EXISTS, gera ADD COLUMN IF NOT EXISTS de cada coluna.
    Bases antigas já têm a tabela, e o CREATE TABLE não acrescenta colunas novas nela.
    NOT NULL / PRIMARY KEY / UNIQUE / REFERENCES são omitidos: em tabela com linhas eles falhariam."""
    m = _CREATE_RE.match(create_sql.strip())
    if not m:
        return []
    table, out = m.group(1), []
    for col in _split_top_level(m.group(2)):
        if col.upper().startswith(_CONSTRAINT_PREFIXES):
            continue
        tokens = col.split(None, 1)
        if len(tokens) < 2:
            continue
        name, rest = tokens
        rest = _re.sub(r'\bPRIMARY\s+KEY\b|\bNOT\s+NULL\b|\bUNIQUE\b', ' ', rest, flags=_re.I)
        rest = _re.sub(r'\bREFERENCES\b.*$', ' ', rest, flags=_re.I | _re.S)
        rest = _re.sub(r'\bSERIAL\b', 'INTEGER', rest, flags=_re.I)
        rest = ' '.join(rest.split())
        if rest:
            out.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {rest}")
    return out


class _SafeMigrationCursor:
    """Executa cada comando da migração no seu próprio SAVEPOINT.
    Antes, uma falha qualquer (ex.: CREATE INDEX numa coluna que a base antiga não tem) abortava a transação
    e o rollback final descartava TODAS as migrações, a cada inicialização: as colunas novas nunca chegavam
    às bases antigas (ex.: job_failure_log.task_id, repositories.engine). Agora a falha é registrada e o resto segue."""

    def __init__(self, cursor, errors):
        self._cur = cursor
        self._errors = errors
        self._n = 0
        self._ok = True
        self._rows = None
        self.rowcount = -1
        self._explicit = 0   # savepoints abertos pelo próprio código da migração

    def execute(self, sql, params=None):
        head = sql.lstrip().upper()
        self._rows = None
        if head.startswith(('SAVEPOINT', 'RELEASE', 'ROLLBACK')):
            self._ok = True
            if head.startswith('SAVEPOINT'):
                self._explicit += 1
            elif self._explicit:
                self._explicit -= 1
            return self._cur.execute(sql, params)
        self._n += 1
        sp = f"gboc_mig_{self._n}"
        self._cur.execute(f"SAVEPOINT {sp}")
        try:
            self._cur.execute(sql, params)
            self._ok = True
            self.rowcount = self._cur.rowcount
            # guardar o resultado antes do RELEASE (que descarta o resultado pendente do cursor)
            self._rows = list(self._cur.fetchall()) if self._cur.description else None
        except Exception as e:
            self._ok = False
            self._cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
            if self._explicit:
                # bloco já protegido por savepoint próprio: mantém o tratamento original (o except dele decide)
                self._cur.execute(f"RELEASE SAVEPOINT {sp}")
                raise
            first = ' '.join(sql.split())[:160]
            msg = f"{first} -> {str(e).strip().splitlines()[0] if str(e).strip() else e}"
            self._errors.append(msg)
            logging.warning(f"⚠️ Migração: comando ignorado ({msg})")
        self._cur.execute(f"RELEASE SAVEPOINT {sp}")
        if self._ok:
            for stmt in _missing_column_statements(sql):
                self._n += 1
                sp2 = f"gboc_mig_{self._n}"
                self._cur.execute(f"SAVEPOINT {sp2}")
                try:
                    self._cur.execute(stmt)
                except Exception as e:
                    self._cur.execute(f"ROLLBACK TO SAVEPOINT {sp2}")
                    self._errors.append(f"{stmt} -> {str(e).strip().splitlines()[0] if str(e).strip() else e}")
                self._cur.execute(f"RELEASE SAVEPOINT {sp2}")
            self._ok = True

    def fetchone(self):
        if not self._ok or not self._rows:
            return None
        return self._rows.pop(0)

    def fetchall(self):
        if not self._ok or not self._rows:
            return []
        rows, self._rows = self._rows, []
        return rows

    def __getattr__(self, name):
        return getattr(self._cur, name)


def run_auto_migrations(conn):

    """Runs the database migration."""

    logging.info("🚀 Starting database migration...")

    migrations_run = 0

    errors = []

    

    with conn.cursor() as _raw_cursor:

        cursor = _SafeMigrationCursor(_raw_cursor, errors)

        try:

            logging.info("🔧 Migrating task_executions table...")

            # Check if the columns are of type 'text' before altering

            cursor.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_name='task_executions' AND column_name='started_at';
            """)
            result = cursor.fetchone()
            if result and result[0] == 'text':

                cursor.execute("""

                    ALTER TABLE task_executions

                    ALTER COLUMN started_at TYPE TIMESTAMPTZ USING started_at::TIMESTAMPTZ,

                    ALTER COLUMN completed_at TYPE TIMESTAMPTZ USING completed_at::TIMESTAMPTZ;

                """)

                migrations_run += 1

                logging.info("✅ Migrated 'started_at' and 'completed_at' to TIMESTAMPTZ in task_executions.")

            else:

                logging.info("👍 'task_executions' table already migrated.")



            logging.info("🔧 Migrating other tables...")

            

            # repositories table

            cursor.execute("SELECT data_type FROM information_schema.columns WHERE table_name='repositories' AND column_name='created_at';")
            result = cursor.fetchone()
            if result and result[0] == 'text':

                cursor.execute("ALTER TABLE repositories ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at::TIMESTAMPTZ;")

                cursor.execute("ALTER TABLE repositories ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at::TIMESTAMPTZ;")

                migrations_run += 1

                logging.info("✅ Migrated 'repositories' table timestamps.")

            else:

                logging.info("👍 'repositories' table already migrated.")



            # tasks table

            cursor.execute("SELECT data_type FROM information_schema.columns WHERE table_name='tasks' AND column_name='created_at';")
            result = cursor.fetchone()

            if result and result[0] == 'text':

                cursor.execute("ALTER TABLE tasks ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at::TIMESTAMPTZ;")

                cursor.execute("ALTER TABLE tasks ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at::TIMESTAMPTZ;")

                cursor.execute("ALTER TABLE tasks ALTER COLUMN last_run TYPE TIMESTAMPTZ USING last_run::TIMESTAMPTZ;")

                migrations_run += 1

                logging.info("✅ Migrated 'tasks' table timestamps.")

            else:

                logging.info("👍 'tasks' table already migrated.")



            # alerts table

            cursor.execute("SELECT data_type FROM information_schema.columns WHERE table_name='alerts' AND column_name='timestamp';")
            result = cursor.fetchone()
            if result and result[0] == 'text':

                cursor.execute("ALTER TABLE alerts ALTER COLUMN timestamp TYPE TIMESTAMPTZ USING timestamp::TIMESTAMPTZ;")

                migrations_run += 1

                logging.info("✅ Migrated 'alerts' table timestamps.")

            else:

                logging.info("👍 'alerts' table already migrated.")



            # Migrações defensivas de schema ausente
            logging.info("🔧 Aplicando migrações defensivas de schema...")

            defensive_statements = [
                "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS encryption_password TEXT;",
                # Bases antigas criaram "repositories"/"tasks" com poucas colunas (importador falhava em "engine")
                "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS engine TEXT DEFAULT 'restic';",
                "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS password TEXT;",
                "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS motor_password TEXT;",
                "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS cloud_password TEXT;",
                "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS config TEXT;",
                "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active';",
                "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE;",
                "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS initialized BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;",
                "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS repository_id INTEGER;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'idle';",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS pre_script TEXT;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS post_script TEXT;",
                # Bases antigas criaram "alerts" sem estas colunas (HTTP 500 em /api/alerts/)
                "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS acknowledged BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS resolved BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS details TEXT;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source_paths TEXT;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS engine TEXT DEFAULT 'restic';",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'backup';",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS schedule_enabled BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS schedule_cron TEXT;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS last_run TIMESTAMPTZ;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS last_status TEXT;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retention_days INTEGER DEFAULT 30;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retention_weekly INTEGER DEFAULT 4;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retention_monthly INTEGER DEFAULT 6;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retention_yearly INTEGER DEFAULT 1;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retry_enabled BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retry_max_attempts INTEGER DEFAULT 3;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retry_delay_minutes INTEGER DEFAULT 5;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS bytes_processed BIGINT DEFAULT 0;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS files_processed INTEGER DEFAULT 0;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS error_message TEXT;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS snapshot_id TEXT;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS current_file TEXT;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS files_total INTEGER DEFAULT 0;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS bytes_total BIGINT DEFAULT 0;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS avg_speed_bytes_per_sec DOUBLE PRECISION DEFAULT 0;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS compression_ratio DOUBLE PRECISION DEFAULT 0;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS files_new INTEGER DEFAULT 0;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS files_changed INTEGER DEFAULT 0;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS files_unmodified INTEGER DEFAULT 0;",
                "ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS bytes_added BIGINT DEFAULT 0;",
                "ALTER TABLE settings ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'general';",
                "ALTER TABLE settings ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'string';",
                "ALTER TABLE settings ADD COLUMN IF NOT EXISTS description TEXT;",
                "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS resolved BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS details TEXT;",
            ]

            for stmt in defensive_statements:
                try:
                    cursor.execute("SAVEPOINT defensive_mig")
                    cursor.execute(stmt)
                    cursor.execute("RELEASE SAVEPOINT defensive_mig")
                except Exception:
                    cursor.execute("ROLLBACK TO SAVEPOINT defensive_mig")

            # Migrar finished_at -> completed_at se necessário
            cursor.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'task_executions' AND column_name = 'finished_at'
            """)
            if cursor.fetchone():
                cursor.execute("""
                    UPDATE task_executions SET completed_at = finished_at
                    WHERE completed_at IS NULL AND finished_at IS NOT NULL
                """)
                cursor.execute("ALTER TABLE task_executions DROP COLUMN IF EXISTS finished_at;")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_executions (
                    id SERIAL PRIMARY KEY,
                    task_id INTEGER,
                    status TEXT,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    duration_seconds INTEGER,
                    bytes_processed BIGINT DEFAULT 0,
                    files_processed INTEGER DEFAULT 0,
                    error_message TEXT,
                    progress INTEGER DEFAULT 0,
                    snapshot_id TEXT,
                    current_file TEXT,
                    files_total INTEGER DEFAULT 0,
                    bytes_total BIGINT DEFAULT 0,
                    avg_speed_bytes_per_sec DOUBLE PRECISION DEFAULT 0,
                    compression_ratio DOUBLE PRECISION DEFAULT 0,
                    files_new INTEGER DEFAULT 0,
                    files_changed INTEGER DEFAULT 0,
                    files_unmodified INTEGER DEFAULT 0,
                    bytes_added BIGINT DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS backup_statistics (
                    id SERIAL PRIMARY KEY,
                    task_id INTEGER,
                    task_name TEXT,
                    repository_name TEXT,
                    backup_date TIMESTAMPTZ,
                    success BOOLEAN,
                    duration_seconds INTEGER,
                    bytes_processed BIGINT,
                    files_processed INTEGER,
                    error_message TEXT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS restore_history (
                    id SERIAL PRIMARY KEY,
                    repository_id INTEGER,
                    snapshot_id TEXT,
                    status TEXT DEFAULT 'pending',
                    target_path TEXT,
                    total_files INTEGER DEFAULT 0,
                    files_restored INTEGER DEFAULT 0,
                    bytes_restored BIGINT DEFAULT 0,
                    duration_seconds INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Auth tables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS auth_users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    display_name TEXT,
                    role TEXT DEFAULT 'admin',
                    is_active BOOLEAN DEFAULT TRUE,
                    last_login TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES auth_users(id),
                    token TEXT UNIQUE NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Alerts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY,
                    type TEXT,
                    severity TEXT DEFAULT 'warning',
                    title TEXT,
                    message TEXT,
                    source TEXT,
                    acknowledged BOOLEAN DEFAULT FALSE,
                    resolved BOOLEAN DEFAULT FALSE,
                    details TEXT,
                    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Report schedules table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS report_schedules (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    format TEXT DEFAULT 'html',
                    period_days INTEGER DEFAULT 30,
                    cron_expression TEXT DEFAULT '0 8 * * 1',
                    email_to TEXT,
                    enabled BOOLEAN DEFAULT TRUE,
                    last_run TIMESTAMPTZ,
                    next_run TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Report history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS report_history (
                    id SERIAL PRIMARY KEY,
                    schedule_id INTEGER,
                    report_type TEXT,
                    format TEXT DEFAULT 'html',
                    generated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    file_size INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'completed',
                    error_message TEXT
                );
            """)

            # Database connections table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS database_connections (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    db_type TEXT NOT NULL DEFAULT 'postgresql',
                    host TEXT DEFAULT 'localhost',
                    port INTEGER DEFAULT 5432,
                    database_name TEXT NOT NULL,
                    username TEXT,
                    password TEXT,
                    options JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Database backups table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS database_backups (
                    id SERIAL PRIMARY KEY,
                    connection_id INTEGER REFERENCES database_connections(id),
                    filename TEXT,
                    file_path TEXT,
                    file_size BIGINT DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMPTZ,
                    duration_seconds INTEGER DEFAULT 0,
                    error_message TEXT
                );
            """)

            # User dashboard layouts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_dashboard_layouts (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    layout_name TEXT DEFAULT 'default',
                    widget_order JSONB DEFAULT '[]',
                    widget_config JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Ransomware scans table
            cursor.execute("""
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

            # Ransomware canary files table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ransomware_canaries (
                    id SERIAL PRIMARY KEY,
                    file_path TEXT UNIQUE NOT NULL,
                    original_hash TEXT NOT NULL,
                    last_verified_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    is_compromised BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Notification channels table
            cursor.execute("""
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

            # Notification history table
            cursor.execute("""
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

            # Replication policies table
            cursor.execute("""
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

            # Replication history table
            cursor.execute("""
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

            # Config snapshots table
            cursor.execute("""
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

            # Audit log table
            cursor.execute("""
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log (timestamp DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log (action);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log (username);")

            # Essential performance indexes (prevents full-table scans on system_logs, task_executions, alerts)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs (timestamp DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs (level);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_source ON system_logs (source);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_executions_started_at ON task_executions (started_at DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_executions_task_id ON task_executions (task_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_executions_status ON task_executions (status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts (timestamp DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON alerts (resolved);")

            # Engine & Module Tables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS auto_heal_logs (
                    id SERIAL PRIMARY KEY,
                    timestamp TEXT,
                    event_type TEXT,
                    details TEXT,
                    status TEXT
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS surebackup_verifications (
                    id SERIAL PRIMARY KEY,
                    task_id INTEGER,
                    snapshot_id TEXT,
                    status TEXT,
                    boot_time_seconds REAL,
                    network_check BOOLEAN,
                    app_check BOOLEAN,
                    verified_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    details JSONB DEFAULT '{}'
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hermes_queue (
                    id SERIAL PRIMARY KEY,
                    event_type TEXT,
                    payload TEXT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending'
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hermes_burst_sync_log (
                    id SERIAL PRIMARY KEY,
                    sequence_number INTEGER,
                    event_type TEXT,
                    payload TEXT,
                    synced_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hermes_sequence (
                    id SERIAL PRIMARY KEY,
                    last_seq INTEGER DEFAULT 0
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS detected_engines (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE,
                    path TEXT,
                    version TEXT,
                    installed BOOLEAN DEFAULT TRUE,
                    detected_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS engine_backup_statistics (
                    id SERIAL PRIMARY KEY,
                    engine TEXT,
                    repository_name TEXT,
                    total_backups INTEGER DEFAULT 0,
                    total_bytes BIGINT DEFAULT 0,
                    last_backup_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS imported_repositories (
                    id SERIAL PRIMARY KEY,
                    engine TEXT,
                    original_path TEXT,
                    repository_id INTEGER REFERENCES repositories(id) ON DELETE CASCADE,
                    imported_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS smtp_config (
                    id SERIAL PRIMARY KEY,
                    host TEXT,
                    port INTEGER DEFAULT 587,
                    username TEXT,
                    password TEXT,
                    from_email TEXT,
                    use_tls BOOLEAN DEFAULT TRUE,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS compliance_policies (
                    id SERIAL PRIMARY KEY,
                    framework TEXT NOT NULL,
                    policy_name TEXT NOT NULL,
                    rule_definition JSONB DEFAULT '{}',
                    enabled BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS compliance_audits (
                    id SERIAL PRIMARY KEY,
                    policy_id INTEGER REFERENCES compliance_policies(id) ON DELETE CASCADE,
                    score INTEGER DEFAULT 100,
                    status TEXT DEFAULT 'passed',
                    findings JSONB DEFAULT '[]',
                    audited_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS backup_patterns (
                    id SERIAL PRIMARY KEY,
                    task_id INTEGER,
                    pattern_type TEXT,
                    data JSONB DEFAULT '{}',
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id SERIAL PRIMARY KEY,
                    metric_name TEXT,
                    value DOUBLE PRECISION,
                    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_suggestions (
                    id SERIAL PRIMARY KEY,
                    category TEXT,
                    suggestion TEXT,
                    status TEXT DEFAULT 'new',
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS backup_settings (
                    id SERIAL PRIMARY KEY,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS error_log (
                    id SERIAL PRIMARY KEY,
                    error_code TEXT,
                    message TEXT,
                    stack_trace TEXT,
                    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
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
            cursor.execute("""
                ALTER TABLE job_failure_log ADD COLUMN IF NOT EXISTS task_id TEXT;
                ALTER TABLE job_failure_log ADD COLUMN IF NOT EXISTS task_name TEXT;
                ALTER TABLE job_failure_log ADD COLUMN IF NOT EXISTS execution_id TEXT;
                ALTER TABLE job_failure_log ADD COLUMN IF NOT EXISTS failure_reason TEXT;
                ALTER TABLE job_failure_log ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;
                ALTER TABLE job_failure_log ADD COLUMN IF NOT EXISTS max_retries INTEGER DEFAULT 3;
                ALTER TABLE job_failure_log ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'failed';
                ALTER TABLE job_failure_log ADD COLUMN IF NOT EXISTS alert_sent BOOLEAN DEFAULT FALSE;
                ALTER TABLE job_failure_log ADD COLUMN IF NOT EXISTS escalated BOOLEAN DEFAULT FALSE;
                ALTER TABLE job_failure_log ADD COLUMN IF NOT EXISTS first_failed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
                ALTER TABLE job_failure_log ADD COLUMN IF NOT EXISTS last_retried_at TIMESTAMPTZ;
                ALTER TABLE job_failure_log ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;
                CREATE INDEX IF NOT EXISTS idx_job_failure_log_task_status ON job_failure_log (task_id, status);
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_metrics (
                    id SERIAL PRIMARY KEY,
                    date TEXT UNIQUE,
                    total_backups INTEGER DEFAULT 0,
                    successful_backups INTEGER DEFAULT 0,
                    failed_backups INTEGER DEFAULT 0,
                    total_bytes BIGINT DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS engine_metrics (
                    id SERIAL PRIMARY KEY,
                    engine TEXT,
                    cpu_pct DOUBLE PRECISION DEFAULT 0,
                    mem_bytes BIGINT DEFAULT 0,
                    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_metrics (
                    id SERIAL PRIMARY KEY,
                    task_id INTEGER,
                    duration_sec INTEGER DEFAULT 0,
                    throughput_mbps DOUBLE PRECISION DEFAULT 0,
                    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS storage_usage_history (
                    id SERIAL PRIMARY KEY,
                    repository_id TEXT,
                    repository_name TEXT,
                    engine TEXT DEFAULT 'unknown',
                    path TEXT,
                    size_bytes BIGINT DEFAULT 0,
                    snapshot_count INTEGER DEFAULT 0,
                    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS storage_alert_config (
                    id SERIAL PRIMARY KEY,
                    alert_threshold_gb DOUBLE PRECISION DEFAULT 0,
                    alert_growth_pct_per_week DOUBLE PRECISION DEFAULT 0,
                    scan_interval_hours INTEGER DEFAULT 6,
                    last_scan_at TIMESTAMPTZ
                );
            """)

            # integrity_checks FK -> repositories: garantir ON DELETE CASCADE
            # SAVEPOINT: em instalação nova integrity_checks ainda não existe; sem ele o erro abortava a transação
            # inteira e o commit() final descartava TODAS as migrações desta execução (log dizia "sucesso").
            cursor.execute("SAVEPOINT fk_integrity_checks")
            try:
                cursor.execute("""
                    SELECT rc.delete_rule, tc.constraint_name
                    FROM information_schema.referential_constraints rc
                    JOIN information_schema.table_constraints tc
                      ON rc.constraint_name = tc.constraint_name
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.table_name = 'integrity_checks'
                      AND kcu.column_name = 'repository_id'
                    LIMIT 1
                """)
                row = cursor.fetchone()
                if row and row[0] == 'CASCADE':
                    logging.info("👍 'integrity_checks' FK already ON DELETE CASCADE.")
                else:
                    if row and row[1]:
                        fk_name = row[1]
                        cursor.execute(f"ALTER TABLE integrity_checks DROP CONSTRAINT IF EXISTS {fk_name}")
                    cursor.execute("""
                        ALTER TABLE integrity_checks
                        ADD CONSTRAINT integrity_checks_repository_id_fkey
                        FOREIGN KEY (repository_id)
                        REFERENCES repositories(id)
                        ON DELETE CASCADE
                    """)
                    logging.info("✅ integrity_checks FK ajustada para ON DELETE CASCADE")
                cursor.execute("RELEASE SAVEPOINT fk_integrity_checks")
            except Exception as e:
                # tabela pode não existir ainda em algumas instalações
                cursor.execute("ROLLBACK TO SAVEPOINT fk_integrity_checks")
                logging.info(f"ℹ️ Migração FK integrity_checks ignorada: {e}")

            migrations_run += 1

            conn.commit()

            logging.info("🎉 Database migration completed successfully!")

        except Exception as e:

            logging.error(f"❌ Migration failed: {e}", exc_info=True)

            errors.append(str(e))

            conn.rollback()



    return {"migrations_run": migrations_run, "errors": errors}