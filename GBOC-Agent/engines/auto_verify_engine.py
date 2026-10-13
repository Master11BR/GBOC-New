# ==============================================================================
# GBOC Agent v14.8.1 Enterprise Edition
# Engine: Universal Auto-Verify Engine (SureRestore On-Completion)
# ==============================================================================

import os
import sys
import shutil
import hashlib
import time
import json
import logging
import threading
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("gboc_auto_verify")

class AutoVerifyEngine:
    """
    Motor de Verificação Universal Pós-Backup.
    Valida automaticamente integridade física, consistência estrutural
    e legibilidade dos snapshots logo após a conclusão de qualquer rotina de backup.
    """

    def __init__(self, core):
        self.core = core
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.sandbox_base = os.path.join(self.base_dir, "data", "sandbox_verify")
        os.makedirs(self.sandbox_base, exist_ok=True)

    def trigger_post_backup_verification_async(self, task_id: int, execution_id: Optional[int] = None):
        """Inicia a auto-verificação em background sem bloquear o encerramento do job."""
        thread = threading.Thread(
            target=self.run_post_backup_verification,
            args=(task_id, execution_id),
            name=f"AutoVerify-Task-{task_id}",
            daemon=True
        )
        thread.start()

    def run_post_backup_verification(self, task_id: int, execution_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Executa a rotina de auto-verificação universal em sandbox isolada.
        """
        t0 = time.perf_counter()
        sandbox_dir = None
        status = "failed"
        details = {}
        error_msg = None

        try:
            # 1. Obter dados da tarefa e repositório
            task = self._get_task(task_id)
            if not task:
                raise ValueError(f"Tarefa {task_id} não encontrada para verificação pós-backup")

            engine_type = (task.get("engine") or "restic").lower()
            task_name = task.get("name") or f"Task-{task_id}"
            repo_id = task.get("repository_id")
            
            logger.info(f"🛡️ [SureRestore] Iniciando auto-verificação pós-backup da tarefa '{task_name}' (Engine: {engine_type})...")

            # 2. Criar sandbox temporária isolada
            exec_tag = execution_id or int(time.time())
            sandbox_dir = os.path.join(self.sandbox_base, f"exec_{task_id}_{exec_tag}")
            os.makedirs(sandbox_dir, exist_ok=True)

            # 3. Execução específica por motor
            if engine_type == "restic":
                details = self._verify_restic(task, repo_id, sandbox_dir)
            elif engine_type == "kopia":
                details = self._verify_kopia(task, repo_id, sandbox_dir)
            elif engine_type == "duplicati":
                details = self._verify_duplicati(task, repo_id, sandbox_dir)
            elif engine_type in ("gboc_native", "native"):
                details = self._verify_native(task, repo_id, sandbox_dir)
            else:
                # Motor genérico / simulação segura de integridade de metadados
                details = self._verify_generic_manifest(task, repo_id, sandbox_dir)

            status = "passed" if details.get("success", False) else "failed"
            error_msg = details.get("error")

        except Exception as e:
            logger.error(f"❌ [SureRestore] Falha na auto-verificação da tarefa {task_id}: {e}")
            status = "failed"
            error_msg = str(e)
            details["error"] = error_msg

        finally:
            elapsed = round((time.perf_counter() - t0), 2)
            
            # 4. Limpeza segura da sandbox
            if sandbox_dir and os.path.exists(sandbox_dir):
                try:
                    shutil.rmtree(sandbox_dir, ignore_errors=True)
                except Exception as ex:
                    logger.warning(f"[SureRestore] Não foi possível remover sandbox temporária {sandbox_dir}: {ex}")

            # 5. Gravação permanente do teste no banco de dados
            self._save_verification_result(repo_id, engine_type, status, elapsed, details, error_msg)

        if status == "passed":
            logger.info(f"✅ [SureRestore] Auto-verificação concluída para Tarefa {task_id}: Status=passed ({elapsed}s)"
                        f" — {details.get('summary') or ''}")
        else:
            logger.warning(f"❌ [SureRestore] Auto-verificação da Tarefa {task_id}: Status=failed ({elapsed}s)"
                           f" — {error_msg or details.get('summary') or 'sem detalhe'}")
        return {
            "task_id": task_id,
            "execution_id": execution_id,
            "status": status,
            "duration_seconds": elapsed,
            "details": details,
            "error": error_msg
        }

    def _get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        with self.core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name, engine, repository_id, source_paths FROM tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
            if row:
                return {
                    "id": row[0],
                    "name": row[1],
                    "engine": row[2],
                    "repository_id": row[3],
                    "source_paths": row[4]
                }
        return None

    def _get_repo_path(self, repo_id: Optional[int]) -> Optional[str]:
        if not repo_id:
            return None
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT path FROM repositories WHERE id = %s", (repo_id,))
                row = cur.fetchone()
                if row and row[0]:
                    return row[0]
        except Exception:
            pass
        return None

    # ── Verificações reais (as mesmas da tela Integridade) ─────────────────────────────────────────────────
    # Antes cada motor só olhava repositories.path como pasta LOCAL: repositório em nuvem (bucket) sempre dava
    # "inacessível" (failed em 0,0 s) e o nativo dava PASSED sem conferir nada.

    def _load_repo(self, repo_id: Optional[int]) -> Dict[str, Any]:
        if not repo_id:
            raise ValueError("Tarefa sem repositório associado")
        with self.core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name, path, motor_password, cloud_password, type, config FROM repositories WHERE id = %s",
                        (repo_id,))
            row = cur.fetchone()
        if not row:
            raise ValueError(f"Repositório {repo_id} não encontrado")
        return {"id": row[0], "name": row[1], "path": row[2], "motor_password": row[3], "cloud_password": row[4],
                "type": row[5], "config": row[6]}

    def _integrity_check(self, engine: str, repo_id: Optional[int]) -> Dict[str, Any]:
        from api import integrity_api as ia
        checks = {"restic": ia._check_restic, "kopia": ia._check_kopia, "duplicati": ia._check_duplicati}
        repo = ia._expand_repo_config(self._load_repo(repo_id))
        r = checks[engine](repo)
        return {"success": bool(r.get("success")), "engine": engine, "method": f"{engine}_integrity_check",
                "summary": r.get("summary"), "output": (r.get("output") or "")[-1500:],
                "error": None if r.get("success") else (r.get("summary") or "verificação falhou")}

    def _verify_restic(self, task: Dict[str, Any], repo_id: Optional[int], sandbox_dir: str) -> Dict[str, Any]:
        """restic check (estrutura, índices e snapshots), local ou nuvem."""
        return self._integrity_check("restic", repo_id)

    def _verify_kopia(self, task: Dict[str, Any], repo_id: Optional[int], sandbox_dir: str) -> Dict[str, Any]:
        """kopia snapshot verify (amostra de arquivos), local ou nuvem."""
        return self._integrity_check("kopia", repo_id)

    def _verify_duplicati(self, task: Dict[str, Any], repo_id: Optional[int], sandbox_dir: str) -> Dict[str, Any]:
        """Acesso ao repositório Duplicati e listagem dos backups."""
        return self._integrity_check("duplicati", repo_id)

    def _verify_native(self, task: Dict[str, Any], repo_id: Optional[int], sandbox_dir: str) -> Dict[str, Any]:
        """Motor nativo: confere se TODOS os blocos de todos os snapshots existem no repositório (local ou nuvem)."""
        from native_engine.engine import GBOCNativeEngine
        repos = getattr(self.core, "repository_manager", None)
        if repos is None:
            raise RuntimeError("RepositoryManager indisponível para a verificação do motor nativo")
        if not repo_id:
            raise ValueError("Tarefa sem repositório associado")
        backend = repos.get_backend(int(repo_id))        # mesmas credenciais e região usadas na restauração
        r = GBOCNativeEngine(task_config={}, storage_backend=backend).verify(read_data=False)
        return {"success": bool(r.get("success")), "engine": "gboc_native", "method": "native_block_presence_check",
                "summary": r.get("summary"), "snapshots": r.get("snapshots"), "chunks_checked": r.get("chunks_checked"),
                "missing": (r.get("missing") or [])[:10],
                "error": None if r.get("success") else r.get("summary")}

    def _verify_generic_manifest(self, task: Dict[str, Any], repo_id: Optional[int], sandbox_dir: str) -> Dict[str, Any]:
        return {"success": False, "engine": task.get("engine", "generic"), "method": "unsupported",
                "error": f"Verificação automática não disponível para o motor {task.get('engine')}"}

    def _save_verification_result(self, repo_id: Optional[int], engine: str, status: str, duration: float, details: Dict[str, Any], error: Optional[str]):
        """Grava na tabela integrity_checks."""
        try:
            with self.core.get_db_connection() as conn:
                try:
                    from api.integrity_api import _ensure_integrity_table
                    _ensure_integrity_table(conn)            # instalação nova: tabela ainda não criada
                except Exception as e:
                    logger.debug(f"[SureRestore] integrity_checks: {e}")
                cur = conn.cursor()
                now = datetime.now()
                summary = (f"SureRestore Auto-Verify: {status.upper()} ({details.get('method', 'check')}) in {duration}s"
                           + (f" — {details.get('summary') or error}" if (details.get('summary') or error) else ""))
                errors_cnt = 0 if status == "passed" else 1
                cur.execute("""
                    INSERT INTO integrity_checks (repository_id, engine, status, started_at, finished_at, result_summary, errors_found, raw_output)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    repo_id,
                    engine,
                    status,
                    now,
                    now,
                    summary,
                    errors_cnt,
                    json.dumps(details)
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"[SureRestore] Erro ao salvar resultado no banco: {e}")
