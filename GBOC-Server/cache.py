"""
GBOC Server - Sistema de Cache com Redis
Caching de dados de agentes, métricas e configurações
"""
from typing import Optional, Any, Dict
import json
import asyncio
from config import (
    REDIS_ENABLED, REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD,
    CACHE_AGENT_DATA_TTL, CACHE_METRICS_TTL, CACHE_SETTINGS_TTL
)
from logger import setup_logger

logger = setup_logger(__name__)

try:
    import aioredis
    # Detectar versão: aioredis v2+ usa aioredis.Redis, v1 usa create_redis_pool
    AIOREDIS_V2 = hasattr(aioredis, 'from_url')
    AIOREDIS_AVAILABLE = True
except ImportError:
    AIOREDIS_AVAILABLE = False
    AIOREDIS_V2 = False
    logger.warning("aioredis não instalado. Cache Redis desabilitado. Instale com: pip install aioredis")

class RedisCache:
    """Gerenciador de cache com Redis"""

    def __init__(self):
        self.redis: Optional[Any] = None
        self.enabled = REDIS_ENABLED and AIOREDIS_AVAILABLE

    async def initialize(self) -> bool:
        """
        Inicializa conexão com Redis (compatível aioredis v1 e v2)

        Returns:
            True se conectado com sucesso, False caso contrário
        """
        if not self.enabled:
            logger.info("Redis cache desabilitado")
            return False

        try:
            url = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
            if AIOREDIS_V2:
                # aioredis v2+
                self.redis = await aioredis.from_url(
                    url,
                    password=REDIS_PASSWORD or None,
                    encoding="utf-8",
                    decode_responses=True,
                )
            else:
                # aioredis v1 (legado)
                self.redis = await aioredis.create_redis_pool(
                    f"redis://{REDIS_HOST}:{REDIS_PORT}",
                    db=REDIS_DB,
                    password=REDIS_PASSWORD,
                    encoding="utf-8",
                )
            logger.info(f"✓ Conectado ao Redis com sucesso (aioredis {'v2+' if AIOREDIS_V2 else 'v1'})")
            return True
        except Exception as e:
            logger.error(f"✗ Erro ao conectar ao Redis: {e}")
            self.enabled = False
            return False

    async def close(self):
        """Fecha conexão com Redis"""
        if self.redis:
            try:
                if AIOREDIS_V2:
                    await self.redis.aclose()
                else:
                    self.redis.close()
                    await self.redis.wait_closed()
                logger.info("Conexão Redis fechada")
            except Exception:
                pass

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Armazena um valor no cache

        Args:
            key: Chave do cache
            value: Valor a armazenar (será convertido para JSON)
            ttl: Tempo de vida em segundos

        Returns:
            True se sucesso, False caso contrário
        """
        if not self.enabled or not self.redis:
            return False

        try:
            json_value = json.dumps(value) if not isinstance(value, str) else value
            if AIOREDIS_V2:
                if ttl:
                    await self.redis.set(key, json_value, ex=ttl)
                else:
                    await self.redis.set(key, json_value)
            else:
                await self.redis.set(key, json_value, expire=ttl)
            logger.debug(f"Cache SET: {key} (TTL: {ttl}s)")
            return True
        except Exception as e:
            logger.error(f"Erro ao SET cache {key}: {e}")
            return False

    async def get(self, key: str) -> Optional[Any]:
        """
        Recupera um valor do cache

        Args:
            key: Chave do cache

        Returns:
            Valor armazenado ou None se não encontrado
        """
        if not self.enabled or not self.redis:
            return None

        try:
            value = await self.redis.get(key)
            if value:
                logger.debug(f"Cache HIT: {key}")
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Erro ao GET cache {key}: {e}")
            return None

    async def delete(self, key: str) -> bool:
        """
        Deleta um valor do cache

        Args:
            key: Chave do cache

        Returns:
            True se deletado, False caso contrário
        """
        if not self.enabled or not self.redis:
            return False

        try:
            await self.redis.delete(key)
            logger.debug(f"Cache DELETE: {key}")
            return True
        except Exception as e:
            logger.error(f"Erro ao DELETE cache {key}: {e}")
            return False

    async def clear_pattern(self, pattern: str) -> int:
        """
        Deleta todos as chaves que correspondem a um padrão

        Args:
            pattern: Padrão GLOB (ex: "agent:*")

        Returns:
            Número de chaves deletadas
        """
        if not self.enabled or not self.redis:
            return 0

        try:
            keys = await self.redis.keys(pattern)
            if keys:
                if AIOREDIS_V2:
                    await self.redis.delete(*keys)
                else:
                    await self.redis.delete(*keys)
                logger.debug(f"Cache CLEAR PATTERN: {pattern} ({len(keys)} chaves)")
                return len(keys)
            return 0
        except Exception as e:
            logger.error(f"Erro ao CLEAR PATTERN {pattern}: {e}")
            return 0

    async def flush_all(self) -> bool:
        """
        Limpa todo o cache

        Returns:
            True se sucesso, False caso contrário
        """
        if not self.enabled or not self.redis:
            return False

        try:
            if AIOREDIS_V2:
                await self.redis.flushdb(asynchronous=False)
            else:
                await self.redis.flushdb()
            logger.warning("Cache FLUSH: Todos os dados deletados")
            return True
        except Exception as e:
            logger.error(f"Erro ao FLUSH cache: {e}")
            return False

class CacheKeys:
    """Constantes para chaves de cache"""

    @staticmethod
    def agent_data(agent_id: str) -> str:
        """Chave para dados de um agente"""
        return f"agent:{agent_id}:data"

    @staticmethod
    def agent_metrics(agent_id: str) -> str:
        """Chave para métricas de um agente"""
        return f"agent:{agent_id}:metrics"

    @staticmethod
    def agent_list() -> str:
        """Chave para lista de todos os agentes"""
        return "agents:list"

    @staticmethod
    def setting(category: str, key: str) -> str:
        """Chave para uma configuração"""
        return f"setting:{category}:{key}"

    @staticmethod
    def user(user_id: int) -> str:
        """Chave para dados de um usuário"""
        return f"user:{user_id}"

# Instância global
cache = RedisCache()
