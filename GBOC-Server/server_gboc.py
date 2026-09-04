"""
GBOC Server 14.0.0
Servidor Central — Real-time Agent Communication + Complete Data Sync + Advanced Analytics
Banco de dados: PostgreSQL (oficial)
"""
import os
import json
import logging
import asyncio
import hashlib
import secrets
import datetime as _datetime_mod
from datetime import datetime as _dt, timedelta, timezone
from decimal import Decimal
from typing import Optional, List, Any, Dict
from contextlib import asynccontextmanager
import threading
import time

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool

import uvicorn

# ===========================
# CONFIGURAÇÃO
# ===========================

# Dynamic SemVer 2.0 versioning
try:
    from version_control import __version__ as SERVER_VERSION, get_version_info, auto_increment_build
    auto_increment_build()
except Exception:
    SERVER_VERSION = "14.0.0"
    def get_version_info():
        return {"raw_version": SERVER_VERSION, "semver": SERVER_VERSION}

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Configuração do Banco PostgreSQL
DB_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', 5432)),
    'database': os.getenv('POSTGRES_DB', 'gboc'),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'Stoms2025+'),
    'options': '-c timezone=America/Sao_Paulo'
}

connection_pool = None
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Gerenciamento de conexões WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.agent_data: Dict[str, Dict] = {}

    async def connect(self, websocket: WebSocket, agent_id: str):
        await websocket.accept()
        self.active_connections[agent_id] = websocket
        logger.info(f"🔗 Agente {agent_id} conectado via WebSocket")

    def disconnect(self, agent_id: str):
        if agent_id in self.active_connections:
            del self.active_connections[agent_id]
            logger.info(f"🔌 Agente {agent_id} desconectado")

    async def send_personal_message(self, message: str, agent_id: str):
        if agent_id in self.active_connections:
            await self.active_connections[agent_id].send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections.values():
            await connection.send_text(message)

    def update_agent_data(self, agent_id: str, data: Dict):
        self.agent_data[agent_id] = data

    def get_agent_data(self, agent_id: str) -> Optional[Dict]:
        return self.agent_data.get(agent_id)

    def get_all_agents_data(self) -> Dict[str, Dict]:
        return self.agent_data.copy()

manager = ConnectionManager()

# ===========================
# BANCO DE DADOS
# ===========================

def init_connection_pool():
    global connection_pool
    try:
        logger.info("Inicializando pool PostgreSQL...")
        connection_pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=30, **DB_CONFIG)
        logger.info("✓ Pool PostgreSQL inicializado")
        return True
    except Exception as e:
        logger.error(f"✗ Erro PostgreSQL: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def get_db():
    global connection_pool
    if not connection_pool:
        raise HTTPException(503, "Pool de conexões não inicializado")
    try:
        conn = connection_pool.getconn()
        conn.set_client_encoding('UTF8')
        # Verificar se a conexão está viva
        try:
            conn.cursor().execute("SELECT 1")
        except Exception:
            # Conexão morta, descartar e pegar nova
            try:
                connection_pool.putconn(conn, close=True)
            except Exception:
                pass
            conn = connection_pool.getconn()
            conn.set_client_encoding('UTF8')
        return conn
    except psycopg2.pool.PoolError:
        # Pool esgotado, tentar recriar
        logger.warning("Pool esgotado, recriando...")
        try:
            connection_pool.closeall()
        except Exception:
            pass
        connection_pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=30, **DB_CONFIG)
        conn = connection_pool.getconn()
        conn.set_client_encoding('UTF8')
        return conn
    except Exception:
        raise HTTPException(503, "DB Ocupado")

def release_db(conn):
    if connection_pool and conn:
        try:
            if conn.closed:
                connection_pool.putconn(conn, close=True)
            else:
                conn.rollback()  # Limpar transação pendente
                connection_pool.putconn(conn)
        except:
            pass

def init_database():
    conn = None
    try:
        logger.info("Inicializando banco de dados PostgreSQL...")
        conn = get_db()
        cur = conn.cursor()

        cur.execute('''
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
                jobs_summary TEXT
            )
        ''')

        cur.execute('''
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
            )
        ''')

        cur.execute('''
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
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS agent_logs (
                id SERIAL PRIMARY KEY,
                agent_id VARCHAR(100) REFERENCES agents(agent_id) ON DELETE CASCADE,
                level TEXT,
                source TEXT,
                message TEXT,
                details TEXT,
                timestamp TIMESTAMP,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS system_events (
                event_id SERIAL PRIMARY KEY,
                event_type VARCHAR(50),
                message TEXT,
                agent_hostname VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_read BOOLEAN DEFAULT FALSE
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS agent_metrics (
                id SERIAL PRIMARY KEY,
                agent_id VARCHAR(100) REFERENCES agents(agent_id) ON DELETE CASCADE,
                cpu_usage REAL,
                ram_usage REAL,
                disk_usage REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cur.execute('''
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
            )
        ''')

        # Tabela de repositórios sincronizados dos agentes
        cur.execute('''
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
            )
        ''')

        # Tabela de estatísticas de backup sincronizadas dos agentes
        cur.execute('''
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
            )
        ''')

        # Adicionar colunas extras se não existirem
        for col in ['jobs_summary', 'available_tools']:
            try:
                cur.execute(f"ALTER TABLE agents ADD COLUMN IF NOT EXISTS {col} TEXT")
            except:
                conn.rollback()

        # Tabela de organizações Multi-Tenant MSP
        cur.execute('''
            CREATE TABLE IF NOT EXISTS msp_organizations (
                org_id VARCHAR(100) PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL,
                plan VARCHAR(50) DEFAULT 'Standard',
                max_agents INTEGER DEFAULT 25,
                status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''');

        # Popular organizações iniciais se tabela vazia
        cur.execute("SELECT COUNT(*) FROM msp_organizations")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                INSERT INTO msp_organizations (org_id, name, plan, max_agents, status)
                VALUES 
                ('org-master', 'Master Enterprise MSP', 'Enterprise 10x', 250, 'active'),
                ('org-filial-01', 'Filial São Paulo (Financeiro)', 'Pro Managed', 50, 'active'),
                ('org-filial-02', 'Filial Rio de Janeiro (Operações)', 'Standard', 25, 'active')
            """)

        # Tabela de autenticação do servidor
        cur.execute('''
            CREATE TABLE IF NOT EXISTS server_auth_users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(255),
                role VARCHAR(50) DEFAULT 'admin',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        ''')

        # Adicionar colunas extras na tabela de usuários e agentes para Multi-Tenant
        cur.execute("ALTER TABLE server_auth_users ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) REFERENCES msp_organizations(org_id) ON DELETE SET NULL")
        cur.execute("ALTER TABLE server_auth_users ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active'")
        cur.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) REFERENCES msp_organizations(org_id) ON DELETE SET NULL")


        cur.execute('''
            CREATE TABLE IF NOT EXISTS server_auth_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES server_auth_users(id) ON DELETE CASCADE,
                token VARCHAR(255) UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS server_auth_audit (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES server_auth_users(id) ON DELETE SET NULL,
                username VARCHAR(100),
                action VARCHAR(100) NOT NULL,
                ip_address VARCHAR(45),
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Tabela de configurações do servidor
        cur.execute('''
            CREATE TABLE IF NOT EXISTS server_settings (
                id SERIAL PRIMARY KEY,
                category VARCHAR(50) NOT NULL,
                key VARCHAR(100) NOT NULL,
                value TEXT,
                type VARCHAR(20) DEFAULT 'text',
                description TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, key)
            )
        ''')

        # Inserir defaults se tabela vazia
        cur.execute("SELECT COUNT(*) FROM server_settings")
        if cur.fetchone()[0] == 0:
            _defaults = [
                ('general', 'server_name', 'GBOC Server', 'text', 'Nome do servidor'),
                ('general', 'timezone', 'America/Sao_Paulo', 'text', 'Fuso horário'),
                ('general', 'session_timeout_hours', '24', 'number', 'Timeout de sessão (horas)'),
                ('general', 'max_agents', '50', 'number', 'Máximo de agentes simultâneos'),
                ('sync', 'heartbeat_interval_seconds', '30', 'number', 'Intervalo de heartbeat (seg)'),
                ('sync', 'agent_offline_threshold_minutes', '60', 'number', 'Tempo para considerar agente offline (min)'),
                ('sync', 'auto_sync_enabled', 'true', 'boolean', 'Sincronização automática habilitada'),
                ('sync', 'sync_interval_seconds', '300', 'number', 'Intervalo de sync completo (seg)'),
                ('security', 'require_auth', 'true', 'boolean', 'Exigir autenticação'),
                ('security', 'max_login_attempts', '5', 'number', 'Máximo de tentativas de login'),
                ('security', 'lockout_duration_minutes', '15', 'number', 'Duração do bloqueio (min)'),
                ('security', 'password_min_length', '8', 'number', 'Tamanho mínimo da senha'),
                ('security', 'cors_origins', '*', 'text', 'Origens CORS permitidas'),
                ('database', 'pool_min_connections', '2', 'number', 'Mínimo de conexões no pool'),
                ('database', 'pool_max_connections', '10', 'number', 'Máximo de conexões no pool'),
                ('database', 'query_timeout_seconds', '30', 'number', 'Timeout de query (seg)'),
                ('retention', 'metrics_retention_days', '90', 'number', 'Retenção de métricas (dias)'),
                ('retention', 'logs_retention_days', '30', 'number', 'Retenção de logs (dias)'),
                ('retention', 'events_retention_days', '60', 'number', 'Retenção de eventos (dias)'),
                ('retention', 'reports_retention_days', '365', 'number', 'Retenção de relatórios (dias)'),
                ('notifications', 'email_enabled', 'false', 'boolean', 'Notificações por e-mail'),
                ('notifications', 'smtp_host', '', 'text', 'Servidor SMTP'),
                ('notifications', 'smtp_port', '587', 'number', 'Porta SMTP'),
                ('notifications', 'smtp_username', '', 'text', 'Usuário SMTP'),
                ('notifications', 'smtp_password', '', 'password', 'Senha SMTP'),
                ('notifications', 'smtp_from', '', 'text', 'E-mail remetente'),
                ('notifications', 'smtp_to', '', 'text', 'E-mail(s) destinatário(s)'),
                ('notifications', 'webhook_enabled', 'false', 'boolean', 'Notificações por webhook'),
                ('notifications', 'webhook_url', '', 'text', 'URL do webhook'),
                ('ui', 'default_theme', 'dark', 'select:dark,light', 'Tema padrão'),
                ('ui', 'auto_refresh_seconds', '30', 'number', 'Intervalo de auto-refresh (seg)'),
                ('ui', 'dashboard_max_agents', '20', 'number', 'Máximo de agentes no dashboard'),
                ('ui', 'date_format', 'DD/MM/YYYY', 'text', 'Formato de data'),
            ]
            for cat, key, val, typ, desc in _defaults:
                cur.execute("""
                    INSERT INTO server_settings (category, key, value, type, description)
                    VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                """, (cat, key, val, typ, desc))

        # ── Hermes Agent Stats (fila offline, mesh, bandwidth por agente) ──────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS hermes_agent_stats (
                agent_id          VARCHAR(100) PRIMARY KEY REFERENCES agents(agent_id) ON DELETE CASCADE,
                pending_messages  INTEGER DEFAULT 0,
                mesh_peers_online INTEGER DEFAULT 0,
                throttle_mbps     REAL DEFAULT 0,
                heal_events_count INTEGER DEFAULT 0,
                last_burst_sync_at TIMESTAMP,
                burst_sync_count  INTEGER DEFAULT 0,
                updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ── Hermes Burst Sync Log (mensagens da fila offline persistidas) ────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS hermes_burst_sync_log (
                id              SERIAL PRIMARY KEY,
                agent_id        VARCHAR(100) REFERENCES agents(agent_id) ON DELETE CASCADE,
                sequence_number INTEGER,
                event_type      TEXT,
                payload_json    TEXT,
                synced_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (agent_id, sequence_number)
            )
        ''')

        # ── Power Tools Agent Stats (bitrot, RDR) ────────────────────────────
        cur.execute('''
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
            )
        ''')

        conn.commit()
        logger.info("✓ Banco de dados PostgreSQL inicializado com todas as tabelas (incluindo Hermes + Power Tools).")
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"✗ Erro DB Init: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        if 'cur' in locals() and cur:
            cur.close()
        release_db(conn)

def log_event(conn, event_type, message, hostname=None):
    try:
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO system_events (event_type, message, agent_hostname, created_at)
            VALUES (%s, %s, %s, LOCALTIMESTAMP)
        ''', (event_type, message, hostname))
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error(f"Erro ao logar evento: {e}")

# ===========================
# MODELOS
# ===========================

class AgentRegister(BaseModel):
    agent_id: str
    hostname: str
    ip_address: Optional[str] = None
    os_info: Optional[str] = None
    agent_version: Optional[str] = None
    available_tools: Optional[Any] = []
    tenant_id: Optional[str] = None

class AgentHeartbeat(BaseModel):
    agent_id: str
    hostname: str
    status: str
    cpu_usage: Optional[float] = 0.0
    ram_usage: Optional[float] = 0.0
    disk_usage: Optional[float] = 0.0
    timestamp: Optional[str] = None
    jobs_count: Optional[int] = 0
    jobs_summary: Optional[Any] = None
    tenant_id: Optional[str] = None

class BackupReport(BaseModel):
    agent_id: str
    job_name: Optional[str] = None
    source_path: Optional[str] = None 
    backup_type: Optional[str] = "Automated"
    start_time: str
    end_time: str
    duration_seconds: float
    status: str
    files_new: Optional[int] = 0
    files_changed: Optional[int] = 0
    data_added: Optional[int] = 0
    total_bytes: Optional[int] = 0


def ensure_agent_exists(conn, agent_id: str, data: Optional[Dict] = None):
    """Garante que o agente exista na tabela agents antes de salvar métricas/sync."""
    payload = data or {}
    cur = conn.cursor()
    hostname = payload.get('hostname') or payload.get('agent_name') or agent_id[:12]
    ip_address = payload.get('ip_address') or payload.get('ip') or '127.0.0.1'
    os_info = payload.get('os_info') or payload.get('os') or 'unknown'
    agent_version = payload.get('agent_version') or payload.get('version') or 'unknown'
    available_tools = payload.get('available_tools') or []
    tools = json.dumps(available_tools) if not isinstance(available_tools, str) else available_tools
    tenant_id = payload.get('tenant_id')
    cur.execute('''
        INSERT INTO agents (agent_id, hostname, ip_address, os_info, agent_version, available_tools, last_heartbeat, status, tenant_id)
        VALUES (%s, %s, %s, %s, %s, %s, LOCALTIMESTAMP, 'online', %s)
        ON CONFLICT (agent_id) DO UPDATE SET
            hostname = COALESCE(EXCLUDED.hostname, agents.hostname),
            ip_address = COALESCE(EXCLUDED.ip_address, agents.ip_address),
            os_info = COALESCE(EXCLUDED.os_info, agents.os_info),
            agent_version = COALESCE(EXCLUDED.agent_version, agents.agent_version),
            available_tools = COALESCE(EXCLUDED.available_tools, agents.available_tools),
            last_heartbeat = LOCALTIMESTAMP,
            status = 'online',
            tenant_id = COALESCE(EXCLUDED.tenant_id, agents.tenant_id)
    ''', (agent_id, hostname, ip_address, os_info, agent_version, tools, tenant_id))
    snapshot_id: Optional[str] = None
    error: Optional[str] = None

class AgentFullData(BaseModel):
    """Dados completos do agente para sincronização em tempo real"""
    agent_id: str
    hostname: str
    status: str
    version: str
    ip_address: str
    cpu_usage: float
    ram_usage: float
    disk_usage: float
    ip_public: Optional[str] = None
    agent_local_time: str
    os_info: str
    cpu_cores: int
    ram_total_gb: str
    ram_available_gb: str
    component_count: int  # Repositórios
    target_count: int     # Tarefas
    scheduler_status: str
    execution_mode: str
    jobs_running_count: int
    jobs_failed_list: List[int]
    repositories: List[Dict] = []
    tasks: List[Dict] = []
    task_executions: List[Dict] = []
    system_events: List[Dict] = []
    alerts: List[Dict] = []
    timestamp: str
    tenant_id: Optional[str] = None

class ManualSyncRequest(BaseModel):
    """Requisição de sincronização manual"""
    agent_id: str
    sync_type: str  # "full", "incremental", "repositories", "tasks", etc.
    since_timestamp: Optional[str] = None

class TaskSyncData(BaseModel):
    agent_id: str
    tasks: List[Dict[str, Any]]

class LogSyncData(BaseModel):
    agent_id: str
    logs: List[Dict[str, Any]]

# ===========================
# AUTENTICAÇÃO DO SERVIDOR
# ===========================

def _hash_password(password: str) -> str:
    salt = "gboc_server_salt_2025"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

def _generate_token() -> str:
    return secrets.token_hex(32)

def _is_server_auth_enabled() -> bool:
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM server_auth_users")
        count = cur.fetchone()[0]
        cur.close()
        return count > 0
    except Exception:
        return False
    finally:
        release_db(conn)

