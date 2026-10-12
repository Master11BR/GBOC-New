#!/usr/bin/env python3
"""
Database Logging Handler
Grava logs no banco de dados PostgreSQL.
Usa conexão DEDICADA (não do pool) para evitar conflito com transações abortadas.
"""

import logging
import queue
import sys
import threading
import time
from datetime import datetime
from typing import Optional

# Configuração de conexão dedicada para logs
_DB_CONFIG = {
    'dbname': 'gboc_agent',
    'user': 'postgres',
    'password': 'Stoms2025+',
    'host': 'localhost',
    'port': 5432,
    # Log nunca pode travar o sistema: se system_logs estiver bloqueada (ex.: migração com
    # CREATE INDEX na mesma inicialização), o INSERT desiste em 2 s em vez de esperar para sempre.
    'options': '-c lock_timeout=2000 -c statement_timeout=5000',
    'connect_timeout': 5,
}

_guard = threading.local()


def _raw_stderr(msg: str) -> None:
    """Escreve no stderr ORIGINAL. sys.stderr é redirecionado para o logger no agent_gboc.py;
    usá-lo aqui reentraria em emit() com self._lock já preso (travamento na mesma thread)."""
    try:
        (sys.__stderr__ or sys.stdout).write(msg)
    except Exception:
        pass

class DatabaseLogHandler(logging.Handler):
    """Handler que grava logs no banco de dados PostgreSQL usando conexão dedicada."""

    def __init__(self, level=logging.INFO):
        super().__init__(level)
        self._conn = None
        self._lock = threading.Lock()
        self._pause_until = 0.0   # após falha (lock/timeout), pausa a gravação no banco por alguns segundos
        # Quem loga só enfileira; uma thread grava em lote. Antes cada linha de log fazia um INSERT síncrono
        # na thread de quem logou — inclusive dentro de rotas async, segurando o event loop do Agente.
        self._queue: "queue.Queue" = queue.Queue(maxsize=5000)
        self._dropped = 0
        self._ensure_table()
        threading.Thread(target=self._writer, name="gboc-db-log-writer", daemon=True).start()

    # ------------------------------------------------------------------ #
    def _get_conn(self):
        """Obtém (ou recria) a conexão dedicada para logs."""
        import psycopg2
        if self._conn is None or self._conn.closed:
            try:
                self._conn = psycopg2.connect(**_DB_CONFIG)
                self._conn.autocommit = True  # cada INSERT é atômico
            except Exception:
                self._conn = None
        return self._conn

    def _ensure_table(self):
        """Garante que tabela system_logs existe"""
        try:
            conn = self._get_conn()
            if conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS system_logs (
                        id SERIAL PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        level TEXT NOT NULL,
                        source TEXT,
                        message TEXT NOT NULL,
                        details TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs (timestamp DESC)")
                cursor.close()
        except Exception as e:
            _raw_stderr(f"Erro ao criar tabela system_logs: {e}\n")

    def emit(self, record):
        """Grava log no banco — uma única tentativa com conexão dedicada."""
        if getattr(_guard, 'active', False):   # log gerado durante a própria gravação: não reentrar
            return
        _guard.active = True
        try:
            self._emit(record)
        finally:
            _guard.active = False

    def _emit(self, record):
        try:
            timestamp = datetime.fromtimestamp(record.created).isoformat()
            message = self.format(record)
            details = None
            if hasattr(record, 'details'):
                details = str(record.details)
            elif record.exc_info:
                details = self.formatter.formatException(record.exc_info) if self.formatter else str(record.exc_info)
            self._queue.put_nowait((timestamp, record.levelname, record.name, message, details))
        except queue.Full:
            self._dropped += 1      # banco parado por muito tempo: descarta (console/arquivo continuam com o log)
        except Exception:
            pass

    def _writer(self):
        """Thread única que grava os logs enfileirados em lote."""
        pending = []
        while True:
            try:
                pending.append(self._queue.get(timeout=2) if not pending else self._queue.get_nowait())
                while len(pending) < 500:
                    pending.append(self._queue.get_nowait())
            except queue.Empty:
                pass
            if not pending:
                continue
            wait = self._pause_until - time.monotonic()
            if wait > 0:                       # falha recente: espera a pausa e grava o que acumulou
                time.sleep(wait)
            _guard.active = True
            try:
                if self._write_batch(pending):
                    pending = []
                elif len(pending) > 5000:      # banco fora por muito tempo: mantém só os mais recentes
                    self._dropped += len(pending) - 5000
                    pending = pending[-5000:]
            finally:
                _guard.active = False

    def _write_batch(self, rows):
        with self._lock:
            try:
                conn = self._get_conn()
                if conn is None:
                    self._pause_until = time.monotonic() + 15
                    return False
                if self._dropped:
                    rows.append((datetime.now().isoformat(), 'WARNING', 'gboc.db_log',
                                 f"{self._dropped} registro(s) de log descartado(s): banco indisponível", None))
                    self._dropped = 0
                cur = conn.cursor()
                cur.executemany("""
                    INSERT INTO system_logs (timestamp, level, source, message, details)
                    VALUES (%s, %s, %s, %s, %s)
                """, rows)
                cur.close()
                return True

            except Exception as e:
                # Conexão corrompida → fechar para recriar na próxima chamada
                try:
                    if self._conn:
                        self._conn.close()
                except Exception:
                    pass
                self._conn = None
                self._pause_until = time.monotonic() + 15
                _raw_stderr(f"Erro ao gravar log no banco (nova tentativa em 15 s): {e}\n")
                return False

    def close(self):
        """Fecha handler e conexão dedicada"""
        try:
            if self._conn and not self._conn.closed:
                self._conn.close()
        except Exception:
            pass
        self._conn = None
        super().close()


def setup_database_logging(logger_name: Optional[str] = None, enable_logstash: bool = False, logstash_host: str = 'localhost', logstash_port: int = 5044):
    """
    Configura logging para banco de dados PostgreSQL e opcionalmente Logstash
    
    Args:
        logger_name: Nome do logger (None = root logger)
        enable_logstash: Se deve enviar logs para Logstash
        logstash_host: Host do Logstash
        logstash_port: Porta do Logstash
    
    Returns:
        Logger configurado
    """
    logger = logging.getLogger(logger_name)
    
    # Criar handler do banco
    db_handler = DatabaseLogHandler()
    db_handler.setLevel(logging.INFO)
    
    # Formato simples (detalhes vão para coluna 'details')
    formatter = logging.Formatter('%(message)s')
    db_handler.setFormatter(formatter)
    
    # Adicionar ao logger
    logger.addHandler(db_handler)
    
    # Adicionar Logstash se habilitado
    if enable_logstash:
        try:
            from core.logstash_handler import LogstashHandler
            logstash_handler = LogstashHandler(host=logstash_host, port=logstash_port)
            logstash_handler.setLevel(logging.INFO)
            logstash_handler.setFormatter(formatter)
            logger.addHandler(logstash_handler)
        except ImportError:
            sys.stderr.write("Logstash handler não encontrado, ignorando\n")
    
    return logger


# ========================================
# EXEMPLO DE USO
# ========================================

if __name__ == "__main__":
    # Setup
    logger = setup_database_logging("GBOC")
    logger.setLevel(logging.INFO)
    
    # Testar logs
    logger.info("Sistema iniciado")
    logger.warning("Repositório sem snapshots")
    logger.error("Falha ao conectar com servidor")
    
    try:
        1 / 0
    except Exception as e:
        logger.exception("Erro crítico no backup")
    
    print("✅ Logs gravados no banco!")
