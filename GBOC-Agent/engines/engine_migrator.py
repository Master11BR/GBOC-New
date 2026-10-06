# GBOC Agent v14.8.1 Full Stable Enterprise Edition
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

NATIVE_ENGINES = ('gboc_native', 'native', 'gboc', 'gboc_native_v4', 'gboc native')


class GBOCEngineMigrator:
    """
    Migração de tarefas de motores externos (Restic, Kopia, Duplicati) para o Motor Nativo GBOC.

    Zero-Mock: lê e grava somente no banco do Agente (tabelas ``tasks`` e ``repositories``).
    A migração troca o motor da tarefa e aponta para um repositório nativo; os backups antigos
    permanecem intactos no repositório de origem (continuam disponíveis para restauração).
    """

    def _conn(self):
        from shared_core import get_shared_core
        return get_shared_core().get_db_connection()

    @staticmethod
    def _is_native(engine: Any) -> bool:
        return str(engine or '').strip().lower() in NATIVE_ENGINES

    def discover_engines(self) -> Dict[str, Any]:
        tasks: List[Dict[str, Any]] = []
        repositories: List[Dict[str, Any]] = []
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT t.id, t.name, COALESCE(t.engine, ''), t.repository_id, r.name, t.source_paths,
                       t.schedule_enabled, t.schedule_cron, t.retention_days, t.enabled
                FROM tasks t LEFT JOIN repositories r ON r.id = t.repository_id
                ORDER BY t.name
            """)
            for row in cur.fetchall():
                engine = row[2] or ''
                tasks.append({
                    "id": row[0],
                    "name": row[1],
                    "current_engine": engine or 'não definido',
                    "repository_id": row[3],
                    "repository_name": row[4],
                    "source_paths": [p for p in str(row[5] or '').replace(';', '\n').splitlines() if p.strip()],
                    "schedule": row[7] if row[6] else None,
                    "retention_days": row[8],
                    "enabled": bool(row[9]),
                    "can_migrate": not self._is_native(engine),
                })
            cur.execute("""
                SELECT id, name, type, path, COALESCE(engine, ''), initialized, status,
                       (COALESCE(password, '') <> '' OR COALESCE(motor_password, '') <> ''
                        OR COALESCE(encryption_password, '') <> '') AS has_password
                FROM repositories ORDER BY name
            """)
            for row in cur.fetchall():
                repositories.append({
                    "id": row[0],
                    "name": row[1],
                    "type": row[2],
                    "target_path": row[3],
                    "engine_type": row[4] or 'não definido',
                    "initialized": bool(row[5]),
                    "status": row[6],
                    "has_password": bool(row[7]),
                    "is_native": self._is_native(row[4]),
                })
            cur.close()

        by_engine: Dict[str, int] = {}
        for t in tasks:
            by_engine[t["current_engine"]] = by_engine.get(t["current_engine"], 0) + 1
        legacy_tasks = [t for t in tasks if t["can_migrate"]]
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_engines_found": len(by_engine),
                "total_tasks_found": len(tasks),
                "legacy_tasks_found": len(legacy_tasks),
                "total_repositories_found": len(repositories),
                "native_repositories_found": sum(1 for r in repositories if r["is_native"]),
                # Senhas nunca são expostas: só a contagem de repositórios que possuem senha salva
                "total_credentials_found": sum(1 for r in repositories if r["has_password"]),
            },
            "engines": [{"name": k, "tasks": v, "native": self._is_native(k)} for k, v in sorted(by_engine.items())],
            "tasks": tasks,
            "repositories": repositories,
            "native_repositories": [r for r in repositories if r["is_native"]],
            "credentials": [{"target": r["name"], "engine": r["engine_type"], "key_alias": "senha salva no repositório"}
                            for r in repositories if r["has_password"]],
        }

    def _create_native_repository(self, name: str, motor_password: str) -> Dict[str, Any]:
        from shared_core import get_shared_core
        from engines.repository_manager import RepositoryManager
        rm = RepositoryManager(get_shared_core())
        return rm.create_repository({
            "name": name,
            "type": "local",
            "engine": "gboc_native",
            "motor_password": motor_password,
        })

    def execute_migration(self, selected_task_ids: List[Any], selected_repo_ids: List[str],
                          target_params: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        target_params = target_params or {}
        task_ids = []
        for x in selected_task_ids or []:
            try:
                task_ids.append(int(x))
            except (TypeError, ValueError):
                continue
        if not task_ids:
            return {"status": "error", "message": "Selecione ao menos uma tarefa para migrar."}

        # 1. Repositório nativo de destino: existente ou criado agora
        target_repo_id = target_params.get("target_repository_id")
        created_repo = None
        if not target_repo_id:
            new_name = (target_params.get("new_repository_name") or "").strip()
            pwd = str(target_params.get("motor_password") or "")
            if not new_name:
                return {"status": "error", "message": "Escolha um repositório nativo de destino ou informe o nome de um novo."}
            try:
                created_repo = self._create_native_repository(new_name, pwd)
            except Exception as exc:
                return {"status": "error", "message": f"Falha ao criar o repositório nativo: {exc}"}
            target_repo_id = (created_repo or {}).get("id") or (created_repo or {}).get("repository", {}).get("id")
            if not target_repo_id:
                with self._conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id FROM repositories WHERE name = %s", (new_name,))
                    row = cur.fetchone()
                    cur.close()
                target_repo_id = row[0] if row else None
            if not target_repo_id:
                return {"status": "error", "message": "Repositório nativo criado, mas o ID não foi encontrado."}

        migrated, skipped = [], []
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name, engine FROM repositories WHERE id = %s", (int(target_repo_id),))
            repo = cur.fetchone()
            if not repo or not self._is_native(repo[2]):
                cur.close()
                return {"status": "error", "message": "O repositório de destino não existe ou não usa o Motor Nativo GBOC."}

            cur.execute("SELECT id, name, engine, repository_id FROM tasks WHERE id = ANY(%s)", (task_ids,))
            rows = cur.fetchall()
            found = {r[0] for r in rows}
            for tid in task_ids:
                if tid not in found:
                    skipped.append({"id": tid, "reason": "tarefa não encontrada"})
            for tid, tname, engine, old_repo in rows:
                if self._is_native(engine):
                    skipped.append({"id": tid, "name": tname, "reason": "já usa o Motor Nativo"})
                    continue
                cur.execute("UPDATE tasks SET engine = 'gboc_native', repository_id = %s, updated_at = %s WHERE id = %s",
                            (repo[0], datetime.now(), tid))
                migrated.append({"id": tid, "name": tname, "from_engine": engine,
                                 "from_repository_id": old_repo, "to_repository": repo[1]})
            # Trilha de auditoria (não bloqueia a migração se a tabela tiver outro formato)
            cur.execute("SAVEPOINT gboc_mig_audit")
            try:
                cur.execute(
                    "INSERT INTO audit_log (action, resource_type, resource_id, resource_name, detail, username) "
                    "VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
                    ("engine_migration", "repository", str(repo[0]), repo[1],
                     json.dumps({"migrated": migrated, "skipped": skipped}, default=str),
                     str(target_params.get("requested_by") or "gboc-server")))
                cur.execute("RELEASE SAVEPOINT gboc_mig_audit")
            except Exception as exc:
                cur.execute("ROLLBACK TO SAVEPOINT gboc_mig_audit")
                logger.warning(f"Auditoria da migração não registrada: {exc}")
            conn.commit()
            cur.close()

        duration = round(time.time() - start_time, 2)
        logger.info(f"Migração para Motor Nativo: {len(migrated)} tarefa(s) -> repositório '{repo[1]}'")
        return {
            "status": "success" if migrated else "warning",
            "message": (f"{len(migrated)} tarefa(s) passam a usar o Motor Nativo GBOC no repositório '{repo[1]}' "
                        f"a partir da próxima execução. Os backups antigos continuam no repositório de origem."
                        if migrated else "Nenhuma tarefa foi alterada."),
            "duration_seconds": duration,
            "target_repository": {"id": repo[0], "name": repo[1], "created_now": bool(created_repo)},
            "migrated_tasks_count": len(migrated),
            "migrated_tasks": migrated,
            "skipped": skipped,
        }

# Instância Singleton
migrator_engine = GBOCEngineMigrator()
