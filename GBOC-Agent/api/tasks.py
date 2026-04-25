#!/usr/bin/env python3
"""
GBOC Agent - API Tasks (estabilizada)
- Normaliza source_paths (aceita texto com linhas, JSON list, list real, ';')
- Mantém rotas essenciais para UI (list, create, update, delete, run, history, execution, running, status)
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Union
import psycopg2
import logging
import json
from datetime import datetime

try:
    from models import TaskCreate, TaskUpdate
except ImportError:
    class TaskCreate(BaseModel):
        name: str
        type: str = "backup"
        source_paths: Union[str, List[str]]
        repository_id: int
        storage_type: Optional[str] = None  # Novo campo para tipo de armazenamento
        engine: str = "restic"
        schedule_enabled: bool = False
        schedule_cron: Optional[str] = None

    class TaskUpdate(BaseModel):
        name: Optional[str] = None
        source_paths: Optional[Union[str, List[str]]] = None
        enabled: Optional[bool] = None
        schedule_enabled: Optional[bool] = None
        schedule_cron: Optional[str] = None
        engine: Optional[str] = None
        storage_type: Optional[str] = None  # Novo campo para tipo de armazenamento

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _normalize_source_paths(value: Union[str, List[str], None]) -> str:
    """
    Normaliza source_paths para JSON string de lista (formato que o TaskManager entende).
    Aceita:
      - list[str]
      - str JSON (ex: '["C:\\\\x"]')
      - str simples (ex: 'C:\\x')
      - str com '\\n' ou ';' (ex: 'C:\\x\\nD:\\y' ou 'C:\\x;D:\\y')
    """
    if value is None:
        return json.dumps([], ensure_ascii=False)

    if isinstance(value, list):
        paths = [str(p).strip() for p in value if str(p).strip()]
        return json.dumps(paths, ensure_ascii=False)

    raw = str(value).strip()
    if not raw:
        return json.dumps([], ensure_ascii=False)

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            paths = [str(p).strip() for p in parsed if str(p).strip()]
            return json.dumps(paths, ensure_ascii=False)
    except Exception:
        pass

    parts: List[str] = []
    for line in raw.replace("\r", "\n").split("\n"):
        parts.extend(line.split(";"))

    paths = [p.strip() for p in parts if p.strip()]
    return json.dumps(paths, ensure_ascii=False)


@router.get("/")
async def list_tasks() -> Dict[str, Any]:
    """Lista todas as tarefas"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT t.*, r.name as repository_name, r.type as repository_type, r.engine as repository_engine
                    FROM tasks t
                    LEFT JOIN repositories r ON t.repository_id = r.id
                    ORDER BY t.id
                """)
            except Exception:
                # Compatibilidade com schema legado sem coluna r.engine
                cursor.execute("""
                    SELECT t.*, r.name as repository_name, r.type as repository_type
                    FROM tasks t
                    LEFT JOIN repositories r ON t.repository_id = r.id
                    ORDER BY t.id
                """)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            tasks = [dict(zip(columns, row)) for row in rows]

        return {"status": "success", "tasks": tasks, "count": len(tasks)}
    except Exception as e:
        logger.error(f"❌ List tasks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/")
async def create_task(task: TaskCreate, request: Request) -> Dict[str, Any]:
    """Cria nova tarefa (normaliza source_paths)"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not getattr(core, "task_manager", None):
            logger.error("❌ TaskManager não disponível no create_task. Verifique logs de inicialização.")
            raise HTTPException(status_code=503, detail="TaskManager não está disponível. Verifique os logs do agente.")

        payload = task.model_dump() if hasattr(task, "model_dump") else task.dict()
        payload["source_paths"] = _normalize_source_paths(payload.get("source_paths"))

        result = core.task_manager.create_task(payload)
        try:
            from api.audit_api import audit_task_action
            from api.auth import get_current_user
            u = get_current_user(request) or {}
            audit_task_action('create', int(result.get('id') or 0), payload.get('name') or 'task', username=u.get('username', 'system'), detail={'repository_id': payload.get('repository_id'), 'engine': payload.get('engine')})
        except Exception:
            pass
        return result

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        if "integrityerror" in str(e).lower() or "unique constraint" in str(e).lower():
            raise HTTPException(status_code=409, detail="Conflito ao criar tarefa")
        logger.error(f"❌ Erro na API de criação de tarefa: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# IMPORTANT: All static routes MUST be defined BEFORE dynamic
# /{task_id} routes to prevent FastAPI from matching "status",
# "running", etc. as task_id integers and returning 422.
# ============================================================

@router.get("/status")
async def get_tasks_status() -> Dict[str, Any]:
    """Lista todas as tarefas com status atual (para aba Sistema)"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    te.id as execution_id,
                    te.task_id,
                    t.name as task_name,
                    r.name as repository_name,
                    te.status,
                    te.started_at,
                    te.completed_at,
                    te.files_processed,
                    te.bytes_processed,
                    te.progress,
                    te.error_message
                FROM task_executions te
                JOIN tasks t ON te.task_id = t.id
                LEFT JOIN repositories r ON t.repository_id = r.id
                WHERE te.status IN ('running', 'failed', 'completed')
                AND te.started_at >= (NOW() - INTERVAL '24 hours')
                ORDER BY te.started_at DESC
                LIMIT 50
            """)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            tasks = [dict(zip(columns, row)) for row in rows]

            formatted_tasks = []
            for task in tasks:
                started = task.get("started_at")
                formatted_tasks.append({
                    "id": task["execution_id"],
                    "name": task["task_name"] or f"Tarefa {task['task_id']}",
                    "status": task["status"],
                    "started_at": started.isoformat() if hasattr(started, 'isoformat') else str(started) if started else None,
                    "repository": task["repository_name"] or "N/A",
                    "error_message": task.get("error_message")
                })

        return {"status": "success", "tasks": formatted_tasks}
    except Exception as e:
        logger.error(f"❌ Tasks status: {e}", exc_info=True)
        return {"status": "success", "tasks": []}


