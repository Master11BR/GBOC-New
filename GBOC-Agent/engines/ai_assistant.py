#!/usr/bin/env python3
"""
GBOC 14.7.6 - Multi-Provider AI Assistant Engine (GBOC Copilot AI - Agent)

Provedores: Ollama Local (padrão/fallback), DeepSeek, Groq, Google Gemini, OpenAI,
Anthropic Claude, xAI Grok, Moonshot Kimi, Mistral e Cohere — via engines/ai_providers.py.

Política Zero-Mock: o contexto enviado à IA e o relatório nativo (sem LLM) são
construídos exclusivamente com dados reais do banco do Agente.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from engines import ai_providers as aip
from engines import gboc_help_kb as kb

logger = logging.getLogger(__name__)

AGENT_ROOT = Path(__file__).resolve().parents[1]
AI_CONFIG_FILE = AGENT_ROOT / "data" / "ai_config.json"
_config_lock = threading.Lock()

DEFAULT_AI_CONFIG: dict[str, Any] = {
    "provider": "ollama_local",
    "ollama_url": aip.DEFAULT_OLLAMA_HOST,
    "ollama_host": aip.DEFAULT_OLLAMA_HOST,
    "ollama_model": aip.DEFAULT_MODELS["ollama"],
    "groq_model": aip.DEFAULT_MODELS["groq"],
    "openai_model": aip.DEFAULT_MODELS["openai"],
    "gemini_model": aip.DEFAULT_MODELS["gemini"],
    "claude_model": aip.DEFAULT_MODELS["claude"],
    "deepseek_model": aip.DEFAULT_MODELS["deepseek"],
    "system_prompt": (
        "Você é o GBOC Copilot AI, especialista em backup, recuperação de desastres, virtualização, proteção "
        "contra ransomware e administração do GBOC Enterprise. Responda em português brasileiro com clareza "
        "técnica. Use SOMENTE os dados do contexto fornecido; se um dado não estiver no contexto, diga que não "
        "está disponível — nunca invente números ou status."
    ),
}


def load_ai_config() -> dict[str, Any]:
    """Carrega a configuração do Copilot (padrões + data/ai_config.json)."""
    merged = DEFAULT_AI_CONFIG.copy()
    if AI_CONFIG_FILE.exists():
        try:
            data = json.loads(AI_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged.update(data)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Configuração de IA ilegível em {AI_CONFIG_FILE}: {e}")
    return merged


def save_ai_config(new_config: dict[str, Any]) -> dict[str, Any]:
    """Salva a configuração (whitelist, sem sobrescrever chaves com máscaras). Retorna a versão mascarada."""
    clean = aip.sanitize_config_update(new_config or {})
    with _config_lock:
        current = load_ai_config()
        current.update(clean)
        AI_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = AI_CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(AI_CONFIG_FILE)
    return aip.mask_config(current)


# ──────────────────────────────────────────────────────────────────────────────
# Contexto operacional REAL do Agente
# ──────────────────────────────────────────────────────────────────────────────

def collect_agent_operational_data(limit: int = 5) -> dict[str, Any]:
    """Execuções reais (7 dias) e estado de proteção ransomware a partir do banco do Agente."""
    data: dict[str, Any] = {"available": False}
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE status IN ('completed', 'success')),
                       COUNT(*) FILTER (WHERE status = 'failed'),
                       COUNT(*) FILTER (WHERE status = 'failed' AND started_at >= NOW() - INTERVAL '24 hours'),
                       COUNT(*) FILTER (WHERE status = 'running')
                FROM task_executions
                WHERE started_at >= NOW() - INTERVAL '7 days'
                """
            )
            total, success, failed, failed_24h, running = cur.fetchone()
            cur.execute(
                """
                SELECT e.started_at, COALESCE(t.name, 'Task #' || e.task_id::text), LEFT(COALESCE(e.error_message, ''), 240)
                FROM task_executions e
                LEFT JOIN tasks t ON t.id = e.task_id
                WHERE e.status = 'failed' AND e.started_at >= NOW() - INTERVAL '7 days'
                ORDER BY e.started_at DESC LIMIT %s
                """,
                (limit,),
            )
            failures = [
                {"started_at": r[0].isoformat() if hasattr(r[0], "isoformat") else r[0], "task_name": r[1], "error": r[2]}
                for r in cur.fetchall()
            ]
            cur.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE enabled = true) FROM tasks")
            tasks_total, tasks_enabled = cur.fetchone()
            cur.close()
        data.update({
            "available": True,
            "executions_7d": int(total or 0), "success_7d": int(success or 0),
            "failed_7d": int(failed or 0), "failed_24h": int(failed_24h or 0), "running": int(running or 0),
            "recent_failures": failures,
            "tasks_total": int(tasks_total or 0), "tasks_enabled": int(tasks_enabled or 0),
        })
    except Exception as e:
        logger.error(f"[AI] Falha ao coletar execuções do Agente: {e}")
        data["error"] = f"Banco do Agente indisponível ({e.__class__.__name__})."

    try:
        from engines.ransomware_detector import get_protection_status
        status = get_protection_status()
        canaries = status.get("canaries", {})
        tools = status.get("integrated_tools", {})
        data["ransomware"] = {
            "available": True,
            "canaries_total": canaries.get("total", 0),
            "canaries_compromised": canaries.get("compromised", 0),
            "last_scan_threat": None if (status.get("last_scan") or {}).get("threat_level") in (None, "never_scanned")
                                else (status.get("last_scan") or {}).get("threat_level"),
            "last_scan_date": (status.get("last_scan") or {}).get("date"),
            "tools_installed": sorted(k for k, v in tools.items() if isinstance(v, dict) and v.get("installed")),
            "tools_total": len(tools),
        }
    except Exception as e:
        logger.warning(f"[AI] Status ransomware indisponível: {e}")
        data["ransomware"] = {"available": False, "error": f"{e.__class__.__name__}"}
    return data


