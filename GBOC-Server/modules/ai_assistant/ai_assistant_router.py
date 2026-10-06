# GBOC System v14.8.1 Enterprise Edition
# Module: Server AI Copilot Assistant
# Provedores: Ollama Local, DeepSeek, Groq, Gemini, OpenAI, Claude, Grok, Kimi, Mistral, Cohere
# Camada de provedores: modules/ai_assistant/ai_providers.py

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from modules.ai_assistant import ai_providers as aip
from modules.ai_assistant import gboc_help_kb as kb

try:
    from database import db_manager

    def get_db():
        return db_manager.get_connection()

    def release_db(conn):
        db_manager.release_connection(conn)
except Exception:  # pragma: no cover - ambiente sem driver PostgreSQL
    def get_db():
        return None

    def release_db(conn):
        return None

logger = logging.getLogger("gboc_server_ai_copilot")
router = APIRouter(prefix="/api/v1/ai", tags=["Server AI Copilot"])

ADMIN_ROLES = frozenset({"admin", "administrator", "superadmin"})

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
AI_CONFIG_FILE = DATA_DIR / "server_ai_config.json"
_config_lock = threading.Lock()

DEFAULT_SERVER_AI_CONFIG: dict[str, Any] = {
    "provider": "ollama_local",
    "ollama_url": aip.DEFAULT_OLLAMA_HOST,
    "ollama_host": aip.DEFAULT_OLLAMA_HOST,
    "ollama_model": aip.DEFAULT_MODELS["ollama"],
    "groq_model": aip.DEFAULT_MODELS["groq"],
    "openai_model": aip.DEFAULT_MODELS["openai"],
    "gemini_model": aip.DEFAULT_MODELS["gemini"],
    "claude_model": aip.DEFAULT_MODELS["claude"],
    "deepseek_model": aip.DEFAULT_MODELS["deepseek"],
    "task_history_limit": 10,
    "system_prompt": (
        "Você é o GBOC Server Copilot AI, assistente central especialista em orquestração de backups, "
        "monitoramento de agentes remotos, RMM e conformidade. Responda em Português brasileiro de forma "
        "clara e profissional. Baseie-se SOMENTE nos dados do contexto operacional fornecido; quando um dado "
        "não estiver no contexto, diga explicitamente que não está disponível — nunca invente números ou status."
    ),
}


# ──────────────────────────────────────────────────────────────────────────────
# Autenticação
# ──────────────────────────────────────────────────────────────────────────────

def _get_current_user_from_req(request: Request) -> dict[str, Any] | None:
    """Obtém o usuário logado com base no token (header Bearer ou cookie gboc_server_token)."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else request.cookies.get("gboc_server_token")
    if not token:
        return None

    conn = None
    try:
        conn = get_db()
        if not conn:
            return None
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.username, u.display_name, u.role, u.tenant_id
            FROM server_auth_tokens t
            JOIN server_auth_users u ON t.user_id = u.id
            WHERE t.token = %s AND t.expires_at > LOCALTIMESTAMP
            """,
            (token,),
        )
        row = cur.fetchone()
        cur.close()
        if row:
            return {"id": row[0], "username": row[1], "display_name": row[2], "role": row[3], "tenant_id": row[4]}
    except Exception as e:
        logger.warning(f"[SERVER AI COPILOT] Erro ao autenticar via token: {e}")
    finally:
        if conn:
            release_db(conn)
    return None


def _require_auth(request: Request) -> dict[str, Any]:
    """Valida autenticação do usuário para os endpoints do Server AI Copilot."""
    user = _get_current_user_from_req(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Não autenticado. Forneça um token válido no header Authorization ou cookie gboc_server_token.",
        )
    return user


def _require_admin(request: Request) -> dict[str, Any]:
    """Operações que alteram configuração/infraestrutura de IA exigem perfil administrador."""
    user = _require_auth(request)
    if (user.get("role") or "admin").lower() not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Permissão negada: somente administradores podem alterar a IA.")
    return user


# ──────────────────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────────────────

def _get_ai_config_file() -> str:
    return str(AI_CONFIG_FILE)


def load_server_ai_config() -> dict[str, Any]:
    """Carrega a configuração de IA do servidor (padrões + arquivo)."""
    merged = DEFAULT_SERVER_AI_CONFIG.copy()
    if AI_CONFIG_FILE.exists():
        try:
            data = json.loads(AI_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged.update(data)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"[SERVER AI COPILOT] Configuração de IA ilegível em {AI_CONFIG_FILE}: {e}")
    return merged


