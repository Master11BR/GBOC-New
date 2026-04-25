#!/usr/bin/env python3
"""
GBOC Agent - Database Migrator
"""
import logging
import os
import sys

# Add the parent directory to the path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run_auto_migrations(conn):

    """Runs the database migration."""

    logging.info("🚀 Starting database migration...")

    migrations_run = 0

    errors = []

    

    with conn.cursor() as cursor:

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

            # integrity_checks FK -> repositories: garantir ON DELETE CASCADE
            try:
                cursor.execute("""
                    SELECT tc.constraint_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.table_name = 'integrity_checks'
                      AND tc.constraint_type = 'FOREIGN KEY'
                      AND kcu.column_name = 'repository_id'
                    LIMIT 1
                """)
                row = cursor.fetchone()
                if row and row[0]:
                    fk_name = row[0]
                    cursor.execute(f"ALTER TABLE integrity_checks DROP CONSTRAINT IF EXISTS {fk_name}")
                cursor.execute("""
                    ALTER TABLE integrity_checks
                    ADD CONSTRAINT integrity_checks_repository_id_fkey
                    FOREIGN KEY (repository_id)
                    REFERENCES repositories(id)
                    ON DELETE CASCADE
                """)
                logging.info("✅ integrity_checks FK ajustada para ON DELETE CASCADE")
            except Exception as e:
                # tabela pode não existir ainda em algumas instalações
                logging.info(f"ℹ️ Migração FK integrity_checks ignorada: {e}")

            migrations_run += 1

            conn.commit()

            logging.info("🎉 Database migration completed successfully!")

        except Exception as e:

            logging.error(f"❌ Migration failed: {e}", exc_info=True)

            errors.append(str(e))

            conn.rollback()



    return {"migrations_run": migrations_run, "errors": errors}