# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Module: Hermes Queue Engine — Store-and-Forward Offline Queue
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================
"""
Hermes Queue Engine — Pilar 1: Store-and-Forward Resilience

Garante que NENHUM evento, telemetria ou relatório de backup seja perdido,
mesmo que o servidor central ou a internet fiquem indisponíveis por horas ou dias.

Implementação:
  - SQLite em modo WAL (Write-Ahead Logging) para acesso concorrente e durabilidade
  - Confirmação de entrega por ACK (sequência numerada)
  - Burst Sync: descarrega toda a fila acumulada assim que a conexão é restaurada
  - Compressão zlib opcional por mensagem para minimizar a banda de burst sync
  - Limite configurável de tamanho da fila (por padrão 50.000 mensagens / ~500 MB)
"""

import os
import sqlite3
import zlib
import json
import logging
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger("hermes_queue_engine")

# Localização do banco da fila offline
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
QUEUE_DB_PATH = os.path.join(DATA_DIR, "hermes_queue.db")

# Limites de segurança
MAX_QUEUE_SIZE = int(os.getenv("HERMES_MAX_QUEUE_SIZE", "50000"))
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024  # 5 MB por mensagem


class HermesQueueEngine:
    """
    Motor de fila offline persistente do Hermes Agent.
    Thread-safe, durável e com suporte a burst sync.
    """

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._initialized = False
        self._init_db()

    # ------------------------------------------------------------------
    # Inicialização
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Cria o banco SQLite em modo WAL e as tabelas necessárias."""
        try:
            self._conn = sqlite3.connect(QUEUE_DB_PATH, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute("PRAGMA cache_size=10000")

            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS hermes_queue (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    sequence_number INTEGER UNIQUE,
                    event_type      TEXT    NOT NULL,
                    payload         BLOB    NOT NULL,
                    compressed      INTEGER NOT NULL DEFAULT 0,
                    enqueued_at     TEXT    NOT NULL,
                    attempts        INTEGER NOT NULL DEFAULT 0,
                    last_attempt    TEXT,
                    acked           INTEGER NOT NULL DEFAULT 0,
                    acked_at        TEXT
                )
            """)

            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS hermes_sequence (
                    id              INTEGER PRIMARY KEY DEFAULT 1,
                    next_sequence   INTEGER NOT NULL DEFAULT 1
                )
            """)

            self._conn.execute("""
                INSERT OR IGNORE INTO hermes_sequence (id, next_sequence) VALUES (1, 1)
            """)

            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS hermes_burst_sync_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    synced_at   TEXT NOT NULL,
                    messages    INTEGER NOT NULL DEFAULT 0,
                    bytes_sent  INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    success     INTEGER NOT NULL DEFAULT 1
                )
            """)

            self._conn.commit()
            self._initialized = True
            logger.info(f"[HERMES QUEUE] Banco SQLite WAL inicializado: {QUEUE_DB_PATH}")
        except Exception as e:
            logger.error(f"[HERMES QUEUE] Erro ao inicializar banco: {e}")

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    def enqueue(self, event_type: str, payload: Dict[str, Any], compress: bool = True) -> Optional[int]:
        """
        Adiciona uma mensagem à fila offline.

        Args:
            event_type: Tipo do evento (ex: 'backup.report', 'telemetry', 'alert')
            payload: Dicionário com os dados do evento
            compress: Se True, comprime o payload com zlib antes de armazenar

        Returns:
            sequence_number da mensagem ou None se falhou
        """
        if not self._initialized:
            logger.warning("[HERMES QUEUE] Banco não inicializado — enqueue ignorado")
            return None

        try:
            raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")

            if len(raw) > MAX_PAYLOAD_BYTES:
                logger.warning(f"[HERMES QUEUE] Payload muito grande ({len(raw)} bytes) — truncando")
                raw = raw[:MAX_PAYLOAD_BYTES]

            blob = zlib.compress(raw, level=6) if compress else raw
            compressed_flag = 1 if compress else 0

            with self._lock:
                # Verificar limite de tamanho da fila
                count_row = self._conn.execute(
                    "SELECT COUNT(*) FROM hermes_queue WHERE acked = 0"
                ).fetchone()
                if count_row and count_row[0] >= MAX_QUEUE_SIZE:
                    # Remover a mensagem mais antiga para abrir espaço (FIFO)
                    self._conn.execute(
                        "DELETE FROM hermes_queue WHERE id = (SELECT MIN(id) FROM hermes_queue WHERE acked = 0)"
                    )
                    logger.warning("[HERMES QUEUE] Fila cheia — removida mensagem mais antiga (FIFO)")

                # Obter próximo número de sequência
                seq_row = self._conn.execute(
                    "SELECT next_sequence FROM hermes_sequence WHERE id = 1"
                ).fetchone()
                seq = seq_row[0] if seq_row else 1
                self._conn.execute(
                    "UPDATE hermes_sequence SET next_sequence = ? WHERE id = 1", (seq + 1,)
                )

                self._conn.execute(
                    """INSERT INTO hermes_queue
                       (sequence_number, event_type, payload, compressed, enqueued_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (seq, event_type, blob, compressed_flag, datetime.now().isoformat())
                )
                self._conn.commit()

            logger.debug(f"[HERMES QUEUE] Enfileirado seq={seq} type={event_type} size={len(blob)}B compressed={compress}")
            return seq

        except Exception as e:
            logger.error(f"[HERMES QUEUE] Erro ao enfileirar evento '{event_type}': {e}")
            return None

    # ------------------------------------------------------------------
    # Peek / Dequeue para Burst Sync
    # ------------------------------------------------------------------

    def get_pending_batch(self, max_count: int = 500) -> List[Dict[str, Any]]:
        """
        Retorna um lote de mensagens pendentes (não entregues / não acked)
        para o Burst Sync ao servidor. Mensagens permanecem na fila até serem acked.
        """
        if not self._initialized:
            return []

        try:
            with self._lock:
                rows = self._conn.execute(
                    """SELECT id, sequence_number, event_type, payload, compressed, enqueued_at, attempts
                       FROM hermes_queue
                       WHERE acked = 0
                       ORDER BY sequence_number ASC
                       LIMIT ?""",
                    (max_count,)
                ).fetchall()

                messages = []
                for row in rows:
                    row_id, seq, event_type, blob, compressed, enqueued_at, attempts = row
                    try:
                        raw = zlib.decompress(blob) if compressed else blob
                        payload = json.loads(raw.decode("utf-8"))
                    except Exception:
                        payload = {"_raw_error": "decompress_failed"}

                    messages.append({
                        "queue_id": row_id,
                        "sequence_number": seq,
                        "event_type": event_type,
                        "payload": payload,
                        "enqueued_at": enqueued_at,
                        "attempts": attempts
                    })

                # Atualizar contador de tentativas
                ids = [m["queue_id"] for m in messages]
                if ids:
                    placeholders = ",".join("?" * len(ids))
                    self._conn.execute(
                        f"UPDATE hermes_queue SET attempts = attempts + 1, last_attempt = ? WHERE id IN ({placeholders})",
                        [datetime.now().isoformat()] + ids
                    )
                    self._conn.commit()

                return messages
        except Exception as e:
            logger.error(f"[HERMES QUEUE] Erro ao obter lote pendente: {e}")
            return []

    def ack_messages(self, sequence_numbers: List[int]) -> int:
        """
        Confirma a entrega de mensagens ao servidor (ack).
        Mensagens acked permanecem no banco por 7 dias para auditoria,
        depois são purgadas pelo GC automático.

        Returns:
            Número de mensagens confirmadas
        """
        if not sequence_numbers or not self._initialized:
            return 0
        try:
            with self._lock:
                placeholders = ",".join("?" * len(sequence_numbers))
                cursor = self._conn.execute(
                    f"UPDATE hermes_queue SET acked = 1, acked_at = ? WHERE sequence_number IN ({placeholders}) AND acked = 0",
                    [datetime.now().isoformat()] + sequence_numbers
                )
                self._conn.commit()
                count = cursor.rowcount
                logger.debug(f"[HERMES QUEUE] {count} mensagens confirmadas (acked)")
                return count
        except Exception as e:
            logger.error(f"[HERMES QUEUE] Erro no ack: {e}")
            return 0

    # ------------------------------------------------------------------
    # Burst Sync Log
    # ------------------------------------------------------------------

    def record_burst_sync(self, messages_synced: int, bytes_sent: int, duration_ms: int, success: bool = True) -> None:
        """Registra um evento de burst sync no log interno."""
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO hermes_burst_sync_log (synced_at, messages, bytes_sent, duration_ms, success) VALUES (?, ?, ?, ?, ?)",
                    (datetime.now().isoformat(), messages_synced, bytes_sent, duration_ms, 1 if success else 0)
                )
                self._conn.commit()
        except Exception as e:
            logger.warning(f"[HERMES QUEUE] Erro ao registrar burst sync: {e}")

    # ------------------------------------------------------------------
    # Garbage Collection
    # ------------------------------------------------------------------

    def run_gc(self, retain_acked_days: int = 7) -> int:
        """
        Remove mensagens acked mais antigas que `retain_acked_days` dias.

        Returns:
            Número de registros removidos
        """
        if not self._initialized:
            return 0
        try:
            with self._lock:
                cursor = self._conn.execute(
                    """DELETE FROM hermes_queue
                       WHERE acked = 1
                         AND acked_at < datetime('now', ?)""",
                    (f"-{retain_acked_days} days",)
                )
                self._conn.commit()
                removed = cursor.rowcount
                if removed > 0:
                    logger.info(f"[HERMES QUEUE] GC: {removed} registros acked removidos")
                return removed
        except Exception as e:
            logger.error(f"[HERMES QUEUE] Erro no GC: {e}")
            return 0

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Retorna o status atual da fila offline."""
        if not self._initialized:
            return {"status": "uninitialized", "error": "SQLite database not initialized"}

        try:
            with self._lock:
                pending = self._conn.execute(
                    "SELECT COUNT(*) FROM hermes_queue WHERE acked = 0"
                ).fetchone()[0]

                acked = self._conn.execute(
                    "SELECT COUNT(*) FROM hermes_queue WHERE acked = 1"
                ).fetchone()[0]

                oldest_row = self._conn.execute(
                    "SELECT enqueued_at FROM hermes_queue WHERE acked = 0 ORDER BY sequence_number ASC LIMIT 1"
                ).fetchone()

                last_sync_row = self._conn.execute(
                    "SELECT synced_at, messages, bytes_sent, success FROM hermes_burst_sync_log ORDER BY id DESC LIMIT 1"
                ).fetchone()

                db_size_bytes = os.path.getsize(QUEUE_DB_PATH) if os.path.exists(QUEUE_DB_PATH) else 0

            return {
                "status": "operational",
                "queue_db_path": QUEUE_DB_PATH,
                "queue_db_size_mb": round(db_size_bytes / 1024 / 1024, 2),
                "pending_messages": pending,
                "acked_messages": acked,
                "oldest_pending_at": oldest_row[0] if oldest_row else None,
                "max_queue_size": MAX_QUEUE_SIZE,
                "last_burst_sync": {
                    "at": last_sync_row[0],
                    "messages": last_sync_row[1],
                    "bytes_sent": last_sync_row[2],
                    "success": bool(last_sync_row[3])
                } if last_sync_row else None
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def close(self) -> None:
        """Fecha a conexão com o banco SQLite."""
        try:
            if self._conn:
                self._conn.close()
                self._conn = None
        except Exception:
            pass


# Instância global singleton
hermes_queue_engine = HermesQueueEngine()
