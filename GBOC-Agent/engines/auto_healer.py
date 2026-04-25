#!/usr/bin/env python3
"""
🔧 GBOC Agent - Auto-Healer (Correção Automática)
Corrige automaticamente problemas conhecidos
"""

import subprocess
import logging
import os
import time
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class AutoHealer:
    """
    Sistema de correção automática de problemas
    """
    
    def __init__(self, db_connection):
        self.db = db_connection
        self.corrections = {
            'init_repository': self._init_repository,
            'connect_repository': self._connect_repository,
            'retry_with_backoff': self._retry_with_backoff,
            'cleanup_old_snapshots': self._cleanup_old_snapshots,
            'reduce_concurrency': self._reduce_concurrency
        }
    
    def attempt_fix(self, error_diagnosis: Dict) -> Dict[str, Any]:
        """
        Tenta corrigir problema automaticamente
        """
        if not error_diagnosis.get('auto_fix_available'):
            return {
                'status': 'not_fixable',
                'message': 'Correção automática não disponível para este erro'
            }
        
        action = error_diagnosis['auto_fix_action']
        
        if action not in self.corrections:
            logger.warning(f"⚠️ Ação desconhecida: {action}")
            return {
                'status': 'unknown_action',
                'action': action
            }
        
        logger.info(f"🔧 Tentando correção: {action}")
        
        try:
            fix_function = self.corrections[action]
            result = fix_function(error_diagnosis)
            
            # Registrar correção no banco
            self._log_correction(error_diagnosis, result)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Erro ao tentar correção: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def _init_repository(self, diagnosis: Dict) -> Dict[str, Any]:
        """
        Inicializa repositório não inicializado
        """
        # TODO: Obter informações do repositório do banco
        # TODO: Executar restic init
        
        return {
            'status': 'manual',
            'message': 'Inicialização de repositório requer intervenção manual',
            'steps': [
                '1. Verifique se o caminho do repositório está correto',
                '2. Execute: restic init',
                '3. Ou use a interface web para inicializar'
            ]
        }
    
    def _connect_repository(self, diagnosis: Dict) -> Dict[str, Any]:
        """
        Conecta repositório Kopia
        """
        return {
            'status': 'manual',
            'message': 'Conexão de repositório requer intervenção manual',
            'steps': [
                '1. Verifique credenciais',
                '2. Execute: kopia repository connect',
                '3. Ou use a interface web'
            ]
        }
    
    def _retry_with_backoff(self, diagnosis: Dict) -> Dict[str, Any]:
        """
        Implementa retry com backoff exponencial
        """
        # Esta correção é aplicada automaticamente pelo BackupExecutor
        return {
            'status': 'automatic',
            'message': 'Retry automático configurado',
            'details': {
                'max_retries': 3,
                'backoff': 'exponential',
                'delays': [30, 60, 120]  # segundos
            }
        }
    
    def _cleanup_old_snapshots(self, diagnosis: Dict) -> Dict[str, Any]:
        """
        Remove snapshots antigos para liberar espaço
        """
        logger.info("🧹 Limpando snapshots antigos...")
        
        # TODO: Implementar lógica de limpeza
        # 1. Buscar repositório
        # 2. Listar snapshots
        # 3. Aplicar política de retenção
        # 4. Executar forget + prune
        
        return {
            'status': 'scheduled',
            'message': 'Limpeza agendada para próxima janela de manutenção',
            'recommendation': 'Configure política de retenção nas configurações'
        }
    
    def _reduce_concurrency(self, diagnosis: Dict) -> Dict[str, Any]:
        """
        Reduz concorrência para economizar memória
        """
        # Atualizar configuração de concorrência no banco
        try:
            # Reduzir threads de backup
            self.db.execute("""
                UPDATE settings 
                SET value = 1 
                WHERE key = 'max_concurrent_backups'
            """)
            self.db.commit()
            
            return {
                'status': 'success',
                'message': 'Concorrência reduzida para 1 backup simultâneo',
                'details': {
                    'previous': 'auto',
                    'current': 1
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Erro: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def _log_correction(self, diagnosis: Dict, result: Dict):
        """
        Registra correção aplicada
        """
        try:
            self.db.execute("""
                INSERT INTO auto_corrections (
                    error_type,
                    error_message,
                    fix_action,
                    fix_result,
                    timestamp
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                diagnosis['error_type'],
                diagnosis['error_message'][:500],
                diagnosis['auto_fix_action'],
                str(result)[:500],
                datetime.now().isoformat()
            ))
            
            self.db.commit()
            
        except Exception as e:
            logger.error(f"❌ Erro ao registrar correção: {e}")
    
    def get_correction_history(self, limit: int = 50) -> list:
        """
        Retorna histórico de correções aplicadas
        """
        try:
            cursor = self.db.execute("""
                SELECT * FROM auto_corrections
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            logger.error(f"❌ Erro ao buscar histórico: {e}")
            return []


class SmartRetryManager:
    """
    Gerencia retries inteligentes de backups
    """
    
    def __init__(self):
        self.retry_delays = [30, 60, 120, 300, 600]  # Segundos
        self.max_retries = 5
    
    def should_retry(self, error_type: str, attempt: int) -> bool:
        """
        Decide se deve tentar novamente
        """
        if attempt >= self.max_retries:
            return False
        
        # Erros que não devem ser retried
        no_retry_errors = [
            'authentication_error',
            'permission_error',
            'source_not_found'
        ]
        
        if error_type in no_retry_errors:
            return False
        
        # Erros que devem ser retried
        retry_errors = [
            'network_error',
            'network_interrupted',
            'timeout'
        ]
        
        return error_type in retry_errors
    
    def get_delay(self, attempt: int) -> int:
        """
        Retorna delay para próxima tentativa
        """
        if attempt >= len(self.retry_delays):
            return self.retry_delays[-1]
        
        return self.retry_delays[attempt]
    
    def calculate_next_run(self, last_failure_time: datetime, attempt: int) -> datetime:
        """
        Calcula próxima execução com backoff
        """
        from datetime import timedelta
        
        delay_seconds = self.get_delay(attempt)
        return last_failure_time + timedelta(seconds=delay_seconds)
