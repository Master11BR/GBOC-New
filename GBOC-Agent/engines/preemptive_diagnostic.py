#!/usr/bin/env python3
"""
GBOC 13.2.0 - Sistema de Diagnóstico Preemptivo
Detecta e previne problemas antes que aconteçam
"""

import logging
import psutil
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
from pathlib import Path
import json

logger = logging.getLogger(__name__)


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


class PreemptiveDiagnostic:
    """Sistema de diagnóstico preemptivo para GBOC"""

    def __init__(self):
        self.alerts = []
        self.warnings = []
        self.recommendations = []
        
    def run_preemptive_check(self) -> Dict[str, Any]:
        """Executa verificação preemptiva completa"""
        logger.info("Executando diagnóstico preemptivo...")
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "checks": {
                "storage_capacity": self._check_storage_capacity(),
                "backup_failures": self._check_backup_failures(),
                "performance_degradation": self._check_performance_degradation(),
                "database_health": self._check_database_health(),
                "system_resources": self._check_system_resources(),
                "schedule_conflicts": self._check_schedule_conflicts(),
                "retention_policy": self._check_retention_policy(),
                "network_issues": self._check_network_issues()
            },
            "alerts": self.alerts,
            "warnings": self.warnings,
            "recommendations": self.recommendations,
            "risk_level": "low"
        }
        
        # Calcular nível de risco geral
        report["risk_level"] = self._calculate_risk_level()
        
        return report
    
    def _check_storage_capacity(self) -> Dict[str, Any]:
        """Verifica capacidade de armazenamento"""
        try:
            result = {
                "status": "ok",
                "details": []
            }

            disk = psutil.disk_usage('/')
            percent_used = disk.percent

            result["details"].append({
                "disk": "/",
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent_used": percent_used
            })

            if percent_used > 70:
                with _get_core().get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT SUM(bytes_processed)
                        FROM task_executions
                        WHERE started_at >= NOW() - INTERVAL '7 days'
                          AND status = 'success'
                    """)
                    weekly_growth = cursor.fetchone()[0] or 0
                    daily_growth = weekly_growth / 7

                if daily_growth > 0:
                    days_until_full = (disk.free / daily_growth)
                    result["days_until_full"] = round(days_until_full, 1)

                    if days_until_full < 30:
                        result["status"] = "critical"
                        self.alerts.append(f"Storage will be full in {days_until_full:.1f} days")
                        self.recommendations.append("Increase storage capacity or implement aggressive retention policy")
                    elif days_until_full < 60:
                        result["status"] = "warning"
                        self.warnings.append(f"Storage will be full in {days_until_full:.1f} days")
                        self.recommendations.append("Plan for storage expansion")

            if percent_used > 90:
                result["status"] = "critical"
                self.alerts.append(f"Disk usage critical: {percent_used}%")
                self.recommendations.append("Free up disk space immediately")
            elif percent_used > 80:
                result["status"] = "warning"
                self.warnings.append(f"Disk usage high: {percent_used}%")

            return result

        except Exception as e:
            logger.error(f"Error checking storage capacity: {e}")
            return {"status": "error", "error": str(e)}
    
    def _check_backup_failures(self) -> Dict[str, Any]:
        """Verifica padrões de falhas de backup"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT COUNT(*)
                    FROM task_executions
                    WHERE status = 'error'
                      AND started_at >= NOW() - INTERVAL '7 days'
                """)
                failures_7d = cursor.fetchone()[0] or 0

                cursor.execute("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(CASE WHEN status = 'error' THEN 1 END) AS failures
                    FROM task_executions
                    WHERE started_at >= NOW() - INTERVAL '7 days'
                """)
                row = cursor.fetchone()
                total, failures = row if row else (0, 0)
                failure_rate = (failures / total * 100) if total > 0 else 0

                cursor.execute("""
                    SELECT
                        task_id,
                        COUNT(*) AS failure_count,
                        MAX(started_at) AS last_failure
                    FROM task_executions
                    WHERE status = 'error'
                      AND started_at >= NOW() - INTERVAL '30 days'
                    GROUP BY task_id
                    HAVING COUNT(*) >= 3
                """)
                recurring_failures = cursor.fetchall()

            result = {
                "status": "ok",
                "failures_7d": failures_7d,
                "failure_rate": round(failure_rate, 2),
                "recurring_failures": len(recurring_failures)
            }

            if failure_rate > 20:
                result["status"] = "critical"
                self.alerts.append(f"High failure rate: {failure_rate:.1f}%")
                self.recommendations.append("Investigate backup configuration and system logs")
            elif failure_rate > 10:
                result["status"] = "warning"
                self.warnings.append(f"Elevated failure rate: {failure_rate:.1f}%")

            if recurring_failures:
                self.warnings.append(f"{len(recurring_failures)} task(s) with recurring failures")
                self.recommendations.append("Review and fix tasks with recurring failures")

            return result

        except Exception as e:
            logger.error(f"Error checking backup failures: {e}")
            return {"status": "error", "error": str(e)}
    
    def _check_performance_degradation(self) -> Dict[str, Any]:
        """Verifica degradação de performance"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT AVG(duration_seconds)
                    FROM task_executions
                    WHERE status = 'success'
                      AND started_at >= NOW() - INTERVAL '7 days'
                """)
                current_avg = cursor.fetchone()[0] or 0

                cursor.execute("""
                    SELECT AVG(duration_seconds)
                    FROM task_executions
                    WHERE status = 'success'
                      AND started_at BETWEEN NOW() - INTERVAL '30 days' AND NOW() - INTERVAL '7 days'
                """)
                historical_avg = cursor.fetchone()[0] or 0

            result = {
                "status": "ok",
                "current_avg_minutes": round(current_avg / 60, 2) if current_avg else 0,
                "historical_avg_minutes": round(historical_avg / 60, 2) if historical_avg else 0
            }

            if historical_avg > 0:
                degradation = ((current_avg - historical_avg) / historical_avg * 100)
                result["degradation_percent"] = round(degradation, 2)

                if degradation > 50:
                    result["status"] = "critical"
                    self.alerts.append(f"Severe performance degradation: {degradation:.1f}%")
                    self.recommendations.append("Check system resources and network connectivity")
                elif degradation > 25:
                    result["status"] = "warning"
                    self.warnings.append(f"Performance degradation detected: {degradation:.1f}%")
                    self.recommendations.append("Monitor system performance")

            return result

        except Exception as e:
            logger.error(f"Error checking performance: {e}")
            return {"status": "error", "error": str(e)}
    
    def _check_database_health(self) -> Dict[str, Any]:
        """Verifica saúde do banco de dados PostgreSQL"""
        try:
            result = {"status": "ok"}

            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()

                # Verificar tamanho do banco
                cursor.execute("""
                    SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size,
                           pg_database_size(current_database()) AS db_size_bytes
                """)
                row = cursor.fetchone()
                db_size_pretty, db_size_bytes = row if row else ('0 bytes', 0)
                result["size_mb"] = round((db_size_bytes or 0) / (1024**2), 2)
                result["size_pretty"] = db_size_pretty

                # Verificar conexões ativas
                cursor.execute("""
                    SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'active'
                """)
                active_conns = cursor.fetchone()[0] or 0
                result["active_connections"] = active_conns

            if result["size_mb"] > 1000:
                self.warnings.append(f"Large database size: {result['size_mb']} MB")
                self.recommendations.append("Consider implementing data retention policy")

            return result

        except Exception as e:
            logger.error(f"Error checking database health: {e}")
            return {"status": "error", "error": str(e)}
    
    def _check_system_resources(self) -> Dict[str, Any]:
        """Verifica recursos do sistema"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            
            result = {
                "status": "ok",
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_available_gb": round(memory.available / (1024**3), 2)
            }
            
            if cpu_percent > 80:
                result["status"] = "warning"
                self.warnings.append(f"High CPU usage: {cpu_percent}%")
                self.recommendations.append("Review backup schedules to reduce load")
            
            if memory.percent > 85:
                result["status"] = "warning"
                self.warnings.append(f"High memory usage: {memory.percent}%")
                self.recommendations.append("Consider increasing system memory")
            
            return result
            
        except Exception as e:
            logger.error(f"Error checking system resources: {e}")
            return {"status": "error", "error": str(e)}
    
    def _check_schedule_conflicts(self) -> Dict[str, Any]:
        """Verifica conflitos de agendamento"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, name, schedule
                    FROM tasks
                    WHERE enabled = 1 AND schedule IS NOT NULL
                """)
                tasks = cursor.fetchall()

            result = {
                "status": "ok",
                "total_scheduled": len(tasks),
                "conflicts": []
            }

            if len(tasks) > 10:
                self.warnings.append(f"Many scheduled tasks: {len(tasks)}")
                self.recommendations.append("Review schedule distribution to avoid overload")

            return result

        except Exception as e:
            logger.error(f"Error checking schedule conflicts: {e}")
            return {"status": "error", "error": str(e)}
    
    def _check_retention_policy(self) -> Dict[str, Any]:
        """Verifica política de retenção"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM task_executions
                    WHERE started_at < NOW() - INTERVAL '90 days'
                """)
                old_records = cursor.fetchone()[0] or 0

            result = {
                "status": "ok",
                "old_records": old_records
            }

            if old_records > 1000:
                result["status"] = "warning"
                self.warnings.append(f"Many old execution records: {old_records}")
                self.recommendations.append("Implement retention policy to clean old data")

            return result

        except Exception as e:
            logger.error(f"Error checking retention policy: {e}")
            return {"status": "error", "error": str(e)}
    
    def _check_network_issues(self) -> Dict[str, Any]:
        """Verifica problemas de rede"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM task_executions
                    WHERE status = 'error'
                      AND error_message ILIKE '%timeout%'
                      AND started_at >= NOW() - INTERVAL '7 days'
                """)
                timeout_errors = cursor.fetchone()[0] or 0

            result = {
                "status": "ok",
                "timeout_errors_7d": timeout_errors
            }

            if timeout_errors > 5:
                result["status"] = "warning"
                self.warnings.append(f"Multiple timeout errors: {timeout_errors}")
                self.recommendations.append("Check network connectivity and speed")

            return result

        except Exception as e:
            logger.error(f"Error checking network issues: {e}")
            return {"status": "error", "error": str(e)}
    
    def _calculate_risk_level(self) -> str:
        """Calcula nível de risco geral"""
        if len(self.alerts) >= 3:
            return "critical"
        elif len(self.alerts) >= 1:
            return "high"
        elif len(self.warnings) >= 5:
            return "medium"
        elif len(self.warnings) >= 1:
            return "low"
        else:
            return "minimal"

def main():
    """Função de teste"""
    diagnostic = PreemptiveDiagnostic()
    report = diagnostic.run_preemptive_check()
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()

