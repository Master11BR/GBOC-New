#!/usr/bin/env python3
"""
🔍 GBOC Agent - Sistema de Captura de Erros Melhorado
Captura erros com contexto completo e integra com análise automática
"""

import logging
import traceback
import sys
from typing import Dict, Any, Optional
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class ErrorCapture:
    """
    Sistema de captura de erros com contexto completo
    """
    
    def __init__(self, db_connection, error_analyzer=None):
        """
        Args:
            db_connection: Conexão com banco de dados
            error_analyzer: Instância do ErrorAnalyzer (opcional)
        """
        self.db = db_connection
        self.error_analyzer = error_analyzer
        self._ensure_error_log_table()
    
    def _ensure_error_log_table(self):
        """Garante que tabela error_log existe"""
        try:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS error_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    task_id INTEGER,
                    repository_id INTEGER,
                    execution_id INTEGER,
                    error_type TEXT,
                    severity TEXT,
                    error_message TEXT NOT NULL,
                    stack_trace TEXT,
                    context TEXT,
                    diagnosis TEXT,
                    auto_fix_available BOOLEAN DEFAULT 0,
                    auto_fix_action TEXT,
                    user_message TEXT,
                    solution TEXT,
                    resolved BOOLEAN DEFAULT 0,
                    resolved_at TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (task_id) REFERENCES tasks(id),
                    FOREIGN KEY (repository_id) REFERENCES repositories(id),
                    FOREIGN KEY (execution_id) REFERENCES task_executions(id)
                )
            """)
            
            # Índices para performance
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_errors_task ON error_log(task_id)")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_errors_repo ON error_log(repository_id)")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_errors_type ON error_log(error_type)")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_errors_severity ON error_log(severity)")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_errors_timestamp ON error_log(timestamp)")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_errors_resolved ON error_log(resolved)")
            
            self.db.commit()
        except Exception as e:
            logger.error(f"Erro ao criar tabela error_log: {e}")
    
    def capture_error(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        task_id: Optional[int] = None,
        repository_id: Optional[int] = None,
        execution_id: Optional[int] = None,
        engine: Optional[str] = None
    ) -> int:
        """
        Captura um erro com contexto completo e análise automática
        
        Args:
            error: Exceção capturada
            context: Contexto adicional (dict)
            task_id: ID da tarefa (se aplicável)
            repository_id: ID do repositório (se aplicável)
            execution_id: ID da execução (se aplicável)
            engine: Engine de backup usado (restic, kopia, etc)
        
        Returns:
            ID do erro registrado
        """
        try:
            # Extrair informações do erro
            error_type = type(error).__name__
            error_message = str(error)
            stack_trace = self._format_stack_trace(error)
            
            # Contexto completo
            full_context = {
                "error_type": error_type,
                "error_message": error_message,
                "context": context or {},
                "task_id": task_id,
                "repository_id": repository_id,
                "execution_id": execution_id,
                "engine": engine,
                "python_version": sys.version,
                "platform": sys.platform
            }
            
            # Análise automática se ErrorAnalyzer disponível
            diagnosis = None
            user_message = None
            solution = None
            auto_fix_available = False
            auto_fix_action = None
            severity = "medium"
            
            if self.error_analyzer:
                try:
                    # Combinar mensagem de erro com stack trace para análise
                    analysis_text = f"{error_message}\n{stack_trace[:500]}"
                    diagnosis_result = self.error_analyzer.analyze_error(analysis_text, engine or "all")
                    
                    diagnosis = json.dumps(diagnosis_result, ensure_ascii=False)
                    user_message = diagnosis_result.get('user_message', error_message)
                    solution = diagnosis_result.get('solution', 'Verifique os logs para mais detalhes')
                    auto_fix_available = diagnosis_result.get('auto_fix_available', False)
                    auto_fix_action = diagnosis_result.get('auto_fix_action')
                    severity = diagnosis_result.get('severity', 'medium')
                except Exception as e:
                    logger.warning(f"Erro ao analisar erro automaticamente: {e}")
            
            # Inserir no banco
            timestamp = datetime.now().isoformat()
            cursor = self.db.cursor()
            cursor.execute("""
                INSERT INTO error_log (
                    timestamp, task_id, repository_id, execution_id,
                    error_type, severity, error_message, stack_trace,
                    context, diagnosis, auto_fix_available, auto_fix_action,
                    user_message, solution
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                timestamp, task_id, repository_id, execution_id,
                error_type, severity, error_message, stack_trace,
                json.dumps(full_context, ensure_ascii=False),
                diagnosis, auto_fix_available, auto_fix_action,
                user_message, solution
            ))
            
            cursor.execute("SELECT LASTVAL()")
            error_id = cursor.fetchone()[0]
            self.db.commit()
            
            # Log também no sistema de logging padrão
            logger.error(
                f"❌ Erro capturado [ID: {error_id}] | "
                f"Tipo: {error_type} | "
                f"Severidade: {severity} | "
                f"Mensagem: {error_message[:100]}"
            )
            
            return error_id
            
        except Exception as e:
            # Fallback: log no sistema padrão se falhar
            logger.error(f"Erro ao capturar erro no banco: {e}")
            logger.exception(error)
            return -1
    
    def capture_error_from_string(
        self,
        error_message: str,
        context: Optional[Dict[str, Any]] = None,
        task_id: Optional[int] = None,
        repository_id: Optional[int] = None,
        execution_id: Optional[int] = None,
        engine: Optional[str] = None,
        severity: str = "medium"
    ) -> int:
        """
        Captura erro a partir de string (útil para erros de subprocess)
        """
        try:
            # Análise automática
            diagnosis = None
            user_message = None
            solution = None
            auto_fix_available = False
            auto_fix_action = None
            
            if self.error_analyzer:
                try:
                    diagnosis_result = self.error_analyzer.analyze_error(error_message, engine or "all")
                    diagnosis = json.dumps(diagnosis_result, ensure_ascii=False)
                    user_message = diagnosis_result.get('user_message', error_message)
                    solution = diagnosis_result.get('solution', 'Verifique os logs para mais detalhes')
                    auto_fix_available = diagnosis_result.get('auto_fix_available', False)
                    auto_fix_action = diagnosis_result.get('auto_fix_action')
                    severity = diagnosis_result.get('severity', severity)
                except Exception as e:
                    logger.warning(f"Erro ao analisar erro: {e}")
            
            # Contexto completo
            full_context = {
                "error_message": error_message,
                "context": context or {},
                "task_id": task_id,
                "repository_id": repository_id,
                "execution_id": execution_id,
                "engine": engine
            }
            
            timestamp = datetime.now().isoformat()
            cursor = self.db.cursor()
            cursor.execute("""
                INSERT INTO error_log (
                    timestamp, task_id, repository_id, execution_id,
                    error_type, severity, error_message, stack_trace,
                    context, diagnosis, auto_fix_available, auto_fix_action,
                    user_message, solution
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                timestamp, task_id, repository_id, execution_id,
                "StringError", severity, error_message, None,
                json.dumps(full_context, ensure_ascii=False),
                diagnosis, auto_fix_available, auto_fix_action,
                user_message, solution
            ))
            
            cursor.execute("SELECT LASTVAL()")
            error_id = cursor.fetchone()[0]
            self.db.commit()
            
            logger.error(f"❌ Erro capturado [ID: {error_id}] | {error_message[:100]}")
            
            return error_id
            
        except Exception as e:
            logger.error(f"Erro ao capturar erro: {e}")
            return -1
    
    def _format_stack_trace(self, error: Exception) -> str:
        """Formata stack trace do erro"""
        try:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            if exc_traceback:
                return ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            return str(error)
        except:
            return str(error)
    
    def mark_resolved(self, error_id: int):
        """Marca erro como resolvido"""
        try:
            self.db.execute("""
                UPDATE error_log 
                SET resolved = 1, resolved_at = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), error_id))
            self.db.commit()
        except Exception as e:
            logger.error(f"Erro ao marcar erro como resolvido: {e}")
    
    def get_recent_errors(
        self,
        limit: int = 50,
        severity: Optional[str] = None,
        resolved: Optional[bool] = None,
        task_id: Optional[int] = None
    ) -> list:
        """Busca erros recentes"""
        try:
            query = "SELECT * FROM error_log WHERE 1=1"
            params = []
            
            if severity:
                query += " AND severity = ?"
                params.append(severity)
            
            if resolved is not None:
                query += " AND resolved = ?"
                params.append(1 if resolved else 0)
            
            if task_id:
                query += " AND task_id = ?"
                params.append(task_id)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor = self.db.execute(query, params)
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Erro ao buscar erros: {e}")
            return []


# Decorator para captura automática de erros
def capture_errors(
    error_capture: ErrorCapture,
    task_id: Optional[int] = None,
    repository_id: Optional[int] = None,
    engine: Optional[str] = None
):
    """
    Decorator para capturar erros automaticamente em funções
    
    Usage:
        @capture_errors(error_capture, task_id=1, engine='restic')
        def my_backup_function():
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Tentar extrair contexto dos argumentos
                context = {
                    "function": func.__name__,
                    "args": str(args)[:200],
                    "kwargs": str(kwargs)[:200]
                }
                
                error_capture.capture_error(
                    e,
                    context=context,
                    task_id=task_id,
                    repository_id=repository_id,
                    engine=engine
                )
                raise
        return wrapper
    return decorator
