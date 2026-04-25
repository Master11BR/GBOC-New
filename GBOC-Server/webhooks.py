"""
GBOC Server - Webhooks (Desabilitado - Estrutura pronta para futuro)
Sistema de notificações via webhook para eventos do servidor
"""
import json
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from config import WEBHOOKS_ENABLED, WEBHOOK_TIMEOUT, WEBHOOK_MAX_RETRIES
from logger import setup_logger
from dlq import dlq

logger = setup_logger(__name__)

class WebhookManager:
    """Gerenciador de webhooks para notificações externas"""

    def __init__(self):
        self.enabled = WEBHOOKS_ENABLED
        self.webhooks: Dict[str, Dict] = {}

    def register_webhook(
        self,
        webhook_id: str,
        url: str,
        events: List[str],
        headers: Optional[Dict] = None,
        active: bool = True
    ) -> bool:
        """
        Registra um novo webhook

        Args:
            webhook_id: ID único do webhook
            url: URL de destino
            events: Lista de eventos a notificar (ex: ["agent_offline", "backup_failed"])
            headers: Headers customizados
            active: Se está ativo

        Returns:
            True se registrado com sucesso
        """
        if not self.enabled:
            logger.warning("Webhooks desabilitados. Skipping registration.")
            return False

        try:
            self.webhooks[webhook_id] = {
                "url": url,
                "events": events,
                "headers": headers or {},
                "active": active,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "retry_count": 0
            }
            logger.info(f"Webhook registrado: {webhook_id} -> {url}")
            return True
        except Exception as e:
            logger.error(f"Erro ao registrar webhook: {e}")
            return False

    def unregister_webhook(self, webhook_id: str) -> bool:
        """
        Remove um webhook

        Args:
            webhook_id: ID do webhook a remover

        Returns:
            True se removido, False caso contrário
        """
        if webhook_id in self.webhooks:
            del self.webhooks[webhook_id]
            logger.info(f"Webhook removido: {webhook_id}")
            return True
        return False

    async def trigger_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        context: Dict[str, Any] = None
    ) -> bool:
        """
        Dispara um evento para todos os webhooks configurados

        Args:
            event_type: Tipo do evento (ex: "agent_offline")
            payload: Dados do evento
            context: Contexto adicional

        Returns:
            True se pelo menos um webhook foi notificado com sucesso
        """
        if not self.enabled:
            logger.debug(f"Webhooks desabilitados. Event {event_type} não será notificado.")
            return False

        context = context or {}
        success_count = 0

        for webhook_id, webhook_config in self.webhooks.items():
            if not webhook_config["active"]:
                continue

            if event_type not in webhook_config["events"]:
                continue

            # Preparar payload
            webhook_payload = {
                "event": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": payload,
                "context": context
            }

            # Tentar enviar
            success = await self._send_webhook(
                webhook_id,
                webhook_config,
                webhook_payload
            )

            if success:
                success_count += 1
            else:
                # Adicionar à DLQ para reprocessamento
                dlq.add(
                    message=webhook_payload,
                    error=f"Webhook {webhook_id} falhou",
                    context={"webhook_id": webhook_id, "event_type": event_type}
                )

        return success_count > 0

    async def _send_webhook(
        self,
        webhook_id: str,
        webhook_config: Dict,
        payload: Dict[str, Any]
    ) -> bool:
        """
        Envia notificação via webhook

        Args:
            webhook_id: ID do webhook
            webhook_config: Configuração do webhook
            payload: Payload a enviar

        Returns:
            True se enviado com sucesso
        """
        try:
            # ESTRUTURA PRONTA MAS DESABILITADA
            # Implementar com httpx ou requests quando habilitado
            logger.warning(f"Webhook enviado (ESTRUTURA): {webhook_id} - {webhook_config['url']}")
            return True

        except Exception as e:
            logger.error(f"Erro ao enviar webhook {webhook_id}: {e}")
            return False

    def get_webhooks(self, event_type: str = None) -> List[Dict]:
        """
        Lista webhooks

        Args:
            event_type: Filtrar por tipo de evento (opcional)

        Returns:
            Lista de webhooks
        """
        if event_type:
            return [
                w for w in self.webhooks.values()
                if event_type in w["events"]
            ]
        return list(self.webhooks.values())

    def get_stats(self) -> Dict[str, Any]:
        """
        Obtém estatísticas de webhooks

        Returns:
            Dicionário com estatísticas
        """
        active_count = sum(1 for w in self.webhooks.values() if w["active"])

        return {
            "total": len(self.webhooks),
            "active": active_count,
            "inactive": len(self.webhooks) - active_count,
            "enabled": self.enabled
        }

# Instância global
webhook_manager = WebhookManager()

# Eventos suportados
WEBHOOK_EVENTS = {
    "agent_online": "Agente conectado",
    "agent_offline": "Agente desconectado",
    "agent_error": "Erro no agente",
    "backup_started": "Backup iniciado",
    "backup_completed": "Backup concluído",
    "backup_failed": "Falha no backup",
    "task_scheduled": "Tarefa agendada",
    "task_completed": "Tarefa concluída",
    "task_failed": "Falha na tarefa",
    "alert_triggered": "Alerta disparado",
    "health_check_failed": "Health check falhou",
}
