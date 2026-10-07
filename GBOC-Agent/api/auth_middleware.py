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
    '/api/v1/auth/login',
    '/api/v1/auth/status',
    '/api/v1/auth/setup',
    '/api/v1/auth/logout',
    '/api/v1/auth/password-policy',
    '/api/v1/version',
    '/api/v1/system/version',
    '/api/v2/system/version',
    '/api/system/info',
    '/api/system/version',
    '/api/server/status',
    '/api/system/hardware',
    '/api/v1/system/hardware',
    '/api/v2/system/hardware',
    '/login.html',
    '/favicon.ico',
    '/.well-known/appspecific/com.chrome.devtools.json',
    '/metrics',
}

PUBLIC_PREFIXES = [
    '/static/',
]

# Rotas chamadas pelo GBOC Server (outra máquina, sem sessão de usuário):
# antes eram públicas — agora exigem a chave de pareamento (X-GBOC-Agent-Key)
# ou uma sessão válida. Ver core/agent_pairing.py.
SERVER_CALLABLE_PREFIXES = [
    '/api/v1/rmm/',
    '/api/rmm/',
    '/api/ransomware/',
    '/api/v2/',
    '/api/v1/diagnostics/',
    '/api/diagnostics/',
    '/api/preemptive/',
    '/api/integrity/',
    '/api/duplicati-native/',
    '/api/advanced-stats/',
    '/api/v1/power-tools/',
    '/api/power-tools/',
]

# Shutdown: liberado sem sessão apenas para o script local (loopback).
LOOPBACK_PATHS = {'/api/system/shutdown', '/api/v1/system/shutdown'}
_LOOPBACK_HOSTS = {'127.0.0.1', '::1', 'localhost', 'testclient'}

# ── Global Rate Limiting ──────────────────────────────────────────

import os

_api_requests: dict = defaultdict(list)   # chave (sessão ou IP) -> [timestamps]
API_RATE_LIMIT_WINDOW = 60    # 1 minute window
# Cada tela dispara 10–30 chamadas (mais o polling); 200/min por IP gerava HTTP 429 ao
# navegar e para vários usuários atrás do mesmo NAT. Agora o limite vale por sessão
# (cookie/Bearer) ou, sem sessão, por IP. Ajustável por GBOC_API_RATE_LIMIT.
API_RATE_LIMIT_MAX = int(os.getenv("GBOC_API_RATE_LIMIT", "1200") or 1200)
API_RATE_LIMIT_ANON_MAX = int(os.getenv("GBOC_API_RATE_LIMIT_ANON", "300") or 300)


def _is_server_call(request: Request) -> bool:
    if not request.headers.get("X-GBOC-Agent-Key"):
        return False
    try:
        from core.agent_pairing import request_has_valid_server_key
        return request_has_valid_server_key(request.headers)
    except Exception:
        return False


def _rate_key(request: Request, client_ip: str):
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else (request.cookies.get("gboc_token") or "")
    if token:
        return "s:" + token[-24:], API_RATE_LIMIT_MAX
    return "ip:" + client_ip, API_RATE_LIMIT_ANON_MAX


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        client_ip = request.client.host if request.client else 'unknown'

        # ── Rate limiting (API calls only) ────────────────────────
        # O GBOC Server (chave de pareamento) não entra no limite: ele consulta vários
        # endpoints do agente a partir de um único IP.
        if path.startswith('/api/') and not _is_server_call(request):
            now = time.time()
            rkey, rmax = _rate_key(request, client_ip)
            bucket = [t for t in _api_requests.get(rkey, ()) if now - t < API_RATE_LIMIT_WINDOW]
            if len(bucket) >= rmax:
                _api_requests[rkey] = bucket
                remaining = max(1, int(API_RATE_LIMIT_WINDOW - (now - bucket[0])))
                return JSONResponse(
                    {"status": "error", "message": f"Rate limit excedido. Tente em {remaining}s.", "code": "RATE_LIMITED"},
                    status_code=429,
                    headers={"Retry-After": str(remaining), "X-RateLimit-Limit": str(rmax)}
                )
            bucket.append(now)
            _api_requests[rkey] = bucket
            if len(_api_requests) > 5000:   # evita crescimento ilimitado (tokens/IPs antigos)
                for k in [k for k, v in _api_requests.items() if not v or now - v[-1] > API_RATE_LIMIT_WINDOW]:
                    _api_requests.pop(k, None)

        # ── Public paths (no auth) ───────────────────────────────
        if path in PUBLIC_PATHS:
            return await call_next(request)

        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        if path in LOOPBACK_PATHS and client_ip in _LOOPBACK_HOSTS:
            return await call_next(request)

        # Chamada do GBOC Server autenticada pela chave de pareamento (qualquer rota protegida,
        # pois o proxy RMM do Server repassa subcaminhos arbitrários).
        # A autenticação é decidida primeiro; a rota roda FORA do try. Antes, uma exceção
        # dentro da rota virava "Serviço de autenticação indisponível" (503) ou 401.
        if _is_server_call(request):
            request.state.user = {"username": "gboc-server", "role": "server", "via": "pairing-key"}
            return await call_next(request)

        try:
            from api.auth import is_auth_enabled, get_current_user
            from starlette.concurrency import run_in_threadpool

            # Se ainda não há usuário configurado, manter apenas tela/login setup e estáticos públicos.
            # Isso força a abertura da tela de login/setup no startup.
            if not await run_in_threadpool(is_auth_enabled):
                if path.startswith('/api/'):
                    return JSONResponse(
                        {"status": "error", "message": "Configuração inicial necessária", "code": "AUTH_SETUP_REQUIRED"},
                        status_code=401
                    )
                return RedirectResponse(url='/login.html', status_code=302)

            # Consulta ao banco fora do event loop (não trava as demais requisições)
            user = await run_in_threadpool(get_current_user, request)
        except Exception as e:
            # Fail-closed: erro na validação de sessão não pode liberar acesso a rotas protegidas.
            logger.error(f"Auth middleware error: {e}")
            if path.startswith('/api/'):
                return JSONResponse(
                    {"status": "error", "message": "Serviço de autenticação indisponível", "code": "AUTH_UNAVAILABLE"},
                    status_code=503
                )
            return RedirectResponse(url='/login.html', status_code=302)

        if user:
            request.state.user = user
            return await call_next(request)

        if path.startswith('/api/'):
            return JSONResponse(
                {"status": "error", "message": "Autenticação necessária", "code": "AUTH_REQUIRED"},
                status_code=401
            )
        return RedirectResponse(url='/login.html', status_code=302)