@router.get("/system/errors/recent")
async def get_recent_task_errors(limit: int = 100) -> Dict[str, Any]:
    """Retorna histórico recente de falhas de execução com detalhes."""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT te.id as execution_id, te.task_id, t.name as task_name, t.engine,
                       te.status, te.started_at, te.completed_at,
                       te.error_message, te.progress, te.files_processed, te.bytes_processed
                FROM task_executions te
                LEFT JOIN tasks t ON te.task_id = t.id
                WHERE te.status IN ('failed', 'error', 'cancelled', 'interrupted')
                ORDER BY te.started_at DESC
                LIMIT %s
            """, (limit,))
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            items = [dict(zip(columns, row)) for row in rows]

        return {"status": "success", "errors": items, "count": len(items)}
    except Exception as e:
        logger.error(f"❌ Recent task errors: {e}", exc_info=True)
        return {"status": "error", "message": str(e), "errors": [], "count": 0}


@router.get("/system/errors/report")
async def get_task_errors_report(days: int = 7) -> Dict[str, Any]:
    """Relatório agregado de falhas de tarefas por engine/tarefa."""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COALESCE(t.engine, 'unknown') as engine, COUNT(*)
                FROM task_executions te
                LEFT JOIN tasks t ON te.task_id = t.id
                WHERE te.status IN ('failed', 'error', 'cancelled', 'interrupted')
                  AND te.started_at >= (NOW() - (%s || ' days')::interval)
                GROUP BY COALESCE(t.engine, 'unknown')
                ORDER BY COUNT(*) DESC
            """, (days,))
            by_engine = [{"engine": r[0], "count": r[1]} for r in cursor.fetchall()]

            cursor.execute("""
                SELECT te.task_id, COALESCE(t.name, 'Task ' || te.task_id::text) as task_name,
                       COALESCE(t.engine, 'unknown') as engine, COUNT(*) as failures,
                       MAX(te.started_at) as last_failure,
                       MAX(te.error_message) as last_error
                FROM task_executions te
                LEFT JOIN tasks t ON te.task_id = t.id
                WHERE te.status IN ('failed', 'error', 'cancelled', 'interrupted')
                  AND te.started_at >= (NOW() - (%s || ' days')::interval)
                GROUP BY te.task_id, COALESCE(t.name, 'Task ' || te.task_id::text), COALESCE(t.engine, 'unknown')
                ORDER BY failures DESC
                LIMIT 50
            """, (days,))
            by_task = []
            for row in cursor.fetchall():
                by_task.append({
                    "task_id": row[0],
                    "task_name": row[1],
                    "engine": row[2],
                    "failures": row[3],
                    "last_failure": row[4].isoformat() if hasattr(row[4], 'isoformat') else row[4],
                    "last_error": row[5]
                })

        total_failures = sum(x["count"] for x in by_engine)
        return {
            "status": "success",
            "period_days": days,
            "total_failures": total_failures,
            "by_engine": by_engine,
            "top_tasks": by_task
        }
    except Exception as e:
        logger.error(f"❌ Task errors report: {e}", exc_info=True)
        return {"status": "error", "message": str(e), "period_days": days, "total_failures": 0, "by_engine": [], "top_tasks": []}


