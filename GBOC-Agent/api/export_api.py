#!/usr/bin/env python3
"""
GBOC 11.7c - API de Exportação de Relatórios
Gera relatórios em CSV e JSON (PDF via frontend)
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import logging
import io
import csv
import json
from decimal import Decimal
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/export", tags=["Export Reports"])


class _DecimalEncoder(json.JSONEncoder):
    """Converte Decimal do PostgreSQL para tipos nativos JSON."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj == obj.to_integral_value() else float(obj)
        return super().default(obj)


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


@router.get("/backup-report/csv")
async def export_backup_report_csv(days: int = 30):
    """Exporta relatório de backups em CSV"""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT te.id, t.name as task_name, t.engine, te.status,
                       te.started_at, te.completed_at, te.snapshot_id,
                       te.files_processed, te.bytes_processed, te.error_message
                FROM task_executions te
                JOIN tasks t ON te.task_id = t.id
                WHERE te.started_at >= NOW() - INTERVAL '%s days'
                ORDER BY te.started_at DESC
            """.replace('%s', str(int(days))))

            rows = cursor.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'ID', 'Task', 'Engine', 'Status', 'Início', 'Fim',
            'Snapshot ID', 'Arquivos', 'Bytes', 'Erro'
        ])

        for row in rows:
            writer.writerow([
                row[0], row[1], row[2], row[3],
                row[4].isoformat() if row[4] else '',
                row[5].isoformat() if row[5] else '',
                row[6] or '', row[7] or 0, row[8] or 0,
                (row[9] or '')[:200]
            ])

        output.seek(0)
        filename = f"gboc_backup_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Erro ao exportar CSV: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backup-report/json")
async def export_backup_report_json(days: int = 30):
    """Exporta relatório completo em JSON"""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            # Resumo
            cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                       SUM(COALESCE(bytes_processed, 0)) as total_bytes,
                       SUM(COALESCE(files_processed, 0)) as total_files
                FROM task_executions
                WHERE started_at >= NOW() - INTERVAL '%s days'
            """.replace('%s', str(int(days))))
            summary_row = cursor.fetchone()

            # Execuções
            cursor.execute("""
                SELECT te.id, t.name, t.engine, te.status, te.started_at, te.completed_at,
                       te.snapshot_id, te.files_processed, te.bytes_processed, te.error_message
                FROM task_executions te
                JOIN tasks t ON te.task_id = t.id
                WHERE te.started_at >= NOW() - INTERVAL '%s days'
                ORDER BY te.started_at DESC
            """.replace('%s', str(int(days))))
            rows = cursor.fetchall()

            # Por tarefa
            cursor.execute("""
                SELECT t.id, t.name, t.engine,
                       COUNT(te.id) as total,
                       SUM(CASE WHEN te.status = 'completed' THEN 1 ELSE 0 END) as ok,
                       MAX(te.started_at) as last_run
                FROM tasks t
                LEFT JOIN task_executions te ON t.id = te.task_id
                    AND te.started_at >= NOW() - INTERVAL '%s days'
                GROUP BY t.id, t.name, t.engine
                ORDER BY t.name
            """.replace('%s', str(int(days))))
            task_rows = cursor.fetchall()

        report = {
            "generated_at": datetime.now().isoformat(),
            "period_days": days,
            "summary": {
                "total_executions": summary_row[0] or 0,
                "completed": summary_row[1] or 0,
                "failed": summary_row[2] or 0,
                "success_rate": round((summary_row[1] or 0) / (summary_row[0] or 1) * 100, 1),
                "total_bytes": summary_row[3] or 0,
                "total_files": summary_row[4] or 0
            },
            "tasks": [
                {
                    "id": r[0], "name": r[1], "engine": r[2],
                    "total_executions": r[3] or 0,
                    "successful": r[4] or 0,
                    "success_rate": round((r[4] or 0) / (r[3] or 1) * 100, 1),
                    "last_run": r[5].isoformat() if r[5] else None
                }
                for r in task_rows
            ],
            "executions": [
                {
                    "id": r[0], "task": r[1], "engine": r[2], "status": r[3],
                    "started_at": r[4].isoformat() if r[4] else None,
                    "completed_at": r[5].isoformat() if r[5] else None,
                    "snapshot_id": r[6], "files": r[7] or 0, "bytes": r[8] or 0,
                    "error": (r[9] or '')[:200]
                }
                for r in rows
            ]
        }

        content = json.dumps(report, indent=2, ensure_ascii=False, cls=_DecimalEncoder)
        filename = f"gboc_backup_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Erro ao exportar JSON: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sla-report/csv")
async def export_sla_report_csv():
    """Exporta relatório de SLA compliance em CSV"""
    try:
        from api.preemptive_api import get_sla_compliance
        data = await get_sla_compliance()
        tasks = data.get("tasks", [])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Tarefa', 'Engine', 'Taxa Sucesso 30d (%)', 'Execuções 30d',
            'Sucessos 30d', 'RPO Atual (h)', 'RPO Esperado (h)',
            'Último Sucesso', 'Última Falha', 'Compliance'
        ])

        for t in tasks:
            writer.writerow([
                t['name'], t['engine'], t['success_rate_30d'], t['total_executions_30d'],
                t['successful_30d'], t['rpo_hours'] or '', t['expected_rpo_hours'] or '',
                t['last_success'] or '', t['last_failure'] or '', t['compliance']
            ])

        output.seek(0)
        filename = f"gboc_sla_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Erro ao exportar SLA CSV: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

