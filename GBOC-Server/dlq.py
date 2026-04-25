"""
GBOC Server - Dead Letter Queue
Armazenamento de mensagens que falharam para reprocessamento posterior
"""
import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Any
from config import DEAD_LETTER_QUEUE_ENABLED, DLQ_FILE, DLQ_MAX_SIZE_MB
from logger import setup_logger

logger = setup_logger(__name__)

class DeadLetterQueue:
    """Gerenciador de Dead Letter Queue para mensagens falhadas"""

    def __init__(self):
        self.enabled = DEAD_LETTER_QUEUE_ENABLED
        self.file_path = DLQ_FILE
        self.max_size_bytes = DLQ_MAX_SIZE_MB * 1024 * 1024

        # Garantir diretório existe
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    def add(
        self,
        message: Dict[str, Any],
        error: str,
        context: Dict[str, Any] = None,
        retry_count: int = 0
    ) -> bool:
        """
        Adiciona uma mensagem falhada à DLQ

        Args:
            message: Mensagem original que falhou
            error: Descrição do erro
            context: Contexto adicional (agent_id, endpoint, etc.)
            retry_count: Número de tentativas anteriores

        Returns:
            True se adicionado com sucesso, False caso contrário
        """
        if not self.enabled:
            return False

        try:
            dlq_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": message,
                "error": error,
                "context": context or {},
                "retry_count": retry_count,
                "next_retry": self._calculate_next_retry(retry_count)
            }

            # Verificar tamanho do arquivo
            if os.path.exists(self.file_path):
                file_size = os.path.getsize(self.file_path)
                if file_size > self.max_size_bytes:
                    logger.warning(f"DLQ atingiu tamanho máximo ({DLQ_MAX_SIZE_MB}MB), limpando...")
                    self._cleanup_old_entries()

            # Adicionar entrada
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(dlq_entry, ensure_ascii=False) + "\n")

            logger.warning(
                f"Mensagem adicionada à DLQ: {context.get('agent_id', 'unknown')} - "
                f"Error: {error[:100]}"
            )
            return True

        except Exception as e:
            logger.error(f"Erro ao adicionar mensagem à DLQ: {e}")
            return False

    def get_pending(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Recupera mensagens pendentes de reprocessamento

        Args:
            limit: Máximo de mensagens a recuperar

        Returns:
            Lista de mensagens da DLQ
        """
        if not self.enabled or not os.path.exists(self.file_path):
            return []

        try:
            entries = []
            current_time = datetime.now(timezone.utc)

            with open(self.file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue

                    entry = json.loads(line)

                    # Verificar se está pronto para retry
                    next_retry = datetime.fromisoformat(entry.get("next_retry", "1970-01-01"))
                    if next_retry <= current_time:
                        entries.append(entry)
                        if len(entries) >= limit:
                            break

            return entries

        except Exception as e:
            logger.error(f"Erro ao recuperar mensagens da DLQ: {e}")
            return []

    def remove(self, timestamp: str) -> bool:
        """
        Remove uma mensagem da DLQ (após reprocessamento bem-sucedido)

        Args:
            timestamp: Timestamp da entrada a remover

        Returns:
            True se removida, False caso contrário
        """
        if not self.enabled or not os.path.exists(self.file_path):
            return False

        try:
            temp_file = self.file_path + ".tmp"
            removed = False

            with open(self.file_path, "r", encoding="utf-8") as f_in:
                with open(temp_file, "w", encoding="utf-8") as f_out:
                    for line in f_in:
                        if line.strip():
                            entry = json.loads(line)
                            if entry.get("timestamp") != timestamp:
                                f_out.write(line)
                            else:
                                removed = True

            if removed:
                os.replace(temp_file, self.file_path)
                logger.info(f"Mensagem removida da DLQ: {timestamp}")
            else:
                os.remove(temp_file)

            return removed

        except Exception as e:
            logger.error(f"Erro ao remover mensagem da DLQ: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """
        Obtém estatísticas da DLQ

        Returns:
            Dicionário com estatísticas
        """
        if not self.enabled or not os.path.exists(self.file_path):
            return {"total": 0, "pending": 0, "file_size_mb": 0}

        try:
            total_entries = 0
            pending_entries = 0
            current_time = datetime.now(timezone.utc)

            with open(self.file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        total_entries += 1
                        entry = json.loads(line)
                        next_retry = datetime.fromisoformat(entry.get("next_retry", "1970-01-01"))
                        if next_retry <= current_time:
                            pending_entries += 1

            file_size = os.path.getsize(self.file_path)

            return {
                "total": total_entries,
                "pending": pending_entries,
                "file_size_mb": file_size / (1024 * 1024),
                "max_size_mb": DLQ_MAX_SIZE_MB
            }

        except Exception as e:
            logger.error(f"Erro ao obter estatísticas da DLQ: {e}")
            return {}

    @staticmethod
    def _calculate_next_retry(retry_count: int) -> str:
        """
        Calcula o tempo da próxima tentativa usando backoff exponencial

        Args:
            retry_count: Número de tentativas anteriores

        Returns:
            ISO format timestamp da próxima tentativa
        """
        # Backoff exponencial: 1min, 5min, 15min, 1h, etc
        delays = [60, 300, 900, 3600, 7200, 14400]
        delay = delays[min(retry_count, len(delays) - 1)]

        next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay)
        return next_retry.isoformat()

from datetime import timedelta

# Instância global
dlq = DeadLetterQueue()