# ============================================================
# Dynamic routes below — /{task_id} catches any path segment
# ============================================================

@router.get("/running/detailed")
async def get_running_tasks_detailed() -> Dict[str, Any]:
    """Retorna execuções em andamento com detalhes para UI de tarefas."""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT te.id as execution_id, te.task_id, te.status,
                       te.started_at, te.completed_at,
                       te.progress, te.files_processed, te.bytes_processed,
                       te.current_file, te.error_message,
                       t.name as task_name
                FROM task_executions te
                LEFT JOIN tasks t ON te.task_id = t.id
                WHERE te.status = 'running'
                ORDER BY te.started_at DESC
            """)
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            executions = [dict(zip(cols, row)) for row in rows]

            for ex in executions:
                for dt_field in ("started_at", "completed_at"):
                    v = ex.get(dt_field)
                    if hasattr(v, 'isoformat'):
                        ex[dt_field] = v.isoformat()

        return {"status": "success", "executions": executions, "count": len(executions)}
    except Exception as e:
        logger.error(f"❌ Running detailed: {e}", exc_info=True)
        return {"status": "success", "executions": [], "count": 0}

@router.get("/{task_id}")
async def get_task(task_id: int) -> Dict[str, Any]:
    """Obtém tarefa por ID"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT t.*, r.name as repository_name, r.type as repository_type
                FROM tasks t
                LEFT JOIN repositories r ON t.repository_id = r.id
                WHERE t.id = %s
                """,
                (task_id,),
            )
            row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Tarefa não encontrada")

        # Para PostgreSQL, converter tupla para dicionário
        columns = [desc[0] for desc in cursor.description]
        task_dict = dict(zip(columns, row))
        return {"status": "success", "task": task_dict}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{task_id}")
async def update_task(task_id: int, task: TaskUpdate, request: Request) -> Dict[str, Any]:
    """Atualiza tarefa (normaliza source_paths quando presente)"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not getattr(core, "task_manager", None):
            raise HTTPException(status_code=503, detail="TaskManager não está disponível")

        payload = task.model_dump(exclude_unset=True) if hasattr(task, "model_dump") else task.dict(exclude_unset=True)

        if "source_paths" in payload and payload["source_paths"] is not None:
            payload["source_paths"] = _normalize_source_paths(payload["source_paths"])

        result = core.task_manager.update_task(task_id, payload)
        try:
            from api.audit_api import audit_task_action
            from api.auth import get_current_user
            u = get_current_user(request) or {}
            audit_task_action('update', task_id, payload.get('name') or f'Task {task_id}', username=u.get('username', 'system'), detail={'fields': list(payload.keys())})
        except Exception:
            pass
        return result

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Update task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{task_id}")
async def delete_task(task_id: int, request: Request) -> Dict[str, Any]:
    """Deleta tarefa"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not getattr(core, "task_manager", None):
            raise HTTPException(status_code=503, detail="TaskManager não está disponível")

        result = core.task_manager.delete_task(task_id)
        try:
            from api.audit_api import audit_task_action
            from api.auth import get_current_user
            u = get_current_user(request) or {}
            audit_task_action('delete', task_id, f'Task {task_id}', username=u.get('username', 'system'))
        except Exception:
            pass
        return result

    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"❌ Delete task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{task_id}/run")
async def run_task(task_id: int, request: Request) -> Dict[str, Any]:
    """Coloca uma tarefa na fila para execução e cria um registro em task_executions"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not getattr(core, "task_manager", None):
            raise HTTPException(status_code=503, detail="TaskManager não está disponível")

        now = datetime.now().isoformat()

        @core.db_retry(max_retries=10, delay=0.3)
        def _execute_run_task():
            with core.get_db_connection() as conn:
                cursor = conn.cursor()
                # Verifica se existe
                cursor.execute("SELECT id, name FROM tasks WHERE id = %s", (task_id,))
                task_row = cursor.fetchone()
                if not task_row:
                    return None, None

                # Criar execução (tentar schema novo primeiro)
                exec_id = None
                try:
                    cursor.execute("""
                        INSERT INTO task_executions (task_id, status, started_at, files_processed, bytes_processed, progress)
                        VALUES (%s, 'running', %s, 0, 0, 0)
                    """, (task_id, now))
                    # Para PostgreSQL, usar cursor.fetchone() para obter o ID
                    cursor.execute("SELECT LASTVAL()")
                    exec_id = cursor.fetchone()[0]
                except psycopg2.OperationalError as e:
                    if "locked" in str(e).lower(): raise # Deixa o db_retry lidar
                    # Se for erro de schema (coluna progress faltando), tenta fallback
                    conn.rollback()
                    logger.warning(f"⚠️ Fallback schema antigo task_executions: {e}")
                    cursor.execute("""
                        INSERT INTO task_executions (task_id, status, started_at, files_processed, bytes_processed)
                        VALUES (%s, 'running', %s, 0, 0)
                    """, (task_id, now))
                    cursor.execute("SELECT LASTVAL()")
                    exec_id = cursor.fetchone()[0]
                except Exception as insert_err:
                    # Fallback para outros erros (ex: coluna faltando)
                    conn.rollback()
                    logger.warning(f"⚠️ Fallback schema antigo task_executions (erro genérico): {insert_err}")
                    cursor.execute("""
                        INSERT INTO task_executions (task_id, status, started_at, files_processed, bytes_processed)
                        VALUES (%s, 'running', %s, 0, 0)
                    """, (task_id, now))
                    cursor.execute("SELECT LASTVAL()")
                    exec_id = cursor.fetchone()[0]

                cursor.execute("UPDATE tasks SET status = 'running' WHERE id = %s", (task_id,))
                conn.commit()
                return exec_id, task_row[1]  # name é o segundo campo (índice 1)

        exec_id, task_name = _execute_run_task()
        
        if exec_id is None:
            raise HTTPException(status_code=404, detail="Tarefa não encontrada")

        core.task_manager.queue_task(task_id, exec_id)

        try:
            from api.audit_api import audit_task_action
            from api.auth import get_current_user
            u = get_current_user(request) or {}
            audit_task_action('run', task_id, task_name or f'Task {task_id}', username=u.get('username', 'system'), detail={'execution_id': exec_id})
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"Tarefa '{task_name}' adicionada à fila.",
            "execution_id": exec_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Run task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execution/{execution_id}/stop")
