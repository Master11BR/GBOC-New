#!/usr/bin/env python3
"""GBOC Agent - API Statistics"""
from fastapi import APIRouter, Query
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/statistics", tags=["statistics"])

@router.get("/")
async def get_statistics():
    """Retorna estatísticas gerais"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        stats = {
            "repositories": 0,
            "tasks": 0,
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "total_backup_size": 0
        }

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM repositories")
            stats['repositories'] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM tasks")
            stats['tasks'] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM task_executions")
            stats['total_executions'] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM task_executions WHERE status = 'completed'")
            stats['successful_executions'] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM task_executions WHERE status = 'failed'")
            stats['failed_executions'] = cursor.fetchone()[0]

        return {"status": "success", "statistics": stats}
    except Exception as e:
        logger.error(f"❌ Statistics error: {e}", exc_info=True)
        return {"status": "error", "statistics": {}}

@router.get("/summary")
async def get_statistics_summary(period: str = Query("month", description="Período: day, week, month, year")):
    """Retorna um resumo de estatísticas para o período especificado"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        now = datetime.now()
        if period == "day":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start_date = now - timedelta(days=7)
        elif period == "month":
            start_date = now - timedelta(days=30)
        elif period == "year":
            start_date = now - timedelta(days=365)
        else:
            start_date = now - timedelta(days=30)

        start_date_str = start_date.isoformat()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM task_executions WHERE started_at::TIMESTAMPTZ >= %s", (start_date_str,))
            total_executions = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM task_executions WHERE status = 'completed' AND started_at::TIMESTAMPTZ >= %s", (start_date_str,))
            successful_executions = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(bytes_processed) FROM task_executions WHERE status = 'completed' AND started_at::TIMESTAMPTZ >= %s", (start_date_str,))
            total_bytes = cursor.fetchone()[0] or 0

            success_rate = (successful_executions / total_executions * 100) if total_executions > 0 else 0

            avg_speed = 0
            if successful_executions > 0:
                cursor.execute("""
                    SELECT 
                        bytes_processed,
                        (EXTRACT(EPOCH FROM (completed_at::TIMESTAMPTZ)) - EXTRACT(EPOCH FROM (started_at::TIMESTAMPTZ)))
                    FROM task_executions 
                    WHERE status = 'completed' AND started_at::TIMESTAMPTZ >= %s AND bytes_processed > 0 AND completed_at IS NOT NULL AND started_at IS NOT NULL
                """, (start_date_str,))
                speed_results = cursor.fetchall()

                if speed_results:
                    total_speed = sum(b / d for b, d in speed_results if d and d > 0 and b is not None)
                    avg_speed = total_speed / len(speed_results) / (1024 * 1024)  # MB/s

            return {
                "status": "success",
                "total_executions": total_executions,
                "successful_executions": successful_executions,
                "success_rate": success_rate,
                "total_bytes": total_bytes,
                "total_bytes_gb": total_bytes / (1024**3),
                "avg_speed_mbps": avg_speed
            }
    except Exception as e:
        logger.error(f"❌ Statistics summary error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@router.get("/daily")
async def get_daily_statistics(days: int = Query(30, description="Número de dias a considerar")):
    """Retorna estatísticas diárias dos últimos N dias"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        days = min(days, 365)

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT 
                    DATE(started_at::TIMESTAMPTZ) as date,
                    COUNT(*) as total_executions,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful_executions,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_executions,
                    SUM(bytes_processed) as total_bytes
                FROM task_executions
                WHERE started_at::TIMESTAMPTZ >= CURRENT_DATE - (%s * INTERVAL '1 day')
                GROUP BY DATE(started_at::TIMESTAMPTZ)
                ORDER BY date
            """
            cursor.execute(query, (days,))
            daily_data = cursor.fetchall()

            chart_data = {
                "labels": [row[0].isoformat() for row in daily_data],
                "datasets": [
                    {"label": "Execuções Totais", "data": [row[1] for row in daily_data], "borderColor": "rgb(75, 192, 192)", "backgroundColor": "rgba(75, 192, 192, 0.2)", "tension": 0.1},
                    {"label": "Execuções Bem-sucedidas", "data": [row[2] for row in daily_data], "borderColor": "rgb(54, 162, 235)", "backgroundColor": "rgba(54, 162, 235, 0.2)", "tension": 0.1},
                    {"label": "Execuções Falharam", "data": [row[3] for row in daily_data], "borderColor": "rgb(255, 99, 132)", "backgroundColor": "rgba(255, 99, 132, 0.2)", "tension": 0.1}
                ]
            }
            return {"status": "success", "chart_data": chart_data}
    except Exception as e:
        logger.error(f"❌ Daily statistics error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@router.get("/throughput")
async def get_throughput_statistics(days: int = Query(30, description="Número de dias a considerar")):
    """Retorna dados de throughput (dados e velocidade) dos últimos N dias"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        days = min(days, 365)

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT
                    DATE(started_at::TIMESTAMPTZ) as date,
                    SUM(bytes_processed) / (1024*1024*1024) as total_gb,
                    AVG(CASE
                        WHEN status = 'completed' AND bytes_processed > 0 AND completed_at IS NOT NULL AND started_at IS NOT NULL
                        THEN bytes_processed / (EXTRACT(EPOCH FROM (completed_at::TIMESTAMPTZ - started_at::TIMESTAMPTZ)))
                        ELSE 0
                    END) / (1024*1024) as avg_speed_mbps
                FROM task_executions
                WHERE started_at::TIMESTAMPTZ >= CURRENT_DATE - (%s * INTERVAL '1 day')
                GROUP BY DATE(started_at::TIMESTAMPTZ)
                ORDER BY date
            """
            cursor.execute(query, (days,))
            throughput_data = cursor.fetchall()

            chart_data = {
                "labels": [row[0].isoformat() for row in throughput_data],
                "datasets": [
                    {"label": "Dados (GB)", "data": [row[1] for row in throughput_data], "borderColor": "rgb(75, 192, 192)", "backgroundColor": "rgba(75, 192, 192, 0.2)", "yAxisID": "y", "tension": 0.1},
                    {"label": "Velocidade Média (MB/s)", "data": [row[2] for row in throughput_data], "borderColor": "rgb(255, 99, 132)", "backgroundColor": "rgba(255, 99, 132, 0.2)", "yAxisID": "y1", "tension": 0.1}
                ]
            }
            return {"status": "success", "chart_data": chart_data}
    except Exception as e:
        logger.error(f"❌ Throughput statistics error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@router.get("/engines/comparison")
async def get_engines_comparison(period: str = Query("month", description="Período: day, week, month, year")):
    """Retorna comparação de estatísticas entre diferentes engines"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        now = datetime.now()
        if period == "day":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start_date = now - timedelta(days=7)
        elif period == "month":
            start_date = now - timedelta(days=30)
        elif period == "year":
            start_date = now - timedelta(days=365)
        else:
            start_date = now - timedelta(days=30)
        start_date_str = start_date.isoformat()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT 
                    t.engine,
                    COUNT(*) as total_executions,
                    SUM(CASE WHEN te.status = 'completed' THEN 1 ELSE 0 END) as successful_executions,
                    SUM(CASE WHEN te.status = 'failed' THEN 1 ELSE 0 END) as failed_executions,
                    SUM(te.bytes_processed) as total_bytes,
                    AVG(CASE 
                        WHEN te.status = 'completed' AND te.bytes_processed > 0 AND te.completed_at IS NOT NULL AND te.started_at IS NOT NULL
                        THEN te.bytes_processed / (EXTRACT(EPOCH FROM (te.completed_at::TIMESTAMPTZ - te.started_at::TIMESTAMPTZ)))
                        ELSE 0 
                    END) / (1024*1024) as avg_speed_mbps
                FROM task_executions te
                JOIN tasks t ON te.task_id = t.id
                WHERE te.started_at::TIMESTAMPTZ >= %s
                GROUP BY t.engine
            """
            cursor.execute(query, (start_date_str,))
            engines_data = cursor.fetchall()

            engines = []
            for engine_row in engines_data:
                total_exec = engine_row[1]
                successful_exec = engine_row[2]
                success_rate = (successful_exec / total_exec * 100) if total_exec > 0 else 0
                engines.append({
                    "engine": engine_row[0],
                    "total_executions": total_exec,
                    "successful_executions": successful_exec,
                    "failed_executions": engine_row[3],
                    "total_bytes_gb": (engine_row[4] or 0) / (1024**3),
                    "avg_speed_mbps": engine_row[5] or 0,
                    "success_rate": success_rate
                })

            chart_data = {
                "labels": [e["engine"] for e in engines],
                "datasets": [
                    {"label": "Execuções Totais", "data": [e["total_executions"] for e in engines], "backgroundColor": "rgba(54, 162, 235, 0.5)"},
                    {"label": "Taxa de Sucesso (%)", "data": [e["success_rate"] for e in engines], "backgroundColor": "rgba(75, 192, 192, 0.5)"}
                ]
            }
            return {"status": "success", "engines": engines, "chart_data": chart_data}
    except Exception as e:
        logger.error(f"❌ Engines comparison error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@router.get("/errors/trend")
async def get_errors_trend(days: int = Query(30, description="Número de dias a considerar")):
    """Retorna tendência de erros dos últimos N dias"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        days = min(days, 365)

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT 
                    DATE(started_at::TIMESTAMPTZ) as date,
                    COUNT(*) as total_errors,
                    STRING_AGG(DISTINCT error_message, ', ') as error_messages
                FROM task_executions
                WHERE status = 'failed' AND started_at::TIMESTAMPTZ >= CURRENT_DATE - (%s * INTERVAL '1 day')
                GROUP BY DATE(started_at::TIMESTAMPTZ)
                ORDER BY date
            """
            cursor.execute(query, (days,))
            errors_data = cursor.fetchall()

            chart_data = {
                "labels": [row[0].isoformat() for row in errors_data],
                "datasets": [{"label": "Erros por Dia", "data": [row[1] for row in errors_data], "borderColor": "rgb(255, 99, 132)", "backgroundColor": "rgba(255, 99, 132, 0.2)", "tension": 0.1}]
            }

            error_counts = {}
            for row in errors_data:
                if row[2]:
                    messages = row[2].split(',')
                    for msg in messages:
                        msg = msg.strip()
                        if msg:
                            error_counts[msg] = error_counts.get(msg, 0) + 1
            
            common_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:10]

            return {
                "status": "success", 
                "chart_data": chart_data,
                "common_errors": [{"message": msg, "count": count} for msg, count in common_errors]
            }
    except Exception as e:
        logger.error(f"❌ Errors trend error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}