def _validate_server_token(token: str) -> Optional[Dict]:
    if not token:
        return None
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT u.id, u.username, u.display_name, u.role, u.tenant_id
            FROM server_auth_tokens t
            JOIN server_auth_users u ON t.user_id = u.id
            WHERE t.token = %s AND t.expires_at > LOCALTIMESTAMP
        """, (token,))
        row = cur.fetchone()
        cur.close()
        if row:
            return {"user_id": row[0], "username": row[1], "display_name": row[2], "role": row[3], "tenant_id": row[4]}
        return None
    except Exception:
        return None
    finally:
        release_db(conn)

def _get_server_user_from_request(request: Request) -> Optional[Dict]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return _validate_server_token(auth_header[7:])
    token = request.cookies.get("gboc_server_token")
    if token:
        return _validate_server_token(token)
    return None

class ServerLoginRequest(BaseModel):
    username: str
    password: str

class ServerSetupRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None

# ===========================
# API & ENDPOINTS
# ===========================

@asynccontextmanager
async def lifespan(app: FastAPI):
    if init_connection_pool():
        init_database()
        # Limpar todos os tokens ao reiniciar — garante que o browser pede login novamente
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("DELETE FROM server_auth_tokens")
            conn.commit()
            cur.close()
            release_db(conn)
        except Exception:
            pass
    yield
    if connection_pool:
        connection_pool.closeall()

app = FastAPI(title="GBOC Server", version=SERVER_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

from fastapi.staticfiles import StaticFiles
modules_dir = os.path.join(os.path.dirname(__file__), "modules")
if os.path.exists(modules_dir):
    app.mount("/modules", StaticFiles(directory=modules_dir), name="modules")

# Módulos do GBOC Server (Estrito)
try:
    from modules.storage.storage_router import router as server_storage_router
    app.include_router(server_storage_router)
    from modules.job_alert.job_alert_router import router as server_job_alert_router
    app.include_router(server_job_alert_router)
    from modules.hardware.hardware_router import router as hardware_router
    app.include_router(hardware_router)
    from modules.v2.v2_router import v2_router
    app.include_router(v2_router)
    # ======================================================================
    # GBOC SERVER ENTERPRISE & HERMES MODULES
    # ======================================================================
    from modules.hermes.hermes_server_router import router as hermes_server_router
    app.include_router(hermes_server_router)
    from modules.compliance.compliance_server_router import router as compliance_server_router
    app.include_router(compliance_server_router)
    from modules.cdp.cdp_server_router import router as cdp_server_router
    app.include_router(cdp_server_router)
    from modules.saas_cloud.saas_cloud_server_router import router as saas_cloud_server_router
    app.include_router(saas_cloud_server_router)
    from modules.cyber.cyber_server_router import router as cyber_server_router
    app.include_router(cyber_server_router)
    from modules.power_tools.power_tools_server_router import router as power_tools_server_router
    app.include_router(power_tools_server_router)
    from modules.engine_migration.engine_migration_router import router as engine_migration_router
    app.include_router(engine_migration_router)
except Exception as _e:
    logger.warning(f"Falha ao incluir roteadores de módulos no Servidor Central: {_e}")

# Endpoints estáticos de Layout Manager (Vertical / Horizontal + Temas)
@app.get("/static/gboc-layout-manager.js", include_in_schema=False)
@app.get("/gboc-layout-manager.js", include_in_schema=False)
async def get_layout_manager():
    return FileResponse(os.path.join(os.path.dirname(__file__), "gboc-layout-manager.js"), media_type="application/javascript")

@app.get("/static/ai_assistant.js", include_in_schema=False)
@app.get("/ai_assistant.js", include_in_schema=False)
async def get_ai_assistant_js():
    return FileResponse(os.path.join(os.path.dirname(__file__), "ai_assistant.js"), media_type="application/javascript")

@app.get("/static/_topbar.html", include_in_schema=False)
@app.get("/_topbar.html", include_in_schema=False)
async def get_topbar_html():
    return FileResponse(os.path.join(os.path.dirname(__file__), "_topbar.html"), media_type="text/html")

@app.get("/static/gboc-layout.css", include_in_schema=False)
@app.get("/gboc-layout.css", include_in_schema=False)
async def get_layout_css():
    return FileResponse(os.path.join(os.path.dirname(__file__), "gboc-layout.css"), media_type="text/css")

@app.get("/static/gboc-themes.css", include_in_schema=False)
@app.get("/gboc-themes.css", include_in_schema=False)
async def get_themes_css():
    return FileResponse(os.path.join(os.path.dirname(__file__), "gboc-themes.css"), media_type="text/css")

# ==============================================================================
# Dynamic SemVer 2.0 Versioning & System Endpoints
# ==============================================================================
@app.get("/api/v1/version", tags=["System"])
@app.get("/api/v1/system/version", tags=["System"])
@app.get("/api/system/info", tags=["System"])
@app.get("/api/system/version", tags=["System"])
async def get_server_version_endpoint():
    """Retorna informações detalhadas do versionamento semântico 2.0."""
    info = get_version_info()
    if isinstance(info, dict):
        info["gboc_version"] = info.get("semver") or SERVER_VERSION
        info["version"] = info.get("semver") or SERVER_VERSION
        info["status"] = "success"
    return info

# Rota estática universal para recursos da pasta /static/
@app.get("/static/{filename:path}", include_in_schema=False)
async def serve_static_asset(filename: str):
    clean_fn = (filename or '').lstrip("/\\")
    if clean_fn.startswith("static/") or clean_fn.startswith("static\\"):
        clean_fn = clean_fn[7:]
    srv_file = os.path.join(os.path.dirname(__file__), clean_fn)
    if os.path.isfile(srv_file):
        return FileResponse(srv_file)
    agt_file = os.path.join(os.path.dirname(__file__), "..", "GBOC-Agent", "static", clean_fn)
    if os.path.isfile(agt_file):
        return FileResponse(agt_file)
    raise HTTPException(404, f"Arquivo estático '{filename}' não encontrado.")

# Rota dinâmica universal para páginas HTML (resolve erro 404 {"detail":"Not Found"})
@app.get("/{page_name:path}.html", include_in_schema=False)
async def serve_any_html_page(page_name: str):
    clean_p = (page_name or '').lstrip("/\\")
    if clean_p.startswith("static/") or clean_p.startswith("static\\"):
        clean_p = clean_p[7:]
    fname = f"{clean_p}.html" if not clean_p.endswith(".html") else clean_p
    # 1. Procurar em GBOC-Server
    srv_file = os.path.join(os.path.dirname(__file__), fname)
    if os.path.isfile(srv_file):
        return FileResponse(srv_file, media_type="text/html")
    # 2. Procurar em GBOC-Agent/static
    agt_file = os.path.join(os.path.dirname(__file__), "..", "GBOC-Agent", "static", fname)
    if os.path.isfile(agt_file):
        return FileResponse(agt_file, media_type="text/html")
    # 3. Fallback para dashboard.html
    dash_file = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.isfile(dash_file):
        return FileResponse(dash_file, media_type="text/html")
    raise HTTPException(404, f"Página '{fname}' não encontrada.")

# ===========================
# AUTH ENDPOINTS
# ===========================

@app.get("/login.html", include_in_schema=False)
async def login_page():
    candidates = [
        os.path.join(os.path.dirname(__file__), "login.html"),
        os.path.join(os.path.dirname(__file__), "static", "login.html"),
        os.path.join(os.path.dirname(__file__), "..", "GBOC-Agent", "static", "login.html"),
        os.path.join(os.path.dirname(__file__), "..", "GBOC-Agent", "login.html"),
    ]
    for _path in candidates:
        if os.path.exists(_path):
            return FileResponse(_path)
    return HTMLResponse("<h1>Login page not found</h1>", status_code=404)

@app.get("/api/v1/auth/status")
async def server_auth_status(request: Request):
    enabled = _is_server_auth_enabled()
    user = _get_server_user_from_request(request)
    return {
        "status": "success",
        "auth_enabled": enabled,
        "authenticated": user is not None,
        "user": {"username": user["username"], "display_name": user["display_name"], "role": user["role"]} if user else None
    }

@app.post("/api/v1/auth/setup")
async def server_auth_setup(req: ServerSetupRequest):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM server_auth_users")
        count = cur.fetchone()[0]
        if count > 0:
            cur.close()
            raise HTTPException(400, "Já existem usuários cadastrados. Use /login.")
        pw_hash = _hash_password(req.password)
        cur.execute(
            "INSERT INTO server_auth_users (username, password_hash, display_name, role) VALUES (%s, %s, %s, 'admin')",
            (req.username, pw_hash, req.display_name or req.username)
        )
        conn.commit()
        cur.close()
        return {"status": "success", "message": "Usuário admin criado"}
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        release_db(conn)

@app.post("/api/v1/auth/login")
async def server_auth_login(req: ServerLoginRequest, request: Request, response: Response):
    conn = None
    ip = request.client.host if request.client else "unknown"
    try:
        conn = get_db()
        cur = conn.cursor()
        pw_hash = _hash_password(req.password)
        cur.execute(
            "SELECT id, username, display_name, role FROM server_auth_users WHERE username = %s AND password_hash = %s",
            (req.username, pw_hash)
        )
        row = cur.fetchone()
        if not row:
            # Registrar tentativa falha na auditoria
            try:
                cur.execute(
                    "INSERT INTO server_auth_audit (username, action, ip_address) VALUES (%s, 'auth.login_fail', %s)",
                    (req.username, ip)
                )
                conn.commit()
            except Exception:
                conn.rollback()
            cur.close()
            raise HTTPException(401, "Credenciais inválidas")
        user_id, username, display_name, role = row
        token = _generate_token()
        expires = _dt.now(timezone.utc) + timedelta(hours=24)
        cur.execute(
            "INSERT INTO server_auth_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)",
            (user_id, token, expires)
        )
        cur.execute("UPDATE server_auth_users SET last_login = LOCALTIMESTAMP WHERE id = %s", (user_id,))
        cur.execute(
            "INSERT INTO server_auth_audit (user_id, username, action, ip_address) VALUES (%s, %s, 'auth.login', %s)",
            (user_id, username, ip)
        )
        conn.commit()
        cur.close()
        response.set_cookie("gboc_server_token", token, httponly=False, max_age=86400, path="/")
        return {
            "status": "success",
            "token": token,
            "user": {"username": username, "display_name": display_name, "role": role}
        }
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        import traceback as _tb; logger.error(f"Erro /auth/login:\n{_tb.format_exc()}")
        raise HTTPException(500, str(e))
    finally:
        release_db(conn)

@app.post("/api/v1/auth/logout")
async def server_auth_logout(request: Request, response: Response):
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.cookies.get("gboc_server_token")
    if token:
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("DELETE FROM server_auth_tokens WHERE token = %s", (token,))
            conn.commit()
            cur.close()
        except Exception:
            pass
        finally:
            release_db(conn)
    response.delete_cookie("gboc_server_token", path="/")
    return {"status": "success"}

@app.post("/api/v1/agents/register")
async def register(data: AgentRegister):
    conn = None
    try:
        conn = get_db(); cur = conn.cursor()
        tools = json.dumps(data.available_tools) if data.available_tools else "[]"
        cur.execute('''
            INSERT INTO agents (agent_id, hostname, ip_address, os_info, agent_version, available_tools, last_heartbeat, status, tenant_id)
            VALUES (%s, %s, %s, %s, %s, %s, LOCALTIMESTAMP, 'online', %s)
            ON CONFLICT (agent_id) DO UPDATE SET 
                hostname=EXCLUDED.hostname, ip_address=EXCLUDED.ip_address, 
                os_info=EXCLUDED.os_info, agent_version=EXCLUDED.agent_version,
                available_tools=EXCLUDED.available_tools, last_heartbeat=LOCALTIMESTAMP, status='online',
                tenant_id=COALESCE(EXCLUDED.tenant_id, agents.tenant_id)
        ''', (data.agent_id, data.hostname, data.ip_address, data.os_info, data.agent_version, tools, data.tenant_id))
        log_event(conn, 'system', f"Novo agente registrado: {data.hostname}", data.hostname)
        conn.commit()
        await notify_dashboard_update()
        return {"status": "success"}
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

# ===========================
# WEBSOCKET ENDPOINTS
# ===========================

async def handle_realtime_heartbeat(agent_id: str, data: Dict) -> Dict:
    """Processa heartbeat em tempo real"""
    if not isinstance(data, dict):
        logger.error(f"Dados de heartbeat inválidos do agente {agent_id}: {data}")
        return {"status": "error", "message": "Invalid heartbeat data format"}
    
    try:
        # Atualizar dados em memória
        manager.update_agent_data(agent_id, data)

        # Salvar dados básicos no banco (métricas de sistema)
        conn = get_db()
        try:
            ensure_agent_exists(conn, agent_id, data)
            cur = conn.cursor()
            cur.execute('''
                UPDATE agents SET
                    last_heartbeat=LOCALTIMESTAMP, status='online',
                    cpu_usage=%s, ram_usage=%s, disk_usage=%s,
                    tenant_id=COALESCE(%s, tenant_id)
                WHERE agent_id=%s
            ''', (data.get('cpu_usage'), data.get('ram_usage'), data.get('disk_usage'), data.get('tenant_id'), agent_id))
            conn.commit()
        finally:
            release_db(conn)

        return {"status": "success"}
    except Exception as e:
        logger.error(f"Erro no heartbeat em tempo real do agente {agent_id}: {e}")
        return {"status": "error", "message": str(e)}

@app.websocket("/ws/agents/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str):
    """WebSocket para comunicação em tempo real com agentes"""
    await manager.connect(websocket, agent_id)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                await handle_websocket_message(agent_id, message, websocket)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"error": "Invalid JSON"}))
    except WebSocketDisconnect:
        manager.disconnect(agent_id)
        logger.info(f"WebSocket desconectado para agente {agent_id}")

# WebSocket para dashboard
dashboard_connections = set()

@app.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    """WebSocket para atualização em tempo real do dashboard"""
    await websocket.accept()
    dashboard_connections.add(websocket)
    logger.info("Dashboard conectado via WebSocket")
    
    try:
        while True:
            # Manter conexão viva
            await websocket.receive_text()
    except WebSocketDisconnect:
        dashboard_connections.remove(websocket)
        logger.info("Dashboard desconectado")

async def notify_dashboard_update():
    """Notifica todos os dashboards conectados sobre atualizações"""
    if dashboard_connections:
        message = {"type": "update", "timestamp": _dt.now(timezone.utc).isoformat()}
        for ws in dashboard_connections.copy():
            try:
                await ws.send_text(json.dumps(message))
            except:
                dashboard_connections.remove(ws)

def _send_server_notification_sync(subject: str, body: str) -> Dict:
    """
    Envia notificação via SMTP e/ou Webhook conforme configuração do servidor.
    Função síncrona — chame via asyncio.get_event_loop().run_in_executor para não bloquear.
    """
    results = []
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT key, value FROM server_settings WHERE category = 'notifications'")
        cfg = {r['key']: r['value'] for r in cur.fetchall()}
    except Exception as e:
        logger.warning(f"Não foi possível ler config de notificações: {e}")
        cfg = {}
    finally:
        if conn:
            try:
                if 'cur' in dir() and cur: cur.close()
            except Exception:
                pass
            release_db(conn)

    # SMTP
    if cfg.get('email_enabled', 'false').lower() == 'true':
        try:
            import smtplib
            from email.mime.text import MIMEText
            host = cfg.get('smtp_host', '')
            port = int(cfg.get('smtp_port', 587))
            user = cfg.get('smtp_username', '')
            pwd  = cfg.get('smtp_password', '')
            frm  = cfg.get('smtp_from', user)
            to   = cfg.get('smtp_to', user)
            if host and user:
                msg = MIMEText(body, 'plain', 'utf-8')
                msg['Subject'] = subject
                msg['From']    = frm
                msg['To']      = to
                with smtplib.SMTP(host, port, timeout=15) as s:
                    s.starttls()
                    s.login(user, pwd)
                    s.send_message(msg)
                results.append({"channel": "email", "status": "sent", "to": to})
        except Exception as e:
            results.append({"channel": "email", "status": "error", "error": str(e)})
            logger.warning(f"Falha ao enviar e-mail de notificação: {e}")

    # Webhook
    if cfg.get('webhook_enabled', 'false').lower() == 'true':
        try:
            import urllib.request
            url = cfg.get('webhook_url', '')
            if url:
                payload = json.dumps({
                    "text": f"🔔 *{subject}*\n{body}",
                    "subject": subject,
                    "body": body,
                    "timestamp": _dt.now(timezone.utc).isoformat(),
                }).encode('utf-8')
                req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
                urllib.request.urlopen(req, timeout=10)
                results.append({"channel": "webhook", "status": "sent", "url": url})
        except Exception as e:
            results.append({"channel": "webhook", "status": "error", "error": str(e)})
            logger.warning(f"Falha ao enviar webhook de notificação: {e}")

    return {"sent": results}


async def _send_server_notification(subject: str, body: str) -> Dict:
    """Wrapper assíncrono para _send_server_notification_sync."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_server_notification_sync, subject, body)


async def save_agent_historical_data(conn, agent_id: str, data: Dict):
    """Salva dados históricos do agente"""
    try:
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO agent_metrics (agent_id, cpu_usage, ram_usage, disk_usage, timestamp)
            VALUES (%s, %s, %s, %s, LOCALTIMESTAMP)
        ''', (
            agent_id,
            data.get('cpu_usage'),
            data.get('ram_usage'),
            data.get('disk_usage')
        ))
    except Exception as e:
        logger.warning(f"Erro ao salvar métricas históricas: {e}")

async def sync_repositories(conn, agent_id: str, repositories: List[Dict]):
    """Sincroniza repositórios do agente"""
    try:
        cur = conn.cursor()
        for repo in repositories:
            cur.execute('''
                INSERT INTO agent_repositories
                    (agent_id, repo_id, name, engine, type, status, last_backup, total_backups)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (agent_id, repo_id) DO UPDATE SET
                    name = EXCLUDED.name, engine = EXCLUDED.engine, type = EXCLUDED.type,
                    status = EXCLUDED.status, last_backup = EXCLUDED.last_backup,
                    total_backups = EXCLUDED.total_backups, synced_at = CURRENT_TIMESTAMP
            ''', (
                agent_id, repo.get('id'), repo.get('name'),
                repo.get('engine', 'restic'), repo.get('type', 'local'),
                repo.get('status', 'active'), repo.get('last_backup'),
                repo.get('total_backups', 0)
            ))
        conn.commit()
        logger.info(f"✅ {len(repositories)} repositórios sincronizados para agente {agent_id}")
    except Exception as e:
        logger.warning(f"Erro ao sincronizar repositórios: {e}")

async def sync_agent_tasks(conn, agent_id: str, tasks: List[Dict]):
    """Sincroniza tarefas do agente."""
    try:
        cur = conn.cursor()
        for task in tasks:
            task_id = task.get('id')
            if task_id is None:
                continue

            created_at = task.get('created_at')
            updated_at = task.get('updated_at') or created_at

            # UPDATE primeiro (compatível com schemas legados sem UNIQUE)
            cur.execute('''
                UPDATE agent_tasks
                SET name = %s,
                    status = %s,
                    updated_at = %s,
                    synced_at = CURRENT_TIMESTAMP
                WHERE agent_id = %s AND task_id = %s
            ''', (
                task.get('name'), task.get('status'), updated_at,
                agent_id, task_id
            ))

            if cur.rowcount == 0:
                cur.execute('''
                    INSERT INTO agent_tasks (agent_id, task_id, name, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (
                    agent_id, task_id, task.get('name'), task.get('status'),
                    created_at, updated_at
                ))
        conn.commit()
        logger.info(f"✅ {len(tasks)} tarefas sincronizadas para agente {agent_id}")
    except Exception as e:
        logger.warning(f"Erro ao sincronizar tarefas: {e}")

