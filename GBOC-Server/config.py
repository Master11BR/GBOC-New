"""
GBOC Server - Configuração centralizada
"""
import os
from typing import List
from datetime import timedelta

# ===========================
# INFORMAÇÕES DO SERVIDOR
# ===========================
try:
    from version_control import __version__ as SERVER_VERSION, get_version_info
except Exception:
    SERVER_VERSION = "13.2.0"
API_VERSION = "v1"
SERVER_NAME = os.getenv("SERVER_NAME", "GBOC Server")
SERVER_ENVIRONMENT = os.getenv("SERVER_ENV", "development")

# ===========================
# BANCO DE DADOS
# ===========================
DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", 5432)),
    "database": os.getenv("POSTGRES_DB", "gboc"),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", "Stoms2025+"),
    "options": "-c timezone=America/Sao_Paulo",
}

DB_POOL_MIN_CONN = int(os.getenv("DB_POOL_MIN", 2))
DB_POOL_MAX_CONN = int(os.getenv("DB_POOL_MAX", 20))
DB_QUERY_TIMEOUT = int(os.getenv("DB_QUERY_TIMEOUT", 30))

# ===========================
# REDIS CACHE
# ===========================
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() == "true"
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# Cache TTL (em segundos)
CACHE_AGENT_DATA_TTL = 300  # 5 minutos
CACHE_METRICS_TTL = 60  # 1 minuto
CACHE_SETTINGS_TTL = 3600  # 1 hora

# ===========================
# SEGURANÇA
# ===========================
SECRET_KEY = os.getenv("SECRET_KEY", "gboc-server-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15
PASSWORD_MIN_LENGTH = 8

# JWT
JWT_EXPIRATION = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
JWT_REFRESH_EXPIRATION = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else ["*"]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = ["*"]
CORS_ALLOW_HEADERS = ["*"]

# ===========================
# RATE LIMITING
# ===========================
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", 100))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW", 60))

# Por endpoint
ENDPOINT_RATE_LIMITS = {
    "/api/v1/auth/login": {"requests": 5, "window": 300},  # 5 requisições por 5 minutos
    "/api/v1/auth/setup": {"requests": 2, "window": 3600},  # 2 requisições por hora
    "/api/v1/agents/register": {"requests": 100, "window": 60},  # 100 por minuto
    "/api/v1/backup/report": {"requests": 50, "window": 60},  # 50 por minuto
}

# ===========================
# LOGGING
# ===========================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "json"  # "json" ou "text"
LOG_FILE = os.getenv("LOG_FILE", "logs/gboc_server.log")
LOG_MAX_SIZE_MB = 10
LOG_BACKUP_COUNT = 5

# ===========================
# RETENÇÃO DE DADOS
# ===========================
RETENTION_POLICIES = {
    "metrics": 90,  # dias
    "logs": 30,  # dias
    "events": 60,  # dias
    "reports": 365,  # dias
}

# ===========================
# SINCRONIZAÇÃO
# ===========================
HEARTBEAT_INTERVAL_SECONDS = 30
AGENT_OFFLINE_THRESHOLD_MINUTES = 60
AUTO_SYNC_ENABLED = True
FULL_SYNC_INTERVAL_SECONDS = 300

# ===========================
# WEBHOOK (TRAVADO - FUTURO)
# ===========================
WEBHOOKS_ENABLED = False  # Mantido desabilitado por enquanto
WEBHOOK_TIMEOUT = 5  # segundos
WEBHOOK_MAX_RETRIES = 3
WEBHOOK_RETRY_DELAY = 60  # segundos

# ===========================
# DEAD LETTER QUEUE
# ===========================
DEAD_LETTER_QUEUE_ENABLED = True
DLQ_FILE = os.getenv("DLQ_FILE", "data/dead_letter_queue.jsonl")
DLQ_MAX_SIZE_MB = 100

# ===========================
# PAGINAÇÃO
# ===========================
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# ===========================
# MONITORAMENTO
# ===========================
METRICS_ENABLED = True
PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", 8001))
HEALTH_CHECK_INTERVAL_SECONDS = 60

# ===========================
# DIRETÓRIOS
# ===========================
import os as os_module
DATA_DIR = os.path.join(os_module.path.dirname(__file__), "data")
LOG_DIR = os.path.join(os_module.path.dirname(__file__), "logs")

os_module.makedirs(DATA_DIR, exist_ok=True)
os_module.makedirs(LOG_DIR, exist_ok=True)
