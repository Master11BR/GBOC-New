#!/usr/bin/env python3
"""
GBOC 14.8.1 - Reports API (Agent)
Generate, schedule, download and manage backup reports with 100% real system data.
Supports HTML (print-to-PDF), CSV, JSON formats.
"""

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.concurrency import run_in_threadpool
import logging
import io
import csv
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional

try:
    from version import GBOC_VERSION as AGENT_VERSION
except ImportError:
    AGENT_VERSION = "14.8.1"

try:
    from engines.v4_reports_engine import (
        generate_real_report_data_v4,
        _clean_task_name,
        _sla_badge,
        get_real_uptime,
        predict_storage_exhaustion,
        build_ai_recommendation
    )
except ImportError:
    try:
        from v4_reports_engine import (
            generate_real_report_data_v4,
            _clean_task_name,
            _sla_badge,
            get_real_uptime,
            predict_storage_exhaustion,
            build_ai_recommendation
        )
    except ImportError:
        try:
            from engines.v3_reports_engine import (
                generate_real_report_data_v3 as generate_real_report_data_v4,
                _clean_task_name,
                _sla_badge,
                get_real_uptime,
                predict_storage_exhaustion,
                build_ai_recommendation
            )
        except ImportError:
            from v3_reports_engine import (
                generate_real_report_data_v3 as generate_real_report_data_v4,
                _clean_task_name,
                _sla_badge,
                get_real_uptime,
                predict_storage_exhaustion,
                build_ai_recommendation
            )

logger = logging.getLogger(__name__)
# Router sem prefixo fixo para mapear tanto /api/reports quanto /api/v1/reports
router = APIRouter(tags=["Reports"])

_EXCHANGE_RATE_CACHE = {"rate": 5.50, "timestamp": 0}
_REPORTS_CONFIG_CACHE = {
    "cloud_storage_cost_usd_per_tb": 7.99,
    "auto_currency_conversion": True
}


