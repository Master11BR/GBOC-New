"""
GBOC Server — Painel de Decisão (dados para os gráficos do Dashboard Central).

GET /api/v1/analytics/decision?days=14[&agent_id=...]

Tudo calculado pelos mesmos critérios dos relatórios (report_core), a partir dos dados reais:
  * KPIs de decisão: proteção dentro do RPO, sucesso 24 h / período, falhas pendentes, risco de capacidade;
  * séries: sucesso/falha por dia e taxa diária; falhas por agente; idade do último backup por agente;
    armazenamento total com projeção linear de 30 dias;
  * fila de ações prioritárias (o que fazer agora), cada uma com o relatório de apoio.
"""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from modules.reports import report_core as rc
from modules.reports.report_source_server import ServerReportSource

router = APIRouter(prefix="/api/v1/analytics", tags=["Painel de Decisão"])


def _decision(days: int, agent_id: Optional[str]) -> Dict[str, Any]:
    with ServerReportSource() as src:
        ctx = rc.ReportContext(src, days=days, agent_ids=[a for a in (agent_id or "").split(",") if a] or None)
        runs = ctx.runs
        done = [r for r in runs if r["status"] in ("success", "failed")]
        ok = [r for r in done if r["status"] == "success"]
        day_ago = ctx.end - timedelta(hours=24)
        d24 = [r for r in done if r["started_at"] >= day_ago]
        ok24 = [r for r in d24 if r["status"] == "success"]
        rpo = rc._task_rpo_rows(ctx)
        within = [x for x in rpo if x["tone"] in ("ok", "warn")]
        growth = rc._repo_growth(ctx)
        pending = [f for f in ctx.job_failures if not f.get("resolved_at")]
        agents = ctx.agents
        online = [a for a in agents if ctx.agent_status(a) == "online"]

        # Séries diárias
        s_ok = rc._daily_counts(ctx, ok)
        s_fail = rc._daily_counts(ctx, [r for r in done if r["status"] == "failed"])
        rate = [round(o / (o + f) * 100, 1) if (o + f) else None for o, f in zip(s_ok, s_fail)]
        vol = rc._daily_counts(ctx, ok, value=lambda r: r["bytes_added"] or r["bytes"] or 0)

        # Falhas por agente (top 10)
        fails_by_agent = Counter(r.get("agent_id") for r in done if r["status"] == "failed")
        top_fail = [{"agent_id": a, "host": ctx.host(a), "failures": n,
                     "rate": round(sum(1 for r in done if r.get("agent_id") == a and r["status"] == "success") /
                                   max(1, sum(1 for r in done if r.get("agent_id") == a)) * 100, 1)}
                    for a, n in fails_by_agent.most_common(10)]

        # Idade do último backup bem-sucedido por agente (pior tarefa do agente)
        age_by_agent: Dict[Any, Dict[str, Any]] = {}
        for x in rpo:
            aid = x["task"].get("agent_id")
            cur = age_by_agent.get(aid)
            age = x["age_h"] if x["age_h"] is not None else float("inf")
            if cur is None or age > cur["_age"]:
                age_by_agent[aid] = {"_age": age, "agent_id": aid, "host": ctx.host(aid), "task": x["task"].get("name"),
                                     "age_h": x["age_h"], "tone": x["tone"], "target_h": x["target_h"]}
        ages = sorted(age_by_agent.values(), key=lambda v: -v["_age"])
        for v in ages:
            v.pop("_age", None)

        # Armazenamento total por dia + projeção de 30 dias (regressão linear da série)
        by_repo = defaultdict(list)
        for h in ctx.repo_history:
            d, v = rc.to_dt(h.get("recorded_at")), rc.to_float(h.get("size_bytes"))
            if d and v is not None:
                by_repo[(h.get("agent_id"), h.get("repo_id"))].append((d, v))
        storage = []
        for d in ctx.day_list:
            de = datetime(d.year, d.month, d.day, 23, 59, 59)
            tot, any_ = 0.0, False
            for pts in by_repo.values():
                prev = [v for (t, v) in pts if t <= de]
                if prev:
                    tot += prev[-1]
                    any_ = True
            storage.append(tot if any_ else None)
        pts = [(datetime(d.year, d.month, d.day), v) for d, v in zip(ctx.day_list, storage) if v is not None]
        slope = rc.linear_slope_per_day(pts)
        proj_labels, proj = [], []
        if slope is not None and pts:
            last_d, last_v = pts[-1]
            for i in range(1, 31):
                dd = last_d + timedelta(days=i)
                proj_labels.append(dd.strftime("%d/%m"))
                proj.append(max(0.0, last_v + slope * i))
        total_storage = sum(x["size"] or 0 for x in growth)
        risky = [x for x in growth if x["tone"] == "bad"]

        # Ações prioritárias
        actions: List[Dict[str, Any]] = []
        for a in agents:
            if ctx.agent_status(a) != "online":
                actions.append({"severity": "bad", "text": f"Agente {ctx.host(a['agent_id'])} offline desde {rc.fmt_dt(a.get('last_heartbeat'))}",
                                "report": "REP-05", "agent_id": a["agent_id"]})
        for x in sorted([x for x in rpo if x["tone"] == "bad"], key=lambda x: -(x["age_h"] or 1e9))[:8]:
            t = x["task"]
            actions.append({"severity": "bad", "text": f"{ctx.host(t.get('agent_id'))} / {t.get('name')}: "
                            + ("nunca concluiu backup com sucesso" if x["age_h"] is None else f"último backup válido há {rc.fmt_age_hours(x['age_h'])}"),
                            "report": "REP-02", "agent_id": t.get("agent_id")})
        for x in risky[:5]:
            actions.append({"severity": "bad", "text": f"{ctx.host(x['repo'].get('agent_id'))} / {x['repo'].get('name')}: {x['status'].lower()}",
                            "report": "REP-06", "agent_id": x["repo"].get("agent_id")})
        for f in pending[:5]:
            actions.append({"severity": "warn", "text": f"Falha pendente em {ctx.host(f.get('agent_id'))} / {f.get('task_name') or f.get('task_id')}: {str(f.get('failure_reason') or '')[:90]}",
                            "report": "REP-04", "agent_id": f.get("agent_id")})
        cats = Counter(rc.classify_error(r.get("error"))[0] for r in done if r["status"] == "failed" and r["started_at"] >= ctx.end - timedelta(days=7))
        if cats:
            top, n = cats.most_common(1)[0]
            actions.append({"severity": "warn", "text": f"Causa de falha mais frequente nos últimos 7 dias: {top} ({n}×)", "report": "REP-04"})

        return {
            "status": "success", "days": ctx.days, "generated_at": ctx.end.isoformat(),
            "kpis": {
                "agents_total": len(agents), "agents_online": len(online),
                "tasks_total": len(rpo), "tasks_in_rpo": len(within),
                "rpo_pct": round(len(within) / len(rpo) * 100, 1) if rpo else None, "rpo_target_h": ctx.rpo_hours,
                "success_24h_pct": round(len(ok24) / len(d24) * 100, 1) if d24 else None, "runs_24h": len(d24),
                "success_pct": round(len(ok) / len(done) * 100, 1) if done else None, "runs": len(done),
                "success_goal": ctx.success_goal, "pending_failures": len(pending),
                "storage_total": total_storage, "storage_growth_month": (slope * 30) if slope else None,
                "repos_at_risk": len(risky),
            },
            "daily": {"labels": ctx.day_labels, "success": s_ok, "failed": s_fail, "rate": rate, "volume": vol},
            "failures_by_agent": top_fail,
            "backup_age": ages[:15],
            "storage": {"labels": ctx.day_labels, "values": storage, "proj_labels": proj_labels, "projection": proj},
            "actions": actions[:20],
        }


@router.get("/decision")
async def decision_panel(days: int = Query(14, ge=1, le=365), agent_id: Optional[str] = Query(None)):
    return await asyncio.to_thread(_decision, days, agent_id)
