#!/usr/bin/env python3
"""
🔧 GBOC Agent 11.7c - MOTOR ENGINE MANAGER
Detecta, importa e gerencia motores de backup instalados
"""

import os
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class BackupEngineManager:
    """Gerenciador de motores de backup"""
    
    def __init__(self, core):
        self.core = core
        self.engines_data = {}
        self._init_database()
        
    def _init_database(self):
        """Inicializa tabelas de motores"""
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                # Tabela de motores detectados
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS detected_engines (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        version TEXT,
                        path TEXT NOT NULL,
                        status TEXT DEFAULT 'active',
                        capabilities TEXT,
                        last_scan TEXT,
                        metadata TEXT DEFAULT '{}',
                        created_at TEXT NOT NULL
                    )
                """)
                
                # Tabela de repositórios importados dos motores
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS imported_repositories (
                        id SERIAL PRIMARY KEY,
                        engine_name TEXT NOT NULL,
                        original_id TEXT,
                        name TEXT NOT NULL,
                        path TEXT NOT NULL,
                        size_bytes BIGINT DEFAULT 0,
                        file_count INTEGER DEFAULT 0,
                        last_backup TEXT,
                        status TEXT DEFAULT 'active',
                        imported_at TEXT NOT NULL,
                        metadata TEXT DEFAULT '{}'
                    )
                """)
                
                # Tabela de estatísticas dos backups
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS engine_backup_statistics (
                        id SERIAL PRIMARY KEY,
                        repository_id INTEGER,
                        engine_name TEXT,
                        backup_date TEXT NOT NULL,
                        files_processed INTEGER DEFAULT 0,
                        bytes_processed BIGINT DEFAULT 0,
                        duration_seconds INTEGER DEFAULT 0,
                        compression_ratio REAL DEFAULT 1.0,
                        deduplication_ratio REAL DEFAULT 1.0,
                        success BOOLEAN DEFAULT true,
                        error_message TEXT,
                        metadata TEXT DEFAULT '{}',
                        created_at TEXT NOT NULL
                    )
                """)
                
                conn.commit()
                logger.info("[SUCCESS] Database de motores inicializada")
                
        except Exception as e:
            logger.error(f"Erro ao inicializar database: {e}")
    
    def scan_all_engines(self) -> Dict[str, Any]:
        """Escaneia todos os motores de backup disponíveis"""
        try:
            logger.info("🔍 Escaneando motores de backup...")
            
            results = {
                "restic": self._scan_restic(),
                "kopia": self._scan_kopia(),
                "duplicati": self._scan_duplicati(),
                "borg": self._scan_borg(),
                "rclone": self._scan_rclone()
            }
            
            # Salvar no banco
            self._save_detected_engines(results)
            
            active_engines = [name for name, data in results.items() if data.get('installed')]
            logger.info(f"🎯 Motores ativos encontrados: {active_engines}")
            
            return {
                "status": "success",
                "engines": results,
                "active_count": len(active_engines),
                "scan_time": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Erro no scan de motores: {e}")
            return {"status": "error", "error": str(e)}
    
    def _scan_restic(self) -> Dict[str, Any]:
        """Detecta Restic"""
        try:
            # Procurar executável em múltiplos locais
            restic_paths = [
                "restic",  # PATH do sistema
                r"C:\GBOC\Tools\Restic\restic.exe",
                r"C:\GBOC\Tools\Restic\restic_0.17.3_windows_amd64.exe",
                r"C:\ProgramData\chocolatey\bin\restic.exe",
                r"C:\Tools\restic\restic.exe",
                os.path.join(os.environ.get('LOCALAPPDATA', ''), 'restic', 'restic.exe'),
                "/usr/bin/restic",
                "/usr/local/bin/restic",
            ]

            # Adicionar path do .env se existir
            env_path = os.environ.get('RESTIC_PATH', '')
            if env_path and env_path not in restic_paths:
                restic_paths.insert(0, env_path)

            # Procurar em subpastas do Tools (pode ter nome diferente)
            tools_restic = r"C:\GBOC\Tools\Restic"
            if os.path.isdir(tools_restic):
                for f in os.listdir(tools_restic):
                    if f.lower().startswith('restic') and f.lower().endswith('.exe'):
                        full = os.path.join(tools_restic, f)
                        if full not in restic_paths:
                            restic_paths.insert(1, full)

            for exe in restic_paths:
                try:
                    result = subprocess.run([exe, 'version'],
                                          capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        version = result.stdout.strip().split('\n')[0]
                        repositories = self._scan_restic_repositories()
                        return {
                            "installed": True,
                            "version": version,
                            "executable": exe,
                            "repositories": repositories,
                            "capabilities": ["encryption", "deduplication", "compression", "cloud_support"],
                            "last_scan": datetime.now().isoformat()
                        }
                except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                    continue

            return {"installed": False, "error": "Não encontrado"}

        except Exception as e:
            return {"installed": False, "error": str(e)}
    
    def _scan_kopia(self) -> Dict[str, Any]:
        """Detecta Kopia"""
        try:
            # Procurar executável em múltiplos locais
            kopia_paths = [
                "kopia",  # PATH do sistema
                r"C:\GBOC\Tools\Kopia\kopia.exe",
                r"C:\ProgramData\chocolatey\bin\kopia.exe",
                r"C:\Tools\kopia\kopia.exe",
                os.path.join(os.environ.get('LOCALAPPDATA', ''), 'kopia', 'kopia.exe'),
                os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'KopiaUI', 'resources', 'server', 'kopia.exe'),
                "/usr/bin/kopia",
                "/usr/local/bin/kopia",
            ]

            # Adicionar path do .env se existir
            env_path = os.environ.get('KOPIA_PATH', '')
            if env_path and env_path not in kopia_paths:
                kopia_paths.insert(0, env_path)

            # Procurar em subpastas do Tools
            tools_kopia = r"C:\GBOC\Tools\Kopia"
            if os.path.isdir(tools_kopia):
                for f in os.listdir(tools_kopia):
                    if f.lower().startswith('kopia') and f.lower().endswith('.exe'):
                        full = os.path.join(tools_kopia, f)
                        if full not in kopia_paths:
                            kopia_paths.insert(1, full)

            for exe in kopia_paths:
                try:
                    result = subprocess.run([exe, '--version'],
                                          capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        version = result.stdout.strip()
                        repositories = self._scan_kopia_repositories()
                        return {
                            "installed": True,
                            "version": version,
                            "executable": exe,
                            "repositories": repositories,
                            "capabilities": ["encryption", "deduplication", "compression", "web_ui"],
                            "last_scan": datetime.now().isoformat()
                        }
                except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                    continue

            return {"installed": False, "error": "Não encontrado"}

        except Exception as e:
            return {"installed": False, "error": str(e)}
    
    def _scan_duplicati(self) -> Dict[str, Any]:
        """Detecta Duplicati"""
        try:
            # Procurar instalação do Duplicati
            duplicati_paths = [
                r"C:\GBOC\Tools\Duplicati\Duplicati.CommandLine.exe",
                r"C:\Program Files\Duplicati 2\Duplicati.CommandLine.exe",
                r"C:\Program Files (x86)\Duplicati 2\Duplicati.CommandLine.exe",
                r"C:\Program Files\Duplicati\Duplicati.CommandLine.exe",
                "/usr/bin/duplicati-cli",
                "/opt/duplicati/Duplicati.CommandLine.exe"
            ]

            # Procurar em subpastas do Tools
            tools_duplicati = r"C:\GBOC\Tools\Duplicati"
            if os.path.isdir(tools_duplicati):
                for f in os.listdir(tools_duplicati):
                    if 'commandline' in f.lower() and f.lower().endswith('.exe'):
                        full = os.path.join(tools_duplicati, f)
                        if full not in duplicati_paths:
                            duplicati_paths.insert(1, full)
            
            for path in duplicati_paths:
                if os.path.exists(path):
                    try:
                        result = subprocess.run([path, 'help'], 
                                              capture_output=True, text=True, timeout=10)
                        
                        if result.returncode == 0:
                            # Extrair versão
                            version = "2.x" # Versão padrão
                            
                            # Detectar backups
                            repositories = self._scan_duplicati_repositories()
                            
                            return {
                                "installed": True,
                                "version": version,
                                "executable": path,
                                "repositories": repositories,
                                "capabilities": ["web_ui", "scheduling", "cloud_support", "encryption"],
                                "last_scan": datetime.now().isoformat()
                            }
                    except:
                        continue
            
            return {"installed": False, "error": "Não encontrado"}
            
        except Exception as e:
            return {"installed": False, "error": str(e)}
    
    def _scan_borg(self) -> Dict[str, Any]:
        """Detecta Borg Backup"""
        try:
            result = subprocess.run(['borg', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                version = result.stdout.strip()
                
                # Detectar repositórios
                repositories = self._scan_borg_repositories()
                
                return {
                    "installed": True,
                    "version": version,
                    "executable": "borg",
                    "repositories": repositories,
                    "capabilities": ["deduplication", "encryption", "compression"],
                    "last_scan": datetime.now().isoformat()
                }
            else:
                return {"installed": False, "error": "Não encontrado"}
                
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {"installed": False, "error": "Não instalado"}
        except Exception as e:
            return {"installed": False, "error": str(e)}
    
    def _scan_rclone(self) -> Dict[str, Any]:
        """Detecta RClone"""
        try:
            result = subprocess.run(['rclone', 'version'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                version = lines[0] if lines else "unknown"
                
                # Detectar configurações
                configs = self._scan_rclone_configs()
                
                return {
                    "installed": True,
                    "version": version,
                    "executable": "rclone",
                    "configs": configs,
                    "capabilities": ["cloud_sync", "encryption", "compression"],
                    "last_scan": datetime.now().isoformat()
                }
            else:
                return {"installed": False, "error": "Não encontrado"}
                
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {"installed": False, "error": "Não instalado"}
        except Exception as e:
            return {"installed": False, "error": str(e)}
    
    def _scan_restic_repositories(self) -> List[Dict[str, Any]]:
        """Escaneia repositórios Restic"""
        repositories = []
        try:
            # Procurar por arquivos de configuração do Restic
            home_dir = Path.home()
            
            # Locais comuns de repositórios Restic
            common_locations = [
                home_dir / ".config" / "restic",
                home_dir / "restic-repos",
                Path("C:/Backup/restic") if os.name == 'nt' else Path("/backup/restic")
            ]
            
            for location in common_locations:
                if location.exists():
                    for item in location.iterdir():
                        if item.is_dir() and self._is_restic_repo(item):
                            repo_info = self._get_restic_repo_info(item)
                            if repo_info:
                                repositories.append(repo_info)
            
        except Exception as e:
            logger.error(f"Erro ao escanear repositórios Restic: {e}")
        
        return repositories
    
    def _scan_kopia_repositories(self) -> List[Dict[str, Any]]:
        """Escaneia repositórios Kopia"""
        repositories = []
        try:
            # Listar repositórios conectados no Kopia
            result = subprocess.run(['kopia', 'repo', 'list'], 
                                  capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if line.strip():
                        repo_info = self._parse_kopia_repo_line(line)
                        if repo_info:
                            repositories.append(repo_info)
            
        except Exception as e:
            logger.error(f"Erro ao escanear repositórios Kopia: {e}")
        
        return repositories
    
    def _scan_duplicati_repositories(self) -> List[Dict[str, Any]]:
        """Escaneia backups Duplicati"""
        repositories = []
        try:
            # Procurar database do Duplicati
            duplicati_data_paths = [
                Path.home() / "AppData" / "Local" / "Duplicati",
                Path("/var/lib/duplicati"),
                Path.home() / ".config" / "Duplicati"
            ]
            
            for data_path in duplicati_data_paths:
                db_file = data_path / "Duplicati-server.sqlite"
                if db_file.exists():
                    repos = self._read_duplicati_database(db_file)
                    repositories.extend(repos)
            
        except Exception as e:
            logger.error(f"Erro ao escanear repositórios Duplicati: {e}")
        
        return repositories
    
    def _scan_borg_repositories(self) -> List[Dict[str, Any]]:
        """Escaneia repositórios Borg"""
        repositories = []
        try:
            # Borg geralmente usa variáveis de ambiente
            borg_repo = os.environ.get('BORG_REPO')
            if borg_repo:
                repo_info = self._get_borg_repo_info(borg_repo)
                if repo_info:
                    repositories.append(repo_info)
            
            # Procurar em locais comuns
            common_locations = [
                Path.home() / "borg-repos",
                Path("/backup/borg"),
                Path("C:/Backup/borg") if os.name == 'nt' else None
            ]
            
            for location in filter(None, common_locations):
                if location.exists():
                    for item in location.iterdir():
                        if item.is_dir() and self._is_borg_repo(item):
                            repo_info = self._get_borg_repo_info(str(item))
                            if repo_info:
                                repositories.append(repo_info)
        
        except Exception as e:
            logger.error(f"Erro ao escanear repositórios Borg: {e}")
        
        return repositories
    
    def _scan_rclone_configs(self) -> List[Dict[str, Any]]:
        """Escaneia configurações RClone"""
        configs = []
        try:
            result = subprocess.run(['rclone', 'config', 'show'], 
                                  capture_output=True, text=True, timeout=20)
            
            if result.returncode == 0:
                configs = self._parse_rclone_config(result.stdout)
        
        except Exception as e:
            logger.error(f"Erro ao escanear configs RClone: {e}")
        
        return configs
    
    def _is_restic_repo(self, path: Path) -> bool:
        """Verifica se é um repositório Restic válido"""
        try:
            config_file = path / "config"
            return config_file.exists()
        except:
            return False
    
    def _get_restic_repo_info(self, path: Path) -> Optional[Dict[str, Any]]:
        """Obtém informações de um repositório Restic"""
        try:
            result = subprocess.run(['restic', '-r', str(path), 'stats', '--json'], 
                                  capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                stats = json.loads(result.stdout)
                return {
                    "name": path.name,
                    "path": str(path),
                    "type": "local",
                    "size_bytes": stats.get("total_size", 0),
                    "file_count": stats.get("total_file_count", 0),
                    "snapshots_count": stats.get("snapshots_count", 0)
                }
        except Exception as e:
            logger.debug(f"Erro ao obter info Restic de {path}: {e}")
        
        return None
    
    def import_engine_data(self, engine_name: str) -> Dict[str, Any]:
        """Importa dados de um motor específico"""
        try:
            logger.info(f"📥 Importando dados do motor: {engine_name}")
            
            if engine_name == "restic":
                return self._import_restic_data()
            elif engine_name == "kopia":
                return self._import_kopia_data()
            elif engine_name == "duplicati":
                return self._import_duplicati_data()
            elif engine_name == "borg":
                return self._import_borg_data()
            else:
                return {"status": "error", "error": f"Motor {engine_name} não suportado"}
        
        except Exception as e:
            logger.error(f"Erro ao importar {engine_name}: {e}")
            return {"status": "error", "error": str(e)}
    
    def _import_restic_data(self) -> Dict[str, Any]:
        """Importa dados detalhados do Restic"""
        try:
            imported_repos = 0
            imported_stats = 0
            
            repositories = self._scan_restic_repositories()
            
            for repo in repositories:
                # Importar repositório
                repo_id = self._save_imported_repository("restic", repo)
                
                # Importar snapshots e estatísticas
                snapshots = self._get_restic_snapshots(repo['path'])
                for snapshot in snapshots:
                    self._save_engine_backup_statistics("restic", repo_id, snapshot)
                    imported_stats += 1
                
                imported_repos += 1
            
            return {
                "status": "success",
                "engine": "restic",
                "imported_repositories": imported_repos,
                "imported_statistics": imported_stats
            }
        
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _get_restic_snapshots(self, repo_path: str) -> List[Dict[str, Any]]:
        """Obtém snapshots do Restic"""
        try:
            result = subprocess.run(['restic', '-r', repo_path, 'snapshots', '--json'], 
                                  capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                return json.loads(result.stdout)
            
        except Exception as e:
            logger.error(f"Erro ao obter snapshots Restic: {e}")
        
        return []
    
    def _save_detected_engines(self, engines_data: Dict[str, Any]):
        """Salva motores detectados no banco"""
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                now = datetime.now().isoformat()
                
                for engine_name, engine_data in engines_data.items():
                    if engine_data.get('installed'):
                        # Primeiro tenta atualizar
                        cur.execute("""
                            UPDATE detected_engines SET
                                version = %s, path = %s, status = %s, capabilities = %s, 
                                last_scan = %s, metadata = %s
                            WHERE name = %s
                        """, (
                            engine_data.get('version', ''),
                            engine_data.get('executable', ''),
                            'active',
                            json.dumps(engine_data.get('capabilities', [])),
                            now,
                            json.dumps(engine_data),
                            engine_name
                        ))
                        
                        # Se não atualizou nada, insere
                        if cur.rowcount == 0:
                            cur.execute("""
                                INSERT INTO detected_engines 
                                (name, version, path, status, capabilities, last_scan, metadata, created_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                engine_name,
                                engine_data.get('version', ''),
                                engine_data.get('executable', ''),
                                'active',
                                json.dumps(engine_data.get('capabilities', [])),
                                now,
                                json.dumps(engine_data),
                                now
                            ))
                
                conn.commit()
                logger.info("💾 Motores detectados salvos no banco")
                
        except Exception as e:
            logger.error(f"Erro ao salvar motores: {e}")
    
    def _save_imported_repository(self, engine_name: str, repo_data: Dict[str, Any]) -> int:
        """Salva repositório importado"""
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                now = datetime.now().isoformat()
                
                cur.execute("""
                    INSERT INTO imported_repositories 
                    (engine_name, name, path, size_bytes, file_count, status, imported_at, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    engine_name,
                    repo_data.get('name', ''),
                    repo_data.get('path', ''),
                    repo_data.get('size_bytes', 0),
                    repo_data.get('file_count', 0),
                    'active',
                    now,
                    json.dumps(repo_data)
                ))
                
                repo_id = cur.fetchone()[0]
                conn.commit()
                
                return repo_id
                
        except Exception as e:
            logger.error(f"Erro ao salvar repositório: {e}")
            return 0
    
    def _save_engine_backup_statistics(self, engine_name: str, repo_id: int, snapshot_data: Dict[str, Any]):
        """Salva estatísticas de backup"""
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                now = datetime.now().isoformat()
                
                cur.execute("""
                    INSERT INTO engine_backup_statistics 
                    (repository_id, engine_name, backup_date, files_processed, bytes_processed, 
                     success, metadata, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    repo_id,
                    engine_name,
                    snapshot_data.get('time', now),
                    snapshot_data.get('file_count', 0),
                    snapshot_data.get('total_size', 0),
                    True,
                    json.dumps(snapshot_data),
                    now
                ))
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"Erro ao salvar estatísticas: {e}")
    
    def get_engine_statistics(self) -> Dict[str, Any]:
        """Obtém estatísticas dos motores"""
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                
                # Estatísticas gerais
                cur.execute("SELECT COUNT(*) as total FROM detected_engines WHERE status='active'")
                active_engines = cur.fetchone()['total']
                
                cur.execute("SELECT COUNT(*) as total FROM imported_repositories")
                total_repos = cur.fetchone()['total']
                
                cur.execute("SELECT COALESCE(SUM(size_bytes), 0) as total FROM imported_repositories")
                total_size = cur.fetchone()['total']
                
                cur.execute("SELECT COUNT(*) as total FROM engine_backup_statistics WHERE success=true")
                successful_backups = cur.fetchone()['total']
                
                # Estatísticas por motor
                cur.execute("""
                    SELECT engine_name, COUNT(*) as backups, SUM(bytes_processed) as bytes
                    FROM engine_backup_statistics 
                    GROUP BY engine_name
                """)
                
                engine_stats = {}
                for row in cur.fetchall():
                    engine_stats[row['engine_name']] = {
                        "backups_count": row['backups'],
                        "bytes_processed": row['bytes']
                    }
                
                return {
                    "status": "success",
                    "summary": {
                        "active_engines": active_engines,
                        "total_repositories": total_repos,
                        "total_size_bytes": total_size,
                        "successful_backups": successful_backups
                    },
                    "engines": engine_stats
                }
                
        except Exception as e:
            logger.error(f"Erro ao obter estatísticas: {e}")
            return {"status": "error", "error": str(e)}



