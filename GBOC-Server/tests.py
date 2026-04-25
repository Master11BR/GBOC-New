"""
GBOC Server - Testes dos Componentes
Testes para validar as melhorias implementadas
"""
import asyncio
import pytest
from datetime import datetime, timedelta

# ===========================
# TESTES DE AUTENTICAÇÃO
# ===========================

def test_password_manager():
    """Testar gerenciamento de senhas"""
    from auth import PasswordManager

    password = "MySecurePassword123!"
    password_hash = PasswordManager.hash_password(password)

    # Verificar hash válido
    assert PasswordManager.verify_password(password, password_hash) is True

    # Verificar hash inválido
    assert PasswordManager.verify_password("WrongPassword", password_hash) is False

    # Verificar senha muito curta
    with pytest.raises(ValueError):
        PasswordManager.hash_password("short")

    print("✓ Testes de Password Manager passaram")

def test_jwt_handler():
    """Testar JWT tokens"""
    from auth import JWTHandler

    data = {"sub": "user123", "role": "admin"}

    # Criar tokens
    access_token = JWTHandler.create_access_token(data)
    refresh_token = JWTHandler.create_refresh_token(data)

    assert access_token is not None
    assert refresh_token is not None

    # Verificar tokens
    access_payload = JWTHandler.verify_token(access_token, token_type="access")
    assert access_payload is not None
    assert access_payload["sub"] == "user123"

    refresh_payload = JWTHandler.verify_token(refresh_token, token_type="refresh")
    assert refresh_payload is not None

    # Renovar token
    new_access = JWTHandler.refresh_access_token(refresh_token)
    assert new_access is not None

    print("✓ Testes de JWT Handler passaram")

def test_login_attempt_tracker():
    """Testar rastreamento de tentativas de login"""
    from auth import LoginAttemptTracker

    username = "testuser"

    # Reset inicial
    LoginAttemptTracker.reset_attempts(username)
    assert LoginAttemptTracker.is_locked(username) is False

    # Registrar tentativas
    for i in range(4):
        is_locked = LoginAttemptTracker.record_failed_attempt(username)
        assert is_locked is False

    # Quinta tentativa deve bloquear
    is_locked = LoginAttemptTracker.record_failed_attempt(username)
    assert is_locked is True
    assert LoginAttemptTracker.is_locked(username) is True

    # Reset
    LoginAttemptTracker.reset_attempts(username)
    assert LoginAttemptTracker.is_locked(username) is False

    print("✓ Testes de Login Attempt Tracker passaram")

# ===========================
# TESTES DE RATE LIMITING
# ===========================

def test_rate_limiter():
    """Testar rate limiting"""
    from rate_limiter import rate_limiter

    if not rate_limiter.enabled:
        print("⚠️  Rate limiter desabilitado, skip")
        return

    ip = "192.168.1.100"
    endpoint = "/api/v1/agents/register"

    # Reset
    rate_limiter.reset(ip, endpoint)

    # Primeira requisição deve passar
    allowed, info = rate_limiter.is_allowed(ip, endpoint)
    assert allowed is True

    # Múltiplas requisições devem passar até o limite
    for _ in range(99):
        allowed, _ = rate_limiter.is_allowed(ip, endpoint)
        assert allowed is True

    # Requisição além do limite deve falhar
    allowed, info = rate_limiter.is_allowed(ip, endpoint)
    assert allowed is False
    assert info["rate_limit_exceeded"] is True

    print("✓ Testes de Rate Limiter passaram")

# ===========================
# TESTES DE CACHE
# ===========================

@pytest.mark.asyncio
async def test_cache():
    """Testar cache Redis"""
    from cache import cache, CacheKeys

    if not cache.enabled:
        print("⚠️  Redis cache desabilitado, skip")
        return

    # Testar SET/GET
    test_key = CacheKeys.agent_data("test-agent")
    test_value = {"agent_id": "test-agent", "status": "online"}

    # Armazenar
    result = await cache.set(test_key, test_value, ttl=10)
    assert result is True

    # Recuperar
    retrieved = await cache.get(test_key)
    assert retrieved == test_value

    # Deletar
    result = await cache.delete(test_key)
    assert result is True

    # Verificar que foi deletado
    retrieved = await cache.get(test_key)
    assert retrieved is None

    print("✓ Testes de Cache passaram")

