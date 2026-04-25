from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
import time
import psutil
from typing import Callable
import logging

logger = logging.getLogger(__name__)

# Métricas do Prometheus
REQUEST_COUNT = Counter(
    'gboc_requests_total',
    'Total number of requests',
    ['method', 'endpoint', 'status']
)

REQUEST_LATENCY = Histogram(
    'gboc_request_duration_seconds',
    'Request duration in seconds',
    ['method', 'endpoint']
)

ACTIVE_CONNECTIONS = Gauge(
    'gboc_active_connections',
    'Number of active connections'
)

DATABASE_CONNECTIONS = Gauge(
    'gboc_db_connections_active',
    'Number of active database connections'
)

BACKUP_OPERATIONS = Counter(
    'gboc_backup_operations_total',
    'Total number of backup operations',
    ['engine', 'status']
)

RESTORE_OPERATIONS = Counter(
    'gboc_restore_operations_total',
    'Total number of restore operations',
    ['engine', 'status']
)

SYSTEM_CPU_USAGE = Gauge(
    'gboc_system_cpu_usage_percent',
    'System CPU usage percentage'
)

SYSTEM_MEMORY_USAGE = Gauge(
    'gboc_system_memory_usage_bytes',
    'System memory usage in bytes'
)

class MonitoringMiddleware:
    """Middleware para coletar métricas de requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        method = scope["method"]
        path = scope["path"]

        # Incrementa conexões ativas
        ACTIVE_CONNECTIONS.inc()

        try:
            await self.app(scope, receive, send)
        finally:
            # Decrementa conexões ativas
            ACTIVE_CONNECTIONS.dec()

            # Registra latência
            duration = time.time() - start_time
            REQUEST_LATENCY.labels(method=method, endpoint=path).observe(duration)

class MetricsCollector:
    """Coletor de métricas do sistema."""

    def __init__(self):
        self.last_update = 0

    def update_system_metrics(self):
        """Atualiza métricas do sistema periodicamente."""
        current_time = time.time()
        if current_time - self.last_update < 30:  # Atualiza a cada 30 segundos
            return

        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            SYSTEM_CPU_USAGE.set(cpu_percent)

            # Memory usage
            memory = psutil.virtual_memory()
            SYSTEM_MEMORY_USAGE.set(memory.used)

            self.last_update = current_time
            logger.debug(f"System metrics updated: CPU {cpu_percent}%, Memory {memory.used/1024/1024:.1f}MB")

        except Exception as e:
            logger.error(f"Error updating system metrics: {e}")

    def increment_backup_operation(self, engine: str, success: bool = True):
        """Incrementa contador de operações de backup."""
        status = 'success' if success else 'failure'
        BACKUP_OPERATIONS.labels(engine=engine, status=status).inc()

    def increment_restore_operation(self, engine: str, success: bool = True):
        """Incrementa contador de operações de restauração."""
        status = 'success' if success else 'failure'
        RESTORE_OPERATIONS.labels(engine=engine, status=status).inc()

    def set_db_connections(self, count: int):
        """Define número de conexões ativas do banco."""
        DATABASE_CONNECTIONS.set(count)

def metrics_endpoint():
    """Endpoint para expor métricas do Prometheus."""
    collector.update_system_metrics()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

def monitor_request(method: str, endpoint: str, status: int = 200):
    """Decorator para monitorar requests."""
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=str(status)).inc()
                return result
            except Exception as e:
                REQUEST_COUNT.labels(method=method, endpoint=endpoint, status='500').inc()
                raise e
            finally:
                duration = time.time() - start_time
                REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(duration)

        return wrapper
    return decorator

# Instância global
collector = MetricsCollector()