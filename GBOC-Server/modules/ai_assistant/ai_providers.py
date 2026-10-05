# ==============================================================================
# GBOC System v14.8.1 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================
"""
GBOC AI Providers — camada única de acesso a LLMs (Server e Agent).

Arquivo compartilhado e IDÊNTICO em:
  - GBOC-Server/modules/ai_assistant/ai_providers.py
  - GBOC-Agent/engines/ai_providers.py

Responsabilidades:
  * Normalizar o nome do provedor (ollama_local, groq_free, gemini_free, ...).
  * Resolver a chave de API e o modelo CORRETOS para cada provedor
    (nunca envia a chave de um provedor para outro).
  * Executar a chamada real ao provedor e devolver um resultado estruturado.
  * Proteger chaves (máscara na leitura e descarte de valores mascarados na gravação).

Política Zero-Mock: nenhuma resposta é fabricada. Em falha, retorna
``ok=False`` com o motivo real; quem chama decide como exibir.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("GBOC.AIProviders")

DEFAULT_OLLAMA_HOST = "http://localhost:11434"

# Modelos padrão vigentes (revisados em out/2026). Todos podem ser sobrescritos na configuração.
DEFAULT_MODELS: dict[str, str] = {
    "ollama": "llama3",
    "openai": "gpt-4o-mini",
    "groq": "openai/gpt-oss-120b",          # llama-3.3-70b-versatile foi descontinuado no Groq (ago/2026)
    "gemini": "gemini-flash-latest",        # Gemini 1.5/2.0 desligados; 2.5 com acesso restrito
    "claude": "claude-sonnet-5-5",
    "deepseek": "deepseek-flash",
    "grok": "grok-4.7",
    "kimi": "kimi-k2.6",
    "mistral": "mistral-large-latest",
    "cohere": "command-a-plus-05-2026",
}

PROVIDER_LABELS: dict[str, str] = {
    "ollama": "Ollama Local (On-Premises)",
    "openai": "OpenAI",
    "groq": "Groq Cloud",
    "gemini": "Google Gemini",
    "claude": "Anthropic Claude",
    "deepseek": "DeepSeek",
    "grok": "xAI Grok",
    "kimi": "Moonshot Kimi",
    "mistral": "Mistral AI",
    "cohere": "Cohere",
}

# Endpoints OpenAI-compatíveis (/chat/completions)
OPENAI_COMPATIBLE_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "grok": "https://api.x.ai/v1/chat/completions",
    "kimi": "https://api.moonshot.ai/v1/chat/completions",
    "mistral": "https://api.mistral.ai/v1/chat/completions",
}

# Campo de chave específico de cada provedor na configuração.
PROVIDER_KEY_FIELDS: dict[str, str] = {
    "openai": "openai_api_key",
    "groq": "groq_api_key",
    "gemini": "gemini_api_key",
    "claude": "claude_api_key",
    "deepseek": "deepseek_api_key",
    "grok": "grok_api_key",
    "kimi": "kimi_api_key",
    "mistral": "mistral_api_key",
    "cohere": "cohere_api_key",
}

# Campo de modelo específico de cada provedor na configuração.
PROVIDER_MODEL_FIELDS: dict[str, str] = {
    "ollama": "ollama_model",
    "openai": "openai_model",
    "groq": "groq_model",
    "gemini": "gemini_model",
    "claude": "claude_model",
    "deepseek": "deepseek_model",
    "grok": "grok_model",
    "kimi": "kimi_model",
    "mistral": "mistral_model",
    "cohere": "cohere_model",
}

SECRET_FIELDS: tuple[str, ...] = ("api_key", "cloud_api_key", *PROVIDER_KEY_FIELDS.values())

# Campos aceitos na gravação da configuração (whitelist).
ALLOWED_CONFIG_FIELDS: frozenset[str] = frozenset({
    "provider", "model", "ollama_url", "ollama_host", "custom_endpoint",
    "system_prompt", "task_history_limit", "auto_diagnose_errors", "timeout_seconds",
    *SECRET_FIELDS, *PROVIDER_MODEL_FIELDS.values(),
})

# Palavras que identificam o provedor (ordem importa: "groq" antes de "grok").
_PROVIDER_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("deepseek", ("deepseek",)),
    ("groq", ("groq",)),
    ("grok", ("grok", "xai")),
    ("openai", ("openai", "gpt")),
    ("gemini", ("gemini", "google")),
    ("claude", ("claude", "anthropic")),
    ("kimi", ("kimi", "moonshot")),
    ("mistral", ("mistral",)),
    ("cohere", ("cohere", "command")),
    ("ollama", ("ollama", "local", "qwen", "llama", "gemma", "phi")),
)

# Regra fixa de ancoragem (sempre anexada ao prompt de sistema, mesmo com prompt customizado).
GROUNDING_RULE = (
    "REGRAS OBRIGATÓRIAS: use somente os dados do CONTEXTO fornecido para afirmar números, status ou eventos; "
    "se a informação não estiver no contexto, diga explicitamente que ela não está disponível; "
    "nunca invente estados como 'online', 'saudável' ou 'concluído com sucesso'."
)

DEFAULT_CLOUD_TIMEOUT = 60.0
DEFAULT_LOCAL_TIMEOUT = 300.0   # modelos locais em CPU podem levar minutos (5 min)
MAX_OUTPUT_TOKENS = 1024


@dataclass(slots=True)
class AIResult:
    """Resultado estruturado de uma chamada real a um provedor."""
    ok: bool
    provider: str
    provider_label: str
    model: str = ""
    answer: str = ""
    error: str = ""
    duration_seconds: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "provider_label": self.provider_label,
            "model": self.model,
            "answer": self.answer,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            **self.extra,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Normalização e resolução de configuração
# ──────────────────────────────────────────────────────────────────────────────

def normalize_provider(raw: str | None) -> str:
    """Converte qualquer apelido (ollama_local, groq_free, gemini_free, anthropic...) no id canônico."""
    value = (raw or "").strip().lower()
    if not value:
        return "ollama"
    for canonical, words in _PROVIDER_ALIASES:
        if any(w in value for w in words):
            return canonical
    return value


def provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider.upper())


def is_masked_secret(value: Any) -> bool:
    """True quando o valor é uma máscara devolvida pela API (ex.: 'sk-a...wxyz', '***')."""
    if not isinstance(value, str):
        return False
    v = value.strip()
    return v == "***" or "..." in v or "•" in v


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "***"


def mask_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Cópia da configuração com todas as chaves mascaradas (para respostas de API)."""
    out = dict(cfg)
    for k in SECRET_FIELDS:
        if out.get(k):
            out[k] = mask_secret(str(out[k]))
    out["configured_keys"] = sorted(
        p for p, f in PROVIDER_KEY_FIELDS.items() if cfg.get(f)
    )
    return out