def get_usd_to_brl_rate() -> float:
    """Obtém a taxa de câmbio comercial do dia USD -> BRL em tempo real com fallback automático."""
    import time
    import urllib.request
    now = time.time()
    if now - _EXCHANGE_RATE_CACHE["timestamp"] < 3600 and _EXCHANGE_RATE_CACHE["rate"] > 0:
        return _EXCHANGE_RATE_CACHE["rate"]

    try:
        req = urllib.request.Request(
            "https://economia.awesomeapi.com.br/json/last/USD-BRL",
            headers={"User-Agent": "GBOC-System/14.8.1"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                rate = float(payload.get("USDBRL", {}).get("bid", 5.50))
                if rate > 0:
                    _EXCHANGE_RATE_CACHE["rate"] = rate
                    _EXCHANGE_RATE_CACHE["timestamp"] = now
                    return rate
    except Exception as err:
        logger.warning(f"Falha ao obter câmbio USD-BRL em tempo real no agente (fallback 5.50): {err}")

    return _EXCHANGE_RATE_CACHE.get("rate", 5.50)


def get_agent_reports_config() -> Dict[str, Any]:
    """Obtém as configurações de relatórios do banco do agente ou fallback em memória."""
    try:
        core = _get_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM settings WHERE category = 'reports'")
            rows = cur.fetchall()
            for r in rows:
                if r[0] == 'cloud_storage_cost_usd_per_tb':
                    try:
                        _REPORTS_CONFIG_CACHE['cloud_storage_cost_usd_per_tb'] = float(r[1])
                    except Exception:
                        pass
                elif r[0] == 'auto_currency_conversion':
                    _REPORTS_CONFIG_CACHE['auto_currency_conversion'] = (str(r[1]).lower() in ['true', '1'])
    except Exception:
        pass
    return _REPORTS_CONFIG_CACHE


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


# ─── RELATÓRIOS REAIS (motor compartilhado engines/report_core.py) ─────────────
# Substitui os 50 relatórios antigos (muitos com números fixos e a mesma consulta) por 20
# relatórios calculados a partir do banco do Agente — os mesmos do GBOC Server para este host.
import asyncio
from engines import report_core as rc
from engines.report_source_agent import AgentReportSource


def _build_agent_report(ref: Any, days: int) -> Dict[str, Any]:
    with AgentReportSource() as src:
        src.prepare(days)
        return rc.build_report(src, ref, days=days)


async def _build_agent_report_async(ref: Any, days: int) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(_build_agent_report, ref, days)
    except KeyError as e:
        raise HTTPException(404, str(e))


def _agent_report_response(rep: Dict[str, Any], format: str):
    fname = f"GBOC_Agent_{rep['code']}_{datetime.now().strftime('%Y%m%d_%H%M')}"
    if format == "json":
        return JSONResponse(rc.report_json(rep))
    if format == "csv":
        return StreamingResponse(io.BytesIO(rc.render_csv(rep).encode("utf-8-sig")), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f"attachment; filename={fname}.csv"})
    if format == "download":
        return HTMLResponse(rc.render_html(rep), headers={"Content-Disposition": f"attachment; filename={fname}.html"})
    return HTMLResponse(rc.render_html(rep, embedded=(format == "embed")))


@router.get("/api/reports/catalog")
@router.get("/api/v1/reports/catalog")
async def get_reports_catalog():
    """Catálogo dos relatórios reais disponíveis no Agente."""
    items = rc.catalog("agent")
    return {"status": "success", "total": len(items), "engine_version": rc.REPORT_ENGINE_VERSION,
            "reports": [{**c, "type": "HTML/PDF/CSV", "format": "HTML/PDF/CSV"} for c in items]}


@router.get("/api/reports/v2/{report_ref}")
@router.get("/api/v1/reports/v2/{report_ref}")
async def get_agent_report_v2(report_ref: str, days: int = Query(30, ge=1, le=730),
                              format: str = Query("html", pattern="^(html|embed|download|csv|json)$")):
    rep = await _build_agent_report_async(report_ref, days)
    return _agent_report_response(rep, format)


@router.post("/api/reports/generate")
@router.post("/api/v1/reports/generate")
@router.get("/api/reports/generate/{report_id}")
@router.get("/api/v1/reports/generate/{report_id}")
async def generate_report_by_payload(request: Request, report_id: Optional[str] = None):
    """Compatibilidade com a tela antiga: resumo (métricas, tabela principal e parecer)."""
    ref, days = report_id, 30
    if request.method == "POST":
        try:
            payload = await request.json()
            ref = payload.get("report_id") or payload.get("id") or payload.get("code") or ref
            days = int(payload.get("days") or 30)
        except Exception:
            pass
    else:
        try:
            days = int(request.query_params.get("days", 30))
        except Exception:
            days = 30
    rep = await _build_agent_report_async(ref or 1, max(1, min(days, 730)))
    return JSONResponse(rc.legacy_payload(rep))


@router.get("/api/reports/export/{report_id}")
@router.get("/api/v1/reports/export/{report_id}")
async def export_agent_report(report_id: str, format: str = Query("html", pattern="^(html|csv|json|pdf|download)$"),
                              days: int = Query(30, ge=1, le=730)):
    """Exporta relatórios do agente em HTML (imprimir/PDF), CSV ou JSON."""
    rep = await _build_agent_report_async(report_id, days)
    return _agent_report_response(rep, "html" if format == "pdf" else format)


try:
    from engines.flagship_reports import (
        FLAGSHIPS_CATALOG_8,
        FLAGSHIPS_CATALOG_7,
        build_flagship_report_agent,
        render_flagship_html,
        render_flagship_csv,
    )
except ImportError:
    from flagship_reports import (
        FLAGSHIPS_CATALOG_8,
        FLAGSHIPS_CATALOG_7,
        build_flagship_report_agent,
        render_flagship_html,
        render_flagship_csv,
    )

try:
    from engines.v4_reports_engine import (
        NEW_REPORTS_CATALOG_5,
        detect_anomalies,
        collect_health_timeline,
        collect_engine_health,
        collect_config_drift,
        compare_periods
    )
except ImportError:
    try:
        from v4_reports_engine import (
            NEW_REPORTS_CATALOG_5,
            detect_anomalies,
            collect_health_timeline,
            collect_engine_health,
            collect_config_drift,
            compare_periods
        )
    except ImportError:
        NEW_REPORTS_CATALOG_5 = []
        detect_anomalies = lambda days=30: []
        collect_health_timeline = lambda days=90: []
        collect_engine_health = lambda: []
        collect_config_drift = lambda: []
        compare_periods = lambda periods=[7, 30, 90]: {"periods": [], "period_labels": []}

from fastapi.responses import Response


@router.get("/api/reports/flagships")
@router.get("/api/v1/reports/flagships")
async def list_agent_flagship_reports():
    """Retorna o catálogo dos 8 relatórios flagship executivos no GBOC Agent (Schema v4.0.0)."""
    return JSONResponse({
        "status": "success",
        "schema_version": "4.0.0",
        "platform": f"GBOC Agent v{AGENT_VERSION}",
        "count": len(FLAGSHIPS_CATALOG_8),
        "flagships": FLAGSHIPS_CATALOG_8,
        "new_reports": NEW_REPORTS_CATALOG_5
    })


@router.get("/api/reports/flagships/{flagship_id}")
@router.get("/api/v1/reports/flagships/{flagship_id}")
async def get_agent_flagship_report(
    flagship_id: str,
    format: str = Query("html", pattern="^(html|pdf|csv|json)$"),
    print: Optional[str] = Query(None)
):
    """Gera e retorna um dos 8 relatórios flagship no formato requisitado (html, pdf, csv, json) no Agente."""
    fid = flagship_id.upper().strip()
    valid_ids = [f["id"] for f in FLAGSHIPS_CATALOG_8]
    if fid not in valid_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Relatório Flagship '{flagship_id}' não encontrado. IDs válidos: {', '.join(valid_ids)}"
        )

    try:
        payload = await run_in_threadpool(build_flagship_report_agent, fid)
    except Exception as e:
        logger.error(f"Erro ao gerar payload do Flagship {fid} no agente: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro interno ao gerar relatório: {str(e)}")

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
        is_print = (format == "pdf") or (print in ("1", "true", "yes"))
        html_content = render_flagship_html(payload, is_print=is_print)
        return HTMLResponse(content=html_content)


