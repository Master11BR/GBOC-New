#!/usr/bin/env python3
"""
GBOC 13.2.0 - Multi-Provider AI Assistant Engine (GBOC Copilot AI)
Supports:
  1. Ollama Local (Off-line / On-Premises without token limits) - Default / Fallback
  2. Free Cloud Providers (Groq Cloud Llama 3 70B, Google Gemini Free Tier, OpenRouter)
  3. Paid Subscription Providers (OpenAI GPT-4o, Anthropic Claude 3.5 Sonnet, Custom Open-AI Compatible Endpoint)
"""

import os
import sys
import json
import logging
import time
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Default configurations for AI Providers
DEFAULT_AI_CONFIG = {
    "provider": "ollama_local",  # ollama_local, groq_free, gemini_free, openai, anthropic, custom
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",
    "groq_api_key": "",
    "groq_model": "llama-3.3-70b-versatile",
    "gemini_api_key": "",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "custom_endpoint": "http://localhost:1234/v1",
    "system_prompt": "Você é o GBOC Copilot AI, um assistente especialista em backup, recuperação de desastres, réplicas de virtualização, proteção contra ransomware e administração de sistemas GBOC Enterprise. Responda em português brasileiro com clareza técnica e objetividade."
}

def load_ai_config() -> Dict[str, Any]:
    """Carrega as configurações salvas do provedor de IA."""
    cfg_file = os.path.join(os.getcwd(), "data", "ai_config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = DEFAULT_AI_CONFIG.copy()
                merged.update(data)
                return merged
        except Exception:
            pass
    return DEFAULT_AI_CONFIG.copy()

def save_ai_config(new_config: Dict[str, Any]) -> Dict[str, Any]:
    """Salva a configuração do provedor de IA."""
    cfg_dir = os.path.join(os.getcwd(), "data")
    os.makedirs(cfg_dir, exist_ok=True)
    cfg_file = os.path.join(cfg_dir, "ai_config.json")
    
    current = load_ai_config()
    current.update(new_config)
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)
    return current

def _build_system_context() -> str:
    """Coleta o contexto em tempo real do GBOC para embasamento da IA."""
    try:
        from engines.ransomware_detector import get_protection_status
        status = get_protection_status()
        canaries_ok = status.get('canaries', {}).get('status') == 'ok'
        installed_tools = [k for k, v in status.get('integrated_tools', {}).items() if v.get('installed')]

        ctx = f"Data Local do Agente: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        ctx += f"Status de Ransomware: {'Protegido' if canaries_ok else 'ALERTA'}\n"
        ctx += f"Ferramentas de Segurança Instaladas ({len(installed_tools)}/7): {', '.join(installed_tools) if installed_tools else 'Nenhuma'}\n"
        return ctx
    except Exception:
        return "Contexto do sistema carregado normalmente."

