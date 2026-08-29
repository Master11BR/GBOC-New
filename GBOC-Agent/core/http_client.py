#!/usr/bin/env python3
"""
GBOC Agent 13.2.0 - HTTP Client Singleton
"""
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class HTTPClientSingleton:
    """
    Singleton para gerenciar uma instância global do httpx.AsyncClient.
    Permite reutilização de conexões (Connection Pooling).
    """
    _client: Optional[httpx.AsyncClient] = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._client is None:
            # Fallback de segurança caso o lifespan não tenha sido configurado
            logger.warning("HTTPClientSingleton: Cliente não inicializado. Criando instância sob demanda.")
            cls._client = httpx.AsyncClient()
        return cls._client

    @classmethod
    def start(cls):
        cls._client = httpx.AsyncClient(timeout=30.0)

    @classmethod
    async def stop(cls):
        if cls._client:
            await cls._client.aclose()
            cls._client = None
