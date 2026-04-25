#!/usr/bin/env python3
"""
Real-Time Backup Monitor
Monitora execução de backups em tempo real e grava estatísticas
"""

import logging
import threading
import time
from datetime import datetime
from typing import Dict, Optional, Callable
from dataclasses import dataclass, asdict

logger = logging.getLogger("BackupMonitor")

@dataclass
class BackupProgress:
    """Estado do backup em execução"""
    task_id: int
    execution_id: int
    task_name: str
    repository_name: str
    status: str  # 'preparing', 'running', 'completed', 'failed'
    started_at: str
    completed_at: Optional[str] = None
    
    # Progresso
    current_file: Optional[str] = None
    files_processed: int = 0
    files_total: int = 0
    bytes_processed: int = 0
    bytes_total: int = 0
    
    # Estatísticas
    files_new: int = 0
    files_changed: int = 0
    files_unmodified: int = 0
    bytes_added: int = 0
    
    # Resultado
    snapshot_id: Optional[str] = None
    error_message: Optional[str] = None
    
    def to_dict(self):
        return asdict(self)
    
    @property
    def duration_seconds(self) -> float:
        if not self.started_at:
            return 0
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.completed_at) if self.completed_at else datetime.now()
        return (end - start).total_seconds()
    
    @property
    def progress_percent(self) -> float:
        if self.files_total == 0:
            return 0
        return min(100, (self.files_processed / self.files_total) * 100)


class RealTimeBackupMonitor:
    """
    Monitor de backups em tempo real
    Rastreia progresso e grava no banco
    """
    
    def __init__(self, core):
        self.core = core
        self.active_backups: Dict[int, BackupProgress] = {}
        self.lock = threading.Lock()
        self._callbacks: Dict[str, Callable] = {}
    
    def start_backup(
        self,
        task_id: int,
        execution_id: int,
        task_name: str,
        repository_name: str
    ) -> BackupProgress:
        """Inicia rastreamento de um backup"""
        
        with self.lock:
            progress = BackupProgress(
                task_id=task_id,
                execution_id=execution_id,
                task_name=task_name,
                repository_name=repository_name,
                status='preparing',
                started_at=datetime.now().isoformat()
            )
            
            self.active_backups[task_id] = progress
            
            # Gravar no banco
            self._save_to_database(progress)
            
            logger.info(f"🔄 Backup iniciado: {task_name} (Task {task_id})")
            self._trigger_callback('on_start', progress)
            
            return progress
    
    def update_progress(
        self,
        task_id: int,
        **kwargs
    ):
        """Atualiza progresso do backup"""
        
        with self.lock:
            if task_id not in self.active_backups:
                logger.warning(f"Tentativa de atualizar backup inexistente: {task_id}")
                return
            
            progress = self.active_backups[task_id]
            
            # Atualizar campos
            for key, value in kwargs.items():
                if hasattr(progress, key):
                    setattr(progress, key, value)
            
            # Atualizar status
            if progress.status == 'preparing' and progress.files_processed > 0:
                progress.status = 'running'
            
            # Gravar no banco
            self._save_to_database(progress)
            
            logger.debug(f"📊 Progresso {task_id}: {progress.progress_percent:.1f}% ({progress.files_processed}/{progress.files_total})")
            self._trigger_callback('on_progress', progress)
    
    def complete_backup(
        self,
        task_id: int,
        snapshot_id: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """Marca backup como concluído"""
        
        with self.lock:
            if task_id not in self.active_backups:
                logger.warning(f"Tentativa de concluir backup inexistente: {task_id}")
                return
            
            progress = self.active_backups[task_id]
            progress.completed_at = datetime.now().isoformat()
            progress.snapshot_id = snapshot_id
            progress.error_message = error_message
            progress.status = 'completed' if not error_message else 'failed'
            
            # Gravar no banco
            self._save_to_database(progress)
            self._finalize_in_database(progress)
            
            duration = progress.duration_seconds
            if progress.status == 'completed':
                logger.info(f"✅ Backup concluído: {progress.task_name} em {duration:.1f}s")
            else:
                logger.error(f"❌ Backup falhou: {progress.task_name} - {error_message}")
            
            self._trigger_callback('on_complete', progress)
            
            # Remover dos ativos
            del self.active_backups[task_id]
    
    def get_progress(self, task_id: int) -> Optional[BackupProgress]:
        """Obtém progresso atual de um backup"""
        with self.lock:
            return self.active_backups.get(task_id)
    
    def get_all_active(self) -> Dict[int, BackupProgress]:
        """Retorna todos os backups ativos"""
        with self.lock:
            return self.active_backups.copy()
    
    def register_callback(self, event: str, callback: Callable):
        """
        Registra callback para eventos
        Eventos: 'on_start', 'on_progress', 'on_complete'
        """
        self._callbacks[event] = callback
    
    def _trigger_callback(self, event: str, progress: BackupProgress):
        """Dispara callback se registrado"""
        if event in self._callbacks:
            try:
                self._callbacks[event](progress)
            except Exception as e:
                logger.error(f"Erro em callback {event}: {e}")
    
    def _save_to_database(self, progress: BackupProgress):
        """Grava progresso no banco com retentativas"""
        last_error = None
        for i in range(5):
            try:
                with self.core.get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE task_executions SET
                            status = %s,
                            files_processed = %s,
                            bytes_processed = %s,
                            current_file = %s,
                            progress = %s
                        WHERE id = %s
                    """, (
                        progress.status,
                        progress.files_processed,
                        progress.bytes_processed,
                        progress.current_file,
                        int(progress.progress_percent),
                        progress.execution_id
                    ))
                    conn.commit()
                return
            except Exception as e:
                last_error = e
                logger.error(f"Erro ao gravar progresso no banco: {e}")
                time.sleep(0.2 * (i + 1))
        
        if last_error:
            logger.error(f"Falha ao gravar progresso após retentativas: {last_error}")

    def _finalize_in_database(self, progress: BackupProgress):
        """Grava estatísticas finais no banco com retentativas"""
        last_error = None
        for i in range(5):
            try:
                with self.core.get_db_connection() as conn:
                    cur = conn.cursor()
                    duration = progress.duration_seconds

                    cur.execute("""
                        UPDATE task_executions
                        SET
                            duration_seconds = %s,
                            files_processed = %s,
                            bytes_processed = %s,
                            status = %s,
                            completed_at = %s,
                            error_message = %s,
                            snapshot_id = %s,
                            progress = %s
                        WHERE id = %s
                    """, (
                        duration,
                        progress.files_processed,
                        progress.bytes_processed,
                        progress.status,
                        progress.completed_at,
                        progress.error_message,
                        progress.snapshot_id,
                        int(progress.progress_percent),
                        progress.execution_id
                    ))

                    final_task_status = 'idle'
                    cur.execute("""
                        UPDATE tasks
                        SET
                            status = %s,
                            last_status = %s,
                            last_run = %s
                        WHERE id = %s
                    """, (
                        final_task_status,
                        progress.status,
                        progress.completed_at,
                        progress.task_id
                    ))

                    conn.commit()
                logger.info(f"✅ Estatísticas finais gravadas para execução {progress.execution_id}")
                return
            except Exception as e:
                last_error = e
                logger.error(f"Erro ao finalizar no banco: {e}")
                time.sleep(0.3 * (i + 1))
        
        if last_error:
            logger.error(f"Falha ao finalizar estatísticas após retentativas: {last_error}")
