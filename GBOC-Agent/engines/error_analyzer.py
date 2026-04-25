#!/usr/bin/env python3
"""
🔍 GBOC Agent - Analisador de Erros com Sugestões
Analisa erros de backup e sugere correções automáticas
"""

import logging
import re
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ErrorAnalyzer:
    """
    Analisa erros e sugere correções
    """
    
    def __init__(self, db_connection):
        self.db = db_connection
        self.error_patterns = self._load_error_patterns()
    
    def _load_error_patterns(self) -> List[Dict]:
        """
        Define padrões de erros conhecidos e suas soluções
        """
        return [
            # RESTIC
            {
                'engine': 'restic',
                'pattern': r'Fatal: unable to open config file',
                'type': 'repository_not_found',
                'severity': 'critical',
                'message': 'Repositório não encontrado ou não inicializado',
                'solution': 'Execute: restic init',
                'auto_fix': 'init_repository'
            },
            {
                'engine': 'restic',
                'pattern': r'wrong password',
                'type': 'authentication_error',
                'severity': 'critical',
                'message': 'Senha do repositório incorreta',
                'solution': 'Verifique a senha configurada no repositório',
                'auto_fix': None
            },
            {
                'engine': 'restic',
                'pattern': r'connection refused|timeout',
                'type': 'network_error',
                'severity': 'high',
                'message': 'Erro de conexão com repositório remoto',
                'solution': 'Verifique conexão de rede e credenciais',
                'auto_fix': 'retry_with_backoff'
            },
            {
                'engine': 'restic',
                'pattern': r'no such file or directory',
                'type': 'source_not_found',
                'severity': 'high',
                'message': 'Caminho de origem não existe',
                'solution': 'Verifique se o caminho está correto',
                'auto_fix': None
            },
            {
                'engine': 'restic',
                'pattern': r'access denied|permission denied',
                'type': 'permission_error',
                'severity': 'high',
                'message': 'Sem permissão para acessar arquivos',
                'solution': 'Execute o agente com privilégios de administrador',
                'auto_fix': None
            },
            {
                'engine': 'restic',
                'pattern': r'not enough space|disk full',
                'type': 'disk_full',
                'severity': 'critical',
                'message': 'Espaço em disco insuficiente',
                'solution': 'Libere espaço no disco de destino',
                'auto_fix': 'cleanup_old_snapshots'
            },
            
            # KOPIA
            {
                'engine': 'kopia',
                'pattern': r'repository not connected',
                'type': 'repository_not_connected',
                'severity': 'critical',
                'message': 'Repositório não conectado',
                'solution': 'Execute: kopia repository connect',
                'auto_fix': 'connect_repository'
            },
            {
                'engine': 'kopia',
                'pattern': r'invalid credentials',
                'type': 'authentication_error',
                'severity': 'critical',
                'message': 'Credenciais inválidas',
                'solution': 'Verifique as credenciais do repositório',
                'auto_fix': None
            },
            
            # DUPLICATI
            {
                'engine': 'duplicati',
                'pattern': r'Backend not found',
                'type': 'backend_error',
                'severity': 'critical',
                'message': 'Backend de armazenamento não encontrado',
                'solution': 'Verifique configuração do destino',
                'auto_fix': None
            },
            
            # ERROS GERAIS
            {
                'engine': 'all',
                'pattern': r'out of memory|oom',
                'type': 'memory_error',
                'severity': 'high',
                'message': 'Memória insuficiente',
                'solution': 'Reduza o tamanho do backup ou aumente memória',
                'auto_fix': 'reduce_concurrency'
            },
            {
                'engine': 'all',
                'pattern': r'connection reset|broken pipe',
                'type': 'network_interrupted',
                'severity': 'medium',
                'message': 'Conexão interrompida',
                'solution': 'Backup será retomado automaticamente',
                'auto_fix': 'retry_with_backoff'
            }
        ]
    
    def analyze_error(self, error_message: str, engine: str) -> Dict[str, Any]:
        """
        Analisa mensagem de erro e retorna diagnóstico
        """
        diagnosis = {
            'error_message': error_message,
            'engine': engine,
            'matched_pattern': None,
            'error_type': 'unknown',
            'severity': 'medium',
            'user_message': 'Erro desconhecido',
            'solution': 'Verifique os logs para mais detalhes',
            'auto_fix_available': False,
            'auto_fix_action': None,
            'timestamp': datetime.now().isoformat()
        }
        
        # Procurar padrão correspondente
        for pattern_def in self.error_patterns:
            if pattern_def['engine'] not in ['all', engine]:
                continue
            
            if re.search(pattern_def['pattern'], error_message, re.IGNORECASE):
                diagnosis.update({
                    'matched_pattern': pattern_def['pattern'],
                    'error_type': pattern_def['type'],
                    'severity': pattern_def['severity'],
                    'user_message': pattern_def['message'],
                    'solution': pattern_def['solution'],
                    'auto_fix_available': pattern_def['auto_fix'] is not None,
                    'auto_fix_action': pattern_def['auto_fix']
                })
                break
        
        return diagnosis
    
    def analyze_task_failures(self, task_id: int) -> Dict[str, Any]:
        """
        Analisa histórico de falhas de uma tarefa
        """
        try:
            # Buscar execuções com falha
            cursor = self.db.execute("""
                SELECT error_message, completed_at
                FROM task_executions
                WHERE task_id = ? AND status = 'failed'
                ORDER BY completed_at DESC
                LIMIT 10
            """, (task_id,))
            
            failures = cursor.fetchall()
            
            if not failures:
                return {
                    'task_id': task_id,
                    'failure_count': 0,
                    'status': 'healthy'
                }
            
            # Buscar informações da tarefa
            task_cursor = self.db.execute(
                "SELECT name, engine FROM tasks WHERE id = ?",
                (task_id,)
            )
            task = task_cursor.fetchone()
            
            # Analisar cada falha
            analyses = []
            error_types = {}
            
            for failure in failures:
                error_msg = failure[0]
                diagnosis = self.analyze_error(error_msg, task['engine'])
                analyses.append(diagnosis)
                
                error_type = diagnosis['error_type']
                error_types[error_type] = error_types.get(error_type, 0) + 1
            
            # Encontrar erro mais comum
            most_common_error = max(error_types, key=error_types.get) \
                if error_types else 'unknown'
            
            # Severidade geral
            severities = [a['severity'] for a in analyses]
            has_critical = 'critical' in severities
            
            return {
                'task_id': task_id,
                'task_name': task['name'],
                'failure_count': len(failures),
                'most_common_error': most_common_error,
                'error_distribution': error_types,
                'severity': 'critical' if has_critical else 'high',
                'recent_analyses': analyses[:3],  # 3 mais recentes
                'recommendation': self._get_recommendation(most_common_error, error_types)
            }
            
        except Exception as e:
            logger.error(f"❌ Erro ao analisar falhas: {e}")
            return {
                'task_id': task_id,
                'error': str(e)
            }
    
    def _get_recommendation(self, most_common: str, distribution: Dict) -> str:
        """
        Gera recomendação baseada no histórico de erros
        """
        if distribution.get('authentication_error', 0) > 2:
            return "❌ Múltiplas falhas de autenticação. Verifique urgentemente as credenciais."
        
        if distribution.get('network_error', 0) > 5:
            return "⚠️ Muitos erros de rede. Considere mudar para backup local ou verificar firewall."
        
        if distribution.get('disk_full', 0) > 0:
            return "💾 Disco cheio. Libere espaço ou configure limpeza automática de snapshots antigos."
        
        if distribution.get('permission_error', 0) > 0:
            return "🔒 Problemas de permissão. Execute o agente como administrador."
        
        if len(distribution) > 3:
            return "⚠️ Múltiplos tipos de erro. Revise configuração completa da tarefa."
        
        return "ℹ️ Erro intermitente. Monitor os próximos backups."
    
    def get_system_health_report(self) -> Dict[str, Any]:
        """
        Gera relatório de saúde do sistema
        """
        try:
            report = {
                'timestamp': datetime.now().isoformat(),
                'overall_health': 'good',
                'issues': [],
                'statistics': {},
                'recommendations': []
            }
            
            # 1. Verificar tarefas com falhas recentes
            cursor = self.db.execute("""
                SELECT task_id, COUNT(*) as failures
                FROM task_executions
                WHERE status = 'failed' 
                    AND completed_at > datetime('now', '-7 days')
                GROUP BY task_id
                HAVING failures > 2
            """)
            
            problematic_tasks = cursor.fetchall()
            
            if problematic_tasks:
                report['overall_health'] = 'degraded'
                for row in problematic_tasks:
                    analysis = self.analyze_task_failures(row[0])
                    report['issues'].append(analysis)
            
            # 2. Verificar repositórios inacessíveis
            # TODO: Adicionar verificação de conectividade
            
            # 3. Estatísticas gerais
            stats_cursor = self.db.execute("""
                SELECT 
                    COUNT(*) as total_executions,
                    SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as successes,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failures
                FROM task_executions
                WHERE completed_at > datetime('now', '-30 days')
            """)
            
            stats = stats_cursor.fetchone()
            
            total = stats[0]
            successes = stats[1]
            failures = stats[2]
            
            success_rate = (successes / total * 100) if total > 0 else 0
            
            report['statistics'] = {
                'total_executions_30d': total,
                'successes': successes,
                'failures': failures,
                'success_rate': round(success_rate, 1)
            }
            
            # Avaliar saúde geral
            if success_rate < 50:
                report['overall_health'] = 'critical'
                report['recommendations'].append(
                    "❌ Taxa de sucesso muito baixa! Revise configurações urgentemente."
                )
            elif success_rate < 80:
                report['overall_health'] = 'warning'
                report['recommendations'].append(
                    "⚠️ Taxa de sucesso abaixo do ideal. Investigue falhas recorrentes."
                )
            
            return report
            
        except Exception as e:
            logger.error(f"❌ Erro ao gerar relatório: {e}")
            return {
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            }
