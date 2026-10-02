"""
GBOC Agent — Chave de Pareamento Agente <-> Server.

A mesma chave é configurada no Agente (Configurações > Servidor Central, campo "Chave de
pareamento") e exibida no Server (Configurações Gerais > Pareamento de Agentes).

  * Agente -> Server: enviada no cabeçalho ``X-GBOC-Agent-Key`` (heartbeat, sync, websocket).
  * Server -> Agente: o Agente só aceita chamadas sem sessão (RMM, ransomware, proxy)
    quando o cabeçalho traz a chave configurada.

A chave legada ``gboc-local-server-key`` (padrão antigo) nunca é aceita.
Pode ser fixada pela variável de ambiente ``GBOC_AGENT_PAIRING_KEY``.
"""
import hmac
import os
from typing import Dict, Optional

AGENT_KEY_HEADER = "X-GBOC-Agent-Key"
AGENT_ID_HEADER = "X-GBOC-Agent-Id"
LEGACY_DEFAULT_KEY = "gboc-local-server-key"
_REJECTED_KEYS = {"", LEGACY_DEFAULT_KEY}


def get_configured_key() -> str:
    env_key = (os.getenv("GBOC_AGENT_PAIRING_KEY") or "").strip()
    if env_key:
        return env_key
    try:
        from server_config import config_manager
        return (config_manager.get_api_key() or "").strip()
    except Exception:
        return ""


def is_paired() -> bool:
    return get_configured_key() not in _REJECTED_KEYS


def is_valid_server_key(candidate: Optional[str]) -> bool:
    candidate = (candidate or "").strip()
    key = get_configured_key()
    if candidate in _REJECTED_KEYS or key in _REJECTED_KEYS:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), key.encode("utf-8"))


def request_has_valid_server_key(headers) -> bool:
    try:
        return is_valid_server_key(headers.get(AGENT_KEY_HEADER))
    except Exception:
        return False


def outbound_headers(agent_id: Optional[str] = None, api_key: Optional[str] = None) -> Dict[str, str]:
    key = (api_key if api_key is not None else get_configured_key()) or ""
    headers: Dict[str, str] = {}
    if key and key not in _REJECTED_KEYS:
        headers[AGENT_KEY_HEADER] = key
    if agent_id:
        headers[AGENT_ID_HEADER] = str(agent_id)
    return headers
