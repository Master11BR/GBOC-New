"""
GBOC Server — Guarda global de autenticação das rotas /api/.

Regras (fail-closed):
  * Rotas públicas: login/setup/status/logout/OAuth, versão e ui-config.
  * Rotas de ingestão de agentes (heartbeat, sync, relatórios): exigem a chave de
    pareamento (X-GBOC-Agent-Key) OU uma sessão de usuário válida.
  * Shutdown: loopback (script local) ou sessão — o próprio endpoint ainda exige admin.
  * Todas as demais rotas /api/: sessão de usuário válida.
Páginas HTML e estáticos continuam livres; as próprias páginas redirecionam ao login.
"""
import logging
import re
import threading
import time
from typing import Callable, Optional

from starlette.concurrency import run_in_threadpool

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("gboc_auth_guard")

PUBLIC_EXACT = {
    "/api/v1/auth/login",
    "/api/v1/auth/setup",
    "/api/v1/auth/status",
    "/api/v1/auth/logout",
    "/api/v1/version",
    "/api/system/version",
    "/api/v1/system/version",
    "/api/v2/system/version",
    "/api/v1/system/ui-config",
    "/api/v2/system/ui-config",
    "/api/v1/jobs/failed",
    "/api/v1/enroll",
}
PUBLIC_PREFIXES = ("/api/v1/auth/oauth/",
                   # Instalação em massa: autenticadas pelo token de instalação (validado na própria rota)
                   "/api/v1/enroll/")

AGENT_EXACT = {
    "/api/v1/agents/register",
    "/api/v1/agents/heartbeat",
    "/api/v1/agents/alert",
    "/api/v1/agents/full-sync",
    "/api/v1/agents/manual-sync",
    "/api/v1/agents/pairing/check",
    "/api/v1/backups/report",
    "/api/v1/server/jobs/report",
    "/api/v1/server/ransomware/sync",
}
AGENT_PREFIXES = ("/api/v1/sync/",)
AGENT_PATTERNS = (
    re.compile(r"^/api/v1/agents/[^/]+/repositories$"),
    re.compile(r"^/api/v1/server/(power-tools|hermes)/agents/[^/]+/stats$"),
)
LOOPBACK_EXACT = {"/api/system/shutdown", "/api/v1/system/shutdown"}
# Perfil "client" (Portal do Cliente): só acessa o portal (dados forçados à própria organização)
CLIENT_ALLOWED_PREFIXES = ("/api/v1/portal/",)
CLIENT_ALLOWED_EXACT = {"/api/v1/auth/status", "/api/v1/auth/logout", "/api/v1/auth/change-password", "/api/v1/version"}
CLIENT_PAGES_ALLOWED = ("/portal.html", "/login.html", "/login")


def client_blocked(user: Optional[dict], path: str) -> bool:
    if not user or str(user.get("role") or "").lower() != "client":
        return False
    return not (path in CLIENT_ALLOWED_EXACT or path.startswith(CLIENT_ALLOWED_PREFIXES))
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def classify(path: str) -> str:
    """Retorna 'public' | 'agent' | 'loopback' | 'user' para um caminho /api/."""
    if path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES):
        return "public"
    if path in AGENT_EXACT or path.startswith(AGENT_PREFIXES) or any(p.match(path) for p in AGENT_PATTERNS):
        return "agent"
    if path in LOOPBACK_EXACT:
        return "loopback"
    return "user"


def _deny(code: str, message: str, status: int = 401) -> JSONResponse:
    return JSONResponse({"status": "error", "code": code, "message": message}, status_code=status)


# Cache curto de sessões válidas: evita uma consulta ao PostgreSQL por requisição
# (o dashboard dispara dezenas de chamadas em paralelo ao abrir).
_SESSION_TTL = 15.0
_session_cache: dict = {}
_session_lock = threading.Lock()


def _token_of(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.cookies.get("gboc_server_token", "") or ""


def invalidate_session_cache(token: Optional[str] = None) -> None:
    with _session_lock:
        if token:
            _session_cache.pop(token, None)
        else:
            _session_cache.clear()


def install(app, get_user: Callable[[Request], Optional[dict]], auth_enabled: Callable[[], bool]) -> None:
    """Registra o middleware no app FastAPI."""
    from modules.agents.agent_pairing import request_has_valid_agent_key

    async def _cached_user(request: Request) -> Optional[dict]:
        token = _token_of(request)
        if not token:
            return None
        now = time.monotonic()
        with _session_lock:
            hit = _session_cache.get(token)
            if hit and now - hit[0] < _SESSION_TTL:
                return hit[1]
        # Consulta síncrona ao banco fora do event loop (não trava as demais requisições)
        user = await run_in_threadpool(get_user, request)
        with _session_lock:
            if user:
                if len(_session_cache) > 2000:
                    _session_cache.clear()
                _session_cache[token] = (now, user)
            else:
                _session_cache.pop(token, None)
        return user

    @app.middleware("http")
    async def _gboc_client_pages(request: Request, call_next):
        """Usuário do Portal do Cliente que abre o painel/páginas internas é levado ao portal."""
        path = request.url.path
        if request.method == "GET" and not path.startswith("/api/") and (path == "/" or path.endswith(".html")) \
                and not path.startswith(CLIENT_PAGES_ALLOWED) and _token_of(request):
            try:
                user = await _cached_user(request)
            except Exception:
                user = None
            if user and str(user.get("role") or "").lower() == "client":
                from fastapi.responses import RedirectResponse
                return RedirectResponse("/portal.html", status_code=302)
        return await call_next(request)

    @app.middleware("http")
    async def _gboc_auth_guard(request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or not path.startswith("/api/"):
            return await call_next(request)

        kind = classify(path)
        if kind == "public":
            return await call_next(request)

        try:
            if kind == "agent" and await run_in_threadpool(request_has_valid_agent_key, request.headers):
                return await call_next(request)

            if kind == "loopback":
                host = request.client.host if request.client else ""
                if host in _LOOPBACK_HOSTS:
                    return await call_next(request)

            user = await _cached_user(request)
            if user:
                if client_blocked(user, path):
                    return _deny("PORTAL_ONLY", "Seu acesso é ao Portal do Cliente.", 403)
                request.state.user = user
                response = await call_next(request)
                # Alteração de usuários/perfis/senhas: sessões em cache precisam ser revalidadas
                if request.method != "GET" and path.startswith(("/api/v1/auth/users", "/api/v1/users", "/api/v1/auth/change-password")):
                    invalidate_session_cache()
                return response

            if kind == "agent":
                host = request.client.host if request.client else "?"
                logger.warning(f"[AUTH] Agente rejeitado ({host} {path}): chave de pareamento ausente ou inválida.")
                try:   # aparece em Jobs com Falha / Alertas (o agente não consegue sincronizar nada)
                    from modules.job_alert.failures import note_rejection
                    note_rejection(request.headers.get("X-GBOC-Agent-Id"), host, path)
                except Exception:
                    pass
                return _deny("AGENT_KEY_INVALID",
                             "Chave de pareamento do agente ausente ou inválida. Configure-a no Agente "
                             "(Configurações > Servidor Central).")
            if not await run_in_threadpool(auth_enabled):
                return _deny("AUTH_SETUP_REQUIRED", "Configuração inicial necessária")
            return _deny("AUTH_REQUIRED", "Autenticação necessária")
        except Exception as exc:  # fail-closed
            logger.error(f"[AUTH] Erro no guarda de autenticação: {exc}")
            return _deny("AUTH_UNAVAILABLE", "Serviço de autenticação indisponível", 503)
