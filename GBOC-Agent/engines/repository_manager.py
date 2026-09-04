#!/usr/bin/env python3
"""
GBOC Agent 14.0.0 - Repository Manager
Refatorado para usar backends de armazenamento modulares.
"""

import psycopg2
import logging
import os
import shutil
import json
import subprocess
import contextlib
import time
import tempfile
from datetime import datetime
from typing import List, Optional, Dict, Any
from engines.engine_paths import get_engine_path

# Imports dos novos backends
from storage_backends.base import StorageBackend
from storage_backends.local import LocalStorageBackend
from storage_backends.cloud import CloudStorageBackend
import psycopg2.extras


logger = logging.getLogger(__name__)


class RepositoryManager:
    def __init__(self, core):
        self.core = core
        logger.info("✅ RepositoryManager (v2) inicializado")

    def initialize_repository(self, repo_data: Dict[str, Any]) -> Dict[str, Any]:
        """Inicializa um novo repositório ou valida sua criação."""
        return self.create_repository(repo_data)

    def test_connection(self, repo_id_or_data: Any) -> Dict[str, Any]:
        """Testa conexão com um repositório por ID ou dicionário de configuração."""
        if isinstance(repo_id_or_data, dict):
            return self.validate_connection(repo_id_or_data)
        return self.validate_connection({"id": repo_id_or_data})

    def _get_conn(self):
        """Obtém uma conexão de banco de dados do pool do core."""
        return self.core.get_db_connection()

    def _normalize_repository_config(self, repo_config: Dict[str, Any]) -> Dict[str, Any]:
        """Expande config JSON para o nível superior."""
        if not repo_config:
            return repo_config

        normalized = dict(repo_config)
        raw_config = normalized.get('config')
        if raw_config:
            try:
                config = json.loads(raw_config) if isinstance(raw_config, str) else raw_config
                if isinstance(config, dict):
                    for key, value in config.items():
                        if value is not None and (key not in normalized or not normalized.get(key)):
                            normalized[key] = value
            except Exception:
                pass

        # Uniformizar todos os campos de senha possíveis para evitar falha de recuperação
        p = (
            normalized.get('motor_password') or 
            normalized.get('encryption_password') or 
            normalized.get('password') or 
            normalized.get('cloud_password') or 
            ''
        )
        if p:
            if 'motor_password' not in normalized or not normalized.get('motor_password'):
                normalized['motor_password'] = p
            if 'cloud_password' not in normalized or not normalized.get('cloud_password'):
                normalized['cloud_password'] = p
            if 'encryption_password' not in normalized or not normalized.get('encryption_password'):
                normalized['encryption_password'] = p
            if 'password' not in normalized or not normalized.get('password'):
                normalized['password'] = p

        return normalized

    def get_backend(self, repo_id: int) -> StorageBackend:
        """
        Factory method para obter o backend de armazenamento correto para um repositório.
        """
        repo_config = self.get_repository(repo_id)
        if not repo_config:
            raise ValueError(f"Repositório com ID {repo_id} não encontrado.")
        
        return self._create_backend_from_config(repo_config)

    def _create_backend_from_config(self, repo_config: Dict[str, Any]) -> StorageBackend:
        """Cria uma instância de backend a partir de um dicionário de configuração."""
        repo_config = self._normalize_repository_config(repo_config)
        repo_type = repo_config.get('type', 'local').lower()

        if repo_type == 'local':
            return LocalStorageBackend(repo_config)
        elif repo_type in ['cloud', 'b2', 's3', 'wasabi', 'azure', 'gcs']:
            if repo_type == 'cloud':
                if repo_config.get('b2_account_id'):
                    repo_config['type'] = 'b2'
                elif repo_config.get('aws_access_key') or repo_config.get('access_key'):
                    repo_config['type'] = 's3'
                elif repo_config.get('azure_account_name'):
                    repo_config['type'] = 'azure'
                elif repo_config.get('gcs_project_id'):
                    repo_config['type'] = 'gcs'
                else:
                    repo_config['type'] = 's3'
            return CloudStorageBackend(repo_config)
        else:
            raise ValueError(f"Tipo de repositório desconhecido ou não suportado: '{repo_type}'")

    # ==========================================================================
    # CRUD Operations
    # ==========================================================================

    def list_repositories(self) -> List[Dict[str, Any]]:
        """Lista todos os repositórios"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT * FROM repositories ORDER BY name ASC")
                rows = cursor.fetchall()
                return [self._normalize_repository_config(row) for row in rows]
        except Exception as e:
            logger.error(f"Erro ao listar repositórios: {e}")
            return []

    def get_repository(self, repo_id: int) -> Optional[Dict[str, Any]]:
        """Obtém um repositório pelo ID"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT * FROM repositories WHERE id = %s", (repo_id,))
                repo = cursor.fetchone()
                return self._normalize_repository_config(repo) if repo else None
        except Exception as e:
            logger.error(f"Erro ao buscar repositório {repo_id}: {e}")
            return None

    def create_repository(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cria um novo repositório no banco de dados e testa a conexão do backend.
        Novo modelo: determina tipo baseado no engine ou provedores.
        Persiste o provider específico (b2/s3/wasabi/azure) em vez de 'cloud' genérico.
        """
        name = data.get('name', '').strip()
        if not name:
            raise ValueError("Nome do repositório é obrigatório")

        engine = data.get('engine', 'restic').lower()

        # Determina tipo priorizando valor enviado pelo frontend
        requested_type = (data.get('type') or data.get('repo_type') or 'local').lower()

        if requested_type in ['local', 'b2', 's3', 'wasabi', 'azure', 'gcs', 'cloud']:
            repo_type = requested_type
        else:
            # Fallback de detecção por campos
            if data.get('b2_account_id'):
                repo_type = 'b2'
            elif data.get('aws_access_key') or data.get('access_key'):
                repo_type = 's3'
            elif data.get('azure_account_name'):
                repo_type = 'azure'
            elif data.get('gcs_project_id'):
                repo_type = 'gcs'
            else:
                repo_type = 'local'

        # Se vier como cloud genérico, mapear para provider específico quando possível
        if repo_type == 'cloud':
            if data.get('b2_account_id'):
                repo_type = 'b2'
            elif data.get('azure_account_name'):
                repo_type = 'azure'
            elif data.get('gcs_project_id'):
                repo_type = 'gcs'
            else:
                repo_type = 's3'

        if not data.get('motor_password'):
            raise ValueError("Senha do motor é obrigatória")

        # Configura o path
        path = ""
        if repo_type == "local":
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
            path = os.path.join(self.core.repo_dir, engine, safe_name)
            os.makedirs(path, exist_ok=True)

            if os.name == 'nt':
                self._secure_windows_directory(path)

            data['path'] = path
        else:
            path = data.get('bucket') or data.get('path', '')
            data['path'] = path

        # Garante que o tipo no dicionário data corresponda ao tipo calculado
        data['type'] = repo_type

        # Testa a conexão ANTES de salvar no banco
        initial_status = 'ready'
        initial_initialized = True
        try:
            if repo_type == 'local':
                # Repositório local: testar via backend de armazenamento
                backend = self._create_backend_from_config(data)
                conn_test = backend.check_connection()
                if not conn_test["success"]:
                    raise ConnectionError(f"Falha no teste de conexão: {conn_test['error']}")
            elif engine == 'gboc_native':
                # gboc_native cloud: testar via CloudStorageBackend (sem validação de motor CLI)
                backend = self._create_backend_from_config(data)
                conn_test = backend.check_connection()
                if not conn_test["success"]:
                    raise ConnectionError(conn_test.get('error') or 'Falha no teste de conexão cloud')
            else:
                # Restic / Kopia / Duplicati cloud: validar motor + autenticação + init se necessário
                if not self._is_engine_installed(engine):
                    logger.warning(f"⚠️ Motor '{engine}' não instalado. Repositório '{name}' salvo como pending_validation.")
                    initial_status = 'pending_validation'
                    initial_initialized = False
                else:
                    engine_test = self._test_local_engine_connection(data, None)
                    if not engine_test.get('success'):
                        err_msg = engine_test.get('details') or engine_test.get('error') or 'Falha no teste de conexão'
                        raise ConnectionError(err_msg)
        except ImportError as e:
            # Não bloquear criação quando falta driver cloud localmente
            err_text = str(e).lower()
            if repo_type != 'local' and ('libcloud' in err_text or 'apache libcloud' in err_text):
                logger.warning(f"⚠️ Libcloud ausente. Repositório '{name}' será salvo para configuração posterior: {e}")
                initial_status = 'pending_validation'
                initial_initialized = False
            else:
                logger.error(f"Falha ao pré-validar backend para o novo repositório '{name}': {e}")
                raise
        except (ValueError, ConnectionError) as e:
            logger.error(f"Falha ao pré-validar backend para o novo repositório '{name}': {e}")
            raise

        # Insere no banco
        now = datetime.now().isoformat()
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                config_data = {
                    'bucket': data.get('bucket'),
                    'region': data.get('region'),
                    'endpoint': data.get('endpoint'),
                    'prefix': data.get('prefix'),
                    'access_key': data.get('access_key') or data.get('aws_access_key') or data.get('b2_account_id'),
                    'secret_key': data.get('secret_key') or data.get('aws_secret_key') or data.get('b2_account_key'),
                    'aws_access_key': data.get('aws_access_key') or data.get('access_key'),
                    'aws_secret_key': data.get('aws_secret_key') or data.get('secret_key'),
                    'b2_account_id': data.get('b2_account_id') or data.get('access_key'),
                    'b2_account_key': data.get('b2_account_key') or data.get('secret_key'),
                    'azure_account_name': data.get('azure_account_name') or data.get('access_key'),
                    'azure_account_key': data.get('azure_account_key') or data.get('secret_key')
                }
                
                sql = """
                    INSERT INTO repositories 
                    (name, type, engine, path, motor_password, cloud_password, config, status, enabled, initialized, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s, %s)
                    RETURNING id;
                """
                values = (
                    name, repo_type, engine, path, data.get('motor_password'),
                    data.get('motor_password'),  # cloud_password = motor_password (mesma senha de criptografia)
                    json.dumps({k: v for k, v in config_data.items() if v}),
                    initial_status, initial_initialized,
                    now, now
                )
                cursor.execute(sql, values)
                repo_id = cursor.fetchone()[0]
                conn.commit()

                logger.info(f"✅ Repositório '{name}' criado com ID: {repo_id}")
                return {"id": repo_id, "path": path}

        except psycopg2.IntegrityError:
            raise ValueError(f"Já existe um repositório com o nome '{name}'")
        except Exception as e:
            logger.error(f"Erro ao criar repositório no banco: {e}", exc_info=True)
            raise

    def update_repository(self, repo_id: int, data: Dict[str, Any]) -> bool:
        """Atualiza um repositório."""
        current_repo = self.get_repository(repo_id)
        if not current_repo:
            raise ValueError(f"Repositório {repo_id} não encontrado.")

        updates = []
        values = []
        
        config_str = current_repo.get('config', '{}')
        config_data = json.loads(config_str) if isinstance(config_str, str) else config_str or {}

        for key in ['bucket', 'region', 'endpoint', 'prefix', 'access_key', 'secret_key']:
            if key in data:
                config_data[key] = data[key]

        # Sincronizar aliases de credenciais para manter config consistente
        if 'access_key' in data:
            for alias in ['aws_access_key', 'b2_account_id', 'azure_account_name']:
                if alias in config_data:
                    config_data[alias] = data['access_key']
        if 'secret_key' in data:
            for alias in ['aws_secret_key', 'b2_account_key', 'azure_account_key']:
                if alias in config_data:
                    config_data[alias] = data['secret_key']

        allowed_fields = ['name', 'type', 'engine', 'path', 'motor_password', 'cloud_password', 'enabled']
        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                values.append(data[field])

        updates.append("config = %s")
        values.append(json.dumps({k: v for k, v in config_data.items() if v is not None and v != ''}))
        
        updates.append("updated_at = %s")
        values.append(datetime.now().isoformat())

        if not updates:
            return True

        sql = f"UPDATE repositories SET {', '.join(updates)} WHERE id = %s"
        values.append(repo_id)

        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, tuple(values))
                conn.commit()
            logger.info(f"✅ Repositório {repo_id} atualizado.")
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar repositório {repo_id}: {e}", exc_info=True)
            raise

    def _safe_delete_by_repository(self, cursor, table_name: str, repo_id: int):
        """Remove dependências por repository_id, ignorando schemas legados sem a tabela."""
        try:
            cursor.execute(f"DELETE FROM {table_name} WHERE repository_id = %s", (repo_id,))
        except Exception as e:
            # Compatibilidade com instalações legadas onde a tabela pode não existir
            msg = str(e).lower()
            if 'does not exist' in msg or 'undefined table' in msg:
                return
            raise

    def _cleanup_engine_artifacts(self, repo: Dict[str, Any]) -> None:
        """Remove artefatos locais de motores relacionados ao repositório excluído."""
        try:
            # Limpeza de configs temporárias/persistidas do Kopia usadas em tasks/restore
            # data/kopia_configs/task_*.config
            config_dir = os.path.join(self.core.base_dir, 'data', 'kopia_configs')
            if os.path.isdir(config_dir):
                removed = 0
                repo_path = str(repo.get('path', '') or '')
                repo_bucket = str(repo.get('bucket', '') or '')
                repo_endpoint = str(repo.get('endpoint', '') or '')

                for fname in os.listdir(config_dir):
                    if not fname.endswith('.config'):
                        continue
                    fpath = os.path.join(config_dir, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            cfg = json.load(f)

                        storage_cfg = ((cfg.get('storage') or {}).get('config') or {})
                        bucket = str(storage_cfg.get('bucket', '') or '')
                        path = str(storage_cfg.get('path', '') or '')
                        endpoint = str(storage_cfg.get('endpoint', '') or '')

                        is_same = False
                        if repo_path and path and os.path.normcase(path) == os.path.normcase(repo_path):
                            is_same = True
                        if repo_bucket and bucket and bucket == repo_bucket:
                            is_same = True
                        if repo_endpoint and endpoint and endpoint == repo_endpoint and (repo_bucket and bucket == repo_bucket):
                            is_same = True

                        if is_same:
                            os.remove(fpath)
                            removed += 1
                    except Exception:
                        # Não bloquear exclusão por falha em arquivo auxiliar
                        continue

                if removed:
                    logger.info(f"✅ Artefatos Kopia removidos: {removed} arquivo(s)")
        except Exception as e:
            logger.warning(f"⚠️ Falha ao limpar artefatos de motores: {e}")

    def delete_repository(self, repo_id: int, keep_folder: bool = False) -> None:
        """Exclui repositório e todos os dados associados."""
        repo = self.get_repository(repo_id)
        if not repo:
            raise ValueError(f"Repositório {repo_id} não encontrado")

        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()

                # Dependências diretas por repository_id (ordem importa)
                self._safe_delete_by_repository(cursor, 'integrity_checks', repo_id)
                self._safe_delete_by_repository(cursor, 'restore_history', repo_id)

                # Tarefas associadas
                cursor.execute("DELETE FROM tasks WHERE repository_id = %s", (repo_id,))

                # Repositório
                cursor.execute("DELETE FROM repositories WHERE id = %s", (repo_id,))
                conn.commit()
            logger.info(f"✅ Repositório {repo_id} e dependências removidos do banco.")

            # Limpeza de artefatos de motores (ex.: Kopia configs)
            self._cleanup_engine_artifacts(repo)

            # Limpeza de diretório local (quando aplicável)
            if not keep_folder and repo.get('type') == 'local':
                backend = self._create_backend_from_config(repo)
                base_path = getattr(backend, 'base_path', None)
                if base_path and os.path.isdir(base_path):
                    shutil.rmtree(base_path, ignore_errors=True)
                    logger.info(f"✅ Pasta do repositório local removida: {base_path}")

        except Exception as e:
            logger.error(f"Erro ao excluir repositório {repo_id}: {e}", exc_info=True)
            raise
            
    # ==========================================================================
    # Validação
    # ==========================================================================

    def test_repository_connection(self, repo_data: Dict) -> Dict:
        """
        Testa a conexão de um repositório usando o backend apropriado.
        Suporta testes específicos para LOCAL (motores) e CLOUD (provedores).
        """
        try:
            repo_type = repo_data.get('type', 'local').lower()
            engine = repo_data.get('engine', 'restic').lower()

            # Preencher dados mínimos para o backend
            if 'path' not in repo_data and 'bucket' in repo_data:
                repo_data['path'] = repo_data['bucket']

            backend = self._create_backend_from_config(repo_data)

            if repo_type == 'local':
                # Teste específico para motores locais
                return self._test_local_engine_connection(repo_data, backend)
            else:
                # Para cloud e tipos específicos, usar o backend de nuvem
                return backend.check_connection()

        except Exception as e:
            logger.error(f"Falha ao testar conexão para '{repo_data.get('name')}': {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _test_local_engine_connection(self, repo_data: Dict, backend: StorageBackend) -> Dict:
        """
        Testa conexão específica para motores locais (kopia, restic, duplicati).
        Verifica se o motor está instalado e consegue acessar o repositório.
        """
        try:
            engine = repo_data.get('engine', 'restic').lower()

            # Verificar se o motor está instalado
            if not self._is_engine_installed(engine):
                return {
                    "success": False,
                    "error": f"Motor '{engine}' não está instalado no sistema",
                    "details": f"Verifique se {engine} está instalado e acessível para o agente"
                }

            # Para motores locais, testar se consegue inicializar ou acessar o repositório
            if engine == 'kopia':
                return self._test_kopia_connection(repo_data)
            elif engine == 'restic':
                return self._test_restic_connection(repo_data)
            elif engine == 'duplicati':
                return self._test_duplicati_connection(repo_data)
            elif engine == 'gboc_native':
                if backend is None:
                    backend = self._create_backend_from_config(repo_data)
                return backend.check_connection()
            else:
                # Fallback para teste genérico do backend
                if backend is None:
                    backend = self._create_backend_from_config(repo_data)
                return backend.check_connection()

        except Exception as e:
            return {
                "success": False,
                "error": f"Erro no teste de conexão do motor local: {str(e)}",
                "details": "Verifique as configurações do repositório e credenciais"
            }

    def _is_engine_installed(self, engine: str) -> bool:
        """Verifica se um motor está acessível para o agente."""
        if engine == 'gboc_native':
            return True
        return bool(get_engine_path(engine))

    def _test_restic_connection(self, repo_data: Dict[str, Any]) -> Dict[str, Any]:
        auth = self._validate_restic_auth(repo_data, allow_init=True)
        if auth.get('valid'):
            return {"success": True, "message": "Conexão Restic válida"}
        return {
            "success": False,
            "error": auth.get('error', 'restic_validation_failed'),
            "details": auth.get('message', 'Falha na validação Restic')
        }

    def _test_kopia_connection(self, repo_data: Dict[str, Any]) -> Dict[str, Any]:
        auth = self._validate_kopia_connection(repo_data)
        if auth.get('valid'):
            return {"success": True, "message": "Conexão Kopia válida"}
        return {
            "success": False,
            "error": auth.get('error', 'kopia_validation_failed'),
            "details": auth.get('message', 'Falha na validação Kopia')
        }

    def _build_duplicati_url(self, repo: Dict[str, Any]) -> str:
        repo_type = str(repo.get('type', 'local')).lower()
        repo_path = str(repo.get('path') or repo.get('bucket') or '')
        prefix = str(repo.get('prefix') or '').strip('/')

        if repo_type == 'local':
            if not repo_path:
                raise ValueError("Caminho local não configurado")
            return f"file://{repo_path}"
        if repo_type == 'b2':
            if not repo_path:
                raise ValueError("Bucket B2 não configurado")
            url_path = f"{repo_path}/{prefix}" if prefix else repo_path
            return f"b2://{url_path}"
        if repo_type in ('s3', 'wasabi'):
            if not repo_path:
                raise ValueError("Bucket S3/Wasabi não configurado")
            url_path = f"{repo_path}/{prefix}" if prefix else repo_path
            return f"s3://{url_path}"
        if repo_type == 'azure':
            if not repo_path:
                raise ValueError("Container Azure não configurado")
            url_path = f"{repo_path}/{prefix}" if prefix else repo_path
            return f"azure://{url_path}"

        raise ValueError(f"Tipo de repositório Duplicati não suportado: {repo_type}")

    def _build_duplicati_auth_args(self, repo: Dict[str, Any]) -> list[str]:
        repo_type = str(repo.get('type', 'local')).lower()
        args: list[str] = []

        password = self._get_repo_password(repo)
        if password:
            args.append(f"--passphrase={password}")

        if repo_type in ('s3', 'wasabi'):
            access_key = str(repo.get('aws_access_key') or repo.get('access_key') or '')
            secret_key = str(repo.get('aws_secret_key') or repo.get('secret_key') or '')
            endpoint = str(repo.get('endpoint') or '').strip()
            region = str(repo.get('region') or '').strip()

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
            account_id = str(repo.get('b2_account_id') or repo.get('access_key') or '')
            account_key = str(repo.get('b2_account_key') or repo.get('secret_key') or '')
            if account_id:
                args.append(f"--b2-accountid={account_id}")
            if account_key:
                args.append(f"--b2-applicationkey={account_key}")

        elif repo_type == 'azure':
            account_name = str(repo.get('azure_account_name') or repo.get('access_key') or '')
            account_key = str(repo.get('azure_account_key') or repo.get('secret_key') or '')
            if account_name:
                args.append(f"--azure-account-name={account_name}")
            if account_key:
                args.append(f"--azure-accesskey={account_key}")

        return args

    def _test_duplicati_connection(self, repo_data: Dict[str, Any]) -> Dict[str, Any]:
        """Teste leve de conexão Duplicati via CLI mantendo UX unificada."""
        try:
            dup_exe = get_engine_path('duplicati')
            if not dup_exe:
                return {
                    "success": False,
                    "error": "duplicati_not_found",
                    "details": "Duplicati não encontrado no sistema"
                }

            repo = self._normalize_repository_config(repo_data or {})
            target_url = self._build_duplicati_url(repo)
            auth_args = self._build_duplicati_auth_args(repo)

            cmd = [dup_exe, 'find', target_url, *auth_args, '--no-encryption=true']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                # Tentar novamente sem --no-encryption para repositórios com passphrase
                cmd2 = [dup_exe, 'find', target_url, *auth_args]
                result = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)

            if result.returncode == 0:
                return {"success": True, "message": "Conexão Duplicati válida"}

            err = (result.stderr or result.stdout or '').strip()
            return {
                "success": False,
                "error": "duplicati_connection_failed",
                "details": err or "Falha ao validar conexão Duplicati"
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "duplicati_timeout",
                "details": "Timeout ao testar conexão Duplicati"
            }
        except Exception as e:
            return {
                "success": False,
                "error": "duplicati_exception",
                "details": str(e)
            }

    def _get_repo_password(self, repo_config: Dict[str, Any]) -> str:
        # motor_password é a senha de criptografia do repositório para todos os motores
        # (Restic, Kopia, Duplicati) independente de ser local ou cloud.
        # access_key/secret_key são as credenciais de acesso ao provedor cloud — não são senhas do motor.
        return str(repo_config.get('motor_password') or '')

    def _validate_kopia_connection(self, repo_config: Dict[str, Any], allow_init: bool = False) -> Dict[str, Any]:
        """Valida conexão real do Kopia com repositório usando config temporária."""
        try:
            kopia = get_engine_path('kopia')
            if not kopia:
                return {
                    "valid": False,
                    "message": "Kopia não encontrado no sistema. Verifique se o Kopia foi instalado e se o caminho foi detectado corretamente.",
                    "error": "kopia_not_found",
                    "error_source": "engine"
                }
            repo = self._normalize_repository_config(repo_config or {})
            repo_type = str(repo.get('type', 'local')).lower()
            password = self._get_repo_password(repo)
            if not password:
                return {"valid": False, "message": "Senha Kopia não configurada", "error": "kopia_password_missing", "error_source": "engine"}

            with tempfile.TemporaryDirectory(prefix='gboc_kopia_test_') as tmp:
                config_path = os.path.join(tmp, 'kopia.config')
                env = os.environ.copy()
                env['KOPIA_PASSWORD'] = password

                connect_cmd = [kopia, 'repository', 'connect', '--config-file', config_path]
                if repo_type == 'local':
                    path = str(repo.get('path') or '')
                    if not path:
                        return {"valid": False, "message": "Caminho local não configurado", "error": "kopia_path_missing", "error_source": "repository"}
                    connect_cmd.extend(['filesystem', '--path', path])
                elif repo_type == 'b2':
                    bucket = str(repo.get('bucket') or repo.get('path') or '')
                    key_id = str(repo.get('b2_account_id') or repo.get('access_key') or '')
                    key = str(repo.get('b2_account_key') or repo.get('secret_key') or '')
                    if not bucket or not key_id or not key:
                        return {"valid": False, "message": "Bucket/credenciais B2 incompletos", "error": "kopia_b2_config_invalid", "error_source": "cloud"}
                    connect_cmd.extend(['b2', '--bucket', bucket, '--key-id', key_id, '--key', key])
                elif repo_type in ('s3', 'wasabi'):
                    bucket = str(repo.get('bucket') or repo.get('path') or '')
                    access_key = str(repo.get('aws_access_key') or repo.get('access_key') or '')
                    secret_key = str(repo.get('aws_secret_key') or repo.get('secret_key') or '')
                    region = str(repo.get('region') or 'us-east-1')
                    if not bucket or not access_key or not secret_key:
                        return {"valid": False, "message": "Bucket/credenciais S3/Wasabi incompletos", "error": "kopia_s3_config_invalid", "error_source": "cloud"}
                    connect_cmd.extend(['s3', '--bucket', bucket, '--access-key', access_key, '--secret-access-key', secret_key, '--region', region])
                    endpoint = str(repo.get('endpoint') or '').strip()
                    if repo_type == 'wasabi':
                        endpoint = endpoint or f"s3.{region}.wasabisys.com"
                    if endpoint:
                        connect_cmd.extend(['--endpoint', endpoint])
                    prefix = str(repo.get('prefix') or '').strip()
                    if prefix:
                        if not prefix.endswith('/'):
                            prefix += '/'
                        connect_cmd.extend(['--prefix', prefix])
                else:
                    return {"valid": False, "message": f"Tipo '{repo_type}' não suportado para validação Kopia", "error": "kopia_type_unsupported", "error_source": "engine"}

                c = subprocess.run(connect_cmd, env=env, capture_output=True, text=True, timeout=60)
                if c.returncode != 0:
                    stderr_low = (c.stderr or c.stdout or '').lower()
                    not_found = ('repository not found' in stderr_low or 'invalid config' in stderr_low
                                 or 'no such file' in stderr_low or 'does not exist' in stderr_low
                                 or 'not initialized' in stderr_low or 'object does not exist' in stderr_low)
                    if not_found and allow_init:
                        # Tentar criar (init) o repositório
                        create_cmd = list(connect_cmd)
                        idx = create_cmd.index('connect') if 'connect' in create_cmd else -1
                        if idx >= 0:
                            create_cmd[idx] = 'create'
                        init_result = subprocess.run(create_cmd, env=env, capture_output=True, text=True, timeout=120)
                        if init_result.returncode == 0:
                            return {"valid": True}
                        init_low = (init_result.stderr or init_result.stdout or '').lower()
                        if 'already exists' in init_low or 'already initialized' in init_low:
                            return {"valid": True}
                        return {
                            "valid": False,
                            "message": f"Falha ao inicializar repositório Kopia: {(init_result.stderr or '').strip()}",
                            "error": "kopia_init_failed",
                            "error_source": "repository"
                        }
                    msg = (c.stderr or c.stdout or '').strip() or 'Falha ao conectar Kopia'
                    return {"valid": False, "message": msg, "error": "kopia_connect_failed", "error_source": "engine"}

                s = subprocess.run([kopia, 'repository', 'status', '--config-file', config_path], env=env, capture_output=True, text=True, timeout=30)
                if s.returncode != 0:
                    msg = (s.stderr or s.stdout or '').strip() or 'Falha no status do repositório Kopia'
                    return {"valid": False, "message": msg, "error": "kopia_status_failed", "error_source": "engine"}

                return {"valid": True}
        except subprocess.TimeoutExpired:
            return {"valid": False, "message": "Timeout na validação Kopia", "error": "kopia_timeout", "error_source": "engine"}
        except FileNotFoundError:
            return {
                "valid": False,
                "message": "Executável do Kopia não encontrado. Instale o Kopia ou corrija o caminho detectado pelo sistema.",
                "error": "kopia_not_found",
                "error_source": "engine"
            }
        except Exception as e:
            return {
                "valid": False,
                "message": f"Erro no teste Kopia: {str(e)}",
                "error": "kopia_exception",
                "error_source": "engine"
            }

    def _build_restic_repo_and_env(self, repo_config: Dict[str, Any], allow_init: bool = False):
        """Monta RESTIC_REPOSITORY e variáveis de ambiente para validar autenticação."""
        repo = self._normalize_repository_config(repo_config or {})
        env = os.environ.copy()

        repo_type = str(repo.get('type', 'local')).lower()
        repo_path = str(repo.get('path') or '')
        motor_password = str(repo.get('motor_password') or '')

        # motor_password é a senha de criptografia do repositório Restic,
        # tanto para repositórios locais quanto para repositórios cloud.
        # As credenciais de acesso ao provedor cloud (AWS keys, etc.) são campos separados.
        password = motor_password
        if not password:
            return None, env, "Senha do repositório não configurada (motor_password)", False

        env['RESTIC_PASSWORD'] = password

        if repo_type == 'local':
            if not repo_path:
                return None, env, "Caminho do repositório local não configurado", False
            return repo_path, env, None, False

        bucket = str(repo.get('bucket') or repo_path or '')
        prefix = str(repo.get('prefix') or '').strip('/')
        endpoint = str(repo.get('endpoint') or '').strip()
        region = str(repo.get('region') or '').strip()

        aws_access = str(repo.get('aws_access_key') or repo.get('access_key') or '')
        aws_secret = str(repo.get('aws_secret_key') or repo.get('secret_key') or '')
        b2_id = str(repo.get('b2_account_id') or repo.get('access_key') or '')
        b2_key = str(repo.get('b2_account_key') or repo.get('secret_key') or '')

        if repo_type in ('s3', 'wasabi'):
            if not bucket:
                return None, env, "Bucket não configurado", False
            if not aws_access or not aws_secret:
                return None, env, "Credenciais AWS/Wasabi não configuradas", False
            env['AWS_ACCESS_KEY_ID'] = aws_access
            env['AWS_SECRET_ACCESS_KEY'] = aws_secret
            if region:
                env['AWS_DEFAULT_REGION'] = region
            path_suffix = f"/{bucket}{('/' + prefix) if prefix else ''}"
            repo_arg = f"s3:{endpoint}{path_suffix}" if endpoint else f"s3:s3.amazonaws.com{path_suffix}"
            return repo_arg, env, None, bool(allow_init)

        if repo_type == 'b2':
            if not bucket:
                return None, env, "Bucket B2 não configurado", False
            if not b2_id or not b2_key:
                return None, env, "Credenciais B2 não configuradas", False
            env['B2_ACCOUNT_ID'] = b2_id
            env['B2_ACCOUNT_KEY'] = b2_key
            repo_arg = f"b2:{bucket}{('/' + prefix) if prefix else ''}"
            return repo_arg, env, None, bool(allow_init)

        return None, env, f"Tipo de repositório '{repo_type}' não suportado para validação Restic", False

    def _validate_restic_auth(self, repo_config: Dict[str, Any], allow_init: bool = False) -> Dict[str, Any]:
        """Valida autenticação real do Restic no repositório."""
        try:
            restic = get_engine_path('restic') or 'restic'
            repo_arg, env, prep_error, can_init = self._build_restic_repo_and_env(repo_config, allow_init=allow_init)
            if prep_error:
                return {"valid": False, "message": prep_error, "error": "restic_config_invalid", "error_source": "engine"}

            cmd = [restic, 'snapshots', '-r', repo_arg]
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=45)
            if result.returncode == 0:
                return {"valid": True}

            stderr = (result.stderr or '').strip()
            stdout = (result.stdout or '').strip()
            low = stderr.lower()
            # Logar o stderr real para diagnóstico
            logger.warning(f"restic snapshots falhou (rc={result.returncode}): {stderr[:500]}")

            # Padrões que indicam credenciais de nuvem (AWS/Wasabi/B2/Azure) inválidas — NÃO tentar init
            cloud_auth_failed = any(p in low for p in (
                'invalidaccesskeyid',
                'invalidsecret',
                'invalid access key',
                'invalid secret',
                'signaturedoesnotmatch',
                'signature',
                'authorizationfailed',
                'requesttimestamptoolarge',
                'access denied',
                'forbidden',
                'invalid credentials',
            ))

            # Padrões de senha do repositório Restic errada (camada de criptografia)
            restic_wrong_password = any(p in low for p in (
                'wrong password',
                'no key found',
                'incorrect password',
            ))

            # Padrões que indicam repositório/bucket não existe ou não está inicializado
            not_found = any(p in low for p in (
                'unable to open config file',
                'specified key does not exist',
                'is there a repository at the following location',
                'nosuchbucket',
                'no such bucket',
                'the specified bucket does not exist',
                'no such key',
                'not exist',
                'not found',
                'could not find',
                'failed to stat',
                'no config file',
                'repository does not exist',
                'failed to get object',
            ))

            auth_failed = cloud_auth_failed or restic_wrong_password

            # Para repos cloud com allow_init: tentar init sempre que não há erro
            # explícito de credenciais de NUVEM (S3/B2/Azure). "wrong password/no key found"
            # em cloud pode significar apenas que o repositório ainda não foi inicializado
            # (bucket vazio) e não que a senha do Restic está errada.
            if can_init and not cloud_auth_failed:
                init_cmd = [restic, 'init', '-r', repo_arg]
                init_result = subprocess.run(init_cmd, env=env, capture_output=True, text=True, timeout=60)
                logger.debug(f"restic init stderr (rc={init_result.returncode}): {(init_result.stderr or '')[:300]}")
                if init_result.returncode == 0:
                    return {"valid": True, "message": "Repositório Restic inicializado com sucesso"}
                init_low = (init_result.stderr or '').lower()
                if 'already exists' in init_low or 'already initialized' in init_low or 'config file already exists' in init_low:
                    return {"valid": True, "message": "Repositório Restic já existia — conectado com sucesso"}
                # Se init falhou com erro de credenciais de nuvem
                init_cloud_fail = any(p in init_low for p in ('access denied', 'forbidden', 'invalidaccesskeyid', 'signaturedoesnotmatch', 'authorizationfailed'))
                init_wrong_pwd = any(p in init_low for p in ('wrong password', 'no key found'))
                if init_cloud_fail:
                    return {
                        "valid": False,
                        "message": f"Credenciais de nuvem inválidas ao inicializar repositório: {(init_result.stderr or '').strip()[:200]}",
                        "error": "restic_auth_failed",
                        "error_source": "engine"
                    }
                if init_wrong_pwd:
                    return {
                        "valid": False,
                        "message": "Senha do repositório Restic incorreta ao inicializar",
                        "error": "restic_auth_failed",
                        "error_source": "engine"
                    }
                return {
                    "valid": False,
                    "message": f"Falha ao inicializar repositório Restic: {(init_result.stderr or '').strip()[:300]}",
                    "error": "restic_init_failed",
                    "error_source": "repository"
                }

            if auth_failed:
                if cloud_auth_failed:
                    return {
                        "valid": False,
                        "message": f"Credenciais de nuvem inválidas (acesso negado ao bucket/storage): {stderr[:200]}",
                        "error": "restic_auth_failed",
                        "error_source": "engine"
                    }
                if restic_wrong_password:
                    return {
                        "valid": False,
                        "message": "Senha do repositório Restic incorreta (wrong password or no key found)",
                        "error": "restic_auth_failed",
                        "error_source": "engine"
                    }
            if not_found:
                return {
                    "valid": False,
                    "message": "Repositório Restic não encontrado no caminho/prefix informado",
                    "error": "restic_repository_not_found",
                    "error_source": "repository"
                }
            return {
                "valid": False,
                "message": f"Falha na validação Restic: {stderr or 'erro desconhecido'}",
                "error": "restic_validation_failed",
                "error_source": "engine"
            }
        except subprocess.TimeoutExpired:
            return {"valid": False, "message": "Timeout ao validar autenticação Restic", "error": "restic_timeout", "error_source": "engine"}
        except Exception as e:
            return {"valid": False, "message": f"Erro no teste Restic: {str(e)}", "error": "restic_exception", "error_source": "engine"}

    def validate_repository_connection(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Testa conexão com repositório a partir de dados de configuração (sem salvar). Se a senha for deixada em branco, recupera do repositório correspondente salvo no sistema."""
        try:
            cfg = dict(data or {})
            engine = str(cfg.get("engine", "restic")).lower()
            repo_type = str(cfg.get("type") or cfg.get("repo_type") or "local").lower()

            # Se repo_id foi fornecido ou campos essenciais estão faltando, busca no repositório salvo
            repo_id = cfg.get("repo_id") or cfg.get("id")
            has_password = bool(cfg.get("motor_password") or cfg.get("password") or cfg.get("encryption_password"))
            has_path_or_bucket = bool(cfg.get("path") or cfg.get("bucket"))
            has_access_key = bool(cfg.get("access_key") or cfg.get("aws_access_key") or cfg.get("b2_account_id"))

            if repo_id or not has_password or not has_path_or_bucket or (repo_type != 'local' and not has_access_key):
                matched_repo = None
                if repo_id:
                    try:
                        matched_repo = self.get_repository(int(repo_id))
                    except Exception:
                        pass
                if not matched_repo:
                    saved_repos = self.list_repositories() or []
                    for r in saved_repos:
                        if str(r.get("engine", "")).lower() == engine:
                            if repo_type == 'local' and str(r.get("type", "local")).lower() == 'local':
                                matched_repo = r
                                break
                            elif repo_type != 'local' and str(r.get("type", "")).lower() == repo_type:
                                b_cfg = cfg.get("bucket") or cfg.get("path")
                                b_r = r.get("bucket") or r.get("path")
                                if not b_cfg or b_cfg == b_r:
                                    matched_repo = r
                                    break
                    if not matched_repo and saved_repos:
                        for r in saved_repos:
                            if str(r.get("engine", "")).lower() == engine:
                                matched_repo = r
                                break

                if matched_repo:
                    norm_matched = self._normalize_repository_config(matched_repo)
                    if not cfg.get("repo_id") and matched_repo.get("id"):
                        cfg["repo_id"] = matched_repo.get("id")
                    if not has_password:
                        saved_pw = norm_matched.get("motor_password") or norm_matched.get("encryption_password") or norm_matched.get("password")
                        if saved_pw:
                            cfg["motor_password"] = saved_pw
                            cfg["password"] = saved_pw
                    if not cfg.get("path") and (norm_matched.get("path") or norm_matched.get("bucket")):
                        cfg["path"] = norm_matched.get("path") or norm_matched.get("bucket")
                    if not cfg.get("bucket") and (norm_matched.get("bucket") or norm_matched.get("path")):
                        cfg["bucket"] = norm_matched.get("bucket") or norm_matched.get("path")
                    if not cfg.get("access_key") and norm_matched.get("access_key"):
                        cfg["access_key"] = norm_matched.get("access_key")
                    if not cfg.get("secret_key") and norm_matched.get("secret_key"):
                        cfg["secret_key"] = norm_matched.get("secret_key")
                    if not cfg.get("region") and norm_matched.get("region"):
                        cfg["region"] = norm_matched.get("region")
                    if not cfg.get("endpoint") and norm_matched.get("endpoint"):
                        cfg["endpoint"] = norm_matched.get("endpoint")
                    if not cfg.get("prefix") and norm_matched.get("prefix"):
                        cfg["prefix"] = norm_matched.get("prefix")

            return self._build_connection_diagnostics(cfg)
        except Exception as e:
            engine = str(data.get("engine", "restic")).lower()
            repo_type = str(data.get("type") or data.get("repo_type") or "local").lower()
            return {
                "valid": False,
                "engine": engine,
                "repo_type": repo_type,
                "connection_tested": True,
                "connection_ok": False,
                "auth_ok": False,
                "error": str(e),
                "details": {},
                "diagnostics": {
                    "local": {"checked": True, "ok": False, "kind": "local_engine", "elapsed_ms": 0, "message": str(e)},
                    "secondary": {"checked": repo_type != 'local', "ok": False if repo_type != 'local' else True, "kind": "cloud_repository" if repo_type != 'local' else "not_applicable", "elapsed_ms": 0, "message": "N/A" if repo_type == 'local' else str(e)},
                    "auth": {"checked": engine in ('restic', 'kopia'), "ok": False, "kind": f"{engine}_auth", "elapsed_ms": 0, "message": "Erro interno"},
                    "total_elapsed_ms": 0
                }
            }

    def validate_connection(self, repo_id: int) -> Dict[str, Any]:
        """Valida conexão de um repositório e retorna diagnóstico detalhado."""
        try:
            repo_config = self.get_repository(repo_id)
            if not repo_config:
                return {
                    "valid": False,
                    "message": "Repositório não encontrado",
                    "error": "not_found"
                }

            result = self._build_connection_diagnostics(repo_config)
            result["repo_id"] = repo_id
            return result

        except Exception as e:
            logger.error(f"Erro ao validar repositório {repo_id}: {e}")
            repo_type = 'local'
            try:
                repo_config = self.get_repository(repo_id) or {}
                repo_type = str(repo_config.get('type', 'local')).lower()
            except Exception:
                pass
            backend_kind = 'cloud' if repo_type != 'local' else 'engine'
            return {
                "valid": False,
                "message": str(e),
                "error": "exception",
                "error_source": backend_kind,
                "connection_ok": False,
                "auth_ok": False,
                "diagnostics": {
                    "local": {"checked": True, "ok": False, "kind": "local_engine", "elapsed_ms": 0, "message": str(e)},
                    "secondary": {"checked": repo_type != 'local', "ok": False if repo_type != 'local' else True, "kind": "cloud_repository" if repo_type != 'local' else "not_applicable", "elapsed_ms": 0, "message": "N/A" if repo_type == 'local' else str(e)},
                    "auth": {"checked": False, "ok": False, "kind": "not_applicable", "elapsed_ms": 0, "message": "Erro interno"},
                    "total_elapsed_ms": 0
                }
            }

    def _build_connection_diagnostics(self, repo_config: Dict[str, Any]) -> Dict[str, Any]:
        repo = self._normalize_repository_config(repo_config or {})
        repo_type = str(repo.get('type', 'local')).lower()
        engine = str(repo.get('engine', 'restic')).lower()
        start_total = time.perf_counter()

        local_stage = {"checked": True, "ok": True, "kind": "local_repository" if repo_type == 'local' else "local_engine", "elapsed_ms": 0, "message": ""}
        secondary_stage = {"checked": repo_type != 'local', "ok": True if repo_type == 'local' else False, "kind": "cloud_repository" if repo_type != 'local' else "not_applicable", "elapsed_ms": 0, "message": "N/A" if repo_type == 'local' else ""}
        auth_stage = {"checked": engine in ('restic', 'kopia'), "ok": True, "kind": f"{engine}_auth" if engine in ('restic', 'kopia') else "not_applicable", "elapsed_ms": 0, "message": "N/A" if engine not in ('restic', 'kopia') else ""}

        # 1) Checagem local (engine instalado / acessível)
        t0 = time.perf_counter()
        if repo_type != 'local':
            if engine == 'gboc_native':
                local_ok = True
                local_msg = 'Engine GBOC Native disponível'
            else:
                engine_path = get_engine_path(engine)
                local_ok = bool(engine_path)
                local_msg = f"Engine '{engine}' disponível em {engine_path}" if local_ok else f"Engine '{engine}' não encontrada no sistema"
            local_stage["ok"] = local_ok
            local_stage["message"] = local_msg
        local_stage["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # 2) Checagem do repositório (local ou secundário em nuvem)
        backend_ok = False
        backend_error = None
        backend_source = 'engine'
        t1 = time.perf_counter()
        try:
            backend = self._create_backend_from_config(repo)
            conn_result = backend.check_connection()
            backend_ok = bool(conn_result.get('success'))
            backend_error = conn_result.get('error')
            backend_msg = conn_result.get('message', '')
        except Exception as e:
            conn_result = {"success": False, "message": str(e), "error": "connection_exception"}
            backend_ok = False
            backend_error = "connection_exception"
            backend_msg = str(e)
        elapsed_backend = round((time.perf_counter() - t1) * 1000, 2)

        if repo_type == 'local':
            local_stage["ok"] = backend_ok
            local_stage["elapsed_ms"] = round(local_stage["elapsed_ms"] + elapsed_backend, 2)
            local_stage["message"] = backend_msg
        else:
            secondary_stage["ok"] = backend_ok
            secondary_stage["elapsed_ms"] = elapsed_backend
            secondary_stage["message"] = backend_msg
            backend_source = 'cloud'

        # 3) Autenticação por engine
        auth_ok = True
        auth_error = None
        auth_source = 'engine'
        if auth_stage["checked"] and backend_ok and local_stage["ok"]:
            t2 = time.perf_counter()
            # Validação padrão NÃO deve inicializar repositório implicitamente.
            # A inicialização explícita é feita pelo endpoint /initialize.
            if engine == 'restic':
                auth = self._validate_restic_auth(repo, allow_init=False)
            else:
                auth = self._validate_kopia_connection(repo, allow_init=False)
            auth_stage["elapsed_ms"] = round((time.perf_counter() - t2) * 1000, 2)
            auth_ok = bool(auth.get('valid'))
            auth_error = auth.get('error')
            auth_stage["ok"] = auth_ok
            auth_stage["message"] = auth.get('message', 'OK' if auth_ok else 'Falha de autenticação')
            auth_source = auth.get('error_source', 'engine')

        total_elapsed_ms = round((time.perf_counter() - start_total) * 1000, 2)
        valid = bool(local_stage["ok"] and (secondary_stage["ok"] if secondary_stage["checked"] else True) and auth_ok)

        if valid:
            msg = "Conexão validada (local e secundário)" if secondary_stage["checked"] else "Conexão validada (repositório local)"
            err = None
            err_source = None
        else:
            if not local_stage["ok"]:
                msg = local_stage["message"] or "Falha na verificação local"
                err = "local_connection_failed"
                err_source = 'engine' if repo_type != 'local' else 'repository'
            elif secondary_stage["checked"] and not secondary_stage["ok"]:
                msg = secondary_stage["message"] or "Falha na conexão secundária (nuvem)"
                err = backend_error or "secondary_connection_failed"
                err_source = backend_source
            elif not auth_ok:
                msg = auth_stage["message"] or "Falha de autenticação"
                err = auth_error or "auth_failed"
                err_source = auth_source
            else:
                msg = "Falha na validação"
                err = "validation_failed"
                err_source = 'engine'

        return {
            "valid": valid,
            "message": msg,
            "error": err,
            "error_source": err_source,
            "connection_ok": bool(local_stage["ok"] and (secondary_stage["ok"] if secondary_stage["checked"] else True)),
            "auth_ok": auth_ok,
            "engine": engine,
            "repo_type": repo_type,
            "diagnostics": {
                "local": local_stage,
                "secondary": secondary_stage,
                "auth": auth_stage,
                "total_elapsed_ms": total_elapsed_ms
            }
        }

    def validate_engines(self) -> Dict[str, Dict[str, Any]]:
        """Valida todos os motores de backup conhecidos e retorna status detalhado."""
        from engines.engine_paths import detect_all_engines, get_engine_path
        results = {}
        for info in detect_all_engines():
            name = info["name"]
            path = info.get("path")
            installed = info.get("detected", False)
            version = None
            error = None

            if installed and path:
                try:
                    out = subprocess.run(
                        [path, "version"],
                        capture_output=True, text=True, timeout=10
                    )
                    version = out.stdout.strip() if out.returncode == 0 else None
                except Exception:
                    pass

            results[name] = {
                "name": name.capitalize(),
                "installed": installed,
                "available": installed,
                "version": version,
                "path": path,
                "source": info.get("source"),
                "error": error,
            }

        # gboc_native sempre disponível
        results["gboc_native"] = {
            "name": "GBOC Native",
            "installed": True,
            "available": True,
            "version": "built-in",
            "path": None,
            "error": None,
        }
        return results

    def validate_engine(self, engine_name: str) -> Dict[str, Any]:
        """Valida um motor específico pelo nome."""
        all_results = self.validate_engines()
        if engine_name in all_results:
            return all_results[engine_name]

        from engines.engine_paths import get_engine_path
        path = get_engine_path(engine_name)
        installed = path is not None
        version = None

        if installed and path:
            try:
                out = subprocess.run([path, "version"], capture_output=True, text=True, timeout=10)
                version = out.stdout.strip() if out.returncode == 0 else None
            except Exception:
                pass

        return {
            "name": engine_name.capitalize(),
            "installed": installed,
            "available": installed,
            "version": version,
            "path": path,
            "error": None if installed else f"Motor '{engine_name}' não encontrado",
        }

    def get_engine_validation_report(self) -> str:
        """Gera relatório completo de validação de motores usando o EngineValidator."""
        from engines.engine_validator import EngineValidator
        validator = EngineValidator()
        return validator.get_validation_report()