# ===========================
# TESTES DE DEAD LETTER QUEUE
# ===========================

def test_dlq():
    """Testar Dead Letter Queue"""
    from dlq import dlq

    if not dlq.enabled:
        print("⚠️  DLQ desabilitada, skip")
        return

    # Adicionar mensagem
    message = {"event": "test_event", "data": "test"}
    error = "Test error"
    context = {"agent_id": "test-001"}

    result = dlq.add(message, error, context, retry_count=0)
    assert result is True

    # Obter estatísticas
    stats = dlq.get_stats()
    assert stats["total"] > 0

    # Obter pendentes
    pending = dlq.get_pending(limit=1)
    assert len(pending) > 0

    # Remover
    if pending:
        result = dlq.remove(pending[0]["timestamp"])
        assert result is True

    print("✓ Testes de DLQ passaram")

# ===========================
# TESTES DE RETRY
# ===========================

@pytest.mark.asyncio
async def test_retry_handler():
    """Testar retry handler"""
    from retry import RetryHandler, RetryConfig

    call_count = 0

    async def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Temporary error")
        return "Success"

    # Testar retry bem-sucedido
    config = RetryConfig(max_attempts=5)
    result = await RetryHandler.execute_with_retry(
        flaky_function,
        config=config
    )

    assert result == "Success"
    assert call_count == 3

    # Testar retry que falha
    async def failing_function():
        raise Exception("Permanent error")

    result = await RetryHandler.execute_with_retry(
        failing_function,
        config=RetryConfig(max_attempts=2)
    )

    assert result is None

    print("✓ Testes de Retry Handler passaram")

# ===========================
# TESTES DE HEALTH CHECK
# ===========================

def test_health_check():
    """Testar health checks"""
    from health import health_check

    # Health check geral
    status = health_check.check_system()
    assert status["status"] in ["healthy", "degraded", "unhealthy"]
    assert "timestamp" in status
    assert "checks" in status

    # Health check database
    db_status = health_check.check_database()
    assert "status" in db_status

    # Health check cache
    cache_status = health_check.check_cache()
    assert "status" in cache_status

    print("✓ Testes de Health Check passaram")

# ===========================
# TESTES DE MÉTRICAS
# ===========================

def test_metrics_collector():
    """Testar coletor de métricas"""
    from health import metrics_collector

    # Registrar requisições
    metrics_collector.record_request(success=True)
    metrics_collector.record_request(success=True)
    metrics_collector.record_request(success=False)

    # Obter métricas
    metrics = metrics_collector.get_metrics()

    assert metrics["requests"]["total"] >= 3
    assert metrics["requests"]["success"] >= 2
    assert metrics["requests"]["errors"] >= 1
    assert metrics["requests"]["success_rate"] >= 0

    print("✓ Testes de Metrics Collector passaram")

# ===========================
# TESTES DE MODELOS
# ===========================

def test_pydantic_models():
    """Testar modelos Pydantic"""
    from models import LoginRequest, PaginationParams, StandardResponse

    # Testar LoginRequest
    login = LoginRequest(username="testuser", password="password123")
    assert login.username == "testuser"

    # Testar validação de tamanho mínimo
    with pytest.raises(ValueError):
        LoginRequest(username="", password="password")

    # Testar PaginationParams
    params = PaginationParams(page=2, page_size=50)
    assert params.offset == 50
    assert params.limit == 50

    # Testar StandardResponse
    response = StandardResponse(
        status="success",
        data={"key": "value"}
    )
    assert response.status == "success"

    print("✓ Testes de Modelos Pydantic passaram")

# ===========================
# EXECUTAR TESTES
# ===========================

def run_all_tests():
    """Executar todos os testes"""
    print("\n" + "="*60)
    print("🧪 EXECUTANDO TESTES DOS COMPONENTES")
    print("="*60 + "\n")

    try:
        # Testes síncronos
        test_password_manager()
        test_jwt_handler()
        test_login_attempt_tracker()
        test_rate_limiter()
        test_dlq()
        test_health_check()
        test_metrics_collector()
        test_pydantic_models()

        # Testes assíncronos
        asyncio.run(test_cache())
        asyncio.run(test_retry_handler())

        print("\n" + "="*60)
        print("✅ TODOS OS TESTES PASSARAM!")
        print("="*60 + "\n")

    except Exception as e:
        print(f"\n❌ TESTE FALHOU: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_all_tests()
