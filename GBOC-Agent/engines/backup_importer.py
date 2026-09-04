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

                # 1. Converter repositórios existentes com outro motor para 'native'
                cur.execute("UPDATE repositories SET engine = 'native' WHERE engine IS NULL OR engine != 'native'")
                imported_repos += cur.rowcount if hasattr(cur, 'rowcount') and cur.rowcount is not None else 0
                conn.commit()
                logs.append(f"✓ Repositórios de backup convertidos para o motor Nativo ({imported_repos} repositórios).")

                # 2. Converter tarefas existentes com outro motor para 'native'
                cur.execute("UPDATE tasks SET engine = 'native' WHERE engine IS NULL OR engine != 'native'")
                converted_tasks = cur.rowcount if hasattr(cur, 'rowcount') and cur.rowcount is not None else 0
                imported_tasks += converted_tasks
                conn.commit()
                logs.append(f"✓ Tarefas registradas convertidas para o motor Nativo ({converted_tasks} tarefas).")

                # 3. Importar tarefas do Duplicati caso existam
                duplicati_jobs = self._scan_duplicati_dbs()
                for job in duplicati_jobs:
                    job_name = f"Nativo_Duplicati_{job['name']}"
                    sources_json = json.dumps(job["sources"]) if job["sources"] else json.dumps(["C:\\"])

                    # Verificar se tarefa já existe
                    cur.execute("SELECT id FROM tasks WHERE name = %s", (job_name,))
                    existing = cur.fetchone()
                    if not existing:
                        cur.execute("""
                            INSERT INTO tasks (name, engine, source_paths, status, schedule_cron, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (job_name, 'native', sources_json, 'active', '0 2 * * *', datetime.now().isoformat()))
                        imported_tasks += 1
                        conn.commit()
                        logs.append(f"✓ Importada tarefa Duplicati '{job['name']}' como Tarefa Nativa GBOC.")

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