# ── NOVAS ROTAS DE RELATÓRIO DO MASTER REPORT STANDARD v4.0 ─────────────────

@router.get("/api/reports/anomalies")
@router.get("/api/v1/reports/anomalies")
async def get_anomalies_endpoint(days: int = Query(30, ge=1, le=365)):
    """REP-N1: Retorna anomalias de volume e duração detectadas via Z-Score."""
    try:
        anomalies = await run_in_threadpool(detect_anomalies, days)
        return JSONResponse({
            "status": "success",
            "code": "REP-N1",
            "title": "Anomaly Detection Report",
            "period_days": days,
            "anomalies_count": len(anomalies),
            "anomalies": anomalies
        })
    except Exception as e:
        logger.error(f"Erro em REP-N1 anomalies: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/reports/health-timeline")
@router.get("/api/v1/reports/health-timeline")
async def get_health_timeline_endpoint(days: int = Query(90, ge=7, le=365)):
    """REP-N2: Retorna calendário visual com matriz diária de saúde dos backups."""
    try:
        timeline = await run_in_threadpool(collect_health_timeline, days)
        return JSONResponse({
            "status": "success",
            "code": "REP-N2",
            "title": "Backup Health Timeline",
            "period_days": days,
            "days_count": len(timeline),
            "timeline": timeline
        })
    except Exception as e:
        logger.error(f"Erro em REP-N2 health-timeline: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/reports/engine-health")
@router.get("/api/v1/reports/engine-health")
async def get_engine_health_endpoint():
    """REP-N3: Retorna diagnóstico aprofundado dos motores de backup instalados."""
    try:
        engines_data = await run_in_threadpool(collect_engine_health)
        return JSONResponse({
            "status": "success",
            "code": "REP-N3",
            "title": "Engine Health Report",
            "engines": engines_data
        })
    except Exception as e:
        logger.error(f"Erro em REP-N3 engine-health: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/reports/config-drift")
@router.get("/api/v1/reports/config-drift")
async def get_config_drift_endpoint():
    """REP-N4: Rastreia desvios e alterações de configuração dos backups."""
    try:
        drift = await run_in_threadpool(collect_config_drift)
        return JSONResponse({
            "status": "success",
            "code": "REP-N4",
            "title": "Configuration Drift Report",
            "drift_events": drift
        })
    except Exception as e:
        logger.error(f"Erro em REP-N4 config-drift: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/reports/compare")