def _format_context(data: dict[str, Any]) -> str:
    lines = [f"Data/Hora local do Agente: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    if data.get("available"):
        lines.append(f"Tarefas cadastradas: {data['tasks_total']} (habilitadas: {data['tasks_enabled']})")
        lines.append(
            f"Execuções nos últimos 7 dias: {data['executions_7d']} (sucesso: {data['success_7d']}, falha: {data['failed_7d']}, "
            f"falhas nas últimas 24h: {data['failed_24h']}, em execução agora: {data['running']})"
        )
        for f in data["recent_failures"]:
            lines.append(f"  - Falha em {f['started_at']}: {f['task_name']} — {f['error'] or 'sem mensagem de erro registrada'}")
    else:
        lines.append(f"EXECUÇÕES INDISPONÍVEIS: {data.get('error', 'motivo desconhecido')}")

    rw = data.get("ransomware", {})
    if rw.get("available"):
        if rw["canaries_total"] == 0:
            canary_txt = "nenhum arquivo canário implantado"
        else:
            canary_txt = f"{rw['canaries_total']} canários, {rw['canaries_compromised']} comprometidos"
        lines.append(
            f"Ransomware: {canary_txt}; último scan: {rw['last_scan_threat'] or 'nunca executado'} "
            f"({rw['last_scan_date'] or 'sem data'}); ferramentas de segurança instaladas "
            f"{len(rw['tools_installed'])}/{rw['tools_total']}: {', '.join(rw['tools_installed']) or 'nenhuma'}"
        )
    else:
        lines.append("Ransomware: status indisponível.")
    return "\n".join(lines)


def _build_system_context() -> str:
    """Contexto textual real para embasar a IA (mantido por compatibilidade)."""
    return _format_context(collect_agent_operational_data())


def _native_report(data: dict[str, Any]) -> str:
    """Relatório determinístico (sem LLM) com dados reais."""
    parts = ["ℹ️ **Motor Nativo GBOC Agent (sem LLM) — dados reais do Agente**"]
    if data.get("available"):
        parts.append(
            f"• Execuções 7 dias: {data['executions_7d']} — {data['success_7d']} sucesso, {data['failed_7d']} falha "
            f"({data['failed_24h']} nas últimas 24h); {data['running']} em execução."
        )
        if data["executions_7d"] == 0:
            parts.append("• Nenhuma execução registrada nos últimos 7 dias — verifique os agendamentos.")
        if data["recent_failures"]:
            parts.append("\n🔴 **Falhas mais recentes:**")
            parts += [f"• {f['started_at']} — {f['task_name']}: {f['error'] or 'sem mensagem'}" for f in data["recent_failures"]]
    else:
        parts.append(f"• Execuções indisponíveis: {data.get('error', 'motivo desconhecido')}")
    rw = data.get("ransomware", {})
    if rw.get("available"):
        parts.append(
            f"• Ransomware: {rw['canaries_compromised']} de {rw['canaries_total']} canários comprometidos; "
            f"último scan: {rw['last_scan_threat'] or 'nunca executado'}."
        )
    parts.append(
        "\n📍 Detalhes: **Tarefas** (`/tasks.html`) → Histórico/Logs, **Falhas** (`/failed-jobs.html`) "
        "e **Ransomware** (`/ransomware.html`)."
    )
    return "\n".join(parts)



def _kb_or_native(prompt: str, topics, native, product: str) -> str:
    """Sem LLM: perguntas de uso ("onde fica", "como usar") são respondidas pelo guia oficial."""
    if topics and kb.is_howto_question(prompt):
        return kb.answer_from_kb(prompt, product) or native()
    if kb.is_howto_question(prompt) and not topics:
        return ("📘 **Guia de uso do GBOC** — não encontrei essa função específica. Funções disponíveis:\n"
                + kb.menu_map(product) + "\n\n" + native())
    return native()

def query_ai_assistant(prompt: str, provider_override: str | None = None) -> dict[str, Any]:
    """Consulta o provedor configurado com contexto real; fallback Ollama → relatório nativo."""
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return {"status": "error", "message": "Prompt vazio"}
    if len(clean_prompt) > 8000:
        return {"status": "error", "message": "Prompt excede o limite de 8000 caracteres."}

    cfg = load_ai_config()
    data = collect_agent_operational_data()
    system = f"{cfg.get('system_prompt') or DEFAULT_AI_CONFIG['system_prompt']}\n\n{aip.GROUNDING_RULE}\n\n[CONTEXTO REAL DO AGENTE GBOC]:\n{_format_context(data)}"
    kb_topics = kb.find_topics(clean_prompt, "agent", limit=3)
    kb_ctx = kb.format_for_prompt(kb_topics, "agent")
    if kb_ctx:
        system += "\n\n" + kb_ctx + "\n\n[MAPA DE FUNÇÕES]:\n" + kb.menu_map("agent")


    primary, fallback = aip.chat_with_fallback(cfg, system, clean_prompt, provider=provider_override)
    if primary.ok:
        return {
            "status": "success", "is_llm_real": True,
            "provider": f"{primary.provider_label} ({primary.model})", "model": primary.model,
            "answer": primary.answer, "duration_seconds": primary.duration_seconds,
        }

    warning = (
        f"⚠️ **IA ({primary.provider_label}) indisponível**: {primary.error}\n"
        "• Ajuste em **Configurações > Provedores de IA**.\n\n"
    )
    if fallback and fallback.ok:
        return {
            "status": "success", "is_llm_real": True, "fallback": True, "primary_error": primary.error,
            "provider": f"Ollama Local (Fallback - {fallback.model})", "model": fallback.model,
            "answer": warning + f"🔄 **Fallback automático (Ollama Local - {fallback.model})**:\n{fallback.answer}",
            "duration_seconds": round(primary.duration_seconds + fallback.duration_seconds, 2),
        }
    return {
        "status": "success", "is_llm_real": False, "primary_error": primary.error,
        "fallback_error": fallback.error if fallback else None,
        "provider": "Motor Nativo GBOC Agent (sem LLM)", "model": "gboc-native-report",
        "answer": warning + _kb_or_native(clean_prompt, kb_topics, lambda: _native_report(data), "agent"),
        "duration_seconds": round(primary.duration_seconds + (fallback.duration_seconds if fallback else 0), 2),
    }
