#!/usr/bin/env python3
"""
GBOC Agent - Servidor MCP (Model Context Protocol)

Permite que clientes de IA (Claude Code/Desktop, Antigravity, Cursor, n8n, etc.) consultem e operem o
GBOC Agent por ferramentas padronizadas. Transporte: Streamable HTTP (JSON-RPC 2.0 via POST em /api/mcp).

Segurança:
  • Token MCP próprio (Authorization: Bearer gboc_mcp_...), gerado na tela de IA; guardado somente como hash SHA-256.
  • Perfil por token: "read" (somente consultas) ou "operate" (também executa/para tarefas e monta VeraCrypt).
  • As ferramentas chamam os endpoints reais do Agente dentro do próprio processo (sem duplicar regras de negócio)
    usando uma chave interna aleatória gerada a cada start (nunca sai da memória do processo).
  • Toda chamada de ferramenta é registrada no log e na trilha de auditoria.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import threading
from datetime import datetime
from typing import Any, Awaitable, Callable

logger = logging.getLogger("GBOC.MCP")

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
TOKEN_PREFIX = "gboc_mcp_"
MAX_TOOL_OUTPUT_CHARS = 60000

# Chave do loopback interno (ferramenta → endpoint do próprio Agente). Gerada por processo.
INTERNAL_KEY = secrets.token_urlsafe(48)
INTERNAL_HEADER = "X-GBOC-Internal-Key"
INTERNAL_USER_HEADER = "X-GBOC-Internal-User"

_lock = threading.RLock()
_schema_ok = False


def is_internal_key(value: str | None) -> bool:
    return bool(value) and hmac.compare_digest(str(value), INTERNAL_KEY)


# ──────────────────────────────────────────────────────────────────────────────
# Tokens MCP
# ──────────────────────────────────────────────────────────────────────────────

def _conn():
    global _schema_ok
    from engines.ai_rag import get_conn
    conn = get_conn()
    if not _schema_ok:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS mcp_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                token_hint TEXT,
                role TEXT NOT NULL DEFAULT 'read',
                created_at TEXT,
                created_by TEXT,
                last_used_at TEXT,
                use_count INTEGER DEFAULT 0,
                revoked INTEGER DEFAULT 0
            );
        """)
        conn.commit()
        _schema_ok = True
    return conn


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_token(name: str, role: str = "read", created_by: str | None = None) -> dict[str, Any]:
    role = role if role in ("read", "operate") else "read"
    name = (name or "").strip()[:80] or "Cliente MCP"
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    with _lock:
        conn = _conn()
        cur = conn.execute(
            "INSERT INTO mcp_tokens(name, token_hash, token_hint, role, created_at, created_by) VALUES(?,?,?,?,?,?)",
            (name, _hash_token(token), f"{token[:13]}…{token[-4:]}", role,
             datetime.now().isoformat(timespec="seconds"), created_by or ""),
        )
        conn.commit()
    return {"id": cur.lastrowid, "name": name, "role": role, "token": token,
            "message": "Copie o token agora: ele não será exibido novamente."}


def list_tokens() -> list[dict[str, Any]]:
    rows = _conn().execute(
        "SELECT id, name, token_hint, role, created_at, created_by, last_used_at, use_count, revoked "
        "FROM mcp_tokens ORDER BY id DESC").fetchall()
    return [dict(r) | {"revoked": bool(r["revoked"])} for r in rows]


def revoke_token(token_id: int) -> bool:
    with _lock:
        conn = _conn()
        cur = conn.execute("UPDATE mcp_tokens SET revoked=1 WHERE id=?", (int(token_id),))
        conn.commit()
        return cur.rowcount > 0


def authenticate_token(token: str) -> dict[str, Any] | None:
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    h = _hash_token(token)
    with _lock:
        conn = _conn()
        row = conn.execute("SELECT id, name, role, revoked FROM mcp_tokens WHERE token_hash=?", (h,)).fetchone()
        if not row or row["revoked"]:
            return None
        conn.execute("UPDATE mcp_tokens SET last_used_at=?, use_count=COALESCE(use_count,0)+1 WHERE id=?",
                     (datetime.now().isoformat(timespec="seconds"), row["id"]))
        conn.commit()
    return {"username": f"mcp:{row['name']}", "role": row["role"], "via": "mcp-token", "mcp_token_id": row["id"]}


def authenticate_mcp_request(headers) -> dict[str, Any] | None:
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    if auth.startswith("Bearer "):
        return authenticate_token(auth[7:].strip())
    return None


def mcp_enabled() -> bool:
    try:
        from engines.ai_diagnostic_engine import ai_diagnostic_engine
        return ai_diagnostic_engine.config.get("mcp_enabled", True) is not False
    except Exception:
        return True


