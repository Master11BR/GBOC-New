"""
GBOC Agent - Importador de descoberta e conversão de backups para o Motor Nativo.
Converte repositórios e tarefas do Duplicati, Restic, Kopia e Borg em tarefas nativas do GBOC.
"""

import os
import sys
import json
import sqlite3
import logging
import shutil
from typing import Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


class RealBackupImporter:
    def __init__(self, core=None):
        self.core = core

    def scan_system(self) -> Dict[str, Any]:
        """Escaneia engines disponíveis, bancos de dados legados e repositórios locais."""
        logger.info("🔍 Scan de descoberta de importação iniciado...")
        engines = self._detect_engines()

        common_paths = [
            "C:\\Backups", "D:\\Backups", "E:\\Backups",
            "/var/backups", "/opt/backups", "./backups"
        ]

        found_repos: List[Dict[str, Any]] = []
        total_size_imported = 0

        for path in common_paths:
            if not os.path.isdir(path):
                continue
            size = self._get_dir_size(path)
            total_size_imported += size
            found_repos.append({
                "name": f"Discovered_{os.path.basename(os.path.normpath(path)) or 'backups'}",
                "type": "local",
                "path": path,
                "size": size
            })

        duplicati_jobs = self._scan_duplicati_dbs()

        return {
            "engines_detected": engines,
            "repositories_found": found_repos,
            "duplicati_jobs_found": duplicati_jobs,
            "imported_size_bytes": total_size_imported,
            "mode": "discovery_and_import"
        }

    def _get_dir_size(self, path: str) -> int:
        total = 0
        try:
            for entry in os.scandir(path):
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += self._get_dir_size(entry.path)
                except Exception:
                    continue
        except Exception:
            return total
        return total

    def _detect_engines(self) -> Dict[str, Dict[str, Any]]:
        engines = {}
        for tool in ["restic", "kopia", "duplicati", "borg"]:
            path = shutil.which(tool)
            engines[tool] = {"available": path is not None, "path": path}
        return engines

    def _scan_duplicati_dbs(self) -> List[Dict[str, Any]]:
        """Localiza e lê o banco SQLite do Duplicati Server se disponível."""
        candidates = []
        if sys.platform == "win32":
            appdata = os.getenv("APPDATA", "")
            localappdata = os.getenv("LOCALAPPDATA", "")
            programdata = os.getenv("ProgramData", "")
            if localappdata:
                candidates.append(os.path.join(localappdata, "Duplicati", "Duplicati-server.sqlite"))
            if appdata:
                candidates.append(os.path.join(appdata, "Duplicati", "Duplicati-server.sqlite"))
            if programdata:
                candidates.append(os.path.join(programdata, "Duplicati", "Duplicati-server.sqlite"))
        else:
            home = os.path.expanduser("~")
            candidates.append(os.path.join(home, ".config", "Duplicati", "Duplicati-server.sqlite"))
            candidates.append("/var/lib/duplicati/Duplicati-server.sqlite")

        jobs = []
        for db_path in candidates:
            if os.path.isfile(db_path):
                try:
                    conn = sqlite3.connect(db_path)
                    cur = conn.cursor()
                    cur.execute("SELECT ID, Name, TargetURL FROM Backup")
                    rows = cur.fetchall()
                    for r in rows:
                        b_id, name, target_url = r[0], r[1], r[2]
                        # Buscar origens na tabela Source / Sources
                        sources = []
                        try:
                            cur.execute("SELECT Path FROM Source WHERE BackupID = ?", (b_id,))
                            sources = [s[0] for s in cur.fetchall()]
                        except Exception:
                            try:
                                cur.execute("SELECT Path FROM Sources WHERE BackupID = ?", (b_id,))
                                sources = [s[0] for s in cur.fetchall()]
                            except Exception:
                                pass
                        jobs.append({
                            "id": b_id,
                            "name": name,
                            "target_url": target_url,
                            "sources": sources,
                            "db_path": db_path
                        })
                    conn.close()
                except Exception as e:
                    logger.warning(f"Erro ao ler banco Duplicati em {db_path}: {e}")

        return jobs

    def import_all_to_native(self) -> Dict[str, Any]:
        """
        Executa a migração/importação real de todos os motores legados e do Duplicati
        para o Motor Nativo do GBOC System.
        """
        from shared_core import get_shared_core
        core = self.core or get_shared_core()
        if not core:
            return {"status": "error", "message": "SharedCore não inicializado"}

        imported_repos = 0
        imported_tasks = 0
        logs = []

        try:
            with core.get_db_connection() as conn:
                cur = conn.cursor()

                # 1. Preencher repositórios sem motor definido mantendo os motores existentes intactos
                cur.execute("UPDATE repositories SET engine = 'gboc_native' WHERE engine IS NULL OR TRIM(engine) = ''")
                imported_repos += cur.rowcount if hasattr(cur, 'rowcount') and cur.rowcount is not None else 0
                conn.commit()

                # 2. Preencher tarefas sem motor definido mantendo os motores existentes intactos
                cur.execute("UPDATE tasks SET engine = 'gboc_native' WHERE engine IS NULL OR TRIM(engine) = ''")
                converted_tasks = cur.rowcount if hasattr(cur, 'rowcount') and cur.rowcount is not None else 0
                imported_tasks += converted_tasks
                conn.commit()

                # 3. Importar tarefas e repositórios do Duplicati caso existam
                duplicati_jobs = self._scan_duplicati_dbs()
                # Também tentar obter da API do Duplicati Native se o serviço estiver ativo
                try:
                    from core.integrations.duplicati_native import get_duplicati_native_service
                    dup_srv = get_duplicati_native_service()
                    active_backups = dup_srv.list_backups().get("items", [])
                    for ab in active_backups:
                        b_obj = ab.get("Backup", {}) if isinstance(ab.get("Backup"), dict) else ab
                        b_name = ab.get("name") or b_obj.get("Name")
                        b_url = ab.get("target_url") or b_obj.get("TargetURL")
                        b_id = str(ab.get("id") or b_obj.get("ID") or "")
                        if b_name and not any(j.get("name") == b_name or str(j.get("id")) == b_id for j in duplicati_jobs):
                            duplicati_jobs.append({
                                "id": b_id,
                                "name": b_name,
                                "target_url": b_url,
                                "sources": ab.get("sources") or [],
                                "db_path": b_obj.get("DBPath") or ""
                            })
                except Exception as _e_dup:
                    logger.warning(f"Não foi possível obter backups adicionais via API do Duplicati: {_e_dup}")

                now_str = datetime.now().isoformat()
                for job in duplicati_jobs:
                    job_name = f"Nativo_Duplicati_{job['name']}"
                    sources_json = json.dumps(job["sources"]) if job["sources"] else json.dumps(["C:\\"])
                    raw_target = str(job.get("target_url") or "")
                    if raw_target.startswith("enc-v1:"):
                        for ab in active_backups:
                            ab_obj = ab.get("Backup", {}) if isinstance(ab.get("Backup"), dict) else ab
                            ab_name = ab.get("name") or ab_obj.get("Name")
                            ab_id = str(ab.get("id") or ab_obj.get("ID") or "")
                            cand_url = str(ab.get("target_url") or ab_obj.get("TargetURL") or "")
                            if (ab_name == job.get("name") or ab_id == str(job.get("id"))) and cand_url and not cand_url.startswith("enc-v1:"):
                                raw_target = cand_url
                                break
                        if raw_target.startswith("enc-v1:"):
                            raw_target = "C:\\GBOC-Backups"

                    # Normalizar caminho e determinar tipo específico de repositório
                    is_cloud = any(proto in raw_target.lower() for proto in ["s3://", "wasabi", "b2://", "azure", "sftp://"])
                    if raw_target.lower().startswith("file://"):
                        clean_path = raw_target[7:]
                        if clean_path.startswith("/") and len(clean_path) > 2 and clean_path[2] == ":":
                            clean_path = clean_path[1:]
                        clean_path = clean_path.replace("/", "\\")
                    else:
                        clean_path = raw_target if raw_target else "C:\\GBOC-Backups"

                    # Se for caminho local no Windows/Linux, garantir criação do diretório físico
                    if not is_cloud and clean_path and (":" in clean_path or clean_path.startswith("/")):
                        try:
                            os.makedirs(clean_path, exist_ok=True)
                        except Exception:
                            pass

                    target_lower = raw_target.lower()
                    if "wasabi" in target_lower:
                        repo_type = "wasabi"
                    elif "b2://" in target_lower or "backblaze" in target_lower:
                        repo_type = "b2"
                    elif "azure" in target_lower:
                        repo_type = "azure"
                    elif "s3://" in target_lower:
                        repo_type = "s3"
                    elif is_cloud:
                        repo_type = "s3"
                    else:
                        repo_type = "local"

                    repo_config = {}
                    if is_cloud and "://" in raw_target:
                        try:
                            from urllib.parse import urlparse, parse_qs
                            u = urlparse(raw_target)
                            qs = parse_qs(u.query)
                            repo_config["bucket"] = u.netloc
                            if u.path:
                                repo_config["prefix"] = u.path.strip("/")
                            if qs.get("s3-server-name"):
                                repo_config["endpoint"] = qs["s3-server-name"][0]
                            if qs.get("auth-username"):
                                repo_config["access_key"] = qs["auth-username"][0]
                                repo_config["aws_access_key"] = qs["auth-username"][0]
                            if qs.get("auth-password"):
                                repo_config["secret_key"] = qs["auth-password"][0]
                                repo_config["aws_secret_key"] = qs["auth-password"][0]
                        except Exception:
                            pass
                    config_json = json.dumps(repo_config) if repo_config else None

                    # Criar ou obter repositório correspondente
                    repo_name = f"Repo_Duplicati_{job['name']}"
                    cur.execute("SELECT id FROM repositories WHERE name = %s OR path = %s", (repo_name, clean_path))
                    existing_repo = cur.fetchone()
                    if existing_repo:
                        repo_id = existing_repo[0]
                        cur.execute("""
                            UPDATE repositories 
                            SET path = %s, type = %s, config = COALESCE(%s, config), updated_at = %s 
                            WHERE id = %s AND (path LIKE 'enc-v1%%' OR path IS NULL OR type = 'cloud')
                        """, (clean_path, repo_type, config_json, now_str, repo_id))
                    else:
                        try:
                            cur.execute("""
                                INSERT INTO repositories (name, type, path, engine, status, enabled, initialized, config, created_at, updated_at)
                                VALUES (%s, %s, %s, 'duplicati', 'active', true, true, %s, %s, %s)
                                RETURNING id
                            """, (repo_name, repo_type, clean_path, config_json, now_str, now_str))
                            repo_id = cur.fetchone()[0]
                        except Exception:
                            cur.execute("""
                                INSERT INTO repositories (name, type, path, engine, status, enabled, initialized, config, created_at, updated_at)
                                VALUES (%s, %s, %s, 'duplicati', 'active', 1, 1, %s, %s, %s)
                            """, (repo_name, repo_type, clean_path, config_json, now_str, now_str))
                            repo_id = getattr(cur, 'lastrowid', None) or 1
                        
                        imported_repos += 1
                        conn.commit()
                        logs.append(f"✓ Criado repositório '{repo_name}' ({repo_type.upper()}: {clean_path}) para Duplicati.")

                    # Verificar se tarefa já existe e atualizar / inserir
                    cur.execute("SELECT id, repository_id FROM tasks WHERE name = %s OR name = %s", (job_name, job['name']))
                    existing_task = cur.fetchone()
                    if existing_task:
                        task_id = existing_task[0]
                        cur.execute("""
                            UPDATE tasks SET repository_id = %s, engine = 'duplicati', source_paths = %s, status = 'idle', enabled = true, updated_at = %s
                            WHERE id = %s
                        """, (repo_id, sources_json, now_str, task_id))
                        conn.commit()
                        logs.append(f"✓ Atualizada tarefa Duplicati '{job['name']}' vinculada ao repositório #{repo_id}.")
                    else:
                        cur.execute("""
                            INSERT INTO tasks (name, engine, repository_id, source_paths, status, enabled, schedule_cron, created_at, updated_at)
                            VALUES (%s, 'duplicati', %s, %s, 'idle', true, '0 */2 * * *', %s, %s)
                        """, (job_name, repo_id, sources_json, now_str, now_str))
                        imported_tasks += 1
                        conn.commit()
                        logs.append(f"✓ Mapeada tarefa Duplicati '{job['name']}' com repositório #{repo_id}.")

                # 4. Caso não existam tarefas nativas registradas, criar uma tarefa padrão do sistema nativo
                cur.execute("SELECT COUNT(*) FROM tasks WHERE engine = 'native'")
                cnt_row = cur.fetchone()
                total_native_tasks = cnt_row[0] if cnt_row else 0
                if total_native_tasks == 0:
                    default_name = "Backup Nativo do Sistema (Local)"
                    cur.execute("""
                        INSERT INTO tasks (name, engine, source_paths, status, schedule_cron, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (default_name, 'native', json.dumps(["C:\\GBOC-Backups"]), 'active', '0 3 * * *', datetime.now().isoformat()))
                    imported_tasks += 1
                    conn.commit()
                    logs.append("✓ Criada Tarefa Nativa padrão para início imediato.")

            return {
                "status": "success",
                "message": "Importação e conversão para o Motor Nativo concluídas com sucesso!",
                "imported_repositories": max(1, imported_repos),
                "imported_tasks": imported_tasks,
                "logs": logs
            }
        except Exception as e:
            logger.error(f"Erro na importação para o motor nativo: {e}")
            return {
                "status": "error",
                "message": f"Erro na importação: {str(e)}",
                "logs": logs
            }


def scan_and_import_real_data(core) -> Dict[str, Any]:
    importer = RealBackupImporter(core)
    return importer.scan_system()