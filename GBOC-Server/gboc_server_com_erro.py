"""
GBOC Server 11.7c
Servidor Central — Real-time Agent Communication + Complete Data Sync + Advanced Analytics
Banco de dados: PostgreSQL (oficial)
"""
import os
import json
import logging
import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta
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

SERVER_VERSION = "11.7c"

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
        connection_pool = psycopg2.pool.SimpleConnectionPool(minconn=1, maxconn=20, **DB_CONFIG)
        logger.info("✓ Pool PostgreSQL inicializado")
        return True
    except Exception as e:
        logger.error(f"✗ Erro PostgreSQL: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def get_db():
    if not connection_pool:
        raise HTTPException(503, "Pool de conexões não inicializado")
    try:
        conn = connection_pool.getconn()
        conn.set_client_encoding('UTF8')
        return conn
    except Exception:
        raise HTTPException(503, "DB Ocupado")

def release_db(conn):
    if connection_pool and conn:
        try:
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

        cur.execute('''
            CREATE TABLE IF NOT EXISTS server_auth_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES server_auth_users(id) ON DELETE CASCADE,
                token VARCHAR(255) UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
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

        conn.commit()
        logger.info("✓ Banco de dados PostgreSQL inicializado com todas as tabelas.")
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
            SELECT u.id, u.username, u.display_name, u.role
            FROM server_auth_tokens t
            JOIN server_auth_users u ON t.user_id = u.id
            WHERE t.token = %s AND t.expires_at > LOCALTIMESTAMP
        """, (token,))
        row = cur.fetchone()
        cur.close()
        if row:
            return {"user_id": row[0], "username": row[1], "display_name": row[2], "role": row[3]}
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
    yield
    if connection_pool:
        connection_pool.closeall()

app = FastAPI(title="GBOC Server", version=SERVER_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ===========================
# AUTH ENDPOINTS
# ===========================

@app.get("/login.html", include_in_schema=False)
async def login_page():
    if os.path.exists("login.html"):
        return FileResponse("login.html")
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
async def server_auth_login(req: ServerLoginRequest, response: Response):
    conn = None
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
            cur.close()
            raise HTTPException(401, "Credenciais inválidas")
        user_id, username, display_name, role = row
        token = _generate_token()
        expires = datetime.now() + timedelta(hours=24)
        cur.execute(
            "INSERT INTO server_auth_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)",
            (user_id, token, expires)
        )
        cur.execute("UPDATE server_auth_users SET last_login = LOCALTIMESTAMP WHERE id = %s", (user_id,))
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
            INSERT INTO agents (agent_id, hostname, ip_address, os_info, agent_version, available_tools, last_heartbeat, status)
            VALUES (%s, %s, %s, %s, %s, %s, LOCALTIMESTAMP, 'online')
            ON CONFLICT (agent_id) DO UPDATE SET 
                hostname=EXCLUDED.hostname, ip_address=EXCLUDED.ip_address, 
                os_info=EXCLUDED.os_info, agent_version=EXCLUDED.agent_version,
                available_tools=EXCLUDED.available_tools, last_heartbeat=LOCALTIMESTAMP, status='online'
        ''', (data.agent_id, data.hostname, data.ip_address, data.os_info, data.agent_version, tools))
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
            cur = conn.cursor()
            cur.execute('''
                UPDATE agents SET
                    last_heartbeat=LOCALTIMESTAMP, status='online',
                    cpu_usage=%s, ram_usage=%s, disk_usage=%s
                WHERE agent_id=%s
            ''', (data.get('cpu_usage'), data.get('ram_usage'), data.get('disk_usage'), agent_id))
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
        message = {"type": "update", "timestamp": datetime.now().isoformat()}
        for ws in dashboard_connections.copy():
            try:
                await ws.send_text(json.dumps(message))
            except:
                dashboard_connections.remove(ws)

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
        conn.rollback()
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
        conn.rollback()
        logger.warning(f"Erro ao sincronizar repositórios: {e}")

async def sync_agent_tasks(conn, agent_id: str, tasks: List[Dict]):
    """Sincroniza tarefas do agente"""
    try:
        cur = conn.cursor()
        for task in tasks:
            task_id = task.get('id')
            if task_id is None:
                continue
            cur.execute('''
                UPDATE agent_tasks
                SET name=%s, status=%s, created_at=COALESCE(created_at, %s), updated_at=%s, synced_at=CURRENT_TIMESTAMP
                WHERE agent_id=%s AND task_id=%s
            ''', (
                task.get('name'), task.get('status'), task.get('created_at'), task.get('updated_at'),
                agent_id, task_id
            ))
            if cur.rowcount == 0:
                cur.execute('''
                    INSERT INTO agent_tasks (agent_id, task_id, name, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (
                    agent_id, task_id, task.get('name'), task.get('status'),
                    task.get('created_at'), task.get('updated_at')
                ))
        conn.commit()
        logger.info(f"✅ {len(tasks)} tarefas sincronizadas para agente {agent_id}")
    except Exception as e:
        conn.rollback()
        logger.warning(f"Erro ao sincronizar tarefas: {e}")

async def sync_task_executions(conn, agent_id: str, executions: List[Dict]):
    """Sincroniza execuções de tarefas do agente"""
    try:
        cur = conn.cursor()
        for ex in executions:
            task_id = ex.get('task_id')
            execution_id = ex.get('id')
            if task_id is None or execution_id is None:
                continue
            cur.execute('''
                UPDATE agent_task_executions
                SET status=%s, started_at=%s, completed_at=%s, duration_seconds=%s,
                    files_processed=%s, bytes_processed=%s, error_message=%s, synced_at=CURRENT_TIMESTAMP
                WHERE agent_id=%s AND task_id=%s AND execution_id=%s
            ''', (
                ex.get('status'), ex.get('started_at'), ex.get('completed_at'), ex.get('duration_seconds'),
                ex.get('files_processed', 0), ex.get('bytes_processed', 0), ex.get('error_message'),
                agent_id, task_id, execution_id
            ))
            if cur.rowcount == 0:
                cur.execute('''
                    INSERT INTO agent_task_executions
                        (agent_id, task_id, execution_id, status, started_at, completed_at,
                         duration_seconds, files_processed, bytes_processed, error_message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    agent_id, task_id, execution_id, ex.get('status'), ex.get('started_at'), ex.get('completed_at'),
                    ex.get('duration_seconds'), ex.get('files_processed', 0), ex.get('bytes_processed', 0), ex.get('error_message')
                ))
        conn.commit()
        logger.info(f"✅ {len(executions)} execuções sincronizadas para agente {agent_id}")
    except Exception as e:
        conn.rollback()
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
                event.get('timestamp', datetime.now().isoformat())
            ))
    except Exception as e:
        conn.rollback()
        logger.warning(f"Erro ao sincronizar eventos: {e}")

