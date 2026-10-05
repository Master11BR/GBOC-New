# GBOC System — Module: Alerts Router (Central de Alertas)
#
# Antes esta rota devolvia sempre uma lista vazia — e, por ser registrada antes, escondia a
# implementação de server_gboc.py. Agora junta, com dados reais:
#   * alertas proativos (proactive_alert_events)
#   * eventos do sistema (system_events)
#   * falhas ativas de agentes e do próprio servidor (modules/job_alert/failures.py)

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("gboc_alerts_module")
router = APIRouter(prefix="/api/v1/server/alerts", tags=["Alertas"])

_SEV_RANK = {"critical": 0, "error": 1, "warning": 2, "info": 3}


def _exec(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    from modules.reports.report_schedules import _exec as ex
    try:
        return ex(sql, params)
    except Exception as e:
        logger.debug(f"[ALERTAS] consulta ignorada: {e}")
        return []


def _event_sev(t: str) -> str:
    t = (t or "").lower()
    if "critical" in t or "failure" in t or "fail" in t:
        return "critical"
    if "error" in t:
        return "error"
    if "warn" in t:
        return "warning"
    return "info"


def _iso(v: Any) -> Optional[str]:
    return v.isoformat() if hasattr(v, "isoformat") else v


def _overview(severity: Optional[str], days: int, agent_id: Optional[str], tenant_id: Optional[str], limit: int) -> Dict[str, Any]:
    since = datetime.now() - timedelta(days=days) if days else datetime(1970, 1, 1)
    agents = {r["agent_id"]: r for r in _exec("SELECT agent_id, hostname, tenant_id FROM agents")}
    allowed = {a for a, r in agents.items() if not tenant_id or r.get("tenant_id") == tenant_id}
    host_to_agent = {str(r.get("hostname") or "").lower(): a for a, r in agents.items()}
    items: List[Dict[str, Any]] = []

    for e in _exec("""SELECT id, rule_type, agent_id, severity, title, message, status, first_seen, last_seen, acknowledged_at
                        FROM proactive_alert_events WHERE status = 'open' OR last_seen >= %s
                        ORDER BY last_seen DESC LIMIT 1000""", (since,)):
        aid = e.get("agent_id")
        if (tenant_id and aid not in allowed) or (agent_id and aid != agent_id):
            continue
        items.append({"id": f"pa-{e['id']}", "origin": "proativo", "severity": (e.get("severity") or "warning").lower(),
                      "hostname": (agents.get(aid) or {}).get("hostname") or aid or "Servidor central", "agent_id": aid,
                      "title": e.get("title"), "message": e.get("message"), "created_at": _iso(e.get("last_seen") or e.get("first_seen")),
                      "status": "aberto" if e.get("status") == "open" else "resolvido",
                      "is_read": bool(e.get("acknowledged_at")) or e.get("status") != "open"})

    for e in _exec("""SELECT event_id, event_type, message, agent_hostname, created_at, is_read FROM system_events
                       WHERE created_at >= %s ORDER BY created_at DESC LIMIT 1000""", (since,)):
        aid = host_to_agent.get(str(e.get("agent_hostname") or "").lower())
        if (tenant_id and aid not in allowed) or (agent_id and aid != agent_id):
            continue
        items.append({"id": f"ev-{e['event_id']}", "origin": "evento", "severity": _event_sev(e.get("event_type")),
                      "hostname": e.get("agent_hostname") or "Servidor central", "agent_id": aid,
                      "title": str(e.get("event_type") or "evento").replace("_", " ").title(), "message": e.get("message"),
                      "created_at": _iso(e.get("created_at")), "status": "lido" if e.get("is_read") else "novo",
                      "is_read": bool(e.get("is_read"))})

    try:
        from modules.job_alert import failures as fl
        fdata = fl.collect(days or 0, None, None, agent_id, tenant_id, None, False)
        for f in fdata["failures"]:
            sev = "critical" if f["kind"] in ("agent_auth", "server_module") or (f.get("consecutive") or 0) >= 3 else "error"
            items.append({"id": f"fl-{f['key']}", "origin": "falha", "severity": sev, "hostname": f.get("hostname"),
                          "agent_id": f.get("agent_id"), "title": f"{f['kind_label']}: {f['title']}", "message": f.get("reason"),
                          "created_at": f.get("last_failed_at"), "status": "ativa", "is_read": False, "failure_key": f["key"]})
    except Exception as e:
        logger.warning(f"[ALERTAS] falhas ativas indisponíveis: {e}")

    total_all = len(items)
    unread = sum(1 for i in items if not i.get("is_read"))
    critical = sum(1 for i in items if i["severity"] in ("critical", "error") and i.get("status") in ("aberto", "ativa", "novo"))
    if severity:
        want = {"critical": ("critical", "error")}.get(severity, (severity,))
        items = [i for i in items if i["severity"] in want]
    items.sort(key=lambda i: str(i.get("created_at") or ""), reverse=True)
    return {"status": "success", "total": total_all, "unread": unread, "critical": critical,
            "by_origin": {o: sum(1 for i in items if i["origin"] == o) for o in ("proativo", "falha", "evento")},
            "alerts": items[:limit]}


@router.get("/overview")
async def get_alerts_overview(severity: Optional[str] = Query(None, pattern="^(critical|error|warning|info)?$"),
                              days: int = Query(30, ge=0, le=3650), agent_id: Optional[str] = None,
                              tenant_id: Optional[str] = None, limit: int = Query(300, ge=1, le=2000)):
    """Alertas proativos + falhas ativas (agentes e servidor) + eventos do sistema."""
    try:
        return JSONResponse(await asyncio.to_thread(_overview, severity or None, days, agent_id, tenant_id, limit))
    except Exception as e:
        logger.error(f"[ALERTAS] overview: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e), "alerts": []})
