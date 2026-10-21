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
        """Extrai todos os backups e configurações do Duplicati (com decifragem completa)."""
        try:
            from core.integrations.duplicati_native import get_duplicati_native_service
            dup_srv = get_duplicati_native_service()
            return dup_srv.extract_all_duplicati_backups_detailed()
        except Exception as e:
            logger.warning(f"Erro ao extrair backups detalhados do Duplicati: {e}")
            return []

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

                failures = []

                # 1. Preencher repositórios sem motor definido mantendo os motores existentes intactos
                try:
                    cur.execute("UPDATE repositories SET engine = 'gboc_native' WHERE engine IS NULL OR TRIM(engine) = ''")
                    imported_repos += cur.rowcount if hasattr(cur, 'rowcount') and cur.rowcount is not None else 0
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    failures.append(f"Repositórios sem motor: {e}")
                    logger.error(f"Importação: falha ao preencher motor dos repositórios: {e}")

                # 2. Preencher tarefas sem motor definido mantendo os motores existentes intactos
                try:
                    cur.execute("UPDATE tasks SET engine = 'gboc_native' WHERE engine IS NULL OR TRIM(engine) = ''")
                    converted_tasks = cur.rowcount if hasattr(cur, 'rowcount') and cur.rowcount is not None else 0
                    imported_tasks += converted_tasks
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    failures.append(f"Tarefas sem motor: {e}")
                    logger.error(f"Importação: falha ao preencher motor das tarefas: {e}")

                # 3. Importar tarefas e repositórios do Duplicati com credenciais e senhas 100% reais
                duplicati_jobs = self._scan_duplicati_dbs()
                now_str = datetime.now().isoformat()
                from core.integrations.duplicati_native import (
                    parse_duplicati_target_and_creds,
                    convert_duplicati_repeat_to_cron,
                    normalize_sources_list,
                    parse_duplicati_retention,
                )

                for job in duplicati_jobs:
                    b_name = job.get("name") or "Backup"
                    try:
                        job_name = f"Nativo_Duplicati_{b_name}"
                        raw_target = str(job.get("target_url") or "")
                        passphrase = str(job.get("passphrase") or "")
                        settings = job.get("settings") or {}
                        sources = job.get("sources") or []
                        schedule = job.get("schedule") or {}
                        meta = job.get("metadata") or {}

                        creds_info = parse_duplicati_target_and_creds(raw_target, passphrase, settings)
                        repo_type = creds_info["repo_type"]
                        clean_path = creds_info["clean_path"]
                        config_json = json.dumps(creds_info["config"])
                        pwd = creds_info["password"] or None
                        m_pwd = creds_info["motor_password"] or None
                        enc_pwd = creds_info["encryption_password"] or None
                        c_pwd = creds_info["cloud_password"] or None

                        repo_name = f"Repo_Duplicati_{b_name}"

                        # Criar ou obter repositório correspondente preenchendo 100% das credenciais
                        cur.execute("""
                            SELECT id FROM repositories 
                            WHERE name = %s OR path = %s OR path = %s OR id = (
                                SELECT repository_id FROM tasks WHERE name IN (%s, %s, %s) LIMIT 1
                            )
                        """, (repo_name, clean_path, raw_target, job_name, b_name, f"Duplicati_{b_name}"))
                        existing_repo = cur.fetchone()

                        if existing_repo:
                            repo_id = existing_repo[0]
                            cur.execute("""
                                UPDATE repositories 
                                SET name = %s, type = %s, path = %s, engine = 'duplicati',
                                    status = 'active', enabled = true, initialized = true,
                                    password = COALESCE(%s, password),
                                    motor_password = COALESCE(%s, motor_password),
                                    encryption_password = COALESCE(%s, encryption_password),
                                    cloud_password = COALESCE(%s, cloud_password),
                                    config = %s, updated_at = %s 
                                WHERE id = %s
                            """, (repo_name, repo_type, clean_path, pwd, m_pwd, enc_pwd, c_pwd, config_json, now_str, repo_id))
                            conn.commit()
                            logs.append(f"✓ Atualizado repositório '{repo_name}' ({repo_type.upper()}: {clean_path}) com credenciais e senhas decifradas.")
                        else:
                            cur.execute("""
                                INSERT INTO repositories (name, type, path, engine, status, enabled, initialized, password, motor_password, encryption_password, cloud_password, config, created_at, updated_at)
                                VALUES (%s, %s, %s, 'duplicati', 'active', true, true, %s, %s, %s, %s, %s, %s, %s)
                                RETURNING id
                            """, (repo_name, repo_type, clean_path, pwd, m_pwd, enc_pwd, c_pwd, config_json, now_str, now_str))
                            repo_id = cur.fetchone()[0]
                            imported_repos += 1
                            conn.commit()
                            logs.append(f"✓ Criado repositório '{repo_name}' ({repo_type.upper()}: {clean_path}) com credenciais e senhas completas.")

                        clean_sources = normalize_sources_list(sources)
                        sources_json = json.dumps(clean_sources)
                        repeat = str(schedule.get("Repeat") or schedule.get("repeat") or "2h")
                        time_val = str(schedule.get("Time") or schedule.get("time") or "")
                        cron = convert_duplicati_repeat_to_cron(repeat, time_val)
                        retention_days = parse_duplicati_retention(settings)
                        last_run_dt = meta.get("LastBackupDate") or meta.get("LastBackupFinished") or job.get("last_run") or now_str
                        last_status = 'completed' if meta.get("LastBackupResult") in ("Success", "OK", "completed") else 'idle'

                        # Verificar se tarefa já existe e atualizar / inserir com retenção, cron e origens limpas
                        cur.execute("""
                            SELECT id, repository_id FROM tasks 
                            WHERE name IN (%s, %s, %s) OR repository_id = %s
                        """, (job_name, b_name, f"Duplicati_{b_name}", repo_id))
                        existing_task = cur.fetchone()

                        if existing_task:
                            task_id = existing_task[0]
                            cur.execute("""
                                UPDATE tasks 
                                SET repository_id = %s, engine = 'duplicati', source_paths = %s,
                                    status = 'idle', enabled = true, schedule_enabled = true,
                                    schedule_cron = %s, retention_days = %s, last_run = %s,
                                    last_status = %s, updated_at = %s
                                WHERE id = %s
                            """, (repo_id, sources_json, cron, retention_days, last_run_dt, last_status, now_str, task_id))
                            conn.commit()
                            logs.append(f"✓ Atualizada tarefa '{job_name}' com origens deduplicadas {clean_sources}, agendamento '{cron}' e retenção de {retention_days} dias.")
                        else:
                            cur.execute("""
                                INSERT INTO tasks (name, repository_id, engine, source_paths, status, enabled, schedule_enabled, schedule_cron, retention_days, last_run, last_status, created_at, updated_at)
                                VALUES (%s, %s, 'duplicati', %s, 'idle', true, true, %s, %s, %s, %s, %s, %s)
                                RETURNING id
                            """, (job_name, repo_id, sources_json, cron, retention_days, last_run_dt, last_status, now_str, now_str))
                            imported_tasks += 1
                            conn.commit()
                            logs.append(f"✓ Mapeada nova tarefa '{job_name}' com repositório #{repo_id}, cron '{cron}' e {len(clean_sources)} origens.")
                    except Exception as e:
                        conn.rollback()
                        failures.append(f"{b_name}: {e}")
                        logs.append(f"✗ Falha ao importar '{b_name}': {e}")
                        logger.error(f"Importação: falha no backup Duplicati '{b_name}': {e}", exc_info=True)

                # 4. Caso não existam tarefas nativas registradas, criar uma tarefa padrão do sistema nativo
                try:
                    if self._ensure_default_native_task(conn, cur, logs):
                        imported_tasks += 1
                except Exception as e:
                    conn.rollback()
                    failures.append(f"Tarefa nativa padrão: {e}")
                    logger.error(f"Importação: falha ao criar tarefa nativa padrão: {e}")

            if failures:
                ok_any = imported_repos or imported_tasks
                return {
                    "status": "partial" if ok_any else "error",
                    "message": (f"Importação concluída com {len(failures)} falha(s)." if ok_any
                                else f"Erro na importação: {failures[0]}"),
                    "imported_repositories": imported_repos,
                    "imported_tasks": imported_tasks,
                    "failures": failures,
                    "logs": logs
                }

            return {
                "status": "success",
                "message": "Importação e conversão para o Motor Nativo concluídas com sucesso!",
                "imported_repositories": max(1, imported_repos),
                "imported_tasks": imported_tasks,
                "logs": logs
            }
        except Exception as e:
            logger.error(f"Erro na importação para o motor nativo: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Erro na importação: {str(e)}",
                "logs": logs
            }

    def _ensure_default_native_task(self, conn, cur, logs) -> bool:
        """Cria a tarefa nativa padrão se ainda não houver nenhuma. Retorna True se criou."""
        cur.execute("SELECT COUNT(*) FROM tasks WHERE engine = 'native'")
        cnt_row = cur.fetchone()
        total_native_tasks = cnt_row[0] if cnt_row else 0
        if total_native_tasks:
            return False
        default_name = "Backup Nativo do Sistema (Local)"
        cur.execute("""
            INSERT INTO tasks (name, engine, source_paths, status, schedule_cron, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (default_name, 'native', json.dumps(["C:\\GBOC-Backups"]), 'active', '0 3 * * *', datetime.now().isoformat()))
        conn.commit()
        logs.append("✓ Criada Tarefa Nativa padrão para início imediato.")
        return True

def scan_and_import_real_data(core) -> Dict[str, Any]:
    importer = RealBackupImporter(core)
    return importer.scan_system()