# GBOC System v14.6.0 Enterprise Edition
# Module: Executive & Operational Reports Router (Server)

import logging
import csv
import io
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request, Response, Query
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from psycopg2.extras import RealDictCursor
from database import db_manager

try:
    from version_control import __version__ as SERVER_VERSION
except Exception:
    SERVER_VERSION = "14.8.1"

logger = logging.getLogger("gboc_reports_module")
router = APIRouter(prefix="/api/v1/reports", tags=["Relatórios Executivos"])


def get_usd_to_brl_rate() -> float:
    """Obtém a taxa de câmbio comercial do dia USD -> BRL em tempo real com fallback automático."""
    try:
        from modules.config.config_router import get_usd_to_brl_rate as _get_rate
        return _get_rate()
    except Exception:
        return 5.50


def get_reports_config() -> Dict[str, Any]:
    """Obtém configurações do módulo de relatórios."""
    try:
        from modules.config.config_router import get_reports_config as _get_cfg
        return _get_cfg()
    except Exception:
        return {"cloud_storage_cost_usd_per_tb": 7.99, "auto_currency_conversion": True}


# Helper para obter conexão DB do servidor
def _get_server_db():
    try:
        from database import db_manager
        conn = db_manager.get_connection()
        if conn:
            return conn, db_manager
    except Exception:
        pass
    try:
        try:
            from server_gboc import get_db, release_db
        except ImportError:
            from gboc_server import get_db, release_db
        conn = get_db()
        class ServerDbReleaseHelper:
            def release_connection(self, c):
                release_db(c)
        return conn, ServerDbReleaseHelper()
    except Exception as e:
        logger.error(f"Erro ao obter conexão DB para relatórios: {e}")
        return None, None

# ─── RELATÓRIOS REAIS (motor report_core) ──────────────────────────────────
# Os 50 relatórios antigos eram, em grande parte, textos e números fixos (ex.: "3 organizações",
# "85 MB/s", "142 expirações") com a mesma consulta para todos. Foram substituídos por 20
# relatórios calculados exclusivamente a partir dos dados sincronizados pelos agentes.
import asyncio
from modules.reports import report_core as rc
from modules.reports.report_source_server import ServerReportSource


def _agent_list(agent_id: Optional[str]) -> Optional[List[str]]:
    if not agent_id:
        return None
    return [a.strip() for a in str(agent_id).split(",") if a.strip()]


def _build(ref: Any, days: int, agent_id: Optional[str], tenant_id: Optional[str]) -> Dict[str, Any]:
    with ServerReportSource() as src:
        return rc.build_report(src, ref, days=days, agent_ids=_agent_list(agent_id), tenant_id=tenant_id)