async def sync_alerts(conn, agent_id: str, alerts: List[Dict]):
    """Sincroniza alertas do agente como eventos do sistema"""
    try:
        cur = conn.cursor()
        for alert in alerts:
            cur.execute('''
                INSERT INTO system_events (event_type, message, agent_hostname, created_at)
                VALUES (%s, %s, %s, %s)
            ''', (
                f"alert_{alert.get('type', 'unknown')}",
                alert.get('message', 'Alert from agent'),
                alert.get('hostname', agent_id),
                alert.get('timestamp', datetime.now().isoformat())
            ))
        conn.commit()
        logger.info(f"✅ {len(alerts)} alertas sincronizados para agente {agent_id}")
    except Exception as e:
        conn.rollback()
        logger.warning(f"Erro ao sincronizar alertas: {e}")

async def handle_full_data_sync(agent_id: str, data: Dict) -> Dict:
    """Processa sincronização completa de dados do agente"""
    # Validar se data é um dicionário
    if not isinstance(data, dict):
        logger.error(f"Dados inválidos recebidos do agente {agent_id}: {data}")
        return {"status": "error", "message": "Invalid data format"}
    
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()

        # Atualizar dados do agente
        manager.update_agent_data(agent_id, data)

        # Salvar dados históricos no banco
        await save_agent_historical_data(conn, agent_id, data)

        # Processar repositórios
        if "repositories" in data:
            await sync_repositories(conn, agent_id, data["repositories"])

        # Processar tarefas
        if "tasks" in data:
            await sync_agent_tasks(conn, agent_id, data["tasks"])

        # Processar execuções de tarefas
        if "task_executions" in data:
            await sync_task_executions(conn, agent_id, data["task_executions"])

        # Processar eventos do sistema
        if "system_events" in data:
            await sync_system_events(conn, agent_id, data["system_events"])

        # Processar alertas
        if "alerts" in data:
            await sync_alerts(conn, agent_id, data["alerts"])

        conn.commit()

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
    return await handle_full_data_sync(data.agent_id, data.dict())

