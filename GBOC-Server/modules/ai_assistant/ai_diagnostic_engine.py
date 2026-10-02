# ==============================================================================
# GBOC System v14.7.3 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# ==============================================================================

"""
GBOC Server AI Diagnostic Engine
Diagnóstico de falhas (agentes, backups, SLA, segurança) usando o LLM configurado
(Ollama, OpenAI, Groq, Gemini, Claude, DeepSeek, Grok, Kimi, Mistral, Cohere) e, na
ausência de LLM, uma heurística determinística baseada em telemetria real do host.

A configuração é relida a cada chamada (mesmo arquivo do Copilot:
data/server_ai_config.json), de modo que alterações salvas na interface
valem imediatamente, sem reiniciar o serviço.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from modules.ai_assistant import ai_providers as aip

logger = logging.getLogger("GBOC.ServerAIDiagnosticEngine")

DIAGNOSTIC_SYSTEM_PROMPT = (
    "Você é o especialista de diagnóstico do GBOC Server Central (backup corporativo). "
    "Analise a falha informada e responda SOMENTE com um objeto JSON com as chaves: "
    '"cause" (causa técnica concisa), "solution" (passos numerados), '
    '"recommended_action" (uma de: "rebuild_index", "vss_shadow_copy", "prune_lock", '
    '"test_credentials", "restart_agent_service", "none") e "analysis" (resumo em Português '
    "para o operador). Não invente dados que não estejam no contexto."
)

_ALLOWED_ACTIONS = {"rebuild_index", "vss_shadow_copy", "prune_lock", "test_credentials", "restart_agent_service", "none"}


class ServerAIDiagnosticEngine:
    """Motor de diagnóstico por IA do Servidor Central."""

    @property
    def config(self) -> dict[str, Any]:
        from modules.ai_assistant.ai_assistant_router import load_server_ai_config
        return load_server_ai_config()

    def save_config(self, update: dict[str, Any] | None = None) -> dict[str, Any]:
        from modules.ai_assistant.ai_assistant_router import save_server_ai_config
        return save_server_ai_config(update or {})

    async def get_installed_ollama_models(self, ollama_host: str | None = None) -> dict[str, Any]:
        """Consulta real dos modelos instalados no Ollama."""
        info = await aip.alist_ollama_models(self.config, ollama_host)
        return {
            "status": "success" if info["connected"] else "error",
            "connected": info["connected"],
            "ollama_host": info["host"],
            "installed_models": info["models"],
            "models": info["models"],
            "count_installed": len(info["models"]),
            "message": "" if info["connected"] else f"Servidor Ollama inacessível: {info['error']}",
        }

    async def analyze_error(self, error_context: str, system_logs: list[str] | None = None,
                            telemetry: dict[str, Any] | None = None) -> dict[str, Any]:
        """Analisa uma falha com o LLM configurado; sem LLM, usa heurística com telemetria real."""
        cfg = self.config
        provider = aip.normalize_provider(cfg.get("provider"))
        error_context = (error_context or "").strip() or "Diagnóstico geral do Servidor Central"
        is_test = "teste" in error_context.lower()

        if is_test:
            result = await aip.achat(cfg, "Você é um verificador de conectividade.", "Responda apenas: OK", provider=provider)
            if result.ok:
                return {
                    "is_llm_real": True, "provider": result.provider_label, "model": result.model,
                    "analysis": f"✅ Conexão com {result.provider_label} OK (modelo '{result.model}', "
                                f"{result.duration_seconds}s).\nResposta do modelo: {result.answer[:200]}",
                }
            return {
                "is_llm_real": False, "provider": result.provider_label, "model": result.model,
                "error": result.error,
                "analysis": f"❌ Falha na conexão com {result.provider_label}: {result.error}",
            }

        logs = [str(x)[:500] for x in (system_logs or [])][:30]
        prompt = (
            f"ERRO REGISTRADO NO SERVIDOR CENTRAL:\n{error_context[:4000]}\n\n"
            f"LOGS RECENTES:\n{json.dumps(logs, ensure_ascii=False, indent=1)}\n\n"
            f"TELEMETRIA REAL DO HOST:\n{json.dumps(telemetry or {}, ensure_ascii=False)}"
        )
        result = await aip.achat(cfg, DIAGNOSTIC_SYSTEM_PROMPT, prompt, provider=provider)
        if result.ok:
            parsed = self._parse_ai_response(result.answer, error_context)
            parsed.update({"is_llm_real": True, "provider": result.provider_label, "model": result.model})
            return parsed

        res = self._rule_based_ai_analysis(error_context, telemetry)
        res.update({
            "is_llm_real": False,
            "provider": f"Heurística GBOC Server (LLM indisponível: {result.provider_label})",
            "model": "gboc-heuristic",
            "llm_error": result.error,
        })
        return res

    def _rule_based_ai_analysis(self, error_text: str, telemetry: dict[str, Any] | None = None) -> dict[str, Any]:
        """Análise heurística determinística (palavras-chave + telemetria real do host)."""
        err_lower = (error_text or "").lower()

        if "offline" in err_lower or "disconnect" in err_lower or "timeout" in err_lower:
            return {
                "cause": "Heartbeat do agente expirado ou porta TCP 9200/443 inacessível.",
                "solution": "1. Verificar se o serviço GBOC Agent está ativo no host remoto.\n2. Confirmar regra de firewall para a porta 9200.\n3. Testar a resolução DNS/IP do host.",
                "recommended_action": "restart_agent_service",
                "analysis": "⚠️ **Possível falha de comunicação com agente** (heurística por palavra-chave).\n"
                            "Verifique conectividade, firewall e o serviço 'GBOC Agent' no host remoto.",
            }
        if "lock" in err_lower or "busy" in err_lower:
            return {
                "cause": "Trava (.lock) residual no repositório de armazenamento.",
                "solution": "1. Abrir o Gerenciador de Repositórios.\n2. Executar a limpeza de trava (Lock Prune).\n3. Reexecutar o job.",
                "recommended_action": "prune_lock",
                "analysis": "⚠️ **Repositório possivelmente bloqueado** (heurística por palavra-chave).\n"
                            "Uma execução anterior pode ter sido interrompida sem liberar a trava.",
            }
        if "permission" in err_lower or "access denied" in err_lower or "acesso negado" in err_lower:
            return {
                "cause": "Permissões NTFS/S3 insuficientes ou credencial revogada.",
                "solution": "1. Validar as credenciais do storage.\n2. Verificar permissão de leitura/escrita do usuário de serviço.",
                "recommended_action": "test_credentials",
                "analysis": "⚠️ **Possível falha de permissão no destino** (heurística por palavra-chave).\n"
                            "Revalide as credenciais em 'Configurações de Storage & Credenciais'.",
            }

        tel = telemetry
        if tel is None:
            from modules.ai_assistant.ai_assistant_router import collect_host_telemetry
            tel = collect_host_telemetry()
        if not tel.get("available", True) or "cpu_percent" not in tel:
            return {
                "cause": "Telemetria do host indisponível.",
                "solution": "Verifique se o pacote 'psutil' está instalado e se o serviço possui permissão para ler métricas.",
                "recommended_action": "none",
                "analysis": f"ℹ️ Não foi possível coletar telemetria real do host ({tel.get('error', 'motivo desconhecido')}). "
                            "Nenhum estado de saúde foi presumido.",
            }

        cpu, ram, disk = float(tel["cpu_percent"]), float(tel["ram_percent"]), float(tel["disk_percent"])
        issues: list[str] = []
        solutions: list[str] = []
        if disk > 85:
            issues.append(f"Ocupação crítica do disco principal: {disk:.1f}%.")
            solutions += ["Executar o expurgo de backups antigos (retenção GFS).", "Limpar logs temporários do GBOC Server."]
        if ram > 85:
            issues.append(f"Alta pressão de memória RAM: {ram:.1f}%.")
            solutions += ["Reduzir workers simultâneos nas configurações globais.", "Reiniciar serviços secundários para liberar memória."]
        if cpu > 80:
            issues.append(f"Uso elevado de CPU: {cpu:.1f}%.")
            solutions.append("Verificar rotinas simultâneas de deduplicação/criptografia.")

        telemetry_txt = f"CPU {cpu:.1f}% • RAM {ram:.1f}% • Disco {disk:.1f}%"
        if not issues:
            return {
                "cause": f"Nenhum limite de telemetria excedido ({telemetry_txt}).",
                "solution": "Nenhuma ação corretiva exigida pelos indicadores de host. Para análise de causa raiz, configure um provedor de IA.",
                "recommended_action": "none",
                "analysis": f"✅ **Telemetria real do host dentro dos limites**\n• {telemetry_txt}\n\n"
                            "Observação: esta é uma análise heurística (sem LLM) e cobre apenas CPU, RAM e disco.",
            }
        numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(solutions, 1))
        return {
            "cause": "Alertas de telemetria: " + " | ".join(issues),
            "solution": numbered,
            "recommended_action": "none",
            "analysis": "⚠️ **Alertas detectados na telemetria real do host**\n"
                        + "\n".join(f"• {i}" for i in issues) + f"\n\n🛠️ **O que fazer:**\n{numbered}",
        }

    def _parse_ai_response(self, text: str, fallback_error: str) -> dict[str, Any]:
        data = aip.parse_json_object(text)
        if data:
            action = str(data.get("recommended_action") or "none")
            return {
                "cause": str(data.get("cause") or ""),
                "solution": str(data.get("solution") or ""),
                "recommended_action": action if action in _ALLOWED_ACTIONS else "none",
                "analysis": str(data.get("analysis") or text),
            }
        return {"cause": "", "solution": "", "recommended_action": "none", "analysis": text}


server_ai_diagnostic_engine = ServerAIDiagnosticEngine()
