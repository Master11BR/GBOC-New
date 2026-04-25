#!/usr/bin/env python3
"""
🚀 GBOC Agent 11.7c - Servidor Principal
Servidor FastAPI com arquitetura modular limpa
"""

import sys
import os
import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import platform
from datetime import datetime
import time
import asyncio

# Diretório base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Carregar .env se existir
_env_file = os.path.join(BASE_DIR, ".env")
if os.path.exists(_env_file):
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        # Fallback manual se python-dotenv não estiver instalado
        with open(_env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    os.environ.setdefault(key.strip(), value.strip())

# Garantir pastas existem
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Configuração de logging com horário local (fuso do sistema)
from logging.handlers import RotatingFileHandler
import io

class LocalTimeFormatter(logging.Formatter):
    converter = time.localtime

_log_formatter = LocalTimeFormatter(
    fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# RotatingFileHandler: máx 10 MB por arquivo, mantém 5 backups
_file_handler = RotatingFileHandler(
    os.path.join(LOGS_DIR, 'gboc_agent.log'),
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)
_file_handler.setFormatter(_log_formatter)

# StreamHandler com UTF-8 forçado (evita UnicodeEncodeError no Windows cp1252)
_safe_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
_stream_handler = logging.StreamHandler(_safe_stdout)
_stream_handler.setFormatter(_log_formatter)

# Handler para stderr — captura erros de subprocessos e exceções não tratadas
_stderr_handler = RotatingFileHandler(
    os.path.join(LOGS_DIR, 'gboc_agent_errors.log'),
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3,
    encoding='utf-8'
)
_stderr_handler.setLevel(logging.ERROR)
_stderr_handler.setFormatter(_log_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[_file_handler, _stream_handler, _stderr_handler]
)

logger = logging.getLogger(__name__)

# Capturar exceções não tratadas no log (independente de como o processo foi iniciado)
def _uncaught_exception_handler(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    logger.critical("Exceção não tratada", exc_info=(exc_type, exc_value, exc_tb))

sys.excepthook = _uncaught_exception_handler

# Redirecionar stderr para log (captura erros de subprocessos/uvicorn)
class _StderrToLogger:
    """Redireciona escrita em stderr para o logger + stderr original."""
    _in_write = False  # guard contra recursão

    def __init__(self, original_stderr):
        self._original = original_stderr

    def write(self, msg):
        if not msg or not msg.strip():
            return
        # Evitar recursão: se o logger falhar ao escrever, o erro volta aqui
        if _StderrToLogger._in_write:
            if self._original:
                try:
                    self._original.write(msg)
                except Exception:
                    pass
            return
        _StderrToLogger._in_write = True
        try:
            text = msg.rstrip()
            upper = text.upper()
            if upper.startswith("INFO:"):
                logger.info(f"[STDERR] {text}")
            elif upper.startswith("WARNING:"):
                logger.warning(f"[STDERR] {text}")
            elif upper.startswith("ERROR:") or "TRACEBACK" in upper or "EXCEPTION" in upper:
                logger.error(f"[STDERR] {text}")
            else:
                logger.info(f"[STDERR] {text}")
        except Exception:
            pass
        finally:
            _StderrToLogger._in_write = False

    def flush(self):
        if self._original:
            try:
                self._original.flush()
            except Exception:
                pass

sys.stderr = _StderrToLogger(sys.stderr)

# Importar handler de logs para banco (opcional)
try:
    from database_log_handler import setup_database_logging
    setup_database_logging()
except Exception as e:
    logger.warning(f"Database log handler não disponível: {e}")

# Importar cliente do servidor central (opcional)
try:
    from server_client import central_client
except ImportError as e:
    logger.warning(f"Server client não disponível (psycopg2 ausente): {e}")
    central_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerenciamento do ciclo de vida da aplicação"""
    logger.info("=" * 50)
    logger.info("[STARTUP] GBOC Agent 11.7c - Servidor Iniciado")
    logger.info(f"[DATA] {DATA_DIR}")
    logger.info(f"[LOGS] {LOGS_DIR}")
    
    # Validar arquivos estáticos
    static_files = ["index.html", "tasks.html", "repositories.html", "overview.html", "logs.html", "restore.html", "statistics.html", "settings.html", "diagnostic.html", "login.html", "ransomware.html", "compliance.html", "alerts.html", "replication.html", "users.html", "config-manager.html", "integrity.html", "audit.html", "notification-channels.html", "duplicati-native.html", "schema-check.html", "auth-diagnostic.html"]
    for f in static_files:
        path = os.path.join(BASE_DIR, "static", f)
        status = "[OK]" if os.path.exists(path) else "[WARN]"
        logger.info(f"{status} {f}")

    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        if core:
            engines = core.get_all_engines()
            logger.info(f"[ENGINES] {list(engines.keys())}")
            
            if hasattr(core, 'restore_manager') and core.restore_manager:
                logger.info("[OK] RestoreManager disponivel")
            
            if hasattr(core, 'repository_manager') and core.repository_manager:
                logger.info("[OK] RepositoryManager disponivel")
            
    except Exception as e:
        logger.error(f"[ERROR] Erro na inicializacao do Core: {e}")

    # Inicializar cliente do servidor central
    try:
        from server_config import config_manager
        logger.info("[SERVER] Inicializando cliente do servidor central...")

        if config_manager.is_enabled():
            logger.info(f"[SERVER] ✅ Cliente habilitado para: {config_manager.get_server_url()}")
            logger.info(f"[SERVER] Agent ID: {central_client.agent_id}")
            logger.info(f"[SERVER] Heartbeat: {config_manager.get_heartbeat_interval()} min")
            logger.info(f"[SERVER] Sincronização: {config_manager.get_sync_interval()} min")

            # Iniciar threads de comunicação agora que o core está pronto
            central_client.start_threads()
        else:
            logger.info("[SERVER] ⚠️ Cliente do servidor central desabilitado")

    except Exception as e:
        logger.error(f"[SERVER] Erro na inicialização do cliente: {e}")

    # Iniciar Ransomware Guardian (watchdog automatico)
    try:
        from engines.ransomware_guardian import get_guardian
        guardian = get_guardian(check_interval_minutes=5)
        guardian.start()
        logger.info("[GUARDIAN] ✅ Ransomware Guardian ativo (verificação a cada 5 min)")
    except Exception as e:
        logger.warning(f"[GUARDIAN] ⚠️ Falha ao iniciar Guardian: {e}")

    # Iniciar Ransomware Shield (proteção real-time — não bloqueia startup)
    try:
        from engines.ransomware_shield import get_shield
        shield = get_shield()
        # Só inicia se explicitamente habilitado na config
        if shield.config.get('enabled', False) and shield.config['monitored_paths']:
            shield.start()
            logger.info("[SHIELD] ✅ Ransomware Shield ativo (real-time)")
        else:
            logger.info("[SHIELD] Shield disponível mas não iniciado (habilite via API /api/ransomware/shield/start)")
    except Exception as e:
        logger.warning(f"[SHIELD] ⚠️ Falha ao carregar Shield: {e}")

    logger.info("[ACCESS] http://localhost:9200")
    logger.info("=" * 50)
    yield
    # Shutdown
    logger.info("[SHUTDOWN] Parando servidor...")
    try:
        from engines.ransomware_guardian import get_guardian
        get_guardian().stop()
        logger.info("[GUARDIAN] Guardian parado")
    except Exception:
        pass
    try:
        from engines.ransomware_shield import get_shield
        get_shield().stop()
        logger.info("[SHIELD] Shield parado")
    except Exception:
        pass


app = FastAPI(
    title="GBOC Agent",
    __version__ = "11.7c",
    lifespan=lifespan
)

_allowed_origins_raw = os.getenv("AGENT_CORS_ORIGINS", "http://localhost:9200,http://127.0.0.1:9200")
_allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=os.getenv("AGENT_CORS_ORIGIN_REGEX", r"https?://.*"),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
);


def _build_error_diagnostic(message: str) -> str:
    msg = (message or '').lower()
    if 'wrong password' in msg or 'no key found' in msg:
        return 'Credencial/senha do repositório inválida. Revisar segredo do repositório e tarefa associada.'
    if 'timeout' in msg or 'connection refused' in msg or 'no such host' in msg:
        return 'Falha de conectividade. Verificar endpoint, rede e disponibilidade do serviço remoto.'
    if 'permission denied' in msg or 'access denied' in msg:
        return 'Falha de permissão. Verificar privilégios do processo e permissões no destino.'
    return 'Erro não tratado no módulo. Consultar stack trace e logs de contexto para ação corretiva.'


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        msg = str(exc)
        module = f"api:{request.url.path}"
        diagnostic = _build_error_diagnostic(msg)

        if hasattr(core, 'register_error_event'):
            core.register_error_event(
                source='agent_server',
                message=f"Exceção não tratada em {request.url.path}: {msg}",
                details=f"method={request.method}\npath={request.url.path}",
                module=module,
                diagnostic=diagnostic,
                severity='error'
            )
        else:
            logger.error(f"[GLOBAL_ERROR] {request.url.path}: {msg}")
    except Exception as reg_err:
        logger.error(f"[GLOBAL_ERROR] Falha ao registrar exceção global: {reg_err}")

    return JSONResponse(status_code=500, content={
        "status": "error",
        "message": str(exc),
        "module": request.url.path,
        "diagnostic": _build_error_diagnostic(str(exc))
    })

@app.exception_handler(HTTPException)
async def global_http_exception_handler(request: Request, exc: HTTPException):
    if int(exc.status_code) >= 500:
        try:
            from shared_core import get_shared_core
            core = get_shared_core()
            msg = str(exc.detail)
            if hasattr(core, 'register_error_event'):
                core.register_error_event(
                    source='agent_server',
                    message=f"HTTP {exc.status_code} em {request.url.path}: {msg}",
                    details=f"method={request.method}\npath={request.url.path}",
                    module=f"api:{request.url.path}",
                    diagnostic=_build_error_diagnostic(msg),
                    severity='error'
                )
        except Exception:
            pass

    return JSONResponse(status_code=exc.status_code, content={
        "status": "error",
        "message": exc.detail,
        "module": request.url.path,
        "diagnostic": _build_error_diagnostic(str(exc.detail)) if int(exc.status_code) >= 500 else None
    })

# Authentication middleware
try:
    from api.auth_middleware import AuthMiddleware
    app.add_middleware(AuthMiddleware)
    logger.info("[OK] Auth middleware loaded")
except Exception as e:
    logger.warning(f"[WARN] Auth middleware not loaded: {e}")

# ==============================================================================
# 1. ROTAS DE ARQUIVOS ESTÁTICOS (HTML) - PRIORIDADE MÁXIMA
# ==============================================================================

def serve_file(filename):
    """Função auxiliar para servir arquivos da pasta static"""
    file_path = os.path.join(BASE_DIR, "static", filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    logger.error(f"[ERROR] Arquivo nao encontrado: {file_path}")
    return JSONResponse({
        "status": "error",
        "message": f"Arquivo {filename} nao encontrado no servidor."
    }, status_code=404)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return JSONResponse(content={}, status_code=200)


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def chrome_devtools():
    return JSONResponse(content={}, status_code=200)


@app.get("/", include_in_schema=False)
async def serve_index():
    return serve_file("index.html")


@app.get("/tasks.html", include_in_schema=False)
async def serve_tasks():
    return serve_file("tasks.html")


@app.get("/repositories.html", include_in_schema=False)
async def serve_repositories():
    return serve_file("repositories.html")


@app.get("/overview.html", include_in_schema=False)
async def serve_overview():
    return RedirectResponse(url='/', status_code=302)


@app.get("/logs.html", include_in_schema=False)
async def serve_logs():
    return serve_file("logs.html")


@app.get("/restore.html", include_in_schema=False)
async def serve_restore():
    return serve_file("restore.html")


@app.get("/statistics.html", include_in_schema=False)
async def serve_statistics():
    return RedirectResponse(url='/', status_code=302)


@app.get("/settings.html", include_in_schema=False)
async def serve_settings():
    return serve_file("settings.html")


@app.get("/engines.html", include_in_schema=False)
async def serve_engines():
    return serve_file("engines.html")


@app.get("/diagnostic.html", include_in_schema=False)
async def serve_diagnostic():
    return serve_file("diagnostic.html")


@app.get("/login.html", include_in_schema=False)
async def serve_login():
    return serve_file("login.html")


@app.get("/reports.html", include_in_schema=False)
async def serve_reports():
    return serve_file("reports.html")


@app.get("/database-backup.html", include_in_schema=False)
async def serve_database_backup():
    return serve_file("database-backup.html")


@app.get("/changelog.html", include_in_schema=False)
async def serve_changelog():
    return serve_file("changelog.html")


@app.get("/ransomware.html", include_in_schema=False)
async def serve_ransomware():
    return serve_file("ransomware.html")


@app.get("/compliance.html", include_in_schema=False)
async def serve_compliance():
    return serve_file("compliance.html")


@app.get("/alerts.html", include_in_schema=False)
async def serve_alerts():
    return serve_file("alerts.html")


@app.get("/replication.html", include_in_schema=False)
async def serve_replication():
    return serve_file("replication.html")


@app.get("/users.html", include_in_schema=False)
async def serve_users():
    return serve_file("users.html")


@app.get("/config-manager.html", include_in_schema=False)
async def serve_config_manager():
    return serve_file("config-manager.html")


@app.get("/integrity.html", include_in_schema=False)
async def serve_integrity():
    return serve_file("integrity.html")


@app.get("/audit.html", include_in_schema=False)
async def serve_audit():
    return serve_file("audit.html")


@app.get("/notification-channels.html", include_in_schema=False)
async def serve_notification_channels():
    return serve_file("notification-channels.html")


@app.get("/duplicati-native.html", include_in_schema=False)
async def serve_duplicati_native():
    return serve_file("duplicati-native.html")


@app.get("/schema-check.html", include_in_schema=False)
async def serve_schema_check():
    return serve_file("schema-check.html")


@app.get("/auth-diagnostic.html", include_in_schema=False)
async def serve_auth_diagnostic():
    return serve_file("auth-diagnostic.html")


@app.get("/app_v6.js", include_in_schema=False)
async def serve_js_root():
    """Serve JS da raiz para compatibilidade"""
    js_path = os.path.join(BASE_DIR, "static", "app_v6.js")
    if os.path.exists(js_path):
        return FileResponse(js_path, media_type="application/javascript")
    return JSONResponse({"error": "JS not found"}, status_code=404)


# Montar pasta static (para CSS, imagens, etc)
static_path = os.path.join(BASE_DIR, "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")

# ==============================================================================
# 2. CARREGAMENTO DE APIs
# ==============================================================================

API_MODULES = [
    ("api.overview", "router"),
    ("api.repositories", "router"),
    ("api.tasks", "router"),
    ("api.engines", "router"),  # ✅ Validação de motores
    ("api.diagnostics", "router"),
    ("api.alerts", "router"),
    ("api.settings", "router"),
    ("api.logs", "router"),
    ("api.import_api", "router"),
    ("api.api_restore", "router"),
    ("api.errors", "router"),
    ("api.statistics", "router"),
    ("api.backup_control", "router"),
    ("api.fs", "router"),
    ("api.tasks_ops", "router"),
    ("api.smtp", "router"),  # ✅ Configuração SMTP
    ("api.advanced_stats_api", "router"),  # ✅ Estatísticas avançadas 11.7c
    ("api.preemptive_api", "router"),  # ✅ Diagnóstico preemptivo 11.7c
    ("api.system_api", "router"),  # ✅ Sistema completo 11.7c
    ("api.auth", "router"),  # ✅ Autenticação
    ("api.export_api", "router"),  # ✅ Exportação de relatórios
    ("api.integrity_api", "router"),  # ✅ Verificação de integridade
    ("api.reports_api", "router"),  # ✅ Relatórios
    ("api.database_backup_api", "router"),  # ✅ Backup de banco de dados
    ("api.websocket_api", "router"),  # ✅ WebSocket real-time
    ("api.metrics_api", "router"),  # ✅ Prometheus metrics export
    ("api.ransomware_api", "router"),  # ✅ Ransomware detection
    ("api.notification_channels_api", "router"),  # ✅ Slack/Teams/Discord/Telegram
    ("api.replication_api", "router"),  # ✅ Backup replication (3-2-1)
    ("api.config_api", "router"),  # ✅ Config export/import
    ("api.audit_api", "router"),  # ✅ Audit trail
    ("api.compliance_api", "router"),  # ✅ Compliance scoring + policies + audit
    ("api.duplicati_native_api", "router"),  # ✅ Duplicati native module (isolado)
    ("api.schema_check_api", "router"),  # ✅ Schema diagnostics and auto-fix
]


for module_name, router_name in API_MODULES:
    try:
        module = __import__(module_name, fromlist=[router_name])
        router = getattr(module, router_name)
        app.include_router(router)
        logger.info(f"[OK] API: {module_name}")
    except Exception as e:
        logger.warning(f"[WARN] API {module_name}: {e}")

# ==============================================================================
# 3. ENDPOINTS DO SERVIDOR CENTRAL
# ==============================================================================

@app.get("/api/server/status")
async def get_server_status():
    """Obtém status da conexão com servidor central"""
    try:
        status = central_client.get_connection_status()
        return {"status": "success", "server": status}
    except Exception as e:
        logger.error(f"Erro ao obter status do servidor: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/server/configure")
async def configure_server(server_url: str, api_key: str = "gboc-local-server-key"):
    """Configura conexão com servidor central"""
    try:
        result = central_client.configure_server(server_url, api_key)
        if result.get("success"):
            logger.info(f"✅ Servidor central configurado: {server_url}")
        return result
    except Exception as e:
        logger.error(f"Erro ao configurar servidor: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/server/sync")
async def sync_with_server():
    """Força sincronização com servidor central"""
    try:
        result = central_client.sync_with_server()
        return {"status": "success", "sync": result}
    except Exception as e:
        logger.error(f"Erro na sincronização: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/server/config/heartbeat")
async def configure_heartbeat(interval_minutes: int = 2):
    """Configura o intervalo do heartbeat (1-60 minutos)"""
    try:
        if not (1 <= interval_minutes <= 60):
            return {"status": "error", "message": "Intervalo deve ser entre 1 e 60 minutos"}

        # Atualizar configuração usando config_manager
        try:
            from server_config import config_manager

            config_manager.set("heartbeat_interval_minutes", interval_minutes)
            logger.info(f"✅ Intervalo do heartbeat atualizado: {interval_minutes} minutos")

            # Recarregar configuração no cliente
            central_client.reload_config()

            return {
                "status": "success",
                "message": f"Intervalo do heartbeat configurado para {interval_minutes} minutos",
                "interval_minutes": interval_minutes
            }

        except Exception as config_error:
            logger.error(f"Erro ao salvar configuração: {config_error}")
            return {"status": "error", "message": f"Erro ao salvar configuração: {str(config_error)}"}

    except Exception as e:
        logger.error(f"Erro ao configurar heartbeat: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/server/config/sync-interval")
async def configure_sync_interval(interval_minutes: int = 10):
    """Configura o intervalo de sincronização (5-1440 minutos)"""
    try:
        if not (5 <= interval_minutes <= 1440):  # 5 min até 24h
            return {"status": "error", "message": "Intervalo deve ser entre 5 e 1440 minutos"}

        from server_config import config_manager
        config_manager.set("sync_interval_minutes", interval_minutes)

        logger.info(f"✅ Intervalo de sincronização atualizado: {interval_minutes} minutos")
        central_client.reload_config()

        return {
            "status": "success",
            "message": f"Intervalo de sincronização configurado para {interval_minutes} minutos",
            "interval_minutes": interval_minutes
        }
    except Exception as e:
        logger.error(f"Erro ao configurar sincronização: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/server/config/toggle")
async def toggle_server_client(enabled: bool = True):
    """Habilita/desabilita o cliente do servidor central"""
    try:
        from server_config import config_manager
        config_manager.set("enabled", enabled)

        action = "habilitado" if enabled else "desabilitado"
        logger.info(f"✅ Cliente do servidor central {action}")

        if enabled:
            central_client.reload_config()
        else:
            logger.info("🔄 Cliente desabilitado - heartbeat parado")

        return {
            "status": "success",
            "message": f"Cliente do servidor central {action}",
            "enabled": enabled
        }
    except Exception as e:
        logger.error(f"Erro ao alternar cliente: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/server/config/reset")
async def reset_server_config():
    """Reseta configuração do servidor para valores padrão"""
    try:
        from server_config import config_manager
        config_manager.reset_to_defaults()

        logger.info("🔄 Configuração do servidor resetada para valores padrão")
        central_client.reload_config()

        return {
            "status": "success",
            "message": "Configuração resetada para valores padrão",
            "config": config_manager.get_all()
        }
    except Exception as e:
        logger.error(f"Erro ao resetar configuração: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/server/config")
async def get_server_config():
    """Obtém configuração atual do servidor central"""
    try:
        from server_config import config_manager

        status = central_client.get_connection_status()
        validation = config_manager.validate_config()

        return {
            "status": "success",
            "connection": status,
            "config": config_manager.get_all(),
            "validation": validation
        }
    except Exception as e:
        logger.error(f"Erro ao obter configuração: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/system/shutdown")
async def shutdown_agent(request: Request):
    """Shutdown controlado do agente (somente localhost)."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Shutdown permitido apenas localmente")

    async def _stop_soon():
        await asyncio.sleep(0.7)
        os._exit(0)

    asyncio.create_task(_stop_soon())
    return {"status": "success", "message": "Agente encerrando..."}


# ============================================================================== 
# 4. START
# ============================================================================== 

if __name__ == "__main__":
    PORT = int(os.getenv("AGENT_PORT", "9200"))
    HOST = os.getenv("AGENT_HOST", "0.0.0.0")
    _http2 = os.getenv("GBOC_HTTP2", "true").lower() in ("1", "true", "yes")
    try:
        from utils.kill_port import kill_process_on_port
        kill_process_on_port(PORT)
        time.sleep(2)

        for uv_logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
            uv_logger = logging.getLogger(uv_logger_name)
            uv_logger.handlers.clear()
            uv_logger.addHandler(_stream_handler)
            uv_logger.addHandler(_file_handler)

        logger.info(f"[ACCESS] http://{HOST}:{PORT}")

        if _http2:
            try:
                from hypercorn.config import Config
                from hypercorn.asyncio import serve
                from utils.tls_cert import ensure_tls_cert
                import asyncio

                cert, key = ensure_tls_cert(cn="GBOC-Agent", ip="127.0.0.1")
                cfg = Config()
                cfg.bind = [f"{HOST}:{PORT}"]
                cfg.certfile = cert
                cfg.keyfile = key
                cfg.alpn_protocols = ["h2", "http/1.1"]
                cfg.loglevel = "info"
                logger.info(f"[HTTPS] Hypercorn HTTP/2+TLS em https://{HOST}:{PORT}")
                asyncio.run(serve(app, cfg))  # asyncio importado no topo do módulo
            except ImportError:
                logger.warning("[HTTP2] hypercorn não encontrado — usando uvicorn (HTTP/1.1). Execute: pip install hypercorn[h2]")
                uvicorn.run(app, host=HOST, port=PORT, log_level="info")
        else:
            uvicorn.run(app, host=HOST, port=PORT, log_level="info")
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Erro fatal: {e}")