# ──────────────────────────────────────────────────────────────────────────────
# Chamadas internas aos endpoints reais do Agente
# ──────────────────────────────────────────────────────────────────────────────

class ToolError(Exception):
    pass


async def _internal(app, method: str, path: str, user: str, json_body: Any = None, params: dict | None = None) -> Any:
    import httpx
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 0))
    async with httpx.AsyncClient(transport=transport, base_url="http://gboc-agent.internal", timeout=180.0) as client:
        resp = await client.request(method, path, json=json_body, params=params,
                                    headers={INTERNAL_HEADER: INTERNAL_KEY, INTERNAL_USER_HEADER: user})
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text[:4000]}
    if resp.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else None
        detail = detail or (data.get("message") if isinstance(data, dict) else None) or resp.text[:500]
        raise ToolError(f"HTTP {resp.status_code}: {detail}")
    return data


def _pick(items: Any, fields: tuple[str, ...]) -> Any:
    if isinstance(items, dict):
        for key in ("tasks", "items", "data", "results", "repositories", "alerts", "failures", "history", "executions"):
            if isinstance(items.get(key), list):
                return {**{k: v for k, v in items.items() if not isinstance(v, list)}, key: _pick(items[key], fields)}
        return items
    if isinstance(items, list):
        out = []
        for it in items:
            if isinstance(it, dict):
                out.append({k: it.get(k) for k in fields if k in it})
            else:
                out.append(it)
        return out
    return items


# ──────────────────────────────────────────────────────────────────────────────
# Ferramentas
# ──────────────────────────────────────────────────────────────────────────────

ToolFn = Callable[[Any, dict[str, Any], dict[str, Any]], Awaitable[Any]]
TOOLS: dict[str, dict[str, Any]] = {}


def tool(name: str, description: str, schema: dict[str, Any], role: str = "read", destructive: bool = False):
    def deco(fn: ToolFn):
        TOOLS[name] = {
            "fn": fn, "role": role,
            "def": {
                "name": name, "description": description,
                "inputSchema": {"type": "object", "properties": schema.get("properties", {}),
                                "required": schema.get("required", []), "additionalProperties": False},
                "annotations": {"readOnlyHint": role == "read", "destructiveHint": destructive,
                                "openWorldHint": False},
            },
        }
        return fn
    return deco


def _int_arg(args: dict[str, Any], key: str, default: int | None = None, lo: int = 1, hi: int = 10**9) -> int:
    v = args.get(key, default)
    if v is None:
        raise ToolError(f"Parâmetro obrigatório ausente: {key}")
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ToolError(f"Parâmetro '{key}' deve ser inteiro.")
    return max(lo, min(hi, v))


_TASK_FIELDS = ("id", "name", "engine", "repository_id", "repository_name", "repo_name", "source_paths", "enabled",
                "schedule_enabled", "schedule_cron", "last_run", "last_status", "status", "next_run", "veracrypt_config")


@tool("gboc_agent_status", "Resumo real do Agente GBOC: versão, host, saúde e tarefas em execução agora.", {})
async def _t_status(app, args, ctx):
    info = await _internal(app, "GET", "/api/system/info", ctx["user"])
    health = None
    try:
        health = await _internal(app, "GET", "/api/system/health", ctx["user"])
    except ToolError as e:
        health = {"error": str(e)}
    running = await _internal(app, "GET", "/api/tasks/running/live", ctx["user"])
    return {"system": info, "health": health, "running": running}


@tool("gboc_list_tasks", "Lista as tarefas (jobs) de backup com motor, agendamento e último status.", {})
async def _t_tasks(app, args, ctx):
    return _pick(await _internal(app, "GET", "/api/tasks/", ctx["user"]), _TASK_FIELDS)


@tool("gboc_task_history", "Histórico de execuções de uma tarefa (status, duração, volume, erro).",
      {"properties": {"task_id": {"type": "integer", "description": "ID da tarefa"},
                      "limit": {"type": "integer", "description": "Máximo de execuções (padrão 20)"}},
       "required": ["task_id"]})
async def _t_history(app, args, ctx):
    tid = _int_arg(args, "task_id")
    data = await _internal(app, "GET", f"/api/tasks/{tid}/history", ctx["user"],
                           params={"limit": _int_arg(args, "limit", 20, 1, 200)})
    return data


@tool("gboc_running_tasks", "Tarefas em execução agora, com progresso ao vivo.", {})
async def _t_running(app, args, ctx):
    return await _internal(app, "GET", "/api/tasks/running/live", ctx["user"])


@tool("gboc_recent_failures", "Falhas recentes de tarefas (job_failure_log): motivo, retentativas e resolução.",
      {"properties": {"limit": {"type": "integer", "description": "Máximo de falhas (padrão 30)"}}})
