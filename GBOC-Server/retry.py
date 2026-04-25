"""
GBOC Server - Retry Logic com Backoff Exponencial
Sistema de retry automático para operações que falham
"""
import asyncio
from typing import Callable, Any, Optional, Dict
from datetime import datetime
from logger import setup_logger

logger = setup_logger(__name__)

class RetryConfig:
    """Configuração para retry"""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        """
        Args:
            max_attempts: Máximo de tentativas
            base_delay: Delay inicial em segundos
            max_delay: Delay máximo em segundos
            exponential_base: Base para cálculo exponencial
            jitter: Adicionar randomização ao delay
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter

class RetryHandler:
    """Handler para retrys com backoff exponencial"""

    @staticmethod
    def calculate_delay(attempt: int, config: RetryConfig) -> float:
        """
        Calcula delay para a próxima tentativa

        Args:
            attempt: Número da tentativa (0-indexed)
            config: Configuração de retry

        Returns:
            Delay em segundos
        """
        delay = config.base_delay * (config.exponential_base ** attempt)
        delay = min(delay, config.max_delay)

        if config.jitter:
            import random
            delay = delay * (0.5 + random.random())

        return delay

    @staticmethod
    async def execute_with_retry(
        func: Callable,
        *args,
        config: RetryConfig = None,
        context: Dict[str, Any] = None,
        **kwargs
    ) -> Optional[Any]:
        """
        Executa uma função com retry automático

        Args:
            func: Função a executar (pode ser async ou sync)
            args: Argumentos posicionais
            config: Configuração de retry (padrão: 3 tentativas)
            context: Contexto adicional para logging
            kwargs: Argumentos nomeados

        Returns:
            Resultado da função ou None se todas as tentativas falharem
        """
        if config is None:
            config = RetryConfig()

        context = context or {}
        is_async = asyncio.iscoroutinefunction(func)

        for attempt in range(config.max_attempts):
            try:
                logger.debug(
                    f"Tentativa {attempt + 1}/{config.max_attempts} - "
                    f"{func.__name__} - {context}"
                )

                if is_async:
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                if attempt > 0:
                    logger.info(
                        f"✓ {func.__name__} bem-sucedido após {attempt} retry(s) - {context}"
                    )

                return result

            except Exception as e:
                if attempt < config.max_attempts - 1:
                    delay = RetryHandler.calculate_delay(attempt, config)
                    logger.warning(
                        f"✗ {func.__name__} falhou (tentativa {attempt + 1}): {e}. "
                        f"Retry em {delay:.1f}s - {context}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"✗ {func.__name__} falhou após {config.max_attempts} tentativas - {context}: {e}"
                    )
                    return None

        return None

    @staticmethod
    def execute_with_retry_sync(
        func: Callable,
        *args,
        config: RetryConfig = None,
        context: Dict[str, Any] = None,
        **kwargs
    ) -> Optional[Any]:
        """
        Versão síncrona de execute_with_retry

        Args:
            func: Função a executar (deve ser sync)
            args: Argumentos posicionais
            config: Configuração de retry
            context: Contexto adicional para logging
            kwargs: Argumentos nomeados

        Returns:
            Resultado da função ou None se falhar
        """
        if config is None:
            config = RetryConfig()

        context = context or {}

        for attempt in range(config.max_attempts):
            try:
                logger.debug(
                    f"Tentativa {attempt + 1}/{config.max_attempts} - "
                    f"{func.__name__} - {context}"
                )

                result = func(*args, **kwargs)

                if attempt > 0:
                    logger.info(
                        f"✓ {func.__name__} bem-sucedido após {attempt} retry(s) - {context}"
                    )

                return result

            except Exception as e:
                if attempt < config.max_attempts - 1:
                    delay = RetryHandler.calculate_delay(attempt, config)
                    logger.warning(
                        f"✗ {func.__name__} falhou (tentativa {attempt + 1}): {e}. "
                        f"Retry em {delay:.1f}s - {context}"
                    )
                    import time
                    time.sleep(delay)
                else:
                    logger.error(
                        f"✗ {func.__name__} falhou após {config.max_attempts} tentativas - {context}: {e}"
                    )
                    return None

        return None

# Configurações pré-definidas
DEFAULT_RETRY_CONFIG = RetryConfig(max_attempts=3)
AGGRESSIVE_RETRY_CONFIG = RetryConfig(max_attempts=5, base_delay=2.0)
GENTLE_RETRY_CONFIG = RetryConfig(max_attempts=2, base_delay=0.5)
