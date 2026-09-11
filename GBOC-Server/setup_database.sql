-- ==============================================================================
-- GBOC System v14.1.0 Enterprise Edition
-- Copyright (c) 2026 Master11BR - Todos os direitos reservados.
-- Propriedade Intelectual & Direitos Autorais Registrados.
-- ==============================================================================

-- Script de Criação e Inicialização Autoritativa do Banco de Dados GBOC (PostgreSQL)
-- Execute como superusuário do PostgreSQL (postgres)

-- 1. Cria o usuário (idempotente)
DO $$
BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gboc_user') THEN
      CREATE ROLE gboc_user LOGIN PASSWORD 'Stoms2025+';
   END IF;
END $$;

-- 2. Cria o banco se não existir (fora de transação implícita)
SELECT 'CREATE DATABASE gboc OWNER gboc_user'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gboc')\gexec

-- 3. Conecta no banco gboc
\c gboc

-- 4. Garantir owner e permissões no schema public
ALTER DATABASE gboc OWNER TO gboc_user;
GRANT ALL PRIVILEGES ON DATABASE gboc TO gboc_user;
ALTER SCHEMA public OWNER TO gboc_user;
GRANT USAGE, CREATE ON SCHEMA public TO gboc_user;

-- 5. Tabelas do Servidor Central GBOC

-- 5.1 MSP Organizations
CREATE TABLE IF NOT EXISTS msp_organizations (
    org_id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    plan VARCHAR(50) DEFAULT 'Standard',
    max_agents INTEGER DEFAULT 25,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5.2 Agents
CREATE TABLE IF NOT EXISTS agents (
    agent_id VARCHAR(100) PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL,
    ip_address VARCHAR(45),
    os_info TEXT,
    agent_version VARCHAR(50),
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_heartbeat TIMESTAMP,
    status VARCHAR(20) DEFAULT 'offline',
    cpu_usage REAL DEFAULT 0,
    ram_usage REAL DEFAULT 0,
    disk_usage REAL DEFAULT 0,
    jobs_count INTEGER DEFAULT 0,
    available_tools TEXT,
    jobs_summary TEXT,
    tenant_id VARCHAR(100) REFERENCES msp_organizations(org_id) ON DELETE SET NULL
);

-- 5.3 Backup Reports
CREATE TABLE IF NOT EXISTS backup_reports (
    report_id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) REFERENCES agents(agent_id) ON DELETE CASCADE,
    backup_type VARCHAR(50),
    source_path TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_seconds INTEGER,
    total_files INTEGER DEFAULT 0,
    total_bytes BIGINT DEFAULT 0,
    status VARCHAR(20),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    snapshot_id TEXT,
    files_new INTEGER DEFAULT 0,
    files_changed INTEGER DEFAULT 0
);

-- 5.4 Agent Tasks
CREATE TABLE IF NOT EXISTS agent_tasks (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) REFERENCES agents(agent_id) ON DELETE CASCADE,
    task_id INTEGER,
    name TEXT,
    status TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (agent_id, task_id)
);

-- 5.5 Agent Logs
CREATE TABLE IF NOT EXISTS agent_logs (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) REFERENCES agents(agent_id) ON DELETE CASCADE,
    level TEXT,
    source TEXT,
    message TEXT,
    details TEXT,
    timestamp TIMESTAMP,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5.6 System Events
CREATE TABLE IF NOT EXISTS system_events (
    event_id SERIAL PRIMARY KEY,
    event_type VARCHAR(50),
    message TEXT,
    agent_hostname VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_read BOOLEAN DEFAULT FALSE
);

-- 5.7 Agent Metrics
CREATE TABLE IF NOT EXISTS agent_metrics (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) REFERENCES agents(agent_id) ON DELETE CASCADE,
    cpu_usage REAL,
    ram_usage REAL,
    disk_usage REAL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5.8 Agent Task Executions
CREATE TABLE IF NOT EXISTS agent_task_executions (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) REFERENCES agents(agent_id) ON DELETE CASCADE,
    task_id INTEGER,
    execution_id INTEGER,
    status TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds REAL,
    files_processed INTEGER DEFAULT 0,
    bytes_processed BIGINT DEFAULT 0,
    error_message TEXT,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (agent_id, task_id, execution_id)
);

-- 5.9 Agent Repositories
CREATE TABLE IF NOT EXISTS agent_repositories (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) REFERENCES agents(agent_id) ON DELETE CASCADE,
    repo_id INTEGER,
    name TEXT,
    engine VARCHAR(50) DEFAULT 'restic',
    type VARCHAR(50) DEFAULT 'local',
    status VARCHAR(20) DEFAULT 'active',
    last_backup TIMESTAMP,
    total_backups INTEGER DEFAULT 0,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (agent_id, repo_id)
);

-- 5.10 Agent Statistics
CREATE TABLE IF NOT EXISTS agent_statistics (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) REFERENCES agents(agent_id) ON DELETE CASCADE,
    task_id INTEGER,
    task_name TEXT,
    repository_name TEXT,
    backup_date TIMESTAMP,
    success BOOLEAN DEFAULT FALSE,
    duration_seconds REAL DEFAULT 0,
    bytes_processed BIGINT DEFAULT 0,
    files_processed INTEGER DEFAULT 0,
    error_message TEXT,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5.11 Server Auth Users
CREATE TABLE IF NOT EXISTS server_auth_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    role VARCHAR(50) DEFAULT 'admin',
    tenant_id VARCHAR(100) REFERENCES msp_organizations(org_id) ON DELETE SET NULL,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

-- 5.12 Server Auth Tokens
CREATE TABLE IF NOT EXISTS server_auth_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES server_auth_users(id) ON DELETE CASCADE,
    token VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL
);