async def _t_failures(app, args, ctx):
    data = await _internal(app, "GET", "/api/v1/jobs/failed", ctx["user"])
    lim = _int_arg(args, "limit", 30, 1, 500)
    if isinstance(data, list):
        return data[:lim]
    if isinstance(data, dict):
        for k, v in list(data.items()):
            if isinstance(v, list):
                data[k] = v[:lim]
    return data


@tool("gboc_list_repositories", "Lista os repositórios de destino (tipo, motor, status).", {})
async def _t_repos(app, args, ctx):
    data = await _internal(app, "GET", "/api/repositories/", ctx["user"])
    return _pick(data, ("id", "name", "type", "engine", "path", "status", "enabled", "initialized",
                        "size_bytes", "snapshots_count", "last_backup", "updated_at"))


@tool("gboc_alerts", "Alertas recentes do Agente.",
      {"properties": {"limit": {"type": "integer", "description": "Máximo de alertas (padrão 30)"}}})
async def _t_alerts(app, args, ctx):
    return await _internal(app, "GET", "/api/alerts/", ctx["user"], params={"limit": _int_arg(args, "limit", 30, 1, 500)})


@tool("gboc_search_knowledge",
      "Busca na base de conhecimento local do Agente (RAG): soluções validadas, falhas, execuções, logs e documentação.",
      {"properties": {"query": {"type": "string", "description": "O que procurar"},
                      "sources": {"type": "array", "items": {"type": "string",
                                  "enum": ["solucoes", "erros", "execucoes", "logs", "docs"]},
                                  "description": "Filtrar fontes (opcional)"},
                      "k": {"type": "integer", "description": "Quantidade de trechos (padrão 6)"}},
       "required": ["query"]})
async def _t_search(app, args, ctx):
    from engines import ai_rag
    q = str(args.get("query") or "").strip()
    if not q:
        raise ToolError("Informe 'query'.")
    res = await asyncio.to_thread(ai_rag.search, q, _int_arg(args, "k", 6, 1, 30), args.get("sources") or None)
    return res


@tool("gboc_ask", "Pergunta ao Copilot do GBOC (usa dados reais do Agente + base de conhecimento local).",
      {"properties": {"question": {"type": "string"}}, "required": ["question"]})
async def _t_ask(app, args, ctx):
    from engines.ai_assistant import query_ai_assistant
    q = str(args.get("question") or "").strip()
    if not q:
        raise ToolError("Informe 'question'.")
    return await asyncio.to_thread(query_ai_assistant, q, None)


@tool("gboc_diagnose_error",
      "Diagnostica uma mensagem de erro de backup com a IA do Agente (usa casos validados do ambiente). Registra o caso.",
      {"properties": {"error_message": {"type": "string"}, "task_id": {"type": "integer"},
                      "task_name": {"type": "string"}, "engine": {"type": "string"}},
       "required": ["error_message"]})
async def _t_diagnose(app, args, ctx):
    from engines.ai_diagnostic_engine import ai_diagnostic_engine
    msg = str(args.get("error_message") or "").strip()
    if not msg:
        raise ToolError("Informe 'error_message'.")
    meta = {k: args.get(k) for k in ("task_id", "task_name", "engine") if args.get(k) is not None}
    meta["origin"] = "mcp"
    return await ai_diagnostic_engine.analyze_error(msg, record_case=True, case_meta=meta)


@tool("gboc_veracrypt_status", "Status do VeraCrypt no host e unidades montadas/livres.", {})
async def _t_vc_status(app, args, ctx):
    return await _internal(app, "GET", "/api/tasks/veracrypt/status", ctx["user"])