def validate_http_url(url: str) -> str:
    """Valida URL de host (Ollama/endpoint). Aceita apenas http/https com host. Retorna normalizada."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("URL inválida: use http:// ou https:// seguido do host (ex.: http://localhost:11434).")
    if parsed.username or parsed.password:
        raise ValueError("URL não pode conter credenciais embutidas.")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if ip.is_multicast or ip.is_unspecified:
            raise ValueError("Endereço IP não permitido para o host de IA.")
    except ValueError as exc:
        if "não permitido" in str(exc):
            raise
    return url.strip().rstrip("/")


def sanitize_config_update(update: dict[str, Any], provider_hint: str | None = None) -> dict[str, Any]:
    """
    Filtra uma atualização de configuração recebida do frontend:
      * somente campos conhecidos;
      * descarta chaves mascaradas/vazias (não sobrescreve a chave real salva);
      * valida URLs de host;
      * mapeia 'api_key' genérico para o campo do provedor selecionado.
    """
    clean: dict[str, Any] = {}
    for key, value in (update or {}).items():
        if key not in ALLOWED_CONFIG_FIELDS or value is None:
            continue
        if key in SECRET_FIELDS:
            if not isinstance(value, str) or not value.strip() or is_masked_secret(value):
                continue
            value = value.strip()
        elif key in ("ollama_url", "ollama_host", "custom_endpoint"):
            if not str(value).strip():
                continue
            value = validate_http_url(str(value))
        elif key == "task_history_limit":
            value = max(1, min(500, int(value)))
        elif key == "timeout_seconds":
            value = max(5, min(600, int(value)))
        elif isinstance(value, str):
            value = value.strip()
        clean[key] = value

    provider = normalize_provider(clean.get("provider") or provider_hint)
    generic_key = clean.pop("api_key", None) or clean.pop("cloud_api_key", None)
    if generic_key and provider in PROVIDER_KEY_FIELDS:
        clean.setdefault(PROVIDER_KEY_FIELDS[provider], generic_key)

    # Mantém ollama_url/ollama_host coerentes
    host = clean.get("ollama_url") or clean.get("ollama_host")
    if host:
        clean["ollama_url"] = clean["ollama_host"] = host
    return clean


def _model_fits_provider(provider: str, model: str) -> bool:
    """Heurística para não enviar um modelo de outro provedor (ex.: 'llama3:latest' para a OpenAI)."""
    m = (model or "").strip().lower()
    if not m or m == "default":
        return False
    if provider == "ollama":
        return True
    if ":" in m:                       # tag de modelo do Ollama
        return False
    prefixes = {
        "openai": ("gpt", "o1", "o3", "o4", "o5", "chatgpt"),
        "gemini": ("gemini",),
        "claude": ("claude",),
        "deepseek": ("deepseek",),
        "grok": ("grok",),
        "kimi": ("kimi", "moonshot"),
        "mistral": ("mistral", "codestral", "ministral", "magistral", "pixtral", "open-mistral"),
        "cohere": ("command", "c4ai"),
    }.get(provider)
    if prefixes is None:               # groq hospeda vários fornecedores
        return True
    return m.startswith(prefixes)


def resolve_api_key(cfg: dict[str, Any], provider: str) -> str:
    field_name = PROVIDER_KEY_FIELDS.get(provider)
    if not field_name:
        return ""
    key = str(cfg.get(field_name) or "").strip()
    if not key:
        # Compatibilidade com configurações antigas que só possuem 'api_key'/'cloud_api_key'
        # e cujo provedor ativo é o mesmo solicitado.
        if normalize_provider(cfg.get("provider")) == provider:
            key = str(cfg.get("api_key") or cfg.get("cloud_api_key") or "").strip()
    return "" if is_masked_secret(key) else key


def resolve_model(cfg: dict[str, Any], provider: str) -> str:
    candidates = [cfg.get(PROVIDER_MODEL_FIELDS.get(provider, ""))]
    if normalize_provider(cfg.get("provider")) == provider:
        candidates.append(cfg.get("model"))
    for cand in candidates:
        if isinstance(cand, str) and _model_fits_provider(provider, cand):
            return cand.strip()
    return DEFAULT_MODELS.get(provider, "")


def resolve_ollama_hosts(cfg: dict[str, Any], override: str | None = None) -> list[str]:
    hosts: list[str] = []
    for h in (override, cfg.get("ollama_url"), cfg.get("ollama_host"), DEFAULT_OLLAMA_HOST, "http://127.0.0.1:11434"):
        if not h:
            continue
        try:
            norm = validate_http_url(str(h))
        except ValueError:
            continue
        if norm not in hosts:
            hosts.append(norm)
    return hosts


def _timeout_for(cfg: dict[str, Any], provider: str) -> float:
    custom = cfg.get("timeout_seconds")
    if isinstance(custom, (int, float)) and custom > 0:
        return float(custom)
    return DEFAULT_LOCAL_TIMEOUT if provider == "ollama" else DEFAULT_CLOUD_TIMEOUT


def _http_error(provider: str, resp: httpx.Response) -> str:
    body = resp.text[:300].replace("\n", " ")
    hint = ""
    if resp.status_code in (401, 403):
        hint = " Verifique a chave de API."
    elif resp.status_code == 404:
        hint = " Verifique o nome do modelo."
    elif resp.status_code == 429:
        hint = " Limite de uso/cota excedido no provedor."
    return f"{provider_label(provider)} respondeu HTTP {resp.status_code}.{hint} Detalhe: {body}"


# ──────────────────────────────────────────────────────────────────────────────
# Ollama
# ──────────────────────────────────────────────────────────────────────────────

def list_ollama_models(cfg: dict[str, Any], host_override: str | None = None, timeout: float = 10.0) -> dict[str, Any]:
    """Consulta /api/tags do Ollama. Retorna {connected, host, models, error}."""
    last_error = "Nenhum host Ollama válido configurado."
    for host in resolve_ollama_hosts(cfg, host_override):
        try:
            resp = httpx.get(f"{host}/api/tags", timeout=timeout)
            if resp.status_code == 200:
                models = [m.get("name") or m.get("model") for m in resp.json().get("models", [])]
                return {"connected": True, "host": host, "models": [m for m in models if m], "error": ""}
            last_error = f"{host} respondeu HTTP {resp.status_code}"
        except (httpx.HTTPError, ValueError) as exc:
            last_error = f"{host}: {exc.__class__.__name__}: {exc}"
    return {"connected": False, "host": host_override or cfg.get("ollama_url") or DEFAULT_OLLAMA_HOST,
            "models": [], "error": last_error}


def _pick_ollama_model(target: str, installed: list[str]) -> str:
    if not installed or target in installed:
        return target
    base = target.lower().split(":")[0]
    exact_base = next((m for m in installed if m.lower().split(":")[0] == base), None)
    return exact_base or next((m for m in installed if base and base in m.lower()), None) or installed[0]


def _call_ollama(cfg: dict[str, Any], system: str, prompt: str, temperature: float) -> AIResult:
    start = time.perf_counter()
    info = list_ollama_models(cfg)
    if not info["connected"]:
        return AIResult(False, "ollama", provider_label("ollama"),
                        error=f"Serviço Ollama inacessível ({info['error']}).",
                        duration_seconds=round(time.perf_counter() - start, 2))
    model = _pick_ollama_model(resolve_model(cfg, "ollama"), info["models"])
    if not info["models"]:
        return AIResult(False, "ollama", provider_label("ollama"), model=model,
                        error=f"Ollama ativo em {info['host']}, mas nenhum modelo está instalado. Execute: ollama pull {model}",
                        duration_seconds=round(time.perf_counter() - start, 2))
    try:
        timeout_val = _timeout_for(cfg, "ollama")
        resp = httpx.post(
            f"{info['host']}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": temperature, "num_predict": min(MAX_OUTPUT_TOKENS, 512)},
            },
            timeout=httpx.Timeout(timeout_val, connect=15.0),
        )
        if resp.status_code != 200:
            return AIResult(False, "ollama", provider_label("ollama"), model=model, error=_http_error("ollama", resp),
                            duration_seconds=round(time.perf_counter() - start, 2))
        text = (resp.json().get("message") or {}).get("content", "").strip()
        if not text:
            return AIResult(False, "ollama", provider_label("ollama"), model=model,
                            error="Ollama retornou resposta vazia.",
                            duration_seconds=round(time.perf_counter() - start, 2))
        return AIResult(True, "ollama", provider_label("ollama"), model=model, answer=text,
                        duration_seconds=round(time.perf_counter() - start, 2), extra={"host": info["host"]})
    except httpx.TimeoutException:
        return AIResult(False, "ollama", provider_label("ollama"), model=model,
                        error=f"Tempo limite excedido aguardando o modelo '{model}' no Ollama.",
                        duration_seconds=round(time.perf_counter() - start, 2))
    except (httpx.HTTPError, ValueError) as exc:
        return AIResult(False, "ollama", provider_label("ollama"), model=model, error=f"Falha no Ollama: {exc}",
                        duration_seconds=round(time.perf_counter() - start, 2))


# ──────────────────────────────────────────────────────────────────────────────
# Provedores em nuvem
# ──────────────────────────────────────────────────────────────────────────────

def _call_cloud(cfg: dict[str, Any], provider: str, system: str, prompt: str, temperature: float) -> AIResult:
    start = time.perf_counter()
    label = provider_label(provider)
    key = resolve_api_key(cfg, provider)
    model = resolve_model(cfg, provider)
    if not key:
        return AIResult(False, provider, label, model=model,
                        error=f"A chave de API do {label} não foi configurada (Configurações > IA & LLMs).")

    timeout = _timeout_for(cfg, provider)
    try:
        if provider in OPENAI_COMPATIBLE_ENDPOINTS:
            resp = httpx.post(
                OPENAI_COMPATIBLE_ENDPOINTS[provider],
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                    "temperature": temperature,
                },
                timeout=timeout,
            )
            if resp.status_code != 200:
                return AIResult(False, provider, label, model=model, error=_http_error(provider, resp),
                                duration_seconds=round(time.perf_counter() - start, 2))
            text = resp.json()["choices"][0]["message"]["content"] or ""

        elif provider == "gemini":
            resp = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": MAX_OUTPUT_TOKENS},
                },
                timeout=timeout,
            )
            if resp.status_code != 200:
                return AIResult(False, provider, label, model=model, error=_http_error(provider, resp),
                                duration_seconds=round(time.perf_counter() - start, 2))
            parts = resp.json()["candidates"][0]["content"].get("parts", [])
            text = "".join(p.get("text", "") for p in parts)

        elif provider == "claude":
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={
                    "model": model,
                    "max_tokens": MAX_OUTPUT_TOKENS,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                },
                timeout=timeout,
            )
            if resp.status_code != 200:
                return AIResult(False, provider, label, model=model, error=_http_error(provider, resp),
                                duration_seconds=round(time.perf_counter() - start, 2))
            text = "".join(b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text")

        elif provider == "cohere":
            resp = httpx.post(
                "https://api.cohere.com/v2/chat",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                    "temperature": temperature,
                },
                timeout=timeout,
            )
            if resp.status_code != 200:
                return AIResult(False, provider, label, model=model, error=_http_error(provider, resp),
                                duration_seconds=round(time.perf_counter() - start, 2))
            content = (resp.json().get("message") or {}).get("content", [])
            text = "".join(c.get("text", "") for c in content if isinstance(c, dict))

        else:
            return AIResult(False, provider, label, model=model, error=f"Provedor de IA '{provider}' não suportado.")

    except httpx.TimeoutException:
        return AIResult(False, provider, label, model=model, error=f"Tempo limite excedido ({timeout:.0f}s) aguardando {label}.",
                        duration_seconds=round(time.perf_counter() - start, 2))
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        return AIResult(False, provider, label, model=model, error=f"Falha ao consultar {label}: {exc.__class__.__name__}: {exc}",
                        duration_seconds=round(time.perf_counter() - start, 2))

    text = (text or "").strip()
    if not text:
        return AIResult(False, provider, label, model=model, error=f"{label} retornou resposta vazia.",
                        duration_seconds=round(time.perf_counter() - start, 2))
    return AIResult(True, provider, label, model=model, answer=text,
                    duration_seconds=round(time.perf_counter() - start, 2))


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def chat(cfg: dict[str, Any], system: str, prompt: str, provider: str | None = None,
         temperature: float = 0.2) -> AIResult:
    """Chamada síncrona e real ao provedor (configurado ou informado)."""
    prov = normalize_provider(provider or cfg.get("provider"))
    if prov == "ollama":
        result = _call_ollama(cfg, system, prompt, temperature)
    else:
        result = _call_cloud(cfg, prov, system, prompt, temperature)
    if not result.ok:
        logger.warning("[AI] %s: %s", result.provider_label, result.error)
    return result


def chat_with_fallback(cfg: dict[str, Any], system: str, prompt: str, provider: str | None = None,
                       temperature: float = 0.2) -> tuple[AIResult, AIResult | None]:
    """
    Tenta o provedor principal; se falhar e ele não for o Ollama, tenta o Ollama local.
    Retorna (resultado_principal, resultado_fallback_ou_None).
    """
    primary = chat(cfg, system, prompt, provider=provider, temperature=temperature)
    if primary.ok or primary.provider == "ollama":
        return primary, None
    fallback = _call_ollama(cfg, system, prompt, temperature)
    return primary, fallback


async def achat(cfg: dict[str, Any], system: str, prompt: str, provider: str | None = None,
                temperature: float = 0.2) -> AIResult:
    """Versão assíncrona (executa em thread para não bloquear o event loop)."""
    return await asyncio.to_thread(chat, cfg, system, prompt, provider, temperature)


async def alist_ollama_models(cfg: dict[str, Any], host_override: str | None = None) -> dict[str, Any]:
    return await asyncio.to_thread(list_ollama_models, cfg, host_override)


def pull_ollama_model(host: str, model: str, timeout: float = 3600.0) -> tuple[bool, str]:
    """Executa o pull real do modelo no Ollama (bloqueante; chamar em background)."""
    try:
        resp = httpx.post(f"{validate_http_url(host)}/api/pull", json={"model": model, "stream": False}, timeout=timeout)
        if resp.status_code == 200:
            return True, f"Modelo '{model}' baixado com sucesso."
        return False, f"Ollama respondeu HTTP {resp.status_code}: {resp.text[:300]}"
    except (httpx.HTTPError, ValueError) as exc:
        return False, f"Falha no download do modelo '{model}': {exc}"


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Extrai o primeiro objeto JSON de uma resposta de LLM (aceita blocos ```json)."""
    import json
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None
