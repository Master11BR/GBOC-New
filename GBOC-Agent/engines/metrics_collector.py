#!/usr/bin/env python3
"""
📊 GBOC Agent - Coletor de Métricas e Estatísticas
Coleta e armazena métricas detalhadas de execução para análise e gráficos
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import json

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Coleta e armazena métricas detalhadas de execução
    """
    
    def __init__(self, core):
        self.core = core
        self._ensure_metrics_tables()
    
    def _ensure_metrics_tables(self):
        """Garante que tabelas de métricas existem (PostgreSQL)"""
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                # Tabela de métricas diárias agregadas
                cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_metrics (
                    id SERIAL PRIMARY KEY,
                    date TEXT NOT NULL UNIQUE,
                    total_executions INTEGER DEFAULT 0,
                    successful_executions INTEGER DEFAULT 0,
                    failed_executions INTEGER DEFAULT 0,
                    total_files_processed INTEGER DEFAULT 0,
                    total_bytes_processed BIGINT DEFAULT 0,
                    total_duration_seconds DOUBLE PRECISION DEFAULT 0,
                    avg_speed_mbps DOUBLE PRECISION DEFAULT 0,
                    errors_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)
                # Tabela de métricas por engine
                cur.execute("""
                CREATE TABLE IF NOT EXISTS engine_metrics (
                    id SERIAL PRIMARY KEY,
                    date TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    execution_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    total_bytes_processed BIGINT DEFAULT 0,
                    total_duration_seconds DOUBLE PRECISION DEFAULT 0,
                    avg_speed_mbps DOUBLE PRECISION DEFAULT 0,
                    errors_count INTEGER DEFAULT 0,
                    UNIQUE(date, engine)
                )
                """)
                # Tabela de métricas por tarefa
                cur.execute("""
                CREATE TABLE IF NOT EXISTS task_metrics (
                    id SERIAL PRIMARY KEY,
                    date TEXT NOT NULL,
                    task_id INTEGER NOT NULL,
                    execution_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    total_bytes_processed BIGINT DEFAULT 0,
                    total_duration_seconds DOUBLE PRECISION DEFAULT 0,
                    avg_speed_mbps DOUBLE PRECISION DEFAULT 0,
                    UNIQUE(date, task_id)
                )
                """)
                # Índices
                cur.execute("CREATE INDEX IF NOT EXISTS idx_daily_metrics_date ON daily_metrics(date)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_metrics_date ON engine_metrics(date)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_metrics_engine ON engine_metrics(engine)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_task_metrics_date ON task_metrics(date)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_task_metrics_task ON task_metrics(task_id)")
                cur.close()
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao criar tabelas de métricas: {e}")
    
    def record_execution(
        self,
        task_id: int,
        engine: str,
        status: str,
        files_processed: int,
        bytes_processed: int,
        duration_seconds: float,
        error_count: int = 0
    ):
        """
        Registra uma execução nas métricas
        
        Args:
            task_id: ID da tarefa
            engine: Engine usado (restic, kopia, etc)
            status: Status da execução (completed, failed)
            files_processed: Número de arquivos processados
            bytes_processed: Bytes processados
            duration_seconds: Duração em segundos
            error_count: Número de erros ocorridos
        """
        try:
            today = datetime.now().date().isoformat()
            
            # Calcular velocidade média (MB/s)
            speed_mbps = 0
            if duration_seconds > 0:
                speed_mbps = (bytes_processed / (1024 * 1024)) / duration_seconds
            
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                # Atualizar métricas diárias
                cur.execute("""
                INSERT INTO daily_metrics (
                    date, total_executions, successful_executions, failed_executions,
                    total_files_processed, total_bytes_processed, total_duration_seconds,
                    avg_speed_mbps, errors_count
                ) VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(date) DO UPDATE SET
                    total_executions = daily_metrics.total_executions + 1,
                    successful_executions = daily_metrics.successful_executions + %s,
                    failed_executions = daily_metrics.failed_executions + %s,
                    total_files_processed = daily_metrics.total_files_processed + %s,
                    total_bytes_processed = daily_metrics.total_bytes_processed + %s,
                    total_duration_seconds = daily_metrics.total_duration_seconds + %s,
                    avg_speed_mbps = (
                        (daily_metrics.avg_speed_mbps * daily_metrics.total_executions + %s)
                        / (daily_metrics.total_executions + 1)
                    ),
                    errors_count = daily_metrics.errors_count + %s
                """, (
                    today,
                    1 if status == 'completed' else 0,
                    1 if status == 'failed' else 0,
                    files_processed,
                    bytes_processed,
                    duration_seconds,
                    speed_mbps,
                    error_count,
                    # UPDATE values
                    1 if status == 'completed' else 0,
                    1 if status == 'failed' else 0,
                    files_processed,
                    bytes_processed,
                    duration_seconds,
                    speed_mbps,
                    error_count
                ))

                # Atualizar métricas por engine
                cur.execute("""
                INSERT INTO engine_metrics (
                    date, engine, execution_count, success_count,
                    total_bytes_processed, total_duration_seconds, avg_speed_mbps, errors_count
                ) VALUES (%s, %s, 1, %s, %s, %s, %s, %s)
                ON CONFLICT(date, engine) DO UPDATE SET
                    execution_count = engine_metrics.execution_count + 1,
                    success_count = engine_metrics.success_count + %s,
                    total_bytes_processed = engine_metrics.total_bytes_processed + %s,
                    total_duration_seconds = engine_metrics.total_duration_seconds + %s,
                    avg_speed_mbps = (
                        (engine_metrics.avg_speed_mbps * engine_metrics.execution_count + %s)
                        / (engine_metrics.execution_count + 1)
                    ),
                    errors_count = engine_metrics.errors_count + %s
                """, (
                    today, engine,
                    1 if status == 'completed' else 0,
                    bytes_processed, duration_seconds, speed_mbps, error_count,
                    # UPDATE values
                    1 if status == 'completed' else 0,
                    bytes_processed, duration_seconds, speed_mbps, error_count
                ))

                # Atualizar métricas por tarefa
                cur.execute("""
                INSERT INTO task_metrics (
                    date, task_id, execution_count, success_count,
                    total_bytes_processed, total_duration_seconds, avg_speed_mbps
                ) VALUES (%s, %s, 1, %s, %s, %s, %s)
                ON CONFLICT(date, task_id) DO UPDATE SET
                    execution_count = task_metrics.execution_count + 1,
                    success_count = task_metrics.success_count + %s,
                    total_bytes_processed = task_metrics.total_bytes_processed + %s,
                    total_duration_seconds = task_metrics.total_duration_seconds + %s,
                    avg_speed_mbps = (
                        (task_metrics.avg_speed_mbps * task_metrics.execution_count + %s)
                        / (task_metrics.execution_count + 1)
                    )
                """, (
                    today, task_id,
                    1 if status == 'completed' else 0,
                    bytes_processed, duration_seconds, speed_mbps,
                    # UPDATE values
                    1 if status == 'completed' else 0,
                    bytes_processed, duration_seconds, speed_mbps
                ))

                cur.close()
                conn.commit()
            
        except Exception as e:
            logger.error(f"Erro ao registrar métricas: {e}")
    
    def get_daily_metrics(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 365
    ) -> List[Dict[str, Any]]:
        """Busca métricas diárias"""
        try:
            with self.core.get_db_connection() as conn:
                query = "SELECT * FROM daily_metrics WHERE 1=1"
                params = []

                if start_date:
                    query += " AND date >= %s"
                    params.append(start_date)

                if end_date:
                    query += " AND date <= %s"
                    params.append(end_date)

                query += " ORDER BY date DESC LIMIT %s"
                params.append(limit)
                
                cursor = conn.cursor()
                cursor.execute(query, params)
                columns = [desc[0] for desc in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Erro ao buscar métricas diárias: {e}")
            return []
    
    def get_engine_comparison(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Compara eficiência entre engines"""
        try:
            with self.core.get_db_connection() as conn:
                query = """
                    SELECT 
                        engine,
                        SUM(execution_count) as total_executions,
                        SUM(success_count) as total_successes,
                        SUM(total_bytes_processed) as total_bytes,
                        SUM(total_duration_seconds) as total_duration,
                        AVG(avg_speed_mbps) as avg_speed,
                        SUM(errors_count) as total_errors
                    FROM engine_metrics
                    WHERE 1=1
                """
                params = []
                
                if start_date:
                    query += " AND date >= %s"
                    params.append(start_date)

                if end_date:
                    query += " AND date <= %s"
                    params.append(end_date)

                query += " GROUP BY engine ORDER BY total_executions DESC"
                
                cursor = conn.cursor()
                cursor.execute(query, params)
                columns = [desc[0] for desc in cursor.description]
                engines = [dict(zip(columns, row)) for row in cursor.fetchall()]
                
                # Calcular taxas de sucesso
                for engine in engines:
                    total = engine['total_executions'] or 0
                    successes = engine['total_successes'] or 0
                    engine['success_rate'] = (successes / total * 100) if total > 0 else 0
                    engine['total_bytes_gb'] = (engine['total_bytes'] or 0) / (1024**3)
                
                return {
                    "engines": engines,
                    "period": {
                        "start": start_date or "all",
                        "end": end_date or "all"
                    }
                }
        except Exception as e:
            logger.error(f"Erro ao comparar engines: {e}")
            return {"engines": [], "error": str(e)}
    
    def get_period_summary(
        self,
        period: str = "month"  # day, week, month, year
    ) -> Dict[str, Any]:
        """Resumo de um período específico"""
        try:
            now = datetime.now()
            
            if period == "day":
                start_date = now.date().isoformat()
                end_date = start_date
            elif period == "week":
                start_date = (now - timedelta(days=7)).date().isoformat()
                end_date = now.date().isoformat()
            elif period == "month":
                start_date = (now - timedelta(days=30)).date().isoformat()
                end_date = now.date().isoformat()
            elif period == "year":
                start_date = (now - timedelta(days=365)).date().isoformat()
                end_date = now.date().isoformat()
            else:
                start_date = None
                end_date = None
            
            metrics = self.get_daily_metrics(start_date, end_date)
            
            if not metrics:
                return {
                    "period": period,
                    "total_executions": 0,
                    "success_rate": 0,
                    "total_bytes_gb": 0,
                    "avg_speed_mbps": 0,
                    "errors_count": 0
                }
            
            total_executions = sum(m['total_executions'] for m in metrics)
            total_successes = sum(m['successful_executions'] for m in metrics)
            total_bytes = sum(m['total_bytes_processed'] for m in metrics)
            total_duration = sum(m['total_duration_seconds'] for m in metrics)
            total_errors = sum(m['errors_count'] for m in metrics)
            
            success_rate = (total_successes / total_executions * 100) if total_executions > 0 else 0
            avg_speed = (total_bytes / (1024 * 1024) / total_duration) if total_duration > 0 else 0
            
            return {
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
                "total_executions": total_executions,
                "successful_executions": total_successes,
                "failed_executions": total_executions - total_successes,
                "success_rate": round(success_rate, 2),
                "total_bytes_processed": total_bytes,
                "total_bytes_gb": round(total_bytes / (1024**3), 2),
                "total_duration_hours": round(total_duration / 3600, 2),
                "avg_speed_mbps": round(avg_speed, 2),
                "errors_count": total_errors,
                "days_count": len(metrics)
            }
        except Exception as e:
            logger.error(f"Erro ao gerar resumo: {e}")
            return {"error": str(e)}
