#!/usr/bin/env python3
"""
[SYNC] GBOC Agent - Sincronizador (CORRIGIDO)
"""
import threading
import time
import logging
import sqlite3
import os
from datetime import datetime

logger = logging.getLogger(__name__)

class BackupSynchronizer:
    def __init__(self, db_path, history_importer):
        self.db_path = db_path
        self.importer = history_importer
        self.running = False
        self.thread = None
        self.sync_interval = 300 
        self.last_sync = {}
    
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def is_alive(self) -> bool:
        """
        Compatibilidade com SharedCore.shutdown().
        Retorna True se a thread do sincronizador existe e está rodando.
        """
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        logger.info("[SYNC] Sincronizador iniciado")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)
    
    def _sync_loop(self):
        while self.running:
            try:
                conn = self._get_connection()
                try:
                    cursor = conn.execute("SELECT id, name FROM repositories WHERE enabled = 1")
                    repos = cursor.fetchall()

                    for repo in repos:
                        repo_id = repo['id']
                        if self.running and (datetime.now() - self.last_sync.get(repo_id, datetime.min)).total_seconds() > self.sync_interval:
                            logger.info(f"[SYNC] Sincronizando repositório: {repo['name']}")
                            try:
                                self.importer.import_all_history() # Simplificado para chamar o importador geral
                            except Exception as e:
                                logger.error(f"  [ERROR] Erro em {repo['name']}: {e}")
                            finally:
                                self.last_sync[repo_id] = datetime.now()
                finally:
                    if conn: conn.close()

                time.sleep(self.sync_interval / 10) # Verifica a cada 1/10 do intervalo
            except Exception as e:
                logger.error(f"[ERROR] Erro geral no loop de sincronização: {e}")
                time.sleep(60) # Espera 1 minuto em caso de erro grave

    def force_sync(self, repository_id=None):
        return {"status": "info", "message": "Agendado"}