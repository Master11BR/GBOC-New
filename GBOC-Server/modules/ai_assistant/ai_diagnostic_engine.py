# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# ==============================================================================

"""
GBOC Server Real AI Diagnostic Engine v14.0.0 Enterprise
Integração de Inteligência Preditiva no Servidor Central para Diagnósticos de Agentes, Backups, SLA e Segurança.
Suporta: Ollama Local, Grok 70B, Google Gemini, OpenAI GPT-4o, DeepSeek, Kimi, Mistral e Motor Heurístico Server.
"""

import os
import json
import logging
import httpx
from typing import Dict, Any, Optional, List
from pathlib import Path

logger = logging.getLogger("GBOC.ServerAIDiagnosticEngine")

class ServerAIDiagnosticEngine:
    def __init__(self):
        self.config_file = Path(__file__).parent.parent.parent / "data" / "server_ai_config.json"
        self._load_config()

    def _load_config(self):
        self.config = {
            "provider": "ollama",
            "ollama_host": "http://localhost:11434",
            "model": "llama3",
            "api_key": "",
            "task_history_limit": 10
        }
        
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    self.config.update(cfg)
            except Exception as e:
                logger.warning(f"Falha ao carregar config de IA do servidor: {e}")

    def save_config(self):
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Falha ao salvar configurações de IA do servidor: {e}")

    async def get_installed_ollama_models(self, ollama_host: Optional[str] = None) -> Dict[str, Any]:
        """Busca modelos instalados e disponíveis no serviço Ollama local no servidor."""
        target_host = ollama_host or self.config.get("ollama_host", "http://localhost:11434")
        hosts_to_try = [target_host, "http://127.0.0.1:11434", "http://localhost:11434"]
        cleaned_hosts = []
        for h in hosts_to_try:
            if h and h.rstrip('/') not in cleaned_hosts:
                cleaned_hosts.append(h.rstrip('/'))

        recommended_models = [
            "llama3:latest",
            "llama3.2:latest",
            "llama3.3:70b",
            "mistral:latest",
            "deepseek-r1:latest",
            "deepseek-r1:1.5b",
            "qwen2.5:latest",
            "gemma2:latest",
            "codellama:latest",
            "phi3:latest"
        ]

        for host in cleaned_hosts:
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.get(f"{host}/api/tags")
                    if resp.status_code == 200:
                        models_data = resp.json().get("models", [])
                        installed = [m.get("name") or m.get("model") for m in models_data if m.get("name") or m.get("model")]
                        return {
                            "status": "success",
                            "connected": True,
                            "ollama_host": host,
                            "installed_models": installed,
                            "recommended_models": recommended_models,
                            "count_installed": len(installed)
                        }
            except Exception:
                continue

        return {
            "status": "error",
            "connected": False,
            "ollama_host": target_host,
            "installed_models": [],
            "recommended_models": recommended_models,
            "count_installed": 0,
            "message": f"Servidor Ollama local inacessível em {target_host} ou 127.0.0.1:11434."
        }

    async def analyze_error(self, error_context: str, system_logs: Optional[List[str]] = None) -> Dict[str, Any]:
        """Realiza análise de erro no Servidor Central utilizando o LLM configurado ou motor heurístico."""
        provider = self.config.get("provider", "ollama")
        model = self.config.get("model", "llama3")
        ollama_host = self.config.get("ollama_host", "http://localhost:11434")
        api_key = self.config.get("api_key") or self.config.get("groq_api_key") or self.config.get("openai_api_key") or ""

        is_test = "teste" in error_context.lower()

        # Prompt estruturado para o Servidor Central
        prompt = f"""Você é o Assistente Especialista de Inteligência Artificial do GBOC Server Central v14.0.0 Enterprise.
Analise a seguinte falha de backup/sistema/agente e forneça o diagnóstico exato da causa raiz e a solução em 1 clique.

ERRO REGISTRADO NO SERVIDOR CENTRAL:
{error_context}

CONTEXTO DE LOGS RECENTES:
{json.dumps(system_logs or [], indent=2)}

Responda em formato JSON contendo obrigatoriamente:
- "cause": Explicação técnica concisa da causa do erro.
- "solution": Passos para solução.
- "recommended_action": Ação automatizada sugerida ("rebuild_index", "vss_shadow_copy", "prune_lock", "test_credentials", "restart_agent_service").
- "analysis": Resumo amigável para o operador do GBOC Server em Português.
"""

        # 1. Ollama Local ou modelos locais
        if provider in ("ollama", "qwen", "llama3", "mistral_local", "ollama_local"):
            ollama_info = await self.get_installed_ollama_models(ollama_host)
            active_host = ollama_info.get("ollama_host") if ollama_info.get("connected") else ollama_host.rstrip('/')
            installed_models = ollama_info.get("installed_models", [])

            selected_model = model
            if installed_models:
                if selected_model not in installed_models:
                    match = next((m for m in installed_models if selected_model.lower() in m.lower()), None)
                    if match:
                        selected_model = match
                    else:
                        selected_model = installed_models[0]

            if ollama_info.get("connected"):
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(
                            f"{active_host}/api/generate",
                            json={
                                "model": selected_model,
                                "prompt": "Responda apenas: OK - GBOC Server Ollama Conectado" if is_test else prompt,
                                "stream": False
                            }
                        )
                        if resp.status_code == 200:
                            raw_text = resp.json().get("response", "")
                            if is_test:
                                return {
                                    "is_llm_real": True,
                                    "provider": f"Ollama Local ({active_host})",
                                    "model": selected_model,
                                    "analysis": f"✅ CONEXÃO COM OLLAMA OK NO SERVIDOR!\n\nO serviço local Ollama respondeu com sucesso usando o modelo '{selected_model}'.\nResposta do Modelo: {raw_text.strip()}"
                                }
                            res = self._parse_ai_response(raw_text, error_context)
                            res["is_llm_real"] = True
                            res["provider"] = f"Ollama Local ({selected_model})"
                            res["model"] = selected_model
                            return res
                except Exception as e:
                    logger.warning(f"Ollama local no servidor indisponível no modelo {selected_model} ({e})...")

        # 2. Provedores Cloud (Groq, OpenAI, Gemini, DeepSeek, Kimi)
        endpoints = {
            "groq": "https://api.groq.com/openai/v1/chat/completions",
            "groq_free": "https://api.groq.com/openai/v1/chat/completions",
            "kimi": "https://api.moonshot.cn/v1/chat/completions",
            "grok": "https://api.x.ai/v1/chat/completions",
            "openai": "https://api.openai.com/v1/chat/completions",
            "deepseek": "https://api.deepseek.com/v1/chat/completions",
            "mistral": "https://api.mistral.ai/v1/chat/completions"
        }

        if provider in endpoints:
            if not api_key:
                return {
                    "is_llm_real": False,
                    "provider": f"{provider.upper()} (Sem Chave API)",
                    "model": model,
                    "analysis": f"⚠️ A Chave de API para o provedor {provider.upper()} não foi configurada no Servidor.\n\nPor favor, insira a sua API Key em Configurações > IA do Servidor."
                }
            try:
                target_url = endpoints[provider]
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                payload = {
                    "model": self.config.get("groq_model", "llama-3.3-70b-versatile") if "groq" in provider else model,
                    "messages": [{"role": "user", "content": "Responda apenas: OK" if is_test else prompt}],
                    "temperature": 0.2
                }
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(target_url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        if is_test:
                            return {
                                "is_llm_real": True,
                                "provider": f"{provider.upper()} Nuvem (API Conectada)",
                                "model": model,
                                "analysis": f"✅ CONEXÃO COM {provider.upper()} OK NO SERVIDOR!\n\nA API em nuvem respondeu com sucesso."
                            }
                        res = self._parse_ai_response(content, error_context)
                        res["is_llm_real"] = True
                        res["provider"] = f"{provider.upper()} Nuvem (LLM Real)"
                        res["model"] = model
                        return res
            except Exception as e:
                logger.warning(f"Falha na API {provider} no servidor ({e})...")

        # 3. Heurística Interna do Servidor Central
        if is_test:
            return {
                "is_llm_real": False,
                "provider": f"{provider.upper()} (Motor Preditivo GBOC Server)",
                "model": model,
                "analysis": f"⚠️ O serviço Ollama local não está ativo em '{ollama_host}' ou a Chave de API não foi informada.\n\n"
                            f"📌 O GBOC Server ativou o Motor Preditivo Interno de Contingência para diagnósticos de conectividade e réplicas.\n\n"
                            f"💡 Para conectar a uma IA Real:\n"
                            f"1. Abra o serviço Ollama na máquina do servidor (ex: `ollama run llama3`), OU\n"
                            f"2. Escolha um provedor de nuvem (Groq, Gemini, OpenAI) e informe a sua Chave de API."
            }

        res = self._rule_based_ai_analysis(error_context)
        res["is_llm_real"] = False
        res["provider"] = f"{provider.upper()} (Heurística Server)"
        res["model"] = model
        return res

    def _rule_based_ai_analysis(self, error_text: str) -> Dict[str, Any]:
        """Análise heurística de causa raiz no Servidor Central."""
        err_lower = error_text.lower()
        
        if "offline" in err_lower or "disconnect" in err_lower or "timeout" in err_lower:
            return {
                "cause": "Agente remoto desconectado ou heartbeat expirado no Servidor Central.",
                "solution": "Verificar conectividade de rede, serviço do agente e porta TCP 9200/443.",
                "recommended_action": "restart_agent_service",
                "analysis": "Agente desconectado. Recomenda-se testar a conexão do agente ou reiniciar o serviço."
            }
        elif "lock" in err_lower or "busy" in err_lower:
            return {
                "cause": "Trava ativa em job de repositório centralizado.",
                "solution": "Executar remoção de trava e sincronização de estado.",
                "recommended_action": "prune_lock",
                "analysis": "Bloqueio detectado. Clique em Auto-Heal para remover travas de jobs."
            }
        elif "permission" in err_lower or "access denied" in err_lower:
            return {
                "cause": "Falha de permissão de acesso ao repositório ou storage MSP.",
                "solution": "Verificar credenciais do repositório de armazenamento no Servidor.",
                "recommended_action": "test_credentials",
                "analysis": "Acesso negado. Recomenda-se revalidar credenciais de armazenamento."
            }
        else:
            return {
                "cause": f"Falha operacional registrada no Servidor Central: {error_text[:120]}",
                "solution": "Executar diagnóstico preventivo de integridade e sincronização.",
                "recommended_action": "rebuild_index",
                "analysis": f"Erro detectado: '{error_text[:100]}'. Clique para executar auto-diagnóstico do servidor."
            }

    def _parse_ai_response(self, text: str, fallback_error: str) -> Dict[str, Any]:
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(text[start:end+1])
        except Exception:
            pass
        
        return {
            "cause": "Análise processada pelo modelo de IA do Servidor.",
            "solution": "Seguir instruções recomendadas no relatório.",
            "recommended_action": "auto_heal",
            "analysis": text
        }

server_ai_diagnostic_engine = ServerAIDiagnosticEngine()
