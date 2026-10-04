"""
GBOC Server — Chave de Pareamento Server <-> Agente.

Server e Agente podem estar em máquinas diferentes. Toda chamada entre eles carrega o
cabeçalho ``X-GBOC-Agent-Key``:

  * Agente -> Server (heartbeat, sync, websocket): o Server valida a chave.
  * Server -> Agente (RMM, ransomware, proxy): o Agente valida a mesma chave.

A chave é gerada automaticamente no primeiro uso (``secrets.token_urlsafe``) e guardada
na tabela ``server_secrets`` (fora de ``server_settings`` para não vazar em export/listagem).
Pode ser fixada pela variável de ambiente ``GBOC_AGENT_PAIRING_KEY``.
A chave legada ``gboc-local-server-key`` nunca é aceita.
"""
import hmac
import logging
import os
import secrets
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger("gboc_agent_pairing")

AGENT_KEY_HEADER = "X-GBOC-Agent-Key"
AGENT_ID_HEADER = "X-GBOC-Agent-Id"
_SECRET_NAME = "agent_pairing_key"
_REJECTED_KEYS = {"", "gboc-local-server-key"}
_CACHE_TTL = 60.0

_lock = threading.Lock()
_cache: Dict[str, object] = {"key": None, "ts": 0.0}


def _db():
    from database import db_manager
    return db_manager


def _ensure_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS server_secrets (
            name VARCHAR(100) PRIMARY KEY,
            value TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            rotated_at TIMESTAMP
        )
        """
    )


def _new_key() -> str:
    return "gboc_pk_" + secrets.token_urlsafe(32)


def get_pairing_key() -> Optional[str]:
    """Retorna a chave de pareamento atual (gera na primeira chamada). None se o banco estiver indisponível."""
    env_key = (os.getenv("GBOC_AGENT_PAIRING_KEY") or "").strip()
    if env_key and env_key not in _REJECTED_KEYS:
        return env_key

    now = time.time()
    with _lock:
        if _cache["key"] and now - float(_cache["ts"]) < _CACHE_TTL:
            return str(_cache["key"])

        dbm = _db()
        conn = None
        try:
            conn = dbm.get_connection()
            if conn is None:
                return _cache["key"]  # type: ignore[return-value]
            cur = conn.cursor()
            _ensure_table(cur)
            cur.execute("SELECT value FROM server_secrets WHERE name = %s", (_SECRET_NAME,))
            row = cur.fetchone()
            if row and row[0]:
                key = row[0]
            else:
                key = _new_key()
                cur.execute(
                    "INSERT INTO server_secrets (name, value) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                    (_SECRET_NAME, key),
                )
                cur.execute("SELECT value FROM server_secrets WHERE name = %s", (_SECRET_NAME,))
                key = cur.fetchone()[0]
                logger.info("[PAIRING] Chave de pareamento de agentes gerada.")
            conn.commit()
            cur.close()
            _cache.update(key=key, ts=now)
            return key
        except Exception as exc:
            logger.error(f"[PAIRING] Falha ao ler chave de pareamento: {exc}")
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return _cache["key"]  # type: ignore[return-value]
        finally:
            if conn is not None:
                dbm.release_connection(conn)


def rotate_pairing_key() -> str:
    """Gera uma nova chave. Todos os agentes precisarão receber a nova chave."""
    if (os.getenv("GBOC_AGENT_PAIRING_KEY") or "").strip():
        raise RuntimeError("Chave definida por GBOC_AGENT_PAIRING_KEY; altere a variável de ambiente.")
    dbm = _db()
    conn = dbm.get_connection()
    if conn is None:
        raise RuntimeError("Banco de dados indisponível")
    try:
        cur = conn.cursor()
        _ensure_table(cur)
        key = _new_key()
        cur.execute(
            """
            INSERT INTO server_secrets (name, value, rotated_at) VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value, rotated_at = CURRENT_TIMESTAMP
            """,
            (_SECRET_NAME, key),
        )
        conn.commit()
        cur.close()
        with _lock:
            _cache.update(key=key, ts=time.time())
        logger.warning("[PAIRING] Chave de pareamento rotacionada.")
        return key
    except Exception:
        conn.rollback()
        raise
    finally:
        dbm.release_connection(conn)


def is_valid_agent_key(candidate: Optional[str]) -> bool:
    candidate = (candidate or "").strip()
    if candidate in _REJECTED_KEYS:
        return False
    key = get_pairing_key()
    if not key:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), key.encode("utf-8"))


def request_has_valid_agent_key(headers) -> bool:
    try:
        return is_valid_agent_key(headers.get(AGENT_KEY_HEADER) or headers.get(AGENT_KEY_HEADER.lower()))
    except Exception:
        return False


def agent_headers() -> Dict[str, str]:
    """Cabeçalhos para chamadas Server -> Agente."""
    key = get_pairing_key()
    return {AGENT_KEY_HEADER: key} if key else {}


def mask_key(key: Optional[str]) -> str:
    if not key:
        return ""
    return f"{key[:10]}…{key[-4:]}" if len(key) > 16 else "***"


def resolve_agent_address(agent_id: str) -> Optional[Dict[str, object]]:
    """IP/porta do agente a partir da tabela agents (atualizada pelo heartbeat). None se desconhecido."""
    dbm = _db()
    conn = None
    try:
        conn = dbm.get_connection()
        if conn is None:
            return None
        cur = conn.cursor()
        cur.execute("SELECT ip_address, hostname FROM agents WHERE agent_id = %s OR hostname = %s LIMIT 1",
                    (agent_id, agent_id))
        row = cur.fetchone()
        cur.close()
        if not row or not row[0]:
            return None
        from modules.agents.remote_mgmt import split_host_port
        host, port = split_host_port(row[0])
        return {"ip": host, "port": port, "hostname": row[1]}
    except Exception as exc:
        logger.warning(f"[PAIRING] Falha ao resolver endereço do agente '{agent_id}': {exc}")
        return None
    finally:
        if conn is not None:
            dbm.release_connection(conn)