def save_server_ai_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Salva a configuração de IA. Campos desconhecidos são ignorados e chaves mascaradas/vazias
    não sobrescrevem as chaves reais já gravadas. Retorna a configuração MASCARADA.
    """
    clean = aip.sanitize_config_update(cfg or {})
    with _config_lock:
        current = load_server_ai_config()
        current.update(clean)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = AI_CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(AI_CONFIG_FILE)
    return aip.mask_config(current)


# ──────────────────────────────────────────────────────────────────────────────
# Contexto operacional REAL (PostgreSQL)
# ──────────────────────────────────────────────────────────────────────────────

def _collect_server_operational_data(limit: int = 5) -> dict[str, Any]:
    """Lê do PostgreSQL o estado real de agentes e execuções. Nunca fabrica valores."""
    conn = None
    try:
        conn = get_db()
        if not conn:
            return {"available": False, "error": "Conexão com o PostgreSQL indisponível."}
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE last_heartbeat > gboc_agent_offline_cutoff())
            FROM agents
            """
        )
        agents_total, agents_online = cur.fetchone()

        cur.execute(
            """
            SELECT hostname, last_heartbeat FROM agents
            WHERE last_heartbeat IS NULL OR last_heartbeat <= gboc_agent_offline_cutoff()
            ORDER BY last_heartbeat DESC NULLS LAST LIMIT %s
            """,
            (limit,),
        )
        offline = [{"hostname": r[0], "last_heartbeat": r[1].isoformat() if r[1] else None} for r in cur.fetchall()]

        cur.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE status IN ('completed','success')),
                   COUNT(*) FILTER (WHERE status = 'failed'),
                   COUNT(*) FILTER (WHERE status = 'failed' AND started_at >= LOCALTIMESTAMP - INTERVAL '24 hours')
            FROM agent_task_executions
            WHERE started_at >= LOCALTIMESTAMP - INTERVAL '7 days'
            """
        )
        exec_total, exec_success, failed_7d, failed_24h = cur.fetchone()

        cur.execute(
            """
            SELECT a.hostname, e.task_id, COALESCE(NULLIF(t.name, ''), 'Task #' || e.task_id::text),
                   e.started_at, LEFT(COALESCE(e.error_message, ''), 240)
            FROM agent_task_executions e
            LEFT JOIN agents a ON a.agent_id = e.agent_id
            LEFT JOIN agent_tasks t ON t.agent_id = e.agent_id AND t.task_id = e.task_id
            WHERE e.status = 'failed' AND e.started_at >= LOCALTIMESTAMP - INTERVAL '7 days'
            ORDER BY e.started_at DESC LIMIT %s
            """,
            (limit,),
        )
        failures = [
            {"hostname": r[0], "task_id": r[1], "task_name": r[2],
             "started_at": r[3].isoformat() if r[3] else None, "error": r[4]}
            for r in cur.fetchall()
        ]
        cur.close()
        return {
            "available": True,
            "agents_total": int(agents_total or 0),
            "agents_online": int(agents_online or 0),
            "agents_offline_sample": offline,
            "executions_7d": int(exec_total or 0),
            "success_7d": int(exec_success or 0),
            "failed_7d": int(failed_7d or 0),
            "failed_24h": int(failed_24h or 0),
            "recent_failures": failures,
        }
    except Exception as e:
        logger.error(f"[SERVER AI COPILOT] Falha ao coletar contexto operacional: {e}")
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return {"available": False, "error": f"Falha na consulta ao banco: {e.__class__.__name__}"}
    finally:
        if conn:
            release_db(conn)


def _format_context(data: dict[str, Any]) -> str:
    lines = [f"Data/Hora do Servidor: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    if not data.get("available"):
        lines.append(f"DADOS OPERACIONAIS INDISPONÍVEIS: {data.get('error', 'motivo desconhecido')}")
        return "\n".join(lines)
    lines.append(
        f"Agentes registrados: {data['agents_total']} (online na última hora: {data['agents_online']}, "
        f"sem heartbeat há mais de 60 min: {data['agents_total'] - data['agents_online']})"
    )
    for a in data.get("agents_offline_sample", [])[:3]:
        lines.append(f"  - Sem heartbeat: {a['hostname']} (último: {a['last_heartbeat'] or 'nunca'})")
    lines.append(
        f"Execuções nos últimos 7 dias: {data['executions_7d']} (sucesso: {data['success_7d']}, "
        f"falha: {data['failed_7d']}; falhas nas últimas 24h: {data['failed_24h']})"
    )
    for f in data.get("recent_failures", [])[:3]:
        err_msg = (f.get("error") or "sem mensagem de erro registrada")[:120]
        lines.append(f"  - Falha em {f.get('started_at')}: {f.get('hostname') or '?'} / {f.get('task_name')} — {err_msg}")
    return "\n".join(lines)


def _build_server_system_context() -> tuple[str, int]:
    """Retorna (contexto_texto, contagem_de_falhas_7d) com dados reais do PostgreSQL."""
    data = _collect_server_operational_data()
    return _format_context(data), int(data.get("failed_7d", 0)) if data.get("available") else 0


def _native_report(prompt: str, data: dict[str, Any]) -> str:
    """Relatório determinístico (sem LLM) construído apenas com dados reais."""
    if not data.get("available"):
        return (
            "ℹ️ **Motor Nativo GBOC (sem LLM)**\n"
            f"Não foi possível obter os dados operacionais: {data.get('error', 'motivo desconhecido')}.\n"
            "Nenhum status foi presumido."
        )
    body = [
        "📊 **Resumo operacional (dados reais do PostgreSQL)**",
        f"• Agentes: {data['agents_total']} registrados, {data['agents_online']} com heartbeat na última hora.",
        f"• Execuções 7 dias: {data['executions_7d']} — {data['success_7d']} com sucesso, {data['failed_7d']} com falha "
        f"({data['failed_24h']} nas últimas 24h).",
    ]
    if data["executions_7d"] == 0:
        body.append("• Nenhuma execução foi sincronizada pelos agentes nos últimos 7 dias — verifique agendamentos e sincronização.")
    if data["recent_failures"]:
        body.append("\n🔴 **Falhas mais recentes:**")
        body += [f"• {f['started_at']} — {f['hostname'] or '?'} / {f['task_name']}: {f['error'] or 'sem mensagem'}"
                 for f in data["recent_failures"]]
    if data["agents_offline_sample"]:
        body.append("\n🟠 **Agentes sem heartbeat recente:**")
        body += [f"• {a['hostname']} (último: {a['last_heartbeat'] or 'nunca'})" for a in data["agents_offline_sample"]]
    body.append(
        "\n📍 Detalhes: **Monitor de Alerta de Jobs** (`/modules/job_alert/`), **Agentes Registrados** "
        "(`/modules/agents/`) e **Relatórios**."
    )
    return "\n".join(body)


# ──────────────────────────────────────────────────────────────────────────────
# Consulta principal (usada pelas APIs v1 e v2)
# ──────────────────────────────────────────────────────────────────────────────


def _kb_or_native(prompt: str, topics, native, product: str) -> str:
    """Sem LLM: perguntas de uso ("onde fica", "como usar") são respondidas pelo guia oficial."""
    if topics and kb.is_howto_question(prompt):
        return kb.answer_from_kb(prompt, product) or native()
    if kb.is_howto_question(prompt) and not topics:
        return ("📘 **Guia de uso do GBOC** — não encontrei essa função específica. Funções disponíveis:\n"
                + kb.menu_map(product) + "\n\n" + native())
    return native()

def query_server_ai_assistant(prompt: str, provider_override: str | None = None) -> dict[str, Any]:
    """
    Consulta o provedor de IA configurado com contexto operacional real.
    Ordem: provedor principal → Ollama local (fallback) → relatório nativo (sem LLM).
    O campo ``is_llm_real`` indica se a resposta veio de um modelo de linguagem.
    """
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return {"status": "error", "message": "Prompt vazio"}
    if len(clean_prompt) > 8000:
        return {"status": "error", "message": "Prompt excede o limite de 8000 caracteres."}

    cfg = load_server_ai_config()
    clean_lower = clean_prompt.lower().strip(".! ")
    is_test = clean_lower in ("responda apenas com ok", "ok", "ping", "teste", "test", "hello")
    is_howto = kb.is_howto_question(clean_prompt)
    kb_topics = kb.find_topics(clean_prompt, "server", limit=2)
    base_prompt = cfg.get("system_prompt") or DEFAULT_SERVER_AI_CONFIG["system_prompt"]

    data: dict[str, Any] = {"available": False}
    if is_test:
        system = f"{base_prompt}\n\nResponda apenas: OK."
    elif is_howto:
        kb_ctx = kb.format_for_prompt(kb_topics, "server") if kb_topics else ""
        system = f"{base_prompt}\n\n{aip.GROUNDING_RULE}"
        if kb_ctx:
            system += f"\n\n[GUIA DE USO DO GBOC]:\n{kb_ctx}"
        system += f"\n\n[MAPA DE FUNÇÕES]:\n{kb.menu_map('server')}"
    else:
        data = _collect_server_operational_data()
        context_info = _format_context(data)
        system = f"{base_prompt}\n\n{aip.GROUNDING_RULE}\n\n[CONTEXTO OPERACIONAL REAL DO SERVIDOR CENTRAL GBOC]:\n{context_info}"
        kb_ctx = kb.format_for_prompt(kb_topics, "server") if kb_topics else ""
        if kb_ctx:
            system += f"\n\n[GUIA DE USO DO GBOC]:\n{kb_ctx}"

    primary, fallback = aip.chat_with_fallback(cfg, system, clean_prompt, provider=provider_override)

    if primary.ok:
        return {
            "status": "success", "is_llm_real": True,
            "provider": f"{primary.provider_label} ({primary.model})", "model": primary.model,
            "answer": primary.answer, "duration_seconds": primary.duration_seconds,
        }

    warning = (
        f"⚠️ **IA ({primary.provider_label}) indisponível**: {primary.error}\n"
        "• Ajuste em **Configurações Gerais > IA & LLMs**.\n\n"
    )
    if fallback and fallback.ok:
        return {
            "status": "success", "is_llm_real": True, "fallback": True, "primary_error": primary.error,
            "provider": f"Ollama Local (Fallback - {fallback.model})", "model": fallback.model,
            "answer": warning + f"🔄 **Fallback automático (Ollama Local - {fallback.model})**:\n{fallback.answer}",
            "duration_seconds": round(primary.duration_seconds + fallback.duration_seconds, 2),
        }

    if not data.get("available"):
        data = _collect_server_operational_data()

    return {
        "status": "success", "is_llm_real": False, "primary_error": primary.error,
        "fallback_error": fallback.error if fallback else None,
        "provider": "Motor Nativo GBOC Server (sem LLM)", "model": "gboc-native-report",
        "answer": warning + _kb_or_native(clean_prompt, kb_topics, lambda: _native_report(clean_prompt, data), "server"),
        "duration_seconds": round(primary.duration_seconds + (fallback.duration_seconds if fallback else 0), 2),
    }


def collect_host_telemetry() -> dict[str, Any]:
    """Telemetria real do host do Servidor Central (psutil)."""
    try:
        import platform
        import psutil
        root = "C:\\" if platform.system() == "Windows" else "/"
        return {
            "available": True,
            "cpu_percent": psutil.cpu_percent(interval=0.2),
            "ram_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage(root).percent,
            "platform": platform.system(),
        }
    except Exception as e:
        logger.error(f"[SERVER AI COPILOT] Telemetria do host indisponível: {e}")
        return {"available": False, "error": f"Telemetria indisponível: {e.__class__.__name__}"}


def compute_health_score(tel: dict[str, Any]) -> int | None:
    if not tel.get("available"):
        return None
    cpu, ram, disk = tel["cpu_percent"], tel["ram_percent"], tel["disk_percent"]
    return max(0, min(100, int(100 - (cpu * 0.15 + ram * 0.25 + (disk if disk > 85 else 0) * 0.4))))


def health_status(score: int | None) -> str:
    if score is None:
        return "UNAVAILABLE"
    return "HEALTHY" if score >= 80 else "WARNING" if score >= 60 else "CRITICAL"


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints v1
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/query")
async def server_ai_query(request: Request):
    """Processa perguntas via IA generativa no Servidor Central (com fallback transparente)."""
    _require_auth(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"status": "error", "message": "JSON inválido"}, status_code=400)
    prompt = (body.get("prompt") or "").strip() if isinstance(body, dict) else ""
    if not prompt:
        return JSONResponse({"status": "error", "message": "Prompt vazio"}, status_code=400)
    try:
        result = await run_in_threadpool(query_server_ai_assistant, prompt, body.get("provider"))
    except Exception as e:
        logger.exception(f"[SERVER AI COPILOT] Erro inesperado: {e}")
        return JSONResponse({"status": "error", "message": "Erro interno ao processar a consulta de IA."}, status_code=500)
    return JSONResponse(result, status_code=200 if result.get("status") == "success" else 400)


@router.get("/config")
async def get_server_ai_config(request: Request):
    """Retorna as configurações de IA do Servidor Central (chaves mascaradas)."""
    _require_auth(request)
    return JSONResponse({"status": "success", "config": aip.mask_config(load_server_ai_config()),
                         "default_models": aip.DEFAULT_MODELS})


@router.post("/config")
async def save_server_ai_config_endpoint(request: Request):
    """Salva configurações de IA do Servidor Central (somente administradores)."""
    _require_admin(request)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Corpo da requisição deve ser um objeto JSON.")
        saved = save_server_ai_config(body)
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except OSError as e:
        logger.error(f"[SERVER AI COPILOT] Falha ao gravar configuração: {e}")
        return JSONResponse({"status": "error", "message": "Falha ao gravar a configuração de IA no disco."}, status_code=500)
    return JSONResponse({"status": "success", "config": saved})


@router.post("/diagnose")
async def server_ai_diagnose(request: Request):
    """Diagnóstico por IA do Servidor Central com telemetria real do host."""
    _require_auth(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        body = {}
    body = body if isinstance(body, dict) else {}
    error_context = body.get("error_context") or body.get("module") or "Diagnóstico geral do Servidor Central"

    from modules.ai_assistant.ai_diagnostic_engine import server_ai_diagnostic_engine

    telemetry = await run_in_threadpool(collect_host_telemetry)
    ai_res = await server_ai_diagnostic_engine.analyze_error(error_context, system_logs=body.get("logs"), telemetry=telemetry)
    score = compute_health_score(telemetry)
    return JSONResponse({
        "status": health_status(score),
        "health_score": score,
        "telemetry": telemetry,
        "ai_insights": ai_res.get("analysis", ""),
        "result": ai_res,
    })


@router.post("/auto_fix")
async def server_ai_auto_fix(request: Request):
    """
    Não existe ação de remediação automática implementada no Servidor Central.
    Retorna erro explícito em vez de simular sucesso (Política Zero-Mock).
    """
    _require_auth(request)
    return JSONResponse(
        {
            "status": "unavailable",
            "fixed": False,
            "error": {
                "code": "AUTO_FIX_NOT_IMPLEMENTED",
                "message": "Nenhuma remediação automática foi executada: o Servidor Central não possui ação "
                           "corretiva automatizada para este item. Siga a solução indicada no diagnóstico.",
            },
        },
        status_code=501,
    )


@router.get("/ollama/models")
@router.post("/ollama/models")
async def get_ollama_models(request: Request):
    """Lista modelos instalados no Ollama configurado (consulta real a /api/tags)."""
    _require_auth(request)
    host = request.query_params.get("host")
    if not host and request.method == "POST":
        try:
            body = await request.json()
            host = body.get("host") if isinstance(body, dict) else None
        except (json.JSONDecodeError, ValueError):
            host = None
    if host:
        try:
            host = aip.validate_http_url(host)
        except ValueError as e:
            return JSONResponse({"status": "error", "connected": False, "message": str(e)}, status_code=400)

    info = await aip.alist_ollama_models(load_server_ai_config(), host)
    recommended = ["llama3.2:latest", "llama3.1:8b", "qwen2.5:7b", "mistral:latest", "deepseek-r1:8b", "gemma2:9b", "phi3:latest"]
    if info["connected"]:
        return JSONResponse({
            "status": "success", "connected": True, "ollama_host": info["host"],
            "installed_models": info["models"], "recommended_models": recommended,
            "count_installed": len(info["models"]),
        })
    return JSONResponse({
        "status": "error", "connected": False, "ollama_host": info["host"],
        "installed_models": [], "recommended_models": recommended, "count_installed": 0,
        "message": f"Servidor Ollama inacessível: {info['error']}",
    })


@router.post("/ollama/models/pull")
async def pull_ollama_model(request: Request):
    """Dispara o download (pull) real de um modelo Ollama em segundo plano (somente administradores)."""
    _require_admin(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"status": "error", "message": "JSON inválido"}, status_code=400)
    model = str(body.get("model") or "").strip()
    if not model or len(model) > 200 or any(c.isspace() for c in model):
        return JSONResponse({"status": "error", "message": "Nome do modelo inválido."}, status_code=400)
    try:
        host = aip.validate_http_url(body.get("host") or load_server_ai_config().get("ollama_url") or aip.DEFAULT_OLLAMA_HOST)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)

    def pull_task():
        logger.info(f"[SERVER AI COPILOT] Iniciando download do modelo '{model}' em {host}...")
        ok, msg = aip.pull_ollama_model(host, model)
        (logger.info if ok else logger.error)(f"[SERVER AI COPILOT] {msg}")

    threading.Thread(target=pull_task, name=f"ollama-pull-{model}", daemon=True).start()
    return JSONResponse({"status": "downloading", "message": f"O download do modelo '{model}' foi iniciado em segundo plano no servidor."})
