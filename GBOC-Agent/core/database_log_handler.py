#!/usr/bin/env python3
"""
Database Logging Handler
Grava logs no banco de dados PostgreSQL.
Usa conexão DEDICADA (não do pool) para evitar conflito com transações abortadas.
"""

import logging
import sys
import threading
from datetime import datetime
from typing import Optional

# Configuração de conexão dedicada para logs
_DB_CONFIG = {
    'dbname': 'gboc_agent',
    'user': 'postgres',
    'password': 'Stoms2025+',
    'host': 'localhost',
    'port': 5432,
}

class DatabaseLogHandler(logging.Handler):
    """Handler que grava logs no banco de dados PostgreSQL usando conexão dedicada."""

    def __init__(self, level=logging.INFO):
        super().__init__(level)
        self._conn = None
        self._lock = threading.Lock()
        self._ensure_table()

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
                cursor.close()
        except Exception as e:
            sys.stderr.write(f"Erro ao criar tabela system_logs: {e}\n")

    def emit(self, record):
        """Grava log no banco — uma única tentativa com conexão dedicada."""
        with self._lock:
            try:
                conn = self._get_conn()
                if conn is None:
                    return

                timestamp = datetime.fromtimestamp(record.created).isoformat()
                level = record.levelname
                source = record.name
                message = self.format(record)

                details = None
                if hasattr(record, 'details'):
                    details = str(record.details)
                elif record.exc_info:
                    details = self.formatter.formatException(record.exc_info) if self.formatter else str(record.exc_info)

                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO system_logs (timestamp, level, source, message, details)
                    VALUES (%s, %s, %s, %s, %s)
                """, (timestamp, level, source, message, details))
                cur.close()

            except Exception as e:
                # Conexão corrompida → fechar para recriar na próxima chamada
                try:
                    if self._conn:
                        self._conn.close()
                except Exception:
                    pass
                self._conn = None
                sys.stderr.write(f"Erro ao gravar log no banco: {e}\n")

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