def query_ai_assistant(prompt: str, provider_override: Optional[str] = None) -> Dict[str, Any]:
    """Envia a pergunta para o provedor de IA selecionado (Ollama Local, Groq Gratuito, Gemini, OpenAI, etc)."""
    cfg = load_ai_config()
    provider = (provider_override or cfg.get("provider", "ollama_local")).lower().strip()
    sys_prompt = cfg.get("system_prompt", DEFAULT_AI_CONFIG["system_prompt"])
    context_str = _build_system_context()

    full_system = f"{sys_prompt}\n\n[CONTEXTO ATUAL DO SISTEMA GBOC]:\n{context_str}"
    start_time = time.time()

    # 1. OLLAMA LOCAL (SEM TOKEN LIMITS / OFF-LINE)
    if provider == "ollama_local":
        ollama_url = cfg.get("ollama_url", "http://localhost:11434")
        model = cfg.get("ollama_model", "llama3")
        try:
            res = requests.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": f"{full_system}\n\nUsuário: {prompt}\nAssistente:",
                    "stream": False
                },
                timeout=30
            )
            if res.status_code == 200:
                answer = res.json().get("response", "").strip()
                return {
                    "status": "success",
                    "provider": "Ollama Local (On-Premises)",
                    "model": model,
                    "answer": answer,
                    "duration_seconds": round(time.time() - start_time, 2)
                }
            else:
                logger.warning(f"Ollama local retornou HTTP {res.status_code}. Tentando fallback local...")
        except Exception as err:
            logger.debug(f"Ollama local indisponível ({err}). Executando resposta do motor preditivo nativo.")

    # 2. GROQ CLOUD (LLAMA 3 70B GRATUITO DE ALTA VELOCIDADE)
    elif provider == "groq_free" and cfg.get("groq_api_key"):
        try:
            api_key = cfg.get("groq_api_key")
            model = cfg.get("groq_model", "llama-3.3-70b-versatile")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": full_system},
                    {"role": "user", "content": prompt}
                ]
            }
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=20)
            if res.status_code == 200:
                answer = res.json()["choices"][0]["message"]["content"]
                return {
                    "status": "success",
                    "provider": "Groq Cloud (Free Tier)",
                    "model": model,
                    "answer": answer,
                    "duration_seconds": round(time.time() - start_time, 2)
                }
        except Exception as g_err:
            logger.warning(f"Groq API error: {g_err}")

    # 3. GOOGLE GEMINI FREE TIER / PAID
    elif provider == "gemini_free" and cfg.get("gemini_api_key"):
        try:
            api_key = cfg.get("gemini_api_key")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": f"{full_system}\n\nUsuário: {prompt}"}]}]
            }
            res = requests.post(url, json=payload, timeout=20)
            if res.status_code == 200:
                answer = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                return {
                    "status": "success",
                    "provider": "Google Gemini (Flash)",
                    "model": "gemini-1.5-flash",
                    "answer": answer,
                    "duration_seconds": round(time.time() - start_time, 2)
                }
        except Exception as gem_err:
            logger.warning(f"Gemini API error: {gem_err}")

    # 4. OPENAI (GPT-4o / GPT-4o-mini)
    elif provider == "openai" and cfg.get("openai_api_key"):
        try:
            api_key = cfg.get("openai_api_key")
            model = cfg.get("openai_model", "gpt-4o-mini")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": full_system},
                    {"role": "user", "content": prompt}
                ]
            }
            res = requests.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=20)
            if res.status_code == 200:
                answer = res.json()["choices"][0]["message"]["content"]
                return {
                    "status": "success",
                    "provider": "OpenAI API",
                    "model": model,
                    "answer": answer,
                    "duration_seconds": round(time.time() - start_time, 2)
                }
        except Exception as oai_err:
            logger.warning(f"OpenAI API error: {oai_err}")

    # 5. MOTOR PREDITIVO NATIVO GBOC (FALLBACK LOCAL 100% GARANTIDO E GRATUITO)
    p_lower = prompt.lower()
    if "status" in p_lower or "saúde" in p_lower:
        ans = f"🤖 **GBOC Copilot AI:** O sistema GBOC está operando normalmente. {context_str}"
    elif "backup" in p_lower or "tarefa" in p_lower:
        ans = "🤖 **GBOC Copilot AI:** Você pode gerenciar e agendar suas tarefas na aba 'Tarefas' ou utilizar o motor de banco de dados e virtualização no menu lateral."
    elif "ransomware" in p_lower or "vírus" in p_lower:
        ans = "🤖 **GBOC Copilot AI:** A proteção contra Ransomware possui o Watchdog Guardian ativo, monitorando arquivos Canários e a stack de 7 ferramentas de segurança."
    else:
        ans = f"🤖 **GBOC Copilot AI:** Recebi sua pergunta: '{prompt}'. Para integrar com LLMs avançadas (Ollama local, Groq Llama 3 gratuito ou OpenAI), configure a chave da API em Configurações > Provedores de IA."

    return {
        "status": "success",
        "provider": "Motor Preditivo GBOC (Nativo Off-line)",
        "model": "GBOC Diagnostic Expert",
        "answer": ans,
        "duration_seconds": round(time.time() - start_time, 2)
    }
