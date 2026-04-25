#!/usr/bin/env python3
"""
🎛️ GBOC Agent - Controlador de Backups
Sistema de controle de velocidade, pausa e retomada de backups
"""

import logging
import threading
import time
from typing import Dict, Any, Optional
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class BackupController:
    """
    Controla velocidade, pausa e retomada de backups
    """
    
    def __init__(self, core):
        self.core = core
        self._paused_tasks = set()  # Set de task_ids pausados
        self._task_speeds = {}  # Dict de task_id -> velocidade (MB/s)
        self._task_threads = {}  # Dict de task_id -> thread
        self._lock = threading.Lock()
        self._ensure_settings_table()
        self._load_settings()
    
    def _ensure_settings_table(self):
        """Garante que tabela de configurações existe"""
        try:
            with self.core.get_db_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS backup_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao criar tabela de configurações: {e}")
    
    def _load_settings(self):
        """Carrega configurações do banco"""
        try:
            cursor = self.core.get_db_connection().cursor().execute("SELECT key, value FROM backup_settings")
            for row in cursor.fetchall():
                key, value = row
                if key == "global_pause":
                    if value.lower() == "true":
                        self._global_paused = True
                elif key.startswith("task_"):
                    task_id = int(key.split("_")[1])
                    if key.endswith("_speed"):
                        self._task_speeds[task_id] = float(value)
                    elif key.endswith("_paused"):
                        if value.lower() == "true":
                            self._paused_tasks.add(task_id)
        except Exception as e:
            logger.warning(f"Erro ao carregar configurações: {e}")
            self._global_paused = False
    
    def is_paused(self, task_id: Optional[int] = None) -> bool:
        """
        Verifica se backup está pausado
        
        Args:
            task_id: ID da tarefa (None = verifica pausa global)
        
        Returns:
            True se pausado
        """
        with self._lock:
            if task_id is None:
                return getattr(self, '_global_paused', False)
            return task_id in self._paused_tasks or getattr(self, '_global_paused', False)
    
    def pause_backup(self, task_id: Optional[int] = None, global_pause: bool = False):
        """
        Pausa backup
        
        Args:
            task_id: ID da tarefa (None = pausa global)
            global_pause: Se True, pausa todos os backups
        """
        try:
            with self._lock:
                if global_pause:
                    with self.core.get_db_connection() as conn:
                        self._global_paused = True
                        conn.execute("""
                            INSERT OR REPLACE INTO backup_settings (key, value, updated_at)
                            VALUES ('global_pause', 'true', ?)
                        """, (datetime.now().isoformat(),))
                        conn.commit()
                elif task_id:
                    with self.core.get_db_connection() as conn:
                        self._paused_tasks.add(task_id)
                        conn.execute("""
                            INSERT OR REPLACE INTO backup_settings (key, value, updated_at)
                            VALUES (?, 'true', ?)
                        """, (f"task_{task_id}_paused", datetime.now().isoformat()))
                        conn.commit()
            logger.info(f"⏸️ Backup pausado: {'global' if global_pause else f'task {task_id}'}")
        except Exception as e:
            logger.error(f"Erro ao pausar backup: {e}")
    
    def resume_backup(self, task_id: Optional[int] = None, global_resume: bool = False):
        """
        Retoma backup
        
        Args:
            task_id: ID da tarefa (None = retoma global)
            global_resume: Se True, retoma todos os backups
        """
        try:
            with self._lock:
                if global_resume:
                    with self.core.get_db_connection() as conn:
                        self._global_paused = False
                        conn.execute("""
                            INSERT OR REPLACE INTO backup_settings (key, value, updated_at)
                            VALUES ('global_pause', 'false', ?)
                        """, (datetime.now().isoformat(),))
                        conn.commit()
                elif task_id:
                    with self.core.get_db_connection() as conn:
                        self._paused_tasks.discard(task_id)
                        conn.execute("""
                            INSERT OR REPLACE INTO backup_settings (key, value, updated_at)
                            VALUES (?, 'false', ?)
                        """, (f"task_{task_id}_paused", datetime.now().isoformat()))
                        conn.commit()
            logger.info(f"▶️ Backup retomado: {'global' if global_resume else f'task {task_id}'}")
        except Exception as e:
            logger.error(f"Erro ao retomar backup: {e}")
    
    def set_speed_limit(self, task_id: int, speed_mbps: float):
        """
        Define limite de velocidade para uma tarefa
        
        Args:
            task_id: ID da tarefa
            speed_mbps: Velocidade máxima em MB/s (0 = sem limite)
        """
        try:
            with self._lock:
                if speed_mbps > 0:
                    self._task_speeds[task_id] = speed_mbps
                else:
                    self._task_speeds.pop(task_id, None)
                
                with self.core.get_db_connection() as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO backup_settings (key, value, updated_at)
                        VALUES (?, ?, ?)
                    """, (f"task_{task_id}_speed", str(speed_mbps), datetime.now().isoformat()))
                    conn.commit()
            logger.info(f"⚡ Velocidade definida para task {task_id}: {speed_mbps} MB/s")
        except Exception as e:
            logger.error(f"Erro ao definir velocidade: {e}")
    
    def get_speed_limit(self, task_id: int) -> Optional[float]:
        """Retorna limite de velocidade de uma tarefa"""
        with self._lock:
            return self._task_speeds.get(task_id)
    
    def wait_if_paused(self, task_id: int):
        """
        Aguarda se backup está pausado (usar em loops de backup)
        
        Args:
            task_id: ID da tarefa
        """
        while self.is_paused(task_id):
            time.sleep(1)  # Aguarda 1 segundo e verifica novamente
    
    def throttle_speed(self, task_id: int, bytes_processed: int, duration_seconds: float):
        """
        Controla velocidade do backup (throttling)
        
        Args:
            task_id: ID da tarefa
            bytes_processed: Bytes já processados
            duration_seconds: Duração da operação até agora
        
        Returns:
            Tempo adicional a aguardar (segundos)
        """
        speed_limit = self.get_speed_limit(task_id)
        if not speed_limit or speed_limit <= 0:
            return 0
        
        # Calcular velocidade atual
        if duration_seconds > 0:
            current_speed_mbps = (bytes_processed / (1024 * 1024)) / duration_seconds
            
            # Se velocidade atual > limite, calcular tempo de espera
            if current_speed_mbps > speed_limit:
                # Calcular quanto tempo deveria ter levado
                expected_duration = (bytes_processed / (1024 * 1024)) / speed_limit
                wait_time = expected_duration - duration_seconds
                return max(0, wait_time)
        
        return 0
    
    def get_status(self) -> Dict[str, Any]:
        """Retorna status do controlador"""
        with self._lock:
            return {
                "global_paused": getattr(self, '_global_paused', False),
                "paused_tasks": list(self._paused_tasks),
                "speed_limited_tasks": {
                    task_id: speed for task_id, speed in self._task_speeds.items()
                }
            }
