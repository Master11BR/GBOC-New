#!/usr/bin/env python3
"""
📊 GBOC Agent 14.0.0 - BACKUP ANALYTICS & SUGGESTIONS
Sistema de análise inteligente de backups com sugestões para o usuário
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any
from dataclasses import dataclass
import statistics

logger = logging.getLogger(__name__)

@dataclass
class BackupPattern:
    """Padrão de backup detectado"""
    frequency: str  # daily, weekly, monthly
    time_of_day: str
    size_trend: str  # growing, stable, shrinking
    success_rate: float
    avg_duration: int

@dataclass
class Suggestion:
    """Sugestão para o usuário"""
    type: str  # optimization, warning, recommendation
    priority: str  # high, medium, low
    title: str
    description: str
    action: str
    impact: str
    category: str

def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


class BackupAnalytics:
    """Sistema de análise de backups"""

    def __init__(self):
        self._init_analytics_tables()

    def _init_analytics_tables(self):
        """Inicializa tabelas de análise"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()

                # Tabela de padrões detectados
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS backup_patterns (
                        id SERIAL PRIMARY KEY,
                        repository_id INTEGER,
                        pattern_type TEXT,
                        frequency TEXT,
                        confidence REAL,
                        detected_at TIMESTAMPTZ,
                        data TEXT DEFAULT '{}',
                        active BOOLEAN DEFAULT TRUE
                    )
                """)

                # Tabela de sugestões geradas
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_suggestions (
                        id SERIAL PRIMARY KEY,
                        type TEXT NOT NULL,
                        priority TEXT NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        action TEXT,
                        impact TEXT,
                        category TEXT,
                        repository_id INTEGER,
                        created_at TIMESTAMPTZ NOT NULL,
                        dismissed_at TIMESTAMPTZ,
                        applied_at TIMESTAMPTZ,
                        metadata TEXT DEFAULT '{}'
                    )
                """)

                # Tabela de métricas de performance
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS performance_metrics (
                        id SERIAL PRIMARY KEY,
                        repository_id INTEGER,
                        metric_name TEXT NOT NULL,
                        metric_value REAL NOT NULL,
                        metric_unit TEXT,
                        measurement_date TIMESTAMPTZ NOT NULL,
                        metadata TEXT DEFAULT '{}'
                    )
                """)

                conn.commit()
                logger.info("✅ Tabelas de analytics inicializadas")

        except Exception as e:
            logger.error(f"Erro ao inicializar analytics: {e}")
    
    def analyze_all_repositories(self) -> Dict[str, Any]:
        """Analisa todos os repositórios e gera insights"""
        try:
            logger.info("📊 Iniciando análise completa de backups...")
            
            repositories = self._get_repositories_for_analysis()
            analysis_results = {}
            
            for repo in repositories:
                repo_id = repo['id']
                logger.info(f"🔍 Analisando repositório: {repo['name']}")
                
                # Analisar padrões
                patterns = self._analyze_backup_patterns(repo_id)
                
                # Calcular métricas
                metrics = self._calculate_performance_metrics(repo_id)
                
                # Gerar sugestões
                suggestions = self._generate_suggestions(repo_id, patterns, metrics)
                
                analysis_results[repo_id] = {
                    "repository": repo,
                    "patterns": patterns,
                    "metrics": metrics,
                    "suggestions": suggestions,
                    "analyzed_at": datetime.now().isoformat()
                }
            
            # Salvar resultados
            self._save_analysis_results(analysis_results)
            
            return {
                "status": "success",
                "repositories_analyzed": len(repositories),
                "total_suggestions": sum(len(r['suggestions']) for r in analysis_results.values()),
                "results": analysis_results
            }
        
        except Exception as e:
            logger.error(f"Erro na análise: {e}")
            return {"status": "error", "error": str(e)}
    
    def _get_repositories_for_analysis(self) -> List[Dict[str, Any]]:
        """Obtém repositórios para análise"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT r.*,
                           COUNT(s.id) AS backup_count,
                           MAX(s.backup_date) AS last_backup
                    FROM repositories r
                    LEFT JOIN backup_statistics s ON r.id = s.repository_id
                    WHERE r.status = 'active'
                    GROUP BY r.id
                    HAVING COUNT(s.id) > 0
                """)
                cols = [d[0] for d in cursor.description] if cursor.description else []
                return [dict(zip(cols, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Erro ao obter repositórios: {e}")
            return []
    
    def _analyze_backup_patterns(self, repo_id: int) -> Dict[str, Any]:
        """Analisa padrões de backup de um repositório"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT backup_date, bytes_processed, duration_seconds, success
                    FROM backup_statistics
                    WHERE repository_id = %s AND backup_date > NOW() - INTERVAL '90 days'
                    ORDER BY backup_date
                """, (repo_id,))

                cols = [d[0] for d in cursor.description] if cursor.description else []
                backups = [dict(zip(cols, row)) for row in cursor.fetchall()]

                if len(backups) < 3:
                    return {"error": "Dados insuficientes", "backup_count": len(backups)}

                frequency_pattern = self._detect_frequency_pattern(backups)
                time_pattern = self._detect_time_pattern(backups)
                size_trend = self._analyze_size_trend(backups)

                success_rate = sum(1 for b in backups if b['success']) / len(backups) * 100

                durations = [b['duration_seconds'] for b in backups if b['duration_seconds']]
                avg_duration = statistics.mean(durations) if durations else 0

                return {
                    "backup_count": len(backups),
                    "frequency": frequency_pattern,
                    "preferred_time": time_pattern,
                    "size_trend": size_trend,
                    "success_rate": round(success_rate, 2),
                    "avg_duration_seconds": round(avg_duration, 2),
                    "last_30_days": len([b for b in backups if self._is_recent(b['backup_date'], 30)]),
                    "last_7_days": len([b for b in backups if self._is_recent(b['backup_date'], 7)])
                }

        except Exception as e:
            logger.error(f"Erro ao analisar padrões do repo {repo_id}: {e}")
            return {"error": str(e)}
    
    def _detect_frequency_pattern(self, backups: List[Dict]) -> str:
        """Detecta padrão de frequência dos backups"""
        if len(backups) < 2:
            return "irregular"
        
        # Calcular intervalos entre backups
        intervals = []
        for i in range(1, len(backups)):
            prev_date = datetime.fromisoformat(backups[i-1]['backup_date'])
            curr_date = datetime.fromisoformat(backups[i]['backup_date'])
            interval_hours = (curr_date - prev_date).total_seconds() / 3600
            intervals.append(interval_hours)
        
        if not intervals:
            return "irregular"
        
        avg_interval = statistics.mean(intervals)
        
        if avg_interval <= 25:  # ~1 dia
            return "daily"
        elif avg_interval <= 168:  # ~1 semana
            return "weekly"
        elif avg_interval <= 744:  # ~1 mês
            return "monthly"
        else:
            return "irregular"
    
    def _detect_time_pattern(self, backups: List[Dict]) -> str:
        """Detecta padrão de horário dos backups"""
        hours = []
        for backup in backups:
            try:
                backup_time = datetime.fromisoformat(backup['backup_date'])
                hours.append(backup_time.hour)
            except:
                continue
        
        if not hours:
            return "unknown"
        
        # Agrupar por períodos
        night = sum(1 for h in hours if 0 <= h < 6)
        morning = sum(1 for h in hours if 6 <= h < 12)
        afternoon = sum(1 for h in hours if 12 <= h < 18)
        evening = sum(1 for h in hours if 18 <= h < 24)
        
        max_period = max(night, morning, afternoon, evening)
        
        if max_period == night:
            return "night (00:00-06:00)"
        elif max_period == morning:
            return "morning (06:00-12:00)"
        elif max_period == afternoon:
            return "afternoon (12:00-18:00)"
        else:
            return "evening (18:00-24:00)"
    
    def _analyze_size_trend(self, backups: List[Dict]) -> str:
        """Analisa tendência do tamanho dos backups"""
        if len(backups) < 5:
            return "insufficient_data"
        
        sizes = [b['bytes_processed'] for b in backups if b['bytes_processed'] > 0]
        if len(sizes) < 5:
            return "insufficient_data"
        
        # Calcular tendência usando últimos 10 backups
        recent_sizes = sizes[-10:]
        if len(recent_sizes) < 5:
            recent_sizes = sizes
        
        # Comparar primeira e segunda metade
        mid = len(recent_sizes) // 2
        first_half_avg = statistics.mean(recent_sizes[:mid])
        second_half_avg = statistics.mean(recent_sizes[mid:])
        
        growth_rate = (second_half_avg - first_half_avg) / first_half_avg * 100
        
        if growth_rate > 20:
            return "growing_fast"
        elif growth_rate > 5:
            return "growing"
        elif growth_rate < -20:
            return "shrinking_fast"
        elif growth_rate < -5:
            return "shrinking"
        else:
            return "stable"
    
    def _is_recent(self, backup_date: str, days: int) -> bool:
        """Verifica se backup é recente"""
        try:
            backup_time = datetime.fromisoformat(backup_date)
            cutoff = datetime.now() - timedelta(days=days)
            return backup_time > cutoff
        except:
            return False
    
    def _calculate_performance_metrics(self, repo_id: int) -> Dict[str, Any]:
        """Calcula métricas de performance"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT
                        AVG(bytes_processed) AS avg_size,
                        AVG(duration_seconds) AS avg_duration,
                        COUNT(*) AS backup_count,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) AS successful_count,
                        MIN(backup_date) AS oldest_backup,
                        MAX(backup_date) AS newest_backup
                    FROM backup_statistics
                    WHERE repository_id = %s AND backup_date > NOW() - INTERVAL '30 days'
                """, (repo_id,))

                cols = [d[0] for d in cursor.description] if cursor.description else []
                row = dict(zip(cols, cursor.fetchone() or []))

                if not row or not row.get('backup_count'):
                    return {"error": "Sem dados dos últimos 30 dias"}

                avg_size_gb = (row['avg_size'] or 0) / (1024**3)
                avg_duration_hours = (row['avg_duration'] or 0) / 3600
                efficiency = avg_size_gb / avg_duration_hours if avg_duration_hours > 0 else 0

                cursor.execute("""
                    SELECT backup_date FROM backup_statistics
                    WHERE repository_id = %s AND backup_date > NOW() - INTERVAL '30 days'
                    ORDER BY backup_date
                """, (repo_id,))

                dates = [r[0] for r in cursor.fetchall()]
                time_consistency = self._calculate_time_consistency(dates)

                return {
                    "avg_size_gb": round(avg_size_gb, 2),
                    "avg_duration_minutes": round((row['avg_duration'] or 0) / 60, 2),
                    "success_rate": round((row['successful_count'] / row['backup_count']) * 100, 2),
                    "backup_frequency_days": round((row['backup_count'] / 30), 2),
                    "efficiency_gb_per_hour": round(efficiency, 2),
                    "time_consistency": time_consistency,
                    "data_period_days": 30
                }

        except Exception as e:
            logger.error(f"Erro ao calcular métricas do repo {repo_id}: {e}")
            return {"error": str(e)}
    
    def _calculate_time_consistency(self, dates: List[str]) -> float:
        """Calcula consistência de horário dos backups"""
        if len(dates) < 3:
            return 0.0
        
        try:
            hours = []
            for date_str in dates:
                dt = datetime.fromisoformat(date_str)
                hours.append(dt.hour)
            
            # Calcular desvio padrão das horas
            if len(set(hours)) == 1:
                return 100.0  # Perfeitamente consistente
            
            std_dev = statistics.stdev(hours)
            # Normalizar para 0-100 (0 = muito inconsistente, 100 = consistente)
            consistency = max(0, 100 - (std_dev * 10))
            return round(consistency, 2)
            
        except:
            return 0.0
    
    def _generate_suggestions(self, repo_id: int, patterns: Dict, metrics: Dict) -> List[Dict[str, Any]]:
        """Gera sugestões inteligentes para o repositório"""
        suggestions = []
        
        try:
            # Verificar taxa de sucesso
            if patterns.get('success_rate', 100) < 95:
                suggestions.append({
                    "type": "warning",
                    "priority": "high",
                    "title": "Taxa de Sucesso Baixa",
                    "description": f"Taxa de sucesso de apenas {patterns.get('success_rate')}%. Backups podem estar falhando.",
                    "action": "Verificar logs de erro e configuração do repositório",
                    "impact": "Risco de perda de dados",
                    "category": "reliability"
                })
            
            # Verificar frequência de backup
            if patterns.get('last_7_days', 0) == 0:
                suggestions.append({
                    "type": "warning",
                    "priority": "high",
                    "title": "Nenhum Backup Recente",
                    "description": "Não foram detectados backups nos últimos 7 dias.",
                    "action": "Executar backup manual e verificar agendamento",
                    "impact": "Alto risco de perda de dados",
                    "category": "frequency"
                })
            elif patterns.get('frequency') == 'irregular':
                suggestions.append({
                    "type": "recommendation",
                    "priority": "medium",
                    "title": "Agendamento Irregular",
                    "description": "Padrão de backup irregular detectado. Considere automatizar.",
                    "action": "Configurar agendamento automático (diário ou semanal)",
                    "impact": "Maior consistência na proteção de dados",
                    "category": "automation"
                })
            
            # Verificar tendência de crescimento
            if patterns.get('size_trend') == 'growing_fast':
                suggestions.append({
                    "type": "optimization",
                    "priority": "medium",
                    "title": "Crescimento Rápido Detectado",
                    "description": "Tamanho dos backups crescendo rapidamente. Considere otimizações.",
                    "action": "Implementar deduplicação ou compressão adicional",
                    "impact": "Redução de espaço de armazenamento",
                    "category": "storage"
                })
            
            # Verificar performance
            if metrics.get('avg_duration_minutes', 0) > 120:  # 2 horas
                suggestions.append({
                    "type": "optimization",
                    "priority": "medium",
                    "title": "Backup Lento",
                    "description": f"Backup demora em média {metrics.get('avg_duration_minutes')} minutos.",
                    "action": "Otimizar filtros de arquivo ou considerar backup incremental",
                    "impact": "Redução do tempo de backup",
                    "category": "performance"
                })
            
            # Verificar consistência de horário
            if metrics.get('time_consistency', 100) < 50:
                suggestions.append({
                    "type": "recommendation",
                    "priority": "low",
                    "title": "Horário Inconsistente",
                    "description": "Backups executados em horários muito variados.",
                    "action": "Padronizar horário de execução (ex: sempre às 2:00)",
                    "impact": "Melhor previsibilidade e organização",
                    "category": "scheduling"
                })
            
            # Verificar se está usando horário adequado
            preferred_time = patterns.get('preferred_time', '')
            if 'afternoon' in preferred_time or 'evening' in preferred_time:
                suggestions.append({
                    "type": "optimization",
                    "priority": "low",
                    "title": "Horário de Backup Sub-ótimo",
                    "description": "Backups executados durante horário de trabalho.",
                    "action": "Agendar backups para madrugada (00:00-06:00)",
                    "impact": "Melhor performance do sistema durante o dia",
                    "category": "scheduling"
                })
            
            # Sugestão de teste de restore
            if len(suggestions) == 0 or patterns.get('success_rate', 0) > 98:
                suggestions.append({
                    "type": "recommendation",
                    "priority": "low",
                    "title": "Teste de Recuperação",
                    "description": "Backups funcionando bem. Recomenda-se teste de recuperação.",
                    "action": "Fazer teste de restore de alguns arquivos",
                    "impact": "Validar integridade dos backups",
                    "category": "validation"
                })
        
        except Exception as e:
            logger.error(f"Erro ao gerar sugestões para repo {repo_id}: {e}")
        
        return suggestions
    
    def _save_analysis_results(self, results: Dict[str, Any]):
        """Salva resultados da análise no banco"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now()

                for repo_id, data in results.items():
                    for suggestion in data.get('suggestions', []):
                        cursor.execute("""
                            INSERT INTO user_suggestions
                            (type, priority, title, description, action, impact, category,
                             repository_id, created_at, metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            suggestion['type'],
                            suggestion['priority'],
                            suggestion['title'],
                            suggestion['description'],
                            suggestion['action'],
                            suggestion['impact'],
                            suggestion['category'],
                            repo_id,
                            now,
                            json.dumps(suggestion)
                        ))

                    metrics = data.get('metrics', {})
                    for metric_name, metric_value in metrics.items():
                        if isinstance(metric_value, (int, float)) and metric_name != 'error':
                            cursor.execute("""
                                INSERT INTO performance_metrics
                                (repository_id, metric_name, metric_value, measurement_date, metadata)
                                VALUES (%s, %s, %s, %s, %s)
                            """, (
                                repo_id,
                                metric_name,
                                metric_value,
                                now,
                                json.dumps({"analysis_session": now.isoformat()})
                            ))

                conn.commit()
                logger.info("💾 Resultados de análise salvos")

        except Exception as e:
            logger.error(f"Erro ao salvar análise: {e}")
    
    def get_active_suggestions(self) -> List[Dict[str, Any]]:
        """Obtém sugestões ativas para exibir ao usuário"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT s.*, r.name AS repository_name
                    FROM user_suggestions s
                    LEFT JOIN repositories r ON s.repository_id = r.id
                    WHERE s.dismissed_at IS NULL AND s.applied_at IS NULL
                    ORDER BY
                        CASE s.priority
                            WHEN 'high' THEN 1
                            WHEN 'medium' THEN 2
                            ELSE 3
                        END,
                        s.created_at DESC
                    LIMIT 20
                """)
                cols = [d[0] for d in cursor.description] if cursor.description else []
                return [dict(zip(cols, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Erro ao obter sugestões: {e}")
            return []
    
    def dismiss_suggestion(self, suggestion_id: int) -> bool:
        """Marca sugestão como dispensada"""
        try:
            with _get_core().get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE user_suggestions
                    SET dismissed_at = NOW()
                    WHERE id = %s
                """, (suggestion_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Erro ao dispensar sugestão {suggestion_id}: {e}")
            return False


# Instância global
analytics = BackupAnalytics()

logger.info("📊 BackupAnalytics inicializado")

