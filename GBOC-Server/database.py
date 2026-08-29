"""
GBOC Server - Database Utils
Funções auxiliares para operações com PostgreSQL
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
from typing import Optional, List, Dict, Any, Callable
from config import DB_CONFIG, DB_POOL_MIN_CONN, DB_POOL_MAX_CONN, DB_QUERY_TIMEOUT, RETENTION_POLICIES
from logger import setup_logger
from datetime import datetime, timedelta

logger = setup_logger(__name__)

class DatabaseManager:
    """Gerenciador de conexões e operações com banco de dados"""

    def __init__(self):
        self.pool: Optional[pool.SimpleConnectionPool] = None

    def initialize(self) -> bool:
        """
        Inicializa o pool de conexões

        Returns:
            True se inicializado com sucesso
        """
        try:
            logger.info("Inicializando pool PostgreSQL...")
            self.pool = psycopg2.pool.SimpleConnectionPool(
                minconn=DB_POOL_MIN_CONN,
                maxconn=DB_POOL_MAX_CONN,
                **DB_CONFIG
            )
            logger.info(f"Pool PostgreSQL inicializado ({DB_POOL_MIN_CONN}-{DB_POOL_MAX_CONN} conexões)")
            return True
        except Exception as e:
            logger.error(f"Erro ao inicializar pool PostgreSQL: {e}")
            return False

    def get_connection(self) -> Optional[psycopg2.extensions.connection]:
        """
        Obtém uma conexão do pool

        Returns:
            Conexão PostgreSQL ou None se falhar
        """
        if not self.pool:
            self.initialize()
        if not self.pool:
            logger.error("Pool não inicializado")
            return None

        try:
            conn = self.pool.getconn()
            conn.set_client_encoding("UTF8")
            return conn
        except Exception as e:
            logger.error(f"Erro ao obter conexão do pool: {e}")
            return None

    def release_connection(self, conn: psycopg2.extensions.connection) -> None:
        """
        Retorna uma conexão ao pool

        Args:
            conn: Conexão a devolver
        """
        if self.pool and conn:
            try:
                self.pool.putconn(conn)
            except Exception as e:
                logger.error(f"Erro ao devolver conexão ao pool: {e}")

    def close_all(self) -> None:
        """Fecha todas as conexões do pool"""
        if self.pool:
            try:
                self.pool.closeall()
                logger.info("Pool PostgreSQL fechado")
            except Exception as e:
                logger.error(f"Erro ao fechar pool: {e}")

    def execute_query(
        self,
        query: str,
        params: tuple = (),
        fetch_one: bool = False,
        fetch_all: bool = True,
        dict_cursor: bool = False
    ) -> Optional[Any]:
        """
        Executa uma query e retorna o resultado

        Args:
            query: SQL query
            params: Parâmetros (use %s para placeholders)
            fetch_one: Se True, retorna apenas uma linha
            fetch_all: Se True, retorna todas as linhas
            dict_cursor: Se True, usa RealDictCursor

        Returns:
            Resultado da query ou None se falhar
        """
        conn = None
        try:
            conn = self.get_connection()
            if not conn:
                return None

            cursor_class = RealDictCursor if dict_cursor else None
            cur = conn.cursor(cursor_factory=cursor_class)
            cur.execute(query, params)

            if fetch_one:
                result = cur.fetchone()
            elif fetch_all:
                result = cur.fetchall()
            else:
                conn.commit()
                result = cur.rowcount

            cur.close()
            return result

        except Exception as e:
            logger.error(f"Erro ao executar query: {e}")
            if conn:
                conn.rollback()
            return None

        finally:
            if conn:
                self.release_connection(conn)

    def execute_update(self, query: str, params: tuple = ()) -> int:
        """
        Executa um UPDATE/INSERT/DELETE e retorna linhas afetadas

        Args:
            query: SQL query
            params: Parâmetros

        Returns:
            Número de linhas afetadas
        """
        conn = None
        try:
            conn = self.get_connection()
            if not conn:
                return 0

            cur = conn.cursor()
            cur.execute(query, params)
            conn.commit()

            rows_affected = cur.rowcount
            cur.close()
            return rows_affected

        except Exception as e:
            logger.error(f"Erro ao executar update: {e}")
            if conn:
                conn.rollback()
            return 0

        finally:
            if conn:
                self.release_connection(conn)

    def create_index_if_not_exists(self, table: str, index_name: str, columns: str) -> bool:
        """
        Cria um índice se não existir

        Args:
            table: Nome da tabela
            index_name: Nome do índice
            columns: Colunas (ex: "(agent_id, timestamp)")

        Returns:
            True se criado ou já existia
        """
        try:
            query = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} {columns}"
            self.execute_query(query, fetch_all=False)
            logger.info(f"Índice criado/verificado: {index_name}")
            return True
        except Exception as e:
            logger.error(f"Erro ao criar índice {index_name}: {e}")
            return False

    def cleanup_old_data(self) -> None:
        """
        Limpa dados antigos baseado em política de retenção
        """
        try:
            logger.info("Iniciando limpeza de dados antigos...")

            # Limpar métricas antigas
            if "metrics" in RETENTION_POLICIES:
                days = RETENTION_POLICIES["metrics"]
                query = f"DELETE FROM agent_metrics WHERE timestamp < NOW() - INTERVAL '{days} days'"
                rows = self.execute_update(query)
                logger.info(f"Deletadas {rows} métricas antigas (>{days} dias)")

            # Limpar logs antigos
            if "logs" in RETENTION_POLICIES:
                days = RETENTION_POLICIES["logs"]
                query = f"DELETE FROM agent_logs WHERE timestamp < NOW() - INTERVAL '{days} days'"
                rows = self.execute_update(query)
                logger.info(f"Deletados {rows} logs antigos (>{days} dias)")

            # Limpar eventos antigos
            if "events" in RETENTION_POLICIES:
                days = RETENTION_POLICIES["events"]
                query = f"DELETE FROM system_events WHERE created_at < NOW() - INTERVAL '{days} days'"
                rows = self.execute_update(query)
                logger.info(f"Deletados {rows} eventos antigos (>{days} dias)")

        except Exception as e:
            logger.error(f"Erro ao limpar dados antigos: {e}")

# Instância global
db_manager = DatabaseManager()
