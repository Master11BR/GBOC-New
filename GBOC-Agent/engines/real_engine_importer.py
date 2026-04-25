#!/usr/bin/env python3
"""
📥 GBOC Agent - Real Engine Importer (IMPORTAÇÃO REAL!)
Detecta engines instalados e importa configurações e estatísticas REAIS
"""

import subprocess
import os
import json
import logging
import shutil
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path
import glob

logger = logging.getLogger(__name__)


class EngineImporter:
    """Importador REAL de engines e suas configurações"""
    
    def __init__(self, db_connection):
        self.db = db_connection
        
    def scan_system(self) -> Dict[str, Any]:
        """
        Escaneia sistema em busca de engines instalados e configurações REAIS
        
        Returns:
            Resultado completo do scan com todas as configurações encontradas
        """
        logger.info("🔍 Iniciando scan REAL do sistema")
        
        result = {
            'engines_detected': {},
            'repositories_found': [],
            'configs_imported': 0,
            'stats_collected': {},
            'timestamp': datetime.now().isoformat()
        }
        
        # 1. Detectar engines instalados
        result['engines_detected'] = self._detect_engines()
        
        # 2. Importar configurações de cada engine
        if result['engines_detected'].get('restic', {}).get('installed'):
            restic_repos = self._import_restic_configs()
            result['repositories_found'].extend(restic_repos)
        
        if result['engines_detected'].get('kopia', {}).get('installed'):
            kopia_repos = self._import_kopia_configs()
            result['repositories_found'].extend(kopia_repos)
        
        if result['engines_detected'].get('duplicati', {}).get('installed'):
            duplicati_repos = self._import_duplicati_configs()
            result['repositories_found'].extend(duplicati_repos)
        
        # 3. Coletar estatísticas reais
        result['stats_collected'] = self._collect_statistics(result['repositories_found'])
        
        result['configs_imported'] = len(result['repositories_found'])
        
        logger.info(f"✅ Scan completo: {result['configs_imported']} repositórios encontrados")
        return result
    
    def _detect_engines(self) -> Dict[str, Dict]:
        """Detecta engines REAIS instalados no sistema"""
        engines = {}
        
        # Lista de engines para detectar
        engine_list = [
            'restic',
            'kopia',
            'duplicati',
            'borg',
            'rclone'
        ]
        
        for engine_name in engine_list:
            # Procurar executável
            exe_name = engine_name
            if os.name == 'nt':  # Windows
                exe_name = f"{engine_name}.exe"
            
            path = shutil.which(exe_name)
            
            # Duplicati tem nome diferente no Windows
            if not path and engine_name == 'duplicati' and os.name == 'nt':
                path = shutil.which('Duplicati.CommandLine.exe')
            
            if path:
                # Obter versão real
                version = self._get_engine_version(engine_name, path)
                
                engines[engine_name] = {
                    'installed': True,
                    'path': path,
                    'version': version
                }
                logger.info(f"✅ Engine detectado: {engine_name} v{version} em {path}")
            else:
                engines[engine_name] = {
                    'installed': False,
                    'path': None,
                    'version': None
                }
        
        return engines
    
    def _get_engine_version(self, engine: str, path: str) -> str:
        """Obtém versão REAL de um engine"""
        try:
            if engine == 'restic':
                result = subprocess.run([path, 'version'], capture_output=True, text=True)
                # Output: "restic 0.16.2 compiled with go1.21.4 on linux/amd64"
                version = result.stdout.split()[1]
                return version
            
            elif engine == 'kopia':
                result = subprocess.run([path, '--version'], capture_output=True, text=True)
                # Output: "0.15.0"
                return result.stdout.strip()
            
            elif engine == 'duplicati':
                # Duplicati mostra versão com --version
                result = subprocess.run([path, 'version'], capture_output=True, text=True)
                return result.stdout.strip()
            
            elif engine == 'borg':
                result = subprocess.run([path, '--version'], capture_output=True, text=True)
                return result.stdout.strip().split()[1]
            
            elif engine == 'rclone':
                result = subprocess.run([path, 'version'], capture_output=True, text=True)
                # Primeira linha tem a versão
                return result.stdout.splitlines()[0].split()[1]
            
        except Exception as e:
            logger.warning(f"⚠️ Não foi possível obter versão de {engine}: {e}")
            return "unknown"
    
    def _import_restic_configs(self) -> List[Dict]:
        """Importa configurações REAIS do Restic"""
        logger.info("📦 Importando configurações Restic...")
        
        repos = []
        
        # Procurar em locais comuns de configuração
        config_locations = []
        
        if os.name == 'nt':  # Windows
            config_locations = [
                os.path.join(os.environ.get('APPDATA', ''), 'restic'),
                os.path.join(os.environ.get('LOCALAPPDATA', ''), 'restic'),
                'C:\\ProgramData\\restic'
            ]
        else:  # Linux/Mac
            config_locations = [
                os.path.expanduser('~/.restic'),
                '/etc/restic',
                os.path.expanduser('~/.config/restic')
            ]
        
        # Procurar por repositórios configurados
        for config_dir in config_locations:
            if not os.path.exists(config_dir):
                continue
            
            # Procurar arquivos de configuração
            for config_file in glob.glob(os.path.join(config_dir, '*.json')):
                try:
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                    
                    if 'repository' in config:
                        repo_path = config['repository']
                        
                        # Tentar obter estatísticas reais
                        stats = self._get_restic_repo_stats(repo_path, config.get('password', ''))
                        
                        repos.append({
                            'name': os.path.basename(config_file).replace('.json', ''),
                            'engine': 'restic',
                            'type': self._detect_repo_type(repo_path),
                            'path': repo_path,
                            'config_file': config_file,
                            'stats': stats
                        })
                        
                        logger.info(f"✅ Repositório Restic encontrado: {repo_path}")
                
                except Exception as e:
                    logger.warning(f"⚠️ Erro ao ler config {config_file}: {e}")
        
        return repos
    
    def _get_restic_repo_stats(self, repo_path: str, password: str) -> Dict:
        """Obtém estatísticas REAIS de um repositório Restic"""
        try:
            env = os.environ.copy()
            env['RESTIC_REPOSITORY'] = repo_path
            env['RESTIC_PASSWORD'] = password
            
            # Comando stats
            result = subprocess.run(
                ['restic', 'stats', '--json'],
                env=env,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                stats_data = json.loads(result.stdout)
                
                return {
                    'total_size': stats_data.get('total_size', 0),
                    'total_file_count': stats_data.get('total_file_count', 0),
                    'snapshots_count': stats_data.get('snapshots_count', 0)
                }
        
        except Exception as e:
            logger.warning(f"⚠️ Não foi possível obter stats de {repo_path}: {e}")
        
        return {}
    
    def _import_kopia_configs(self) -> List[Dict]:
        """Importa configurações REAIS do Kopia"""
        logger.info("📦 Importando configurações Kopia...")
        
        repos = []
        
        # Kopia guarda configs em ~/.kopia ou %LOCALAPPDATA%\kopia
        if os.name == 'nt':
            kopia_dir = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'kopia')
        else:
            kopia_dir = os.path.expanduser('~/.kopia')
        
        if not os.path.exists(kopia_dir):
            return repos
        
        # Procurar por repositórios configurados
        for repo_dir in os.listdir(kopia_dir):
            repo_path = os.path.join(kopia_dir, repo_dir)
            
            if not os.path.isdir(repo_path):
                continue
            
            config_file = os.path.join(repo_path, 'repository.config')
            
            if os.path.exists(config_file):
                try:
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                    
                    storage_config = config.get('storage', {})
                    
                    # Obter estatísticas reais
                    stats = self._get_kopia_repo_stats(repo_path)
                    
                    repos.append({
                        'name': repo_dir,
                        'engine': 'kopia',
                        'type': storage_config.get('type', 'filesystem'),
                        'path': storage_config.get('path', ''),
                        'config_file': config_file,
                        'stats': stats
                    })
                    
                    logger.info(f"✅ Repositório Kopia encontrado: {repo_dir}")
                
                except Exception as e:
                    logger.warning(f"⚠️ Erro ao ler config Kopia {config_file}: {e}")
        
        return repos
    
    def _get_kopia_repo_stats(self, config_path: str) -> Dict:
        """Obtém estatísticas REAIS de um repositório Kopia"""
        try:
            env = os.environ.copy()
            env['KOPIA_CONFIG_PATH'] = config_path
            
            # Obter lista de snapshots
            result = subprocess.run(
                ['kopia', 'snapshot', 'list', '--json'],
                env=env,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                snapshots = json.loads(result.stdout)
                
                total_size = sum(s.get('stats', {}).get('totalSize', 0) for s in snapshots)
                total_files = sum(s.get('stats', {}).get('totalFiles', 0) for s in snapshots)
                
                return {
                    'total_size': total_size,
                    'total_file_count': total_files,
                    'snapshots_count': len(snapshots)
                }
        
        except Exception as e:
            logger.warning(f"⚠️ Não foi possível obter stats Kopia: {e}")
        
        return {}
    
    def _import_duplicati_configs(self) -> List[Dict]:
        """Importa configurações REAIS do Duplicati"""
        logger.info("📦 Importando configurações Duplicati...")
        
        repos = []
        
        # Duplicati guarda configs em SQLite
        if os.name == 'nt':
            duplicati_data = os.path.join(
                os.environ.get('APPDATA', ''),
                'Duplicati'
            )
        else:
            duplicati_data = os.path.expanduser('~/.config/Duplicati')
        
        db_file = os.path.join(duplicati_data, 'Duplicati-server.sqlite')
        
        if not os.path.exists(db_file):
            return repos
        
        try:
            import sqlite3
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            
            # Listar backups configurados
            cursor.execute("SELECT ID, Name, TargetURL FROM Backup")
            
            for row in cursor.fetchall():
                backup_id, name, target_url = row
                
                repos.append({
                    'name': name,
                    'engine': 'duplicati',
                    'type': self._detect_repo_type(target_url),
                    'path': target_url,
                    'backup_id': backup_id,
                    'stats': {}  # TODO: obter estatísticas
                })
                
                logger.info(f"✅ Repositório Duplicati encontrado: {name}")
            
            conn.close()
        
        except Exception as e:
            logger.warning(f"⚠️ Erro ao importar configs Duplicati: {e}")
        
        return repos
    
    def _detect_repo_type(self, path: str) -> str:
        """Detecta tipo de repositório baseado no path"""
        if path.startswith('b2://'):
            return 'b2'
        elif path.startswith('s3://'):
            return 's3'
        elif path.startswith('azure://'):
            return 'azure'
        elif path.startswith('gs://'):
            return 'gcs'
        elif path.startswith('sftp://'):
            return 'sftp'
        elif path.startswith('file://') or os.path.exists(path):
            return 'local'
        else:
            return 'unknown'
    
    def _collect_statistics(self, repositories: List[Dict]) -> Dict:
        """Coleta estatísticas GERAIS de todos os repositórios"""
        stats = {
            'total_repositories': len(repositories),
            'total_size_bytes': 0,
            'total_files': 0,
            'total_snapshots': 0,
            'by_engine': {}
        }
        
        for repo in repositories:
            repo_stats = repo.get('stats', {})
            
            stats['total_size_bytes'] += repo_stats.get('total_size', 0)
            stats['total_files'] += repo_stats.get('total_file_count', 0)
            stats['total_snapshots'] += repo_stats.get('snapshots_count', 0)
            
            # Agrupar por engine
            engine = repo['engine']
            if engine not in stats['by_engine']:
                stats['by_engine'][engine] = {
                    'count': 0,
                    'total_size': 0
                }
            
            stats['by_engine'][engine]['count'] += 1
            stats['by_engine'][engine]['total_size'] += repo_stats.get('total_size', 0)
        
        # Converter bytes para GB
        stats['total_size_gb'] = round(stats['total_size_bytes'] / (1024**3), 2)
        
        return stats
    
    def import_to_database(self, scan_result: Dict) -> int:
        """Importa repositórios encontrados para o banco de dados"""
        logger.info("💾 Importando repositórios para banco de dados...")
        
        imported = 0
        
        for repo in scan_result['repositories_found']:
            try:
                # Verificar se já existe
                cursor = self.db.execute(
                    "SELECT id FROM repositories WHERE path = ?",
                    (repo['path'],)
                )
                
                if cursor.fetchone():
                    logger.info(f"⏭️ Repositório já existe: {repo['name']}")
                    continue
                
                # Inserir novo repositório
                self.db.execute("""
                    INSERT INTO repositories (
                        name,
                        engine,
                        type,
                        path,
                        config_file,
                        total_size_bytes,
                        total_files,
                        total_snapshots,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    repo['name'],
                    repo['engine'],
                    repo['type'],
                    repo['path'],
                    repo.get('config_file', ''),
                    repo.get('stats', {}).get('total_size', 0),
                    repo.get('stats', {}).get('total_file_count', 0),
                    repo.get('stats', {}).get('snapshots_count', 0),
                    datetime.now().isoformat()
                ))
                
                imported += 1
                logger.info(f"✅ Repositório importado: {repo['name']}")
            
            except Exception as e:
                logger.error(f"❌ Erro ao importar {repo['name']}: {e}")
        
        self.db.commit()
        
        logger.info(f"✅ Importação concluída: {imported} novos repositórios")
        return imported
