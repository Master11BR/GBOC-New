"""
GBOC Server - Middlewares e Decoradores
Middlewares para autenticação, rate limiting, logging e error handling
"""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from typing import Callable, Optional
from functools import wraps
from datetime import datetime, timezone
import json
from config import API_VERSION
from logger import setup_logger, log_with_context
from rate_limiter import rate_limiter
from auth import JWTHandler, TokenManager
from models import ErrorResponse
from health import metrics_collector

logger = setup_logger(__name__)

# ===========================
# MIDDLEWARE
# ===========================

class AuthenticationMiddleware:
    """Middleware para autenticação JWT"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, request: Request, call_next: Callable):
        # Rotas públicas que não precisam de autenticação
        public_routes = [
            "/api/v1/auth/login",
            "/api/v1/auth/setup",
            "/api/v1/auth/status",
            "/api/v1/agents/register",
            "/ws/",
            "/health",
            "/metrics",
            "/docs",
            "/openapi.json"
        ]

        # Verificar se é rota pública
        if any(request.url.path.startswith(route) for route in public_routes):
            return await call_next(request)

        # Verificar token
        token = self._extract_token(request)
        if not token:
            return JSONResponse(
                status_code=401,
                content={"status": "error", "message": "Token não fornecido"}
            )

        # Validar token
        payload = JWTHandler.verify_token(token)
        if not payload or TokenManager.is_token_revoked(token):
            return JSONResponse(
                status_code=401,
                content={"status": "error", "message": "Token inválido ou expirado"}
            )

        # Adicionar ao request
        request.state.user = payload
        request.state.token = token

        return await call_next(request)

    @staticmethod
    def _extract_token(request: Request) -> Optional[str]:
        """Extrai token do header Authorization ou cookie"""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]

        return request.cookies.get("access_token")

class RateLimitMiddleware:
    """Middleware para rate limiting"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, request: Request, call_next: Callable):
        # Obter IP do cliente
        client_ip = request.client.host if request.client else "unknown"

        # Verificar rate limit
        allowed, info = rate_limiter.is_allowed(client_ip, request.url.path)

        if not allowed:
            logger.warning(f"Rate limit excedido para {client_ip}")
            return JSONResponse(
                status_code=429,
                content={
                    "status": "error",
                    "message": "Muitas requisições. Tente novamente mais tarde.",
                    "retry_after": info.get("reset_in", 60)
                }
            )

        # Adicionar headers de rate limit
        response = await call_next(request)
        if isinstance(info, dict):
            response.headers["X-RateLimit-Limit"] = str(info.get("limit", 100))
            response.headers["X-RateLimit-Remaining"] = str(info.get("remaining", 0))

        return response

class LoggingMiddleware:
    """Middleware para logging de requisições"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, request: Request, call_next: Callable):
        start_time = datetime.now(timezone.utc)

        try:
            response = await call_next(request)

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            success = response.status_code < 400

            log_with_context(
                logger,
                "info" if success else "warning",
                f"{request.method} {request.url.path}",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration * 1000,
                client_ip=request.client.host if request.client else "unknown",
                success=success
            )

            metrics_collector.record_request(success=success)

            return response

        except Exception as e:
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.error(
                f"Erro em {request.method} {request.url.path}: {e}",
                exc_info=True
            )
            metrics_collector.record_request(success=False)
            raise

class CORSEnhancedMiddleware:
    """Middleware CORS melhorado com segurança"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, request: Request, call_next: Callable):
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response

# ===========================
# DECORADORES
# ===========================

def require_auth(func: Callable) -> Callable:
    """
    Decorador para exigir autenticação

    Uso:
        @require_auth
        async def my_endpoint(request: Request):
            user = request.state.user
    """
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        if not hasattr(request.state, "user") or not request.state.user:
            raise HTTPException(
                status_code=401,
                detail="Autenticação necessária"
            )
        return await func(request, *args, **kwargs)
    return wrapper

def require_role(*allowed_roles: str) -> Callable:
    """
    Decorador para exigir role específico

    Uso:
        @require_role("admin", "operator")
        async def my_endpoint(request: Request):
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            if not hasattr(request.state, "user"):
                raise HTTPException(status_code=401, detail="Token não fornecido")

            user_role = request.state.user.get("role")
            if user_role not in allowed_roles:
                raise HTTPException(
                    status_code=403,
                    detail=f"Role necessário: {', '.join(allowed_roles)}"
                )

            return await func(request, *args, **kwargs)
        return wrapper
    return decorator

def validate_model(model_class) -> Callable:
    """
    Decorador para validar modelo Pydantic

    Uso:
        @validate_model(MyModel)
        async def my_endpoint(data: MyModel):
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except ValueError as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Validação falhou: {str(e)}"
                )
        return wrapper
    return decorator

def handle_exceptions(func: Callable) -> Callable:
    """
    Decorador para tratamento de exceções

    Uso:
        @handle_exceptions
        async def my_endpoint():
            pass
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Erro não tratado em {func.__name__}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Erro interno do servidor"
            )
    return wrapper

# ===========================
# ERROR HANDLERS
# ===========================

async def generic_exception_handler(request: Request, exc: Exception):
    """Handler genérico para exceções"""
    logger.error(f"Exceção não tratada: {exc}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": "Erro interno do servidor",
            "error_code": "INTERNAL_ERROR",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )

async def http_exception_handler(request: Request, exc: HTTPException):
    """Handler para HTTPException"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "error": exc.detail,
            "error_code": f"HTTP_{exc.status_code}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )

async def validation_exception_handler(request: Request, exc: Exception):
    """Handler para erros de validação"""
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "error": "Erro de validação",
            "error_code": "VALIDATION_ERROR",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )
