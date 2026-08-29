#!/usr/bin/env python3
"""
GBOC Agent - Gerenciador de Configuração do Servidor Central
Módulo para gerenciar configurações do cliente do servidor central
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ServerConfigManager:
    """Gerenciador de configuração do servidor central"""

    def __init__(self):
        self.config_dir = Path("C:/ProgramData/GBOC") if os.name == 'nt' else Path.home() / ".gboc"
        self.config_file = self.config_dir / "central_config.json"
        self._config = {}
        self._load_config()

    def _load_config(self):
        """Carrega configuração do arquivo"""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)

            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
                logger.debug("✅ Configuração carregada do arquivo")
            else:
                logger.info("📝 Arquivo de configuração não encontrado, criando padrão")
                self._create_default_config()
        except Exception as e:
            logger.error(f"Erro ao carregar configuração: {e}")
            self._config = self._get_default_config()

    def _create_default_config(self):
        """Cria arquivo de configuração padrão"""
        self._config = self._get_default_config()

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.info(f"✅ Configuração padrão criada: {self.config_file}")
        except Exception as e:
            logger.error(f"Erro ao criar configuração padrão: {e}")

    def _get_default_config(self) -> Dict[str, Any]:
        """Retorna configuração padrão"""
        return {
            "server_url": "https://localhost:8000",
            "api_key": "gboc-local-server-key",
            "tenant_id": None,  # MSP Tenant ID
            "enabled": True,  # Habilitado por padrão
            "heartbeat_interval_minutes": 2,
            "sync_interval_minutes": 10,
            "send_logs": True,
            "send_metrics": True,
            "auto_connect": True,
            "max_retry_attempts": 5,
            "retry_delay_seconds": 30
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Obtém valor da configuração"""
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        """Define valor na configuração"""
        self._config[key] = value
        self._save_config()

    def update(self, updates: Dict[str, Any]):
        """Atualiza múltiplos valores de configuração"""
        self._config.update(updates)
        self._save_config()

    def _save_config(self):
        """Salva configuração no arquivo"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.debug("✅ Configuração salva")
        except Exception as e:
            logger.error(f"Erro ao salvar configuração: {e}")

    def reload(self):
        """Recarrega configuração do arquivo"""
        self._load_config()
        logger.info("🔄 Configuração recarregada")

    def get_all(self) -> Dict[str, Any]:
        """Retorna toda a configuração"""
        return self._config.copy()

    def is_enabled(self) -> bool:
        """Verifica se o cliente do servidor está habilitado"""
        return bool(self.get('enabled', True))

    def get_server_url(self) -> str:
        """Retorna URL do servidor"""
        return self.get('server_url', 'https://localhost:8000')

    def get_api_key(self) -> str:
        """Retorna chave da API"""
        return self.get('api_key', 'gboc-local-server-key')

    def get_tenant_id(self) -> Optional[str]:
        """Retorna o tenant_id configurado"""
        return self.get('tenant_id', None)

    def set_tenant_id(self, tenant_id: Optional[str]):
        """Define o tenant_id configurado"""
        self.set('tenant_id', tenant_id)

    def get_heartbeat_interval(self) -> int:
        """Retorna intervalo do heartbeat em minutos"""
        return self.get('heartbeat_interval_minutes', 2)

    def get_sync_interval(self) -> int:
        """Retorna intervalo de sincronização em minutos"""
        return self.get('sync_interval_minutes', 10)

    def should_send_logs(self) -> bool:
        """Verifica se deve enviar logs"""
        return self.get('send_logs', True)

    def should_send_metrics(self) -> bool:
        """Verifica se deve enviar métricas"""
        return self.get('send_metrics', True)

    def get_max_retries(self) -> int:
        """Retorna número máximo de tentativas de reconexão"""
        return self.get('max_retry_attempts', 5)

    def get_retry_delay(self) -> int:
        """Retorna delay entre tentativas de reconexão em segundos"""
        return self.get('retry_delay_seconds', 30)

    def validate_config(self) -> Dict[str, Any]:
        """Valida configuração e retorna problemas encontrados"""
        issues = []

        # Validar URL do servidor
        server_url = self.get_server_url()
        if not server_url.startswith(('http://', 'https://')):
            issues.append(f"URL do servidor inválida: {server_url}")

        # Validar intervalos
        heartbeat_interval = self.get_heartbeat_interval()
        if not (1 <= heartbeat_interval <= 60):
            issues.append(f"Intervalo do heartbeat deve ser entre 1-60 min: {heartbeat_interval}")

        sync_interval = self.get_sync_interval()
        if not (5 <= sync_interval <= 1440):  # 5 min até 24h
            issues.append(f"Intervalo de sincronização deve ser entre 5-1440 min: {sync_interval}")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "config": self.get_all()
        }

    def reset_to_defaults(self):
        """Reseta configuração para valores padrão"""
        self._config = self._get_default_config()
        self._save_config()
        logger.info("🔄 Configuração resetada para valores padrão")

# Instância global
config_manager = ServerConfigManager()
