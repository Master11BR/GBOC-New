#!/usr/bin/env python3
"""
GBOC Agent - Endpoint MCP (Streamable HTTP, JSON-RPC 2.0)

URL: http(s)://<agente>:9200/api/mcp   ·   Authorization: Bearer gboc_mcp_...
A lógica do protocolo e as ferramentas ficam em engines/mcp_server.py.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["MCP Server"])


def _role_for(request: Request) -> tuple[str | None, str]:
    user = getattr(request.state, "user", None) or {}
    if user.get("via") == "mcp-token":
        return user.get("username"), user.get("role") or "read"
    # Sessão web (teste pela tela): administradores operam, demais só consultam
    try:
        from api.ai_api import _get_user_role, ADMIN_ROLES
        role = (_get_user_role(user.get("user_id")) or "").lower()
        return user.get("username") or "sessao-web", "operate" if role in ADMIN_ROLES else "read"
    except Exception:
        return user.get("username") or "sessao-web", "read"


def _origin_ok(request: Request) -> bool:
    """Proteção contra DNS rebinding para chamadas de navegador (com cookie de sessão)."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    user = getattr(request.state, "user", None) or {}
    if user.get("via") == "mcp-token":
        return True
    return (urlparse(origin).netloc or "").lower() == (request.headers.get("host") or "").lower()


@router.post("")
@router.post("/")
async def mcp_endpoint(request: Request):
    from engines import mcp_server
    if not mcp_server.mcp_enabled():
        return JSONResponse({"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32000, "message": "Servidor MCP desativado nas configurações de IA do Agente."}},
                            status_code=403)
    if not _origin_ok(request):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "Origem não permitida."}},
                            status_code=403)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido."}},
                            status_code=400)
    username, role = _role_for(request)
    ctx = {"user": username or "mcp", "role": role, "ip": request.client.host if request.client else None}
    app = request.app

    if isinstance(body, list):
        if not body:
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Lote vazio."}},
                                status_code=400)
        out = []
        for m in body:
            r = await mcp_server.handle_message(app, m, ctx)
            if r is not None:
                out.append(r)
        return JSONResponse(out) if out else Response(status_code=202)

    r = await mcp_server.handle_message(app, body, ctx)
    if r is None:
        return Response(status_code=202)
    return JSONResponse(r)


@router.get("")
@router.get("/")
async def mcp_get():
    # Sem stream SSE iniciado pelo servidor: o cliente usa somente POST (permitido pela especificação).
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("")
@router.delete("/")
async def mcp_delete():
    return Response(status_code=405, headers={"Allow": "POST"})
