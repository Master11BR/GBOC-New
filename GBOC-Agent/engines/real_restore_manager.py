#!/usr/bin/env python3
"""
🔄 GBOC Agent - Real Restore Module (RESTAURAÇÃO REAL!)
Restaura arquivos e diretórios de snapshots reais
Suporta Restic, Kopia e Duplicati
"""

import subprocess
import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
import threading
import time
import shutil

from engines.engine_paths import get_engine_path_or_raise, get_engine_path

logger = logging.getLogger(__name__)


class RestoreManager:
    """Gerenciador de restauração REAL - SEM SIMULAÇÃO"""
    
    def __init__(self, core_or_db):
        """Aceita SharedCore ou conexão direta"""
        if hasattr(core_or_db, 'get_db_connection'):
            self.core = core_or_db
            self.db = None
        else:
            self.core = None
            self.db = core_or_db
        self.active_restores = {}

    def _append_restore_log(self, restore_id: int, message: str):
        """Acumula logs em memória para exibição no monitor de restauração."""
        try:
            entry = self.active_restores.setdefault(restore_id, {"logs": [], "progress": 0, "status": "running"})
            entry.setdefault("logs", []).append({
                "timestamp": datetime.now().isoformat(),
                "message": message
            })
            # limitar tamanho para não crescer indefinidamente
            if len(entry["logs"]) > 200:
                entry["logs"] = entry["logs"][-200:]
        except Exception:
            pass
    
    def _get_db(self):
        """Obtém conexão com o banco"""
        if self.core and hasattr(self.core, 'get_db_connection'):
            return self.core.get_db_connection()
        return self.db

    def _get_wasabi_endpoint(self, repo: Dict[str, Any]) -> str:
        """Resolve o endpoint Wasabi correto baseado na região."""
        endpoint = (repo.get('endpoint') or '').strip()
        if endpoint:
            return endpoint
        region = (repo.get('region') or 'us-east-1').strip()
        return f"s3.{region}.wasabisys.com"

    def _resolve_region(self, repo: Dict[str, Any]) -> str:
        """Resolve a região real: usa config, ou extrai do endpoint, ou default."""
        region = (repo.get('region') or '').strip()
        if region:
            return region
        endpoint = (repo.get('endpoint') or '').strip()
        if endpoint:
            # Extrair região de endpoints como s3.eu-central-2.wasabisys.com
            parts = endpoint.replace('https://', '').replace('http://', '').split('.')
            if len(parts) >= 3 and parts[0] == 's3':
                return parts[1]
        return 'us-east-1'

    def _build_kopia_s3_args(self, repo: Dict[str, Any]) -> list:
        """Monta argumentos de conexão Kopia S3/Wasabi com suporte a prefix."""
        bucket = repo.get('bucket', '') or repo.get('path', '')
        region = self._resolve_region(repo)
        access_key = repo.get('aws_access_key', '') or repo.get('access_key', '')
        secret_key = repo.get('aws_secret_key', '') or repo.get('secret_key', '')

        args = [
            's3',
            '--bucket', bucket,
            '--access-key', access_key,
            '--secret-access-key', secret_key,
            '--region', region
        ]

        # Prefix para isolamento dentro do bucket
        prefix = (repo.get('prefix') or '').strip()
        if prefix:
            if not prefix.endswith('/'):
                prefix += '/'
            args.extend(['--prefix', prefix])

        repo_type = repo.get('type', 'local')
        if repo_type == 'wasabi':
            endpoint = self._get_wasabi_endpoint(repo)
            args.extend(['--endpoint', endpoint])
        elif repo_type == 's3':
            endpoint = (repo.get('endpoint') or '').strip()
            if endpoint:
                args.extend(['--endpoint', endpoint])

        return args

    def _get_password(self, repo: Dict[str, Any]) -> str:
        """
        Obtém a senha correta baseada no tipo de repositório:
        - LOCAL: motor_password
        - CLOUD: cloud_password
        """
        repo_type = (repo.get('repo_type') or repo.get('type') or 'local').lower()
        if repo_type == 'local':
            return repo.get('motor_password', '')
        return repo.get('cloud_password', '')

    def _get_kopia_config_dir(self, repo: Dict, operation: str) -> tuple[str, bool]:
        """
        Obtém ou cria diretório de configuração Kopia.

        Retorna (config_dir, is_temporary) onde is_temporary indica se deve ser limpo depois.

        Prioriza configurações existentes criadas pelo backup em ./data/kopia_configs/
        Só cria configurações temporárias se não encontrar existentes.
        """
        # Primeiro, tentar encontrar configurações existentes do backup
        backup_config_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "data", "kopia_configs"
        )

        # Procurar por arquivos de configuração existentes para este repositório
        if os.path.exists(backup_config_dir):
            for config_file in os.listdir(backup_config_dir):
                if config_file.endswith('.config'):
                    # Verificar se esta configuração funciona para o repositório atual
                    config_path = os.path.join(backup_config_dir, config_file)
                    if self._test_kopia_config(config_path, repo):
                        return config_path, False  # Não é temporário

        # Se não encontrou configuração existente, criar temporária
        timestamp = int(datetime.now().timestamp())
        temp_config_dir = os.path.join(
            os.path.expanduser("~"),
            ".kopia",
            f"restore_{operation}_{repo['id']}_{timestamp}"
        )
        os.makedirs(temp_config_dir, exist_ok=True)
        return os.path.join(temp_config_dir, "repository.config"), True  # É temporária

    def _test_kopia_config(self, config_path: str, repo: Dict) -> bool:
        """
        Testa se uma configuração Kopia existente funciona para o repositório.
        """
        try:
            kopia = get_engine_path_or_raise('kopia')
            env = os.environ.copy()
            env['KOPIA_CONFIG_PATH'] = os.path.dirname(config_path)
            env['KOPIA_PASSWORD'] = self._get_password(repo)

            # Tentar listar repositórios conectados
            cmd = [kopia, 'repository', 'status', '--config-file', config_path]
            result = subprocess.run(
                cmd, env=env, capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except:
            return False

    def start_restore(self, repository_id: int, snapshot_id: str, files: List[str], target_path: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Inicia um processo de restauração assíncrono.
        
        Args:
            repository_id: ID do repositório
            snapshot_id: ID do snapshot
            files: Lista de arquivos/diretórios para restaurar
            target_path: Caminho de destino
            options: Opções adicionais (overwrite, preserve_permissions, etc.)
        """
        try:
            # 1. Criar registro inicial no banco
            restore_id = self._create_restore_entry(repository_id, snapshot_id, target_path, len(files))
            
            # 2. Registrar contexto ativo e iniciar thread de trabalho
            self.active_restores[restore_id] = {
                "logs": [],
                "progress": 0,
                "status": "running"
            }
            self._append_restore_log(restore_id, f"Restauração iniciada para {len(files)} item(ns) no destino {target_path}")

            thread = threading.Thread(
                target=self._restore_worker,
                args=(restore_id, repository_id, snapshot_id, files, target_path, options),
                daemon=True
            )
            thread.start()

            logger.info(f"🚀 Restauração iniciada (ID: {restore_id}) para {len(files)} arquivos")
            
            return {
                "status": "started",
                "restore_id": restore_id,
                "message": "Restauração iniciada em segundo plano"
            }
            
        except Exception as e:
            logger.error(f"❌ Falha ao iniciar restauração: {e}")
            raise

    def _create_restore_entry(self, repo_id: int, snapshot_id: str, target_path: str, total_files: int) -> int:
        """Cria registro inicial na tabela restore_history"""
        try:
            db = self._get_db()
            sql = """
                INSERT INTO restore_history (
                    repository_id, snapshot_id, status, target_path, 
                    total_files, created_at, files_restored, bytes_restored
                ) VALUES (%s, %s, %s, %s, %s, %s, 0, 0)
                RETURNING id
            """
            params = (repo_id, snapshot_id, 'running', target_path, total_files, datetime.now().isoformat())
            
            if hasattr(db, '__enter__'):
                # Context manager (PostgreSQL)
                with db as conn:
                    cursor = conn.cursor()
                    cursor.execute(sql, params)
                    restore_id = cursor.fetchone()[0]
                    conn.commit()
                    return restore_id
            else:
                # Conexão SQLite (fallback)
                cursor = db.cursor()
                cursor.execute(sql.replace('RETURNING id', ''), params)
                cursor.execute("SELECT last_insert_rowid()")
                restore_id = cursor.fetchone()[0]
                db.commit()
                return restore_id
        except Exception as e:
            logger.error(f"❌ Erro ao criar entrada de restauração: {e}", exc_info=True)
            raise

    def _update_restore_progress(self, restore_id: int, files_restored: int, bytes_restored: int = 0):
        """Atualiza progresso da restauração"""
        try:
            db = self._get_db()
            sql = "UPDATE restore_history SET files_restored = %s, bytes_restored = %s WHERE id = %s"
            params = (files_restored, bytes_restored, restore_id)

            active = self.active_restores.setdefault(restore_id, {"logs": [], "progress": 0, "status": "running"})
            active["files_restored"] = files_restored
            active["bytes_restored"] = bytes_restored
            
            if hasattr(db, '__enter__'):
                with db as conn:
                    cursor = conn.cursor()
                    cursor.execute(sql, params)
                    conn.commit()
            else:
                cursor = db.cursor()
                cursor.execute(sql, params)
                db.commit()
        except Exception as e:
            logger.error(f"Erro ao atualizar progresso restore {restore_id}: {e}")

    def _complete_restore(self, restore_id: int, status: str, error_message: Optional[str] = None, duration: float = 0):
        """Finaliza registro de restauração"""
        try:
            active = self.active_restores.setdefault(restore_id, {"logs": [], "progress": 0, "status": "running"})
            active["status"] = status
            active["progress"] = 100 if status in ('success', 'completed') else active.get('progress', 0)
            if error_message:
                self._append_restore_log(restore_id, f"Erro: {error_message}")
            else:
                self._append_restore_log(restore_id, f"Restauração finalizada com status: {status}")

            db = self._get_db()
            sql = """
                UPDATE restore_history 
                SET status = %s, error_message = %s, completed_at = %s, duration_seconds = %s
                WHERE id = %s
            """
            params = (status, error_message, datetime.now().isoformat(), duration, restore_id)
            
            if hasattr(db, '__enter__'):
                with db as conn:
                    cursor = conn.cursor()
                    cursor.execute(sql, params)
                    conn.commit()
            else:
                cursor = db.cursor()
                cursor.execute(sql, params)
                db.commit()
        except Exception as e:
            logger.error(f"Erro ao finalizar restore {restore_id}: {e}")

    def _restore_worker(self, restore_id: int, repository_id: int, snapshot_id: str, files: List[str], target_path: str, options: Optional[Dict[str, Any]] = None):
        """Worker que executa a restauração em background"""
        start_time = time.time()
        try:
            self._append_restore_log(restore_id, f"Iniciando worker de restauração para snapshot {snapshot_id}")
            result = self.restore_files(repository_id, snapshot_id, files, target_path, options)
            duration = time.time() - start_time
            status = result.get('status', 'completed')
            error_message = result.get('error_message')
            
            if status != 'success' and not error_message:
                error_message = 'Erro parcial ou falha na restauração'
                
            self._update_restore_progress(restore_id, result.get('files_restored', 0), result.get('bytes_restored', 0))
            self._complete_restore(restore_id, status, error_message, duration)
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"❌ Erro fatal no worker de restore {restore_id}: {e}")
            self._complete_restore(restore_id, 'failed', str(e), duration)
        
    def list_snapshots(self, repository_id: int) -> List[Dict[str, Any]]:
        """
        Lista snapshots REAIS de um repositório
        
        Returns:
            Lista de snapshots com metadata real
        """
        logger.info(f"📋 Listando snapshots - Repository {repository_id}")
        
        try:
            repo = self._load_repository(repository_id)
            if not repo:
                raise ValueError(f"Repository {repository_id} não encontrado")
            
            engine = repo.get('engine', 'restic')
            
            if engine == 'restic':
                return self._list_restic_snapshots(repo)
            elif engine == 'kopia':
                return self._list_kopia_snapshots(repo)
            elif engine == 'duplicati':
                return self._list_duplicati_snapshots(repo)
            elif engine == 'gboc_native':
                return self._list_native_snapshots(repo)
            else:
                raise ValueError(f"Engine '{engine}' não suportado")
                
        except Exception as e:
            logger.error(f"❌ Erro ao listar snapshots: {e}")
            raise

    def _list_native_snapshots(self, repo: Dict) -> List[Dict]:
        """Lista snapshots para o motor GBOC Native."""
        logger.info(f"Listando snapshots para o motor nativo no repositório '{repo['name']}'")
        if not self.core or not hasattr(self.core, 'repository_manager'):
            raise RuntimeError("RepositoryManager não está disponível no core.")
        
        backend = self.core.repository_manager.get_backend(repo['id'])
        all_files = backend.list_files()

        # Snapshots são os diretórios de primeiro nível (timestamps)
        snapshots_ids = sorted(list(set([f.split('/')[0] for f in all_files if '/' in f and f.split('/')[0].isdigit()])))

        snapshots = []
        for snapshot_id in snapshots_ids:
            try:
                # O ID é o timestamp, que também pode ser usado para data/hora
                ts = datetime.strptime(snapshot_id, '%Y%m%d%H%M%S')
                snapshots.append({
                    'id': snapshot_id,
                    'full_id': snapshot_id,
                    'time': ts.isoformat(),
                    'hostname': 'native',
                    'username': 'native',
                    'paths': ['/'], 
                    'engine': 'gboc_native'
                })
            except ValueError:
                continue # Ignora diretórios que não são timestamps válidos
        
        logger.info(f"✅ {len(snapshots)} snapshots nativos encontrados")
        return snapshots
    
    def _list_restic_snapshots(self, repo: Dict) -> List[Dict]:
        """Lista snapshots REAIS do Restic"""
        restic = get_engine_path_or_raise('restic')
        env = os.environ.copy()
        env['RESTIC_REPOSITORY'] = repo.get('path', '')
        env['RESTIC_PASSWORD'] = self._get_password(repo)

        # Configurar credenciais cloud
        repo_type = repo.get('type', 'local')
        if repo_type == 'b2':
            env['RESTIC_REPOSITORY'] = f"b2:{repo['path']}"
            env['B2_ACCOUNT_ID'] = repo.get('b2_account_id', '')
            env['B2_ACCOUNT_KEY'] = repo.get('b2_account_key', '')
        elif repo_type in ('s3', 'wasabi'):
            env['AWS_ACCESS_KEY_ID'] = repo.get('aws_access_key', '')
            env['AWS_SECRET_ACCESS_KEY'] = repo.get('aws_secret_key', '')
            if repo_type == 'wasabi':
                endpoint = self._get_wasabi_endpoint(repo)
                env['RESTIC_REPOSITORY'] = f"s3:{endpoint}/{repo['path']}"
            elif repo_type == 's3':
                env['RESTIC_REPOSITORY'] = f"s3:s3.amazonaws.com/{repo['path']}"

        cmd = [restic, 'snapshots', '--json']

        try:
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )

            snapshots_data = json.loads(result.stdout)
            
            # Converter para formato padronizado
            # IMPORTANTE: usar full_id como id de trabalho para evitar ambiguidades
            # de short_id quando há muitos snapshots.
            snapshots = []
            for snap in snapshots_data:
                full_id = snap.get('id', '')
                short_id = snap.get('short_id', '')
                snapshots.append({
                    'id': full_id,
                    'short_id': short_id,
                    'full_id': full_id,
                    'time': snap['time'],
                    'hostname': snap['hostname'],
                    'username': snap['username'],
                    'paths': snap['paths'],
                    'tags': snap.get('tags', []),
                    'parent': snap.get('parent', ''),
                    'tree': snap.get('tree', ''),
                    'engine': 'restic'
                })
            
            logger.info(f"✅ {len(snapshots)} snapshots encontrados")
            return snapshots
            
        except FileNotFoundError:
            logger.error("❌ Executável 'restic' não encontrado no PATH do sistema")
            raise ValueError("Motor 'restic' não está instalado ou não está no PATH do sistema. Instale o restic e adicione ao PATH.")
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or '').strip()
            stderr_l = stderr.lower()
            logger.error(f"❌ Erro ao listar snapshots Restic: {stderr}")

            if 'wrong password' in stderr_l or 'password is incorrect' in stderr_l:
                raise ValueError("Erro ao listar snapshots Restic: senha do repositório inválida")
            if 'repository does not exist' in stderr_l or 'is there a repository at the following location' in stderr_l:
                raise ValueError("Erro ao listar snapshots Restic: repositório não encontrado (path/bucket/prefix)")
            if 'access denied' in stderr_l or 'permission denied' in stderr_l:
                raise ValueError("Erro ao listar snapshots Restic: acesso negado (credenciais/permissões)")

            raise ValueError(f"Erro ao listar snapshots Restic: {stderr or 'falha desconhecida'}")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Erro ao parsear JSON do Restic: {e}")
            raise
    
    def _list_kopia_snapshots(self, repo: Dict) -> List[Dict]:
        """Lista snapshots REAIS do Kopia"""
        kopia = get_engine_path_or_raise('kopia')
        # Obter diretório de configuração (prioriza configurações existentes do backup)
        config_path, is_temporary = self._get_kopia_config_dir(repo, "list")

        env = os.environ.copy()
        env['KOPIA_CONFIG_PATH'] = os.path.dirname(config_path)
        env['KOPIA_PASSWORD'] = self._get_password(repo)

        try:
            # 1. Conectar ao repositório
            connect_cmd = [kopia, 'repository', 'connect', '--config-file', config_path]

            repo_type = repo.get('type', 'local')
            if repo_type == 'local':
                connect_cmd.extend(['filesystem', '--path', repo['path']])
            elif repo_type == 'b2':
                connect_cmd.extend([
                    'b2', 
                    '--bucket', repo.get('bucket', ''),
                    '--key-id', repo.get('b2_account_id', '') or repo.get('access_key', ''),
                    '--key', repo.get('b2_account_key', '') or repo.get('secret_key', '')
                ])
            elif repo_type in ('s3', 'wasabi'):
                connect_cmd.extend(self._build_kopia_s3_args(repo))

            # Executar conexão
            subprocess.run(
                connect_cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=60
            )

            # 2. Listar snapshots
            cmd = [kopia, 'snapshot', 'list', '--json', '--config-file', config_path]
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=120
            )
            
            snapshots_data = json.loads(result.stdout)
            
            snapshots = []
            for snap in snapshots_data:
                source = snap.get('source', {})
                snapshots.append({
                    'id': snap['id'],
                    'full_id': snap['id'],
                    'time': snap['startTime'],
                    'hostname': source.get('host', ''),
                    'username': source.get('userName', ''),
                    'paths': [source.get('path', '')] if source.get('path') else [],
                    'size': snap.get('stats', {}).get('totalSize', 0),
                    'engine': 'kopia'
                })
            
            return snapshots
            
        except FileNotFoundError:
            logger.error("❌ Executável 'kopia' não encontrado no PATH do sistema")
            raise ValueError("Motor 'kopia' não está instalado ou não está no PATH do sistema. Instale o kopia e adicione ao PATH.")
        except subprocess.TimeoutExpired:
            logger.error("❌ Timeout ao conectar/listar snapshots Kopia (120s)")
            raise ValueError("Timeout ao acessar repositório Kopia. Verifique a conexão de rede e credenciais.")
        except subprocess.CalledProcessError as e:
            stderr = e.stderr if hasattr(e, 'stderr') and e.stderr else str(e)
            if isinstance(stderr, bytes):
                stderr = stderr.decode('utf-8', errors='replace')
            # Limpar códigos ANSI
            import re
            stderr_clean = re.sub(r'\x1b\[[0-9;]*m', '', stderr).strip()
            logger.error(f"❌ Erro ao listar snapshots Kopia: {stderr_clean}")
            if 'not initialized' in stderr_clean.lower():
                raise ValueError(f"Repositório Kopia não está inicializado. Execute um backup primeiro ou verifique se o bucket/path está correto.")
            raise ValueError(f"Erro ao acessar repositório Kopia: {stderr_clean}")
        except Exception as e:
            logger.error(f"❌ Erro ao listar snapshots Kopia: {e}")
            raise
        finally:
            # Limpar configuração temporária (não limpar configurações compartilhadas do backup)
            if is_temporary:
                shutil.rmtree(os.path.dirname(config_path), ignore_errors=True)
    
    def _list_duplicati_snapshots(self, repo: Dict) -> List[Dict]:
        """Lista snapshots REAIS do Duplicati (local e cloud)"""
        repo_type = repo.get('type', 'local').lower()

        if repo_type == 'local':
            return self._list_duplicati_snapshots_local(repo)
        else:
            return self._list_duplicati_snapshots_cli(repo)

    def _get_duplicati_exe(self) -> str:
        """Localiza o executável do Duplicati CLI"""
        dup_exe = get_engine_path('duplicati')
        if not dup_exe:
            raise FileNotFoundError("Duplicati CLI não encontrado")
        return dup_exe

    def _build_duplicati_cli_args(self, repo: Dict) -> List[str]:
        """Constrói argumentos extras de autenticação para Duplicati CLI"""
        repo_type = repo.get('type', 'local').lower()
        args = []

        password = self._get_password(repo)
        if password:
            args.append(f"--passphrase={password}")

        if repo_type in ('s3', 'wasabi'):
            access_key = repo.get('access_key') or repo.get('aws_access_key', '')
            secret_key = repo.get('secret_key') or repo.get('aws_secret_key', '')
            endpoint = repo.get('endpoint', '')
            region = repo.get('region', '')

            if access_key:
                args.append(f"--aws-access-key-id={access_key}")
            if secret_key:
                args.append(f"--aws-secret-access-key={secret_key}")

            # Determinar server name para Duplicati
            if endpoint:
                args.append(f"--s3-server-name={endpoint}")
            elif repo_type == 'wasabi' and region:
                args.append(f"--s3-server-name=s3.{region}.wasabisys.com")
            elif repo_type == 's3' and region:
                args.append(f"--s3-server-name=s3.{region}.amazonaws.com")

        elif repo_type == 'b2':
            app_id = repo.get('access_key') or repo.get('b2_account_id', '')
            app_key = repo.get('secret_key') or repo.get('b2_account_key', '')
            if app_id:
                args.append(f"--b2-accountid={app_id}")
            if app_key:
                args.append(f"--b2-applicationkey={app_key}")

        elif repo_type == 'azure':
            account = repo.get('access_key') or repo.get('azure_account_name', '')
            key = repo.get('secret_key') or repo.get('azure_account_key', '')
            if account:
                args.append(f"--azure-account-name={account}")
            if key:
                args.append(f"--azure-accesskey={key}")

        return args

    def _list_duplicati_snapshots_cli(self, repo: Dict) -> List[Dict]:
        """Lista snapshots Duplicati usando CLI (para repos cloud)"""
        try:
            dup_exe = self._get_duplicati_exe()
            target_url = self._build_duplicati_url(repo)
            cli_args = self._build_duplicati_cli_args(repo)

            # Duplicati 'find' sem filename lista todos os backups disponíveis
            cmd = [dup_exe, 'find', target_url] + cli_args + ['--no-encryption=true']

            logger.info(f"🔍 Listando snapshots Duplicati via CLI: {target_url}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0 and not result.stdout.strip():
                # Tentar sem --no-encryption
                cmd2 = [dup_exe, 'find', target_url] + cli_args
                result = subprocess.run(
                    cmd2,
                    capture_output=True,
                    text=True,
                    timeout=120
                )

            output = result.stdout.strip()
            if not output:
                if result.stderr:
                    logger.warning(f"⚠️ Duplicati stderr: {result.stderr.strip()[:300]}")
                logger.info("📭 Nenhum snapshot Duplicati encontrado (output vazio)")
                return []

            # Parsear output do 'find' que lista backups
            # Formato típico:
            #   Listing backup sets:
            #   0: 2024-01-15 10:30:00 (Full) [15 files, 1.2 GB]
            #   1: 2024-01-16 10:30:00 (Incremental) [3 files, 100 MB]
            snapshots = []
            from datetime import datetime as dt
            import re

            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue

                # Padrão: "N: YYYY-MM-DD HH:MM:SS (Type)"
                match = re.match(
                    r'^\s*(\d+)\s*:\s*(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2})\s*\((\w+)\)',
                    line
                )
                if match:
                    version = int(match.group(1))
                    timestamp_str = match.group(2)
                    backup_type = match.group(3)

                    try:
                        timestamp = dt.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        timestamp = dt.now()

                    # Extrair contagem de arquivos e tamanho se disponível
                    size_match = re.search(r'\[(\d+)\s+files?,\s+([\d.]+\s*\w+)\]', line)
                    file_count = int(size_match.group(1)) if size_match else 0

                    snapshots.append({
                        'id': f"v{version}",
                        'full_id': f"version_{version}",
                        'time': timestamp.isoformat(),
                        'hostname': repo.get('name', 'duplicati'),
                        'username': 'duplicati',
                        'paths': [repo.get('path', '')],
                        'engine': 'duplicati',
                        'backup_type': backup_type,
                        'files': file_count,
                        'size': 0
                    })

            if not snapshots and output:
                # Se não encontrou padrão mas tem output, pode ser formato diferente
                # Tentar extrair qualquer informação útil
                logger.warning(f"⚠️ Output Duplicati não parseado: {output[:500]}")
                # Criar ao menos uma entrada genérica se há dados
                if 'backup' in output.lower() or 'version' in output.lower():
                    snapshots.append({
                        'id': 'v0',
                        'full_id': 'version_0',
                        'time': dt.now().isoformat(),
                        'hostname': repo.get('name', 'duplicati'),
                        'username': 'duplicati',
                        'paths': [repo.get('path', '')],
                        'engine': 'duplicati',
                        'files': 0,
                        'size': 0
                    })

            logger.info(f"✅ {len(snapshots)} snapshots Duplicati encontrados via CLI")
            return snapshots

        except FileNotFoundError as e:
            logger.error(f"❌ {e}")
            return []
        except subprocess.TimeoutExpired:
            logger.error("❌ Timeout ao listar snapshots Duplicati via CLI")
            return []
        except Exception as e:
            logger.error(f"❌ Erro ao listar snapshots Duplicati via CLI: {e}", exc_info=True)
            return []

    def _list_duplicati_snapshots_local(self, repo: Dict) -> List[Dict]:
        """Lista snapshots Duplicati a partir de arquivos .sqlite locais"""
        try:
            import sqlite3
            from pathlib import Path

            repo_path = repo.get('path', '')
            if not repo_path or not os.path.exists(repo_path):
                logger.warning(f"Caminho do repositório Duplicati não existe: {repo_path}")
                return []

            # Procurar por arquivos .sqlite do Duplicati
            db_files = list(Path(repo_path).glob('*.sqlite'))

            if not db_files:
                logger.warning(f"Nenhum arquivo de banco Duplicati encontrado em {repo_path}")
                return []

            snapshots = []

            # Para cada arquivo de banco, tentar extrair informações de versões
            for db_file in db_files:
                try:
                    conn = sqlite3.connect(str(db_file))
                    cursor = conn.cursor()

                    # Tentar obter versões de backup
                    cursor.execute("""
                        SELECT 
                            ID, 
                            Timestamp,
                            FileCount,
                            TotalSize
                        FROM Fileset
                        ORDER BY Timestamp DESC
                    """)

                    for row in cursor.fetchall():
                        version_id, timestamp, file_count, total_size = row

                        # Converter timestamp do Duplicati (formato Unix)
                        from datetime import datetime
                        dt = datetime.fromtimestamp(int(timestamp)) if timestamp else datetime.now()

                        snapshots.append({
                            'id': f"v{version_id}",
                            'full_id': f"version_{version_id}",
                            'time': dt.isoformat(),
                            'hostname': repo.get('name', 'duplicati'),
                            'username': 'duplicati',
                            'paths': [repo_path],
                            'engine': 'duplicati',
                            'files': file_count or 0,
                            'size': total_size or 0
                        })

                    conn.close()

                except sqlite3.Error as e:
                    logger.warning(f"Erro ao ler banco Duplicati {db_file}: {e}")
                    continue

            logger.info(f"✅ {len(snapshots)} snapshots Duplicati encontrados")
            return snapshots

        except Exception as e:
            logger.error(f"❌ Erro ao listar snapshots Duplicati: {e}", exc_info=True)
            return []

    def _list_duplicati_files(self, repo: Dict, snapshot_id: str, path: str) -> List[Dict]:
        """Lista arquivos de um snapshot Duplicati usando CLI"""
        try:
            import re
            dup_exe = self._get_duplicati_exe()
            target_url = self._build_duplicati_url(repo)
            cli_args = self._build_duplicati_cli_args(repo)

            # Extrair número da versão do snapshot_id (formato: "v0", "v1", etc)
            version = snapshot_id.lstrip('v').replace('version_', '')

            # Usar 'find' com versão específica e wildcard para listar conteúdo
            search_path = path.rstrip('/') + '/*' if path and path != '/' else '*'

            cmd = [dup_exe, 'find', target_url, search_path] + cli_args + [
                f'--version={version}',
                '--no-encryption=true'
            ]

            logger.info(f"📂 Listando arquivos Duplicati versão {version}: {path}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0 and not result.stdout.strip():
                # Tentar sem --no-encryption
                cmd2 = [dup_exe, 'find', target_url, search_path] + cli_args + [
                    f'--version={version}'
                ]
                result = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)

            output = result.stdout.strip()
            if not output:
                logger.info("📭 Nenhum arquivo encontrado neste snapshot Duplicati")
                return []

            files = []
            seen_dirs = set()

            # Parsear output - formato típico:
            # /path/to/file (size bytes, date)
            # ou simplesmente linhas com caminhos
            for line in output.splitlines():
                line = line.strip()
                if not line or line.startswith('Listing') or line.startswith('Searching') or line.startswith('Found'):
                    continue

                # Extrair tamanho se disponível: "filename (1234 bytes, ...)"
                size = 0
                size_match = re.search(r'\((\d+)\s+bytes?', line)
                if size_match:
                    size = int(size_match.group(1))
                    # Remover a parte do tamanho para obter o nome
                    name_part = re.sub(r'\s*\(.*\)\s*$', '', line)
                else:
                    name_part = line

                name_part = name_part.strip()
                if not name_part:
                    continue

                # Normalizar separadores
                name_part = name_part.replace('\\', '/')

                # Se o path atual não é raiz, filtrar apenas itens no nível correto
                clean_path = path.rstrip('/')
                if clean_path and clean_path != '/':
                    if not name_part.startswith(clean_path):
                        continue
                    relative = name_part[len(clean_path):].lstrip('/')
                else:
                    relative = name_part.lstrip('/')

                if not relative:
                    continue

                # Verificar se é um item direto ou um subdiretório
                parts = relative.split('/')
                if len(parts) > 1:
                    # É um arquivo em subdiretório — registrar o diretório
                    dir_name = parts[0]
                    if dir_name not in seen_dirs:
                        seen_dirs.add(dir_name)
                        files.append({
                            'name': dir_name,
                            'path': f"{clean_path}/{dir_name}" if clean_path else f"/{dir_name}",
                            'type': 'dir',
                            'is_dir': True,
                            'size': 0,
                            'mtime': ''
                        })
                else:
                    # Item direto neste nível
                    name = parts[0]
                    is_dir = name.endswith('/')
                    name = name.rstrip('/')

                    if name and name not in seen_dirs:
                        files.append({
                            'name': name,
                            'path': f"{clean_path}/{name}" if clean_path else f"/{name}",
                            'type': 'dir' if is_dir else 'file',
                            'is_dir': is_dir,
                            'size': size,
                            'mtime': ''
                        })

            logger.info(f"✅ {len(files)} items Duplicati encontrados")
            return files

        except FileNotFoundError as e:
            logger.error(f"❌ {e}")
            return []
        except subprocess.TimeoutExpired:
            logger.error("❌ Timeout ao listar arquivos Duplicati")
            return []
        except Exception as e:
            logger.error(f"❌ Erro ao listar arquivos Duplicati: {e}", exc_info=True)
            return []

    def list_files(self, repository_id: int, snapshot_id: str, path: str = "/") -> List[Dict]:
        """
        Lista arquivos REAIS dentro de um snapshot
        """
        logger.info(f"📂 Listando arquivos - Snapshot {snapshot_id}: {path}")
        
        try:
            repo = self._load_repository(repository_id)
            engine = repo.get('engine', 'restic')
            
            if engine == 'restic':
                return self._list_restic_files(repo, snapshot_id, path)
            elif engine == 'kopia':
                return self._list_kopia_files(repo, snapshot_id, path)
            elif engine == 'duplicati':
                return self._list_duplicati_files(repo, snapshot_id, path)
            elif engine == 'gboc_native':
                return self._list_native_files(repo, snapshot_id, path)
            else:
                raise ValueError(f"Engine '{engine}' não suportado para listagem")
                
        except Exception as e:
            logger.error(f"❌ Erro ao listar arquivos: {e}")
            raise

    def _list_native_files(self, repo: Dict, snapshot_id: str, path: str) -> List[Dict]:
        """Lista arquivos de um snapshot para o motor GBOC Native."""
        logger.info(f"Listando arquivos nativos para snapshot '{snapshot_id}'")
        if not self.core or not hasattr(self.core, 'repository_manager'):
            raise RuntimeError("RepositoryManager não está disponível no core.")

        backend = self.core.repository_manager.get_backend(repo['id'])
        
        # O "path" dentro do snapshot não se aplica diretamente ao nosso modelo de zips,
        # mas podemos listar o conteúdo dos zips. Por simplicidade, vamos listar os zips.
        all_files = backend.list_files(sub_path=snapshot_id)
        
        files = []
        for file_path in all_files:
            # Remove o prefixo do snapshot_id
            name = file_path.replace(f"{snapshot_id}/", "")
            files.append({
                'name': name,
                'path': f"/{name}", # Caminho simplificado
                'type': 'file', # Nativamente, só guardamos arquivos .zip
                'size': 0, # O tamanho real exigiria baixar o zip ou metadados
            })
        return files
    
    def _list_restic_files(self, repo: Dict, snapshot_id: str, path: str) -> List[Dict]:
        """Lista arquivos REAIS de um snapshot Restic"""
        restic = get_engine_path_or_raise('restic')
        env = os.environ.copy()
        env['RESTIC_REPOSITORY'] = repo.get('path', '')
        env['RESTIC_PASSWORD'] = self._get_password(repo)

        repo_type = repo.get('type', 'local')
        if repo_type == 'b2':
            env['RESTIC_REPOSITORY'] = f"b2:{repo['path']}"
            env['B2_ACCOUNT_ID'] = repo.get('b2_account_id', '')
            env['B2_ACCOUNT_KEY'] = repo.get('b2_account_key', '')
        elif repo_type in ('s3', 'wasabi'):
            env['AWS_ACCESS_KEY_ID'] = repo.get('aws_access_key', '')
            env['AWS_SECRET_ACCESS_KEY'] = repo.get('aws_secret_key', '')
            if repo_type == 'wasabi':
                endpoint = self._get_wasabi_endpoint(repo)
                env['RESTIC_REPOSITORY'] = f"s3:{endpoint}/{repo['path']}"
            elif repo_type == 's3':
                env['RESTIC_REPOSITORY'] = f"s3:s3.amazonaws.com/{repo['path']}"

        cmd = [restic, 'ls', snapshot_id, '--json']
        if path != "/":
            cmd.append(path)

        try:
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )

            # Normalizar path para comparação de filhos diretos
            norm_path = path.rstrip('/')
            if not norm_path:
                norm_path = ''
            # Profundidade esperada: filhos diretos = path_depth + 1
            path_depth = len([p for p in norm_path.split('/') if p])

            files = []
            seen_names = set()
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue

                try:
                    item = json.loads(line)
                    # Pular a linha de metadados do snapshot (struct_type=snapshot)
                    if item.get('struct_type') == 'snapshot' or 'name' not in item:
                        continue

                    item_path = item.get('path', '')
                    # Filtrar apenas filhos diretos do path solicitado
                    parts = [p for p in item_path.split('/') if p]
                    item_depth = len(parts)

                    if item_depth != path_depth + 1:
                        continue

                    # Verificar se é filho do path correto
                    if norm_path and not item_path.startswith(norm_path + '/'):
                        continue

                    name = item['name']
                    if name in seen_names:
                        continue
                    seen_names.add(name)

                    is_dir = item.get('type') == 'dir'
                    files.append({
                        'name': name,
                        'path': item_path,
                        'type': item['type'],
                        'is_dir': is_dir,
                        'size': item.get('size', 0),
                        'mtime': item.get('mtime', ''),
                        'mode': item.get('mode', 0)
                    })
                except (json.JSONDecodeError, KeyError):
                    continue

            return files
            
        except FileNotFoundError:
            logger.error("❌ Executável 'restic' não encontrado no PATH do sistema")
            raise ValueError("Motor 'restic' não está instalado ou não está no PATH do sistema.")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Erro ao listar arquivos Restic: {e.stderr}")
            raise

    def _list_kopia_files(self, repo: Dict, snapshot_id: str, path: str) -> List[Dict]:
        """Lista arquivos REAIS de um snapshot Kopia"""
        kopia = get_engine_path_or_raise('kopia')
        # Obter diretório de configuração (prioriza configurações existentes do backup)
        config_path, is_temporary = self._get_kopia_config_dir(repo, "ls")

        env = os.environ.copy()
        env['KOPIA_CONFIG_PATH'] = os.path.dirname(config_path)
        env['KOPIA_PASSWORD'] = self._get_password(repo)

        try:
            # 1. Conectar
            connect_cmd = [kopia, 'repository', 'connect', '--config-file', config_path]
            if repo['type'] == 'local':
                connect_cmd.extend(['filesystem', '--path', repo['path']])
            elif repo['type'] == 'b2':
                connect_cmd.extend([
                    'b2', 
                    '--bucket', repo.get('bucket', ''),
                    '--key-id', repo.get('b2_account_id', '') or repo.get('access_key', ''),
                    '--key', repo.get('b2_account_key', '') or repo.get('secret_key', '')
                ])
            elif repo['type'] in ('s3', 'wasabi'):
                connect_cmd.extend(self._build_kopia_s3_args(repo))

            subprocess.run(connect_cmd, env=env, capture_output=True, text=True, check=True, timeout=60)

            # 2. Listar arquivos
            # Kopia usa object IDs para navegar em subdiretórios.
            # Para a raiz, usamos o snapshot_id. Para subdiretórios, 
            # precisamos navegar passo a passo pelos object IDs.
            target = snapshot_id
            if path and path != '/':
                # Navegar pelo caminho usando object IDs
                path_parts = [p for p in path.split('/') if p]
                current_target = snapshot_id

                for part in path_parts:
                    # Listar o diretório atual para encontrar o object_id do próximo nível
                    nav_cmd = [kopia, 'ls', '-l', current_target, '--config-file', config_path]
                    nav_result = subprocess.run(
                        nav_cmd, env=env, capture_output=True, text=True, check=True, timeout=60
                    )

                    found = False
                    for nav_line in nav_result.stdout.splitlines():
                        nav_line = nav_line.strip()
                        if not nav_line:
                            continue
                        nav_parts = nav_line.split(None, 6)
                        if len(nav_parts) >= 7:
                            nav_name = nav_parts[6].rstrip('/')
                            if nav_name == part and nav_parts[0].startswith('d'):
                                current_target = nav_parts[5]  # object_id
                                found = True
                                break

                    if not found:
                        raise ValueError(f"Diretório '{part}' não encontrado no caminho '{path}'")

                target = current_target
            
            # Usar kopia ls -l para obter formato detalhado
            # Formato: mode  size  date  time  tz  objectid  name[/]
            cmd = [kopia, 'ls', '-l', target, '--config-file', config_path]
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=60
            )

            files = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue

                parts = line.split(None, 6)
                if len(parts) < 7:
                    # Linha com formato inesperado, tentar nome simples
                    name = line.rstrip('/')
                    is_dir = line.endswith('/')
                    name = name.rstrip('/')

                    if name:
                        files.append({
                            'name': name,
                            'path': f"{path.rstrip('/')}/{name}",
                            'type': 'dir' if is_dir else 'file',
                            'is_dir': is_dir,
                            'size': 0,
                            'mtime': '',
                            'object_id': ''
                        })
                    continue

                mode = parts[0]
                size = int(parts[1]) if parts[1].isdigit() else 0
                date_str = parts[2]
                time_str = parts[3]
                object_id = parts[5]
                name = parts[6].rstrip('/')
                is_dir = mode.startswith('d')

                files.append({
                    'name': name,
                    'path': f"{path.rstrip('/')}/{name}",
                    'type': 'dir' if is_dir else 'file',
                    'is_dir': is_dir,
                    'size': size,
                    'mtime': f"{date_str} {time_str}",
                    'object_id': object_id
                })
            return files
            
        except Exception as e:
            logger.error(f"❌ Erro ao listar arquivos Kopia: {e}")
            raise
        finally:
            if is_temporary:
                shutil.rmtree(os.path.dirname(config_path), ignore_errors=True)
    
    def restore_files(
        self,
        repository_id: int,
        snapshot_id: str,
        files: List[str],
        target_path: str,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Restaura arquivos REAIS de um snapshot
        """
        logger.info(f"🔄 Restaurando {len(files)} arquivos do snapshot {snapshot_id}")
        
        restore_options = {
            'overwrite': options.get('overwrite', False) if options else False,
            'preserve_permissions': options.get('preserve_permissions', True) if options else True,
        }
        
        repo = self._load_repository(repository_id)
        if not repo:
            raise ValueError(f"Repositório {repository_id} não encontrado durante a restauração.")

        try:
            engine = repo.get('engine', 'restic')
            
            if engine == 'restic':
                return self._restore_restic_files(repo, snapshot_id, files, target_path, restore_options)
            elif engine == 'kopia':
                return self._restore_kopia_files(repo, snapshot_id, files, target_path, restore_options)
            elif engine == 'duplicati':
                return self._restore_duplicati_files(repo, snapshot_id, files, target_path, restore_options)
            elif engine == 'gboc_native':
                return self._restore_native_files(repo, snapshot_id, files, target_path, restore_options)
            else:
                raise ValueError(f"Engine '{engine}' não suportado para restauração")
            
        except Exception as e:
            logger.error(f"❌ Erro ao restaurar arquivos: {e}", exc_info=True)
            # Retornar um dicionário de erro padronizado
            return {
                'status': 'failed',
                'engine': repo.get('engine', 'unknown'),
                'snapshot_id': snapshot_id,
                'error_message': str(e),
                'target_path': target_path,
                'timestamp': datetime.now().isoformat()
            }

    def _restore_native_files(
        self,
        repo: Dict,
        snapshot_id: str,
        files: List[str],
        target_path: str,
        options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Restaura arquivos usando o motor GBOC Native."""
        logger.info(f"Restaurando arquivos via motor nativo para snapshot '{snapshot_id}'")
        if not self.core or not hasattr(self.core, 'repository_manager'):
            raise RuntimeError("RepositoryManager não está disponível no core.")

        from native_engine.engine import GBOCNativeEngine

        backend = self.core.repository_manager.get_backend(repo['id'])
        # A task_config aqui é um mock, pois o motor só precisa dos detalhes do repositório
        engine = GBOCNativeEngine(task_config={'repository': repo}, storage_backend=backend)

        # O restore do motor nativo pode não precisar da lista de 'files' se ele restaura o snapshot inteiro
        restore_config = {
            'snapshot_id': snapshot_id,
            'destination_path': target_path,
            'files': files,
            'options': options
        }
        
        result = engine.run_restore(restore_config)

        # Adaptar o resultado para o formato esperado pelo worker
        if result["success"]:
            return {
                'status': 'success',
                'engine': 'gboc_native',
                'snapshot_id': snapshot_id,
                'files_restored': result.get('restored', len(files)),
                'bytes_restored': result.get('bytes_restored', 0),
                'target_path': target_path,
                'timestamp': datetime.now().isoformat()
            }
        else:
            return {
                'status': 'failed',
                'engine': 'gboc_native',
                'snapshot_id': snapshot_id,
                'error_message': result.get("error", "Falha no restore nativo"),
                'target_path': target_path,
                'timestamp': datetime.now().isoformat()
            }
    
    def _restore_restic_files(
        self,
        repo: Dict,
        snapshot_id: str,
        files: List[str],
        target_path: str,
        options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Restaura arquivos REAIS com Restic"""
        restic = get_engine_path_or_raise('restic')
        env = os.environ.copy()
        env['RESTIC_REPOSITORY'] = repo.get('path', '')
        env['RESTIC_PASSWORD'] = self._get_password(repo)

        repo_type = repo.get('type', 'local')
        if repo_type == 'b2':
            env['RESTIC_REPOSITORY'] = f"b2:{repo['path']}"
            env['B2_ACCOUNT_ID'] = repo.get('b2_account_id', '')
            env['B2_ACCOUNT_KEY'] = repo.get('b2_account_key', '')
        elif repo_type in ('s3', 'wasabi'):
            env['AWS_ACCESS_KEY_ID'] = repo.get('aws_access_key', '')
            env['AWS_SECRET_ACCESS_KEY'] = repo.get('aws_secret_key', '')
            if repo_type == 'wasabi':
                endpoint = self._get_wasabi_endpoint(repo)
                env['RESTIC_REPOSITORY'] = f"s3:{endpoint}/{repo['path']}"
            elif repo_type == 's3':
                env['RESTIC_REPOSITORY'] = f"s3:s3.amazonaws.com/{repo['path']}"

        # Criar diretório de destino
        os.makedirs(target_path, exist_ok=True)

        # Comando de restauração
        cmd = [
            restic, 'restore', snapshot_id,
            '--target', target_path,
            '--json'
        ]
        
        # Adicionar opções de restauração
        if options.get('overwrite'):
            cmd.append('--overwrite')
        if not options.get('preserve_permissions', True):
            cmd.append('--no-restore-permissions')
        if options.get('restore_ownership'):
            cmd.append('--restore-owner')
        
        # Adicionar includes para arquivos específicos
        for file_path in files:
            cmd.extend(['--include', file_path])
        
        import time
        start_time = time.time()
        
        try:
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )
            
            duration = time.time() - start_time
            
            # Parsear resultado
            stats = {
                'files_restored': 0,
                'bytes_restored': 0
            }
            
            for line in result.stdout.splitlines():
                try:
                    event = json.loads(line)
                    if event.get('message_type') == 'summary':
                        stats['files_restored'] = event.get('files_restored', 0)
                        stats['bytes_restored'] = event.get('total_bytes', 0)
                except:
                    continue
            
            return {
                'status': 'success',
                'engine': 'restic',
                'snapshot_id': snapshot_id,
                'files_restored': stats['files_restored'],
                'bytes_restored': stats['bytes_restored'],
                'duration_seconds': duration,
                'target_path': target_path,
                'timestamp': datetime.now().isoformat()
            }
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Erro na restauração Restic: {e.stderr}")
            return {
                'status': 'failed',
                'engine': 'restic',
                'snapshot_id': snapshot_id,
                'error_message': e.stderr,
                'target_path': target_path,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"❌ Erro inesperado na restauração Restic: {e}")
            return {
                'status': 'failed',
                'engine': 'restic',
                'snapshot_id': snapshot_id,
                'error_message': str(e),
                'target_path': target_path,
                'timestamp': datetime.now().isoformat()
            }
    
    def _restore_kopia_files(
        self,
        repo: Dict,
        snapshot_id: str,
        files: List[str],
        target_path: str,
        options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Restaura arquivos REAIS com Kopia"""
        kopia = get_engine_path_or_raise('kopia')
        # Obter diretório de configuração (prioriza configurações existentes do backup)
        config_path, is_temporary = self._get_kopia_config_dir(repo, "restore")

        env = os.environ.copy()
        env['KOPIA_CONFIG_PATH'] = os.path.dirname(config_path)
        env['KOPIA_PASSWORD'] = self._get_password(repo)

        os.makedirs(target_path, exist_ok=True)

        import time
        start_time = time.time()
        files_restored = 0
        bytes_restored = 0
        errors = []

        try:
            # 1. Conectar
            connect_cmd = [kopia, 'repository', 'connect', '--config-file', config_path]
            if repo['type'] == 'local':
                connect_cmd.extend(['filesystem', '--path', repo.get('path', '')])
            elif repo['type'] == 'b2':
                connect_cmd.extend([
                    'b2', 
                    '--bucket', repo.get('bucket', ''),
                    '--key-id', repo.get('b2_account_id', '') or repo.get('access_key', ''),
                    '--key', repo.get('b2_account_key', '') or repo.get('secret_key', '')
                ])
            elif repo['type'] in ('s3', 'wasabi'):
                connect_cmd.extend(self._build_kopia_s3_args(repo))

            subprocess.run(connect_cmd, env=env, capture_output=True, check=True)

            # 2. Restaurar arquivos
            for file_path in files:
                cmd = [
                    kopia, 'restore',
                    f"{snapshot_id}:{file_path}",
                    target_path
                ]
                
                # Adicionar opções de restauração
                if options.get('overwrite'):
                    cmd.append('--overwrite')
                if not options.get('preserve_permissions', True):
                    cmd.append('--no-set-modification-time')
                if options.get('restore_ownership'):
                    cmd.append('--preserve-ownership')
                
                try:
                    result = subprocess.run(
                        cmd,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    files_restored += 1
                except subprocess.CalledProcessError as e:
                    error_msg = f"Erro em {file_path}: {e.stderr}"
                    logger.error(f"❌ {error_msg}")
                    errors.append(error_msg)
        except Exception as e:
            logger.error(f"❌ Erro fatal na conexão/restauração Kopia: {e}")
            errors.append(str(e))
        finally:
            # Limpar configuração temporária (não limpar configurações compartilhadas do backup)
            if is_temporary:
                shutil.rmtree(os.path.dirname(config_path), ignore_errors=True)
        
        duration = time.time() - start_time
        
        status = 'success'
        if not files_restored:
            status = 'failed'
        elif errors:
            status = 'partial'
            
        return {
            'status': status,
            'engine': 'kopia',
            'snapshot_id': snapshot_id,
            'files_restored': files_restored,
            'bytes_restored': bytes_restored,
            'duration_seconds': duration,
            'target_path': target_path,
            'error_message': "; ".join(errors) if errors else None,
            'timestamp': datetime.now().isoformat()
        }
    
    def _restore_duplicati_files(
        self,
        repo: Dict,
        snapshot_id: str,
        files: List[str],
        target_path: str,
        options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Restaura arquivos REAIS com Duplicati"""
        try:
            import subprocess

            dup_exe = self._get_duplicati_exe()

            # Configurar diretório de DB local
            db_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "duplicati_dbs")
            os.makedirs(db_dir, exist_ok=True)
            local_db = os.path.join(db_dir, f"repo_{repo['id']}.sqlite")

            target_url = self._build_duplicati_url(repo)
            cli_args = self._build_duplicati_cli_args(repo)

            cmd = [
                dup_exe,
                "restore",
                target_url,
                f"--dbpath={local_db}",
                f"--restore-path={target_path}",
                "--disable-module=console-log-output",
                "--log-level=information",
                *cli_args,
                *files
            ]

            logger.info(f"Executando restore Duplicati: {' '.join(cmd[:3])}...")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            try:
                stdout, stderr = process.communicate(timeout=86400)
            except subprocess.TimeoutExpired:
                process.terminate()
                return {
                    'status': 'failed',
                    'engine': 'duplicati',
                    'snapshot_id': snapshot_id,
                    'error_message': 'Timeout: Duplicati restore process took too long and was terminated.',
                    'target_path': target_path,
                    'timestamp': datetime.now().isoformat()
                }

            logger.info(f"Duplicati stdout: {stdout}")
            if stderr:
                logger.warning(f"Duplicati stderr: {stderr}")

            if process.returncode == 0:
                # Contar arquivos restaurados
                files_restored = len(files)
                bytes_restored = 0

                # Calcular tamanho dos arquivos
                for file_path in files:
                    full_path = os.path.join(target_path, file_path)
                    if os.path.exists(full_path):
                        if os.path.isfile(full_path):
                            bytes_restored += os.path.getsize(full_path)
                        else:
                            for root, dirs, filenames in os.walk(full_path):
                                bytes_restored += sum(os.path.getsize(os.path.join(root, f)) for f in filenames)

                return {
                    'status': 'success',
                    'engine': 'duplicati',
                    'snapshot_id': snapshot_id,
                    'files_restored': files_restored,
                    'bytes_restored': bytes_restored,
                    'target_path': target_path,
                    'timestamp': datetime.now().isoformat()
                }
            else:
                return {
                    'status': 'failed',
                    'engine': 'duplicati',
                    'snapshot_id': snapshot_id,
                    'error_message': stderr or 'Erro desconhecido no Duplicati',
                    'target_path': target_path,
                    'timestamp': datetime.now().isoformat()
                }

        except Exception as e:
            logger.error(f"Erro no restore Duplicati: {e}")
            return {"success": False, "error": str(e)}
    
    def _build_duplicati_url(self, repo: Dict, password: str = None) -> str:
        """Constrói URL de storage para Duplicati usando campos do banco de dados"""
        repo_type = repo.get('type', 'local').lower()

        if repo_type == 'local':
            return f"file://{repo.get('path', '/backups')}"
        elif repo_type == 'b2':
            app_id = repo.get('access_key') or repo.get('b2_account_id', '')
            bucket = repo.get('bucket') or repo.get('path', '')
            if not bucket:
                raise ValueError("B2: Bucket obrigatório")
            return f"b2://{bucket}"
        elif repo_type == 's3':
            bucket = repo.get('bucket') or repo.get('path', '')
            endpoint = repo.get('endpoint', '')
            region = repo.get('region', 'us-east-1')
            prefix = repo.get('prefix', '')
            if not bucket:
                raise ValueError("S3: Bucket obrigatório")
            server = endpoint or f"s3.{region}.amazonaws.com"
            url_path = f"{bucket}/{prefix}" if prefix else bucket
            return f"s3://{url_path}"
        elif repo_type == 'wasabi':
            bucket = repo.get('bucket') or repo.get('path', '')
            endpoint = repo.get('endpoint', '')
            region = repo.get('region', 'us-east-1')
            prefix = repo.get('prefix', '')
            if not bucket:
                raise ValueError("Wasabi: Bucket obrigatório")
            url_path = f"{bucket}/{prefix}" if prefix else bucket
            return f"s3://{url_path}"
        elif repo_type == 'azure':
            account = repo.get('access_key') or repo.get('azure_account_name', '')
            container = repo.get('bucket') or repo.get('path', '')
            if not all([account, container]):
                raise ValueError("Azure: Account e Container obrigatórios")
            return f"azure://{container}"
        else:
            raise ValueError(f"Storage type '{repo_type}' não suportado para Duplicati")
    
    def _load_repository(self, repo_id: int) -> Optional[Dict]:
        """Carrega repositório do banco"""
        logger.info(f"🔍 Carregando repositório ID: {repo_id}")
        db = self._get_db()
        try:
            if hasattr(db, '__enter__'):
                # É um context manager (recomendado)
                with db as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT * FROM repositories WHERE id = %s",
                        (repo_id,)
                    )
                    row = cursor.fetchone()
                    if row:
                        columns = [desc[0] for desc in cursor.description]
                        repo = dict(zip(columns, row))
                    else:
                        logger.warning(f"❌ Repositório ID {repo_id} não encontrado no banco")
                        return None
            else:
                # Conexão direta SQLite (fallback)
                cursor = db.cursor()
                cursor.execute(
                    "SELECT * FROM repositories WHERE id = ?",
                    (repo_id,)
                )
                row = cursor.fetchone()
                if row:
                    repo = dict(row)
                else:
                    logger.warning(f"❌ Repositório ID {repo_id} não encontrado no banco")
                    return None

            # Extrair credenciais do config JSON para o nível superior
            config_str = repo.get('config')
            if config_str:
                try:
                    config = json.loads(config_str) if isinstance(config_str, str) else config_str
                    for field in ['bucket', 'region', 'endpoint', 'prefix', 'access_key', 'secret_key',
                                  'aws_access_key', 'aws_secret_key', 'b2_account_id', 'b2_account_key',
                                  'azure_account_name', 'azure_account_key']:
                        if field in config and config[field] and (field not in repo or not repo.get(field)):
                            repo[field] = config[field]
                except (json.JSONDecodeError, TypeError):
                    pass

            logger.info(f"✅ Repositório encontrado: {repo.get('name', 'N/A')}")
            return repo
        except Exception as e:
            logger.error(f"❌ Erro ao carregar repositório {repo_id}: {e}", exc_info=True)
            return None

    def get_restore_status(self, restore_id: int) -> Dict[str, Any]:
        """Obtém status de uma restauração."""
        db = self._get_db()
        sql = "SELECT * FROM restore_history WHERE id = %s"

        row = None
        if hasattr(db, '__enter__'):
            with db as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (restore_id,))
                row = cursor.fetchone()
        else:
            cursor = db.cursor()
            cursor.execute(sql, (restore_id,))
            row = cursor.fetchone()

        if row:
            columns = [desc[0] for desc in cursor.description]
            data = dict(zip(columns, row))
            total_files = data.get('total_files') or 0
            restored = data.get('files_restored') or 0
            if total_files > 0:
                data['progress'] = int(min(100, round((restored / total_files) * 100)))
            else:
                data['progress'] = 100 if data.get('status') in ('success', 'completed') else 0
            if data.get('status') == 'success':
                data['status'] = 'completed'
            active = self.active_restores.get(restore_id) or {}
            if active.get('status') == 'success':
                data['status'] = 'completed'
            if active.get('progress'):
                data['progress'] = max(data.get('progress', 0), active.get('progress', 0))
            data['logs'] = active.get('logs', [])
            return data
        return None

    def get_recovery_status(self, restore_id: int) -> Optional[Dict[str, Any]]:
        """
        Alias para get_restore_status para compatibilidade com a API.
        Obtém o status de uma operação de restauração.
        """
        return self.get_restore_status(restore_id)

    # Deprecated or internal use mostly now
    def _record_restore(self, repo_id: int, snapshot_id: str, result: Dict):
        """Registra restauração no banco"""
        try:
            db = self._get_db()
            if hasattr(db, '__enter__'):
                with db as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO restore_history (
                            repository_id,
                            snapshot_id,
                            status,
                            files_restored,
                            bytes_restored,
                            duration_seconds,
                            target_path,
                            created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        repo_id,
                        snapshot_id,
                        result.get('status', 'unknown'),
                        result.get('files_restored', 0),
                        result.get('bytes_restored', 0),
                        result.get('duration_seconds', 0),
                        result.get('target_path', ''),
                        datetime.now().isoformat()
                    ))
                    conn.commit()
            else:
                cursor = db.cursor()
                cursor.execute("""
                    INSERT INTO restore_history (
                        repository_id,
                        snapshot_id,
                        status,
                        files_restored,
                        bytes_restored,
                        duration_seconds,
                        target_path,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    repo_id,
                    snapshot_id,
                    result.get('status', 'unknown'),
                    result.get('files_restored', 0),
                    result.get('bytes_restored', 0),
                    result.get('duration_seconds', 0),
                    result.get('target_path', ''),
                    datetime.now().isoformat()
                ))
                db.commit()
            logger.info(f"✅ Restauração registrada")
        except Exception as e:
            logger.error(f"❌ Erro ao registrar restauração: {e}")