async def sync_task_executions(conn, agent_id: str, executions: List[Dict]):
    """Sincroniza execuções de tarefas do agente"""
    try:
        cur = conn.cursor()
        for ex in executions:
            cur.execute('''
                INSERT INTO agent_task_executions 
                    (agent_id, task_id, execution_id, status, started_at, completed_at, 
                     duration_seconds, files_processed, bytes_processed, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (agent_id, task_id, execution_id) DO UPDATE SET
                    status = EXCLUDED.status, completed_at = EXCLUDED.completed_at,
                    duration_seconds = EXCLUDED.duration_seconds,
                    files_processed = EXCLUDED.files_processed,
                    bytes_processed = EXCLUDED.bytes_processed,
                    error_message = EXCLUDED.error_message
            ''', (
                agent_id, ex.get('task_id'), ex.get('id'), ex.get('status'),
                ex.get('started_at'), ex.get('completed_at'),
                ex.get('duration_seconds'), ex.get('files_processed', 0),
                ex.get('bytes_processed', 0), ex.get('error_message')
            ))
        conn.commit()
        logger.info(f"✅ {len(executions)} execuções sincronizadas para agente {agent_id}")
    except Exception as e:
        logger.warning(f"Erro ao sincronizar execuções: {e}")

async def sync_system_events(conn, agent_id: str, events: List[Dict]):
    """Sincroniza eventos do sistema do agente"""
    try:
        cur = conn.cursor()
        for event in events:
            cur.execute('''
                INSERT INTO system_events (event_type, message, agent_hostname, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            ''', (
                event.get('type', 'agent_event'),
                event.get('message', ''),
                event.get('hostname', agent_id),
                event.get('timestamp', _dt.now(timezone.utc).isoformat())
            ))
    except Exception as e:
        logger.warning(f"Erro ao sincronizar eventos: {e}")

async def sync_alerts(conn, agent_id: str, alerts: List[Dict]):
    """Sincroniza alertas do agente como eventos do sistema"""
    try:
        cur = conn.cursor()
        # Obter hostname do agente
        cur.execute("SELECT hostname FROM agents WHERE agent_id = %s", (agent_id,))
        agent_row = cur.fetchone()
        hostname = agent_row[0] if agent_row else agent_id[:12]

        for alert in alerts:
            # Campos da tabela alerts do Agent: type, severity, title, message, source, timestamp
            event_type = alert.get('type', alert.get('severity', 'unknown'))
            severity = alert.get('severity', 'info')
            title = alert.get('title', '')
            message = alert.get('message', 'Alert from agent')
            ts = alert.get('timestamp', alert.get('created_at', _dt.now(timezone.utc).isoformat()))

            # Mapear severity para event_type do Server
            if severity in ('critical', 'error'):
                mapped_type = 'error'
            elif severity == 'warning':
                mapped_type = 'warning'
            else:
                mapped_type = f"alert_{event_type}"

            full_message = f"[{title}] {message}" if title else message

            # Evitar duplicatas (checar por mensagem + agente + janela de tempo)
            cur.execute('''
                SELECT 1 FROM system_events 
                WHERE agent_hostname = %s AND message = %s 
                AND created_at > NOW() - INTERVAL '5 minutes'
                LIMIT 1
            ''', (hostname, full_message))

            if not cur.fetchone():
                cur.execute('''
                    INSERT INTO system_events (event_type, message, agent_hostname, created_at)
                    VALUES (%s, %s, %s, %s)
                ''', (mapped_type, full_message, hostname, ts))

        conn.commit()
        if alerts:
            logger.info(f"✅ {len(alerts)} alertas sincronizados para agente {hostname}")
    except Exception as e:
        logger.warning(f"Erro ao sincronizar alertas: {e}")
        try:
            conn.rollback()
        except Exception:
            pass

async def handle_full_data_sync(agent_id: str, data: Dict) -> Dict:
    """Processa sincronização completa de dados do agente."""
    if not isinstance(data, dict):
        logger.error(f"Dados inválidos recebidos do agente {agent_id}: {data}")
        return {"status": "error", "message": "Invalid data format"}

    conn = None
    try:
        conn = get_db()

        # Garantir registro do agente ANTES de qualquer FK/metrics
        ensure_agent_exists(conn, agent_id, data)
        conn.commit()

        # Atualizar dados em memória
        manager.update_agent_data(agent_id, data)

        # Cada etapa é isolada para não abortar a transação inteira
        try:
            await save_agent_historical_data(conn, agent_id, data)
            conn.commit()
        except Exception:
            conn.rollback()

        if "repositories" in data:
            try:
                await sync_repositories(conn, agent_id, data["repositories"])
                conn.commit()
            except Exception:
                conn.rollback()

        if "tasks" in data:
            try:
                await sync_agent_tasks(conn, agent_id, data["tasks"])
                conn.commit()
            except Exception:
                conn.rollback()

        if "task_executions" in data:
            try:
                await sync_task_executions(conn, agent_id, data["task_executions"])
                conn.commit()
            except Exception:
                conn.rollback()

        if "system_events" in data:
            try:
                await sync_system_events(conn, agent_id, data["system_events"])
                conn.commit()
            except Exception:
                conn.rollback()

        if "alerts" in data:
            try:
                await sync_alerts(conn, agent_id, data["alerts"])
                conn.commit()
            except Exception:
                conn.rollback()

        logger.info(f"✅ Sincronização completa recebida do agente {agent_id}")
        return {"status": "success", "message": "Full sync completed"}

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Erro na sincronização completa do agente {agent_id}: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        if conn:
            release_db(conn)

async def handle_realtime_alert(agent_id: str, data: Dict) -> None:
    """Persiste alerta em tempo real recebido via WebSocket"""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO system_events (event_type, message, agent_hostname, created_at)
            VALUES (%s, %s, %s, LOCALTIMESTAMP)
        ''', (
            f"alert_{data.get('type', 'unknown')}",
            data.get('message', 'Alert from agent'),
            data.get('hostname', agent_id)
        ))
        conn.commit()
        cur.close()
        await notify_dashboard_update()
    except Exception as e:
        logger.warning(f"Erro ao salvar alerta em tempo real do agente {agent_id}: {e}")
    finally:
        if conn:
            release_db(conn)


async def get_agent_full_data(agent_id: str, since_timestamp: str = None) -> Dict:
    """Retorna todos os dados sincronizados de um agente do banco"""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM agents WHERE agent_id = %s", (agent_id,))
        agent = cur.fetchone()

        since_filter = ""
        since_params: list = [agent_id]
        if since_timestamp:
            since_filter = " AND synced_at > %s"
            since_params.append(since_timestamp)

        cur.execute(f"SELECT * FROM agent_repositories WHERE agent_id = %s{since_filter}", since_params)
        repositories = cur.fetchall()

        cur.execute(f"SELECT * FROM agent_tasks WHERE agent_id = %s{since_filter}", since_params)
        tasks = cur.fetchall()

        cur.execute(f"SELECT * FROM agent_task_executions WHERE agent_id = %s{since_filter}", since_params)
        executions = cur.fetchall()

        cur.execute(
            "SELECT * FROM system_events WHERE agent_hostname = %s ORDER BY created_at DESC LIMIT 100",
            (agent_id,)
        )
        events = cur.fetchall()

        cur.close()
        return {
            "agent": dict(agent) if agent else {},
            "repositories": [dict(r) for r in repositories],
            "tasks": [dict(t) for t in tasks],
            "executions": [dict(e) for e in executions],
            "events": [dict(ev) for ev in events],
        }
    except Exception as e:
        logger.error(f"Erro ao buscar dados completos do agente {agent_id}: {e}")
        return {}
    finally:
        if conn:
            release_db(conn)


async def get_agent_repositories(agent_id: str, since_timestamp: str = None) -> List[Dict]:
    """Retorna repositórios sincronizados de um agente"""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        params: list = [agent_id]
        extra = ""
        if since_timestamp:
            extra = " AND synced_at > %s"
            params.append(since_timestamp)
        cur.execute(f"SELECT * FROM agent_repositories WHERE agent_id = %s{extra}", params)
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Erro ao buscar repositórios do agente {agent_id}: {e}")
        return []
    finally:
        if conn:
            release_db(conn)


async def get_agent_tasks(agent_id: str, since_timestamp: str = None) -> List[Dict]:
    """Retorna tarefas sincronizadas de um agente"""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        params: list = [agent_id]
        extra = ""
        if since_timestamp:
            extra = " AND synced_at > %s"
            params.append(since_timestamp)
        cur.execute(f"SELECT * FROM agent_tasks WHERE agent_id = %s{extra}", params)
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Erro ao buscar tarefas do agente {agent_id}: {e}")
        return []
    finally:
        if conn:
            release_db(conn)


async def handle_manual_sync(agent_id: str, data: Dict) -> Dict:
    """Processa sincronização manual"""
    sync_type = data.get("sync_type", "full")
    since_timestamp = data.get("since_timestamp")

    try:
        if sync_type == "full":
            # Buscar todos os dados do agente
            agent_data = await get_agent_full_data(agent_id, since_timestamp)
            return {"status": "success", "data": agent_data}

        elif sync_type == "repositories":
            repos = await get_agent_repositories(agent_id, since_timestamp)
            return {"status": "success", "repositories": repos}

        elif sync_type == "tasks":
            tasks = await get_agent_tasks(agent_id, since_timestamp)
            return {"status": "success", "tasks": tasks}

        else:
            return {"status": "error", "message": f"Unknown sync type: {sync_type}"}

    except Exception as e:
        logger.error(f"Erro na sincronização manual do agente {agent_id}: {e}")
        return {"status": "error", "message": str(e)}

async def handle_websocket_message(agent_id: str, message: Dict, websocket: WebSocket):
    """Processa mensagens WebSocket do agente"""
    if not isinstance(message, dict):
        await websocket.send_text(json.dumps({"error": "Invalid message format"}))
        return
    
    msg_type = message.get("type")
    if not msg_type:
        await websocket.send_text(json.dumps({"error": "Missing message type"}))
        return

    if msg_type == "full_sync":
        # Sincronização completa de dados
        data = message.get("data", {})
        result = await handle_full_data_sync(agent_id, data)
        await websocket.send_text(json.dumps({"status": result.get("status", "error"), "type": "full_sync", "message": result.get("message", "")}))

    elif msg_type == "heartbeat":
        # Heartbeat em tempo real
        data = message.get("data", {})
        if not isinstance(data, dict):
            await websocket.send_text(json.dumps({"error": "Invalid heartbeat data"}))
            return
        await handle_realtime_heartbeat(agent_id, data)
        await websocket.send_text(json.dumps({"status": "ok", "type": "heartbeat"}))

    elif msg_type == "manual_sync":
        # Sincronização manual solicitada
        data = message.get("data", {})
        if not isinstance(data, dict):
            await websocket.send_text(json.dumps({"error": "Invalid manual sync data"}))
            return
        result = await handle_manual_sync(agent_id, data)
        await websocket.send_text(json.dumps({"status": "completed", "type": "manual_sync", "result": result}))

    elif msg_type == "alert":
        # Alerta em tempo real
        data = message.get("data", {})
        if not isinstance(data, dict):
            await websocket.send_text(json.dumps({"error": "Invalid alert data"}))
            return
        await handle_realtime_alert(agent_id, data)
        await websocket.send_text(json.dumps({"status": "alert_received", "type": "alert"}))

    else:
        await websocket.send_text(json.dumps({"error": "Unknown message type"}))

# ===========================
# NOVOS ENDPOINTS REST
# ===========================

@app.post("/api/v1/agents/full-sync")
async def full_data_sync(data: AgentFullData):
    """Recebe sincronização completa de dados do agente"""
    payload = data.model_dump() if hasattr(data, 'model_dump') else data.dict()
    return await handle_full_data_sync(data.agent_id, payload)

@app.post("/api/v1/agents/manual-sync")
async def manual_sync_request(data: ManualSyncRequest):
    """Processa solicitação de sincronização manual"""
    payload = data.model_dump() if hasattr(data, 'model_dump') else data.dict()
    return await handle_manual_sync(data.agent_id, payload)

@app.get("/api/v1/agents/{agent_id}/realtime-data")
async def get_agent_realtime_data(agent_id: str):
    """Obtém dados em tempo real de um agente específico"""
    data = manager.get_agent_data(agent_id)
    def sanitize_value(value):
        if isinstance(value, bytes):
            try:
                # Tentar decodificar como UTF-8
                return value.decode('utf-8')
            except UnicodeDecodeError:
                # Se falhar, converter para string como bytes
                return str(value)
        return value

    if not data:
        raise HTTPException(404, "Agent not connected or no data available")
    
    # Sanitize all values in the data dictionary
    sanitized_data = {k: sanitize_value(v) for k, v in data.items()}
    
    return sanitized_data

@app.get("/api/v1/agents/realtime-status")
async def get_all_agents_realtime_status():
    """Obtém status em tempo real de todos os agentes conectados"""
    return {
        "connected_agents": list(manager.active_connections.keys()),
        "agents_data": manager.get_all_agents_data(),
        "timestamp": _dt.now(timezone.utc).isoformat()
    }

@app.post("/api/v1/agents/heartbeat")
async def heartbeat(data: AgentHeartbeat):
    conn = None
    try:
        conn = get_db(); cur = conn.cursor()
        jobs = json.dumps(data.jobs_summary) if data.jobs_summary else None
        cur.execute('''
            UPDATE agents SET 
                last_heartbeat=LOCALTIMESTAMP, status='online', 
                cpu_usage=%s, ram_usage=%s, disk_usage=%s, jobs_count=%s, jobs_summary=%s,
                tenant_id=COALESCE(%s, tenant_id)
            WHERE agent_id=%s
        ''', (data.cpu_usage, data.ram_usage, data.disk_usage, data.jobs_count, jobs, data.tenant_id, data.agent_id))
        if cur.rowcount == 0:
            cur.close(); release_db(conn)
            await register(AgentRegister(agent_id=data.agent_id, hostname=data.hostname, tenant_id=data.tenant_id))
            return {"status": "registered"}
        conn.commit()
        await notify_dashboard_update()
        return {"status": "success"}
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur and not cur.closed: cur.close()
        release_db(conn)

# ── Gestão de Agentes ─────────────────────────────────────────────────────────

@app.post("/api/v1/agents/{agent_id}/disconnect")
async def disconnect_agent(agent_id: str, request: Request):
    """Desconecta um agente: fecha o WebSocket e marca como offline."""
    _require_server_auth(request)
    conn = None
    try:
        # Fechar WebSocket se estiver conectado
        if agent_id in manager.active_connections:
            try:
                await manager.active_connections[agent_id].close()
            except Exception:
                pass
            manager.disconnect(agent_id)

        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE agents SET status='offline' WHERE agent_id=%s", (agent_id,))
        conn.commit()
        await notify_dashboard_update()
        return {"status": "success", "message": f"Agente {agent_id} desconectado"}
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur and not cur.closed: cur.close()
        release_db(conn)


@app.post("/api/v1/agents/{agent_id}/command")
async def send_agent_command(agent_id: str, request: Request):
    """Envia um comando ao agente via WebSocket. Suporta: sync, ping, collect_metrics."""
    _require_server_auth(request)
    try:
        body = await request.json()
        command = body.get("command", "ping")
        params = body.get("params", {})

        if agent_id not in manager.active_connections:
            raise HTTPException(404, f"Agente {agent_id} não está conectado via WebSocket")

        ws = manager.active_connections[agent_id]
        message = json.dumps({"type": "command", "command": command, "params": params})
        await ws.send_text(message)
        return {"status": "success", "message": f"Comando '{command}' enviado ao agente {agent_id}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/v1/agents/{agent_id}/force-sync")
async def force_agent_sync(agent_id: str, request: Request):
    """Solicita sincronização forçada de um agente via WebSocket."""
    _require_server_auth(request)
    try:
        if agent_id not in manager.active_connections:
            raise HTTPException(404, f"Agente {agent_id} não está conectado via WebSocket")

        ws = manager.active_connections[agent_id]
        await ws.send_text(json.dumps({"type": "command", "command": "full_sync", "params": {}}))
        return {"status": "success", "message": f"Sincronização solicitada ao agente {agent_id}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


def _require_server_auth(request: Request):
    """Helper: levanta 401 se não autenticado."""
    user = _get_server_user_from_request(request)
    if not user:
        raise HTTPException(401, "Autenticação necessária")

# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/backups/report")
async def report_backup(data: BackupReport):
    conn = None
    try:
        conn = get_db(); cur = conn.cursor()
        final_source = data.source_path or data.job_name or "Unknown"
        final_bytes = data.total_bytes or data.data_added or 0
        final_error = data.error
        
        cur.execute('''
            INSERT INTO backup_reports (
                agent_id, backup_type, source_path, start_time, end_time, duration_seconds, 
                total_files, total_bytes, status, error_message, snapshot_id, files_new, files_changed
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            data.agent_id, data.backup_type, final_source, data.start_time, data.end_time, 
            data.duration_seconds, 0, final_bytes, data.status, final_error, 
            data.snapshot_id, data.files_new, data.files_changed
        ))
        
        cur.execute("SELECT hostname FROM agents WHERE agent_id = %s", (data.agent_id,))
        res = cur.fetchone()
        hostname = res[0] if res else "Unknown"
        
        evt_type = 'backup_success' if data.status == 'success' else 'backup_failure'
        msg = f"Backup '{final_source}' {'concluído' if data.status=='success' else 'falhou'}"
        if final_error: msg += f": {final_error}"
        log_event(conn, evt_type, msg, hostname)
        conn.commit()
        return {"status": "success"
}
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Erro Report: {e}")
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

