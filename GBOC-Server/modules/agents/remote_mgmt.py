"""
GBOC Server — Gerenciamento Remoto de Agentes.

Canal de comandos Server → Agente com dois caminhos:
  1. WebSocket aberto pelo próprio agente (preferencial: funciona com o agente atrás de NAT,
     firewall ou em outra rede, sem abrir portas no cliente);
  2. HTTP direto para IP:porta do agente (quando o WebSocket não está conectado).

Ambos usam a chave de pareamento; o Agente aplica as mesmas validações da sua interface.

Rotas:
  GET  /api/v1/agents/{agent_id}/remote/status          — resumo (canais, saúde, sincronização)
  ANY  /api/v1/agents/{agent_id}/remote/api/{path}       — chamada à API do agente (path começa com api/)
Ações que alteram algo (POST/PUT/DELETE) exigem perfil admin/operator e ficam na auditoria.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger("gboc_remote_mgmt")
router = APIRouter(prefix="/api/v1/agents", tags=["Gerenciamento Remoto"])

_WRITE_ROLES = ("admin", "superadmin", "administrator", "operator")
_BLOCKED = ("api/system/shutdown", "api/v1/system/shutdown")


def _manager():
    try:
        from server_gboc import manager
    except ImportError:
        from gboc_server import manager
    return manager


def split_host_port(value: Optional[str], default_port: int = 9200) -> Tuple[Optional[str], int]:
    """'10.0.0.5:9200' → ('10.0.0.5', 9200); '[fe80::1]:9200' e IPv6 sem porta também são aceitos."""
    v = (value or "").strip()
    if not v:
        return None, default_port
    if v.startswith("["):
        host, _, rest = v[1:].partition("]")
        port = rest.lstrip(":")
        return host, int(port) if port.isdigit() else default_port
    if v.count(":") == 1:
        host, port = v.split(":")
        return host, int(port) if port.isdigit() else default_port
    return v, default_port


def _agent_row(agent_id: str) -> Optional[Dict[str, Any]]:
    from database import db_manager
    from psycopg2.extras import RealDictCursor
    conn = db_manager.get_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT agent_id, hostname, ip_address, os_info, agent_version, status, last_heartbeat, registered_at,
                              cpu_usage, ram_usage, disk_usage, tenant_id FROM agents WHERE agent_id=%s""", (agent_id,))
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        db_manager.release_connection(conn)


async def agent_call(agent_id: str, method: str, path: str, query: Optional[Dict[str, Any]] = None,
                     body: Any = None, timeout: float = 30.0) -> Dict[str, Any]:
    """Executa uma chamada na API do agente. Retorna {status_code, body, content_type, channel}."""
    path = path.lstrip("/")
    mgr = _manager()
    errors = []
    if agent_id in mgr.active_connections:
        try:
            res = await mgr.request(agent_id, {"type": "command", "command": "api_request",
                                               "data": {"method": method, "path": path, "query": query or {}, "body": body,
                                                        "timeout": timeout}}, timeout=timeout + 5)
            return {"status_code": int(res.get("status_code") or 502), "body": res.get("body"),
                    "content_type": res.get("content_type") or "application/json", "channel": "websocket"}
        except asyncio.TimeoutError:
            errors.append("WebSocket: o agente não respondeu a tempo")
        except Exception as e:
            errors.append(f"WebSocket: {e}")
    row = await asyncio.to_thread(_agent_row, agent_id)
    host, port = split_host_port((row or {}).get("ip_address"))
    if host:
        from modules.agents.agent_pairing import agent_headers
        headers = {"Content-Type": "application/json", **agent_headers()}
        for scheme in ("http", "https"):
            try:
                async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                    r = await client.request(method, f"{scheme}://{host}:{port}/{path}", params=query or None,
                                             content=json.dumps(body) if body is not None else None, headers=headers)
                ctype = r.headers.get("content-type", "")
                try:
                    data = r.json() if "json" in ctype else r.text
                except ValueError:
                    data = r.text
                return {"status_code": r.status_code, "body": data, "content_type": ctype, "channel": "http"}
            except Exception as e:
                errors.append(f"HTTP {scheme}://{host}:{port}: {type(e).__name__}")
    else:
        errors.append("Agente sem endereço IP registrado")
    return {"status_code": 503, "channel": None, "content_type": "application/json",
            "body": {"status": "error", "code": "AGENT_UNREACHABLE",
                     "message": "Agente inacessível. " + " · ".join(errors) +
                                ". Verifique se o serviço do agente está ativo e conectado ao Server (WebSocket)."}}


