#!/usr/bin/env python3
"""
GBOC Agent 13.2.0 - Task Manager
[OK] Usa motor_password para repositórios locais e cloud_password para nuvem
"""

import subprocess
import os
import shutil
import platform
from pathlib import Path
import threading
import logging
import json
import time
from queue import Queue, Empty
from datetime import datetime
from typing import Dict, Any, Optional, List
import psycopg2.extras
import re
from logging.handlers import RotatingFileHandler

from engines.engine_paths import get_engine_path_or_raise, get_engine_path
from engines.realtime_backup_monitor import RealTimeBackupMonitor
from engines.auto_verify_engine import AutoVerifyEngine
from native_engine.engine import GBOCNativeEngine

logger = logging.getLogger(__name__)


class TaskManager:
    """Gerenciador de tarefas de backup"""

    def __init__(self, core):
        """
        Inicializa o Task Manager

        Args:
            core: SharedCore instance
        """
        self.core = core

        # Fila de execução
        self._task_queue = Queue()
        self._worker_thread = None
        self._running = False
        self._current_process = None
        self._current_execution_id = None
        self._max_concurrent_tasks = 1  # Limitar a uma tarefa por enquanto
        self._running_tasks = []  # Lista de tarefas em execução

        # Inicializar Monitor com SharedCore
        self.monitor = RealTimeBackupMonitor(self.core)
        self.auto_verify_engine = AutoVerifyEngine(self.core)
        # Alias de logger para compatibilidade com métodos que usam self.logger
        self.logger = logger

        # Logger dedicado para erros de tarefas
        self.task_error_logger = logging.getLogger("task_errors")
        if not self.task_error_logger.handlers:
            logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
            os.makedirs(logs_dir, exist_ok=True)
            err_handler = RotatingFileHandler(
                os.path.join(logs_dir, "task_errors.log"),
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding='utf-8'
            )
            err_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            self.task_error_logger.addHandler(err_handler)
            self.task_error_logger.setLevel(logging.ERROR)
            self.task_error_logger.propagate = False

        self._cleanup_stale_tasks()
        logger.info("[OK] TaskManager inicializado")

    def _get_connection(self):
        """Obtém conexão com o banco via pool do core"""
        return self.core.get_db_connection()

    def _get_password(self, repo: Dict[str, Any]) -> Optional[str]:
        """
        Obtém a senha correta baseada no tipo de repositório:
        - LOCAL: motor_password
        - CLOUD: cloud_password
        """
        repo_type = (repo.get('repo_type') or repo.get('type') or 'local').lower()
        if repo_type == 'local':
            return repo.get('motor_password')
        return repo.get('cloud_password')

    def _resolve_region(self, data: Dict[str, Any]) -> str:
        """Resolve a região real: usa config, ou extrai do endpoint, ou default."""
        region = (data.get('region') or '').strip()
        if region:
            return region
        endpoint = (data.get('endpoint') or '').strip()
        if endpoint:
            parts = endpoint.replace('https://', '').replace('http://', '').split('.')
            if len(parts) >= 3 and parts[0] == 's3':
                return parts[1]
        return 'us-east-1'

    def _configure_restic_repository(self, env: Dict[str, str], task: Dict[str, Any]):
        """
        Configura as variáveis de ambiente para o repositório Restic
        baseado no tipo de repositório
        """
        repo_type = (task.get('repo_type') or task.get('type') or 'local').lower()
        repo_path = task.get('repo_path')

        if repo_type == 'local':
            env["RESTIC_REPOSITORY"] = str(repo_path or '')
        elif repo_type == 's3':
            env["RESTIC_REPOSITORY"] = f"s3:s3.amazonaws.com/{repo_path}"
            env["AWS_ACCESS_KEY_ID"] = str(task.get('aws_access_key') or '')
            env["AWS_SECRET_ACCESS_KEY"] = str(task.get('aws_secret_key') or '')
        elif repo_type == 'wasabi':
            # Wasabi usa S3 API mas com endpoint personalizado
            region = self._resolve_region(task)
            endpoint = task.get('endpoint') or f"s3.{region}.wasabisys.com"
            env["RESTIC_REPOSITORY"] = f"s3:{endpoint}/{repo_path}"
            env["AWS_ACCESS_KEY_ID"] = str(task.get('aws_access_key') or '')
            env["AWS_SECRET_ACCESS_KEY"] = str(task.get('aws_secret_key') or '')
            env["AWS_DEFAULT_REGION"] = region
        elif repo_type == 'b2':
            env["RESTIC_REPOSITORY"] = f"b2:{repo_path}"
            env["B2_ACCOUNT_ID"] = str(task.get('b2_account_id') or '')
            env["B2_ACCOUNT_KEY"] = str(task.get('b2_account_key') or '')

    def _build_duplicati_url(self, repo: Dict, password: str) -> str:
        """Constrói URL do Duplicati baseada no tipo de repositório (sem credenciais na URL)"""
        repo_type = (repo.get('repo_type') or repo.get('type') or 'local')
        repo_path = repo.get('repo_path', '')
        prefix = repo.get('prefix', '')

        if repo_type == 'local':
            return f"file://{repo_path}"
        elif repo_type == 'b2':
            bucket = repo_path
            url_path = f"{bucket}/{prefix}" if prefix else bucket
            return f"b2://{url_path}"
        elif repo_type == 's3':
            bucket = repo_path
            url_path = f"{bucket}/{prefix}" if prefix else bucket
            return f"s3://{url_path}"
        elif repo_type == 'wasabi':
            bucket = repo_path
            url_path = f"{bucket}/{prefix}" if prefix else bucket
            return f"s3://{url_path}"
        elif repo_type == 'azure':
            container = repo_path
            url_path = f"{container}/{prefix}" if prefix else container
            return f"azure://{url_path}"
        else:
            raise ValueError(f"Tipo de repositório Duplicati não suportado: {repo_type}")

    def _build_duplicati_auth_args(self, repo: Dict) -> list:
        """Constrói argumentos de autenticação para Duplicati CLI"""
        repo_type = (repo.get('repo_type') or repo.get('type') or 'local')
        args = []

        if repo_type in ('s3', 'wasabi'):
            access_key = repo.get('aws_access_key', '')
            secret_key = repo.get('aws_secret_key', '')
            endpoint = repo.get('endpoint', '')
            region = repo.get('region', '')

            if access_key:
                args.append(f"--aws-access-key-id={access_key}")
            if secret_key:
                args.append(f"--aws-secret-access-key={secret_key}")
            if endpoint:
                args.append(f"--s3-server-name={endpoint}")
            elif repo_type == 'wasabi' and region:
                args.append(f"--s3-server-name=s3.{region}.wasabisys.com")
            elif repo_type == 's3' and region:
                args.append(f"--s3-server-name=s3.{region}.amazonaws.com")

        elif repo_type == 'b2':
            account_id = repo.get('b2_account_id', '')
            account_key = repo.get('b2_account_key', '')
            if account_id:
                args.append(f"--b2-accountid={account_id}")
            if account_key:
                args.append(f"--b2-applicationkey={account_key}")

        elif repo_type == 'azure':
            account_name = repo.get('azure_account_name', '')
            account_key = repo.get('azure_account_key', '')
            if account_name:
                args.append(f"--azure-account-name={account_name}")
            if account_key:
                args.append(f"--azure-accesskey={account_key}")

        return args

    def _mark_repository_initialized(self, repository_id: int):
        """Marca o repositório como inicializado no banco de dados"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE repositories SET initialized = true, updated_at = %s WHERE id = %s",
                    (datetime.now().isoformat(), repository_id)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Erro ao atualizar status do repositório {repository_id}: {e}")

    def start(self):
        """Inicia o worker thread"""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("[OK] TaskManager worker iniciado")

    def stop(self):
        """Para o worker thread"""
        self._running = False
        if self._current_process:
            try:
                self._current_process.terminate()
            except:
                pass

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        
        if hasattr(self, '_monitor_conn'):
            self._monitor_conn.close()
        logger.info("[OK] TaskManager parado")

    def _cleanup_stale_tasks(self):
        """Limpa tarefas que ficaram presas como 'running' após reinício"""
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                # Buscar execuções presas
                cur.execute("SELECT id, task_id FROM task_executions WHERE status = 'running'")
                stale_executions = cur.fetchall()

                if stale_executions:
                    logger.warning(f"🧹 Encontradas {len(stale_executions)} execuções estagnadas. Limpando...")

                    now = datetime.now().isoformat()
                    for exec_row in stale_executions:
                        exec_id = exec_row['id']
                        task_id = exec_row['task_id']

                        # Atualizar execução
                        cur.execute("""
                            UPDATE task_executions 
                            SET status = 'interrupted', 
                                error_message = 'Sistema reiniciado durante execução (Stale)', 
                                completed_at = %s 
                            WHERE id = %s
                        """, (now, exec_id))

                        # Atualizar tarefa
                        cur.execute("""
                            UPDATE tasks 
                            SET status = 'idle', 
                                last_status = 'interrupted',
                                last_run = %s 
                            WHERE id = %s AND status = 'running'
                        """, (now, task_id))

                    conn.commit()
                    logger.info("✅ Limpeza de execuções estagnadas concluída.")

                # Corrigir tarefas órfãs: tasks.status='running' sem execução ativa
                now = datetime.now().isoformat()
                cur.execute("""
                    UPDATE tasks 
                    SET status = 'idle', last_status = 'interrupted', last_run = %s
                    WHERE status = 'running' 
                    AND id NOT IN (
                        SELECT DISTINCT task_id FROM task_executions WHERE status = 'running'
                    )
                """, (now,))
                orphan_count = cur.rowcount
                if orphan_count > 0:
                    conn.commit()
                    logger.warning(f"🧹 Corrigidas {orphan_count} tarefas órfãs travadas em 'running'.")

        except Exception as e:
            logger.error(f"❌ Erro ao limpar tarefas estagnadas: {e}")

    def _build_task_diagnostic(self, engine: str, error_msg: str) -> str:
        msg = (error_msg or '').lower()
        if 'wrong password' in msg or 'no key found' in msg or 'incorrect password' in msg:
            return f"Falha de autenticação do repositório ({engine}). Verifique senha/chave usada na criação do repositório."
        if 'access denied' in msg or 'forbidden' in msg or 'signaturedoesnotmatch' in msg:
            return f"Falha de credenciais/permissão no storage ({engine}). Verifique access key/secret e permissões do bucket."
        if 'timeout' in msg or 'connection refused' in msg or 'no such host' in msg:
            return f"Falha de conectividade com destino ({engine}). Verifique rede, endpoint e DNS."
        if 'not found' in msg or 'repository does not exist' in msg:
            return f"Repositório não encontrado ({engine}). Confirme bucket/path/prefix."
        return f"Falha operacional no módulo de tarefas ({engine}). Revisar log detalhado da execução."

    def _register_task_error(self, task_id: int, execution_id: int, task_name: str, engine: str, error_msg: str):
        try:
            diagnostic = self._build_task_diagnostic(engine, error_msg)
            details = (
                f"task_id={task_id}\n"
                f"execution_id={execution_id}\n"
                f"task_name={task_name}\n"
                f"engine={engine}\n"
                f"error={error_msg}"
            )

            self.task_error_logger.error(
                f"task_id={task_id} execution_id={execution_id} task={task_name} engine={engine} error={error_msg} diagnostic={diagnostic}"
            )

            if hasattr(self.core, 'register_error_event'):
                self.core.register_error_event(
                    source='task_manager',
                    message=f"Falha na tarefa '{task_name}' (engine={engine})",
                    details=details,
                    module='engines.task_manager',
                    diagnostic=diagnostic,
                    severity='error'
                )
            else:
                self.core.log_system_event('ERROR', 'task_manager', f"Falha na tarefa '{task_name}'", details)
        except Exception as reg_err:
            logger.error(f"❌ Erro ao registrar falha da tarefa em alertas/logs: {reg_err}")

    def _strip_ansi(self, s: Optional[str]) -> str:
        """Remove códigos de escape ANSI de uma string."""
        if not s:
            return ""
        try:
            ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
            return ansi_escape.sub('', s)
        except Exception:
            return s

    def create_task(self, data: Dict) -> Dict:
        """Cria uma nova tarefa"""
        try:
            name = data.get('name', '').strip()
            if not name:
                raise ValueError("Nome da tarefa é obrigatório")

            repository_id = data.get('repository_id')
            if not repository_id:
                raise ValueError("Repositório é obrigatório")

            source_paths = data.get('source_paths', '')
            if not source_paths:
                raise ValueError("Caminhos de origem são obrigatórios")

            # Validar se os caminhos existem e são seguros
            try:
                paths = json.loads(source_paths) if isinstance(source_paths, str) else source_paths
                if isinstance(paths, list):
                    for path in paths:
                        # Validar segurança do caminho (prevenir path traversal)
                        normalized_path = os.path.normpath(path)
                        if '..' in normalized_path or not os.path.exists(normalized_path):
                            logger.warning(f"⚠️ Caminho de origem inválido ou não encontrado: {path}")
                            raise ValueError(f"Caminho inválido ou não encontrado: {path}")
                else:
                    raise ValueError("Caminhos de origem devem ser uma lista")
            except (json.JSONDecodeError, TypeError):
                raise ValueError("Formato inválido para caminhos de origem")

            # O motor da tarefa deve seguir o motor do repositório.
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT engine FROM repositories WHERE id = %s", (repository_id,))
                repo_row = cursor.fetchone()
                if not repo_row:
                    raise ValueError("Repositório não encontrado")
                engine = (repo_row[0] or 'restic').lower()

            task_type = data.get('type', 'backup')
            schedule_enabled = bool(data.get('schedule_enabled', False))
            schedule_cron = data.get('schedule_cron', '')
            pre_script = (data.get('pre_script') or '').strip()
            post_script = (data.get('post_script') or '').strip()

            # Retention policy
            retention_days = int(data.get('retention_days', 30))
            retention_weekly = int(data.get('retention_weekly', 4))
            retention_monthly = int(data.get('retention_monthly', 6))
            retention_yearly = int(data.get('retention_yearly', 1))

            # Auto-retry
            retry_enabled = bool(data.get('retry_enabled', False))
            retry_max_attempts = int(data.get('retry_max_attempts', 3))
            retry_delay_minutes = int(data.get('retry_delay_minutes', 5))

            now = datetime.now().isoformat()

            with self._get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS pre_script TEXT")
                    cursor.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS post_script TEXT")
                    conn.commit()
                except Exception:
                    conn.rollback()

                cursor.execute("""
                    INSERT INTO tasks (name, repository_id, source_paths, engine, type,
                                      schedule_enabled, schedule_cron, status, enabled, created_at, updated_at,
                                      retention_days, retention_weekly, retention_monthly, retention_yearly,
                                      retry_enabled, retry_max_attempts, retry_delay_minutes,
                                      pre_script, post_script)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'idle', true, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (name, repository_id, source_paths, engine, task_type,
                      schedule_enabled, schedule_cron, now, now,
                      retention_days, retention_weekly, retention_monthly, retention_yearly,
                      retry_enabled, retry_max_attempts, retry_delay_minutes,
                      pre_script, post_script))
                conn.commit()
                cursor.execute("SELECT LASTVAL()")
                task_id = cursor.fetchone()[0]

            logger.info(f"[OK] Tarefa criada: {name} (ID: {task_id})")
            return {"status": "success", "id": task_id, "message": f"Tarefa '{name}' criada"}

        except psycopg2.IntegrityError as e:
            logger.error(f"❌ Conflito ao criar tarefa: {e}")
            raise ValueError("Erro de integridade ao criar tarefa")
        except Exception as e:
            logger.error(f"❌ Erro ao criar tarefa: {e}")
            raise

    def update_task(self, task_id: int, data: Dict) -> Dict:
        """Atualiza uma tarefa com edição completa"""
        try:
            # Campos permitidos para edição completa
            allowed_fields = [
                'name', 'repository_id', 'source_paths', 'engine', 'type',
                'enabled', 'schedule_enabled', 'schedule_cron',
                'retention_days', 'retention_weekly', 'retention_monthly', 'retention_yearly',
                'retry_enabled', 'retry_max_attempts', 'retry_delay_minutes',
                'pre_script', 'post_script'
            ]

            updates = []
            values = []

            for field in allowed_fields:
                if field in data and data[field] is not None:
                    updates.append(f"{field} = %s")
                    if field in ['enabled', 'schedule_enabled', 'retry_enabled']:
                        values.append(bool(data[field]))
                    elif field in ['retention_days', 'retention_weekly', 'retention_monthly', 'retention_yearly',
                                   'retry_max_attempts', 'retry_delay_minutes', 'repository_id']:
                        values.append(int(data[field]))
                    else:
                        values.append(data[field])

            if not updates:
                return {"status": "noop", "message": "Nenhum campo para atualizar"}

            # Validações específicas para campos críticos
            if 'name' in data and data['name']:
                if not isinstance(data['name'], str) or not data['name'].strip():
                    raise ValueError("Nome da tarefa não pode ser vazio")

            if 'repository_id' in data and data['repository_id'] is not None:
                # Verificar se repositório existe
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM repositories WHERE id = %s", (data['repository_id'],))
                    repo = cursor.fetchone()
                    if not repo:
                        raise ValueError("Repositório não encontrado")

            if 'source_paths' in data and data['source_paths']:
                # Validar caminhos de origem: apenas path traversal, não existência
                try:
                    paths = json.loads(data['source_paths']) if isinstance(data['source_paths'], str) else data['source_paths']
                    if isinstance(paths, list):
                        for path in paths:
                            normalized_path = os.path.normpath(str(path))
                            if '..' in normalized_path:
                                raise ValueError(f"Caminho inválido (path traversal detectado): {path}")
                            if not os.path.exists(normalized_path):
                                logger.warning(f"⚠️ Caminho não encontrado (pode estar em rede/desmontado): {path}")
                    else:
                        raise ValueError("Caminhos de origem devem ser uma lista")
                except (json.JSONDecodeError, TypeError):
                    raise ValueError("Formato inválido para caminhos de origem")

            # O engine sempre acompanha o repositório selecionado.
            if 'repository_id' in data and data['repository_id'] is not None:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT engine FROM repositories WHERE id = %s", (data['repository_id'],))
                    repo_engine_row = cursor.fetchone()
                    if not repo_engine_row:
                        raise ValueError("Repositório não encontrado")
                    data['engine'] = (repo_engine_row[0] or 'restic').lower()
                    updates.append("engine = %s")
                    values.append(data['engine'])
            elif 'engine' in data:
                # Ignorar engine manual sem mudança de repositório para evitar divergência.
                data.pop('engine', None)

            updates.append("updated_at = %s")
            values.append(datetime.now().isoformat())
            values.append(task_id)

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"UPDATE tasks SET {', '.join(updates)} WHERE id = %s",
                    tuple(values)
                )
                conn.commit()

            logger.info(f"[OK] Tarefa {task_id} atualizada completamente")
            return {"status": "success", "message": "Tarefa atualizada completamente"}

        except Exception as e:
            logger.error(f"❌ Erro ao atualizar tarefa: {e}")
            raise

    def delete_task(self, task_id: int) -> Dict:
        """Deleta uma tarefa"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Verificar se existe
                cursor.execute("SELECT id FROM tasks WHERE id = %s", (task_id,))
                row = cursor.fetchone()
                if not row:
                    raise ValueError("Tarefa não encontrada")

                # Deletar execuções associadas
                cursor.execute("DELETE FROM task_executions WHERE task_id = %s", (task_id,))

                # Deletar tarefa
                cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
                conn.commit()

            logger.info(f"[OK] Tarefa {task_id} deletada")
            return {"status": "success", "message": "Tarefa deletada"}

        except Exception as e:
            logger.error(f"❌ Erro ao deletar tarefa: {e}")
            raise

    def queue_task(self, task_id: int, execution_id: int):
        """Adiciona tarefa à fila de execução"""
        self._task_queue.put((task_id, execution_id))
        logger.info(f"📋 Tarefa {task_id} adicionada à fila (exec: {execution_id})")

    def stop_task(self, execution_id: int) -> Dict:
        """Para uma tarefa em execução"""
        try:
            if self._current_execution_id == execution_id and self._current_process:
                self._current_process.terminate()

                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE task_executions
                        SET status = 'cancelled', completed_at = %s
                        WHERE id = %s
                    """, (datetime.now().isoformat(), execution_id))
                    conn.commit()

                return {"status": "success", "message": "Tarefa cancelada"}
            else:
                return {"status": "error", "message": "Tarefa não está em execução"}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def force_stop_task(self, execution_id: int) -> Dict:
        """Força a parada de uma tarefa (mata processo ou limpa banco se estiver travada)"""
        try:
            # 1. Tentar parar processo ativo se for o atual
            if self._current_execution_id == execution_id and self._current_process:
                try:
                    # Tentar terminar graciosamente primeiro
                    self._current_process.terminate()

                    # Aguardar até 10 segundos para terminar graciosamente
                    try:
                        self._current_process.wait(timeout=10)
                        logger.info(f"✅ Processo {execution_id} terminado graciosamente")
                    except subprocess.TimeoutExpired:
                        # Se não terminou, forçar kill
                        logger.warning(f"⚠️ Processo {execution_id} não respondeu, forçando kill")
                        self._current_process.kill()
                        self._current_process.wait()
                        logger.info(f"✅ Processo {execution_id} forçado a terminar")

                except Exception as e:
                    logger.error(f"❌ Erro ao terminar processo {execution_id}: {e}")
                    try:
                        # Última tentativa de kill se terminate falhou
                        self._current_process.kill()
                    except:
                        pass

                # Limpar estado interno
                if execution_id in self._running_tasks:
                    self._running_tasks.remove(execution_id)
                self._current_execution_id = None
                self._current_process = None

                # Atualizar banco
                with self._get_connection() as conn:
                    now = datetime.now().isoformat()
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE task_executions
                        SET status = 'cancelled', completed_at = %s,
                            error_message = 'Cancelado pelo usuário'
                        WHERE id = %s
                    """, (now, execution_id))
                    conn.commit()

                return {"status": "success", "message": "Tarefa cancelada com sucesso"}

            # 2. Se não é o processo atual, verificar se está travado no banco
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT status, task_id, started_at FROM task_executions
                    WHERE id = %s
                """, (execution_id,))
                row = cursor.fetchone()

                if not row:
                    return {"status": "error", "message": "Execução não encontrada"}

                status = row[0]

                if status in ['running', 'preparing', 'queued']:
                    now = datetime.now().isoformat()

                    # Verificar se está travado (mais de 5 minutos sem atualização)
                    if row[2]:  # started_at
                        start_time = datetime.fromisoformat(row[2])
                        elapsed = (datetime.now() - start_time).total_seconds()
                        if elapsed > 300:  # 5 minutos
                            logger.warning(f"⚠️ Execução {execution_id} parece travada ({elapsed:.0f}s sem resposta)")

                    # Cancelar execução
                    cursor.execute("""
                        UPDATE task_executions
                        SET status = 'cancelled',
                            error_message = 'Parada Forçada (Stuck/Terminated)',
                            completed_at = %s
                        WHERE id = %s
                    """, (now, execution_id))

                    # Resetar status da tarefa se ainda estiver rodando
                    cursor.execute("""
                        UPDATE tasks
                        SET status = 'idle', last_status = 'cancelled', last_run = %s
                        WHERE id = %s AND status = 'running'
                    """, (now, row[1]))  # task_id

                    conn.commit()
                    return {"status": "success", "message": "Tarefa travada foi forçada a parar (Limpeza de DB)"}
                else:
                    return {"status": "info", "message": f"Tarefa não está rodando (Status: {status})"}

        except Exception as e:
            logger.error(f"Erro ao forçar parada da tarefa {execution_id}: {e}")
            return {"status": "error", "message": f"Erro interno: {str(e)}"}

    def _ensure_process_terminated(self):
        """Garante que processos sejam terminados adequadamente"""
        try:
            if hasattr(self, '_current_process') and self._current_process:
                try:
                    # Tentar terminar graciosamente
                    self._current_process.terminate()

                    # Aguardar até 5 segundos
                    try:
                        self._current_process.wait(timeout=5)
                        logger.info("✅ Processo terminado graciosamente")
                    except subprocess.TimeoutExpired:
                        # Forçar kill se não terminou
                        self._current_process.kill()
                        self._current_process.wait()
                        logger.warning("⚠️ Processo forçado a terminar")

                except Exception as e:
                    logger.error(f"Erro ao terminar processo: {e}")

                finally:
                    self._current_process = None

        except Exception as e:
            logger.error(f"Erro ao garantir terminação do processo: {e}")

    def _worker_loop(self):
        """Loop principal do worker"""
        logger.info("🔄 TaskManager worker loop iniciado")

        while self._running:
            try:
                # Esperar por tarefa na fila (timeout para verificar _running)
                try:
                    task_id, execution_id = self._task_queue.get(timeout=1)
                except Empty:
                    continue

                # Adicionar à lista de tarefas em execução
                self._running_tasks.append((task_id, execution_id))
                self._current_execution_id = execution_id

                # Executar tarefa
                self._execute_task(task_id, execution_id)

                # Remover da lista de tarefas em execução
                self._running_tasks.remove((task_id, execution_id))
                self._current_execution_id = None

            except Exception as e:
                logger.error(f"❌ Erro no worker: {e}")
                # Remover da lista de tarefas em execução se ainda estiver lá
                if (task_id, execution_id) in self._running_tasks:
                    self._running_tasks.remove((task_id, execution_id))
                self._current_execution_id = None
                time.sleep(1)

        logger.info("🛑 TaskManager worker loop encerrado")

    def _execute_task(self, task_id: int, execution_id: int):
        """Executa uma tarefa de backup"""
        task_name = "Unknown"
        try:
            # Buscar dados da tarefa
            with self.core.get_db_connection() as conn:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("""
                    SELECT t.*, r.path as repo_path, r.motor_password, r.cloud_password,
                           r.type as repo_type, r.name as repo_name, r.config as repo_config,
                           r.engine as repository_engine
                    FROM tasks t
                    JOIN repositories r ON t.repository_id = r.id
                    WHERE t.id = %s
                """, (task_id,))
                row = cursor.fetchone()
                task = dict(row) if row else None

            # Extrair credenciais do config JSON do repositório
            if task and task.get('repo_config'):
                try:
                    config = json.loads(task['repo_config']) if isinstance(task['repo_config'], str) else task['repo_config']
                    task['aws_access_key'] = config.get('aws_access_key') or config.get('access_key', '')
                    task['aws_secret_key'] = config.get('aws_secret_key') or config.get('secret_key', '')
                    task['b2_account_id'] = config.get('b2_account_id') or config.get('access_key', '')
                    task['b2_account_key'] = config.get('b2_account_key') or config.get('secret_key', '')
                    task['endpoint'] = config.get('endpoint', '')
                    task['region'] = config.get('region', '')
                    task['prefix'] = config.get('prefix', '')
                    if not task.get('repo_path'):
                        task['repo_path'] = config.get('bucket') or ''
                except (json.JSONDecodeError, TypeError):
                    pass

            if not task:
                error_msg = "Tarefa não encontrada"
                logger.error(f"❌ {error_msg} (ID: {task_id})")
                self._update_execution(execution_id, 'failed', error_message=error_msg)
                self.monitor.complete_backup(task_id, error_message=error_msg)
                self._register_task_error(task_id, execution_id, f"Task {task_id}", "unknown", error_msg)
                return

            task_name = task.get('name', f'Task {task_id}')
            engine = (task.get('repository_engine') or task.get('engine') or 'restic').lower()
            logger.info(f"▶️ Executando tarefa: {task_name} (engine: {engine})")

            self.monitor.start_backup(task_id, execution_id, task_name, task.get('repo_name', 'Unknown'))

            if engine == 'restic':
                result = self._run_restic_backup(task, execution_id)
            elif engine == 'duplicati':
                result = self._run_duplicati_backup(task, execution_id)
            elif engine == 'kopia':
                result = self._run_kopia_backup(task, execution_id)
            elif engine == 'gboc_native':
                result = self._run_gboc_native_backup(task, execution_id)
            else:
                result = {"success": False, "error": f"Motor de backup desconhecido: {engine}"}

            self._ensure_process_terminated()

            if result.get('success'):
                snapshot_id = result.get('snapshot_id')
                files_count = int(result.get('files', 0) or 0)
                bytes_count = int(result.get('bytes', 0) or 0)
                self._register_backup_as_snapshot(task.get('repository_id', 0), snapshot_id, files_count, bytes_count)
                self._update_execution(
                    execution_id,
                    'completed',
                    snapshot_id=snapshot_id,
                    files_processed=files_count,
                    bytes_processed=bytes_count
                )
                self.monitor.complete_backup(task_id, snapshot_id=snapshot_id)
                logger.info(f"✅ Tarefa {task_name} concluída com sucesso")

                # 🛡️ Auto-Verificação Pós-Backup (SureRestore On-Completion)
                try:
                    if hasattr(self, 'auto_verify_engine') and self.auto_verify_engine:
                        self.auto_verify_engine.trigger_post_backup_verification_async(task_id, execution_id)
                except Exception as _ave_err:
                    logger.warning(f"[SureRestore] Aviso ao disparar auto-verificação pós-backup: {_ave_err}")
            else:
                error_msg = result.get('error', 'Erro desconhecido')
                self._update_execution(execution_id, 'failed', error_message=error_msg)
                self.monitor.complete_backup(task_id, error_message=error_msg)
                logger.error(f"❌ Falha na tarefa {task_name}: {error_msg}")
                self._register_task_error(task_id, execution_id, task_name, engine, error_msg)

        except Exception as e:
            error_msg = f"Erro crítico na execução: {str(e)}"
            logger.error(f"💥 {error_msg}")
            self._ensure_process_terminated()
            try:
                self._update_execution(execution_id, 'failed', error_message=error_msg)
                self.monitor.complete_backup(task_id, error_message=error_msg)
                self._register_task_error(task_id, execution_id, task_name, 'unknown', error_msg)
            except Exception as cleanup_error:
                logger.error(f"❌ Erro ao fazer limpeza: {cleanup_error}")

    def _run_restic_backup(self, task: Dict, execution_id: int) -> Dict:
        """Executa backup com Restic"""
        try:
            restic = get_engine_path_or_raise('restic')
            env = os.environ.copy()

            password = self._get_password(task)
            if not password:
                return {"success": False, "error": "Senha não configurada"}

            env["RESTIC_PASSWORD"] = password
            repo_type = (task.get('repo_type') or task.get('type') or 'local')
            self._configure_restic_repository(env, task)

            if repo_type != 'local':
                check_result = subprocess.run([restic, "snapshots"], env=env, capture_output=True, text=True, timeout=30)
                if check_result.returncode != 0:
                    stderr_check = (check_result.stderr or '').strip()
                    stderr_lower = stderr_check.lower()
                    if "wrong password" in stderr_lower or "no key found" in stderr_lower or "incorrect password" in stderr_lower:
                        return {"success": False, "error": "Restic: senha inválida para o repositório (wrong password or no key found)"}
                    logger.warning(f"[!] Repositório Restic não encontrado: {stderr_check}")
                    init_result = subprocess.run([restic, "init"], env=env, capture_output=True, text=True, timeout=60)
                    if init_result.returncode != 0:
                        init_stderr = (init_result.stderr or '').lower()
                        if not ("already exists" in init_stderr or "already initialized" in init_stderr):
                            return {"success": False, "error": f"Falha na inicialização: {(init_result.stderr or '').strip()}"}

            source_paths_raw = task.get('source_paths', '[]')
            try:
                source_paths = json.loads(source_paths_raw) if isinstance(source_paths_raw, str) else source_paths_raw
                if not isinstance(source_paths, list):
                    raise ValueError("Caminhos de origem devem ser uma lista")
            except (json.JSONDecodeError, TypeError):
                return {"success": False, "error": "Formato inválido para caminhos de origem"}

            cmd = [restic, "backup", "--json"] + source_paths

            self._current_process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )

            stats = {"files": 0, "bytes": 0}
            start_time = time.time()
            timeout = 86400

            while True:
                if time.time() - start_time > timeout:
                    self._current_process.terminate()
                    return {"success": False, "error": "Timeout: Restic backup process took too long and was terminated."}

                line = self._current_process.stdout.readline()
                if not line:
                    if self._current_process.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue

                try:
                    data = json.loads(line)
                    if data.get('message_type') == 'status':
                        self.monitor.update_progress(
                            task.get('id'),
                            files_processed=data.get('files_done', 0),
                            files_total=data.get('total_files', 0),
                            bytes_processed=data.get('bytes_done', 0),
                            bytes_total=data.get('total_bytes', 0),
                            current_file=data.get('current_files', [''])[0] if data.get('current_files') else None
                        )
                    elif data.get('message_type') == 'summary':
                        stats['files'] = data.get('files_new', 0) + data.get('files_changed', 0)
                        stats['bytes'] = data.get('data_added', 0)
                        stats['snapshot_id'] = data.get('snapshot_id')
                except (json.JSONDecodeError, ValueError):
                    pass

            if self._current_process.returncode == 0:
                self._mark_repository_initialized(task.get('repository_id'))
                return {"success": True, **stats}

            stderr_output = (self._current_process.stderr.read() or '').strip()
            return {"success": False, "error": stderr_output or "Unknown error"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_duplicati_backup(self, task: Dict, execution_id: int) -> Dict:
        """Executa backup com Duplicati"""
        try:
            dup_exe = get_engine_path('duplicati')
            if not dup_exe:
                return {"success": False, "error": "Duplicati-CLI não encontrado"}

            source_paths_raw = task.get('source_paths', '[]')
            try:
                source_paths = json.loads(source_paths_raw) if isinstance(source_paths_raw, str) else source_paths_raw
                if not isinstance(source_paths, list):
                    raise ValueError("Caminhos de origem devem ser uma lista")
            except (json.JSONDecodeError, TypeError):
                return {"success": False, "error": "Formato inválido para caminhos de origem"}

            if not source_paths:
                return {"success": False, "error": "Nenhum caminho de origem especificado"}

            valid_sources = []
            for path in source_paths:
                normalized_path = os.path.normpath(path)
                if '..' in normalized_path or not os.path.exists(normalized_path):
                    raise ValueError(f"Caminho inválido ou não encontrado: {path}")
                valid_sources.append(normalized_path)

            db_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "duplicati_dbs")
            os.makedirs(db_dir, exist_ok=True)
            local_db = os.path.join(db_dir, f"task_{task['id']}.sqlite")

            password = self._get_password(task) or "gboc"
            target_url = self._build_duplicati_url(task, password)
            auth_args = self._build_duplicati_auth_args(task)

            if os.path.exists(local_db):
                repair_cmd = [dup_exe, "repair", target_url, f"--dbpath={local_db}", "--encryption-module=aes", f"--passphrase={password}", *auth_args]
                try:
                    subprocess.run(repair_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=300)
                except Exception:
                    pass

            cmd = [
                dup_exe, "backup", target_url, *valid_sources,
                f"--dbpath={local_db}",
                "--backup-name=gboc-backup",
                "--encryption-module=aes",
                f"--passphrase={password}",
                "--disable-module=console-log-output",
                "--console-log-level=information",
                *auth_args
            ]

            self._current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )

            try:
                stdout, stderr = self._current_process.communicate(timeout=86400)
            except subprocess.TimeoutExpired:
                self._current_process.terminate()
                return {"success": False, "error": "Timeout: Duplicati backup process took too long and was terminated."}

            combined_output = (stdout or '') + '\n' + (stderr or '')
            backup_success = bool(re.search(r'backup completed successfully', combined_output, re.IGNORECASE))

            files_backed_up = 0
            bytes_backed_up = 0

            m_added = re.search(r'Files added:\s*(\d+)', combined_output)
            files_added = int(m_added.group(1)) if m_added else 0
            m_changed = re.search(r'Files changed:\s*(\d+)', combined_output)
            files_changed = int(m_changed.group(1)) if m_changed else 0
            files_backed_up = files_added + files_changed

            m_uploaded = re.search(r'Data uploaded:\s*([\d.,]+)\s*(\w+)', combined_output)
            if m_uploaded:
                size_val = float(m_uploaded.group(1).replace(',', '.'))
                size_unit = m_uploaded.group(2).upper()
                if 'KB' in size_unit:
                    bytes_backed_up = int(size_val * 1024)
                elif 'MB' in size_unit:
                    bytes_backed_up = int(size_val * 1024 * 1024)
                elif 'GB' in size_unit:
                    bytes_backed_up = int(size_val * 1024 * 1024 * 1024)
                else:
                    bytes_backed_up = int(size_val)

            has_error = bool(re.search(r'backup failed|(?:^|\n)\s*error:|fatal:', combined_output, re.IGNORECASE))
            fatal_error = (self._current_process.returncode != 0 and not backup_success) or (has_error and not backup_success)

            if fatal_error:
                error_msg = stderr or stdout or "Erro desconhecido no Duplicati"
                return {"success": False, "error": error_msg}

            self._mark_repository_initialized(task.get('repository_id'))
            logger.info(f"✅ Backup Duplicati concluído: {files_backed_up} arquivos, {bytes_backed_up} bytes")
            return {"success": True, "files": files_backed_up, "bytes": bytes_backed_up}

        except Exception as e:
            self.logger.error(f"Erro no backup Duplicati: {e}")
            return {"success": False, "error": str(e)}

    def _run_kopia_backup(self, task: Dict, execution_id: int) -> Dict:
        """Executa backup com Kopia (modo básico)."""
        try:
            kopia = get_engine_path_or_raise('kopia')
            env = os.environ.copy()

            password = self._get_password(task)
            if not password:
                return {"success": False, "error": "Senha não configurada"}

            env['KOPIA_PASSWORD'] = password
            repo_type = (task.get('repo_type') or task.get('type') or 'local').lower()

            source_paths_raw = task.get('source_paths', '[]')
            try:
                source_paths = json.loads(source_paths_raw) if isinstance(source_paths_raw, str) else source_paths_raw
                if not isinstance(source_paths, list):
                    raise ValueError("Caminhos de origem devem ser uma lista")
            except (json.JSONDecodeError, TypeError):
                return {"success": False, "error": "Formato inválido para caminhos de origem"}

            if not source_paths:
                return {"success": False, "error": "Nenhum caminho de origem especificado"}

            config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "kopia_configs")
            os.makedirs(config_dir, exist_ok=True)
            config_path = os.path.join(config_dir, f"task_{task.get('id', execution_id)}.config")
            env['KOPIA_CONFIG_PATH'] = os.path.dirname(config_path)

            connect_cmd = [kopia, 'repository', 'connect', '--config-file', config_path]
            if repo_type == 'local':
                connect_cmd.extend(['filesystem', '--path', task.get('repo_path', '')])
            elif repo_type in ('s3', 'wasabi'):
                bucket = task.get('repo_path', '')
                region = self._resolve_region(task)
                access_key = task.get('aws_access_key', '') or task.get('access_key', '')
                secret_key = task.get('aws_secret_key', '') or task.get('secret_key', '')
                s3_args = [
                    's3',
                    '--bucket', bucket,
                    '--access-key', access_key,
                    '--secret-access-key', secret_key,
                    '--region', region
                ]
                prefix = (task.get('prefix') or '').strip()
                if prefix:
                    if not prefix.endswith('/'):
                        prefix += '/'
                    s3_args.extend(['--prefix', prefix])
                if repo_type == 'wasabi':
                    endpoint = task.get('endpoint') or f"s3.{region}.wasabisys.com"
                    s3_args.extend(['--endpoint', endpoint])
                elif task.get('endpoint'):
                    s3_args.extend(['--endpoint', task.get('endpoint')])
                connect_cmd.extend(s3_args)
            elif repo_type == 'b2':
                connect_cmd.extend([
                    'b2',
                    '--bucket', task.get('repo_path', ''),
                    '--key-id', task.get('b2_account_id', ''),
                    '--key', task.get('b2_account_key', '')
                ])

            c = subprocess.run(connect_cmd, env=env, capture_output=True, text=True, timeout=60)
            if c.returncode != 0:
                connect_err = (c.stderr or c.stdout or 'Falha ao conectar repositório Kopia').strip()
                return {"success": False, "error": connect_err}

            cmd = [kopia, 'snapshot', 'create', '--config-file', config_path] + source_paths

            self._current_process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )

            try:
                stdout, stderr = self._current_process.communicate(timeout=86400)
            except subprocess.TimeoutExpired:
                self._current_process.terminate()
                return {"success": False, "error": "Timeout: Kopia backup process took too long and was terminated."}

            output = (stdout or '') + '\n' + (stderr or '')
            if self._current_process.returncode != 0:
                return {"success": False, "error": (stderr or stdout or 'Erro no Kopia').strip()}

            snapshot_id = None
            m = re.search(r'([a-f0-9]{32,64})', output, re.IGNORECASE)
            if m:
                snapshot_id = m.group(1)

            self._mark_repository_initialized(task.get('repository_id'))
            return {"success": True, "files": 0, "bytes": 0, "snapshot_id": snapshot_id}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_gboc_native_backup(self, task: Dict, execution_id: int) -> Dict:
        """Executa backup com engine GBOC Native."""
        try:
            from engines.repository_manager import RepositoryManager

            source_paths_raw = task.get('source_paths', '[]')
            try:
                source_paths = json.loads(source_paths_raw) if isinstance(source_paths_raw, str) else source_paths_raw
                if not isinstance(source_paths, list):
                    raise ValueError("Caminhos de origem devem ser uma lista")
            except (json.JSONDecodeError, TypeError):
                return {"success": False, "error": "Formato inválido para caminhos de origem"}

            if not source_paths:
                return {"success": False, "error": "Nenhum caminho de origem especificado"}

            for p in source_paths:
                if not os.path.exists(p):
                    return {"success": False, "error": f"Caminho inválido ou não encontrado: {p}"}

            repo_cfg = {
                'id': task.get('repository_id'),
                'type': task.get('repo_type', 'local'),
                'path': task.get('repo_path', ''),
                'bucket': task.get('repo_path', ''),
                'engine': 'gboc_native',
                'motor_password': task.get('motor_password'),
                'cloud_password': task.get('cloud_password'),
                'aws_access_key': task.get('aws_access_key'),
                'aws_secret_key': task.get('aws_secret_key'),
                'b2_account_id': task.get('b2_account_id'),
                'b2_account_key': task.get('b2_account_key'),
                'endpoint': task.get('endpoint'),
                'region': task.get('region'),
                'prefix': task.get('prefix')
            }

            backend = RepositoryManager(self.core)._create_backend_from_config(repo_cfg)
            engine = GBOCNativeEngine({'source_paths': source_paths}, backend)
            result = engine.run_backup()

            if result.get('success'):
                self._mark_repository_initialized(task.get('repository_id'))

            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def trigger_task(self, task_id: int) -> Dict[str, Any]:
        last_error = None
        for i in range(5):
            try:
                now = datetime.now().isoformat()
                with self.core.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT status, name FROM tasks WHERE id = %s", (task_id,))
                    row = cursor.fetchone()
                    if not row:
                        return {"status": "error", "message": "Tarefa não encontrada"}
                    cursor.execute("""
                        INSERT INTO task_executions (task_id, status, started_at, files_processed, bytes_processed, progress)
                        VALUES (%s, 'running', %s, 0, 0, 0)
                    """, (task_id, now))
                    cursor.execute("SELECT LASTVAL()")
                    exec_id = cursor.fetchone()[0]
                    cursor.execute("UPDATE tasks SET status = 'running' WHERE id = %s", (task_id,))
                    conn.commit()
                self.queue_task(task_id, exec_id)
                return {"status": "success", "task_id": task_id, "execution_id": exec_id}
            except Exception as e:
                last_error = e
                time.sleep(0.2 * (i + 1))
        return {"status": "error", "message": str(last_error) if last_error else "Erro ao disparar tarefa"}

    def run_task(self, task_id: int) -> Dict[str, Any]:
        return self.trigger_task(task_id)

    def _update_execution(self, execution_id: int, status: str, **kwargs):
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                sql = "UPDATE task_executions SET status = %s, completed_at = %s"
                values = [status, datetime.now().isoformat()]

                if 'error_message' in kwargs:
                    sql += ", error_message = %s"
                    values.append(kwargs['error_message'])
                if 'snapshot_id' in kwargs:
                    sql += ", snapshot_id = %s"
                    values.append(kwargs['snapshot_id'])
                if 'files_processed' in kwargs:
                    sql += ", files_processed = %s"
                    values.append(kwargs['files_processed'])
                if 'bytes_processed' in kwargs:
                    sql += ", bytes_processed = %s"
                    values.append(kwargs['bytes_processed'])

                sql += " WHERE id = %s"
                values.append(execution_id)
                cur.execute(sql, tuple(values))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Erro ao atualizar execução {execution_id}: {e}")

    def _register_backup_as_snapshot(self, repository_id: int, snapshot_id: Optional[str], files_count: int, bytes_count: int):
        try:
            logger.info(f"✅ Backup registrado como snapshot {snapshot_id} - disponível para restore")
        except Exception:
            pass

    def get_task_status(self, task_id: int) -> Dict[str, Any]:
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
                task = cur.fetchone()
                if not task:
                    return {"status": "error", "message": "Tarefa não encontrada"}
                return {"status": "success", "task": dict(task)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_running_executions(self) -> Dict[str, Any]:
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("""
                    SELECT te.id as execution_id, te.task_id, t.name as task_name, t.engine,
                           r.name as repository_name, te.status, te.started_at,
                           te.files_processed, te.files_total, te.bytes_processed, te.bytes_total,
                           te.current_file, te.progress
                    FROM task_executions te
                    LEFT JOIN tasks t ON te.task_id = t.id
                    LEFT JOIN repositories r ON t.repository_id = r.id
                    WHERE te.status = 'running'
                    ORDER BY te.started_at DESC
                """)
                rows = cur.fetchall()
                executions = [dict(r) for r in rows]
                return {"status": "success", "executions": executions, "count": len(executions)}
        except Exception as e:
            return {"status": "error", "message": str(e), "executions": [], "count": 0}

    def get_execution_details(self, execution_id: int) -> Dict[str, Any]:
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("SELECT * FROM task_executions WHERE id = %s", (execution_id,))
                row = cur.fetchone()
                if not row:
                    return {"status": "error", "message": "Execução não encontrada"}
                return {"status": "success", "execution": dict(row)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

