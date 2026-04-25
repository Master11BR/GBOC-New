#!/usr/bin/env python3
"""GBOC Agent - API Backup Control"""
from fastapi import APIRouter
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backup", tags=["backup"])

@router.post("/run-all")
async def run_all_backups():
    """Executa todos os backups habilitados com retentativas"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        
        queued = 0
        
        @core.db_retry(max_retries=5, delay=0.3)
        def _execute_run_all():
            nonlocal queued
            queued = 0
            with core.get_db_connection() as conn:
                cursor = conn.execute("""
                    SELECT id FROM tasks 
                    WHERE enabled = 1 AND status != 'running'
                """)
                tasks = cursor.fetchall()
                
                for task in tasks:
                    task_id = task[0]
                    now = datetime.now().isoformat()
                    
                    try:
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO task_executions (task_id, status, started_at)
                            VALUES (%s, 'running', %s)
                            RETURNING id
                        """, (task_id, now))
                        row = cursor.fetchone()
                        exec_id = row[0] if row else None

                        cursor.execute("UPDATE tasks SET status = 'running' WHERE id = %s", (task_id,))

                        if core.task_manager and exec_id:
                            core.task_manager.queue_task(task_id, exec_id)
                            queued += 1
                    except Exception as e:
                        logger.error(f"Erro ao disparar tarefa {task_id}: {e}")
                
                conn.commit()

        _execute_run_all()
        
        return {"status": "success", "message": f"{queued} tarefas adicionadas à fila"}
    except Exception as e:
        logger.error(f"❌ Run all error: {e}")
        return {"status": "error", "message": str(e)}

@router.post("/stop-all")
async def stop_all_backups():
    """Para todos os backups em execução"""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE task_executions 
                SET status = 'cancelled', completed_at = %s
                WHERE status = 'running'
            """, (datetime.now().isoformat(),))
            conn.commit()
        
        return {"status": "success", "message": "Todas as tarefas foram canceladas"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
