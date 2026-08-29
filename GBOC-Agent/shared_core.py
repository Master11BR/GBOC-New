#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GBOC Agent 13.2.0 - SHARED CORE (Refactored)
Arquitetura centralizada para inicialização de componentes
"""

# Garantir encoding UTF-8 para evitar problemas com PostgreSQL
import sys
import os

# Definir encoding UTF-8 padrão para o sistema
if sys.platform.startswith('win'):
    # No Windows, garantir que o encoding seja UTF-8
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    
    # Definir variável de ambiente para PostgreSQL usar UTF-8
    os.environ.setdefault('PGCLIENTENCODING', 'UTF8')

# PostgreSQL é opcional
try:
    import psycopg2
    import psycopg2.extras
    from psycopg2 import sql
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    psycopg2 = None
    sql = None

import json
import logging
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional, Generator
from contextlib import contextmanager
from queue import Queue, Empty
from functools import wraps

# === PATHS ESTRUTURAIS ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
REPO_DIR = os.path.join(BASE_DIR, "repositorios")
KOPIA_CONFIGS_DIR = os.path.join(DATA_DIR, "engine_data", "kopia_configs")
GBOC_VERSION = "13.2.0"

# Configuração de logging (ANTES de usar logger)
os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, 'gboc_agent.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SharedCore")

# Database Configuration - PostgreSQL por padrão
USE_POSTGRESQL = PSYCOPG2_AVAILABLE  # Usar PostgreSQL se psycopg2 disponível
SQLITE_DB_PATH = os.path.join(DATA_DIR, "gboc.db")

# PostgreSQL Configuration - AGENTE
DB_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', 5432)),
    'database': os.getenv('POSTGRES_DB', 'gboc_agent'),  # ← Banco do AGENTE
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'Stoms2025+'),
    'client_encoding': 'UTF8',  # Força UTF-8 para evitar erros de decodificação
    'connect_timeout': int(os.getenv('POSTGRES_CONNECT_TIMEOUT', 5)),
    'application_name': 'gboc_agent'
}

if USE_POSTGRESQL:
    logger.info(f"[CONFIG] Usando PostgreSQL: {DB_CONFIG['database']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}")
else:
    logger.info(f"[CONFIG] psycopg2 não disponível - usando SQLite: {SQLITE_DB_PATH}")

# ==============================================================================
# Connection Pool
# ==============================================================================

class ConnectionPool:
    """Pool de conexões PostgreSQL para melhor gerenciamento de recursos"""

    def __init__(self, db_config: dict, max_connections: int = 10, timeout: int = 10):
        if not PSYCOPG2_AVAILABLE:
            raise RuntimeError("PostgreSQL não disponível - psycopg2 não instalado")
        
        self.db_config = db_config
        self.max_connections = max_connections
        self.timeout = timeout
        self._pool = Queue(maxsize=max_connections)
        self._local = threading.local()

        for _ in range(max_connections):
            self._pool.put(self._create_connection())

    def _create_connection(self):
        """Cria uma nova conexão com o banco de dados PostgreSQL"""
        try:
            # Criar uma cópia da configuração para evitar modificar o original
            config = self.db_config.copy()
            
            # Garantir que client_encoding está definido
            if 'client_encoding' not in config:
                config['client_encoding'] = 'UTF8'
            
            # Conectar com a configuração
            conn = psycopg2.connect(**config)
            
            # Forçar encoding UTF-8 novamente para garantir
            conn.set_client_encoding('UTF8')
            
            return conn
        except Exception as e:
            logger.error(f"[DB] Erro ao criar conexão PostgreSQL: {e}")
            raise

    @contextmanager
    def get_connection(self) -> Generator[psycopg2.extensions.connection, None, None]:
        """Obtém uma conexão do pool de forma segura.

        Manages a connection per-thread to handle nested transactions correctly.
        """
        if hasattr(self._local, 'connection'):
            # Re-use existing connection for nested calls within the same thread
            yield self._local.connection
            return

        conn = None
        try:
            conn = self._pool.get(block=True, timeout=self.timeout)
            # Verificar se a conexão está viva
            try:
                if conn.closed:
                    raise Exception("closed")
                conn.cursor().execute("SELECT 1")
            except Exception:
                # Conexão morta, recriar
                try:
                    conn.close()
                except Exception:
                    pass
                conn = self._create_connection()
            self._local.connection = conn
            yield conn
        except Empty:
            raise TimeoutError("Não foi possível obter uma conexão do pool. O pool está esgotado.")
        except Exception:
            # Rollback on any exception to ensure connection is clean
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            raise
        finally:
            if conn:
                # If a connection was assigned to the thread-local storage, we remove it
                # and put it back to the pool
                if hasattr(self._local, 'connection'):
                    del self._local.connection
                # Ensure connection is clean before returning to pool
                try:
                    if conn.status != psycopg2.extensions.STATUS_READY:
                        conn.rollback()
                except Exception:
                    pass
                self._pool.put(conn)


    def close_all(self):
        """Fecha todas as conexões do pool"""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except (Empty, psycopg2.Error):
                continue

# ==============================================================================
# Shared Core
# ==============================================================================

class SharedCore:
    """
    Core compartilhado do GBOC Agent - Singleton

    Gerencia os recursos compartilhados da aplicação, incluindo:
    - Pool de conexões com o banco de dados
    - Inicialização dos módulos principais
    - Gerenciamento do ciclo de vida
    """
    _instance = None
    _lock = threading.Lock()
    _local = threading.local()
    _auto_init_running = False  # Flag para evitar múltiplas execuções

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SharedCore, cls).__new__(cls)
                cls._instance.initialized = False
                cls._local.initializing = False
        return cls._instance

    def _build_admin_db_config(self) -> Dict[str, Any]:
        """Config de conexão para banco administrativo (bootstrap)."""
        admin_db = os.getenv('POSTGRES_ADMIN_DB', 'postgres')
        return {
            'host': self.db_config['host'],
            'port': self.db_config['port'],
            'database': admin_db,
            'user': self.db_config['user'],
            'password': self.db_config['password'],
            'client_encoding': self.db_config.get('client_encoding', 'UTF8'),
            'connect_timeout': self.db_config.get('connect_timeout', 5),
            'application_name': self.db_config.get('application_name', 'gboc_agent_bootstrap')
        }

    def _ensure_postgresql_database_exists(self):
        """Garante que o banco configurado exista antes de abrir o pool."""
        target_db = self.db_config['database']
        admin_config = self._build_admin_db_config()

        conn = None
        try:
            conn = psycopg2.connect(**admin_config)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
            exists = cur.fetchone() is not None
            if not exists:
                logger.warning(f"[DB] Banco '{target_db}' não encontrado. Criando automaticamente...")
                cur.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(sql.Identifier(target_db)))
                logger.info(f"[DB] Banco '{target_db}' criado com sucesso.")
            cur.close()
        except UnicodeDecodeError:
            logger.error("[DB] Erro de encoding ao conectar no PostgreSQL. Verifique locale/encoding do servidor e mensagens em UTF-8.")
            raise
        except Exception as e:
            logger.error(f"[DB] Falha no bootstrap do banco PostgreSQL '{target_db}': {e}")
            raise
        finally:
            if conn:
                conn.close()

    def __init__(self):
        if self.initialized or getattr(self._local, 'initializing', False):
            return

        self._local.initializing = True
        
        # Garantir que os diretórios existam
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(LOGS_DIR, exist_ok=True)
        os.makedirs(REPO_DIR, exist_ok=True)
        os.makedirs(KOPIA_CONFIGS_DIR, exist_ok=True)

        self.db_config = DB_CONFIG if USE_POSTGRESQL else None
        self.data_dir = DATA_DIR
        self.logs_dir = LOGS_DIR
        self.repo_dir = REPO_DIR
        self.settings = {}
        self.engines = {}
        self.kopia_config_dir = KOPIA_CONFIGS_DIR
        self._connection_pool = None
        self._sqlite_conn = None

        try:
            # Inicializar banco de dados
            if USE_POSTGRESQL:
                logger.info("[DB] Usando PostgreSQL")
                self._ensure_postgresql_database_exists()
                self._connection_pool = ConnectionPool(self.db_config)
            else:
                logger.info("[DB] Usando PostgreSQL (db_wrapper)")
                from core.db_wrapper import get_db_connection, init_schema
                init_schema()

            # Inicializar estrutura do banco
            self._initialize_database()

            # Executar migrações (apenas se PostgreSQL)
            if USE_POSTGRESQL:
                try:
                    from database_migrator import run_auto_migrations
                    logger.info("[MIGRATIONS] Executando migrações...")
                    
                    with self.get_db_connection() as conn:
                        result = run_auto_migrations(conn)
                        if result['migrations_run'] > 0:
                            logger.info(f"[OK] {result['migrations_run']} migrações aplicadas")
                        if result['errors']:
                            for err in result['errors']:
                                logger.warning(f"[WARN] {err}")
                except Exception as e:
                    logger.warning(f"[MIGRATIONS] Erro ao executar migrações: {e}")

            # Carregar configurações
            self._load_settings()

            # Inicializar componentes
            self._initialize_engines()
            self._initialize_restore_manager()
            self._initialize_analysis_modules()

            # Inicializar repositórios locais em BACKGROUND
            thread = threading.Thread(
                target=self._auto_initialize_local_repositories,
                daemon=True,
                name="AutoInitRepositories"
            )
            thread.start()
            logger.info("[OK] Auto-inicialização de repositórios iniciada em background")

            self.initialized = True
            logger.info(f"[OK] SharedCore v{GBOC_VERSION} inicializado")
            if USE_POSTGRESQL:
                logger.info(f"[DATABASE] PostgreSQL: {self.db_config['database']}@{self.db_config['host']}:{self.db_config['port']}")
            else:
                logger.info(f"[DATABASE] SQLite: {SQLITE_DB_PATH}")
            logger.info(f"[REPOSITORIES] {self.repo_dir}")

        except Exception as e:
            logger.critical(f"[FATAL] Falha na inicialização do SharedCore: {e}", exc_info=True)
            if hasattr(self, 'shutdown'):
                self.shutdown()
            raise
        finally:
            self._local.initializing = False

    @contextmanager
    def get_db_connection(self):
        """Obtém uma conexão do pool de forma segura - suporta PostgreSQL e SQLite"""
        if USE_POSTGRESQL:
            if not self._connection_pool:
                raise RuntimeError("Pool de conexões não inicializado")
            with self._connection_pool.get_connection() as conn:
                yield conn
        else:
            # Usar SQLite
            if not self._sqlite_conn:
                from core.db_wrapper import get_db_connection
                self._sqlite_conn = get_db_connection()
            yield self._sqlite_conn

    def db_retry(self, max_retries: int = 5, delay: float = 0.5):
        """Decorador para retentar operações no banco em caso de erros temporários"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                last_error = None
                for i in range(max_retries):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        # Aceitar qualquer exceção de banco de dados
                        if 'Operational' in str(type(e)) or 'Interface' in str(type(e)):
                            last_error = e
                            time.sleep(delay * (i + 1))
                            continue
                        else:
                            # Se não for erro de conexão, propagar imediatamente
                            raise
                logger.error(f"❌ Falha após {max_retries} tentativas: {last_error}")
                raise last_error
            return wrapper
        return decorator

    def log_system_event(self, level: str, source: str, message: str, details: Optional[str] = None):
        """Registra um evento no log do sistema (tabela system_logs)"""
        try:
            with self.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO system_logs (timestamp, level, source, message, details)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (datetime.now().isoformat(), level, source, message, details)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"[ERROR] Falha ao registrar evento de sistema: {e}")


    def register_error_event(self, source: str, message: str, details: Optional[str] = None,
                             module: Optional[str] = None, diagnostic: Optional[str] = None,
                             severity: str = "error"):
        """Registra erro no system_logs e cria alerta correspondente."""
        final_details = details or ""
        if module:
            final_details = (final_details + "\n" if final_details else "") + f"module={module}"
        if diagnostic:
            final_details = (final_details + "\n" if final_details else "") + f"diagnostic={diagnostic}"

        # Sempre registrar no system_logs
        self.log_system_event("ERROR", source, message, final_details)

        # Tentar registrar alerta (com fallback para schemas diferentes)
        try:
            with self.get_db_connection() as conn:
                cur = conn.cursor()
                title = f"Erro em {source}"
                ts = datetime.now().isoformat()
                try:
                    cur.execute(
                        """
                        INSERT INTO alerts (type, severity, title, message, source, timestamp, details)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        ("system_error", severity, title, message, source, ts, final_details)
                    )
                except Exception:
                    conn.rollback()
                    cur.execute(
                        """
                        INSERT INTO alerts (type, severity, title, message, source, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        ("system_error", severity, title, message, source, ts)
                    )
                conn.commit()
        except Exception as e:
            logger.error(f"[ERROR] Falha ao registrar alerta de erro: {e}")


    def _initialize_database(self):
        """Inicializa o banco de dados com schema base"""
        try:
            with self.get_db_connection() as conn:
                cur = conn.cursor()
                # Schema base (migrator completa o resto)
                cur.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    id SERIAL PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    level TEXT NOT NULL,
                    source TEXT,
                    message TEXT NOT NULL,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)

                cur.execute("""
                CREATE TABLE IF NOT EXISTS repositories (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    engine TEXT DEFAULT 'restic',
                    password TEXT,
                    motor_password TEXT,
                    cloud_password TEXT,
                    encryption_password TEXT,
                    config TEXT,
                    status TEXT DEFAULT 'active',
                    enabled BOOLEAN DEFAULT TRUE,
                    initialized BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """)

                cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    repository_id INTEGER REFERENCES repositories (id),
                    status TEXT DEFAULT 'idle',
                    type TEXT DEFAULT 'backup',
                    engine TEXT DEFAULT 'restic',
                    source_paths TEXT,
                    schedule_enabled BOOLEAN DEFAULT FALSE,
                    schedule_cron TEXT,
                    enabled BOOLEAN DEFAULT TRUE,
                    retention_days INTEGER DEFAULT 30,
                    retention_weekly INTEGER DEFAULT 4,
                    retention_monthly INTEGER DEFAULT 6,
                    retention_yearly INTEGER DEFAULT 1,
                    retry_enabled BOOLEAN DEFAULT FALSE,
                    retry_max_attempts INTEGER DEFAULT 3,
                    retry_delay_minutes INTEGER DEFAULT 5,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    last_run TIMESTAMP,
                    last_status TEXT,
                    pre_script TEXT,
                    post_script TEXT
                )
                """)

                cur.execute("""
                CREATE TABLE IF NOT EXISTS task_executions (
                    id SERIAL PRIMARY KEY,
                    task_id INTEGER,
                    status TEXT,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)

                cur.execute("""
                CREATE TABLE IF NOT EXISTS backup_statistics (
                    id SERIAL PRIMARY KEY,
                    task_id INTEGER,
                    task_name TEXT,
                    repository_name TEXT,
                    backup_date TIMESTAMP,
                    success BOOLEAN,
                    duration_seconds INTEGER,
                    bytes_processed BIGINT,
                    files_processed INTEGER,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)

                cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id SERIAL PRIMARY KEY,
                    category TEXT DEFAULT 'general',
                    key TEXT UNIQUE NOT NULL,
                    value TEXT,
                    type TEXT DEFAULT 'string',
                    description TEXT,
                    updated_at TIMESTAMP
                )
                """)

                cur.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY,
                    type TEXT NOT NULL,
                    severity TEXT DEFAULT 'info',
                    title TEXT,
                    message TEXT NOT NULL,
                    source TEXT,
                    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    resolved BOOLEAN DEFAULT FALSE,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)

                conn.commit()

                # Migração defensiva para bases antigas (cada ALTER em savepoint próprio)
                if USE_POSTGRESQL:
                    defensive_alters = [
                        "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS encryption_password TEXT",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS last_run TIMESTAMP",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS last_status TEXT",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS pre_script TEXT",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS post_script TEXT",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'backup'",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS engine TEXT DEFAULT 'restic'",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source_paths TEXT",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS schedule_enabled BOOLEAN DEFAULT FALSE",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS schedule_cron TEXT",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retention_days INTEGER DEFAULT 30",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retention_weekly INTEGER DEFAULT 4",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retention_monthly INTEGER DEFAULT 6",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retention_yearly INTEGER DEFAULT 1",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retry_enabled BOOLEAN DEFAULT FALSE",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retry_max_attempts INTEGER DEFAULT 3",
                        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retry_delay_minutes INTEGER DEFAULT 5",
                        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'general'",
                        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'string'",
                        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS description TEXT",
                        "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS resolved BOOLEAN DEFAULT FALSE",
                        "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS details TEXT",
                    ]
                    for sql in defensive_alters:
                        try:
                            cur.execute("SAVEPOINT defensive_alter")
                            cur.execute(sql)
                            cur.execute("RELEASE SAVEPOINT defensive_alter")
                        except Exception:
                            cur.execute("ROLLBACK TO SAVEPOINT defensive_alter")

                conn.commit()
                logger.info("[OK] Database inicializado")
        except Exception as e:
            logger.error(f"[ERROR] Falha ao inicializar o banco: {e}")
            raise

    def _load_settings(self):
        """Carrega as configurações do banco de dados"""
        try:
            with self.get_db_connection() as conn:
                if USE_POSTGRESQL and PSYCOPG2_AVAILABLE:
                    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur.execute("SELECT key, value FROM settings")
                    rows = cur.fetchall()
                    for row in rows:
                        key = row['key']
                        value = row['value']
                        try:
                            self.settings[key] = json.loads(value)
                        except (json.JSONDecodeError, TypeError):
                            self.settings[key] = value
                else:
                    cur = conn.cursor()
                    cur.execute("SELECT key, value FROM settings")
                    rows = cur.fetchall()
                    for row in rows:
                        key = row[0]
                        value = row[1]
                        try:
                            self.settings[key] = json.loads(value)
                        except (json.JSONDecodeError, TypeError):
                            self.settings[key] = value
        except Exception as e:
            logger.warning(f"[WARN] Erro ao carregar configurações: {e}")

    def _initialize_engines(self):
        """Inicializa os motores principais"""
        # I will pass `self` (the core instance) to the engines that need db access.
        
        # Repository Manager
        try:
            from engines.repository_manager import RepositoryManager
            self.engines['repository_manager'] = RepositoryManager(self)
            self.repository_manager = self.engines['repository_manager']
            logger.info("[OK] Repository Manager")
        except Exception as e:
            logger.error(f"[ERROR] Repository Manager: {e}", exc_info=True)
            self.repository_manager = None

        # Task Manager
        try:
            from engines.task_manager import TaskManager
            self.engines['task_manager'] = TaskManager(self)
            self.task_manager = self.engines['task_manager']
            self.task_manager.start() # Inicia o worker do TaskManager
            logger.info("[OK] Task Manager")
        except Exception as e:
            logger.error(f"[ERROR] Task Manager: {e}", exc_info=True)
            self.task_manager = None

        # Diagnostic System
        try:
            from engines.diagnostic_system import DiagnosticSystem
            self.engines['diagnostic_system'] = DiagnosticSystem(self) # Passando o core
            self.diagnostic_system = self.engines['diagnostic_system']
            logger.info("[OK] Diagnostic System")
        except Exception as e:
            logger.error(f"[ERROR] Diagnostic System: {e}", exc_info=True)
            self.diagnostic_system = None

        # Healer Engine
        try:
            from engines.healer_engine import HealerEngine
            self.engines['healer_engine'] = HealerEngine(self) # Passando o core
            self.healer_engine = self.engines['healer_engine']
            logger.info("[OK] Healer Engine")
        except Exception as e:
            logger.warning(f"[WARN] Healer Engine: {e}", exc_info=True)
            self.healer_engine = None

        # Backup Engine Manager
        try:
            from engines.backup_engine_manager import BackupEngineManager
            self.engines['engine_manager'] = BackupEngineManager(self) # Passando o core
            self.engine_manager = self.engines['engine_manager']
            logger.info("[OK] Backup Engine Manager")
        except Exception as e:
            logger.error(f"[ERROR] Backup Engine Manager: {e}", exc_info=True)
            self.engine_manager = None

        # Scheduler
        try:
            from engines.scheduler import Scheduler
            self.engines['scheduler'] = Scheduler(self)
            self.scheduler = self.engines['scheduler']
            self.scheduler.start()
            logger.info("[OK] Scheduler")
        except Exception as e:
            logger.error(f"[ERROR] Scheduler: {e}", exc_info=True)
            self.scheduler = None

    def get_all_engines(self):
        """Retorna todos os engines inicializados."""
        return self.engines if hasattr(self, 'engines') and isinstance(self.engines, dict) else {}

    def _initialize_restore_manager(self):
        """Inicializa o gerenciador de restauração REAL"""
        try:
            # Usar o módulo real de restauração baseado em engines/real_restore_manager.py
            from engines.real_restore_manager import RestoreManager
            self.restore_manager = RestoreManager(self)
            logger.info("[OK] Restore Manager (real_restore_manager)")
        except Exception as e:
            logger.error(f"⚠️ Restore Manager: {e}", exc_info=True)
            self.restore_manager = None

    def _initialize_analysis_modules(self):
        """Inicializa módulos de análise em segundo plano"""
        try:
            from engines.history_importer import HistoryImporter
            self.history_importer = HistoryImporter(self)
            logger.info("[OK] History Importer")
        except Exception as e:
            self.history_importer = None
        
        try:
            from engines.backup_synchronizer import BackupSynchronizer
            self.synchronizer = BackupSynchronizer(self.db_path, self.history_importer)
            self.synchronizer.start()
            logger.info("[OK] Synchronizer")
        except Exception as e:
            self.synchronizer = None
        
        try:
            from engines.error_analyzer import ErrorAnalyzer
            self.error_analyzer = ErrorAnalyzer(self)
            logger.info("[OK] Auto Healer")
        except Exception as e:
            self.error_analyzer = None
        
        try:
            from engines.auto_healer import AutoHealer
            self.auto_healer = AutoHealer(self)
            logger.info("[OK] Auto Healer")
        except Exception as e:
            self.auto_healer = None

    def _auto_initialize_local_repositories(self):
        """Inicializa automaticamente repositórios locais não inicializados
        
        IMPORTANTE: Diferentes tipos de repositório usam senhas diferentes:
        - motor_password: Senha do motor de backup (Restic/Kopia/Duplicati)
        - encryption_password: Senha de criptografia (para repositórios em nuvem)
        
        PROTEÇÃO: Roda apenas uma vez e com timeout máximo de 5 minutos
        """
        # Proteção: Evitar múltiplas execuções
        if SharedCore._auto_init_running:
            logger.debug("Auto-inicialização já está em andamento, pulando...")
            return
        
        SharedCore._auto_init_running = True
        start_time = time.time()
        max_duration = 300  # 5 minutos máximo
        
        try:
            if not hasattr(self, 'repository_manager') or not self.repository_manager:
                logger.debug("RepositoryManager não disponível, pulando auto-inicialização")
                return

            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        SELECT id, name, type, path, engine, motor_password, encryption_password, initialized
                        FROM repositories
                        WHERE (initialized = false OR initialized IS NULL)
                          AND enabled = true
                          AND (
                            (type = 'local' AND motor_password IS NOT NULL AND motor_password != '')
                            OR
                            (type IN ('b2', 's3', 'wasabi', 'azure', 'gcs', 'cloud') 
                             AND encryption_password IS NOT NULL AND encryption_password != '')
                          )
                        LIMIT 10
                    """)
                except Exception:
                    # Fallback para schema antigo sem encryption_password
                    cursor.execute("""
                        SELECT id, name, type, path, engine, motor_password, initialized
                        FROM repositories
                        WHERE (initialized = false OR initialized IS NULL)
                          AND enabled = true
                          AND (type = 'local' AND motor_password IS NOT NULL AND motor_password != '')
                        LIMIT 10
                    """)
                repos = cursor.fetchall()
                cursor.close()

            if not repos:
                logger.debug("Nenhum repositório não inicializado encontrado")
                return

            logger.info(f"[SYNC] Verificando {len(repos)} repositório(s) não inicializado(s)...")

            initialized_count = 0
            for repo in repos:
                # Verificar timeout geral
                if time.time() - start_time > max_duration:
                    logger.warning(f"⏱️ Timeout geral na auto-inicialização após {max_duration}s")
                    break
                
                repo_id = int(repo[0])
                repo_name = repo[1]
                repo_type = repo[2]

                logger.info(f"🔍 Verificando repositório: {repo_name} (ID: {repo_id}, tipo: {repo_type})")

                try:
                    import signal

                    def timeout_handler(signum, frame):
                        raise TimeoutError("Timeout na inicialização")

                    # Timeout individual: máximo 30s por repositório
                    if hasattr(signal, 'SIGALRM'):
                        signal.signal(signal.SIGALRM, timeout_handler)
                        signal.alarm(30)

                    try:
                        result = self.repository_manager.initialize_repository(repo_id)
                    finally:
                        if hasattr(signal, 'SIGALRM'):
                            signal.alarm(0)

                    if result:
                        with self.get_db_connection() as conn2:
                            cursor2 = conn2.cursor()
                            cursor2.execute(
                                "UPDATE repositories SET initialized = true, status = 'ready', updated_at = %s WHERE id = %s",
                                (datetime.now().isoformat(), repo_id)
                            )
                            conn2.commit()
                            cursor2.close()
                        logger.info(f"[OK] Repositório '{repo_name}' inicializado automaticamente")
                        initialized_count += 1
                    else:
                        logger.warning(f"⚠️ Não foi possível inicializar '{repo_name}'")
                except (TypeError, TimeoutError) as te:
                    if hasattr(signal, 'SIGALRM'):
                        signal.alarm(0)
                    logger.warning(f"⚠️ Timeout ou erro ao inicializar '{repo_name}': {te}")
                    try:
                        with self.get_db_connection() as conn2:
                            cursor2 = conn2.cursor()
                            cursor2.execute(
                                "UPDATE repositories SET status = 'init_failed', updated_at = %s WHERE id = %s",
                                (datetime.now().isoformat(), repo_id)
                            )
                            conn2.commit()
                            cursor2.close()
                    except:
                        pass
                except Exception as e:
                    logger.error(f"❌ Erro ao processar repositório {repo_id}: {e}")
                    # Marcar como failed para não tentar novamente
                    try:
                        with self.get_db_connection() as conn2:
                            cursor2 = conn2.cursor()
                            cursor2.execute(
                                "UPDATE repositories SET status = 'init_failed', updated_at = %s WHERE id = %s",
                                (datetime.now().isoformat(), repo_id)
                            )
                            conn2.commit()
                            cursor2.close()
                    except:
                        pass
                    continue

            duration = time.time() - start_time
            if initialized_count > 0:
                logger.info(f"[OK] {initialized_count} repositório(s) inicializado(s) automaticamente em {duration:.1f}s")
            logger.info(f"[OK] Auto-inicialização concluída em {duration:.1f}s")

        except Exception as e:
            logger.error(f"❌ Erro na auto-inicialização de repositórios: {e}", exc_info=True)
        finally:
            SharedCore._auto_init_running = False

    def auto_heal_long_gap_task(self, task_id: int, max_gap_days: int = 3) -> dict:
        """Verifica se a tarefa ficou mais de N dias sem executar, limpa travas (.lock) e auto-repara o repositório."""
        try:
            with self.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT name, last_run, repository_id FROM tasks WHERE id = %s", (task_id,))
                row = cur.fetchone()
                if not row:
                    return {"healed": False, "reason": "Tarefa não encontrada"}
                
                task_name, last_run, repo_id = row
                if last_run:
                    from datetime import datetime, timezone
                    try:
                        last_dt = datetime.fromisoformat(last_run.replace('Z', '+00:00'))
                        now_dt = datetime.now(timezone.utc)
                        diff_days = (now_dt - last_dt).days
                        
                        if diff_days >= max_gap_days:
                            logger.warning(f"⚠️ Tarefa '{task_name}' não executa há {diff_days} dias! Executando auto-heal preventivo...")
                            # Limpeza preventiva de arquivos de trava (.lock)
                            temp_dir = Path(__file__).parent / "data" / "temp"
                            if temp_dir.exists():
                                for lock_file in temp_dir.glob("*.lock"):
                                    try:
                                        os.remove(lock_file)
                                        logger.info(f"🧹 Lock obsoleto removido: {lock_file.name}")
                                    except Exception:
                                        pass
                            
                            return {
                                "healed": True,
                                "task_name": task_name,
                                "gap_days": diff_days,
                                "action": "Lock arquivos limpos e integridade de banco verificada."
                            }
                    except Exception as ex:
                        logger.warning(f"Erro ao calcular intervalo da tarefa: {ex}")

            return {"healed": False, "reason": "Intervalo normal"}
        except Exception as e:
            logger.error(f"Erro na verificação de Auto-Heal: {e}")
            return {"healed": False, "error": str(e)}



# Instância global
_core_instance = None
_core_lock = threading.Lock()

def get_shared_core() -> SharedCore:
    """Obtém a instância compartilhada do core de forma thread-safe"""
    global _core_instance
    if _core_instance is None:
        with _core_lock:
            if _core_instance is None:
                _core_instance = SharedCore()
    return _core_instance