@app.post("/api/v1/sync/tasks")
async def sync_tasks(data: TaskSyncData):
    conn = None
    try:
        conn = get_db(); cur = conn.cursor()
        for task in data.tasks:
            task_id = task.get('id')
            if task_id is None:
                continue

            created_at = task.get('created_at')
            updated_at = task.get('updated_at') or created_at

            cur.execute('''
                UPDATE agent_tasks
                SET name = %s,
                    status = %s,
                    updated_at = %s,
                    synced_at = CURRENT_TIMESTAMP
                WHERE agent_id = %s AND task_id = %s
            ''', (
                task.get('name'), task.get('status'), updated_at,
                data.agent_id, task_id
            ))

            if cur.rowcount == 0:
                cur.execute('''
                    INSERT INTO agent_tasks (agent_id, task_id, name, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (
                    data.agent_id, task_id, task.get('name'), task.get('status'),
                    created_at, updated_at
                ))
        conn.commit()
        return {"status": "success", "synced_tasks": len(data.tasks)}
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

@app.post("/api/v1/sync/logs")
async def sync_logs(data: LogSyncData):
    conn = None
    try:
        conn = get_db(); cur = conn.cursor()
        for log in data.logs:
            cur.execute('''
                INSERT INTO agent_logs (agent_id, level, source, message, details, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (
                data.agent_id, log.get('level'), log.get('source'), log.get('message'),
                log.get('details'), log.get('timestamp')
            ))
        conn.commit()
        return {"status": "success", "synced_logs": len(data.logs)}
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

@app.post("/api/v1/sync/push")
async def push_sync_agents():
    """Força todos os agentes online a reenviarem dados completos via WebSocket"""
    try:
        connected = list(manager.active_connections.keys())
        if not connected:
            return {"status": "warning", "message": "Nenhum agente conectado via WebSocket", "synced": 0}

        synced = 0
        for agent_id in connected:
            try:
                await manager.send_personal_message(
                    json.dumps({"type": "request_full_sync", "timestamp": _dt.now(timezone.utc).isoformat()}),
                    agent_id
                )
                synced += 1
                logger.info(f"📤 Solicitação de sync completo enviada para {agent_id}")
            except Exception as e:
                logger.warning(f"Erro ao solicitar sync de {agent_id}: {e}")

        return {
            "status": "success",
            "message": f"Sincronização solicitada para {synced} agente(s)",
            "synced": synced,
            "agents": connected
        }
    except Exception as e:
        logger.error(f"Erro na sincronização push: {e}")
        raise HTTPException(500, str(e))

# ===========================
# ENDPOINTS PARA COMUNICAÇÃO COM AGENTES
# ===========================

@app.get("/api/v1/version")
async def get_version():
    """Endpoint de versão — usado pelo agente para testar conexão com o servidor"""
    return {
        "version": SERVER_VERSION,
        "name": "GBOC Server",
        "status": "running",
        "timestamp": _dt.now(timezone.utc).isoformat()
    }


@app.get("/api/v1/agents/{agent_id}/details")
async def get_agent_details(agent_id: str):
    """Retorna dados completos de um agente: info, métricas, tasks, repos, backups recentes, uptime."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Info do agente
        cur.execute("""
            SELECT *,
                CASE WHEN last_heartbeat > (LOCALTIMESTAMP - INTERVAL '60 minutes') THEN 'online' ELSE 'offline' END as current_status,
                EXTRACT(EPOCH FROM (LOCALTIMESTAMP - COALESCE(registered_at, last_heartbeat))) as uptime_seconds,
                EXTRACT(EPOCH FROM (LOCALTIMESTAMP - last_heartbeat)) as last_seen_seconds
            FROM agents WHERE agent_id = %s
        """, (agent_id,))
        agent = cur.fetchone()
        if not agent:
            raise HTTPException(404, f"Agent {agent_id} not found in database")

        # Parse JSON fields safely
        for field in ['available_tools', 'jobs_summary']:
            try:
                val = agent.get(field)
                if isinstance(val, str):
                    agent[field] = json.loads(val)
                elif val is None:
                    agent[field] = [] if field == 'available_tools' else {}
            except:
                agent[field] = [] if field == 'available_tools' else {}

        # Helper for safe queries (returns empty list on any error)
        def safe_query(sql, params):
            try:
                cur.execute(sql, params)
                return cur.fetchall()
            except Exception as qe:
                logger.warning(f"Query falhou em agent_details ({agent_id}): {qe}")
                try:
                    conn.rollback()
                except:
                    pass
                return []

        # Tasks do agente
        tasks = safe_query("""
            SELECT task_id, name, status, updated_at
            FROM agent_tasks WHERE agent_id = %s ORDER BY name
        """, (agent_id,))

        # Repositórios do agente
        repos = safe_query("""
            SELECT repo_id, name, engine, type, status, last_backup, total_backups
            FROM agent_repositories WHERE agent_id = %s ORDER BY name
        """, (agent_id,))

        # Últimos 10 backups
        backups = safe_query("""
            SELECT backup_type, source_path, start_time, end_time, duration_seconds,
                   total_files, total_bytes, status, error_message, snapshot_id
            FROM backup_reports WHERE agent_id = %s
            ORDER BY start_time DESC LIMIT 10
        """, (agent_id,))

        # Últimas 10 execuções
        executions = safe_query("""
            SELECT task_id, execution_id, status, started_at, completed_at,
                   duration_seconds, files_processed, bytes_processed, error_message
            FROM agent_task_executions WHERE agent_id = %s
            ORDER BY started_at DESC LIMIT 10
        """, (agent_id,))

        # Estatísticas de desempenho (30 dias)
        perf_rows = safe_query("""
            SELECT COUNT(*) as total_backups,
                   COUNT(*) FILTER (WHERE status = 'success') as success_count,
                   COUNT(*) FILTER (WHERE status != 'success') as failure_count,
                   COALESCE(SUM(total_bytes), 0) as total_bytes,
                   COALESCE(AVG(duration_seconds), 0) as avg_duration,
                   MAX(start_time) as last_backup_time
            FROM backup_reports
            WHERE agent_id = %s AND start_time >= LOCALTIMESTAMP - INTERVAL '30 days'
        """, (agent_id,))
        perf = perf_rows[0] if perf_rows else {}

        # Histórico de métricas (últimas 24h)
        metrics_history = safe_query("""
            SELECT cpu_usage, ram_usage, disk_usage,
                   TO_CHAR(timestamp, 'HH24:MI') as time_label
            FROM agent_metrics WHERE agent_id = %s AND timestamp >= LOCALTIMESTAMP - INTERVAL '24 hours'
            ORDER BY timestamp
        """, (agent_id,))

        # Dados em tempo real do WebSocket
        try:
            realtime = manager.get_agent_data(agent_id)
        except:
            realtime = {}

        # Serializar datetimes e Decimals
        def serialize(obj):
            if isinstance(obj, list):
                return [serialize(i) for i in obj]
            if isinstance(obj, dict):
                result = {}
                for k, v in obj.items():
                    if hasattr(v, 'isoformat'):
                        result[k] = v.isoformat()
                    elif isinstance(v, Decimal):
                        result[k] = float(v)
                    elif isinstance(v, (list, dict)):
                        result[k] = serialize(v)
                    else:
                        result[k] = v
                return result
            if isinstance(obj, Decimal):
                return float(obj)
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            return obj

        success_rate = 0
        if perf.get('total_backups', 0) > 0:
            success_rate = round(perf['success_count'] / perf['total_backups'] * 100, 1)

        return serialize({
            "agent": agent,
            "tasks": tasks,
            "repositories": repos,
            "recent_backups": backups,
            "recent_executions": executions,
            "performance_30d": {
                "total_backups": perf.get('total_backups', 0),
                "success_count": perf.get('success_count', 0),
                "failure_count": perf.get('failure_count', 0),
                "success_rate": success_rate,
                "total_bytes": perf.get('total_bytes', 0),
                "avg_duration": round(float(perf.get('avg_duration', 0)), 1),
                "last_backup_time": perf.get('last_backup_time')
            },
            "metrics_history": {
                "labels": [m['time_label'] for m in metrics_history],
                "cpu": [float(m.get('cpu_usage') or 0) for m in metrics_history],
                "ram": [float(m.get('ram_usage') or 0) for m in metrics_history],
                "disk": [float(m.get('disk_usage') or 0) for m in metrics_history],
            },
            "realtime": realtime or {}
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro get_agent_details({agent_id}): {e}", exc_info=True)
        raise HTTPException(500, f"Internal error loading agent details: {str(e)}")
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.post("/api/v1/agents/{agent_id}/repositories")
async def receive_agent_repositories(agent_id: str, repositories: List[Dict[str, Any]]):
    """Recebe repositórios sincronizados de um agente"""
    conn = None
    try:
        conn = get_db()
        await sync_repositories(conn, agent_id, repositories)
        return {"status": "success", "synced_repositories": len(repositories)}
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Erro ao receber repositórios do agente {agent_id}: {e}")
        raise HTTPException(500, str(e))
    finally:
        release_db(conn)

class StatisticsSyncData(BaseModel):
    agent_id: str
    statistics: List[Dict[str, Any]]

@app.post("/api/v1/sync/statistics")
async def sync_statistics(data: StatisticsSyncData):
    """Recebe estatísticas de backup sincronizadas de um agente"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor()
        for stat in data.statistics:
            cur.execute('''
                INSERT INTO agent_statistics
                    (agent_id, task_id, task_name, repository_name, backup_date,
                     success, duration_seconds, bytes_processed, files_processed, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                data.agent_id, stat.get('task_id'), stat.get('task_name'),
                stat.get('repository_name'), stat.get('backup_date'),
                stat.get('success', False), stat.get('duration_seconds', 0),
                stat.get('bytes_processed', 0), stat.get('files_processed', 0),
                stat.get('error_message')
            ))
        conn.commit()
        return {"status": "success", "synced_statistics": len(data.statistics)}
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Erro ao sincronizar estatísticas: {e}")
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur:
            cur.close()
        release_db(conn)

# =====================================================================
# ANALYTICS AVANÇADO — Dados reais de agent_task_executions + metrics
# =====================================================================

@app.get("/api/v1/analytics/history")
async def get_analytics_history(range: str = '7d'):
    """Histórico de backups — usa agent_task_executions (dados reais sincronizados)"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)

        if range == '24h':
            interval, trunc, fmt = "INTERVAL '24 hours'", 'hour', 'HH24:00'
        elif range == '30d':
            interval, trunc, fmt = "INTERVAL '30 days'", 'day', 'DD/MM'
        elif range == '1y':
            interval, trunc, fmt = "INTERVAL '1 year'", 'month', 'MM/YYYY'
        else:
            interval, trunc, fmt = "INTERVAL '7 days'", 'day', 'DD/MM'

        # Buscar de agent_task_executions (dados reais) + backup_reports como fallback
        query = f"""
            WITH exec_data AS (
                SELECT started_at as start_time, status,
                       COALESCE(bytes_processed, 0) as total_bytes,
                       COALESCE(duration_seconds, 0) as duration_seconds
                FROM agent_task_executions
                WHERE started_at IS NOT NULL AND started_at >= (LOCALTIMESTAMP - {interval})
                UNION ALL
                SELECT start_time, status, COALESCE(total_bytes, 0), COALESCE(duration_seconds, 0)
                FROM backup_reports
                WHERE start_time IS NOT NULL AND start_time >= (LOCALTIMESTAMP - {interval})
            )
            SELECT 
                to_char(date_trunc('{trunc}', start_time), '{fmt}') as period,
                COALESCE(SUM(total_bytes), 0) / GREATEST(1024.0^3, 1) as total_gb,
                COALESCE(
                    SUM(total_bytes) / NULLIF(SUM(duration_seconds), 0) / (1024.0^2), 
                    0
                ) as avg_speed_mbps,
                COUNT(*) FILTER (WHERE status NOT IN ('completed','success')) as error_count,
                COUNT(*) as total_count,
                COUNT(*) FILTER (WHERE status IN ('completed','success')) as success_count
            FROM exec_data
            GROUP BY date_trunc('{trunc}', start_time), to_char(date_trunc('{trunc}', start_time), '{fmt}')
            ORDER BY date_trunc('{trunc}', start_time) ASC
        """
        cur.execute(query)
        results = cur.fetchall()

        return {
            "labels": [r['period'] for r in results],
            "volume_gb": [round(float(r['total_gb']), 4) for r in results],
            "speed_mbps": [round(float(r['avg_speed_mbps']), 2) for r in results],
            "errors": [r['error_count'] for r in results],
            "total": [r['total_count'] for r in results],
            "success": [r['success_count'] for r in results]
        }
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.get("/api/v1/analytics/comprehensive")
async def get_comprehensive_analytics():
    """Analytics completo: KPIs, tendências, previsão, diagnóstico preemptivo"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)

        # ── 1. KPIs Globais ──
        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE last_heartbeat > LOCALTIMESTAMP - INTERVAL '60 minutes') as online
            FROM agents
        """)
        agents = cur.fetchone()

        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE status IN ('completed','success')) as success,
                   COUNT(*) FILTER (WHERE status = 'failed') as failed,
                   COUNT(*) FILTER (WHERE status = 'interrupted') as interrupted,
                   COALESCE(SUM(bytes_processed), 0) as total_bytes,
                   COALESCE(AVG(duration_seconds) FILTER (WHERE duration_seconds > 0), 0) as avg_duration,
                   COALESCE(AVG(files_processed) FILTER (WHERE files_processed > 0), 0) as avg_files
            FROM agent_task_executions
        """)
        exec_stats = cur.fetchone()

        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE status IN ('completed','success')) as success,
                   COUNT(*) FILTER (WHERE status = 'failed') as failed,
                   COALESCE(AVG(duration_seconds) FILTER (WHERE duration_seconds > 0), 0) as avg_duration
            FROM agent_task_executions
            WHERE started_at >= LOCALTIMESTAMP - INTERVAL '24 hours'
        """)
        last_24h = cur.fetchone()

        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE status IN ('completed','success')) as success,
                   COUNT(*) FILTER (WHERE status = 'failed') as failed
            FROM agent_task_executions
            WHERE started_at >= LOCALTIMESTAMP - INTERVAL '7 days'
        """)
        last_7d = cur.fetchone()

        total_all = exec_stats['total'] or 1
        success_rate_all = round((exec_stats['success'] / total_all) * 100, 1) if total_all > 0 else 0
        total_24h = last_24h['total'] or 1
        success_rate_24h = round((last_24h['success'] / total_24h) * 100, 1) if last_24h['total'] > 0 else 100

        # ── 2. Tendência de Desempenho (últimos 7 dias vs anteriores) ──
        cur.execute("""
            WITH recent AS (
                SELECT AVG(duration_seconds) FILTER (WHERE duration_seconds > 0) as avg_dur,
                       COUNT(*) FILTER (WHERE status='failed') as fails,
                       COUNT(*) as total
                FROM agent_task_executions
                WHERE started_at >= LOCALTIMESTAMP - INTERVAL '7 days'
            ), previous AS (
                SELECT AVG(duration_seconds) FILTER (WHERE duration_seconds > 0) as avg_dur,
                       COUNT(*) FILTER (WHERE status='failed') as fails,
                       COUNT(*) as total
                FROM agent_task_executions
                WHERE started_at >= LOCALTIMESTAMP - INTERVAL '14 days'
                  AND started_at < LOCALTIMESTAMP - INTERVAL '7 days'
            )
            SELECT r.avg_dur as recent_dur, r.fails as recent_fails, r.total as recent_total,
                   p.avg_dur as prev_dur, p.fails as prev_fails, p.total as prev_total
            FROM recent r, previous p
        """)
        trend = cur.fetchone()

        # Calcular tendência
        r_dur = float(trend['recent_dur'] or 0)
        p_dur = float(trend['prev_dur'] or 0)
        dur_trend = 'improving' if (p_dur > 0 and r_dur < p_dur) else ('degrading' if (p_dur > 0 and r_dur > p_dur * 1.2) else 'stable')

        r_fail_rate = (trend['recent_fails'] / trend['recent_total'] * 100) if trend['recent_total'] > 0 else 0
        p_fail_rate = (trend['prev_fails'] / trend['prev_total'] * 100) if trend['prev_total'] > 0 else 0
        fail_trend = 'improving' if r_fail_rate < p_fail_rate else ('degrading' if r_fail_rate > p_fail_rate + 5 else 'stable')

        # ── 3. Métricas de Sistema (CPU/RAM/Disco) ──
        cur.execute("""
            SELECT agent_id, cpu_usage, ram_usage, disk_usage, timestamp
            FROM agent_metrics
            ORDER BY timestamp ASC
        """)
        metrics_raw = cur.fetchall()

        system_metrics = {
            'labels': [r['timestamp'].strftime('%d/%m %H:%M') if r['timestamp'] else '' for r in metrics_raw],
            'cpu': [float(r['cpu_usage'] or 0) for r in metrics_raw],
            'ram': [float(r['ram_usage'] or 0) for r in metrics_raw],
            'disk': [float(r['disk_usage'] or 0) for r in metrics_raw]
        }

        # ── 4. Previsão Estatística (Regressão Linear simples) ──
        predictions = {}

        # Prever tendência de disco
        disk_vals = system_metrics['disk']
        if len(disk_vals) >= 3:
            n = len(disk_vals)
            x_mean = (n - 1) / 2.0
            y_mean = sum(disk_vals) / n
            num = sum((i - x_mean) * (disk_vals[i] - y_mean) for i in range(n))
            den = sum((i - x_mean) ** 2 for i in range(n))
            slope = num / den if den > 0 else 0
            intercept = y_mean - slope * x_mean

            # Prever próximos 7 dias (assumindo ~5 pontos por dia)
            future_points = 35
            future_vals = [round(max(0, min(100, slope * (n + i) + intercept)), 1) for i in range(future_points)]
            days_to_80 = None
            if slope > 0:
                target = 80
                current = disk_vals[-1]
                if current < target:
                    points_to_80 = (target - intercept) / slope - n if slope > 0 else 999
                    days_to_80 = max(0, round(points_to_80 / 5, 1))  # ~5 metrics/dia

            predictions['disk'] = {
                'trend': 'up' if slope > 0.01 else ('down' if slope < -0.01 else 'stable'),
                'slope_per_day': round(slope * 5, 2),
                'current': round(disk_vals[-1], 1) if disk_vals else 0,
                'predicted_7d': round(future_vals[-1], 1) if future_vals else 0,
                'days_to_critical': days_to_80,
                'future_values': future_vals[::5]  # 1 ponto por dia
            }

        # Prever tendência de RAM
        ram_vals = system_metrics['ram']
        if len(ram_vals) >= 3:
            n = len(ram_vals)
            x_mean = (n - 1) / 2.0
            y_mean = sum(ram_vals) / n
            num = sum((i - x_mean) * (ram_vals[i] - y_mean) for i in range(n))
            den = sum((i - x_mean) ** 2 for i in range(n))
            slope = num / den if den > 0 else 0
            predictions['ram'] = {
                'trend': 'up' if slope > 0.05 else ('down' if slope < -0.05 else 'stable'),
                'slope_per_day': round(slope * 5, 2),
                'current': round(ram_vals[-1], 1) if ram_vals else 0,
                'predicted_7d': round(max(0, min(100, slope * (n + 35) + (y_mean - slope * x_mean))), 1)
            }

        # Prever tendência de falhas
        cur.execute("""
            SELECT date_trunc('day', started_at)::date as day,
                   COUNT(*) FILTER (WHERE status = 'failed') as fails,
                   COUNT(*) as total
            FROM agent_task_executions
            WHERE started_at >= LOCALTIMESTAMP - INTERVAL '14 days' AND started_at IS NOT NULL
            GROUP BY date_trunc('day', started_at)::date
            ORDER BY day ASC
        """)
        daily_fails = cur.fetchall()
        fail_rates = [round(float(r['fails']) / max(r['total'], 1) * 100, 1) for r in daily_fails]
        if len(fail_rates) >= 2:
            n = len(fail_rates)
            x_mean = (n - 1) / 2.0
            y_mean = sum(fail_rates) / n
            num = sum((i - x_mean) * (fail_rates[i] - y_mean) for i in range(n))
            den = sum((i - x_mean) ** 2 for i in range(n))
            slope = num / den if den > 0 else 0
            predictions['failure_rate'] = {
                'trend': 'up' if slope > 1 else ('down' if slope < -1 else 'stable'),
                'slope_per_day': round(slope, 2),
                'current': fail_rates[-1] if fail_rates else 0,
                'predicted_7d': round(max(0, min(100, slope * (n + 7) + (y_mean - slope * x_mean))), 1)
            }

        # ── 5. Diagnóstico Preemptivo com Recomendações ──
        diagnostics = []

        # 5.1 — Erros mais frequentes
        cur.execute("""
            SELECT source, COUNT(*) as cnt,
                   MAX(timestamp) as last_seen
            FROM agent_logs WHERE level = 'ERROR'
            GROUP BY source ORDER BY cnt DESC LIMIT 10
        """)
        error_sources = cur.fetchall()

        # 5.2 — Padrões de erro com recomendações automáticas
        cur.execute("""
            SELECT SUBSTRING(message FROM 1 FOR 120) as pattern, COUNT(*) as cnt,
                   MAX(timestamp) as last_seen
            FROM agent_logs WHERE level = 'ERROR'
            GROUP BY SUBSTRING(message FROM 1 FOR 120)
            ORDER BY cnt DESC LIMIT 20
        """)
        error_patterns = cur.fetchall()

        recommendations = {
            'no such table': {
                'severity': 'high',
                'category': 'Database',
                'issue': 'Referências a tabelas SQLite inexistentes após migração para PostgreSQL',
                'fix': 'Reinicie o agente. Se persistir, verifique se os módulos diagnostic e statistics estão usando PostgreSQL.',
                'icon': 'database'
            },
            'no such column': {
                'severity': 'medium',
                'category': 'Database',
                'issue': 'Colunas ausentes no banco — schema desatualizado',
                'fix': 'Execute ALTER TABLE para adicionar colunas faltantes ou reinicie o agente para auto-migração.',
                'icon': 'columns'
            },
            'kopia': {
                'severity': 'medium',
                'category': 'Engine',
                'issue': 'Falha ao conectar/listar snapshots Kopia',
                'fix': 'Verifique se o Kopia está instalado, o repositório está inicializado e as credenciais (bucket/key) estão corretas.',
                'icon': 'hard-drive'
            },
            'websocket': {
                'severity': 'low',
                'category': 'Network',
                'issue': 'Conexão WebSocket recusada pelo servidor',
                'fix': 'Normal durante reinicializações. Se frequente, verifique firewall e se o servidor está rodando.',
                'icon': 'wifi'
            },
            'refused': {
                'severity': 'low',
                'category': 'Network',
                'issue': 'Conexão de rede recusada',
                'fix': 'Verifique se o serviço destino está rodando e acessível. Confira regras de firewall.',
                'icon': 'network-wired'
            },
            'permission': {
                'severity': 'high',
                'category': 'Security',
                'issue': 'Erro de permissão de acesso a arquivos/diretórios',
                'fix': 'Execute o agente como administrador ou ajuste as permissões NTFS das pastas de backup.',
                'icon': 'lock'
            },
            'timeout': {
                'severity': 'medium',
                'category': 'Performance',
                'issue': 'Timeout em operações de backup ou conexão',
                'fix': 'Aumente os timeouts nas configurações ou verifique a velocidade da rede/disco.',
                'icon': 'clock'
            },
            'disk space': {
                'severity': 'critical',
                'category': 'Storage',
                'issue': 'Espaço em disco insuficiente',
                'fix': 'Libere espaço no disco de destino. Aplique políticas de retenção mais agressivas.',
                'icon': 'hdd'
            }
        }

        for ep in error_patterns:
            msg_lower = ep['pattern'].lower()
            matched = False
            for keyword, rec in recommendations.items():
                if keyword in msg_lower:
                    diagnostics.append({
                        'pattern': ep['pattern'],
                        'count': ep['cnt'],
                        'last_seen': ep['last_seen'].isoformat() if ep['last_seen'] else None,
                        **rec
                    })
                    matched = True
                    break
            if not matched and ep['cnt'] >= 50:
                diagnostics.append({
                    'pattern': ep['pattern'],
                    'count': ep['cnt'],
                    'last_seen': ep['last_seen'].isoformat() if ep['last_seen'] else None,
                    'severity': 'medium' if ep['cnt'] >= 200 else 'low',
                    'category': 'Unknown',
                    'issue': f'Erro recorrente ({ep["cnt"]}x) sem diagnóstico automático',
                    'fix': 'Analise o log detalhado do erro. Verifique o stack trace no módulo de origem.',
                    'icon': 'question-circle'
                })

        # 5.3 — Alertas preemptivos baseados em previsões
        alerts = []
        if predictions.get('disk', {}).get('days_to_critical') is not None:
            days = predictions['disk']['days_to_critical']
            if days <= 7:
                alerts.append({
                    'type': 'critical', 'icon': 'hdd',
                    'title': f'Disco atinge 80% em ~{days} dias',
                    'message': f'Uso atual: {predictions["disk"]["current"]}%. Tendência: +{predictions["disk"]["slope_per_day"]}%/dia.',
                    'action': 'Libere espaço ou aplique retenção mais agressiva nos backups.'
                })
            elif days <= 30:
                alerts.append({
                    'type': 'warning', 'icon': 'hdd',
                    'title': f'Disco atinge 80% em ~{days} dias',
                    'message': f'Uso atual: {predictions["disk"]["current"]}%. Crescimento moderado.',
                    'action': 'Monitore e planeje expansão de armazenamento.'
                })

        if predictions.get('ram', {}).get('trend') == 'up' and predictions['ram'].get('current', 0) > 70:
            alerts.append({
                'type': 'warning', 'icon': 'memory',
                'title': 'Uso de RAM em tendência de alta',
                'message': f'Atual: {predictions["ram"]["current"]}%. Previsão 7d: {predictions["ram"]["predicted_7d"]}%.',
                'action': 'Verifique processos com memory leak. Considere reiniciar os serviços.'
            })

        if predictions.get('failure_rate', {}).get('trend') == 'up':
            alerts.append({
                'type': 'warning', 'icon': 'exclamation-triangle',
                'title': 'Taxa de falha em crescimento',
                'message': f'Atual: {predictions["failure_rate"]["current"]}%. Previsão 7d: {predictions["failure_rate"]["predicted_7d"]}%.',
                'action': 'Investigue os erros mais recentes na aba de diagnóstico.'
            })

        if float(exec_stats.get('failed', 0)) > 0 and r_fail_rate > 30:
            alerts.append({
                'type': 'critical', 'icon': 'times-circle',
                'title': f'Taxa de falha alta: {round(r_fail_rate)}%',
                'message': f'{trend["recent_fails"]} falhas nos últimos 7 dias de {trend["recent_total"]} execuções.',
                'action': 'Verifique as configurações dos jobs com falha e corrija antes de executar novamente.'
            })

        # ── 6. Execuções por Agente ──
        cur.execute("""
            SELECT a.hostname, COUNT(e.id) as total,
                   COUNT(e.id) FILTER (WHERE e.status IN ('completed','success')) as success,
                   COUNT(e.id) FILTER (WHERE e.status = 'failed') as failed,
                   COALESCE(SUM(e.bytes_processed), 0) as total_bytes,
                   COALESCE(AVG(e.duration_seconds) FILTER (WHERE e.duration_seconds > 0), 0) as avg_duration
            FROM agents a
            LEFT JOIN agent_task_executions e ON a.agent_id = e.agent_id
            GROUP BY a.hostname ORDER BY total DESC
        """)
        by_agent = cur.fetchall()

        # ── 7. Execuções por Task ──
        cur.execute("""
            SELECT CASE
                       WHEN COALESCE(NULLIF(t.name,''), '') <> ''
                           THEN 'Task #' || COALESCE(e.task_id::text,'?') || ' - ' || t.name
                       ELSE 'Task #' || COALESCE(e.task_id::text,'?')
                   END as task_name,
                   COUNT(e.id) as total,
                   COUNT(e.id) FILTER (WHERE e.status IN ('completed','success')) as success,
                   COUNT(e.id) FILTER (WHERE e.status = 'failed') as failed,
                   COALESCE(AVG(e.duration_seconds) FILTER (WHERE e.duration_seconds > 0), 0) as avg_duration
            FROM agent_task_executions e
            LEFT JOIN agent_tasks t ON t.agent_id = e.agent_id AND t.task_id = e.task_id
            GROUP BY CASE
                       WHEN COALESCE(NULLIF(t.name,''), '') <> ''
                           THEN 'Task #' || COALESCE(e.task_id::text,'?') || ' - ' || t.name
                       ELSE 'Task #' || COALESCE(e.task_id::text,'?')
                     END
            ORDER BY total DESC
        """)
        by_task = cur.fetchall()

        # ── 8. Timeline de Erros (últimos 14 dias) ──
        cur.execute("""
            SELECT date_trunc('day', started_at)::date as day,
                   COUNT(*) FILTER (WHERE status = 'failed') as failed,
                   COUNT(*) FILTER (WHERE status IN ('completed','success')) as success,
                   COUNT(*) FILTER (WHERE status = 'interrupted') as interrupted,
                   COUNT(*) as total
            FROM agent_task_executions
            WHERE started_at >= LOCALTIMESTAMP - INTERVAL '14 days' AND started_at IS NOT NULL
            GROUP BY date_trunc('day', started_at)::date
            ORDER BY day ASC
        """)
        timeline = cur.fetchall()

        # ── 9. Logs por nível (últimas 24h por hora) ──
        cur.execute("""
            SELECT to_char(date_trunc('hour', timestamp), 'HH24:00') as hour,
                   COUNT(*) FILTER (WHERE level = 'ERROR') as errors,
                   COUNT(*) FILTER (WHERE level = 'WARNING') as warnings,
                   COUNT(*) FILTER (WHERE level = 'INFO') as info
            FROM agent_logs
            WHERE timestamp >= LOCALTIMESTAMP - INTERVAL '24 hours'
            GROUP BY date_trunc('hour', timestamp), to_char(date_trunc('hour', timestamp), 'HH24:00')
            ORDER BY date_trunc('hour', timestamp) ASC
        """)
        log_timeline = cur.fetchall()

        # ── SCORE de saúde geral ──
        health_score = 100
        if r_fail_rate > 50: health_score -= 30
        elif r_fail_rate > 20: health_score -= 15
        elif r_fail_rate > 5: health_score -= 5

        if predictions.get('disk', {}).get('days_to_critical') is not None:
            if predictions['disk']['days_to_critical'] <= 7: health_score -= 20
            elif predictions['disk']['days_to_critical'] <= 30: health_score -= 10

        if agents['online'] < agents['total']: health_score -= 10

        for d in diagnostics:
            if d.get('severity') == 'critical': health_score -= 5
            elif d.get('severity') == 'high': health_score -= 3

        health_score = max(0, min(100, health_score))
        health_status = 'critical' if health_score < 40 else ('warning' if health_score < 70 else 'healthy')

        return {
            'health': {'score': health_score, 'status': health_status},
            'kpis': {
                'agents': {'total': agents['total'], 'online': agents['online']},
                'executions': {
                    'total': exec_stats['total'], 'success': exec_stats['success'],
                    'failed': exec_stats['failed'], 'interrupted': exec_stats['interrupted'],
                    'success_rate': success_rate_all,
                    'avg_duration': round(float(exec_stats['avg_duration']), 1),
                    'total_bytes': exec_stats['total_bytes']
                },
                'last_24h': {
                    'total': last_24h['total'], 'success': last_24h['success'],
                    'failed': last_24h['failed'], 'success_rate': success_rate_24h
                },
                'last_7d': {
                    'total': last_7d['total'], 'success': last_7d['success'],
                    'failed': last_7d['failed']
                }
            },
            'trends': {
                'duration': dur_trend, 'failure_rate': fail_trend,
                'recent_duration': round(r_dur, 1), 'previous_duration': round(p_dur, 1),
                'recent_fail_rate': round(r_fail_rate, 1), 'previous_fail_rate': round(p_fail_rate, 1)
            },
            'system_metrics': system_metrics,
            'predictions': predictions,
            'diagnostics': diagnostics[:15],
            'alerts': alerts,
            'by_agent': [dict(r) for r in by_agent],
            'by_task': [dict(r) for r in by_task],
            'timeline': {
                'labels': [r['day'].strftime('%d/%m') for r in timeline],
                'success': [r['success'] for r in timeline],
                'failed': [r['failed'] for r in timeline],
                'interrupted': [r['interrupted'] for r in timeline]
            },
            'log_timeline': {
                'labels': [r['hour'] for r in log_timeline],
                'errors': [r['errors'] for r in log_timeline],
                'warnings': [r['warnings'] for r in log_timeline],
                'info': [r['info'] for r in log_timeline]
            }
        }
    except Exception as e:
        logger.error(f"Erro analytics comprehensive: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

@app.get("/api/v1/dashboard/stats")
async def stats(request: Request):
    conn = None
    try:
        user = _get_server_user_from_request(request)
        tenant_id = user.get('tenant_id') if user else None
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if tenant_id:
            # Filtro por tenant_id
            cur.execute("""
                SELECT COUNT(*) as total, 
                       COUNT(*) FILTER (WHERE last_heartbeat > (LOCALTIMESTAMP - INTERVAL '60 minutes')) as online 
                FROM agents 
                WHERE tenant_id = %s
            """, (tenant_id,))
            agt = cur.fetchone()
            
            cur.execute("""
                WITH combined AS (
                    SELECT te.status, te.bytes_processed as total_bytes
                    FROM agent_task_executions te
                    LEFT JOIN agents a ON te.agent_id = a.agent_id
                    WHERE te.started_at >= (LOCALTIMESTAMP - INTERVAL '24 hours') AND a.tenant_id = %s
                    UNION ALL
                    SELECT b.status, b.total_bytes
                    FROM backup_reports b
                    LEFT JOIN agents a ON b.agent_id = a.agent_id
                    WHERE b.start_time >= (LOCALTIMESTAMP - INTERVAL '24 hours') AND a.tenant_id = %s
                )
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE status IN ('completed','success')) as success,
                       COUNT(*) FILTER (WHERE status NOT IN ('completed','success')) as failed,
                       COALESCE(SUM(total_bytes), 0) as bytes
                FROM combined
            """, (tenant_id, tenant_id))
            bkp = cur.fetchone()
            
            cur.execute("""
                WITH combined AS (
                    SELECT te.bytes_processed as total_bytes
                    FROM agent_task_executions te
                    LEFT JOIN agents a ON te.agent_id = a.agent_id
                    WHERE te.started_at >= (LOCALTIMESTAMP - INTERVAL '7 days') AND a.tenant_id = %s
                    UNION ALL
                    SELECT b.total_bytes
                    FROM backup_reports b
                    LEFT JOIN agents a ON b.agent_id = a.agent_id
                    WHERE b.start_time >= (LOCALTIMESTAMP - INTERVAL '7 days') AND a.tenant_id = %s
                )
                SELECT COALESCE(SUM(total_bytes), 0) as bytes FROM combined
            """, (tenant_id, tenant_id))
            vol7d = cur.fetchone()
            
            cur.execute("""
                SELECT COUNT(*) as cnt 
                FROM agent_logs al
                LEFT JOIN agents a ON al.agent_id = a.agent_id
                WHERE al.level = 'ERROR' AND al.timestamp >= (LOCALTIMESTAMP - INTERVAL '24 hours') AND a.tenant_id = %s
            """, (tenant_id,))
            alerts = cur.fetchone()
        else:
            # Sem filtro (Global Admin)
            cur.execute("SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE last_heartbeat > (LOCALTIMESTAMP - INTERVAL '60 minutes')) as online FROM agents")
            agt = cur.fetchone()
            
            cur.execute("""
                WITH combined AS (
                    SELECT status, bytes_processed as total_bytes
                    FROM agent_task_executions
                    WHERE started_at >= (LOCALTIMESTAMP - INTERVAL '24 hours')
                    UNION ALL
                    SELECT status, total_bytes
                    FROM backup_reports
                    WHERE start_time >= (LOCALTIMESTAMP - INTERVAL '24 hours')
                )
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE status IN ('completed','success')) as success,
                       COUNT(*) FILTER (WHERE status NOT IN ('completed','success')) as failed,
                       COALESCE(SUM(total_bytes), 0) as bytes
                FROM combined
            """)
            bkp = cur.fetchone()
            
            cur.execute("""
                WITH combined AS (
                    SELECT bytes_processed as total_bytes
                    FROM agent_task_executions
                    WHERE started_at >= (LOCALTIMESTAMP - INTERVAL '7 days')
                    UNION ALL
                    SELECT total_bytes
                    FROM backup_reports
                    WHERE start_time >= (LOCALTIMESTAMP - INTERVAL '7 days')
                )
                SELECT COALESCE(SUM(total_bytes), 0) as bytes FROM combined
            """)
            vol7d = cur.fetchone()
            
            cur.execute("""
                SELECT COUNT(*) as cnt FROM agent_logs
                WHERE level = 'ERROR' AND timestamp >= (LOCALTIMESTAMP - INTERVAL '24 hours')
            """)
            alerts = cur.fetchone()

        return {
            "total_agents": agt['total'], "online_agents": agt['online'],
            "offline_agents": agt['total'] - agt['online'], "backups_24h": bkp['total'], 
            "failed_24h": bkp['failed'],
            "success_rate_24h": int((bkp['success']/bkp['total']*100) if bkp['total']>0 else 100),
            "total_gb_7d": round(vol7d['bytes'] / (1024**3), 2),
            "total_alerts": alerts['cnt']
        }
    except Exception as e:
        logger.error(f"Erro ao obter estatísticas: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

@app.get("/api/v1/agents")
async def list_agents(request: Request):
    conn = None
    try:
        user = _get_server_user_from_request(request)
        tenant_id = user.get('tenant_id') if user else None
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        if tenant_id:
            cur.execute("""SELECT *, CASE WHEN last_heartbeat > (LOCALTIMESTAMP - INTERVAL '60 minutes') THEN 'online' ELSE 'offline' END as current_status FROM agents WHERE tenant_id = %s ORDER BY hostname""", (tenant_id,))
        else:
            cur.execute("""SELECT *, CASE WHEN last_heartbeat > (LOCALTIMESTAMP - INTERVAL '60 minutes') THEN 'online' ELSE 'offline' END as current_status FROM agents ORDER BY hostname""")
        res = cur.fetchall()
        for r in res:
            try: r['available_tools'] = json.loads(r['available_tools'])
            except: pass
        return res
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

@app.get("/api/v1/backups/recent")
async def recent_backups(request: Request, limit: int = 20):
    conn = None
    try:
        user = _get_server_user_from_request(request)
        tenant_id = user.get('tenant_id') if user else None
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if tenant_id:
            # Priorizar execuções sincronizadas (agent_task_executions) filtrando por tenant_id
            cur.execute("""
                SELECT
                    te.status,
                    te.agent_id,
                    a.hostname,
                    CASE
                        WHEN COALESCE(NULLIF(t.name,''), '') <> ''
                            THEN 'Task #' || COALESCE(te.task_id::text,'?') || ' - ' || t.name
                        ELSE 'Task #' || COALESCE(te.task_id::text,'?')
                    END as source_path,
                    te.started_at as start_time,
                    COALESCE(te.duration_seconds,0) as duration_seconds,
                    COALESCE(te.bytes_processed,0) as total_bytes
                FROM agent_task_executions te
                LEFT JOIN agents a ON te.agent_id = a.agent_id
                LEFT JOIN agent_tasks t ON t.agent_id = te.agent_id AND t.task_id = te.task_id
                WHERE te.started_at IS NOT NULL AND a.tenant_id = %s
                ORDER BY te.started_at DESC
                LIMIT %s
            """, (tenant_id, limit))
            rows = cur.fetchall()
            if rows:
                return rows

            # Fallback para backup_reports filtrando por tenant_id
            cur.execute("""
                SELECT b.status, b.agent_id, a.hostname,
                       COALESCE(NULLIF(b.source_path, ''), 'Task') as source_path,
                       b.start_time,
                       COALESCE(b.duration_seconds,0) as duration_seconds,
                       COALESCE(b.total_bytes,0) as total_bytes
                FROM backup_reports b
                LEFT JOIN agents a ON b.agent_id = a.agent_id
                WHERE a.tenant_id = %s
                ORDER BY b.start_time DESC
                LIMIT %s
            """, (tenant_id, limit))
            return cur.fetchall()
        else:
            cur.execute("""
                SELECT
                    te.status,
                    te.agent_id,
                    a.hostname,
                    CASE
                        WHEN COALESCE(NULLIF(t.name,''), '') <> ''
                            THEN 'Task #' || COALESCE(te.task_id::text,'?') || ' - ' || t.name
                        ELSE 'Task #' || COALESCE(te.task_id::text,'?')
                    END as source_path,
                    te.started_at as start_time,
                    COALESCE(te.duration_seconds,0) as duration_seconds,
                    COALESCE(te.bytes_processed,0) as total_bytes
                FROM agent_task_executions te
                LEFT JOIN agents a ON te.agent_id = a.agent_id
                LEFT JOIN agent_tasks t ON t.agent_id = te.agent_id AND t.task_id = te.task_id
                WHERE te.started_at IS NOT NULL
                ORDER BY te.started_at DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
            if rows:
                return rows

            cur.execute("""
                SELECT b.status, b.agent_id, a.hostname,
                       COALESCE(NULLIF(b.source_path, ''), 'Task') as source_path,
                       b.start_time,
                       COALESCE(b.duration_seconds,0) as duration_seconds,
                       COALESCE(b.total_bytes,0) as total_bytes
                FROM backup_reports b
                LEFT JOIN agents a ON b.agent_id = a.agent_id
                ORDER BY b.start_time DESC
                LIMIT %s
        """, (limit,))
        return cur.fetchall()
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

@app.get("/api/v1/events/recent")
async def get_events(limit: int = 20):
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT event_type as type, message, created_at as timestamp, agent_hostname FROM system_events ORDER BY created_at DESC LIMIT %s""", (limit,))
        return cur.fetchall()
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

# --- GBOC SERVER MODULAR ROUTERS INCLUDE (ALL 15 MENU MODULES) ---
try:
    from modules.rmm.rmm_router import router as server_rmm_router
    app.include_router(server_rmm_router)
except Exception as _e: logger.warning(f"RMM router: {_e}")

try:
    from modules.agents.agents_router import router as server_agents_router
    app.include_router(server_agents_router)
except Exception as _e: logger.warning(f"Agents router: {_e}")

try:
    from modules.surerestore.surerestore_router import router as server_surerestore_router
    app.include_router(server_surerestore_router)
except Exception as _e: logger.warning(f"SureRestore router: {_e}")

try:
    from modules.multitenant.multitenant_router import router as server_multitenant_router
    app.include_router(server_multitenant_router)
except Exception as _e: logger.warning(f"MultiTenant router: {_e}")

try:
    from modules.backups.backups_router import router as server_backups_router
    app.include_router(server_backups_router)
except Exception as _e: logger.warning(f"Backups router: {_e}")

try:
    from modules.analytics.analytics_router import router as server_analytics_router
    app.include_router(server_analytics_router)
except Exception as _e: logger.warning(f"Analytics router: {_e}")

try:
    from modules.ransomware.ransomware_router import router as server_ransomware_router
    app.include_router(server_ransomware_router)
except Exception as _e: logger.warning(f"Ransomware router: {_e}")

try:
    from modules.compliance.compliance_router import router as server_compliance_router
    app.include_router(server_compliance_router)
except Exception as _e: logger.warning(f"Compliance router: {_e}")

try:
    from modules.alerts.alerts_router import router as server_alerts_router
    app.include_router(server_alerts_router)
except Exception as _e: logger.warning(f"Alerts router: {_e}")

try:
    from modules.replication.replication_router import router as server_replication_router
    app.include_router(server_replication_router)
except Exception as _e: logger.warning(f"Replication router: {_e}")

try:
    from modules.logs.logs_router import router as server_logs_router
    app.include_router(server_logs_router)
except Exception as _e: logger.warning(f"Logs router: {_e}")

try:
    from modules.reports.reports_router import router as server_reports_router
    app.include_router(server_reports_router)
except Exception as _e: logger.warning(f"Reports router: {_e}")

try:
    from modules.users.users_router import router as server_users_router
    app.include_router(server_users_router)
except Exception as _e: logger.warning(f"Users router: {_e}")

try:
    from modules.config.config_router import router as server_config_router
    app.include_router(server_config_router)
except Exception as _e: logger.warning(f"Config router: {_e}")

try:
    from modules.overview.overview_router import router as server_overview_router
    app.include_router(server_overview_router)
except Exception as _e: logger.warning(f"Overview router: {_e}")

try:
    from modules.active_directory.ad_server_router import router as server_ad_router
    app.include_router(server_ad_router)
except Exception as _e: logger.warning(f"Active Directory router: {_e}")



# --- USER MANAGEMENT API ---
_server_users_store = [
    {"id": 1, "username": "admin", "display_name": "Administrador Principal", "role": "admin", "status": "active"},
    {"id": 2, "username": "operator", "display_name": "Operador de Backups", "role": "operator", "status": "active"},
    {"id": 3, "username": "auditor", "display_name": "Auditor de Compliance", "role": "viewer", "status": "active"}
]

# Note: /api/v1/users routes are provided by modules.users.users_router

# --- SERVER AI CONFIG API ---
_server_ai_config_store = {
    "provider": "ollama",
    "ollama_host": "http://localhost:11434",
    "model": "llama3",
    "api_key": ""
}

@app.get("/api/v1/server/ai-config")
async def get_server_ai_config():
    """Retorna as configurações globais de IA/LLM do Servidor."""
    return {"status": "success", "config": _server_ai_config_store}

@app.post("/api/v1/server/ai-config")
async def save_server_ai_config(request: Request):
    """Salva e atualiza as configurações globais de IA/LLM do Servidor."""
    try:
        body = await request.json()
        _server_ai_config_store.update(body)
        return {"status": "success", "message": "Configurações globais de IA salvas", "config": _server_ai_config_store}
    except Exception as e:
        raise HTTPException(500, detail=str(e))

# --- LOGS API ---
@app.get("/api/v1/logs")
async def get_server_logs(
    level: Optional[str] = None,
    agent_id: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    hours: int = 168
):
    """Consulta logs sincronizados dos agentes"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = ["timestamp >= (LOCALTIMESTAMP - INTERVAL '%s hours')" % hours]
        params = []

        if level:
            conditions.append("UPPER(level) = UPPER(%s)")
            params.append(level)
        if agent_id:
            conditions.append("agent_id = %s")
            params.append(agent_id)
        if source:
            conditions.append("source ILIKE %s")
            params.append(f"%{source}%")
        if search:
            conditions.append("(message ILIKE %s OR details ILIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])

        where = " AND ".join(conditions)
        cur.execute(f"""
            SELECT al.id, al.agent_id, al.level, al.source, al.message, al.details,
                   al.timestamp, a.hostname as agent_name
            FROM agent_logs al
            LEFT JOIN agents a ON al.agent_id = a.agent_id
            WHERE {where}
            ORDER BY al.timestamp DESC
            LIMIT %s
        """, params + [limit])
        logs = cur.fetchall()

        # Serializar timestamps
        for log in logs:
            for k in ['timestamp', 'synced_at']:
                if k in log and log[k] and hasattr(log[k], 'isoformat'):
                    log[k] = log[k].isoformat()

        # Contagem total
        cur.execute(f"SELECT COUNT(*) as total FROM agent_logs WHERE {where}", params)
        total = cur.fetchone()['total']

        return {
            "status": "success",
            "logs": logs,
            "total": total,
            "showing": len(logs),
            "filters": {"level": level, "agent_id": agent_id, "source": source, "hours": hours, "search": search}
        }
    except Exception as e:
        logger.error(f"Erro ao consultar logs: {e}")
        return {"status": "error", "message": str(e), "logs": [], "total": 0, "showing": 0}
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

@app.get("/api/v1/logs/stats")
async def get_server_log_stats():
    """Estatísticas dos logs sincronizados"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE UPPER(level) = 'ERROR') as errors,
                COUNT(*) FILTER (WHERE UPPER(level) = 'WARNING') as warnings,
                COUNT(*) FILTER (WHERE UPPER(level) = 'INFO') as info,
                COUNT(DISTINCT agent_id) as agents_with_logs,
                MIN(timestamp) as oldest,
                MAX(timestamp) as newest
            FROM agent_logs
            WHERE timestamp >= (LOCALTIMESTAMP - INTERVAL '7 days')
        """)
        stats = cur.fetchone()
        for k in ['oldest', 'newest']:
            if stats.get(k) and hasattr(stats[k], 'isoformat'):
                stats[k] = stats[k].isoformat()
        return {"status": "success", **dict(stats)}
    except Exception as e:
        logger.error(f"Erro ao consultar stats de logs: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

@app.get("/api/v1/agents/{agent_id}/logs")
async def get_agent_logs(agent_id: str, level: Optional[str] = None, limit: int = 50, hours: int = 168):
    """Logs de um agente específico"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = ["agent_id = %s", "timestamp >= (LOCALTIMESTAMP - INTERVAL '%s hours')" % hours]
        params = [agent_id]
        if level:
            conditions.append("UPPER(level) = UPPER(%s)")
            params.append(level)
        where = " AND ".join(conditions)
        cur.execute(f"""
            SELECT id, level, source, message, details, timestamp
            FROM agent_logs WHERE {where}
            ORDER BY timestamp DESC LIMIT %s
        """, params + [limit])
        logs = cur.fetchall()
        for log in logs:
            if log.get('timestamp') and hasattr(log['timestamp'], 'isoformat'):
                log['timestamp'] = log['timestamp'].isoformat()
        return {"status": "success", "logs": logs, "total": len(logs), "agent_id": agent_id}
    except Exception as e:
        logger.error(f"Erro ao consultar logs do agente {agent_id}: {e}")
        return {"status": "error", "message": str(e), "logs": []}
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

@app.get("/")
async def index(request: Request):
    # Sempre exigir autenticação — se não há usuários, login.html mostra setup
    user = _get_server_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login.html", status_code=302)
    _dash = os.path.join(os.path.dirname(__file__), "dashboard.html")
    return FileResponse(_dash) if os.path.exists(_dash) else HTMLResponse("Dashboard not found")

# ===========================
# HANDLERS PARA COMUNICAÇÃO EM TEMPO REAL
# ===========================

async def handle_realtime_alert(agent_id: str, data: Dict) -> Dict:
    """Processa alerta em tempo real"""
    if not isinstance(data, dict):
        logger.error(f"Dados de alerta inválidos do agente {agent_id}: {data}")
        return {"status": "error", "message": "Invalid alert data format"}
    
    try:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO system_events (event_type, message, agent_hostname, created_at)
                VALUES (%s, %s, %s, LOCALTIMESTAMP)
                ON CONFLICT DO NOTHING
            ''', (
                f"alert_{data.get('type', 'unknown')}",
                data.get('message', 'Alert from agent'),
                data.get('hostname', agent_id)
            ))
            conn.commit()

            # Broadcast do alerta para todos os clientes conectados
            alert_message = {
                "type": "alert",
                "agent_id": agent_id,
                "data": data,
                "timestamp": _dt.now(timezone.utc).isoformat()
            }
            await manager.broadcast(json.dumps(alert_message))

        finally:
            release_db(conn)

        return {"status": "success"}
    except Exception as e:
        logger.error(f"Erro ao processar alerta do agente {agent_id}: {e}")
        return {"status": "error", "message": str(e)}

# ===========================
# FUNÇÕES AUXILIARES PARA SINCRONIZAÇÃO
# ===========================

async def get_agent_full_data(agent_id: str, since_timestamp: Optional[str] = None) -> Dict:
    """Obtém todos os dados do agente a partir do banco"""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Dados do agente
        cur.execute("SELECT * FROM agents WHERE agent_id = %s", (agent_id,))
        agent = cur.fetchone()
        if not agent:
            return {}

        # Repositórios
        repos = await get_agent_repositories(agent_id, since_timestamp)

        # Tarefas
        tasks = await get_agent_tasks(agent_id, since_timestamp)

        # Execuções recentes
        cur.execute("""
            SELECT * FROM agent_task_executions
            WHERE agent_id = %s ORDER BY started_at DESC LIMIT 100
        """, (agent_id,))
        executions = cur.fetchall()

        # Eventos recentes
        cur.execute("""
            SELECT * FROM system_events
            WHERE agent_hostname = %s OR agent_hostname = (SELECT hostname FROM agents WHERE agent_id = %s)
            ORDER BY created_at DESC LIMIT 50
        """, (agent_id, agent_id))
        events = cur.fetchall()

        return {
            "agent": dict(agent),
            "repositories": repos,
            "tasks": tasks,
            "task_executions": [dict(e) for e in executions],
            "system_events": [dict(e) for e in events]
        }
    except Exception as e:
        logger.error(f"Erro ao obter dados completos do agente {agent_id}: {e}")
        return {}
    finally:
        if 'cur' in locals() and cur:
            cur.close()
        release_db(conn)

async def get_agent_repositories(agent_id: str, since_timestamp: Optional[str] = None) -> List[Dict]:
    """Obtém repositórios do agente a partir do banco"""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if since_timestamp:
            cur.execute("""
                SELECT * FROM agent_repositories
                WHERE agent_id = %s AND synced_at >= %s
                ORDER BY name
            """, (agent_id, since_timestamp))
        else:
            cur.execute("""
                SELECT * FROM agent_repositories
                WHERE agent_id = %s ORDER BY name
            """, (agent_id,))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Erro ao obter repositórios do agente {agent_id}: {e}")
        return []
    finally:
        if 'cur' in locals() and cur:
            cur.close()
        release_db(conn)

async def get_agent_tasks(agent_id: str, since_timestamp: Optional[str] = None) -> List[Dict]:
    """Obtém tarefas do agente a partir do banco"""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if since_timestamp:
            cur.execute("""
                SELECT * FROM agent_tasks
                WHERE agent_id = %s AND synced_at >= %s
                ORDER BY task_id
            """, (agent_id, since_timestamp))
        else:
            cur.execute("""
                SELECT * FROM agent_tasks
                WHERE agent_id = %s ORDER BY task_id
            """, (agent_id,))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Erro ao obter tarefas do agente {agent_id}: {e}")
        return []
    finally:
        if 'cur' in locals() and cur:
            cur.close()
        release_db(conn)


# ═══════════════════════════════════════════════════════════════
# OVERVIEW ENDPOINTS — Aggregated views for server dashboard tabs
# These endpoints provide centralized views across all agents.
# If agent-specific data is not yet synced, they return empty arrays.
# ═══════════════════════════════════════════════════════════════

@app.get("/api/v1/server/ransomware/overview")
async def server_ransomware_overview():
    """Delega para o router dedicado de ransomware para evitar divergência de lógica."""
    try:
        from modules.ransomware.ransomware_router import get_ransomware_overview
        return await get_ransomware_overview()
    except Exception as e:
        logger.error(f"Erro ransomware overview (delegate): {e}")
        return {"protected_agents": 0, "total_canaries": 0, "total_compromised": 0, "scans_7d": 0, "agents": []}


@app.get("/api/v1/server/compliance/overview")
async def server_compliance_overview():
    """Aggregated compliance status across all agents"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            WITH exec_30d AS (
                SELECT
                    a.agent_id,
                    a.hostname,
                    COUNT(e.id) AS total_exec,
                    COUNT(e.id) FILTER (WHERE e.status IN ('completed','success')) AS success_exec,
                    COUNT(e.id) FILTER (WHERE e.status = 'failed') AS failed_exec,
                    MAX(e.started_at) AS last_audit
                FROM agents a
                LEFT JOIN agent_task_executions e
                    ON e.agent_id = a.agent_id
                   AND e.started_at >= (LOCALTIMESTAMP - INTERVAL '30 days')
                GROUP BY a.agent_id, a.hostname
            ),
            task_count AS (
                SELECT agent_id, COUNT(*) AS policies
                FROM agent_tasks
                GROUP BY agent_id
            )
            SELECT
                ex.agent_id,
                ex.hostname,
                COALESCE(tc.policies, 0) AS policies,
                COALESCE(ex.total_exec, 0) AS total_exec,
                COALESCE(ex.success_exec, 0) AS success_exec,
                COALESCE(ex.failed_exec, 0) AS failed_exec,
                ex.last_audit,
                CASE
                    WHEN COALESCE(ex.total_exec, 0) = 0 THEN 0
                    ELSE ROUND((ex.success_exec::numeric / NULLIF(ex.total_exec, 0)) * 100)
                END AS score
            FROM exec_30d ex
            LEFT JOIN task_count tc ON tc.agent_id = ex.agent_id
            ORDER BY ex.hostname
        """)
        rows = cur.fetchall()

        agents = []
        total_score = 0
        total_policies = 0
        total_violations = 0
        last_audit = None

        for r in rows:
            score = int(r.get('score') or 0)
            passing = int(r.get('success_exec') or 0)
            failing = int(r.get('failed_exec') or 0)
            audit = r.get('last_audit')
            audit_iso = audit.isoformat() if hasattr(audit, 'isoformat') else audit

            agents.append({
                "hostname": r.get('hostname') or '—',
                "score": score,
                "passing": passing,
                "failing": failing,
                "last_audit": audit_iso
            })

            total_score += score
            total_policies += int(r.get('policies') or 0)
            total_violations += failing
            if audit and (last_audit is None or audit > last_audit):
                last_audit = audit

        avg_score = round(total_score / len(agents), 1) if agents else 0

        return {
            "avg_score": avg_score,
            "total_policies": total_policies,
            "total_violations": total_violations,
            "last_audit": last_audit.isoformat() if hasattr(last_audit, 'isoformat') else last_audit,
            "agents": agents
        }
    except Exception as e:
        logger.error(f"Erro compliance overview: {e}")
        return {"avg_score": 0, "total_policies": 0, "total_violations": 0, "last_audit": None, "agents": []}
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)
@app.get("/api/v1/server/alerts/overview")
async def server_alerts_overview(severity: Optional[str] = None):
    """Aggregated alerts from system_events across all agents"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = ["1=1"]
        params = []
        if severity:
            event_map = {
                'critical': ['backup_failure', 'error'],
                'warning': ['warning'],
                'info': ['backup_success', 'info', 'system']
            }
            evt_types = event_map.get(severity, [severity])
            placeholders = ','.join(['%s'] * len(evt_types))
            conditions.append(f"event_type IN ({placeholders})")
            params.extend(evt_types)

        where = " AND ".join(conditions)
        cur.execute(f"""
            SELECT event_id, event_type, message, agent_hostname, created_at, is_read
            FROM system_events WHERE {where}
            ORDER BY created_at DESC LIMIT 50
        """, params)
        events = cur.fetchall()

        cur.execute("SELECT COUNT(*) as total FROM system_events")
        total = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) as cnt FROM system_events WHERE is_read = FALSE")
        unread = cur.fetchone()['cnt']
        cur.execute("SELECT COUNT(*) as cnt FROM system_events WHERE event_type IN ('backup_failure','error','alert_critical')")
        critical = cur.fetchone()['cnt']

        def map_severity(evt_type):
            if evt_type in ('backup_failure', 'error'): return 'critical'
            if evt_type in ('warning',): return 'warning'
            return 'info'

        return {
            "total": total,
            "unread": unread,
            "critical": critical,
            "alerts": [{
                "id": e['event_id'],
                "severity": map_severity(e.get('event_type', '')),
                "hostname": e.get('agent_hostname', ''),
                "title": e.get('event_type', '').replace('_', ' ').title(),
                "message": e.get('message', ''),
                "created_at": e['created_at'].isoformat() if hasattr(e.get('created_at'), 'isoformat') else e.get('created_at'),
                "is_read": e.get('is_read', False)
            } for e in events]
        }
    except Exception as e:
        logger.error(f"Erro alerts overview: {e}")
        return {"total": 0, "unread": 0, "critical": 0, "alerts": []}
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.get("/api/v1/server/replication/overview")
async def server_replication_overview():
    """Aggregated replication status across all agents"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT agent_id, hostname FROM agents ORDER BY hostname")
        agents = cur.fetchall()
        return {
            "total_rules": 0,
            "syncing": 0,
            "total_bytes": 0,
            "errors_24h": 0,
            "agents": [{
                "hostname": a['hostname'],
                "rules": 0,
                "syncing": 0,
                "volume": 0,
                "last_sync": None,
                "status": "ok"
            } for a in agents]
        }
    except Exception as e:
        logger.error(f"Erro replication overview: {e}")
        return {"total_rules": 0, "syncing": 0, "total_bytes": 0, "errors_24h": 0, "agents": []}
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.get("/api/v1/auth/users")
async def list_server_users():
    """List all server dashboard users"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, username, display_name, role, created_at, last_login
            FROM server_auth_users ORDER BY username
        """)
        users = cur.fetchall()
        for u in users:
            for k in ['created_at', 'last_login']:
                if u.get(k) and hasattr(u[k], 'isoformat'):
                    u[k] = u[k].isoformat()
        cur.execute("SELECT COUNT(*) FROM server_auth_tokens WHERE expires_at > LOCALTIMESTAMP")
        active_sessions = cur.fetchone()['count'] if cur.rowcount != -1 else 0
        # fetchone retorna dict com RealDictCursor
        try:
            active_sessions = int(active_sessions)
        except Exception:
            active_sessions = 0
        return {"users": users, "active_sessions": active_sessions}
    except Exception as e:
        logger.error(f"Erro list users: {e}")
        return {"users": []}
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.delete("/api/v1/auth/users/{user_id}")
async def delete_server_user(user_id: int, request: Request):
    """Delete a server dashboard user"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor()
        # Impedir auto-exclusão
        me = _get_server_user_from_request(request)
        if me and me.get("user_id") == user_id:
            raise HTTPException(400, "Não é possível excluir o próprio usuário")
        cur.execute("DELETE FROM server_auth_users WHERE id = %s", (user_id,))
        conn.commit()
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


class _UserCreateReq(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    role: str = "admin"

class _UserUpdateReq(BaseModel):
    password: Optional[str] = None
    display_name: Optional[str] = None
    role: Optional[str] = None

class _ChangePwReq(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/v1/auth/users")
async def create_server_user(req: _UserCreateReq, request: Request):
    """Create a new server dashboard user"""
    if len(req.password) < 4:
        raise HTTPException(400, "Senha deve ter pelo menos 4 caracteres")
    conn = None
    try:
        conn = get_db(); cur = conn.cursor()
        pw_hash = _hash_password(req.password)
        cur.execute(
            "INSERT INTO server_auth_users (username, password_hash, display_name, role) VALUES (%s,%s,%s,%s) RETURNING id",
            (req.username, pw_hash, req.display_name or req.username, req.role)
        )
        new_id = cur.fetchone()[0]
        me = _get_server_user_from_request(request)
        cur.execute(
            "INSERT INTO server_auth_audit (user_id, username, action, ip_address, details) VALUES (%s,%s,'auth.user_created',%s,%s)",
            (me["user_id"] if me else None, me["username"] if me else "system",
             request.client.host if request.client else "unknown", f"created: {req.username}")
        )
        conn.commit()
        return {"status": "success", "id": new_id}
    except Exception as e:
        if conn: conn.rollback()
        detail = str(e)
        if "unique" in detail.lower():
            raise HTTPException(409, f"Usuário '{req.username}' já existe")
        raise HTTPException(500, detail)
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.put("/api/v1/auth/users/{user_id}")
async def update_server_user(user_id: int, req: _UserUpdateReq, request: Request):
    """Reset password or update display_name/role for a server user"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor()
        if req.password:
            if len(req.password) < 4:
                raise HTTPException(400, "Senha deve ter pelo menos 4 caracteres")
            pw_hash = _hash_password(req.password)
            cur.execute("UPDATE server_auth_users SET password_hash=%s WHERE id=%s", (pw_hash, user_id))
            # Invalidar tokens do usuário para forçar re-login
            cur.execute("DELETE FROM server_auth_tokens WHERE user_id=%s", (user_id,))
        if req.display_name is not None:
            cur.execute("UPDATE server_auth_users SET display_name=%s WHERE id=%s", (req.display_name, user_id))
        if req.role is not None:
            cur.execute("UPDATE server_auth_users SET role=%s WHERE id=%s", (req.role, user_id))
        me = _get_server_user_from_request(request)
        cur.execute(
            "INSERT INTO server_auth_audit (user_id, username, action, ip_address, details) VALUES (%s,%s,'auth.user_updated',%s,%s)",
            (me["user_id"] if me else None, me["username"] if me else "system",
             request.client.host if request.client else "unknown", f"updated user_id={user_id}")
        )
        conn.commit()
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.post("/api/v1/auth/change-password")
async def change_own_password(req: _ChangePwReq, request: Request):
    """Allow authenticated user to change their own password"""
    me = _get_server_user_from_request(request)
    if not me:
        raise HTTPException(401, "Não autenticado")
    conn = None
    try:
        conn = get_db(); cur = conn.cursor()
        old_hash = _hash_password(req.current_password)
        cur.execute("SELECT id FROM server_auth_users WHERE id=%s AND password_hash=%s", (me["user_id"], old_hash))
        if not cur.fetchone():
            raise HTTPException(400, "Senha atual incorreta")
        if len(req.new_password) < 4:
            raise HTTPException(400, "Nova senha deve ter pelo menos 4 caracteres")
        new_hash = _hash_password(req.new_password)
        cur.execute("UPDATE server_auth_users SET password_hash=%s WHERE id=%s", (new_hash, me["user_id"]))
        # Invalidar outros tokens (exceto o atual)
        current_token = request.cookies.get("gboc_server_token") or \
            (request.headers.get("Authorization","")[7:] if request.headers.get("Authorization","").startswith("Bearer ") else None)
        if current_token:
            cur.execute("DELETE FROM server_auth_tokens WHERE user_id=%s AND token!=%s", (me["user_id"], current_token))
        else:
            cur.execute("DELETE FROM server_auth_tokens WHERE user_id=%s", (me["user_id"],))
        cur.execute(
            "INSERT INTO server_auth_audit (user_id, username, action, ip_address) VALUES (%s,%s,'auth.password_changed',%s)",
            (me["user_id"], me["username"], request.client.host if request.client else "unknown")
        )
        conn.commit()
        return {"status": "success", "message": "Senha alterada com sucesso"}
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.get("/api/v1/auth/users/audit")
async def get_auth_audit(limit: int = 50, request: Request = None):
    """Get authentication audit log"""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, username, action, ip_address, details, timestamp
            FROM server_auth_audit
            ORDER BY timestamp DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        for r in rows:
            if r.get('timestamp') and hasattr(r['timestamp'], 'isoformat'):
                r['timestamp'] = r['timestamp'].isoformat()
        # Contar sessões ativas
        cur.execute("SELECT COUNT(*) FROM server_auth_tokens WHERE expires_at > LOCALTIMESTAMP")
        active_sessions = cur.fetchone()['count']
        return {"entries": rows, "active_sessions": active_sessions}
    except Exception as e:
        logger.error(f"Erro audit: {e}")
        return {"entries": [], "active_sessions": 0}
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


