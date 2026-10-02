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
from typing import Callable, Optional

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
    "/api/v1/server/jobs/failed",
}
PUBLIC_PREFIXES = ("/api/v1/auth/oauth/",)

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


def install(app, get_user: Callable[[Request], Optional[dict]], auth_enabled: Callable[[], bool]) -> None:
    """Registra o middleware no app FastAPI."""
    from modules.agents.agent_pairing import request_has_valid_agent_key

    @app.middleware("http")
    async def _gboc_auth_guard(request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or not path.startswith("/api/"):
            return await call_next(request)

        kind = classify(path)
        if kind == "public":
            return await call_next(request)

        try:
            if kind == "agent" and request_has_valid_agent_key(request.headers):
                return await call_next(request)

            if kind == "loopback":
                host = request.client.host if request.client else ""
                if host in _LOOPBACK_HOSTS:
                    return await call_next(request)

            user = get_user(request)
            if user:
                request.state.user = user
                return await call_next(request)

            if kind == "agent":
                host = request.client.host if request.client else "?"
                logger.warning(f"[AUTH] Agente rejeitado ({host} {path}): chave de pareamento ausente ou inválida.")
                return _deny("AGENT_KEY_INVALID",
                             "Chave de pareamento do agente ausente ou inválida. Configure-a no Agente "
                             "(Configurações > Servidor Central).")
            if not auth_enabled():
                return _deny("AUTH_SETUP_REQUIRED", "Configuração inicial necessária")
            return _deny("AUTH_REQUIRED", "Autenticação necessária")
        except Exception as exc:  # fail-closed
            logger.error(f"[AUTH] Erro no guarda de autenticação: {exc}")
            return _deny("AUTH_UNAVAILABLE", "Serviço de autenticação indisponível", 503)