-- 5.13 Server Auth Audit
CREATE TABLE IF NOT EXISTS server_auth_audit (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES server_auth_users(id) ON DELETE SET NULL,
    username VARCHAR(100),
    action VARCHAR(100) NOT NULL,
    ip_address VARCHAR(45),
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5.14 Server Settings
CREATE TABLE IF NOT EXISTS server_settings (
    id SERIAL PRIMARY KEY,
    category VARCHAR(50) NOT NULL,
    key VARCHAR(100) NOT NULL,
    value TEXT,
    type VARCHAR(20) DEFAULT 'text',
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, key)
);

-- 5.15 Hermes Agent Stats
CREATE TABLE IF NOT EXISTS hermes_agent_stats (
    agent_id          VARCHAR(100) PRIMARY KEY REFERENCES agents(agent_id) ON DELETE CASCADE,
    pending_messages  INTEGER DEFAULT 0,
    mesh_peers_online INTEGER DEFAULT 0,
    throttle_mbps     REAL DEFAULT 0,
    heal_events_count INTEGER DEFAULT 0,
    last_burst_sync_at TIMESTAMP,
    burst_sync_count  INTEGER DEFAULT 0,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5.16 Hermes Burst Sync Log
CREATE TABLE IF NOT EXISTS hermes_burst_sync_log (
    id              SERIAL PRIMARY KEY,
    agent_id        VARCHAR(100) REFERENCES agents(agent_id) ON DELETE CASCADE,
    sequence_number INTEGER,
    event_type      TEXT,
    payload_json    TEXT,
    synced_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (agent_id, sequence_number)
);

-- 5.17 Power Tools Agent Stats
CREATE TABLE IF NOT EXISTS power_tools_agent_stats (
    agent_id                VARCHAR(100) PRIMARY KEY REFERENCES agents(agent_id) ON DELETE CASCADE,
    last_scrub_at           TIMESTAMP,
    integrity_health_pct    REAL DEFAULT 100.0,
    corrupted_blocks        INTEGER DEFAULT 0,
    repaired_blocks         INTEGER DEFAULT 0,
    last_rdr_at             TIMESTAMP,
    last_rdr_time_saved_pct REAL DEFAULT 0,
    last_rdr_sectors_written BIGINT DEFAULT 0,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5.18 Storage Usage History
CREATE TABLE IF NOT EXISTS storage_usage_history (
    id SERIAL PRIMARY KEY,
    repository_id TEXT,
    repository_name TEXT,
    engine TEXT DEFAULT 'unknown',
    path TEXT,
    size_bytes BIGINT DEFAULT 0,
    snapshot_count INTEGER DEFAULT 0,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5.19 Storage Alert Config
CREATE TABLE IF NOT EXISTS storage_alert_config (
    id SERIAL PRIMARY KEY,
    alert_threshold_gb REAL DEFAULT 0,
    alert_growth_pct_per_week REAL DEFAULT 0,
    scan_interval_hours INTEGER DEFAULT 6,
    last_scan_at TIMESTAMP WITH TIME ZONE
);

-- 5.20 Storage Destinations
CREATE TABLE IF NOT EXISTS storage_destinations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) DEFAULT 's3',
    bucket VARCHAR(255),
    provider VARCHAR(100),
    region VARCHAR(50),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5.21 Ransomware Agent Snapshots
CREATE TABLE IF NOT EXISTS ransomware_agent_snapshots (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) NOT NULL,
    agent_hostname VARCHAR(255),
    snapshot_type VARCHAR(100) NOT NULL,
    payload_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5.22 Ransomware AI Diagnostics
CREATE TABLE IF NOT EXISTS ransomware_ai_diagnostics (
    id SERIAL PRIMARY KEY,
    scope VARCHAR(50) NOT NULL,
    node_id VARCHAR(150),
    threat_score INTEGER DEFAULT 0,
    status VARCHAR(50),
    summary TEXT,
    details_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5.23 Ransomware Central Events
CREATE TABLE IF NOT EXISTS ransomware_central_events (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) NOT NULL,
    agent_hostname VARCHAR(255),
    event_type VARCHAR(120),
    message TEXT,
    event_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5.24 Ransomware Central Incidents
CREATE TABLE IF NOT EXISTS ransomware_central_incidents (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) NOT NULL,
    incident_external_id VARCHAR(100),
    status VARCHAR(50),
    detected_at TIMESTAMP,
    resolved_at TIMESTAMP,
    threat_info_json TEXT,
    response_actions_json TEXT,
    raw_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(agent_id, incident_external_id)
);

-- 6. Inserir dados padrão (Se tabelas estiverem vazias)

-- Populate Initial MSP Orgs
INSERT INTO msp_organizations (org_id, name, plan, max_agents, status)
VALUES 
    ('org-master', 'Master Enterprise MSP', 'Enterprise 10x', 250, 'active'),
    ('org-filial-01', 'Filial São Paulo (Financeiro)', 'Pro Managed', 50, 'active'),
    ('org-filial-02', 'Filial Rio de Janeiro (Operações)', 'Standard', 25, 'active')
ON CONFLICT (org_id) DO NOTHING;

-- Populate Storage Alert Config default
INSERT INTO storage_alert_config (id, alert_threshold_gb, alert_growth_pct_per_week, scan_interval_hours)
VALUES (1, 500.0, 15.0, 6)
ON CONFLICT (id) DO NOTHING;

-- 7. Concede privilégios em objetos existentes e futuros
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO gboc_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO gboc_user;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO gboc_user;

ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO gboc_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO gboc_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO gboc_user;

\echo '✓ Banco de dados GBOC v14.1.0 pronto com todas as 24 tabelas autoritativas criadas!'
