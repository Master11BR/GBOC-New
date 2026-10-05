"""
GBOC Server — Portal do Cliente.

Usuários com perfil "client" (vinculados a uma organização) acessam apenas /portal.html e estas rotas,
sempre limitadas à própria organização (o tenant vem da sessão, nunca de parâmetro):
  GET /api/v1/portal/summary              situação: agentes, últimos backups, RPO, alertas, testes de restauração
  GET /api/v1/portal/reports              relatórios disponíveis ao cliente
  GET /api/v1/portal/reports/{code}       relatório (HTML com a marca do cliente, CSV)
  GET /api/v1/portal/invoices             meses fechados (faturamento)
  GET /api/v1/portal/invoices/{period}    demonstrativo do mês (CSV)
Administradores/operadores também podem abrir o portal informando ?tenant_id= (pré-visualização).
"""
from __future__ import annotations

import asyncio
import io
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse

router = APIRouter(prefix="/api/v1/portal", tags=["Portal do Cliente"])
CLIENT_REPORTS = ("REP-01", "REP-02", "REP-05", "REP-06", "REP-09", "REP-10", "REP-13")


def _db_exec(sql: str, params: Any = (), fetch: bool = True) -> List[Dict[str, Any]]:
    from modules.reports.report_schedules import _exec
    return _exec(sql, params, fetch)


def _tenant(request: Request, tenant_id: Optional[str]) -> str:
    u = getattr(request.state, "user", None) or {}
    role = str(u.get("role") or "").lower()
    if role == "client":
        if not u.get("tenant_id"):
            raise HTTPException(403, "Usuário sem organização vinculada")
        return u["tenant_id"]
    if not tenant_id:
        raise HTTPException(400, "Informe tenant_id para pré-visualizar o portal")
    return tenant_id