async def stop_task(execution_id: int) -> Dict[str, Any]:
    """Para uma tarefa em execução"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not getattr(core, "task_manager", None):
            raise HTTPException(status_code=503, detail="TaskManager não está disponível")

        # Usar force_stop_task para garantir que tarefas travadas/zumbis sejam limpas
        result = core.task_manager.force_stop_task(execution_id)
        if result.get("status") == "error":
            raise HTTPException(status_code=404, detail=result.get("message", "Execução não encontrada"))
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Stop task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}/history")
async def get_task_history(task_id: int, limit: int = 20) -> Dict[str, Any]:
    """Histórico de execuções"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            # Preferir started_at; se não existir, cai para start_time
            try:
                cursor.execute("""
                    SELECT * FROM task_executions
                    WHERE task_id = %s
                    ORDER BY started_at DESC
                    LIMIT %s
                """, (task_id, limit))
            except Exception:
                cursor.execute("""
                    SELECT * FROM task_executions
                    WHERE task_id = %s
                    ORDER BY start_time DESC
                    LIMIT %s
                """, (task_id, limit))

            rows = cursor.fetchall()
            # Para PostgreSQL, converter tuplas para dicionários
            columns = [desc[0] for desc in cursor.description]
            history = [dict(zip(columns, row)) for row in rows]

        return {"status": "success", "history": history, "count": len(history)}
    except Exception as e:
        logger.error(f"❌ Task history: {e}", exc_info=True)
        return {"status": "success", "history": [], "count": 0}


