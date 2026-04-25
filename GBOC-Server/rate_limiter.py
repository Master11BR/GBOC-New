"""
GBOC Server - Rate Limiting
Proteção contra abuso de API com rate limiting por IP e endpoint
"""
from typing import Dict, Tuple
from datetime import datetime, timedelta, timezone
from config import ENDPOINT_RATE_LIMITS, RATE_LIMIT_ENABLED
from logger import setup_logger

logger = setup_logger(__name__)

class RateLimiter:
    """Gerenciador de rate limiting"""

    def __init__(self):
        # Formato: {key: [(timestamp, count)]}
        self.requests: Dict[str, list] = {}
        self.enabled = RATE_LIMIT_ENABLED

    def get_key(self, ip: str, endpoint: str) -> str:
        """
        Gera chave única para rastreamento

        Args:
            ip: IP do cliente
            endpoint: Endpoint da API

        Returns:
            Chave única
        """
        return f"{ip}:{endpoint}"

    def is_allowed(self, ip: str, endpoint: str) -> Tuple[bool, Dict]:
        """
        Verifica se uma requisição é permitida

        Args:
            ip: IP do cliente
            endpoint: Endpoint da API

        Returns:
            Tupla (allowed: bool, info: dict com detalhes)
        """
        if not self.enabled:
            return True, {"rate_limit_enabled": False}

        # Obter configuração do endpoint
        limit_config = ENDPOINT_RATE_LIMITS.get(endpoint, {
            "requests": 100,
            "window": 60
        })

        requests_limit = limit_config["requests"]
        window_seconds = limit_config["window"]

        key = self.get_key(ip, endpoint)
        now = datetime.now(timezone.utc)
        cutoff_time = now - timedelta(seconds=window_seconds)

        # Limpar requisições antigas
        if key in self.requests:
            self.requests[key] = [
                (ts, count) for ts, count in self.requests[key]
                if ts > cutoff_time
            ]
        else:
            self.requests[key] = []

        # Contar requisições no período
        total_requests = sum(count for _, count in self.requests[key])

        # Verificar limite
        if total_requests >= requests_limit:
            logger.warning(
                f"Rate limit excedido para {ip} em {endpoint}: "
                f"{total_requests}/{requests_limit}"
            )
            return False, {
                "rate_limit_exceeded": True,
                "limit": requests_limit,
                "window": window_seconds,
                "current": total_requests,
                "reset_in": window_seconds
            }

        # Registrar nova requisição
        if not self.requests[key]:
            self.requests[key].append((now, 1))
        else:
            # Atualizar última entrada se for do mesmo segundo
            last_ts, last_count = self.requests[key][-1]
            if (now - last_ts).total_seconds() < 1:
                self.requests[key][-1] = (last_ts, last_count + 1)
            else:
                self.requests[key].append((now, 1))

        return True, {
            "rate_limit_enabled": True,
            "limit": requests_limit,
            "window": window_seconds,
            "current": total_requests + 1,
            "remaining": requests_limit - (total_requests + 1)
        }

    def reset(self, ip: str = None, endpoint: str = None) -> None:
        """
        Reseta o rate limit para um cliente/endpoint específico

        Args:
            ip: IP do cliente (None = todos)
            endpoint: Endpoint (None = todos)
        """
        if ip is None or endpoint is None:
            self.requests.clear()
            logger.info("Rate limiter zerado")
        else:
            key = self.get_key(ip, endpoint)
            if key in self.requests:
                del self.requests[key]
                logger.info(f"Rate limiter zerado para {key}")

# Instância global
rate_limiter = RateLimiter()