@router.get("/api/v1/reports/compare")
async def get_compare_periods_endpoint(periods: str = Query("7,30,90")):
    """REP-N5: Comparativo analítico multi-período lado a lado."""
    try:
        days_list = [int(p.strip()) for p in periods.split(",") if p.strip().isdigit()]
        if not days_list:
            days_list = [7, 30, 90]
        comp = await run_in_threadpool(compare_periods, days_list)
        return JSONResponse({
            "status": "success",
            "code": "REP-N5",
            "title": "Multi-Period Comparison Report",
            "data": comp
        })
    except Exception as e:
        logger.error(f"Erro em REP-N5 compare: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/reports/schema")
@router.get("/api/v1/reports/schema")
async def get_reports_schema():
    """Retorna a especificação normativa Schema v4.0.0 para integrações de BI e API."""
    return JSONResponse({
        "schema_version": "4.0.0",
        "normative_standard": "GBOC Agent Master Report Standard v4.0",
        "flagships_count": len(FLAGSHIPS_CATALOG_8),
        "new_reports_count": len(NEW_REPORTS_CATALOG_5),
        "supported_formats": ["html", "pdf", "csv", "json"],
        "flagships": FLAGSHIPS_CATALOG_8,
        "new_reports": NEW_REPORTS_CATALOG_5
    })


@router.get("/api/system/health")
@router.get("/api/v1/system/health")
def get_system_health():
    """Health check unificado — expõe versão, uptime, integridade do banco e engines ativos."""
    try:
        from version import GBOC_VERSION, version_string
    except ImportError:
        GBOC_VERSION = "14.8.1"
        version_string = lambda: "GBOC Agent v14.8.1 Enterprise"

    import psutil, os, time
    proc = psutil.Process(os.getpid())
    elapsed = time.time() - proc.create_time()
    h, m = int(elapsed // 3600), int((elapsed % 3600) // 60)
    uptime_info = {
        "pid": os.getpid(),
        "uptime_str": f"{h}h {m}m",
        "uptime_hours": round(elapsed / 3600, 1),
        "memory_mb": round(proc.memory_info().rss / (1024**2), 1),
        "cpu_pct": proc.cpu_percent(interval=None),
        "status": proc.status(),
    }

    core = _get_core()
    summary = {"total": 0, "ok": 0, "failed": 0, "success_rate": 100.0}
    engines = []
    try:
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END)
                FROM backups WHERE start_time >= datetime('now', '-1 day')
            """)
            r = cur.fetchone()
            if r and r[0]:
                tot = int(r[0] or 0)
                ok = int(r[1] or 0)
                summary = {
                    "total": tot,
                    "ok": ok,
                    "failed": int(r[2] or 0),
                    "success_rate": round(ok / tot * 100, 1) if tot else 100.0
                }
            cur.execute("SELECT engine, path, detected FROM detected_engines LIMIT 10")
            for erow in cur.fetchall():
                engines.append({"engine": erow[0], "path": erow[1], "detected": bool(erow[2])})
    except Exception as db_err:
        logger.warning(f"Erro ao consultar DB para healthcheck: {db_err}")

    status_str = "healthy" if summary["failed"] == 0 else ("degraded" if summary["success_rate"] >= 80 else "unhealthy")

    return JSONResponse({
        "status": status_str,
        "version": GBOC_VERSION,
        "version_string": version_string(),
        "uptime": uptime_info,
        "last_24h": summary,
        "engines": engines,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


@router.get("/api/system/version")
@router.get("/api/v1/system/version")
async def get_system_version():
    """Retorna versão oficial, build e metadados de release da plataforma."""
    try:
        from version import GBOC_VERSION, GBOC_BUILD, GBOC_EDITION, GBOC_RELEASE_DATE, GBOC_PLATFORM, version_string
        return JSONResponse({
            "version": GBOC_VERSION,
            "build": GBOC_BUILD,
            "edition": GBOC_EDITION,
            "release_date": GBOC_RELEASE_DATE,
            "platform": GBOC_PLATFORM,
            "string": version_string()
        })
    except Exception:
        return JSONResponse({"version": "14.8.1", "build": "stable", "edition": "Enterprise"})


