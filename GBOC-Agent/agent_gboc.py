#!/usr/bin/env python3
"""
🚀 GBOC Agent 14.8.1 - Servidor Principal
Servidor FastAPI com arquitetura modular limpa
"""

import sys
import os
import logging
import uvicorn
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import platform
from datetime import datetime
import time
import asyncio
import ssl
import socket

# ── Patch para Windows Proactor EventLoop (Python 3.14) ──────────────────────
if sys.platform == "win32":
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport
        _orig_call_conn_lost = _ProactorBasePipeTransport._call_connection_lost

        def _safe_call_connection_lost(self, exc):
            if getattr(self, '_called_connection_lost', False):
                return
            try:
                if hasattr(self, '_protocol') and self._protocol is not None:
                    self._protocol.connection_lost(exc)
            finally:
                if hasattr(self, '_sock') and self._sock is not None:
                    if hasattr(self._sock, 'shutdown') and self._sock.fileno() != -1:
                        try:
                            self._sock.shutdown(socket.SHUT_RDWR)
                        except (OSError, ConnectionResetError, BrokenPipeError):
                            pass
                    try:
                        self._sock.close()
                    except Exception:
                        pass
                    self._sock = None
                server = getattr(self, '_server', None)
                if server is not None:
                    try:
                        server._detach(self)
                    except Exception:
                        pass
                    self._server = None
                self._called_connection_lost = True

        _ProactorBasePipeTransport._call_connection_lost = _safe_call_connection_lost
    except Exception:
        pass

# Diretório base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
# Dynamic SemVer 2.0 versioning
try:
    from version_control import __version__ as AGENT_VERSION, get_version_info, auto_increment_build
    auto_increment_build()
except Exception:
    AGENT_VERSION = "14.8.1"
    def get_version_info():
        return {"raw_version": AGENT_VERSION, "semver": AGENT_VERSION}


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