@router.get("/execution/{exec_id}")
async def get_execution_status(exec_id: int) -> Dict[str, Any]:
    """Status de uma execução"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT te.*, t.name as task_name
                FROM task_executions te
                LEFT JOIN tasks t ON te.task_id = t.id
                WHERE te.id = %s
            """, (exec_id,))
            row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Execução não encontrada")

        # Para PostgreSQL, converter tupla para dicionário
        columns = [desc[0] for desc in cursor.description]
        execution = dict(zip(columns, row))
        return {
            "status": execution.get("status", "unknown"),
            "execution": execution,
            "error_message": execution.get("error_message"),
            "progress": execution.get("progress", 0),
            "current_file": execution.get("current_file"),
            "files_processed": execution.get("files_processed", 0),
            "bytes_processed": execution.get("bytes_processed", 0),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get execution: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.get("/{task_id}/status")
async def get_task_status(task_id: int) -> Dict[str, Any]:
    """Status atual de uma tarefa (via TaskManager)"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not getattr(core, "task_manager", None):
            raise HTTPException(status_code=503, detail="TaskManager não está disponível")

        result = core.task_manager.get_task_status(task_id)
        if result.get("status") == "error":
            raise HTTPException(status_code=404, detail=result.get("message", "Tarefa não encontrada"))
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Task status: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.get("/execution/{execution_id}/details")
async def get_execution_details(execution_id: int) -> Dict[str, Any]:
    """Obtém detalhes detalhados de uma execução em tempo real"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not getattr(core, "task_manager", None):
            raise HTTPException(status_code=503, detail="TaskManager não está disponível")

        result = core.task_manager.get_execution_details(execution_id)
        if result.get("status") == "error":
            raise HTTPException(status_code=404, detail=result.get("message", "Execução não encontrada"))
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Execution details: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.post("/{task_id}/force-cancel")
async def force_cancel_task(task_id: int) -> Dict[str, Any]:
    """Força cancelamento de tarefa independente do status de execuções"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not getattr(core, "task_manager", None):
            raise HTTPException(status_code=503, detail="TaskManager não está disponível")

        # Resetar status da tarefa para 'idle' diretamente
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute("""
                UPDATE tasks
                SET status = 'idle', last_status = 'cancelled', last_run = %s
                WHERE id = %s
            """, (now, task_id))

            # Cancelar qualquer execução ativa desta tarefa
            cursor.execute("""
                UPDATE task_executions
                SET status = 'cancelled', error_message = 'Cancelado pelo usuário (Forçado)',
                    completed_at = %s
                WHERE task_id = %s AND status IN ('running', 'preparing', 'queued')
            """, (now, task_id))

            conn.commit()

        logger.info(f"✅ Tarefa {task_id} cancelada forçadamente")
        return {"status": "success", "message": "Tarefa cancelada com sucesso"}

    except Exception as e:
        logger.error(f"❌ Force cancel task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset-stuck")
async def reset_stuck_backups() -> Dict[str, Any]:
    """Reseta backups que estão presos no status 'running' por mais de 1 hora"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE task_executions 
                SET status = 'failed', 
                    completed_at = NOW(),
                    error_message = 'Execução resetada automaticamente - agente foi fechado inesperadamente'
                WHERE status = 'running' 
                AND started_at < (NOW() - INTERVAL '1 hour')
            """)

            reset_count = cursor.rowcount
            conn.commit()

        logger.info(f"✅ Reset {reset_count} stuck backup executions")
        return {"status": "success", "reset_count": reset_count, "message": f"{reset_count} execuções resetadas"}

    except Exception as e:
        logger.error(f"❌ Reset stuck backups: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@router.get("/system/password-audit")
async def task_password_audit(task_id: int = 0, execution_id: int = 0) -> Dict[str, Any]:
    """Audita vínculo task/repo e presença de senhas sem expor valores."""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            where_clause = ""
            params = []
            if execution_id:
                where_clause = "WHERE te.id = %s"
                params.append(execution_id)
            elif task_id:
                where_clause = "WHERE t.id = %s"
                params.append(task_id)

            cursor.execute(f"""
                SELECT
                    t.id as task_id,
                    t.name as task_name,
                    COALESCE(t.engine, 'unknown') as task_engine,
                    r.id as repo_id,
                    r.name as repo_name,
                    COALESCE(r.type, 'local') as repo_type,
                    COALESCE(r.engine, 'unknown') as repo_engine,
                    CASE WHEN COALESCE(r.motor_password, '') <> '' THEN true ELSE false END as has_motor_password,
                    CASE WHEN COALESCE(r.cloud_password, '') <> '' THEN true ELSE false END as has_cloud_password,
                    te.id as execution_id,
                    te.status as execution_status,
                    te.started_at,
                    te.completed_at,
                    te.error_message
                FROM tasks t
                LEFT JOIN repositories r ON r.id = t.repository_id
                LEFT JOIN task_executions te ON te.task_id = t.id
                {where_clause}
                ORDER BY te.started_at DESC NULLS LAST
                LIMIT 30
            """, tuple(params))

            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            items = [dict(zip(cols, row)) for row in rows]

            for it in items:
                st = it.get('started_at')
                ct = it.get('completed_at')
                if hasattr(st, 'isoformat'): it['started_at'] = st.isoformat()
                if hasattr(ct, 'isoformat'): it['completed_at'] = ct.isoformat()

        return {"status": "success", "count": len(items), "items": items}
    except Exception as e:
        logger.error(f"❌ Password audit: {e}", exc_info=True)
        return {"status": "error", "message": str(e), "count": 0, "items": []}