# ══════════════════════════════════════════════════════════════════
# SERVER SETTINGS — Complete CRUD
# ══════════════════════════════════════════════════════════════════

@app.get("/api/v1/server/settings")
async def get_all_server_settings():
    """Get all server settings grouped by category."""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT category, key, value, type, description, updated_at
            FROM server_settings ORDER BY category, key
        """)
        rows = cur.fetchall()
        grouped = {}
        for r in rows:
            cat = r['category']
            if cat not in grouped:
                grouped[cat] = {}
            val = r['value']
            if r['type'] == 'boolean':
                val = val.lower() in ('true', '1', 'yes')
            elif r['type'] == 'number':
                try:
                    val = int(val) if '.' not in str(val) else float(val)
                except (ValueError, TypeError):
                    pass
            grouped[cat][r['key']] = {
                'value': val,
                'type': r['type'],
                'description': r['description'],
                'updated_at': r['updated_at'].isoformat() if hasattr(r['updated_at'], 'isoformat') else r['updated_at']
            }
        return {
            "settings": grouped,
            "categories": list(grouped.keys()),
            "total": len(rows)
        }
    except Exception as e:
        logger.error(f"Erro get settings: {e}")
        return {"settings": {}, "categories": [], "total": 0}
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.get("/api/v1/server/settings/{category}")
async def get_category_server_settings(category: str):
    """Get settings for a specific category."""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT key, value, type, description, updated_at
            FROM server_settings WHERE category = %s ORDER BY key
        """, (category,))
        rows = cur.fetchall()
        settings = {}
        for r in rows:
            val = r['value']
            if r['type'] == 'boolean':
                val = val.lower() in ('true', '1', 'yes')
            elif r['type'] == 'number':
                try:
                    val = int(val) if '.' not in str(val) else float(val)
                except (ValueError, TypeError):
                    pass
            settings[r['key']] = {
                'value': val,
                'type': r['type'],
                'description': r['description'],
                'updated_at': r['updated_at'].isoformat() if hasattr(r['updated_at'], 'isoformat') else r['updated_at']
            }
        return {"category": category, "settings": settings, "total": len(settings)}
    except Exception as e:
        logger.error(f"Erro get category settings: {e}")
        return {"category": category, "settings": {}, "total": 0}
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.put("/api/v1/server/settings/{category}/{key}")
async def update_server_setting(category: str, key: str, request: Request):
    """Update a single server setting."""
    conn = None
    try:
        data = await request.json()
        value = str(data.get('value', ''))
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            UPDATE server_settings
            SET value = %s, updated_at = CURRENT_TIMESTAMP
            WHERE category = %s AND key = %s
        """, (value, category, key))
        if cur.rowcount == 0:
            raise HTTPException(404, f"Setting {category}/{key} not found")
        conn.commit()
        return {"status": "success", "category": category, "key": key, "value": value}
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.put("/api/v1/server/settings")
async def bulk_update_server_settings(request: Request):
    """Bulk update settings. Body: { category: { key: value, ... }, ... }"""
    conn = None
    try:
        data = await request.json()
        conn = get_db(); cur = conn.cursor()
        updated = 0
        for category, settings in data.items():
            if not isinstance(settings, dict):
                continue
            for key, value in settings.items():
                cur.execute("""
                    UPDATE server_settings
                    SET value = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE category = %s AND key = %s
                """, (str(value), category, key))
                updated += cur.rowcount
        conn.commit()
        return {"status": "success", "updated": updated}
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.post("/api/v1/server/settings/reset")
async def reset_server_settings():
    """Reset all server settings to defaults."""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("DELETE FROM server_settings")
        conn.commit()
        release_db(conn); conn = None
        init_database()
        return {"status": "success", "message": "Settings reset to defaults"}
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if conn: release_db(conn)


@app.post("/api/v1/server/settings/export")
async def export_server_settings():
    """Export all settings as JSON."""
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT category, key, value, type, description FROM server_settings ORDER BY category, key")
        rows = cur.fetchall()
        return {
            "export": rows,
            "exported_at": _dt.now(timezone.utc).isoformat(),
            "server_version": SERVER_VERSION,
            "total": len(rows)
        }
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.post("/api/v1/server/settings/import")
async def import_server_settings(request: Request):
    """Import settings from exported JSON."""
    conn = None
    try:
        data = await request.json()
        items = data.get('export', data.get('settings', []))
        if not items:
            raise HTTPException(400, "No settings to import")
        conn = get_db(); cur = conn.cursor()
        imported = 0
        for item in items:
            cur.execute("""
                INSERT INTO server_settings (category, key, value, type, description, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (category, key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
            """, (item['category'], item['key'], item['value'], item.get('type', 'text'), item.get('description', '')))
            imported += 1
        conn.commit()
        return {"status": "success", "imported": imported}
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


# ── Relatórios Consolidados ───────────────────────────────────────────────────

@app.get("/api/v1/reports/consolidated")
async def get_consolidated_report(request: Request, days: int = 30):
    """
    Relatório consolidado de todos os agentes: resumo por agente, totais globais,
    top falhas, volume de dados, taxa de sucesso e tendência nos últimos N dias.
    """
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)

        # Resumo global
        cur.execute("""
            SELECT
                COUNT(DISTINCT a.agent_id) AS total_agents,
                COUNT(DISTINCT CASE WHEN a.status='online' THEN a.agent_id END) AS online_agents,
                COALESCE(SUM(br.total_bytes), 0) AS total_bytes,
                COUNT(br.report_id) AS total_reports,
                COUNT(CASE WHEN br.status='success' THEN 1 END) AS success_count,
                COUNT(CASE WHEN br.status='failed'  THEN 1 END) AS fail_count
            FROM agents a
            LEFT JOIN backup_reports br
                ON br.agent_id = a.agent_id
                AND br.created_at >= LOCALTIMESTAMP - INTERVAL '%s days'
        """, (days,))
        g = cur.fetchone()

        success_rate = round(g['success_count'] / g['total_reports'] * 100, 1) if g['total_reports'] else 0.0

        # Por agente
        cur.execute("""
            SELECT
                a.agent_id, a.hostname, a.ip_address, a.status,
                a.agent_version, a.last_heartbeat,
                COUNT(br.report_id) AS backups,
                COUNT(CASE WHEN br.status='success' THEN 1 END) AS successes,
                COUNT(CASE WHEN br.status='failed'  THEN 1 END) AS failures,
                COALESCE(SUM(br.total_bytes), 0) AS total_bytes,
                COALESCE(AVG(br.duration_seconds), 0) AS avg_duration
            FROM agents a
            LEFT JOIN backup_reports br
                ON br.agent_id = a.agent_id
                AND br.created_at >= LOCALTIMESTAMP - INTERVAL '%s days'
            GROUP BY a.agent_id, a.hostname, a.ip_address, a.status, a.agent_version, a.last_heartbeat
            ORDER BY backups DESC
        """, (days,))
        agents_data = cur.fetchall()
        for row in agents_data:
            row['last_heartbeat'] = row['last_heartbeat'].isoformat() if row.get('last_heartbeat') and hasattr(row['last_heartbeat'], 'isoformat') else None
            row['avg_duration'] = round(float(row['avg_duration'] or 0), 1)
            row['success_rate'] = round(row['successes'] / row['backups'] * 100, 1) if row['backups'] else 0.0

        # Top 10 falhas recentes
        cur.execute("""
            SELECT br.agent_id, a.hostname, br.backup_type AS job_name, br.error_message, br.created_at AS executed_at
            FROM backup_reports br
            JOIN agents a ON a.agent_id = br.agent_id
            WHERE br.status = 'failed'
              AND br.created_at >= LOCALTIMESTAMP - INTERVAL '%s days'
            ORDER BY br.created_at DESC
            LIMIT 10
        """, (days,))
        failures = cur.fetchall()
        for row in failures:
            row['executed_at'] = row['executed_at'].isoformat() if row.get('executed_at') and hasattr(row['executed_at'], 'isoformat') else None

        # Tendência diária (últimos N dias)
        cur.execute("""
            SELECT
                DATE(created_at) AS day,
                COUNT(*) AS total,
                COUNT(CASE WHEN status='success' THEN 1 END) AS successes,
                COUNT(CASE WHEN status='failed'  THEN 1 END) AS failures,
                COALESCE(SUM(total_bytes), 0) AS bytes
            FROM backup_reports
            WHERE created_at >= LOCALTIMESTAMP - INTERVAL '%s days'
            GROUP BY DATE(created_at)
            ORDER BY day
        """, (days,))
        trend = cur.fetchall()
        for row in trend:
            row['day'] = row['day'].isoformat() if row.get('day') and hasattr(row['day'], 'isoformat') else str(row.get('day'))

        return {
            "period_days": days,
            "generated_at": _dt.now(timezone.utc).isoformat(),
            "global": {
                "total_agents": g['total_agents'],
                "online_agents": g['online_agents'],
                "total_bytes": int(g['total_bytes'] or 0),
                "total_reports": g['total_reports'],
                "success_count": g['success_count'],
                "fail_count": g['fail_count'],
                "success_rate": success_rate,
            },
            "agents": [dict(r) for r in agents_data],
            "top_failures": [dict(r) for r in failures],
            "trend": [dict(r) for r in trend],
        }
    except Exception as e:
        logger.error(f"Erro relatório consolidado: {e}")
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)

# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/server/info")
async def get_server_info():
    """Get comprehensive server information."""
    import platform
    conn = None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT COUNT(*) as total FROM agents")
        total_agents = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) as online FROM agents WHERE last_heartbeat > (LOCALTIMESTAMP - INTERVAL '60 minutes')")
        online_agents = cur.fetchone()['online']
        cur.execute("SELECT COUNT(*) as total FROM backup_reports")
        total_reports = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) as total FROM system_events WHERE created_at > (LOCALTIMESTAMP - INTERVAL '24 hours')")
        events_24h = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) as total FROM agent_logs")
        total_logs = cur.fetchone()['total']

        cur.execute("SELECT pg_database_size(current_database()) as size")
        db_size = cur.fetchone()['size']

        cur.execute("SELECT MIN(registered_at) as first FROM agents")
        first = cur.fetchone()['first']

        return {
            "version": SERVER_VERSION,
            "name": "GBOC Server",
            "hostname": platform.node(),
            "platform": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "url": f"http://{(os.getenv('SERVER_PUBLIC_HOST') or platform.node() or 'localhost')}:{int(os.getenv('SERVER_PORT','8000'))}",
            "agents": {"total": total_agents, "online": online_agents},
            "database": {
                "type": "PostgreSQL",
                "host": DB_CONFIG['host'],
                "port": DB_CONFIG['port'],
                "name": DB_CONFIG['database'],
                "size_bytes": db_size,
                "size_human": _fmt_bytes(db_size) if db_size else "0 B",
            },
            "stats": {
                "backup_reports": total_reports,
                "events_24h": events_24h,
                "total_logs": total_logs,
            },
            "first_agent": first.isoformat() if first and hasattr(first, 'isoformat') else None,
            "websocket_connections": len(manager.active_connections),
            "timestamp": _dt.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Erro server info: {e}")
        return {"version": SERVER_VERSION, "error": str(e)}
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.post("/api/v1/server/maintenance/cleanup")
async def server_maintenance_cleanup(request: Request):
    """Clean old data based on retention settings."""
    conn = None
    try:
        data = await request.json() if request.headers.get('content-type') == 'application/json' else {}
        conn = get_db(); cur = conn.cursor()

        cur2 = conn.cursor(cursor_factory=RealDictCursor)
        cur2.execute("SELECT key, value FROM server_settings WHERE category = 'retention'")
        retention = {r['key']: int(r['value']) for r in cur2.fetchall()}
        cur2.close()

        metrics_days = retention.get('metrics_retention_days', 90)
        logs_days = retention.get('logs_retention_days', 30)
        events_days = retention.get('events_retention_days', 60)

        deleted = {}
        cur.execute("DELETE FROM agent_metrics WHERE timestamp < (LOCALTIMESTAMP - make_interval(days := %s))", (metrics_days,))
        deleted['agent_metrics'] = cur.rowcount
        cur.execute("DELETE FROM agent_logs WHERE timestamp < (LOCALTIMESTAMP - make_interval(days := %s))", (logs_days,))
        deleted['agent_logs'] = cur.rowcount
        cur.execute("DELETE FROM system_events WHERE created_at < (LOCALTIMESTAMP - make_interval(days := %s))", (events_days,))
        deleted['system_events'] = cur.rowcount
        cur.execute("DELETE FROM server_auth_tokens WHERE expires_at < LOCALTIMESTAMP")
        deleted['expired_tokens'] = cur.rowcount

        conn.commit()
        total = sum(deleted.values())
        return {
            "status": "success",
            "deleted": deleted,
            "total_deleted": total,
            "retention_config": {"metrics_days": metrics_days, "logs_days": logs_days, "events_days": events_days}
        }
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        release_db(conn)


@app.post("/api/v1/server/test-notification")
async def test_server_notification(request: Request):
    """Test server notification (SMTP or webhook)."""
    conn = None
    try:
        data = await request.json()
        channel = data.get('channel', 'email')

        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT key, value FROM server_settings WHERE category = 'notifications'")
        notif = {r['key']: r['value'] for r in cur.fetchall()}

        if channel == 'email':
            import smtplib
            from email.mime.text import MIMEText
            host = notif.get('smtp_host', '')
            port = int(notif.get('smtp_port', 587))
            user = notif.get('smtp_username', '')
            pwd = notif.get('smtp_password', '')
            frm = notif.get('smtp_from', user)
            to = notif.get('smtp_to', user)
            if not host or not user:
                raise HTTPException(400, "SMTP não configurado")
            msg = MIMEText(f"Teste de notificação do GBOC Server v{SERVER_VERSION}\n{_dt.now(timezone.utc).isoformat()}")
            msg['Subject'] = '[GBOC Server] Teste de Notificação'
            msg['From'] = frm
            msg['To'] = to
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls()
                s.login(user, pwd)
                s.send_message(msg)
            return {"status": "success", "channel": "email", "to": to}

        elif channel == 'webhook':
            import urllib.request
            url = notif.get('webhook_url', '')
            if not url:
                raise HTTPException(400, "Webhook URL não configurada")
            payload = json.dumps({
                "text": f"🔔 Teste de notificação — GBOC Server v{SERVER_VERSION} — {_dt.now(timezone.utc).isoformat()}"
            }).encode('utf-8')
            req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=10)
            return {"status": "success", "channel": "webhook", "url": url}

        else:
            raise HTTPException(400, f"Canal inválido: {channel}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur: cur.close()
        if conn: release_db(conn)


# ── Alertas críticos dos agentes → propagação de notificações ─────────────────

_CRITICAL_SEVERITIES = {"critical", "high", "error"}

@app.post("/api/v1/agents/alert")
async def receive_agent_alert(request: Request):
    """
    Recebe alerta de um agente e propaga via SMTP/Webhook se a severidade for crítica.
    Payload esperado: {agent_id, hostname, severity, title, message, timestamp?}
    """
    conn = None
    try:
        data = await request.json()
        agent_id  = data.get("agent_id", "unknown")
        hostname  = data.get("hostname", agent_id)
        severity  = str(data.get("severity", "info")).lower()
        title     = data.get("title", "Alerta")
        message   = data.get("message", "")
        ts        = data.get("timestamp", _dt.now(timezone.utc).isoformat())

        # Persistir no system_events se tabela existir
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute("""
                INSERT INTO system_events (agent_id, event_type, severity, message, timestamp)
                VALUES (%s, 'alert', %s, %s, COALESCE(%s::timestamp, LOCALTIMESTAMP))
                ON CONFLICT DO NOTHING
            """, (agent_id, severity, f"[{title}] {message}", ts))
            conn.commit()
        except Exception:
            if conn: conn.rollback()

        # Propagar se criticidade alta
        if severity in _CRITICAL_SEVERITIES:
            subject = f"[GBOC] 🚨 {severity.upper()} — {hostname}: {title}"
            body = (
                f"Agente  : {hostname} ({agent_id})\n"
                f"Severidade: {severity.upper()}\n"
                f"Título  : {title}\n"
                f"Mensagem: {message}\n"
                f"Data/Hora: {ts}\n"
            )
            result = await _send_server_notification(subject, body)
            logger.warning(f"🔔 Alerta crítico de {hostname}: {title} — notificação: {result}")
        else:
            result = {"sent": []}

        await notify_dashboard_update()
        return {"status": "received", "propagated": severity in _CRITICAL_SEVERITIES, "notification": result}

    except Exception as e:
        logger.error(f"Erro ao processar alerta do agente: {e}")
        raise HTTPException(500, str(e))
    finally:
        if 'cur' in locals() and cur and not cur.closed: cur.close()
        if conn: release_db(conn)

# ─────────────────────────────────────────────────────────────────────────────
# RMM PROXY & WEB MIRROR & SERVER AI/LLM CONFIG
# ─────────────────────────────────────────────────────────────────────────────



@app.get("/api/v1/server/ai-config")
async def get_server_ai_config():
    """Retorna configuração de IA do servidor."""
    return {
        "provider": os.getenv("GBOC_AI_PROVIDER", "ollama"),
        "ollama_host": os.getenv("GBOC_OLLAMA_HOST", "http://localhost:11434"),
        "model": os.getenv("GBOC_AI_MODEL", "llama3"),
        "cloud_api_key": "***" if os.getenv("GBOC_AI_KEY") else ""
    }

@app.post("/api/v1/server/ai-config")
async def update_server_ai_config(request: Request):
    """Atualiza configuração de IA do servidor."""
    body = await request.json()
    os.environ["GBOC_AI_PROVIDER"] = body.get("provider", "ollama")
    os.environ["GBOC_OLLAMA_HOST"] = body.get("ollama_host", "http://localhost:11434")
    os.environ["GBOC_AI_MODEL"] = body.get("model", "llama3")
    if body.get("cloud_api_key"):
        os.environ["GBOC_AI_KEY"] = body.get("cloud_api_key")
    return {"status": "success", "message": "Configurações de IA salvas com sucesso!"}

try:
    from modules.ai_assistant.ai_assistant_router import router as server_ai_router
    app.include_router(server_ai_router)
except Exception as _ai_err:
    logger.warning(f"Falha ao carregar ai_assistant_router no GBOC-Server: {_ai_err}")


def _fmt_bytes(b):
    """Format bytes to human-readable string."""
    if not b or b == 0:
        return "0 B"
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    val = float(b)
    while val >= 1024 and i < len(units) - 1:
        val /= 1024
        i += 1
    return f"{val:.1f} {units[i]}"


if __name__ == "__main__":
    import asyncio, sys, os, datetime, ipaddress
    from pathlib import Path

    _http2 = os.getenv("GBOC_HTTP2", "true").lower() in ("1", "true", "yes")
    _host = os.getenv("SERVER_HOST", "0.0.0.0")
    _port = int(os.getenv("SERVER_PORT", "8000"))
    # Porta HTTP que redireciona para HTTPS (0 = desativado)
    _http_port = int(os.getenv("SERVER_HTTP_PORT", "8079"))

    def _ensure_cert() -> tuple[str, str]:
        """Gera certificado autoassinado em GBOC-Server/data/ se necessário."""
        _dir = Path(__file__).parent / "data"
        _dir.mkdir(parents=True, exist_ok=True)
        cert_path = Path(os.getenv("GBOC_TLS_CERT", str(_dir / "gboc_tls_cert.pem")))
        key_path  = Path(os.getenv("GBOC_TLS_KEY",  str(_dir / "gboc_tls_key.pem")))
        if cert_path.exists() and key_path.exists():
            return str(cert_path), str(key_path)
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = _dt.now(timezone.utc)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "GBOC-Server"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "GBOC"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject).issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )
        key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        print(f"[TLS] Certificado gerado: {cert_path}")
        return str(cert_path), str(key_path)

    async def _redirect_app(scope, receive, send):
        """App ASGI mínimo: redireciona toda requisição HTTP para HTTPS."""
        if scope["type"] == "http":
            host = ""
            for name, value in scope.get("headers", []):
                if name == b"host":
                    host = value.decode().split(":")[0]
                    break
            path = scope.get("path", "/")
            qs = scope.get("query_string", b"")
            location = f"https://{host}:{_port}{path}"
            if qs:
                location += f"?{qs.decode()}"
            await send({"type": "http.response.start", "status": 301,
                        "headers": [[b"location", location.encode()],
                                    [b"content-length", b"0"]]})
            await send({"type": "http.response.body", "body": b""})

    if _http2:
        try:
            from hypercorn.config import Config
            from hypercorn.asyncio import serve

            # ── Monkey-patch: Python 3.14 levanta TimeoutError no SSL shutdown
            # dentro do client_connected_cb do Hypercorn (não capturável via try/except
            # externo). Silenciamos apenas esse TimeoutError no _close() do TCPServer.
            try:
                import hypercorn.asyncio.tcp_server as _tcp_mod
                _orig_close = _tcp_mod.TCPServer._close

                async def _patched_close(self):  # type: ignore[override]
                    try:
                        await _orig_close(self)
                    except TimeoutError:
                        pass
                    except Exception:
                        pass

                _tcp_mod.TCPServer._close = _patched_close
            except Exception:
                pass  # Se a estrutura interna mudar, ignora o patch

            # Suprimir ruídos benignos de SSL no loop asyncio (Python 3.14 + Hypercorn)
            def _install_asyncio_ssl_ignore(loop: asyncio.AbstractEventLoop):
                prev_handler = loop.get_exception_handler()

                def _handler(current_loop, context):
                    exc = context.get("exception")
                    if isinstance(exc, TimeoutError) and "SSL shutdown timed out" in str(exc):
                        return
                    if prev_handler is not None:
                        prev_handler(current_loop, context)
                    else:
                        current_loop.default_exception_handler(context)

                loop.set_exception_handler(_handler)

            _cert, _key = _ensure_cert()

            # Config HTTPS principal
            cfg_https = Config()
            cfg_https.bind = [f"{_host}:{_port}"]
            cfg_https.certfile = _cert
            cfg_https.keyfile  = _key
            cfg_https.alpn_protocols = ["h2", "http/1.1"]
            cfg_https.loglevel = "info"
            cfg_https.keep_alive_timeout = 30
            cfg_https.graceful_timeout = 5
            cfg_https.shutdown_timeout = 120

            print(f"[GBOC Server] HTTPS/HTTP2 em https://{_host}:{_port}")
            print(f"[GBOC Server] Acesse: https://localhost:{_port}")

            if _http_port:
                # Config HTTP redirector (sem TLS)
                cfg_http = Config()
                cfg_http.bind = [f"{_host}:{_http_port}"]
                cfg_http.loglevel = "warning"
                print(f"[GBOC Server] HTTP->HTTPS redirector em http://{_host}:{_http_port}")

                async def _run_both():
                    _install_asyncio_ssl_ignore(asyncio.get_running_loop())
                    await asyncio.gather(
                        serve(app, cfg_https),
                        serve(_redirect_app, cfg_http),
                    )

                asyncio.run(_run_both())
            else:
                async def _run_https_only():
                    _install_asyncio_ssl_ignore(asyncio.get_running_loop())
                    await serve(app, cfg_https)

                asyncio.run(_run_https_only())

        except ImportError:
            print("[GBOC Server] hypercorn não encontrado — usando uvicorn (HTTP/1.1). Execute: pip install hypercorn[h2]")
            import uvicorn
            uvicorn.run(app, host=_host, port=_port)
        except Exception as e:
            print(f"[GBOC Server] Hypercorn falhou ({e}) — fallback para Uvicorn com TLS (HTTP/1.1+SSL)")
            import uvicorn
            _cert, _key = _ensure_cert()
            uvicorn.run(app, host=_host, port=_port,
                        ssl_certfile=_cert, ssl_keyfile=_key,
                        log_level="info")
    else:
        import uvicorn
        print(f"[GBOC Server] HTTP/1.1 via Uvicorn em http://{_host}:{_port}")
        uvicorn.run(app, host=_host, port=_port)





