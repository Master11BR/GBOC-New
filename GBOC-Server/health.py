"""
GBOC Server - Health Checks e Monitoramento
Sistema de verificação de saúde do servidor e agentes
"""
from typing import Dict, Any, List
from datetime import datetime, timedelta, timezone
import psycopg2
from config import DB_CONFIG, HEARTBEAT_INTERVAL_SECONDS, AGENT_OFFLINE_THRESHOLD_MINUTES
from logger import setup_logger

logger = setup_logger(__name__)

class HealthCheckManager:
    """Gerenciador de health checks"""

    @staticmethod
    def check_database() -> Dict[str, Any]:
        """
        Verifica saúde da conexão com banco de dados

        Returns:
            Dicionário com status
        """
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()

            # Verificar que a conexão está funcionando
            cur.execute("SELECT CURRENT_TIMESTAMP")
            timestamp = cur.fetchone()[0]

            # Contar agentes
            cur.execute("SELECT COUNT(*) FROM agents")
            agent_count = cur.fetchone()[0]

            # Contar agentes online
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=AGENT_OFFLINE_THRESHOLD_MINUTES)
            cur.execute(
                "SELECT COUNT(*) FROM agents WHERE last_heartbeat > %s",
                (cutoff_time,)
            )
            online_count = cur.fetchone()[0]

            cur.close()
            conn.close()

            return {
                "status": "healthy",
                "database": "PostgreSQL",
                "timestamp": timestamp.isoformat(),
                "agents": {
                    "total": agent_count,
                    "online": online_count,
                    "offline": agent_count - online_count
                }
            }
        except Exception as e:
            logger.error(f"Database health check falhou: {e}")
            return {
                "status": "unhealthy",
                "error": str(e)
            }

    @staticmethod
    def check_cache() -> Dict[str, Any]:
        """
        Verifica saúde do cache Redis

        Returns:
            Dicionário com status
        """
        from cache import cache

        if not cache.enabled:
            return {
                "status": "disabled",
                "service": "Redis Cache"
            }

        try:
            # Tentar uma operação simples
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def test_redis():
                if await cache.set("health_check", "ok", ttl=10):
                    value = await cache.get("health_check")
                    return value == "ok"
                return False

            result = loop.run_until_complete(test_redis())

            if result:
                return {
                    "status": "healthy",
                    "service": "Redis Cache"
                }
            else:
                return {
                    "status": "degraded",
                    "service": "Redis Cache",
                    "error": "Failed to read/write"
                }
        except Exception as e:
            logger.error(f"Redis health check falhou: {e}")
            return {
                "status": "unhealthy",
                "service": "Redis Cache",
                "error": str(e)
            }

    @staticmethod
    def check_dlq() -> Dict[str, Any]:
        """
        Verifica status da Dead Letter Queue

        Returns:
            Dicionário com status
        """
        try:
            stats = dlq.get_stats()

            status = "healthy"
            if stats.get("file_size_mb", 0) > stats.get("max_size_mb", 100) * 0.8:
                status = "warning"

            return {
                "status": status,
                "service": "Dead Letter Queue",
                "stats": stats
            }
        except Exception as e:
            logger.error(f"DLQ health check falhou: {e}")
            return {
                "status": "unhealthy",
                "service": "Dead Letter Queue",
                "error": str(e)
            }

    @staticmethod
    def check_system() -> Dict[str, Any]:
        """
        Verifica saúde geral do sistema

        Returns:
            Dicionário com status geral
        """
        checks = {
            "database": HealthCheckManager.check_database(),
            "cache": HealthCheckManager.check_cache(),
            "dlq": HealthCheckManager.check_dlq(),
        }

        # Determinar status geral
        statuses = [c.get("status") for c in checks.values()]

        if "unhealthy" in statuses:
            overall_status = "unhealthy"
        elif "warning" in statuses or "degraded" in statuses:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        return {
            "status": overall_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": checks
        }

class MetricsCollector:
    """Coletor de métricas do servidor"""

    def __init__(self):
        self.start_time = datetime.now(timezone.utc)
        self.requests_total = 0
        self.requests_success = 0
        self.requests_error = 0
        self.websocket_connections = 0

    def record_request(self, success: bool = True) -> None:
        """
        Registra uma requisição

        Args:
            success: Se foi bem-sucedida
        """
        self.requests_total += 1
        if success:
            self.requests_success += 1
        else:
            self.requests_error += 1

    def get_metrics(self) -> Dict[str, Any]:
        """
        Obtém métricas do servidor

        Returns:
            Dicionário com métricas
        """
        uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()

        return {
            "uptime_seconds": uptime,
            "requests": {
                "total": self.requests_total,
                "success": self.requests_success,
                "errors": self.requests_error,
                "success_rate": (
                    self.requests_success / self.requests_total * 100
                    if self.requests_total > 0 else 0
                )
            },
            "websocket_connections": self.websocket_connections,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

# Importar dlq aqui para evitar circular imports
from dlq import dlq

# Instâncias globais
health_check = HealthCheckManager()
metrics_collector = MetricsCollector()
