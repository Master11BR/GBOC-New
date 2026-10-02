# ==============================================================================
# GBOC System v14.7.4 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# A cópia, distribuição ou modificação não autorizada é estritamente proibida.
# ==============================================================================

"""
GBOC Agent AI Diagnostic Engine
Análise de falhas de backup/sistema com o LLM configurado (Ollama, OpenAI, Groq, Gemini,
Claude, DeepSeek, Grok, Kimi, Mistral, Cohere) e heurística determinística com telemetria
real do host quando nenhum LLM responde.

Configuração: config/global_settings.json → global_settings.ai_llm_config
(relida a cada chamada; alterações valem sem reiniciar o Agente).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from engines import ai_providers as aip

logger = logging.getLogger("GBOC.AIDiagnosticEngine")

DIAGNOSTIC_SYSTEM_PROMPT = (
    "Você é o especialista de diagnóstico do GBOC Agent (backup corporativo). "
    "Analise a falha informada e responda SOMENTE com um objeto JSON com as chaves: "
    '"cause" (causa técnica concisa), "solution" (passos numerados), '
    '"recommended_action" (uma de: "rebuild_index", "vss_shadow_copy", "prune_lock", "test_credentials", "none") '
    'e "analysis" (resumo em Português para o operador). Não invente dados que não estejam no contexto.'
)
_ALLOWED_ACTIONS = {"rebuild_index", "vss_shadow_copy", "prune_lock", "test_credentials", "none"}

DEFAULT_DIAG_CONFIG: dict[str, Any] = {
    "provider": "ollama",
    "ollama_host": aip.DEFAULT_OLLAMA_HOST,
    "ollama_url": aip.DEFAULT_OLLAMA_HOST,
    "model": aip.DEFAULT_MODELS["ollama"],
    "task_history_limit": 10,
    "auto_diagnose_errors": True,
}


def collect_host_telemetry() -> dict[str, Any]:
    """Telemetria real do host do Agente (psutil)."""
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
        logger.error(f"Telemetria do host indisponível: {e}")
        return {"available": False, "error": f"Telemetria indisponível: {e.__class__.__name__}"}


class AIDiagnosticEngine:
    def __init__(self):
        self.config_file = Path(__file__).resolve().parent.parent / "config" / "global_settings.json"
        self._lock = threading.Lock()

    # ── Configuração ─────────────────────────────────────────────────────────
    def _read_file(self) -> dict[str, Any]:
        if not self.config_file.exists():
            return {}
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Falha ao ler {self.config_file}: {e}")
            return {}

    @property
    def config(self) -> dict[str, Any]:
        cfg = DEFAULT_DIAG_CONFIG.copy()
        cfg.update(self._read_file().get("global_settings", {}).get("ai_llm_config", {}) or {})
        return cfg

    def public_config(self) -> dict[str, Any]:
        """Configuração com chaves mascaradas (para respostas de API)."""
        return aip.mask_config(self.config)

    def save_config(self, update: dict[str, Any] | None = None) -> dict[str, Any]:
        """Grava somente campos válidos; chaves mascaradas/vazias não sobrescrevem as reais."""
        clean = aip.sanitize_config_update(update or {}, provider_hint=self.config.get("provider"))
        with self._lock:
            full = self._read_file()
            gs = full.setdefault("global_settings", {})
            current = DEFAULT_DIAG_CONFIG.copy()
            current.update(gs.get("ai_llm_config", {}) or {})
            current.update(clean)
            gs["ai_llm_config"] = current
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.config_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(full, indent=4, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.config_file)
        return aip.mask_config(current)

    # ── Ollama ───────────────────────────────────────────────────────────────
    async def get_installed_ollama_models(self, ollama_host: str | None = None) -> dict[str, Any]:
        info = await aip.alist_ollama_models(self.config, ollama_host)
        return {
            "status": "success" if info["connected"] else "error",
            "connected": info["connected"],
            "ollama_host": info["host"],
            "installed_models": info["models"],
            "models": info["models"],
            "recommended_models": ["llama3.2:latest", "llama3.1:8b", "qwen2.5:7b", "mistral:latest",
                                   "deepseek-r1:8b", "gemma2:9b", "phi3:latest"],
            "count_installed": len(info["models"]),
            "message": "" if info["connected"] else f"Servidor Ollama inacessível: {info['error']}",
        }

    # ── Análise ──────────────────────────────────────────────────────────────
    async def analyze_error(self, error_context: str, system_logs: list[str] | None = None,
                            telemetry: dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = self.config
        provider = aip.normalize_provider(cfg.get("provider"))
        error_context = (error_context or "").strip() or "Verificação geral do Agente"
        is_test = "teste" in error_context.lower()

        if is_test:
            result = await aip.achat(cfg, "Você é um verificador de conectividade.", "Responda apenas: OK", provider=provider)
            if result.ok:
                return {"is_llm_real": True, "provider": result.provider_label, "model": result.model,
                        "analysis": f"✅ Conexão com {result.provider_label} OK (modelo '{result.model}', "
                                    f"{result.duration_seconds}s).\nResposta do modelo: {result.answer[:200]}"}
            return {"is_llm_real": False, "provider": result.provider_label, "model": result.model,
                    "error": result.error, "analysis": f"❌ Falha na conexão com {result.provider_label}: {result.error}"}

        if telemetry is None:
            import asyncio
            telemetry = await asyncio.to_thread(collect_host_telemetry)
        logs = [str(x)[:500] for x in (system_logs or [])][:30]
        prompt = (
            f"ERRO REGISTRADO:\n{error_context[:4000]}\n\n"
            f"LOGS RECENTES:\n{json.dumps(logs, ensure_ascii=False, indent=1)}\n\n"
            f"TELEMETRIA REAL DO HOST:\n{json.dumps(telemetry, ensure_ascii=False)}"
        )
        result = await aip.achat(cfg, DIAGNOSTIC_SYSTEM_PROMPT, prompt, provider=provider)
        if result.ok:
            parsed = self._parse_ai_response(result.answer, error_context)
            parsed.update({"is_llm_real": True, "provider": result.provider_label, "model": result.model})
            return parsed

        res = self._rule_based_ai_analysis(error_context, telemetry)
        res.update({"is_llm_real": False, "provider": f"Heurística GBOC Agent (LLM indisponível: {result.provider_label})",
                    "model": "gboc-heuristic", "llm_error": result.error})
        return res

    def _rule_based_ai_analysis(self, error_text: str, telemetry: dict[str, Any] | None = None) -> dict[str, Any]:
        """Heurística determinística: palavras-chave do erro + telemetria real do host."""
        err = (error_text or "").lower()
        if "lock" in err or "busy" in err:
            return {"cause": "Trava (.lock) residual no repositório.",
                    "solution": "1. Abrir Repositórios.\n2. Executar 'unlock'/limpeza de trava do motor (restic unlock / kopia maintenance).\n3. Reexecutar a tarefa.",
                    "recommended_action": "prune_lock",
                    "analysis": "⚠️ **Repositório possivelmente bloqueado** (heurística por palavra-chave)."}
        if "permission" in err or "access denied" in err or "acesso negado" in err:
            return {"cause": "Permissão insuficiente no caminho de origem/destino ou credencial inválida.",
                    "solution": "1. Verificar se o serviço GBOC roda como SYSTEM/Administrador.\n2. Validar credenciais do repositório.",
                    "recommended_action": "test_credentials",
                    "analysis": "⚠️ **Possível falha de permissão** (heurística por palavra-chave)."}
        if "vss" in err or "shadow" in err or "in use" in err or "being used by another process" in err:
            return {"cause": "Arquivo em uso sem Shadow Copy (VSS) ativa.",
                    "solution": "1. Habilitar VSS na tarefa.\n2. Verificar o serviço 'Volume Shadow Copy' (vssadmin list writers).",
                    "recommended_action": "vss_shadow_copy",
                    "analysis": "⚠️ **Arquivos bloqueados durante o backup** (heurística por palavra-chave)."}

        tel = telemetry or collect_host_telemetry()
        if not tel.get("available", True) or "cpu_percent" not in tel:
            return {"cause": "Telemetria do host indisponível.",
                    "solution": "Verifique a instalação do pacote 'psutil'.",
                    "recommended_action": "none",
                    "analysis": f"ℹ️ Telemetria real indisponível ({tel.get('error', 'motivo desconhecido')}). Nenhum estado foi presumido."}

        cpu, ram, disk = float(tel["cpu_percent"]), float(tel["ram_percent"]), float(tel["disk_percent"])
        issues, solutions = [], []
        if disk > 85:
            issues.append(f"Disco principal com {disk:.1f}% de uso.")
            solutions += ["Aplicar retenção/prune nos repositórios locais.", "Limpar data/temp e logs antigos do Agente."]
        if ram > 85:
            issues.append(f"RAM com {ram:.1f}% de uso.")
            solutions.append("Reduzir tarefas simultâneas.")
        if cpu > 80:
            issues.append(f"CPU com {cpu:.1f}% de uso.")
            solutions.append("Reagendar tarefas concorrentes de compressão/criptografia.")
        tel_txt = f"CPU {cpu:.1f}% • RAM {ram:.1f}% • Disco {disk:.1f}%"
        if not issues:
            return {"cause": f"Nenhum limite de telemetria excedido ({tel_txt}).",
                    "solution": "Sem ação corretiva indicada pelos indicadores de host. Configure um provedor de IA para análise de causa raiz.",
                    "recommended_action": "none",
                    "analysis": f"✅ **Telemetria real do host dentro dos limites**\n• {tel_txt}\n\nAnálise heurística (sem LLM)."}
        numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(solutions, 1))
        return {"cause": "Alertas de telemetria: " + " | ".join(issues), "solution": numbered, "recommended_action": "none",
                "analysis": "⚠️ **Alertas na telemetria real do host**\n" + "\n".join(f"• {i}" for i in issues)
                            + f"\n\n🛠️ **O que fazer:**\n{numbered}"}

    def _parse_ai_response(self, text: str, fallback_error: str) -> dict[str, Any]:
        data = aip.parse_json_object(text)
        if data:
            action = str(data.get("recommended_action") or "none")
            return {"cause": str(data.get("cause") or ""), "solution": str(data.get("solution") or ""),
                    "recommended_action": action if action in _ALLOWED_ACTIONS else "none",
                    "analysis": str(data.get("analysis") or text)}
        return {"cause": "", "solution": "", "recommended_action": "none", "analysis": text}


ai_diagnostic_engine = AIDiagnosticEngine()
