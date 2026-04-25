#!/usr/bin/env python3
"""
GBOC 11.7c - Reports API
Generate, schedule, download and manage backup reports.
Supports HTML (print-to-PDF), CSV, JSON formats.
Report types: executive, sla, capacity, errors.
Scheduling: cron-based automatic report generation & email delivery.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
import logging
import io
import csv
import json
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["Reports"])


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        return super().default(o)


# ─── Report Types ──────────────────────────────────────────────────

@router.get("/types")
async def list_report_types():
    """Lista todos os tipos de relatório disponíveis"""
    from engines.report_generator import REPORT_TYPES
    return {
        "types": [
            {"id": k, "label": v["label"], "description": v["desc"]}
            for k, v in REPORT_TYPES.items()
        ]
    }


@router.get("/generate/{report_type}")
async def generate_report(report_type: str, days: int = 30, format: str = "html"):
    """
    Gera um relatório sob demanda.
    - report_type: executive, sla, capacity, errors
    - format: html, json, csv
    - days: período em dias (padrão 30)
    """
    from engines.report_generator import REPORT_TYPES

    if report_type not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Use: {', '.join(REPORT_TYPES.keys())}")

    core = _get_core()

    def _write_history(status: str, file_size: int = 0, error_message: str = None):
        try:
            with core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO report_history (schedule_id, report_type, format, generated_at, file_size, status, error_message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (None, report_type, format, datetime.now().isoformat(), file_size, status, error_message))
                conn.commit()
        except Exception as hist_err:
            logger.warning(f"Falha ao gravar report_history: {hist_err}")

    try:
        gen = REPORT_TYPES[report_type]

        if format == "html":
            html = gen["fn"](days) if report_type != "capacity" else gen["fn"]()
            _write_history("success", len(html.encode('utf-8')), None)
            return HTMLResponse(content=html)

        elif format == "json":
            from engines.report_generator import (
                collect_summary, collect_tasks_detail, collect_sla,
                collect_engine_comparison, collect_errors, collect_repos, collect_capacity
            )
            data = {
                "report_type": report_type,
                "generated_at": datetime.now().isoformat(),
                "period_days": days,
            }
            if report_type == "executive":
                data["summary"] = collect_summary(days)
                data["tasks"] = collect_tasks_detail(days)
                data["sla"] = collect_sla()
                data["engines"] = collect_engine_comparison(days)
                data["repositories"] = collect_repos()
                data["capacity"] = collect_capacity()
                data["errors"] = collect_errors(days, 20)
            elif report_type == "sla":
                data["sla"] = collect_sla()
            elif report_type == "capacity":
                data["capacity"] = collect_capacity()
                data["repositories"] = collect_repos()
            elif report_type == "errors":
                data["errors"] = collect_errors(days, 50)
                data["summary"] = collect_summary(days)

            content = json.dumps(data, cls=_DecimalEncoder, indent=2, ensure_ascii=False)
            _write_history("success", len(content.encode('utf-8')), None)
            filename = f"gboc_{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            return StreamingResponse(
                iter([content]),
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )

        elif format == "csv":
            from engines.report_generator import collect_tasks_detail, collect_sla, collect_errors
            output = io.StringIO()
            writer = csv.writer(output)

            if report_type in ("executive", "sla"):
                rows = collect_sla() if report_type == "sla" else collect_tasks_detail(days)
                if rows:
                    writer.writerow(rows[0].keys())
                    for r in rows:
                        writer.writerow([
                            float(v) if isinstance(v, Decimal) else
                            v.isoformat() if hasattr(v, 'isoformat') else v
                            for v in r.values()
                        ])
            elif report_type == "errors":
                rows = collect_errors(days, 100)
                if rows:
                    writer.writerow(rows[0].keys())
                    for r in rows:
                        writer.writerow([
                            float(v) if isinstance(v, Decimal) else
                            v.isoformat() if hasattr(v, 'isoformat') else v
                            for v in r.values()
                        ])
            else:
                writer.writerow(["info"])
                writer.writerow(["Use format=html or format=json for this report type"])

            output.seek(0)
            csv_content = output.getvalue()
            _write_history("success", len(csv_content.encode('utf-8')), None)
            filename = f"gboc_{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            return StreamingResponse(
                iter([csv_content]),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )

        else:
            _write_history("failed", 0, "Formato inválido")
            raise HTTPException(status_code=400, detail="Formato inválido. Use: html, json, csv")

    except HTTPException:
        raise
    except Exception as e:
        _write_history("failed", 0, str(e))
        logger.error(f"Report generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─── Report Scheduling ────────────────────────────────────────────

@router.get("/schedules")
async def list_report_schedules():
    """Lista agendamentos de relatórios"""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(""" 
                SELECT id, name, report_type, format, period_days, cron_expression,
                       email_to, enabled, last_run, next_run, created_at
                FROM report_schedules
                ORDER BY created_at DESC
            """)
            cols = [d[0] for d in cursor.description]
            rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
        return {"schedules": rows}
    except Exception as e:
        logger.error(f"Error listing report schedules: {e}")
        return {"schedules": [], "error": str(e)}


@router.post("/schedules")
async def create_report_schedule(request: Request):
    """Cria um agendamento de relatório"""
    data = await request.json()
    core = _get_core()

    required = ["name", "report_type", "cron_expression"]
    for f in required:
        if f not in data:
            raise HTTPException(status_code=400, detail=f"Campo obrigatório: {f}")

    from engines.report_generator import REPORT_TYPES
    if data["report_type"] not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail=f"Tipo inválido: {data['report_type']}")

    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO report_schedules
                    (name, report_type, format, period_days, cron_expression, email_to, enabled)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                data["name"],
                data["report_type"],
                data.get("format", "html"),
                data.get("period_days", 30),
                data["cron_expression"],
                data.get("email_to", ""),
                data.get("enabled", True),
            ))
            sched_id = cursor.fetchone()[0]
            conn.commit()

        return {"success": True, "id": sched_id}
    except Exception as e:
        logger.error(f"Error creating report schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/schedules/{schedule_id}")
async def update_report_schedule(schedule_id: int, request: Request):
    """Atualiza um agendamento"""
    data = await request.json()
    core = _get_core()
    try:
        sets = []
        vals = []
        for col in ["name", "report_type", "format", "period_days", "cron_expression", "email_to", "enabled"]:
            if col in data:
                sets.append(f"{col} = %s")
                vals.append(data[col])
        if not sets:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
        vals.append(schedule_id)
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE report_schedules SET {', '.join(sets)} WHERE id = %s", vals)
            conn.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/schedules/{schedule_id}")
async def delete_report_schedule(schedule_id: int):
    """Remove um agendamento"""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM report_schedules WHERE id = %s", (schedule_id,))
            conn.commit()
        return {"success": True}
    except Exception as e:
        logger.error(f"Error deleting schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def report_history(limit: int = 50):
    """Histórico de relatórios gerados"""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, schedule_id, report_type, format, generated_at,
                       file_size, status, error_message
                FROM report_history
                ORDER BY generated_at DESC
                LIMIT %s
            """, (limit,))
            cols = [d[0] for d in cursor.description]
            rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
        return {"history": rows}
    except Exception as e:
        logger.error(f"Error getting report history: {e}")
        return {"history": [], "error": str(e)}