class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler imune a PermissionError no Windows durante rotação de logs."""
    def shouldRollover(self, record):
        try:
            return super().shouldRollover(record)
        except PermissionError:
            return False
        except Exception:
            return False

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            pass
        except Exception:
            pass

    def emit(self, record):
        try:
            super().emit(record)
        except PermissionError:
            pass
        except Exception:
            pass

class LocalTimeFormatter(logging.Formatter):
    converter = time.localtime

_log_formatter = LocalTimeFormatter(
    fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# SafeRotatingFileHandler: máx 10 MB por arquivo, mantém 5 backups
_file_handler = SafeRotatingFileHandler(
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
_stderr_handler = SafeRotatingFileHandler(
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

# CPU amostrada em segundo plano: psutil.cpu_percent(interval=...) deixa de dormir dentro das rotas
try:
    from core.fast_metrics import install as _install_fast_metrics
    _install_fast_metrics()
except Exception as _fm_e:
    logger.warning(f"Métricas rápidas de CPU indisponíveis: {_fm_e}")

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
        # Ignorar erros de close-notify do SSL e erros de rotação de log do Windows
        if (
            "APPLICATION_DATA_AFTER_CLOSE_NOTIFY" in msg
            or "application data after close notify" in msg
            or "TLSV1_ALERT_UNKNOWN_CA" in msg
            or "tlsv1 alert unknown ca" in msg
            or "Logging error" in msg
            or "PermissionError" in msg
            or "shouldRollover" in msg
        ):
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
    logger.info("[STARTUP] GBOC Agent 14.6.0 - Servidor Iniciado")
    logger.info(f"[DATA] {DATA_DIR}")
    logger.info(f"[LOGS] {LOGS_DIR}")
    
    # Validar arquivos estáticos
    static_files = ["index.html", "tasks.html", "repositories.html", "overview.html", "logs.html", "restore.html", "statistics.html", "settings.html", "diagnostic.html", "login.html", "ransomware.html", "compliance.html", "alerts.html", "replication.html", "users.html", "config-manager.html", "integrity.html", "audit.html", "notification-channels.html", "duplicati-native.html", "schema-check.html", "auth-diagnostic.html", "failed-jobs.html", "storage-usage.html", "import.html"]
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

    # Inscrição automática (instalação em massa): C:\ProgramData\GBOC\enroll.json com URL + token de instalação
    try:
        import threading as _enroll_th
        from core.enrollment import seed_loop
        _enroll_th.Thread(target=seed_loop, name="gboc-enroll", daemon=True).start()
    except Exception as e:
        logger.warning(f"[INSCRIÇÃO] Verificação do enroll.json indisponível: {e}")

    # Retenção automática dos logs do agente (Logs > Retenção; 0 = manter tudo)
    try:
        from api.logs import start_retention_loop
        start_retention_loop()
    except Exception as e:
        logger.warning(f"[LOGS] Retenção automática indisponível: {e}")

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

    # Iniciar Job Alert Monitor (alerta proativo de falhas)
    try:
        from engines.job_alert_monitor import start_job_failure_monitor
        start_job_failure_monitor()
        logger.info("[JOB-ALERT] ✅ Job Alert Monitor ativo (verificação a cada 2 min)")
    except Exception as e:
        logger.warning(f"[JOB-ALERT] ⚠️ Falha ao iniciar Job Alert Monitor: {e}")

    # Iniciar Storage Growth Monitor
    try:
        from engines.storage_monitor import start_storage_monitor
        start_storage_monitor()
        logger.info("[📦 STORAGE] ✅ Storage Growth Monitor ativo")
    except Exception as e:
        logger.warning(f"[📦 STORAGE] ⚠️ Falha ao iniciar Storage Monitor: {e}")

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

    # Iniciar Hermes Agent — Agente de Borda Autônomo (4 Pilares)
    try:
        from engines.hermes_self_heal_engine import hermes_self_heal_engine
        hermes_self_heal_engine.start_watchdog()
        logger.info("[HERMES] ✅ Self-Healing Watchdog ativo (VSS + Disk + Serviços a cada 120s)")
    except Exception as _he:
        logger.warning(f"[HERMES] ⚠️ Falha ao iniciar Self-Heal Watchdog: {_he}")

    try:
        from engines.hermes_bandwidth_engine import hermes_bandwidth_engine
        hermes_bandwidth_engine.start()
        logger.info("[HERMES] ✅ Edge AI Bandwidth Engine ativo (aprendizado adaptativo de largura de banda)")
    except Exception as _he:
        logger.warning(f"[HERMES] ⚠️ Falha ao iniciar Bandwidth Engine: {_he}")

    try:
        from engines.hermes_mesh_engine import hermes_mesh_engine
        import socket as _sock
        import os as _os
        _agent_id = _os.environ.get("GBOC_AGENT_ID", _sock.gethostname())
        hermes_mesh_engine.start(_agent_id)
        logger.info(f"[HERMES] ✅ P2P LAN Mesh ativo (mDNS/UDP broadcast — agente: {_agent_id})")
    except Exception as _he:
        logger.warning(f"[HERMES] ⚠️ Falha ao iniciar LAN Mesh: {_he}")

    try:
        get_version_info()
    except Exception:
        pass

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
    version=AGENT_VERSION,
    lifespan=lifespan
)

@app.get("/api/v1/version", tags=["System"])
@app.get("/api/v1/system/version", tags=["System"])
@app.get("/api/system/info", tags=["System"])
async def get_agent_version_endpoint():
    """Retorna informações detalhadas do versionamento semântico 2.0 e contrato de UI Model."""
    info = get_version_info()
    if isinstance(info, dict):
        info["gboc_version"] = AGENT_VERSION
        info["raw_version"] = AGENT_VERSION
        info["version"] = AGENT_VERSION
        info["status"] = "success"
        info["UI_MODEL"] = "modern"
        info["ACTIVE_UI_MODEL"] = "modern"
        info["DEFAULT_UI_MODEL"] = "modern"
    return info

@app.get("/api/v1/system/ui-config", tags=["System"])
async def get_agent_ui_config_endpoint():
    """Retorna a configuração oficial estrita do Modelo UI/UX Moderno."""
    return {
        "UI_MODEL": "modern",
        "ACTIVE_UI_MODEL": "modern",
        "DEFAULT_UI_MODEL": "modern",
        "AVAILABLE_MODELS": ["modern"],
        "DEFAULT_THEME": "dark",
        "AVAILABLE_THEMES": ["dark", "light", "purple", "ocean"],
        "DEFAULT_UI_STYLE": "minimal",
        "AVAILABLE_UI_STYLES": ["minimal", "neumorphism", "claymorphism", "fluent"]
    }

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

_SLOW_THRESHOLD_MS = float(os.getenv("GBOC_SLOW_MS", "250"))

@app.middleware("http")
async def _gboc_asset_revalidate(request: Request, call_next):
    """JS/CSS/HTML sempre revalidados (ETag → 304): os HTML usam ?v= fixo e, sem isso,
    o navegador seguia com scripts antigos depois de uma atualização do GBOC."""
    r = await call_next(request)
    p = request.url.path.lower()
    if p.endswith(".html") or p in ("/", ""):
        r.headers["Cache-Control"] = "no-cache"
    elif p.endswith((".js", ".css")):
        # Antes "no-cache": cada troca de tela revalidava ~20 arquivos (um pedido ao servidor por arquivo).
        # 5 minutos em cache: navegação rápida; uma atualização do GBOC aparece em até 5 min (ou Ctrl+F5).
        r.headers["Cache-Control"] = "private, max-age=300"
    elif p.endswith((".woff2", ".woff", ".ttf", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".webp", ".gif")):
        r.headers["Cache-Control"] = "private, max-age=86400"
    return r

@app.middleware("http")
async def _gboc_timing_middleware(request: Request, call_next):
    """Medidor de performance das rotas HTTP.

    Qualquer rota com tempo > GBOC_SLOW_MS (padrão 250 ms) é logada com WARNING
    para fácil identificação de operações síncronas que bloqueiam o event loop
    (ex: .sleep síncrono, SELECT * sem índice, subprocess que trava, etc).

    A latência reportada é o tempo de ida-e-volta do handler.
    """
    t0 = time.perf_counter()
    try:
        r = await call_next(request)
        return r
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if dt_ms >= _SLOW_THRESHOLD_MS:
            try:
                method = request.method
                path = request.url.path
                query = request.url.query
                full = f"{method} {path}"
                if query:
                    full += f"?{query}"
                logger.warning(
                    "[PERF-SLOW] %s — %.0f ms (threshold=%.0f ms). "
                    "Se repetir, considerar asyncio.to_thread() / LIMIT / índices.",
                    full, dt_ms, _SLOW_THRESHOLD_MS,
                )
            except Exception:
                pass


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
    clean_name = (filename or '').lstrip("/\\")
    if clean_name.startswith("static/") or clean_name.startswith("static\\"):
        clean_name = clean_name[7:]
    file_path = os.path.join(BASE_DIR, "static", clean_name)
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
    ("api.advanced_stats_api", "router"),  # ✅ Estatísticas avançadas 14.6.0
    ("api.preemptive_api", "router"),  # ✅ Diagnóstico preemptivo 14.6.0
    ("api.system_api", "router"),  # ✅ Sistema completo 14.6.0
    ("api.auth", "router"),  # ✅ Autenticação (/api/auth)
    ("api.auth", "router_v1"),  # ✅ Autenticação v1 (/api/v1/auth)
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
    ("api.hardware_api", "router"),  # ✅ Hardware, Disks & SMART
    ("api.ai_api", "router"),  # ✅ GBOC Copilot AI Assistant (/api/ai)
    ("api.ai_api", "router_v1"),  # ✅ GBOC Copilot AI Assistant v1 (/api/v1/ai)
    ("api.diagnostics", "router_v1"),  # ✅ IA de diagnóstico v1 (/api/v1/diagnostics/ai-*)
    ("api.agent_ops_api", "router"),  # ✅ Teste de restauração, atualização remota e pausa de agendamentos
]


for module_name, router_name in API_MODULES:
    try:
        module = __import__(module_name, fromlist=[router_name])
        router = getattr(module, router_name)
        app.include_router(router)
        logger.info(f"[OK] API: {module_name}")
    except Exception as e:
        logger.warning(f"[WARN] API {module_name}: {e}")

try:
    from modules.v2.v2_router import v2_router
    app.include_router(v2_router)
    logger.info("[OK] API v2: modules.v2.v2_router")
except Exception as e:
    logger.warning(f"[WARN] API v2: {e}")

# ==============================================================================
# 3. ENDPOINTS DO SERVIDOR CENTRAL
# ==============================================================================

@app.get("/api/server/status")
async def get_server_status():
    """Obtém status da conexão com servidor central"""
    try:
        central_client.sync_runtime_config("consulta de status")   # reflete a chave gravada por outro processo
        status = central_client.get_connection_status()
        return {"status": "success", "server": status}
    except Exception as e:
        logger.error(f"Erro ao obter status do servidor: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/server/configure")
async def configure_server(request: Request, server_url: Optional[str] = None, api_key: Optional[str] = None,
                           tenant_id: Optional[str] = None):
    """Configura conexão com servidor central (aceita JSON no corpo ou query string).
    api_key = chave de pareamento exibida no GBOC Server; vazio mantém a chave já salva."""
    try:
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        server_url = (body.get("server_url") or server_url or "").strip()
        if not (body.get("api_key") or api_key or "").strip():
            central_client.sync_runtime_config("salvar sem nova chave")   # mantém a chave do ARQUIVO, não uma antiga em memória
        api_key = (body.get("api_key") or api_key or "").strip() or (central_client.api_key or "")
        tenant_id = body.get("tenant_id", tenant_id)
        if not server_url:
            return {"status": "error", "success": False, "message": "Informe a URL do Servidor Central"}
        result = await asyncio.to_thread(central_client.configure_server, server_url, api_key, tenant_id)
        if result.get("success"):
            logger.info(f"✅ Servidor central configurado: {server_url} (tenant: {tenant_id})")
        result.setdefault("status", "success" if result.get("success") else "error")
        result.setdefault("message", result.get("error") or "")
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

@app.post("/api/v1/system/shutdown", tags=["System"])
@app.post("/api/system/shutdown", tags=["System"])
async def shutdown_agent(request: Request):
    """Shutdown controlado do agente GBOC."""
    host = request.client.host if request.client else ""
    is_local = host in ("127.0.0.1", "::1", "localhost", "testclient")

    is_allowed = is_local
    if not is_allowed and host:
        try:
            import ipaddress
            ip = ipaddress.ip_address(host)
            is_allowed = ip.is_loopback or ip.is_private
        except Exception:
            is_allowed = False

    if not is_allowed:
        raise HTTPException(status_code=403, detail="Shutdown permitido apenas localmente ou via rede privada autorizada")

    logger.info(f"[SHUTDOWN] Agente GBOC recebendo solicitacao de encerramento de host={host}")

    async def _stop_soon():
        await asyncio.sleep(0.8)
        try:
            from engines.ransomware_guardian import get_guardian
            get_guardian().stop()
        except Exception:
            pass
        try:
            from engines.ransomware_shield import get_shield
            get_shield().stop()
        except Exception:
            pass
        try:
            from shared_core import get_shared_core
            core = get_shared_core()
            if hasattr(core, "shutdown"):
                core.shutdown()
        except Exception:
            pass
        logger.info("[SHUTDOWN] Agente GBOC finalizado.")
        os._exit(0)

    asyncio.create_task(_stop_soon())
    return {"status": "success", "message": "GBOC Agent encerrando com sucesso..."}



# ============================================================================== 
# 3.5. ENTERPRISE ENDPOINTS (RMM, CBT, DR, Security Sentinel, Remote Restore)
# ============================================================================== 



# /api/v1/cbt/* e /api/v1/dr/export: implementados em modules/cbt e modules/dr.
# (As rotas duplicadas que existiam aqui importavam módulos vazios — core/cbt_vss.py e
#  core/agent_dr_sync.py — e, por serem registradas antes, sobrepunham as rotas reais com erro 500.)

@app.post("/api/v1/dr/import-file")
async def dr_import_from_file(request: Request):
    """Restauração de pacote DR a partir de arquivo ainda não implementada (core/dr_restore_manager.py está vazio)."""
    return JSONResponse(
        {"status": "unavailable", "error": {"code": "DR_IMPORT_NOT_IMPLEMENTED",
         "message": "Importação de pacote DR a partir de arquivo ainda não está implementada neste Agente."}},
        status_code=501,
    )

@app.get("/api/v1/security/defender-status")
async def security_defender_status():
    try:
        from core.security_sentinel import security_sentinel
        return security_sentinel.get_windows_defender_status()
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.post("/api/v1/security/defender-scan")
async def security_defender_scan(request: Request):
    try:
        body = await request.json()
        scan_type = body.get("scan_type", "Quick")
        from core.security_sentinel import security_sentinel
        return security_sentinel.trigger_windows_defender_scan(scan_type)
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.post("/api/v1/security/clamav-scan")
async def security_clamav_scan(request: Request):
    try:
        body = await request.json()
        path = body.get("path", ".")
        from core.security_sentinel import security_sentinel
        return security_sentinel.run_clamav_scan(path)
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.post("/api/v1/remote-restore/register")
async def remote_restore_register(request: Request):
    try:
        body = await request.json()
        agent_id = body.get("agent_id")
        ip = body.get("ip_address")
        port = int(body.get("port", 9200))
        from core.remote_restore_manager import remote_restore_manager
        return remote_restore_manager.register_remote_agent(agent_id, ip, port)
    except Exception as e:
        raise HTTPException(500, detail=str(e))

# Rotas de IA de diagnóstico (/api/diagnostics/* e /api/v1/diagnostics/*): api/diagnostics.py

# ==============================================================================
# GBOC AGENT MODULAR ROUTERS INCLUDE (ALL AGENT MODULES)
# ==============================================================================
try:
    # Migração de motores (chamada pelo Server com a chave de pareamento)
    from api.api_migrator import router as agent_migrator_router
    app.include_router(agent_migrator_router)
except Exception as _mig_err:
    logger.warning(f"Router de migração de motores indisponível: {_mig_err}")

try:
    from modules.rmm.rmm_router import router as agent_rmm_router
    app.include_router(agent_rmm_router)
    from modules.cbt.cbt_router import router as agent_cbt_router
    app.include_router(agent_cbt_router)
    from modules.dr.dr_router import router as agent_dr_router
    app.include_router(agent_dr_router)
    from modules.active_directory.ad_router import router as ad_backup_router
    app.include_router(ad_backup_router)
    from modules.enterprise_connectors.enterprise_connectors_router import router as enterprise_connectors_router
    app.include_router(enterprise_connectors_router)
    from modules.saas_cloud.saas_cloud_router import router as saas_cloud_router
    app.include_router(saas_cloud_router)
    from modules.freemium_power_tools.power_tools_router import router as power_tools_router
    app.include_router(power_tools_router)
    from modules.security.security_router import router as agent_security_router
    app.include_router(agent_security_router)
    from modules.logs.logs_router import router as agent_logs_router
    app.include_router(agent_logs_router)
    from modules.config.config_router import router as agent_config_router
    app.include_router(agent_config_router)
    # api.ai_api (router e router_v1) já é registrado via API_MODULES — evita rotas duplicadas.
    from modules.job_alert.job_alert_router import router as job_alert_router
    app.include_router(job_alert_router)
    from modules.storage.storage_router import router as storage_router
    app.include_router(storage_router)
    # Hermes Agent — Agente de Borda Autônomo
    from modules.hermes.hermes_router import router as hermes_agent_router
    app.include_router(hermes_agent_router)
    # Virtualization & Agentless Hypervisors (VMware ESXi, Hyper-V RCT)
    from modules.virtualization.virtualization_router import router as virtualization_router
    app.include_router(virtualization_router)
    # Granular Item-Level Recovery (SQL, PostgreSQL, AD)
    from modules.granular_recovery.granular_recovery_router import router as granular_recovery_router
    app.include_router(granular_recovery_router)
except Exception as _e:
    logger.warning(f"Falha ao carregar módulos do Agente: {_e}")





# ============================================================================== 
# 4. START
# ============================================================================== 
 


# ===========================
# STATIC & HTML ROUTES (GUI)
# ===========================
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

@app.get("/login.html", include_in_schema=False)
async def login_page():
    candidates = [
        os.path.join(os.path.dirname(__file__), "static", "login.html"),
        os.path.join(os.path.dirname(__file__), "login.html"),
        os.path.join(BASE_DIR, "static", "login.html"),
        os.path.join(BASE_DIR, "login.html"),
    ]
    for _path in candidates:
        if os.path.exists(_path):
            return FileResponse(_path)
    return HTMLResponse("<h1>Login page not found</h1>", status_code=404)

@app.get("/static/{filename:path}", include_in_schema=False)
async def serve_static_asset(filename: str):
    clean_fn = (filename or '').lstrip("/\\")
    if clean_fn.startswith("static/") or clean_fn.startswith("static\\"):
        clean_fn = clean_fn[7:]
    static_file = os.path.join(os.path.dirname(__file__), "static", clean_fn)
    if os.path.isfile(static_file):
        return FileResponse(static_file)
    srv_file = os.path.join(os.path.dirname(__file__), clean_fn)
    if os.path.isfile(srv_file):
        return FileResponse(srv_file)
    return HTMLResponse("Not found", status_code=404)

@app.get("/{page_name:path}.html", include_in_schema=False)
async def serve_any_html_page(page_name: str):
    clean_p = (page_name or '').lstrip("/\\")
    if clean_p.startswith("static/") or clean_p.startswith("static\\"):
        clean_p = clean_p[7:]
    fname = f"{clean_p}.html" if not clean_p.endswith(".html") else clean_p
    
    # 1. Procurar na pasta static/ (onde as páginas do Agente residem)
    static_file = os.path.join(os.path.dirname(__file__), "static", fname)
    if os.path.isfile(static_file):
        return FileResponse(static_file, media_type="text/html")
        
    # 2. Procurar na propria pasta root
    srv_file = os.path.join(os.path.dirname(__file__), fname)
    if os.path.isfile(srv_file):
        return FileResponse(srv_file, media_type="text/html")
        
    # 3. Fallback para dashboard.html ou index.html
    dash_file = os.path.join(os.path.dirname(__file__), "dashboard.html")
    idx_file = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.isfile(dash_file):
        return FileResponse(dash_file, media_type="text/html")
    if os.path.isfile(idx_file):
        return FileResponse(idx_file, media_type="text/html")
        
    return HTMLResponse(f"Página '{fname}' não encontrada.", status_code=404)

@app.get("/{file:path}.js", include_in_schema=False)
async def serve_any_js_page(file: str):
    clean_p = (file or '').lstrip("/\\")
    if clean_p.startswith("static/") or clean_p.startswith("static\\"):
        clean_p = clean_p[7:]
    fname = f"{clean_p}.js" if not clean_p.endswith(".js") else clean_p
    static_file = os.path.join(os.path.dirname(__file__), "static", fname)
    if os.path.isfile(static_file):
        return FileResponse(static_file, media_type="application/javascript")
    srv_file = os.path.join(os.path.dirname(__file__), fname)
    if os.path.isfile(srv_file):
        return FileResponse(srv_file, media_type="application/javascript")
    return HTMLResponse("Not found", status_code=404)

@app.get("/{file:path}.css", include_in_schema=False)
async def serve_any_css_page(file: str):
    clean_p = (file or '').lstrip("/\\")
    if clean_p.startswith("static/") or clean_p.startswith("static\\"):
        clean_p = clean_p[7:]
    fname = f"{clean_p}.css" if not clean_p.endswith(".css") else clean_p
    static_file = os.path.join(os.path.dirname(__file__), "static", fname)
    if os.path.isfile(static_file):
        return FileResponse(static_file, media_type="text/css")
    srv_file = os.path.join(os.path.dirname(__file__), fname)
    if os.path.isfile(srv_file):
        return FileResponse(srv_file, media_type="text/css")
    return HTMLResponse("Not found", status_code=404)


from fastapi.responses import RedirectResponse
@app.get("/")
async def index():
    return RedirectResponse(url="/dashboard.html", status_code=302)

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

        # Filtro para suprimir erros SSL close-notify que são ruído benigno
        class SSLCloseNotifyFilter(logging.Filter):
            def filter(self, record):
                msg = record.getMessage()
                return (
                    "APPLICATION_DATA_AFTER_CLOSE_NOTIFY" not in msg
                    and "application data after close notify" not in msg
                    and "TLSV1_ALERT_UNKNOWN_CA" not in msg
                    and "tlsv1 alert unknown ca" not in msg
                )

        asyncio_logger = logging.getLogger("asyncio")
        asyncio_logger.addFilter(SSLCloseNotifyFilter())

        def _install_asyncio_ssl_ignore(loop: asyncio.AbstractEventLoop):
            previous_handler = loop.get_exception_handler()

            def _handler(current_loop, context):
                exc = context.get("exception")
                if isinstance(exc, ssl.SSLError):
                    txt = str(exc)
                    if "APPLICATION_DATA_AFTER_CLOSE_NOTIFY" in txt or "TLSV1_ALERT_UNKNOWN_CA" in txt:
                        return
                if previous_handler is not None:
                    previous_handler(current_loop, context)
                else:
                    current_loop.default_exception_handler(context)

            loop.set_exception_handler(_handler)

        logger.info(f"[ACCESS] http://{HOST}:{PORT}")

        def _build_uvicorn_kwargs(extra: dict = None) -> dict:
            kwargs = {"log_level": "info"}
            try:
                import httptools  # noqa: F401
                kwargs["http"] = "httptools"
            except Exception:
                pass
            if sys.platform != "win32":
                try:
                    import uvloop  # noqa: F401
                    kwargs["loop"] = "uvloop"
                except Exception:
                    pass
            if extra:
                kwargs.update(extra)
            return kwargs

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
                cfg.graceful_timeout = 3
                cfg.shutdown_timeout = 10
                cfg.keep_alive_timeout = 5
                logger.info(f"[HTTPS] Hypercorn HTTP/2+TLS em https://{HOST}:{PORT}")
                async def _run_https():
                    _install_asyncio_ssl_ignore(asyncio.get_running_loop())
                    await serve(app, cfg)

                asyncio.run(_run_https())  # asyncio importado no topo do módulo
            except ImportError:
                logger.warning("[HTTP2] hypercorn não encontrado — usando uvicorn (HTTP/1.1). Execute: pip install hypercorn[h2]")
                uvicorn.run(app, host=HOST, port=PORT, **_build_uvicorn_kwargs())
        else:
            uvicorn.run(app, host=HOST, port=PORT, **_build_uvicorn_kwargs())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Erro fatal: {e}")

