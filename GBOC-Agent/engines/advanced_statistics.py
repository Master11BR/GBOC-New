#!/usr/bin/env python3
"""
GBOC 14.0.0 - Sistema de Análise Estatística Avançada
Inspirado no Duplicati com estatísticas detalhadas e previsões
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
import statistics

logger = logging.getLogger(__name__)


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


class AdvancedStatistics:
    """Sistema de estatísticas avançadas para backups"""

    def __init__(self):
        self.stats_cache = {}
        
    def get_comprehensive_stats(self, days: int = 30) -> Dict[str, Any]:
        """Obtém estatísticas abrangentes"""
        logger.info(f"Gerando estatísticas para os últimos {days} dias...")
        
        stats = {
            "period_days": days,
            "generated_at": datetime.now().isoformat(),
            "backup_stats": self._get_backup_stats(days),
            "performance_stats": self._get_performance_stats(days),
            "storage_stats": self._get_storage_stats(days),
            "reliability_stats": self._get_reliability_stats(days),
            "predictions": self._get_predictions(),
            "trends": self._get_trends(days),
            "health_score": 0
        }
        
        # Calcular health score geral
        stats["health_score"] = self._calculate_health_score(stats)
        
        return stats
    
    def _get_backup_stats(self, days: int) -> Dict[str, Any]:
        """Estatísticas de backup"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT COUNT(*),
                           SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successful,
                           SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS failed,
                           SUM(CASE WHEN status = 'warning' THEN 1 ELSE 0 END) AS warnings
                    FROM task_executions
                    WHERE started_at >= NOW() - INTERVAL '%s days'
                """ % int(days))

                row = cursor.fetchone()
                total, successful, failed, warnings = row if row else (0, 0, 0, 0)
                success_rate = (successful / total * 100) if total > 0 else 100

                cursor.execute("""
                    SELECT DATE(started_at) AS day, COUNT(*) AS count
                    FROM task_executions
                    WHERE started_at >= NOW() - INTERVAL '%s days'
                    GROUP BY DATE(started_at)
                    ORDER BY day DESC
                """ % int(days))

                daily_backups = cursor.fetchall()
                avg_daily_backups = statistics.mean([count for _, count in daily_backups]) if daily_backups else 0

            return {
                "total_backups": total,
                "successful": successful,
                "failed": failed,
                "warnings": warnings,
                "success_rate": round(success_rate, 2),
                "avg_daily_backups": round(avg_daily_backups, 2),
                "most_active_day": daily_backups[0] if daily_backups else None
            }

        except Exception as e:
            logger.error(f"Erro ao obter estatísticas de backup: {e}")
            return {"error": str(e)}
    
    def _get_performance_stats(self, days: int) -> Dict[str, Any]:
        """Estatísticas de performance"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT
                        AVG(duration_seconds) AS avg_duration,
                        MIN(duration_seconds) AS min_duration,
                        MAX(duration_seconds) AS max_duration,
                        SUM(files_processed) AS total_files,
                        SUM(bytes_processed) AS total_bytes
                    FROM task_executions
                    WHERE started_at >= NOW() - INTERVAL '%s days' AND status = 'success'
                """ % int(days))

                row = cursor.fetchone()
                if row and row[0]:
                    avg_dur, min_dur, max_dur, total_files, total_bytes = row
                    avg_speed_mbps = (total_bytes / avg_dur / (1024**2)) if avg_dur and total_bytes else 0
                    total_gb = total_bytes / (1024**3) if total_bytes else 0

                    return {
                        "avg_duration_minutes": round(avg_dur / 60, 2) if avg_dur else 0,
                        "min_duration_minutes": round(min_dur / 60, 2) if min_dur else 0,
                        "max_duration_minutes": round(max_dur / 60, 2) if max_dur else 0,
                        "total_files_processed": total_files or 0,
                        "total_data_processed_gb": round(total_gb, 2),
                        "avg_speed_mbps": round(avg_speed_mbps, 2)
                    }

            return {}

        except Exception as e:
            logger.error(f"Erro ao obter estatísticas de performance: {e}")
            return {"error": str(e)}
    
    def _get_storage_stats(self, days: int) -> Dict[str, Any]:
        """Estatísticas de armazenamento"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT
                        SUM(size_bytes) AS total_backup_size,
                        COUNT(DISTINCT repository_id) AS repository_count
                    FROM repositories
                """)
                row = cursor.fetchone()
                total_size, repo_count = row if row else (0, 0)

                cursor.execute("""
                    SELECT SUM(bytes_processed)
                    FROM task_executions
                    WHERE started_at >= NOW() - INTERVAL '%s days' AND status = 'success'
                """ % int(days))

                growth = cursor.fetchone()[0] or 0
                daily_growth = growth / days if days > 0 else 0

            return {
                "total_backup_size_gb": round(total_size / (1024**3), 2) if total_size else 0,
                "repository_count": repo_count,
                "data_growth_period_gb": round(growth / (1024**3), 2),
                "avg_daily_growth_gb": round(daily_growth / (1024**3), 2),
                "projected_monthly_growth_gb": round(daily_growth * 30 / (1024**3), 2)
            }

        except Exception as e:
            logger.error(f"Erro ao obter estatísticas de armazenamento: {e}")
            return {"error": str(e)}
    
    def _get_reliability_stats(self, days: int) -> Dict[str, Any]:
        """Estatísticas de confiabilidade"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT
                        COUNT(CASE WHEN status = 'success' THEN 1 END) AS successful,
                        COUNT(CASE WHEN status = 'error' THEN 1 END) AS failed,
                        COUNT(*) AS total
                    FROM task_executions
                    WHERE started_at >= NOW() - INTERVAL '%s days'
                """ % int(days))

                row = cursor.fetchone()
                successful, failed, total = row if row else (0, 0, 0)
                reliability = (successful / total * 100) if total > 0 else 100

                cursor.execute("""
                    SELECT started_at
                    FROM task_executions
                    WHERE started_at >= NOW() - INTERVAL '%s days' AND status = 'error'
                    ORDER BY started_at
                """ % int(days))

                failures = cursor.fetchall()
                mtbf_hours = 0

                if len(failures) > 1:
                    time_between_failures = []
                    for i in range(1, len(failures)):
                        prev_time = failures[i-1][0] if hasattr(failures[i-1][0], 'total_seconds') else datetime.fromisoformat(str(failures[i-1][0]))
                        curr_time = failures[i][0] if hasattr(failures[i][0], 'total_seconds') else datetime.fromisoformat(str(failures[i][0]))
                        diff = (curr_time - prev_time).total_seconds() / 3600
                        time_between_failures.append(diff)
                    mtbf_hours = statistics.mean(time_between_failures) if time_between_failures else 0

            return {
                "reliability_score": round(reliability, 2),
                "total_failures": failed,
                "mtbf_hours": round(mtbf_hours, 2),
                "uptime_percentage": round(reliability, 2)
            }

        except Exception as e:
            logger.error(f"Erro ao obter estatísticas de confiabilidade: {e}")
            return {"error": str(e)}
    
    def _get_predictions(self) -> Dict[str, Any]:
        """Previsões baseadas em dados históricos"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT bytes_processed, started_at
                    FROM task_executions
                    WHERE status = 'success'
                    ORDER BY started_at DESC
                    LIMIT 30
                """)

                recent_backups = cursor.fetchall()

                if len(recent_backups) >= 3:
                    sizes = [size for size, _ in recent_backups if size]
                    avg_size = statistics.mean(sizes) if sizes else 0
                    predictions = {
                        "storage_30d_gb": round(avg_size * 30 / (1024**3), 2),
                        "storage_60d_gb": round(avg_size * 60 / (1024**3), 2),
                        "storage_90d_gb": round(avg_size * 90 / (1024**3), 2)
                    }
                else:
                    predictions = {
                        "storage_30d_gb": 0,
                        "storage_60d_gb": 0,
                        "storage_90d_gb": 0,
                        "note": "Insufficient data for predictions"
                    }

            return predictions

        except Exception as e:
            logger.error(f"Erro ao gerar previsões: {e}")
            return {"error": str(e)}
    
    def _get_trends(self, days: int) -> Dict[str, Any]:
        """Análise de tendências"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT
                        DATE(started_at) AS day,
                        COUNT(CASE WHEN status = 'success' THEN 1 END) * 100.0 / COUNT(*) AS success_rate
                    FROM task_executions
                    WHERE started_at >= NOW() - INTERVAL '%s days'
                    GROUP BY DATE(started_at)
                    ORDER BY day
                """ % int(days))

                daily_success = cursor.fetchall()

                if len(daily_success) >= 7:
                    recent_rate = statistics.mean([rate for _, rate in daily_success[-7:]])
                    older_rate = statistics.mean([rate for _, rate in daily_success[:7]])
                    trend = "improving" if recent_rate > older_rate else "declining" if recent_rate < older_rate else "stable"
                else:
                    trend = "insufficient_data"

            return {
                "success_trend": trend,
                "daily_success_rates": [(str(day), round(rate, 2)) for day, rate in daily_success]
            }

        except Exception as e:
            logger.error(f"Erro ao analisar tendências: {e}")
            return {"error": str(e)}
    
    def _calculate_health_score(self, stats: Dict[str, Any]) -> float:
        """Calcula score de saúde geral do sistema"""
        try:
            scores = []
            
            # Score de confiabilidade (40%)
            if "reliability_stats" in stats and "reliability_score" in stats["reliability_stats"]:
                scores.append(stats["reliability_stats"]["reliability_score"] * 0.4)
            
            # Score de performance (30%)
            if "performance_stats" in stats and "avg_speed_mbps" in stats["performance_stats"]:
                # Assumir que 10 MB/s é excelente
                perf_score = min(stats["performance_stats"]["avg_speed_mbps"] / 10 * 100, 100)
                scores.append(perf_score * 0.3)
            
            # Score de backup (30%)
            if "backup_stats" in stats and "success_rate" in stats["backup_stats"]:
                scores.append(stats["backup_stats"]["success_rate"] * 0.3)
            
            health_score = sum(scores) if scores else 0
            return round(health_score, 2)
            
        except Exception as e:
            logger.error(f"Erro ao calcular health score: {e}")
            return 0

def main():
    """Função de teste"""
    stats_engine = AdvancedStatistics()
    stats = stats_engine.get_comprehensive_stats(30)
    print(json.dumps(stats, indent=2))

if __name__ == "__main__":
    main()