async def _build_async(ref: Any, days: int, agent_id: Optional[str], tenant_id: Optional[str]) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(_build, ref, days, agent_id, tenant_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


def _filename(rep: Dict[str, Any], ext: str) -> str:
    return f"GBOC_{rep['code']}_{datetime.now().strftime('%Y%m%d_%H%M')}.{ext}"


def _branding_for(rep: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        from modules.reports.branding import get_branding
        return get_branding(rep.get("tenant_id"))
    except Exception as e:
        logger.warning(f"Marca do relatório indisponível: {e}")
        return None


async def _respond(rep: Dict[str, Any], format: str):
    if format in ("html", "embed", "download", "pdf"):
        brand = await asyncio.to_thread(_branding_for, rep)
    else:
        brand = None
    if format == "json":
        return JSONResponse(rc.report_json(rep))
    if format == "csv":
        return StreamingResponse(io.BytesIO(rc.render_csv(rep).encode("utf-8-sig")), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f"attachment; filename={_filename(rep, 'csv')}"})
    if format == "download":
        return HTMLResponse(rc.render_html(rep, branding=brand), headers={"Content-Disposition": f"attachment; filename={_filename(rep, 'html')}"})
    return HTMLResponse(rc.render_html(rep, embedded=(format == "embed"), branding=brand))


@router.get("/catalog")
async def get_reports_catalog():
    """Catálogo dos relatórios reais (operação, SLA, risco, capacidade, segurança e comercial)."""
    items = rc.catalog("server")
    return JSONResponse({"status": "success", "total": len(items), "reports": [
        {**c, "type": "HTML/PDF/CSV", "format": "HTML/PDF/CSV"} for c in items], "engine_version": rc.REPORT_ENGINE_VERSION})


@router.get("/v2/{report_ref}")
async def get_report_v2(report_ref: str, days: int = Query(30, ge=1, le=730), agent_id: Optional[str] = Query(None),
                        tenant_id: Optional[str] = Query(None),
                        format: str = Query("html", pattern="^(html|embed|download|csv|json)$")):
    """Gera um relatório real. format: html (visualizar/imprimir), embed, download, csv ou json."""
    rep = await _build_async(report_ref, days, agent_id, tenant_id)
    return await _respond(rep, format)


@router.post("/generate")
@router.get("/generate/{report_id}")
async def generate_report_endpoint(request: Request, report_id: Optional[str] = None,
                                   days: int = Query(30, ge=1, le=730), agent_id: Optional[str] = Query(None),
                                   tenant_id: Optional[str] = Query(None)):
    """Compatibilidade: retorna o resumo do relatório no formato antigo (metrics/table/parecer)."""
    ref = report_id
    if request.method == "POST":
        try:
            body = await request.json()
            ref = body.get("report_id") or body.get("id") or body.get("code") or ref
            days = int(body.get("days") or days)
            agent_id = body.get("agent_id") or agent_id
            tenant_id = body.get("tenant_id") or tenant_id
        except Exception:
            pass
    rep = await _build_async(ref or 1, days, agent_id, tenant_id)
    return JSONResponse(rc.legacy_payload(rep))


@router.get("/export/{report_id}")
async def export_report(report_id: str, format: str = Query("html", pattern="^(html|csv|json|pdf|download)$"),
                        days: int = Query(30, ge=1, le=730), agent_id: Optional[str] = Query(None),
                        tenant_id: Optional[str] = Query(None), print: Optional[str] = Query(None)):
    """Exporta o relatório: HTML (imprimir/PDF), CSV ou JSON."""
    rep = await _build_async(report_id, days, agent_id, tenant_id)
    return await _respond(rep, "html" if format == "pdf" else format)


@router.get("/consolidated")
async def get_consolidated_reports(days: int = Query(30, ge=1, le=730), agent_id: Optional[str] = Query(None)):
    """Resumo consolidado real (aba Relatórios): KPIs, tendência diária, por agente e falhas recentes."""
    def work():
        with ServerReportSource() as src:
            ctx = rc.ReportContext(src, days=days, agent_ids=_agent_list(agent_id))
            runs = ctx.runs
            ok = [r for r in runs if r["status"] == "success"]
            fl = [r for r in runs if r["status"] == "failed"]
            by_agent = {a["agent_id"]: {"agent_id": a["agent_id"], "hostname": a.get("hostname"), "ip_address": a.get("ip_address"),
                                        "status": ctx.agent_status(a), "backups": 0, "successes": 0, "failures": 0, "total_bytes": 0}
                        for a in ctx.agents}
            for r in runs:
                b = by_agent.get(r.get("agent_id"))
                if not b or r["status"] not in ("success", "failed"):
                    continue
                b["backups"] += 1
                if r["status"] == "success":
                    b["successes"] += 1
                    b["total_bytes"] += int(r["bytes"] or 0)
                else:
                    b["failures"] += 1
            s_daily = rc._daily_counts(ctx, ok)
            f_daily = rc._daily_counts(ctx, fl)
            total = len(ok) + len(fl)
            return {
                "status": "success",
                "global": {"total_agents": len(ctx.agents), "online_agents": sum(1 for a in ctx.agents if ctx.agent_status(a) == "online"),
                           "total_reports": total, "success_rate": round(len(ok) / total * 100, 1) if total else None,
                           "fail_count": len(fl), "total_bytes": int(sum(r["bytes"] or 0 for r in ok))},
                "agents": sorted(by_agent.values(), key=lambda b: (b["hostname"] or "").lower()),
                "top_failures": [{"agent_id": r.get("agent_id"), "hostname": ctx.host(r.get("agent_id")), "job_name": r["task_label"],
                                  "error_message": r.get("error"), "executed_at": r["started_at"].isoformat()} for r in reversed(fl[-10:])],
                "trend": [{"day": l, "successes": int(s), "failures": int(f)} for l, s, f in zip(ctx.day_labels, s_daily, f_daily)],
                "days": ctx.days,
            }
    return JSONResponse(await asyncio.to_thread(work))


# Agendamentos reais por e-mail: modules/reports/report_schedules.py (/api/v1/reports/schedules)


# =====================================================================
# GBOC v4.0 FLAGSHIP REPORTS (8 Relatórios Executivos de Mercado)
# =====================================================================

try:
    from modules.reports.flagship_reports import (
        FLAGSHIPS_CATALOG_8,
        FLAGSHIPS_CATALOG_7,
        build_flagship_report_server,
        render_flagship_html,
        render_flagship_csv,
    )
except ImportError:
    from flagship_reports import (
        FLAGSHIPS_CATALOG_8,
        FLAGSHIPS_CATALOG_7,
        build_flagship_report_server,
        render_flagship_html,
        render_flagship_csv,
    )


@router.get("/flagships")
async def list_flagship_reports():
    """Retorna o catálogo dos 8 relatórios flagship executivos da Arquitetura v4.0."""
    return JSONResponse({
        "status": "success",
        "schema_version": "4.0.0",
        "platform": f"GBOC Server v{SERVER_VERSION}",
        "count": len(FLAGSHIPS_CATALOG_8),
        "flagships": FLAGSHIPS_CATALOG_8
    })


@router.get("/flagships/{flagship_id}")
async def get_flagship_report_endpoint(
    flagship_id: str,
    format: str = Query("html", pattern="^(html|pdf|csv|json)$"),
    print: Optional[str] = Query(None)
):
    """Gera e retorna um dos 8 relatórios flagship no formato requisitado (html, pdf, csv, json)."""
    fid = flagship_id.upper().strip()
    valid_ids = [f["id"] for f in FLAGSHIPS_CATALOG_8]
    if fid not in valid_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Relatório Flagship '{flagship_id}' não encontrado. IDs válidos: {', '.join(valid_ids)}"
        )

    try:
        payload = build_flagship_report_server(fid)
    except Exception as e:
        logger.error(f"Erro ao gerar payload do Flagship {fid}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro interno ao gerar relatório: {str(e)}")

    # Formatos de saída
    if format == "json":
        return JSONResponse(content=payload)

    elif format == "csv":
        csv_data = render_flagship_csv(payload)
        filename = f"{fid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    else:
        # html ou pdf (A4 print layout)
        is_print = (format == "pdf") or (print in ("1", "true", "yes"))
        html_content = render_flagship_html(payload, is_print=is_print)
        return HTMLResponse(content=html_content)

