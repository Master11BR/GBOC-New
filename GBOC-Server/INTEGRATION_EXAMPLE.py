"""
GBOC Server - Arquivo de Integração das Melhorias
Exemplo de como integrar os novos módulos ao gboc_server.py

Este arquivo mostra como modificar o servidor principal para usar todas as melhorias.
COPIE ESTE CONTEÚDO PARA O FINAL DO SEU gboc_server.py
"""

# ===========================
# INTEGRAÇÃO DAS MELHORIAS
# ===========================

# 1. Substituir imports originais com novos módulos
from config import (
    SERVER_VERSION, SERVER_NAME, API_VERSION,
    DB_CONFIG, REDIS_ENABLED, RATE_LIMIT_ENABLED,
    DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
)
from logger import setup_logger, log_with_context
from auth import JWTHandler, PasswordManager, LoginAttemptTracker
from cache import cache, CacheKeys
from rate_limiter import rate_limiter
from dlq import dlq
from retry import RetryHandler, DEFAULT_RETRY_CONFIG
from database import db_manager
from health import health_check, metrics_collector
from webhooks import webhook_manager, WEBHOOK_EVENTS
from models import (
    LoginRequest, AuthResponse, StandardResponse,
    PaginatedResponse, HealthCheckResponse, MetricsResponse
)
from middleware import (
    AuthenticationMiddleware, RateLimitMiddleware, LoggingMiddleware,
    CORSEnhancedMiddleware, require_auth, require_role, handle_exceptions,
    generic_exception_handler, http_exception_handler
)

# 2. Criar logger
logger = setup_logger(__name__)

# ===========================
# LIFESPAN - INICIALIZAR COMPONENTES
# ===========================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup e shutdown do servidor com todas as melhorias"""

    # STARTUP
    logger.info("🚀 Iniciando GBOC Server...")

    # Inicializar database
    if db_manager.initialize():
        logger.info("✓ Database pool inicializado")
    else:
        logger.error("✗ Falha ao inicializar database")

    # Inicializar cache Redis
    if REDIS_ENABLED:
        await cache.initialize()

    # Criar índices
    db_manager.create_index_if_not_exists("agents", "idx_agent_id", "(agent_id)")
    db_manager.create_index_if_not_exists("agents", "idx_agent_status", "(status)")
    db_manager.create_index_if_not_exists("agents", "idx_agent_last_heartbeat", "(last_heartbeat)")
    logger.info("✓ Índices PostgreSQL criados")

    # Verificar saúde do sistema
    health_status = health_check.check_system()
    logger.info(f"✓ Sistema: {health_status['status'].upper()}")

    yield

    # SHUTDOWN
    logger.info("🛑 Encerrando GBOC Server...")
    db_manager.close_all()
    await cache.close()
    logger.info("✓ Recursos liberados")

# ===========================
# CONFIGURAR APP FASTAPI
# ===========================

app = FastAPI(
    title="GBOC Server",
    version=SERVER_VERSION,
    description="Servidor Central com Melhorias de Segurança, Performance e Confiabilidade",
    lifespan=lifespan
)

