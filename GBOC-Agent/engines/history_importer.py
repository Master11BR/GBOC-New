#!/usr/bin/env python3
"""
📥 GBOC Agent - Importador de Histórico COMPLETO
Importa TODO o histórico de backups de Restic, Kopia e Duplicati
Analisa snapshots, estatísticas, erros e sucessos
"""

import subprocess
import json
import logging
import sqlite3
from datetime import datetime
from typing import Dict, List, Any, Optional
import os
import platform
import shutil

logger = logging.getLogger(__name__)


class HistoryImporter:
    """
    Importa histórico completo de backups dos engines
    """
    
    def __init__(self, core_instance):
        self.core = core_instance
        self.stats = {
            'repositories_imported': 0,
            'snapshots_imported': 0,
            'errors_found': 0,
            'data_size_total': 0
        }
    
    def import_all_history(self) -> Dict[str, Any]:
        """
        Importa histórico de TODOS os repositórios configurados
        """
        logger.info("📥 Iniciando importação COMPLETA de histórico")
        
        result = {
            'status': 'success',
            'timestamp': datetime.now().isoformat(),
            'repositories': [],
            'statistics': {},
            'errors': []
        }
        
        try:
            # Buscar todos os repositórios no banco
            with self.core.get_db_connection() as conn:
                cursor = conn.execute("""
                    SELECT *
                    FROM repositories
                    ORDER BY id
                """)
                
                repositories = [dict(row) for row in cursor.fetchall()]
            
            logger.info(f"📊 Encontrados {len(repositories)} repositórios")
            
            # Importar histórico de cada repositório
            for repo in repositories:
                logger.info(f"📦 Importando: {repo['name']} ({repo['engine']})")
                
                try:
                    if repo['engine'] == 'restic':
                        repo_result = self._import_restic_history(repo)
                    elif repo['engine'] == 'kopia':
                        repo_result = self._import_kopia_history(repo)
                    elif repo['engine'] == 'duplicati':
                        repo_result = self._import_duplicati_history(repo)
                    else:
                        logger.warning(f"⚠️ Engine desconhecido: {repo['engine']}")
                        continue
                    
                    result['repositories'].append(repo_result)
                    self.stats['repositories_imported'] += 1
                    
                except Exception as e:
                    logger.error(f"❌ Erro ao importar {repo['name']}: {e}")
                    result['errors'].append({
                        'repository': repo['name'],
                        'engine': repo['engine'],
                        'error': str(e)
                    })
                    # Continuar mesmo com erro - não travar toda a importação
                    self.stats['errors_found'] += 1
            
            # Estatísticas finais
            result['statistics'] = self.stats
            
            logger.info(f"✅ Importação concluída: {self.stats}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Erro fatal na importação: {e}")
            return {
                'status': 'error',
                'message': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def _import_restic_history(self, repo: Dict) -> Dict[str, Any]:
        """
        Importa histórico COMPLETO do Restic
        """
        logger.info(f"📦 Restic: {repo['name']}")
        
        # Checar se o repositório e a senha existem
        password = None
        if repo.get('type') == 'local':
            password = repo.get('motor_password')
        else:
            # Para nuvem, priorizar cloud_password, mas usar motor_password como fallback
            password = repo.get('cloud_password')
            if not password:
                password = repo.get('motor_password')

        # Para repositórios na nuvem, usar bucket como path se não houver path
        repo_path = repo.get('path')
        if not repo_path and repo.get('type') != 'local':
            repo_path = repo.get('bucket')

        if not repo_path or not password:
            error_msg = f"Repositório Restic '{repo['name']}' não tem caminho ou senha configurado."
            logger.warning(f"  ⚠️ {error_msg}")
            return {
                'repository_id': repo['id'],
                'name': repo['name'],
                'engine': 'restic',
                'snapshots': [],
                'statistics': {},
                'errors': [error_msg]
            }

        # Preparar ambiente
        env = os.environ.copy()
        # Configurar formato do repositório
        if repo['type'] == 'local':
            env['RESTIC_REPOSITORY'] = repo_path
        else:
            # Para repositórios na nuvem, usar formato específico
            if repo['type'] == 'b2':
                bucket = repo.get('bucket', '')
                access_key = repo.get('access_key', '')
                secret_key = repo.get('secret_key', '')
                
                if bucket and access_key and secret_key:
                    env['RESTIC_REPOSITORY'] = f"b2:{bucket}"
                else:
                    error_msg = f"Repositório Restic '{repo['name']}' não tem todas as credenciais B2 configuradas"
                    logger.warning(f"  ⚠️ {error_msg}")
                    return {
                        'repository_id': repo['id'],
                        'name': repo['name'],
                        'engine': 'restic',
                        'snapshots': [],
                        'statistics': {},
                        'errors': [error_msg]
                    }
            elif repo['type'] == 's3':
                env['RESTIC_REPOSITORY'] = f"s3:{repo.get('bucket', '')}"
            else:
                # Para outros tipos, usar formato genérico
                env['RESTIC_REPOSITORY'] = f"{repo['type']}:{repo.get('bucket', '')}"
        env['RESTIC_PASSWORD'] = password
        
        # Configurar credenciais cloud
        if repo['type'] == 'b2':
            env['B2_ACCOUNT_ID'] = repo.get('access_key', '')
            env['B2_ACCOUNT_KEY'] = repo.get('secret_key', '')
        elif repo['type'] == 's3':
            env['AWS_ACCESS_KEY_ID'] = repo.get('access_key', '')
            env['AWS_SECRET_ACCESS_KEY'] = repo.get('secret_key', '')
        
        result = {
            'repository_id': repo['id'],
            'name': repo['name'],
            'engine': 'restic',
            'snapshots': [],
            'statistics': {},
            'errors': []
        }
        
        try:
            # 1. Listar todos os snapshots
            logger.info("  📋 Listando snapshots...")
            
            snapshots_result = subprocess.run(
                ['restic', 'snapshots', '--json'],
                env=env,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if snapshots_result.returncode != 0:
                raise Exception(f"Restic falhou: {snapshots_result.stderr}")
            
            snapshots = json.loads(snapshots_result.stdout)
            logger.info(f"  ✅ {len(snapshots)} snapshots encontrados")
            
            # 2. Importar cada snapshot
            for snapshot in snapshots:
                snap_data = self._process_restic_snapshot(repo, snapshot, env)
                result['snapshots'].append(snap_data)
                
                # Registrar no banco
                self._save_snapshot_to_db(repo['id'], snap_data)
                self.stats['snapshots_imported'] += 1
            
            # 3. Obter estatísticas globais
            logger.info("  📊 Obtendo estatísticas...")
            
            stats_result = subprocess.run(
                ['restic', 'stats', '--json'],
                env=env,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if stats_result.returncode == 0:
                stats = json.loads(stats_result.stdout)
                result['statistics'] = {
                    'total_size': stats.get('total_size', 0),
                    'total_file_count': stats.get('total_file_count', 0),
                    'snapshots_count': len(snapshots)
                }
                
                # Atualizar repositório no banco
                self._update_repository_stats(repo['id'], result['statistics'])
                self.stats['data_size_total'] += stats.get('total_size', 0)
            
            logger.info(f"  ✅ Repositório importado com sucesso")
            
        except subprocess.TimeoutExpired:
            error = "Timeout ao acessar repositório"
            logger.error(f"  ❌ {error}")
            result['errors'].append(error)
        except Exception as e:
            error = str(e)
            logger.error(f"  ❌ Erro: {error}")
            result['errors'].append(error)
            self.stats['errors_found'] += 1
        
        return result
    
    def _process_restic_snapshot(self, repo: Dict, snapshot: Dict, env: Dict) -> Dict:
        """
        Processa um snapshot do Restic e extrai informações
        """
        snap_data = {
            'snapshot_id': snapshot['short_id'],
            'full_id': snapshot['id'],
            'time': snapshot['time'],
            'hostname': snapshot['hostname'],
            'username': snapshot.get('username', ''),
            'paths': snapshot['paths'],
            'tags': snapshot.get('tags', []),
            'parent': snapshot.get('parent', ''),
            'tree': snapshot.get('tree', ''),
            'size': 0,
            'files_new': 0,
            'files_changed': 0,
            'files_unmodified': 0,
            'status': 'success'
        }
        
        # Tentar obter estatísticas do snapshot específico
        try:
            stats_cmd = ['restic', 'stats', snapshot['short_id'], '--json']
            stats_result = subprocess.run(
                stats_cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if stats_result.returncode == 0:
                stats = json.loads(stats_result.stdout)
                snap_data['size'] = stats.get('total_size', 0)
                snap_data['files_new'] = stats.get('total_file_count', 0)
        except:
            pass
        
        return snap_data
    
    def _import_kopia_history(self, repo: Dict) -> Dict[str, Any]:
        """
        Importa histórico COMPLETO do Kopia
        """
        logger.info(f"📦 Kopia: {repo['name']}")

        # Usar um diretório de configuração temporário para evitar conflitos
        config_dir = os.path.join(os.path.expanduser("~"), ".kopia", f"gboc_config_{repo['id']}")
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, "repository.config")
        
        env = os.environ.copy()
        env['KOPIA_CONFIG_PATH'] = config_file
        
        # CORREÇÃO: Lógica de senha robusta e consistente
        password = None
        if repo.get('type') == 'local':
            password = repo.get('motor_password')
        else:
            # Para nuvem, priorizar cloud_password, mas usar motor_password como fallback
            password = repo.get('cloud_password')
            if not password:
                password = repo.get('motor_password')

        # Para repositórios na nuvem, usar bucket como path se não houver path
        repo_path = repo.get('path')
        if not repo_path and repo.get('type') != 'local':
            repo_path = repo.get('bucket')

        if not password:
            error_msg = f"Repositório Kopia '{repo['name']}' não tem senha configurada."
            logger.warning(f"  ⚠️ {error_msg}")
            return { 'repository_id': repo['id'], 'name': repo['name'], 'engine': 'kopia', 'errors': [error_msg] }
        
        env['KOPIA_PASSWORD'] = password

        result = {
            'repository_id': repo['id'],
            'name': repo['name'],
            'engine': 'kopia',
            'snapshots': [],
            'statistics': {},
            'errors': []
        }

        try:
            # 1. Conectar ao repositório
            logger.info(f"  🔗 Conectando ao repositório Kopia: {repo_path}")
            
            connect_cmd = ['kopia', 'repository', 'connect']
            repo_type = repo.get('type', 'filesystem')

            if repo_type == 'local':
                connect_cmd.extend(['filesystem', '--path', repo_path])
            elif repo_type == 's3':
                # CORREÇÃO: Validar credenciais S3 antes de usar
                bucket = repo.get('bucket')
                access_key = repo.get('aws_access_key')
                secret_key = repo.get('aws_secret_key')
                endpoint = repo.get('endpoint', '') # Endpoint é opcional

                if not all([bucket, access_key, secret_key]):
                    error_msg = f"Repositório Kopia S3 '{repo['name']}' não tem todas as credenciais (bucket, access key, secret key) configuradas."
                    logger.warning(f"  ⚠️ {error_msg}")
                    return { 'repository_id': repo['id'], 'name': repo['name'], 'engine': 'kopia', 'errors': [error_msg], 'snapshots': [], 'statistics': {} }

                connect_cmd.extend([
                    's3',
                    '--bucket', bucket,
                    '--endpoint', endpoint,
                    '--access-key', access_key,
                    '--secret-access-key', secret_key
                ])
            elif repo_type == 'b2':
                bucket = repo.get('bucket', '')
                access_key = repo.get('access_key', '')
                secret_key = repo.get('secret_key', '')
                
                if bucket and access_key and secret_key:
                    connect_cmd.extend([
                        'b2',
                        '--bucket', bucket,
                        '--key-id', access_key,
                        '--key', secret_key
                    ])
                else:
                    error_msg = f"Repositório Kopia '{repo['name']}' não tem todas as credenciais B2 configuradas"
                    logger.warning(f"  ⚠️ {error_msg}")
                    return {
                        'repository_id': repo['id'],
                        'name': repo['name'],
                        'engine': 'kopia',
                        'snapshots': [],
                        'statistics': {},
                        'errors': [error_msg]
                    }
            else:
                raise Exception(f"Tipo de repositório Kopia não suportado: {repo_type}")

            connect_result = subprocess.run(
                connect_cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=120 # Timeout maior para conexão
            )

            if connect_result.returncode != 0:
                error_msg = f"Kopia (connect) falhou: {connect_result.stderr.strip()}"
                logger.warning(f"  ❌ {error_msg}")
                return {
                    'repository_id': repo['id'],
                    'name': repo['name'],
                    'engine': 'kopia',
                    'errors': [error_msg],
                    'snapshots': [],
                    'statistics': {}
                }

            logger.info("  ✅ Conectado com sucesso.")

            # 2. Listar snapshots
            logger.info("  📋 Listando snapshots...")
            
            snapshots_result = subprocess.run(
                ['kopia', 'snapshot', 'list', '--json'],
                env=env,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if snapshots_result.returncode != 0:
                raise Exception(f"Kopia (list) falhou: {snapshots_result.stderr}")
            
            snapshots = json.loads(snapshots_result.stdout)
            logger.info(f"  ✅ {len(snapshots)} snapshots encontrados")
            
            total_size = 0
            total_files = 0
            
            # 3. Processar cada snapshot
            for snapshot in snapshots:
                snap_data = {
                    'snapshot_id': snapshot['id'],
                    'full_id': snapshot['id'],
                    'time': snapshot['startTime'],
                    'hostname': snapshot.get('source', {}).get('host', ''),
                    'username': snapshot.get('source', {}).get('userName', ''),
                    'paths': [snapshot.get('source', {}).get('path', '')],
                    'size': snapshot.get('stats', {}).get('totalSize', 0),
                    'files_new': snapshot.get('stats', {}).get('totalFiles', 0),
                    'status': 'success' # Kopia não tem status por snapshot na listagem
                }
                
                result['snapshots'].append(snap_data)
                self._save_snapshot_to_db(repo['id'], snap_data)
                self.stats['snapshots_imported'] += 1
                
                total_size += snap_data['size']
                total_files += snap_data['files_new']
            
            # 4. Estatísticas
            result['statistics'] = {
                'total_size': total_size,
                'total_file_count': total_files,
                'snapshots_count': len(snapshots)
            }
            
            self._update_repository_stats(repo['id'], result['statistics'])
            self.stats['data_size_total'] += total_size
            
            logger.info(f"  ✅ Repositório importado com sucesso")
            
        except Exception as e:
            error = str(e)
            logger.error(f"  ❌ Erro: {error}")
            result['errors'].append(error)
            self.stats['errors_found'] += 1
        
        finally:
            # 5. Desconectar do repositório
            logger.info("  🔌 Desconectando do repositório Kopia...")
            subprocess.run(
                ['kopia', 'repository', 'disconnect'],
                env=env,
                capture_output=True, # Suprime output
                text=True,
                timeout=30
            )
            # Limpar o diretório de configuração
            if os.path.exists(config_dir):
                shutil.rmtree(config_dir, ignore_errors=True)
        
        return result
    
    def _import_duplicati_history(self, repo: Dict) -> Dict[str, Any]:
        """
        Importa histórico do Duplicati
        """
        logger.info(f"📦 Duplicati: {repo['name']}")
        
        # Para repositórios na nuvem, usar bucket como path se não houver path
        repo_path = repo.get('path')
        if not repo_path and repo.get('type') != 'local':
            repo_path = repo.get('bucket')
            
        # Verificar se temos as credenciais necessárias para repositórios na nuvem
        if repo.get('type') != 'local':
            access_key = repo.get('access_key', '')
            secret_key = repo.get('secret_key', '')
            if not access_key or not secret_key:
                error_msg = f"Repositório Duplicati '{repo['name']}' não tem todas as credenciais configuradas"
                logger.warning(f"  ⚠️ {error_msg}")
                return {
                    'repository_id': repo['id'],
                    'name': repo['name'],
                    'engine': 'duplicati',
                    'snapshots': [],
                    'statistics': {},
                    'errors': [error_msg]
                }
        
        # Para repositórios na nuvem, usar bucket como path se não houver path
        repo_path = repo.get('path')
        if not repo_path and repo.get('type') != 'local':
            repo_path = repo.get('bucket')
        
        result = {
            'repository_id': repo['id'],
            'name': repo['name'],
            'engine': 'duplicati',
            'snapshots': [],
            'statistics': {},
            'errors': []
        }
        
        try:
            # Duplicati usa banco SQLite local
            duplicati_db = self._find_duplicati_database(repo)
            
            if not duplicati_db:
                raise Exception("Banco de dados do Duplicati não encontrado")
            
            # Conectar ao banco do Duplicati
            conn = sqlite3.connect(duplicati_db)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Buscar backups
            cursor.execute("""
                SELECT * FROM Backup 
                WHERE Name = ? 
                ORDER BY Timestamp DESC
            """, (repo['name'],))
            
            backups = cursor.fetchall()
            logger.info(f"  ✅ {len(backups)} backups encontrados")
            
            for backup in backups:
                snap_data = {
                    'snapshot_id': str(backup['ID']),
                    'full_id': str(backup['ID']),
                    'time': backup['Timestamp'],
                    'size': backup.get('SizeOfExaminedFiles', 0),
                    'files_new': backup.get('AddedFiles', 0),
                    'files_changed': backup.get('ModifiedFiles', 0),
                    'status': 'success' if backup.get('EndTime') else 'failed'
                }
                
                result['snapshots'].append(snap_data)
                self._save_snapshot_to_db(repo['id'], snap_data)
                self.stats['snapshots_imported'] += 1
            
            conn.close()
            
            logger.info(f"  ✅ Repositório importado com sucesso")
            
        except Exception as e:
            error = str(e)
            logger.error(f"  ❌ Erro: {error}")
            result['errors'].append(error)
            self.stats['errors_found'] += 1
        
        return result
    
    def _find_duplicati_database(self, repo: Dict) -> Optional[str]:
        """
        Encontra banco de dados do Duplicati de forma mais robusta.
        1. Procura por um arquivo .sqlite no caminho do repositório.
        2. Faz fallback para o caminho padrão do Duplicati.
        """
        # 1. Procurar no caminho do repositório gerenciado pelo GBOC
        repo_path = repo.get('path')
        if repo_path and os.path.isdir(repo_path):
            for file in os.listdir(repo_path):
                if file.endswith('.sqlite'):
                    db_file = os.path.join(repo_path, file)
                    logger.info(f"  🔍 Banco de dados Duplicati encontrado no caminho do repositório: {db_file}")
                    return db_file

        # 2. Fallback para o caminho padrão
        if platform.system() == "Windows":
            duplicati_data = os.path.join(
                os.environ.get('APPDATA', ''),
                'Duplicati'
            )
        else:
            duplicati_data = os.path.expanduser('~/.config/Duplicati')
        
        db_file = os.path.join(duplicati_data, 'Duplicati-server.sqlite')
        
        if os.path.exists(db_file):
            logger.info(f"  🔍 Banco de dados Duplicati encontrado no caminho global: {db_file}")
            return db_file
        
        logger.warning(f"  ⚠️ Não foi possível encontrar o banco de dados do Duplicati para o repositório '{repo['name']}'")
        return None
    
    def _save_snapshot_to_db(self, repo_id: int, snapshot: Dict):
        """
        Salva snapshot no banco de dados com retentativas
        """
        @self.core.db_retry(max_retries=10, delay=1.0)
        def _execute_save():
            with self.core.get_db_connection() as conn:
                # Verificar se já existe
                existing = conn.execute("""
                    SELECT id FROM snapshots 
                    WHERE repository_id = ? AND snapshot_id = ?
                """, (repo_id, snapshot['snapshot_id'])).fetchone()
                
                if existing:
                    # Atualizar
                    conn.execute("""
                        UPDATE snapshots SET
                            time = ?,
                            hostname = ?,
                            username = ?,
                            paths = ?,
                            size = ?,
                            files_new = ?,
                            files_changed = ?,
                            status = ?
                        WHERE id = ?
                    """, (
                        snapshot['time'],
                        snapshot.get('hostname', ''),
                        snapshot.get('username', ''),
                        json.dumps(snapshot.get('paths', [])),
                        snapshot.get('size', 0),
                        snapshot.get('files_new', 0),
                        snapshot.get('files_changed', 0),
                        snapshot.get('status', 'unknown'),
                        existing[0]
                    ))
                else:
                    # Inserir
                    conn.execute("""
                        INSERT INTO snapshots (
                            repository_id, snapshot_id, full_id,
                            time, hostname, username, paths,
                            size, files_new, files_changed, status,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        repo_id,
                        snapshot['snapshot_id'],
                        snapshot.get('full_id', ''),
                        snapshot['time'],
                        snapshot.get('hostname', ''),
                        snapshot.get('username', ''),
                        json.dumps(snapshot.get('paths', [])),
                        snapshot.get('size', 0),
                        snapshot.get('files_new', 0),
                        snapshot.get('files_changed', 0),
                        snapshot.get('status', 'unknown'),
                        datetime.now().isoformat()
                    ))
                
                conn.commit()
        
        try:
            _execute_save()
        except Exception as e:
            logger.error(f"❌ Erro ao salvar snapshot ({snapshot['snapshot_id']}): {e}")

    def _update_repository_stats(self, repo_id: int, stats: Dict):
        """
        Atualiza estatísticas do repositório com retentativas
        """
        @self.core.db_retry(max_retries=10, delay=1.0)
        def _execute_update():
            with self.core.get_db_connection() as conn:
                conn.execute("""
                    UPDATE repositories SET
                        total_size_bytes = ?,
                        total_files = ?,
                        total_snapshots = ?,
                        last_updated = ?
                    WHERE id = ?
                """, (
                    stats.get('total_size', 0),
                    stats.get('total_file_count', 0),
                    stats.get('snapshots_count', 0),
                    datetime.now().isoformat(),
                    repo_id
                ))
                
                conn.commit()
        
        try:
            _execute_update()
        except Exception as e:
            logger.error(f"❌ Erro ao atualizar stats para o repositório {repo_id}: {e}")