@tool("gboc_run_task", "Executa agora uma tarefa de backup.",
      {"properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}, role="operate")
async def _t_run(app, args, ctx):
    tid = _int_arg(args, "task_id")
    return await _internal(app, "POST", f"/api/tasks/{tid}/run", ctx["user"])


@tool("gboc_stop_task", "Interrompe uma tarefa de backup em execução.",
      {"properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}, role="operate", destructive=True)
async def _t_stop(app, args, ctx):
    tid = _int_arg(args, "task_id")
    return await _internal(app, "POST", f"/api/tasks/{tid}/stop", ctx["user"])


@tool("gboc_veracrypt_mount", "Monta o volume VeraCrypt configurado em uma tarefa.",
      {"properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}, role="operate")
async def _t_vc_mount(app, args, ctx):
    return await _internal(app, "POST", "/api/tasks/veracrypt/mount", ctx["user"],
                           json_body={"task_id": _int_arg(args, "task_id")})


@tool("gboc_veracrypt_dismount", "Desmonta o volume VeraCrypt de uma tarefa (recusado se houver backup usando).",
      {"properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}, role="operate", destructive=True)
async def _t_vc_dismount(app, args, ctx):
    return await _internal(app, "POST", "/api/tasks/veracrypt/dismount", ctx["user"],
                           json_body={"task_id": _int_arg(args, "task_id")})


@tool("gboc_case_feedback",
      "Registra se a solução de um caso de diagnóstico resolveu o problema (alimenta o RAG e o dataset de fine-tuning).",
      {"properties": {"case_id": {"type": "integer"}, "resolved": {"type": "boolean"},
                      "note": {"type": "string", "description": "Observação do que foi feito"}},
       "required": ["case_id", "resolved"]}, role="operate")
async def _t_feedback(app, args, ctx):
    from engines import ai_cases
    return await asyncio.to_thread(
        ai_cases.set_feedback, _int_arg(args, "case_id"), "resolved" if args.get("resolved") else "not_resolved",
        args.get("note"), None, None, ctx["user"])


# ──────────────────────────────────────────────────────────────────────────────
# JSON-RPC
# ──────────────────────────────────────────────────────────────────────────────

def _rpc_error(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _allowed_tools(role: str) -> list[dict[str, Any]]:
    can_operate = role in ("operate", "internal")
    return [t for t in TOOLS.values() if t["role"] == "read" or can_operate]


def _audit(ctx: dict[str, Any], name: str, args: dict[str, Any], ok: bool, err: str | None = None) -> None:
    safe_args = {k: (v if k not in ("password",) else "***") for k, v in (args or {}).items()}
    logger.info(f"[MCP] {ctx['user']} → {name}({json.dumps(safe_args, ensure_ascii=False)[:300]}) {'OK' if ok else 'ERRO: ' + str(err)}")
    try:
        from api.audit_api import record_audit
        record_audit(f"mcp.tool.{name}", resource_type="mcp", resource_id=name, detail={"args": safe_args},
                     username=ctx["user"], ip_address=ctx.get("ip"), result="success" if ok else "error",
                     error_message=err)
    except Exception:
        pass


async def handle_message(app, msg: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _rpc_error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Requisição JSON-RPC inválida.")
    mid = msg.get("id")
    method = msg["method"]
    params = msg.get("params") or {}
    is_notification = "id" not in msg

    if method == "initialize":
        requested = str(params.get("protocolVersion") or "")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
        try:
            from version import GBOC_VERSION
        except Exception:
            GBOC_VERSION = "15"
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "gboc-agent", "title": "GBOC Agent", "version": str(GBOC_VERSION)},
            "instructions": (
                "Servidor MCP do GBOC Agent (backup corporativo). Use gboc_agent_status e gboc_list_tasks para visão geral, "
                "gboc_recent_failures/gboc_task_history para investigar falhas, gboc_search_knowledge para consultar soluções "
                "já validadas no ambiente e gboc_diagnose_error para diagnóstico. Ações (executar/parar tarefa, VeraCrypt) "
                f"exigem token com perfil 'operate'. Perfil deste token: {ctx['role']}."
            ),
        }
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if is_notification:
        return None  # notifications/initialized, notifications/cancelled etc.

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [t["def"] for t in _allowed_tools(ctx["role"])]}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        entry = TOOLS.get(name)
        if not entry:
            return _rpc_error(mid, -32602, f"Ferramenta desconhecida: {name}")
        if entry not in _allowed_tools(ctx["role"]):
            msg_txt = f"O token MCP atual ('{ctx['role']}') não tem permissão para '{name}'. Use um token com perfil 'operate'."
            _audit(ctx, name, args, False, msg_txt)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": msg_txt}], "isError": True}}
        try:
            data = await entry["fn"](app, args, ctx)
            text = json.dumps(data, ensure_ascii=False, default=str, indent=1)
            if len(text) > MAX_TOOL_OUTPUT_CHARS:
                text = text[:MAX_TOOL_OUTPUT_CHARS] + "\n… (resposta truncada)"
            _audit(ctx, name, args, True)
            result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": False}
            if isinstance(data, dict):
                result["structuredContent"] = json.loads(json.dumps(data, default=str))
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except ToolError as e:
            _audit(ctx, name, args, False, str(e))
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": str(e)}], "isError": True}}
        except Exception as e:
            logger.exception(f"[MCP] Erro na ferramenta {name}: {e}")
            _audit(ctx, name, args, False, str(e))
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": f"Erro interno: {e.__class__.__name__}: {e}"}], "isError": True}}

    if method in ("resources/list", "prompts/list"):
        key = "resources" if method.startswith("resources") else "prompts"
        return {"jsonrpc": "2.0", "id": mid, "result": {key: []}}

    return _rpc_error(mid, -32601, f"Método não suportado: {method}")
