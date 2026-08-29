#!/usr/bin/env python3
"""
🔄 GBOC Agent 13.2.0 - Task Scheduler
Agendador de tarefas para execução automática
"""

import logging
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def _match_cron_field(field: str, value: int) -> bool:
    """Verifica se um valor corresponde a um campo cron (ex: *, */5, 1,3,5, 1-5)"""
    if field == '*':
        return True
    if field.startswith('*/'):
        step = int(field[2:])
        return value % step == 0
    parts = field.split(',')
    for part in parts:
        if '-' in part:
            lo, hi = part.split('-', 1)
            if int(lo) <= value <= int(hi):
                return True
        elif int(part) == value:
            return True
    return False


def cron_matches_now(cron_expr: str, now: datetime = None) -> bool:
    """Verifica se uma expressão cron (5 campos: min hour dom mon dow) corresponde ao momento atual"""
    if not cron_expr or not cron_expr.strip():
        return False
    now = now or datetime.now()
    parts = cron_expr.strip().split()
    if len(parts) < 5:
        return False
    try:
        return (
            _match_cron_field(parts[0], now.minute) and
            _match_cron_field(parts[1], now.hour) and
            _match_cron_field(parts[2], now.day) and
            _match_cron_field(parts[3], now.month) and
            _match_cron_field(parts[4], now.weekday())  # 0=Monday
        )
    except (ValueError, IndexError):
        return False


class Scheduler:
    """Agendador de tarefas do sistema GBOC"""

    def __init__(self, shared_core):
        self.shared_core = shared_core
        self.running = False
        self.thread = None
        self.logger = logging.getLogger(__name__)
        self._last_check_minute = -1
        self._schedule_schema_ok: Optional[bool] = None

    def start(self):
        """Inicia o agendador"""
        if self.running:
            self.logger.warning("[WARNING] Scheduler já está em execução")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.logger.info("[OK] Scheduler iniciado")

    def stop(self):
        """Para o agendador"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.logger.info("[OK] Scheduler parado")

    def _run_loop(self):
        """Loop principal do agendador — verifica a cada 15s, executa no máximo 1x por minuto"""
        while self.running:
            try:
                now = datetime.now()
                current_minute = now.hour * 60 + now.minute
                if current_minute != self._last_check_minute:
                    self._last_check_minute = current_minute
                    self._check_scheduled_tasks(now)
                time.sleep(15)
            except Exception as e:
                self.logger.error(f"[ERROR] Erro no loop do scheduler: {e}")
                time.sleep(60)

    def _has_schedule_columns(self, cursor) -> bool:
        """Verifica se a tabela tasks possui colunas de agendamento."""
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'tasks'
              AND column_name IN ('schedule_cron', 'schedule_enabled', 'enabled')
        """)
        cols = {row[0] for row in cursor.fetchall()}
        return {'schedule_cron', 'schedule_enabled', 'enabled'}.issubset(cols)

    def _check_scheduled_tasks(self, now: datetime = None):
        """Verifica e executa tarefas agendadas cujo cron corresponde ao momento atual"""
        if not self.shared_core:
            return
        try:
            now = now or datetime.now()
            with self.shared_core.get_db_connection() as conn:
                cursor = conn.cursor()

                if self._schedule_schema_ok is not True:
                    self._schedule_schema_ok = self._has_schedule_columns(cursor)
                    if not self._schedule_schema_ok:
                        self.logger.warning("[SCHEDULER] Colunas de agendamento ausentes em 'tasks'. Aguardando migração de schema.")
                        return

                cursor.execute("""
                    SELECT id, name, schedule_cron
                    FROM tasks
                    WHERE enabled = TRUE
                      AND schedule_enabled = TRUE
                      AND schedule_cron IS NOT NULL
                      AND status != 'running'
                """)
                tasks = cursor.fetchall()

            if not tasks:
                return

            task_manager = getattr(self.shared_core, 'task_manager', None)
            if not task_manager:
                return

            for row in tasks:
                task_id, task_name, cron_expr = row[0], row[1], row[2]
                try:
                    if cron_matches_now(cron_expr, now):
                        self.logger.info(f"[SCHEDULER] Disparando tarefa agendada: {task_name} (id={task_id}, cron={cron_expr})")
                        result = task_manager.trigger_task(task_id)
                        if result.get('status') == 'success':
                            self.logger.info(f"[SCHEDULER] Tarefa {task_name} iniciada com sucesso (exec_id={result.get('execution_id')})")
                        else:
                            err = result.get('message') or result.get('error') or 'erro desconhecido'
                            self.logger.warning(f"[SCHEDULER] Falha ao iniciar {task_name}: {err}")
                except Exception as e:
                    self.logger.error(f"[SCHEDULER] Erro ao avaliar tarefa {task_name}: {e}")

        except Exception as e:
            self.logger.error(f"[ERROR] Erro ao verificar tarefas agendadas: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Retorna status do scheduler"""
        return {
            "running": self.running,
            "last_check_minute": self._last_check_minute,
            "has_shared_core": self.shared_core is not None
        }

