#!/usr/bin/env python3
"""
GBOC Agent 13.2.0 - Database Wrapper
PostgreSQL exclusivo via psycopg2
"""

import logging
from typing import Optional
import os

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


def get_db_connection():
    """Obter conexão com PostgreSQL"""
    try:
        conn = psycopg2.connect(
            host=os.getenv('GBOC_DB_HOST', 'localhost'),
            port=os.getenv('GBOC_DB_PORT', '5432'),
            database=os.getenv('GBOC_DB_NAME', 'gboc'),
            user=os.getenv('GBOC_DB_USER', 'gboc'),
            password=os.getenv('GBOC_DB_PASSWORD', '')
        )
        conn.autocommit = False
        return conn
    except Exception as e:
        logger.error(f"Erro ao conectar ao PostgreSQL: {e}")
        raise


class DatabaseConnection:
    """Wrapper de conexão PostgreSQL"""

    def connect(self):
        return get_db_connection()

    def execute(self, query: str, params: Optional[tuple] = None):
        """Executar query"""
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            conn.commit()
            return cursor
        finally:
            conn.close()

    def fetchone(self, query: str, params: Optional[tuple] = None):
        """Buscar um resultado"""
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            return cursor.fetchone()
        finally:
            conn.close()

    def fetchall(self, query: str, params: Optional[tuple] = None):
        """Buscar todos resultados"""
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            return cursor.fetchall()
        finally:
            conn.close()


# Instância global
db = DatabaseConnection()


def init_schema():
    """Inicializar schema básico no PostgreSQL"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Tabela de backups
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backups (
                id SERIAL PRIMARY KEY,
                repository_id INTEGER,
                status TEXT,
                start_time TIMESTAMPTZ,
                end_time TIMESTAMPTZ,
                files_processed INTEGER DEFAULT 0,
                size_mb REAL DEFAULT 0,
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Tabela de repositórios
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS repositories (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE,
                path TEXT,
                engine TEXT DEFAULT 'kopia',
                status TEXT DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Tabela de tarefas
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                name TEXT,
                repository_id INTEGER,
                schedule TEXT,
                enabled INTEGER DEFAULT 1,
                last_run TIMESTAMPTZ,
                next_run TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Tabela de logs do sistema
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id SERIAL PRIMARY KEY,
                level TEXT,
                message TEXT,
                source TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        conn.commit()
        logger.info("Schema PostgreSQL inicializado")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao inicializar schema PostgreSQL: {e}")
        raise
    finally:
        conn.close()


try:
    init_schema()
except Exception as e:
    logger.error(f"Erro ao inicializar banco de dados: {e}")