@app.post("/api/v1/agents/manual-sync")
async def manual_sync_request(data: ManualSyncRequest):
    """Processa solicitação de sincronização manual"""
    return await handle_manual_sync(data.agent_id, data.dict())

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
        "timestamp": datetime.now().isoformat()
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
                cpu_usage=%s, ram_usage=%s, disk_usage=%s, jobs_count=%s, jobs_summary=%s
            WHERE agent_id=%s
        ''', (data.cpu_usage, data.ram_usage, data.disk_usage, data.jobs_count, jobs, data.agent_id))
        if cur.rowcount == 0:
            cur.close(); release_db(conn)
            await register(AgentRegister(agent_id=data.agent_id, hostname=data.hostname))
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
        return {"status": "success"}
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
            cur.execute('''
                UPDATE agent_tasks
                SET name=%s, status=%s, created_at=COALESCE(created_at, %s), updated_at=%s, synced_at=CURRENT_TIMESTAMP
                WHERE agent_id=%s AND task_id=%s
            ''', (
                task.get('name'), task.get('status'), task.get('created_at'), task.get('updated_at'),
                data.agent_id, task_id
            ))
            if cur.rowcount == 0:
                cur.execute('''
                    INSERT INTO agent_tasks (agent_id, task_id, name, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (
                    data.agent_id, task_id, task.get('name'), task.get('status'),
                    task.get('created_at'), task.get('updated_at')
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
                    json.dumps({"type": "request_full_sync", "timestamp": datetime.now().isoformat()}),
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
        "timestamp": datetime.now().isoformat()
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
            intercept = y_mean - slope * x_mean

            # Prever próximos 7 dias (assumindo ~5 pontos por dia)
            future_points = 35
            future_vals = [round(max(0, slope * (n + i) + intercept), 1) for i in range(future_points)]
            days_to_80 = None
            if slope > 0:
                target = 80
                current = ram_vals[-1]
                if current < target:
                    points_to_80 = (target - intercept) / slope - n if slope > 0 else 999
                    days_to_80 = max(0, round(points_to_80 / 5, 1))

            predictions['ram'] = {
                'trend': 'up' if slope > 0.01 else ('down' if slope < -0.01 else 'stable'),
                'slope_per_day': round(slope * 5, 2),
                'current': round(ram_vals[-1], 1) if ram_vals else 0,
                'predicted_7d': round(future_vals[-1], 1) if future_vals else 0,
                'days_to_critical': days_to_80,
                'future_values': future_vals[::5]
            }

        return {
            "status": "success",
            "kpi": {
                "uptime_ratio": round(100 * (agents['online'] / agents['total']), 2) if agents['total'] > 0 else 0,
                "backup_success_rate": success_rate_all,
                "exec_success_rate_24h": success_rate_24h
            },
            "trends": {
                "performance": {
                    "duration_trend": dur_trend,
                    "failure_rate_trend": fail_trend
                },
                "resource_usage": predictions
            },
            "system_metrics": system_metrics
        }
    except Exception as e:
        logger.error(f"Erro analytics/comprehensive: {e}")
        raise HTTPException(500, "Erro interno ao gerar análises abrangentes")