def _audit(request: Request, agent_id: str, action: str, ok: bool, details: str) -> None:
    try:
        from database import db_manager
        user = getattr(request.state, "user", None) or {}
        conn = db_manager.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO server_auth_audit (user_id, username, action, ip_address, details) VALUES (%s, %s, %s, %s, %s)",
                        (user.get("id"), user.get("username"), f"remote.{action}" + ("" if ok else ".fail"),
                         request.client.host if request.client else None, f"agente={agent_id} {details}"[:1000]))
            conn.commit()
            cur.close()
        finally:
            db_manager.release_connection(conn)
    except Exception as e:
        logger.debug(f"auditoria remota: {e}")


@router.get("/{agent_id}/remote/status")
async def remote_status(agent_id: str):
    row = await asyncio.to_thread(_agent_row, agent_id)
    if not row:
        return JSONResponse({"status": "error", "message": "Agente não encontrado"}, status_code=404)
    mgr = _manager()
    ws = agent_id in mgr.active_connections
    health, server = await asyncio.gather(agent_call(agent_id, "GET", "api/v1/system/health", timeout=15),
                                          agent_call(agent_id, "GET", "api/server/status", timeout=15))
    for k, v in list(row.items()):
        if hasattr(v, "isoformat"):
            row[k] = v.isoformat()
    host, port = split_host_port(row.get("ip_address"))
    return {"status": "success", "agent": row, "address": {"host": host, "port": port},
            "channels": {"websocket": ws, "reachable": health["status_code"] < 500, "used": health.get("channel")},
            "health": health["body"] if health["status_code"] < 400 else None,
            "health_error": None if health["status_code"] < 400 else health["body"],
            "server_link": server["body"] if server["status_code"] < 400 else None}


@router.api_route("/{agent_id}/remote/api/{subpath:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def remote_api(agent_id: str, subpath: str, request: Request):
    path = subpath.lstrip("/")
    if not path.startswith("api/") or ".." in path:
        return JSONResponse({"status": "error", "message": "Somente rotas da API do agente (api/...)"}, status_code=400)
    if path.rstrip("/") in _BLOCKED:
        return JSONResponse({"status": "error", "message": "Desligamento remoto do agente não é permitido."}, status_code=403)
    method = request.method.upper()
    if method != "GET":
        role = ((getattr(request.state, "user", None) or {}).get("role") or "").lower()
        if role not in _WRITE_ROLES:
            return JSONResponse({"status": "error", "code": "FORBIDDEN",
                                 "message": "Seu perfil não pode executar ações remotas (requer admin ou operator)."}, status_code=403)
    raw = await request.body()
    body = None
    if raw:
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            return JSONResponse({"status": "error", "message": "Corpo JSON inválido"}, status_code=400)
    res = await agent_call(agent_id, method, path, query=dict(request.query_params), body=body,
                           timeout=120.0 if method != "GET" else 45.0)
    if method != "GET":
        await asyncio.to_thread(_audit, request, agent_id, f"{method} /{path}", res["status_code"] < 400,
                                f"canal={res.get('channel')} status={res['status_code']}")
    headers = {"X-GBOC-Channel": res.get("channel") or "none"}
    b = res["body"]
    if isinstance(b, (dict, list)):
        return JSONResponse(b, status_code=res["status_code"], headers=headers)
    return Response(content=str(b or ""), status_code=res["status_code"], media_type=res.get("content_type") or "text/plain",
                    headers=headers)
