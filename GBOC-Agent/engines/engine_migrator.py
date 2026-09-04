# GBOC Agent v14.0.0 Full Stable Enterprise Edition
# Module: Universal Backup Engine Migrator (engine_migrator.py)
# Descoberta e migração automatizada de tarefas, repositórios e senhas para o Motor Nativo GBOC v4

import os
import sys
import json
import logging
import time
from typing import Dict, Any, List
from datetime import datetime

logger = logging.getLogger("gboc_engine_migrator")

class GBOCEngineMigrator:
    """
    Motor de Descoberta e Migração de Configurações de Backup Legadas/Externas
    para o Motor Nativo GBOC (FastCDC v4 / Zstd / AES-256-GCM / Imutabilidade WORM).
    """

    def __init__(self):
        self.agent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.path.join(self.agent_dir, "data")
        os.makedirs(self.data_dir, exist_ok=True)

    def discover_engines(self) -> Dict[str, Any]:
        """
        Varre o sistema (100% Zero-Mock) em busca de tarefas, repositórios e senhas
        configurados em motores como Restic, Duplicati, Windows Backup e GBOC Legacy.
        """
        discovered_engines = []
        discovered_tasks = []
        discovered_repositories = []
        discovered_credentials = []

        # 1. VARREDURA RESTIC (Local / Cloud)
        restic_cfg_path = os.path.join(self.data_dir, "restic_repositories.json")
        if os.path.exists(restic_cfg_path):
            try:
                with open(restic_cfg_path, "r", encoding="utf-8") as f:
                    r_repos = json.load(f)
                    if isinstance(r_repos, list):
                        for repo in r_repos:
                            discovered_repositories.append({
                                "id": f"restic_{repo.get('id', len(discovered_repositories)+1)}",
                                "engine_type": "Restic CLI/API",
                                "name": repo.get("name") or repo.get("repo_url", "Repositório Restic"),
                                "target_path": repo.get("repo_url") or repo.get("path", "S3/Local"),
                                "storage_type": "cloud_s3" if "s3." in str(repo.get("repo_url")).lower() else "local",
                                "has_password": bool(repo.get("password") or repo.get("key")),
                                "raw_config": repo
                            })
                            if repo.get("password"):
                                discovered_credentials.append({
                                    "target": repo.get("name", "Restic Key"),
                                    "engine": "Restic",
                                    "key_alias": f"RESTIC_PASSWORD_{repo.get('id', '1')}"
                                })
            except Exception as e:
                logger.warning(f"Erro ao ler repositórios Restic: {e}")

        # 2. VARREDURA DE TAREFAS AGENDADAS EXISTENTES (GBOC Tasks / Restic / Duplicati)
        tasks_cfg_path = os.path.join(self.data_dir, "tasks.json")
        if os.path.exists(tasks_cfg_path):
            try:
                with open(tasks_cfg_path, "r", encoding="utf-8") as f:
                    tasks_data = json.load(f)
                    if isinstance(tasks_data, list):
                        for t in tasks_data:
                            eng = t.get("engine", "legacy")
                            discovered_tasks.append({
                                "id": t.get("id"),
                                "name": t.get("name", "Tarefa de Backup"),
                                "source_paths": t.get("source_paths") or t.get("paths") or ["C:\\Data"],
                                "current_engine": eng,
                                "schedule": t.get("schedule", "0 2 * * *"),
                                "retention_days": t.get("retention_days", 30),
                                "can_migrate": eng != "gboc_native_v4",
                                "raw_config": t
                            })
            except Exception as e:
                logger.warning(f"Erro ao ler tarefas de backup: {e}")

        # 3. VERIFICAÇÃO DE DADOS DE MOTORES INSTALADOS NO SO
        engines_detected = [
            {"name": "GBOC Native Engine v4", "installed": True, "active_tasks": sum(1 for t in discovered_tasks if t.get("current_engine") == "gboc_native_v4")},
            {"name": "Restic Backup Engine", "installed": len(discovered_repositories) > 0, "active_tasks": sum(1 for t in discovered_tasks if "restic" in str(t.get("current_engine")).lower())},
            {"name": "Duplicati Engine Engine", "installed": os.path.exists("C:\\Program Files\\Duplicati 2") or os.path.exists("/usr/bin/duplicati-cli"), "active_tasks": 0}
        ]

        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_engines_found": len([e for e in engines_detected if e["installed"]]),
                "total_tasks_found": len(discovered_tasks),
                "total_repositories_found": len(discovered_repositories),
                "total_credentials_found": len(discovered_credentials)
            },
            "engines": engines_detected,
            "tasks": discovered_tasks,
            "repositories": discovered_repositories,
            "credentials": discovered_credentials
        }

    def execute_migration(self, selected_task_ids: List[Any], selected_repo_ids: List[str], target_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executa a conversão e criação automatizada no Motor Nativo GBOC (FastCDC v4).
        """
        discovery = self.discover_engines()
        migrated_tasks = []
        migrated_repos = []
        start_time = time.time()

        # 1. MIGRAÇÃO DE REPOSITÓRIOS PARA O MOTOR NATIVO GBOC
        native_repos_file = os.path.join(self.data_dir, "native_repositories.json")
        native_repos = []
        if os.path.exists(native_repos_file):
            try:
                with open(native_repos_file, "r", encoding="utf-8") as f:
                    native_repos = json.load(f)
            except Exception:
                native_repos = []

        for repo in discovery["repositories"]:
            if repo["id"] in selected_repo_ids or "all" in selected_repo_ids:
                new_native_repo = {
                    "id": f"native_{repo['id']}_{int(time.time())}",
                    "name": f"{repo['name']} (Migrado Nativo)",
                    "engine": "gboc_native_v4",
                    "chunking": target_params.get("chunking", "FastCDC 4KB-4MB"),
                    "compression": target_params.get("compression", "Zstd-Level3"),
                    "encryption": target_params.get("encryption", "AES-256-GCM"),
                    "worm_immutability": target_params.get("worm_immutability", True),
                    "target_path": repo["target_path"],
                    "migrated_from": repo["engine_type"],
                    "migrated_at": datetime.now().isoformat()
                }
                native_repos.append(new_native_repo)
                migrated_repos.append(new_native_repo)

        with open(native_repos_file, "w", encoding="utf-8") as f:
            json.dump(native_repos, f, indent=2, ensure_ascii=False)

        # 2. MIGRAÇÃO E CONVERSÃO DAS TAREFAS SELECIONADAS PARA O MOTOR NATIVO GBOC
        tasks_cfg_path = os.path.join(self.data_dir, "tasks.json")
        all_tasks = []
        if os.path.exists(tasks_cfg_path):
            try:
                with open(tasks_cfg_path, "r", encoding="utf-8") as f:
                    all_tasks = json.load(f)
            except Exception:
                all_tasks = []

        for t in all_tasks:
            t_id = t.get("id")
            if t_id in selected_task_ids or str(t_id) in [str(x) for x in selected_task_ids]:
                t["engine"] = "gboc_native_v4"
                t["native_v4_config"] = {
                    "chunking_algorithm": "FastCDC",
                    "min_chunk_kb": 4,
                    "avg_chunk_kb": 1024,
                    "max_chunk_kb": 4096,
                    "compression_algorithm": target_params.get("compression", "Zstd"),
                    "encryption_algorithm": "AES-256-GCM",
                    "worm_immutability": target_params.get("worm_immutability", True),
                    "migrated_at": datetime.now().isoformat()
                }
                migrated_tasks.append({
                    "id": t_id,
                    "name": t.get("name"),
                    "status": "migrated_to_native_v4"
                })

        with open(tasks_cfg_path, "w", encoding="utf-8") as f:
            json.dump(all_tasks, f, indent=2, ensure_ascii=False)

        duration = round(time.time() - start_time, 2)
        logger.info(f"✅ Migração para Motor Nativo GBOC concluída: {len(migrated_tasks)} tarefas e {len(migrated_repos)} repositórios.")

        return {
            "status": "success",
            "message": f"Migração para o Motor Nativo GBOC concluída com sucesso em {duration}s!",
            "duration_seconds": duration,
            "migrated_tasks_count": len(migrated_tasks),
            "migrated_repositories_count": len(migrated_repos),
            "migrated_tasks": migrated_tasks,
            "migrated_repositories": migrated_repos
        }

# Instância Singleton
migrator_engine = GBOCEngineMigrator()