def _summary(tenant_id: str) -> Dict[str, Any]:
    from modules.reports import report_core as rc
    from modules.reports.branding import get_branding
    from modules.reports.report_source_server import ServerReportSource
    org = _db_exec("SELECT org_id, name, plan, max_agents, status FROM msp_organizations WHERE org_id=%s", (tenant_id,))
    if not org:
        raise HTTPException(404, "Organização não encontrada")
    with ServerReportSource() as src:
        ctx = rc.ReportContext(src, days=30, tenant_id=tenant_id)
        runs = ctx.runs
        done = [r for r in runs if r["status"] in ("success", "failed")]
        ok = [r for r in done if r["status"] == "success"]
        rpo = rc._task_rpo_rows(ctx)
        growth = rc._repo_growth(ctx)
        agents = []
        for a in ctx.agents:
            arpo = [x for x in rpo if x["task"].get("agent_id") == a["agent_id"]]
            last = max((x["last_success"] for x in arpo if x["last_success"]), default=None)
            agents.append({"hostname": ctx.host(a["agent_id"]), "status": ctx.agent_status(a), "version": a.get("agent_version"),
                           "last_heartbeat": rc.fmt_dt(a.get("last_heartbeat")), "last_backup": rc.fmt_dt(last) if last else "—",
                           "tasks": len(arpo), "tasks_in_rpo": sum(1 for x in arpo if x["tone"] in ("ok", "warn"))})
        tasks = [{"hostname": ctx.host(x["task"].get("agent_id")), "task": x["task"].get("name"), "status": x["status"], "tone": x["tone"],
                  "last_success": rc.fmt_dt(x["last_success"]) if x["last_success"] else "Nunca",
                  "schedule": rc.cron_human(x["task"].get("schedule_cron"), x["task"].get("schedule_enabled"))} for x in rpo]
        daily_ok = rc._daily_counts(ctx, ok)
        daily_fail = rc._daily_counts(ctx, [r for r in done if r["status"] == "failed"])
        tests = sorted(ctx.restore_tests, key=lambda t: rc.to_dt(t.get("started_at")) or datetime.min, reverse=True)[:10]
        kpis = {"success_pct": round(len(ok) / len(done) * 100, 1) if done else None, "runs": len(done),
                "tasks": len(rpo), "tasks_in_rpo": sum(1 for x in rpo if x["tone"] in ("ok", "warn")),
                "storage": rc.fmt_bytes(sum(x["size"] or 0 for x in growth)), "agents": len(ctx.agents),
                "agents_online": sum(1 for a in ctx.agents if ctx.agent_status(a) == "online"),
                "last_restore_test": rc.fmt_dt(tests[0].get("started_at")) if tests else None,
                "last_restore_test_ok": (str(tests[0].get("status")) == "passed") if tests else None}
        agent_ids = [a["agent_id"] for a in ctx.agents]
    alerts = []
    if agent_ids:
        try:
            alerts = _db_exec("""SELECT severity, title, message, first_seen FROM proactive_alert_events
                                 WHERE status <> 'resolved' AND agent_id = ANY(%s) ORDER BY first_seen DESC LIMIT 20""", (agent_ids,))
        except Exception:
            alerts = []
    brand = get_branding(tenant_id) or {}
    return {"tenant": {"id": tenant_id, "name": org[0]["name"], "plan": org[0].get("plan")},
            "branding": {k: brand.get(k) for k in ("display_name", "logo_data", "primary_color", "provider_name", "contact")},
            "kpis": kpis, "agents": agents, "tasks": tasks,
            "daily": {"labels": ctx.day_labels, "success": daily_ok, "failed": daily_fail},
            "alerts": [{"severity": a["severity"], "title": a["title"], "message": a["message"],
                        "since": a["first_seen"].strftime("%d/%m/%Y %H:%M") if a.get("first_seen") else ""} for a in alerts],
            "restore_tests": [{"date": rc.fmt_dt(t.get("started_at")), "repository": t.get("repository_name"), "status": t.get("status"),
                               "files": f"{t.get('files_ok') or 0}/{t.get('files_tested') or 0}"} for t in tests],
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M")}


@router.get("/summary")
async def summary(request: Request, tenant_id: Optional[str] = None):
    t = _tenant(request, tenant_id)
    return {"status": "success", **(await asyncio.to_thread(_summary, t))}


@router.get("/reports")
async def reports(request: Request, tenant_id: Optional[str] = None):
    _tenant(request, tenant_id)
    from modules.reports import report_core as rc
    return {"status": "success", "reports": [{"code": c["code"], "name": c["name"], "description": c["description"], "category": c["category"]}
                                             for c in rc.catalog("server") if c["code"] in CLIENT_REPORTS]}


@router.get("/reports/{code}")
async def report(code: str, request: Request, tenant_id: Optional[str] = None, days: int = Query(30, ge=1, le=365),
                 format: str = Query("html", pattern="^(html|embed|csv)$")):
    t = _tenant(request, tenant_id)
    if code.upper() not in CLIENT_REPORTS:
        raise HTTPException(404, "Relatório não disponível no portal")
    from modules.reports import report_core as rc
    from modules.reports.branding import get_branding
    from modules.reports.report_source_server import ServerReportSource

    def build():
        with ServerReportSource() as src:
            rep = rc.build_report(src, code.upper(), days=days, tenant_id=t)
        return rep, get_branding(t)
    rep, brand = await asyncio.to_thread(build)
    if format == "csv":
        return StreamingResponse(io.BytesIO(rc.render_csv(rep).encode("utf-8-sig")), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f"attachment; filename={rep['code']}_{datetime.now():%Y%m%d}.csv"})
    return HTMLResponse(rc.render_html(rep, embedded=(format == "embed"), branding=brand))


@router.get("/invoices")
async def invoices(request: Request, tenant_id: Optional[str] = None):
    t = _tenant(request, tenant_id)
    from modules.reports.billing import closings
    rows = await asyncio.to_thread(closings, None, t)
    return {"status": "success", "invoices": [{k: r.get(k) for k in ("period", "agents", "storage_bytes", "executions", "success", "base_fee",
                                                                      "price_per_agent", "price_per_tb", "currency", "amount", "closed_at",
                                                                      "integrity", "details")} for r in rows]}


@router.get("/invoices/{period}")
async def invoice(period: str, request: Request, tenant_id: Optional[str] = None):
    t = _tenant(request, tenant_id)
    from modules.reports.billing import closings, csv_export
    rows = await asyncio.to_thread(closings, period, t)
    if not rows:
        raise HTTPException(404, "Mês não fechado")
    return StreamingResponse(io.BytesIO(csv_export(rows).encode("utf-8-sig")), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename=demonstrativo_{period}.csv"})
