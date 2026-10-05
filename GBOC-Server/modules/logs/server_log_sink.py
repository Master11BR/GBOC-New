"""
GBOC Server — grava os avisos e erros do PRÓPRIO servidor em agent_logs (agent_id NULL = "Servidor"),
para aparecerem em Logs Globais, Jobs com Falha e nos relatórios junto com os logs dos agentes.

* Nível mínimo: WARNING (configurável por GBOC_SERVER_LOG_LEVEL=INFO|WARNING|ERROR).
* Não bloqueia quem loga: registros vão para uma fila e uma thread grava em lote a cada 2 s.
* Mensagens idênticas repetidas em menos de 60 s são agrupadas ("repetido N vez(es)").
* Registros gerados durante a própria gravação são ignorados (sem recursão).
* Enquanto o banco não estiver disponível (início do serviço) os registros ficam na fila (até 5.000).
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
import traceback
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple

_QUEUE: "queue.Queue[Tuple]" = queue.Queue(maxsize=5000)
_LOCAL = threading.local()
_IGNORE_PREFIXES = ("uvicorn.access", "gboc.server_log_sink", "psycopg2", "urllib3", "asyncio", "multipart", "watchfiles")
_installed = False
_dropped = 0


class ServerDBLogHandler(logging.Handler):
    def __init__(self, level: int = logging.WARNING):
        super().__init__(level)
        self._recent: Dict[Tuple[str, str], list] = {}
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        global _dropped
        if getattr(_LOCAL, "busy", False) or record.name.startswith(_IGNORE_PREFIXES):
            return
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        key = (record.name, msg[:300])
        now = time.monotonic()
        with self._lock:
            seen = self._recent.get(key)
            if seen and now - seen[0] < 60:
                seen[1] += 1
                return
            repeated = seen[1] if seen else 0
            self._recent[key] = [now, 0]
            if len(self._recent) > 2000:
                self._recent = {k: v for k, v in self._recent.items() if now - v[0] < 60}
        details = None
        if record.exc_info:
            try:
                details = "".join(traceback.format_exception(*record.exc_info))[-4000:]
            except Exception:
                details = None
        if repeated:
            msg = f"{msg}  (repetido {repeated} vez(es) no último minuto)"
        level = {"WARN": "WARNING", "FATAL": "CRITICAL"}.get(record.levelname, record.levelname)
        try:
            _QUEUE.put_nowait((level, f"server.{record.name}"[:200], msg[:8000], details,
                               datetime.fromtimestamp(record.created)))
        except queue.Full:
            _dropped += 1


def _writer(get_conn: Callable, release_conn: Callable) -> None:
    global _dropped
    pending = []
    while True:
        try:
            pending.append(_QUEUE.get(timeout=2))
            while len(pending) < 500:
                pending.append(_QUEUE.get_nowait())
        except queue.Empty:
            pass
        if not pending:
            continue
        _LOCAL.busy = True
        conn = None
        try:
            conn = get_conn()
            cur = conn.cursor()
            if _dropped:
                pending.append(("WARNING", "server.gboc.log_sink", f"{_dropped} registro(s) de log do servidor descartado(s) (fila cheia)",
                                None, datetime.now()))
                _dropped = 0
            cur.executemany("INSERT INTO agent_logs (agent_id, level, source, message, details, timestamp) "
                            "VALUES (NULL, %s, %s, %s, %s, %s)", pending)
            conn.commit()
            cur.close()
            pending = []
        except Exception:
            try:
                if conn is not None:
                    conn.rollback()
            except Exception:
                pass
            if len(pending) > 5000:
                pending = pending[-5000:]
            time.sleep(5)                   # banco indisponível: mantém e tenta de novo
        finally:
            if conn is not None:
                try:
                    release_conn(conn)
                except Exception:
                    pass
            _LOCAL.busy = False


def install(get_conn: Callable, release_conn: Callable, level: Optional[str] = None) -> bool:
    """Anexa o handler ao logger raiz e ao uvicorn.error (que não propaga). Idempotente."""
    global _installed
    if _installed or os.getenv("GBOC_SERVER_LOG_TO_DB", "1") == "0":
        return False
    lvl = getattr(logging, (level or os.getenv("GBOC_SERVER_LOG_LEVEL") or "WARNING").upper(), logging.WARNING)
    h = ServerDBLogHandler(lvl)
    logging.getLogger().addHandler(h)
    logging.getLogger("uvicorn.error").addHandler(h)     # duplicatas eventuais são agrupadas pelo filtro de 60 s
    threading.Thread(target=_writer, args=(get_conn, release_conn), name="gboc-server-log-sink", daemon=True).start()
    _installed = True
    return True
