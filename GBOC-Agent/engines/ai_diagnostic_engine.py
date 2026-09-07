# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# A cópia, distribuição ou modificação não autorizada é estritamente proibida.
# ==============================================================================

"""
GBOC Real AI Diagnostic Engine v14.0.0 Enterprise
Integração Real com 11 Motores de IA (Local Ollama, Kimi, Grok, OpenAI, Gemini, DeepSeek, Claude, Qwen, Mistral, Llama 3.3 e Cohere).
Análise preditiva de logs, falhas de backup, integridade de disco e auto-reparo.
"""

import os
import json
import logging
import httpx
from typing import Dict, Any, Optional, List
from pathlib import Path

logger = logging.getLogger("GBOC.AIDiagnosticEngine")

class AIDiagnosticEngine:
    def __init__(self):
        self.config_file = Path(__file__).parent.parent / "config" / "global_settings.json"
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
                    cfg = json.load(f).get("global_settings", {}).get("ai_llm_config", {})
                    self.config.update(cfg)
            except Exception as e:
                logger.warning(f"Falha ao carregar config de IA: {e}")

    def save_config(self):
        try:
            full_data = {}
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    full_data = json.load(f)
            
            if "global_settings" not in full_data:
                full_data["global_settings"] = {}
            full_data["global_settings"]["ai_llm_config"] = self.config

            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(full_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Falha ao salvar configurações de IA: {e}")

    async def get_installed_ollama_models(self, ollama_host: Optional[str] = None) -> Dict[str, Any]:
        """Busca modelos instalados e disponíveis no serviço Ollama local."""
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
        """Realiza análise real de erro utilizando o LLM configurado (Ollama, Kimi, Grok, Cloud)."""
        provider = self.config.get("provider", "ollama")
        model = self.config.get("model", "llama3")
        ollama_host = self.config.get("ollama_host", "http://localhost:11434")
        api_key = self.config.get("api_key", "")

        is_test = "teste" in error_context.lower()

        # Prompt estruturado
        prompt = f"""Você é o Assistente Especialista de Inteligência Artificial do GBOC System v14.0.0 Enterprise.
Analise a seguinte falha de backup/sistema e forneça o diagnóstico exato da causa raiz e a solução em 1 clique.

ERRO REGISTRADO:
{error_context}

CONTEXTO DE LOGS RECENTES:
{json.dumps(system_logs or [], indent=2)}

Responda em formato JSON contendo obrigatoriamente:
- "cause": Explicação técnica concisa da causa do erro.
- "solution": Passos para solução.
- "recommended_action": Ação automatizada sugerida ("rebuild_index", "vss_shadow_copy", "prune_lock", "test_credentials").
- "analysis": Resumo amigável para o operador em Português.
"""

        # 1. Ollama Local ou modelos locais
        if provider in ("ollama", "qwen", "llama3", "mistral_local", "ollama_local"):
            ollama_info = await self.get_installed_ollama_models(ollama_host)
            active_host = ollama_info.get("ollama_host") if ollama_info.get("connected") else ollama_host.rstrip('/')
            installed_models = ollama_info.get("installed_models") or ollama_info.get("models", [])

            # Resolver o melhor modelo disponível se o especificado não for exato
            selected_model = model
            if installed_models:
                if selected_model not in installed_models:
                    prefix = selected_model.lower().split(':')[0]
                    match = next((m for m in installed_models if prefix == m.lower().split(':')[0]), None)
                    if not match:
                        match = next((m for m in installed_models if prefix in m.lower()), None)
                    selected_model = match or installed_models[0]

            if ollama_info.get("connected"):
                try:
                    async with httpx.AsyncClient(timeout=6.0) as client:
                        resp = await client.post(
                            f"{active_host}/api/generate",
                            json={
                                "model": selected_model,
                                "prompt": "Responda apenas: OK - Ollama Conectado" if is_test else prompt,
                                "stream": False,
                                "options": {
                                    "num_predict": 256,
                                    "temperature": 0.2
                                }
                            }
                        )
                        if resp.status_code == 200:
                            raw_text = resp.json().get("response", "")
                            if is_test:
                                return {
                                    "is_llm_real": True,
                                    "provider": f"Ollama Local ({active_host})",
                                    "model": selected_model,
                                    "analysis": f"✅ CONEXÃO COM OLLAMA OK!\n\nO serviço local Ollama respondeu com sucesso usando o modelo '{selected_model}'.\nResposta do Modelo: {raw_text.strip()}"
                                }
                            res = self._parse_ai_response(raw_text, error_context)
                            res["is_llm_real"] = True
                            res["provider"] = f"Ollama Local ({selected_model})"
                            res["model"] = selected_model
                            return res
                        elif resp.status_code == 404 and is_test:
                            return {
                                "is_llm_real": False,
                                "provider": f"Ollama Local ({active_host})",
                                "model": selected_model,
                                "analysis": f"⚠️ Ollama está ativo em {active_host}, mas o modelo '{selected_model}' não está baixado.\n\nExecute no terminal:\n`ollama pull {model}`\nou selecione um dos modelos instalados: {', '.join(installed_models) if installed_models else 'Nenhum'}"
                            }
                except Exception as e:
                    logger.warning(f"Ollama local indisponível no modelo {selected_model} ({e})...")

        # 2. Google Gemini
        if provider in ("gemini", "google"):
            if not api_key:
                return {
                    "is_llm_real": False,
                    "provider": "Google Gemini (Sem Chave API)",
                    "model": model,
                    "analysis": "⚠️ A Chave de API do Google Gemini não foi preenchida nas configurações.\n\nPor favor, insira a sua API Key e clique em 'Salvar Configuração de IA'."
                }
            try:
                gemini_model = model if "gemini" in model.lower() else "gemini-1.5-flash"
                target_url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
                payload = {"contents": [{"parts": [{"text": "Responda apenas: OK" if is_test else prompt}]}]}
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(target_url, json=payload)
                    if resp.status_code == 200:
                        content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                        if is_test:
                            return {
                                "is_llm_real": True,
                                "provider": "Google Gemini (API Conectada)",
                                "model": gemini_model,
                                "analysis": f"✅ CONEXÃO COM GOOGLE GEMINI OK!\n\nA API respondeu com sucesso usando o modelo '{gemini_model}'."
                            }
                        res = self._parse_ai_response(content, error_context)
                        res["is_llm_real"] = True
                        res["provider"] = "Google Gemini (LLM Real)"
                        res["model"] = gemini_model
                        return res
            except Exception as e:
                logger.warning(f"Falha na API Google Gemini ({e})...")

        # 3. Anthropic Claude
        if provider in ("claude", "anthropic"):
            if not api_key:
                return {
                    "is_llm_real": False,
                    "provider": "Anthropic Claude (Sem Chave API)",
                    "model": model,
                    "analysis": "⚠️ A Chave de API do Anthropic Claude não foi preenchida nas configurações.\n\nPor favor, insira a sua API Key e clique em 'Salvar Configuração de IA'."
                }
            try:
                claude_model = model if "claude" in model.lower() else "claude-3-5-sonnet-20241022"
                target_url = "https://api.anthropic.com/v1/messages"
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                payload = {
                    "model": claude_model,
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": "Responda apenas: OK" if is_test else prompt}]
                }
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(target_url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        content = resp.json()["content"][0]["text"]
                        if is_test:
                            return {
                                "is_llm_real": True,
                                "provider": "Anthropic Claude (API Conectada)",
                                "model": claude_model,
                                "analysis": f"✅ CONEXÃO COM ANTHROPIC CLAUDE OK!\n\nA API respondeu com sucesso usando o modelo '{claude_model}'."
                            }
                        res = self._parse_ai_response(content, error_context)
                        res["is_llm_real"] = True
                        res["provider"] = "Anthropic Claude (LLM Real)"
                        res["model"] = claude_model
                        return res
            except Exception as e:
                logger.warning(f"Falha na API Anthropic Claude ({e})...")

        # 4. Provedores Cloud padrão OpenAI-compatíveis (Groq, OpenAI, DeepSeek, Kimi, Mistral)
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
                    "analysis": f"⚠️ A Chave de API (API Key) para o provedor {provider.upper()} não foi preenchida nas configurações.\n\nPor favor, insira a sua API Key e clique em 'Salvar Configuração de IA'."
                }
            try:
                target_url = endpoints[provider]
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                actual_model = self.config.get("groq_model", "llama-3.3-70b-versatile") if "groq" in provider else model
                payload = {
                    "model": actual_model,
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
                                "model": actual_model,
                                "analysis": f"✅ CONEXÃO COM {provider.upper()} OK!\n\nA API em nuvem respondeu com sucesso usando o modelo '{actual_model}'."
                            }
                        res = self._parse_ai_response(content, error_context)
                        res["is_llm_real"] = True
                        res["provider"] = f"{provider.upper()} Nuvem (LLM Real)"
                        res["model"] = actual_model
                        return res
            except Exception as e:
                logger.warning(f"Falha na API {provider} ({e})...")

        # 3. Heurística Interna (Quando o serviço Ollama local não está aberto no Windows ou não há chave de API)
        if is_test:
            return {
                "is_llm_real": False,
                "provider": f"{provider.upper()} (Motor de Regras Heurísticas Interno)",
                "model": model,
                "analysis": f"⚠️ O serviço Ollama local não está em execução em '{ollama_host}' ou a Chave de API não foi informada.\n\n"
                            f"📌 O GBOC ativou o Motor Heurístico Interno de Contingência para garantir que os diagnósticos de backup continuem funcionando mesmo sem internet ou sem o Ollama aberto!\n\n"
                            f"💡 Para conectar a uma IA Real:\n"
                            f"1. Abra o serviço Ollama na sua máquina (ex: `ollama run llama3`), OU\n"
                            f"2. Escolha um provedor de nuvem (Kimi, Grok, OpenAI, DeepSeek) e informe a sua Chave de API."
            }

        res = self._rule_based_ai_analysis(error_context)
        res["is_llm_real"] = False
        res["provider"] = f"{provider.upper()} (Heurística Interna)"
        res["model"] = model
        return res

    def _rule_based_ai_analysis(self, error_text: str) -> Dict[str, Any]:
        """Análise heurística de causa raiz baseada no padrão do erro."""
        err_lower = error_text.lower()
        
        if "lock" in err_lower or "busy" in err_lower:
            return {
                "cause": "Arquivo de repositório bloqueado por processo concorrente ou execução interrompida.",
                "solution": "Executar higienização de trava (Lock Prune) e reiniciar o serviço do agente.",
                "recommended_action": "prune_lock",
                "analysis": "Identificada trava obsoleta no repositório. Clique em Auto-Heal para remover arquivos .lock."
            }
        elif "permission" in err_lower or "access denied" in err_lower:
            return {
                "cause": "Falha de permissão de E/S no diretório de destino ou credencial inválida.",
                "solution": "Verifique se a conta do GBOC Agent tem acesso de leitura/escrita ao caminho de rede/disco.",
                "recommended_action": "test_credentials",
                "analysis": "Acesso negado ao destino. Recomenda-se validar permissões NTFS/S3."
            }
        elif "open file" in err_lower or "in use" in err_lower:
            return {
                "cause": "Arquivo em uso exclusivo por outra aplicação (ex: SQL Server / Outlook).",
                "solution": "Ativar a captura de Shadow Copy VSS para arquivos abertos no job de backup.",
                "recommended_action": "vss_shadow_copy",
                "analysis": "Detectado arquivo em uso. Habilite o modo VSS Volume Shadow Copy."
            }
        else:
            return {
                "cause": f"Falha operacional no motor de backup: {error_text[:120]}",
                "solution": "Executar o utilitário de reparo e reconstrução de índice de blocos.",
                "recommended_action": "rebuild_index",
                "analysis": f"Erro detectado: '{error_text[:100]}'. Clique para executar auto-reparo de repositório."
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
            "cause": "Análise processada pelo modelo de IA.",
            "solution": "Seguir instruções recomendadas no relatório.",
            "recommended_action": "auto_heal",
            "analysis": text
        }

ai_diagnostic_engine = AIDiagnosticEngine()
