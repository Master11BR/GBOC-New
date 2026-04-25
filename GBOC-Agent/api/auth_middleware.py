#!/usr/bin/env python3
"""
GBOC Agent - Authentication + Rate Limiting Middleware
Protects all routes except login, static assets, and public endpoints.
Global API rate limiting per IP.
"""

from fastapi import Request
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {
    '/api/auth/login',
    '/api/auth/status',
    '/api/auth/setup',
    '/api/auth/logout',
    '/api/auth/password-policy',
    '/login.html',
    '/favicon.ico',
    '/.well-known/appspecific/com.chrome.devtools.json',
    '/metrics',
}

PUBLIC_PREFIXES = [
    '/static/',
]

# ── Global Rate Limiting ──────────────────────────────────────────

_api_requests: dict = defaultdict(list)   # ip -> [timestamps]
API_RATE_LIMIT_WINDOW = 60    # 1 minute window
API_RATE_LIMIT_MAX = 200      # 200 requests per minute per IP


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        client_ip = request.client.host if request.client else 'unknown'

        # ── Rate limiting (API calls only) ────────────────────────
        if path.startswith('/api/'):
            now = time.time()
            bucket = _api_requests[client_ip]
            # Purge old entries
            _api_requests[client_ip] = [t for t in bucket if now - t < API_RATE_LIMIT_WINDOW]
            if len(_api_requests[client_ip]) >= API_RATE_LIMIT_MAX:
                remaining = int(API_RATE_LIMIT_WINDOW - (now - _api_requests[client_ip][0]))
                return JSONResponse(
                    {"status": "error", "message": f"Rate limit excedido. Tente em {remaining}s.", "code": "RATE_LIMITED"},
                    status_code=429,
                    headers={"Retry-After": str(remaining), "X-RateLimit-Limit": str(API_RATE_LIMIT_MAX)}
                )
            _api_requests[client_ip].append(now)

        # ── Public paths (no auth) ───────────────────────────────
        if path in PUBLIC_PATHS:
            return await call_next(request)

        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        try:
            from api.auth import is_auth_enabled, get_current_user

            # Se ainda não há usuário configurado, manter apenas tela/login setup e estáticos públicos.
            # Isso força a abertura da tela de login/setup no startup.
            if not is_auth_enabled():
                if path.startswith('/api/'):
                    return JSONResponse(
                        {"status": "error", "message": "Configuração inicial necessária", "code": "AUTH_SETUP_REQUIRED"},
                        status_code=401
                    )
                return RedirectResponse(url='/login.html', status_code=302)

            user = get_current_user(request)
            if user:
                request.state.user = user
                return await call_next(request)

            if path.startswith('/api/'):
                return JSONResponse(
                    {"status": "error", "message": "Autenticação necessária", "code": "AUTH_REQUIRED"},
                    status_code=401
                )
            else:
                return RedirectResponse(url='/login.html', status_code=302)

        except Exception as e:
            logger.error(f"Auth middleware error: {e}")
            return await call_next(request)