# Adicionar middlewares na ordem correta
app.add_middleware(CORSEnhancedMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthenticationMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Adicionar exception handlers
app.add_exception_handler(Exception, generic_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)

# ===========================
# ENDPOINTS DE SAÚDE E MONITORAMENTO
# ===========================

@app.get("/health", response_model=HealthCheckResponse, tags=["Monitoramento"])
async def health_status():
    """Verificar saúde do servidor"""
    status = health_check.check_system()
    return status

@app.get("/metrics", response_model=MetricsResponse, tags=["Monitoramento"])
async def server_metrics():
    """Obter métricas do servidor"""
    metrics = metrics_collector.get_metrics()
    return metrics

@app.get("/api/{api_version}/health/detailed", tags=["Monitoramento"])
@require_auth
@require_role("admin")
async def health_detailed(request: Request):
    """Health check detalhado (admin only)"""
    checks = {
        "database": health_check.check_database(),
        "cache": health_check.check_cache(),
        "dlq": health_check.check_dlq(),
    }
    return {"status": "ok", "checks": checks}

# ===========================
# ENDPOINTS DE AUTENTICAÇÃO (MELHORADOS)
# ===========================

@app.post("/api/v1/auth/login", response_model=AuthResponse, tags=["Autenticação"])
async def login(request: Request, credentials: LoginRequest):
    """Login com JWT tokens"""

    # Verificar rate limit
    client_ip = request.client.host
    allowed, _ = rate_limiter.is_allowed(client_ip, "/api/v1/auth/login")
    if not allowed:
        raise HTTPException(status_code=429, detail="Muitas tentativas de login")

    # Verificar se conta está bloqueada
    if LoginAttemptTracker.is_locked(credentials.username):
        raise HTTPException(status_code=403, detail="Conta temporariamente bloqueada")

    # Validar credenciais (exemplo)
    user = None  # Buscar do banco

    if not user or not PasswordManager.verify_password(credentials.password, user["password_hash"]):
        LoginAttemptTracker.record_failed_attempt(credentials.username)
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    # Reset de tentativas
    LoginAttemptTracker.reset_attempts(credentials.username)

    # Criar tokens
    token_data = {
        "sub": user["username"],
        "user_id": user["id"],
        "role": user["role"]
    }

    access_token = JWTHandler.create_access_token(token_data)
    refresh_token = JWTHandler.create_refresh_token(token_data)

    logger.info(f"✓ Login bem-sucedido: {credentials.username}")

    return AuthResponse(
        status="success",
        access_token=access_token,
        refresh_token=refresh_token,
        user={"username": user["username"], "role": user["role"]},
        expires_in=3600
    )

@app.post("/api/v1/auth/refresh", response_model=AuthResponse, tags=["Autenticação"])
async def refresh_token(refresh_token: str):
    """Renovar access token usando refresh token"""

    new_access_token = JWTHandler.refresh_access_token(refresh_token)
    if not new_access_token:
        raise HTTPException(status_code=401, detail="Refresh token inválido")

    return AuthResponse(
        status="success",
        access_token=new_access_token,
        expires_in=3600
    )

@app.post("/api/v1/auth/logout", tags=["Autenticação"])
@require_auth
async def logout(request: Request):
    """Logout (revoga token)"""
    token = request.state.token
    TokenManager.revoke_token(token)
    return StandardResponse(status="success", message="Logout bem-sucedido")

# ===========================
# ENDPOINTS DE AGENTES (MELHORADOS)
# ===========================

@app.get("/api/v1/agents", tags=["Agentes"])
@require_auth
async def list_agents(page: int = 1, page_size: int = 20):
    """Listar agentes com paginação"""

    # Validar paginação
    page_size = min(page_size, MAX_PAGE_SIZE)

    # Tentar cache primeiro
    cache_key = f"agents:list:{page}:{page_size}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    # Buscar do banco
    offset = (page - 1) * page_size

    total = db_manager.execute_query(
        "SELECT COUNT(*) FROM agents",
        fetch_one=True
    )[0]

    agents = db_manager.execute_query(
        "SELECT * FROM agents ORDER BY registered_at DESC LIMIT %s OFFSET %s",
        (page_size, offset),
        fetch_all=True,
        dict_cursor=True
    )

    # Preparar resposta
    response = {
        "data": agents or [],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "has_next": offset + page_size < total,
        "has_previous": page > 1
    }

    # Cachear resultado
    await cache.set(cache_key, response, ttl=CACHE_AGENT_DATA_TTL)

    return response

@app.get("/api/v1/agents/{agent_id}", tags=["Agentes"])
@require_auth
async def get_agent(agent_id: str):
    """Obter dados de um agente"""

    # Tentar cache
    cache_key = CacheKeys.agent_data(agent_id)
    cached = await cache.get(cache_key)
    if cached:
        return StandardResponse(status="success", data=cached)

    # Buscar do banco com retry
    result = await RetryHandler.execute_with_retry(
        db_manager.execute_query,
        "SELECT * FROM agents WHERE agent_id = %s",
        (agent_id,),
        fetch_one=True,
        dict_cursor=True,
        config=DEFAULT_RETRY_CONFIG,
        context={"agent_id": agent_id, "operation": "fetch_agent"}
    )

    if not result:
        raise HTTPException(status_code=404, detail="Agente não encontrado")

    # Cachear
    await cache.set(cache_key, result, ttl=CACHE_AGENT_DATA_TTL)

    return StandardResponse(status="success", data=result)

# ===========================
# ENDPOINTS DE MONITORAMENTO AVANÇADO
# ===========================

@app.get("/api/v1/dlq/stats", tags=["Dead Letter Queue"])
@require_auth
@require_role("admin")
async def dlq_stats():
    """Estatísticas da Dead Letter Queue"""
    stats = dlq.get_stats()
    return StandardResponse(status="success", data=stats)

@app.get("/api/v1/dlq/pending", tags=["Dead Letter Queue"])
@require_auth
@require_role("admin")
async def dlq_pending(limit: int = 10):
    """Recuperar mensagens pendentes na DLQ"""
    pending = dlq.get_pending(limit=limit)
    return StandardResponse(status="success", data={"pending": pending})

@app.post("/api/v1/dlq/reprocess/{timestamp}", tags=["Dead Letter Queue"])
@require_auth
@require_role("admin")
async def dlq_reprocess(timestamp: str):
    """Reprocessar uma mensagem da DLQ manualmente"""
    # Implementar lógica de reprocessamento
    return StandardResponse(status="success", message="Reprocessamento iniciado")

# ===========================
# ENDPOINTS DE CONFIGURAÇÃO
# ===========================

@app.get("/api/v1/settings", tags=["Configurações"])
@require_auth
async def get_settings():
    """Obter configurações do servidor"""

    # Tentar cache
    cache_key = "settings:all"
    cached = await cache.get(cache_key)
    if cached:
        return StandardResponse(status="success", data=cached)

    # Buscar do banco
    settings = db_manager.execute_query(
        "SELECT * FROM server_settings",
        fetch_all=True,
        dict_cursor=True
    )

    # Converter para dict
    settings_dict = {s["key"]: s["value"] for s in settings}

    # Cachear
    await cache.set(cache_key, settings_dict, ttl=CACHE_SETTINGS_TTL)

    return StandardResponse(status="success", data=settings_dict)

# ===========================
# EXECUTAR SERVIDOR
# ===========================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "gboc_server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
