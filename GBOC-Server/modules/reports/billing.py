"""
GBOC Server — Fechamento mensal de faturamento (MSP).

Para cada cliente (organização) e mês:
  * agentes faturáveis = cadastrados até o fim do mês e com atividade no mês (heartbeat ou execução);
  * armazenamento faturável = PICO do mês de cada repositório (histórico de tamanho sincronizado pelos
    agentes; mês corrente sem histórico usa o tamanho atual), somado por cliente;
  * execuções, sucesso e dados novos no mês (informativos);
  * valor = mensalidade fixa + agentes × preço por agente + TB × preço por TB (preço do cliente ou padrão
    de Configurações > Relatórios).
"Fechar o mês" congela os valores (não mudam mais com novos dados), com hash de integridade, e libera o
demonstrativo no portal do cliente. Pode ser reaberto por um administrador. Fechamento automático opcional
no dia 1 (mês anterior).

Rotas: /api/v1/billing/preview · /close · /closings · /closings/{period}/export · /pricing
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import threading
import time
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger("gboc_billing")
router = APIRouter(prefix="/api/v1/billing", tags=["Faturamento"])
SCHEMA = [
    "ALTER TABLE msp_organizations ADD COLUMN IF NOT EXISTS price_per_agent NUMERIC(12,2)",
    "ALTER TABLE msp_organizations ADD COLUMN IF NOT EXISTS price_per_tb NUMERIC(12,2)",
    "ALTER TABLE msp_organizations ADD COLUMN IF NOT EXISTS base_fee NUMERIC(12,2)",
    """CREATE TABLE IF NOT EXISTS billing_closings (
        id SERIAL PRIMARY KEY,
        period VARCHAR(7) NOT NULL,
        tenant_id VARCHAR(100) NOT NULL,
        tenant_name TEXT,
        plan TEXT,
        agents INTEGER,
        max_agents INTEGER,
        storage_bytes BIGINT,
        executions INTEGER,
        success INTEGER,
        bytes_added BIGINT,
        base_fee NUMERIC(12,2),
        price_per_agent NUMERIC(12,2),
        price_per_tb NUMERIC(12,2),
        currency VARCHAR(8),
        amount NUMERIC(14,2),
        details JSONB,
        integrity VARCHAR(64),
        closed_by TEXT,
        closed_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
        UNIQUE (period, tenant_id)
    )""",
]
_ready = False
_lock = threading.Lock()


def _db_exec(sql: str, params: Any = (), fetch: bool = True) -> List[Dict[str, Any]]:
    from modules.reports.report_schedules import _exec
    return _exec(sql, params, fetch)


def ensure_schema() -> None:
    global _ready
    if not _ready:
        with _lock:
            if not _ready:
                for s in SCHEMA:
                    _db_exec(s, fetch=False)
                _ready = True


def period_bounds(period: str) -> Tuple[datetime, datetime]:
    try:
        y, m = int(period[:4]), int(period[5:7])
        if len(period) != 7 or period[4] != "-" or not 1 <= m <= 12:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(400, "Período inválido (use AAAA-MM)")
    start = datetime(y, m, 1)
    end = datetime(y, m, monthrange(y, m)[1], 23, 59, 59)
    return start, end


def _settings() -> Dict[str, str]:
    rows = _db_exec("SELECT key, value FROM server_settings WHERE category='reports' AND key IN ('price_per_agent','price_per_tb','currency','billing_base_fee')")
    return {r["key"]: r["value"] for r in rows}


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def compute(period: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    ensure_schema()
    start, end = period_bounds(period)
    now = datetime.now()
    cfg = _settings()
    d_agent, d_tb, d_base = _num(cfg.get("price_per_agent")), _num(cfg.get("price_per_tb")), _num(cfg.get("billing_base_fee"))
    currency = cfg.get("currency") or "BRL"
    orgs = _db_exec("SELECT org_id, name, plan, max_agents, status, price_per_agent, price_per_tb, base_fee FROM msp_organizations"
                    + (" WHERE org_id=%s" if tenant_id else "") + " ORDER BY name", (tenant_id,) if tenant_id else ())
    agents = _db_exec("SELECT agent_id, hostname, tenant_id, registered_at, last_heartbeat FROM agents WHERE tenant_id IS NOT NULL")
    act = {r["agent_id"]: r for r in _db_exec("""SELECT agent_id, COUNT(*) AS runs,
                SUM(CASE WHEN LOWER(status) IN ('completed','success','succeeded','ok') THEN 1 ELSE 0 END) AS ok,
                COALESCE(SUM(bytes_added),0) AS added FROM agent_task_executions WHERE started_at BETWEEN %s AND %s GROUP BY agent_id""",
                (start, end))}
    peak = {(r["agent_id"], r["repo_id"]): int(r["peak"] or 0) for r in _db_exec(
        "SELECT agent_id, repo_id, MAX(size_bytes) AS peak FROM agent_repo_size_history WHERE recorded_at BETWEEN %s AND %s GROUP BY agent_id, repo_id",
        (start, end))}
    current = [r for r in _db_exec("SELECT agent_id, repo_id, name, size_bytes FROM agent_repositories WHERE removed_at IS NULL")]
    is_current_month = start <= now <= end
    rows = []
    for o in orgs:
        items, n_agents, storage, runs, ok, added = [], 0, 0, 0, 0, 0
        for a in [a for a in agents if a["tenant_id"] == o["org_id"]]:
            reg, hb = a.get("registered_at"), a.get("last_heartbeat")
            ac = act.get(a["agent_id"]) or {}
            active = (reg is None or reg <= end) and ((hb is not None and hb >= start) or int(ac.get("runs") or 0) > 0)
            a_storage = 0
            for rp in [r for r in current if r["agent_id"] == a["agent_id"]]:
                v = peak.get((a["agent_id"], rp["repo_id"]))
                if v is None and is_current_month:
                    v = int(rp.get("size_bytes") or 0)
                a_storage += int(v or 0)
            for (aid, rid), v in peak.items():                   # repositórios removidos depois, mas existentes no mês
                if aid == a["agent_id"] and not any(r["repo_id"] == rid and r["agent_id"] == aid for r in current):
                    a_storage += v
            if not active and not a_storage:
                continue
            n_agents += 1 if active else 0
            storage += a_storage
            runs += int(ac.get("runs") or 0)
            ok += int(ac.get("ok") or 0)
            added += int(ac.get("added") or 0)
            items.append({"agent_id": a["agent_id"], "hostname": a["hostname"], "active": active, "storage_bytes": a_storage,
                          "executions": int(ac.get("runs") or 0), "success": int(ac.get("ok") or 0)})
        p_agent = _num(o.get("price_per_agent"), d_agent)
        p_tb = _num(o.get("price_per_tb"), d_tb)
        base = _num(o.get("base_fee"), d_base)
        tb = storage / 1024 ** 4
        amount = round(base + n_agents * p_agent + tb * p_tb, 2)
        rows.append({"period": period, "tenant_id": o["org_id"], "tenant_name": o["name"], "plan": o.get("plan"),
                     "agents": n_agents, "max_agents": o.get("max_agents"), "storage_bytes": storage, "storage_tb": round(tb, 4),
                     "executions": runs, "success": ok, "bytes_added": added, "base_fee": base, "price_per_agent": p_agent,
                     "price_per_tb": p_tb, "currency": currency, "amount": amount, "details": items,
                     "over_limit": bool(o.get("max_agents") and n_agents > int(o["max_agents"]))})
    return {"period": period, "start": start.isoformat(), "end": end.isoformat(), "currency": currency, "rows": rows,
            "total": round(sum(r["amount"] for r in rows), 2), "partial": end > now}


def _ser(r: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in r.items():
        if isinstance(v, Decimal):
            v = float(v)
        elif hasattr(v, "isoformat"):
            v = v.isoformat(sep=" ", timespec="seconds")
        out[k] = v
    return out


def closings(period: Optional[str] = None, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    ensure_schema()
    sql, p = "SELECT * FROM billing_closings WHERE 1=1", []
    if period:
        sql += " AND period=%s"
        p.append(period)
    if tenant_id:
        sql += " AND tenant_id=%s"
        p.append(tenant_id)
    return [_ser(r) for r in _db_exec(sql + " ORDER BY period DESC, tenant_name", tuple(p))]


def close(period: str, user: str, force: bool = False) -> Dict[str, Any]:
    start, end = period_bounds(period)
    if end > datetime.now() and not force:
        raise HTTPException(400, "O mês ainda não terminou — feche a partir do dia 1 do mês seguinte")
    if _db_exec("SELECT 1 FROM billing_closings WHERE period=%s LIMIT 1", (period,)):
        raise HTTPException(409, f"O mês {period} já está fechado (reabra para recalcular)")
    data = compute(period)
    for r in data["rows"]:
        raw = json.dumps({k: r[k] for k in ("period", "tenant_id", "agents", "storage_bytes", "amount")}, sort_keys=True)
        _db_exec("""INSERT INTO billing_closings (period, tenant_id, tenant_name, plan, agents, max_agents, storage_bytes, executions, success,
                    bytes_added, base_fee, price_per_agent, price_per_tb, currency, amount, details, integrity, closed_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                 (period, r["tenant_id"], r["tenant_name"], r["plan"], r["agents"], r["max_agents"], r["storage_bytes"], r["executions"],
                  r["success"], r["bytes_added"], r["base_fee"], r["price_per_agent"], r["price_per_tb"], r["currency"], r["amount"],
                  json.dumps(r["details"]), hashlib.sha256(raw.encode()).hexdigest(), user), False)
    logger.info(f"[FATURAMENTO] Mês {period} fechado por {user}: {len(data['rows'])} cliente(s), total {data['total']}")
    return {"period": period, "tenants": len(data["rows"]), "total": data["total"], "currency": data["currency"]}


def auto_close_loop() -> None:
    time.sleep(300)
    while True:
        try:
            ensure_schema()
            rows = _db_exec("SELECT value FROM server_settings WHERE category='reports' AND key='billing_auto_close'")
            if rows and str(rows[0]["value"]).lower() == "true":
                prev = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
                if not _db_exec("SELECT 1 FROM billing_closings WHERE period=%s LIMIT 1", (prev,)):
                    close(prev, "automático")
        except Exception as e:
            logger.warning(f"[FATURAMENTO] Fechamento automático: {e}")
        time.sleep(6 * 3600)


def start_scheduler() -> None:
    threading.Thread(target=auto_close_loop, name="gboc-billing", daemon=True).start()


def csv_export(rows: List[Dict[str, Any]], detailed: bool = True) -> str:
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Período", "Cliente", "Plano", "Agentes", "Limite", "Armazenamento (GB)", "Execuções", "Sucesso", "Mensalidade",
                "Preço/agente", "Preço/TB", "Moeda", "Valor", "Integridade"])
    for r in rows:
        w.writerow([r["period"], r["tenant_name"], r.get("plan") or "", r["agents"], r.get("max_agents") or "",
                    f"{(r['storage_bytes'] or 0) / 1024 ** 3:.2f}".replace(".", ","), r["executions"], r["success"],
                    f"{r['base_fee'] or 0:.2f}".replace(".", ","), f"{r['price_per_agent'] or 0:.2f}".replace(".", ","),
                    f"{r['price_per_tb'] or 0:.2f}".replace(".", ","), r["currency"], f"{r['amount'] or 0:.2f}".replace(".", ","),
                    r.get("integrity") or ""])
    if detailed:
        w.writerow([])
        w.writerow(["Período", "Cliente", "Agente", "Ativo no mês", "Armazenamento (GB)", "Execuções", "Sucesso"])
        for r in rows:
            for d in r.get("details") or []:
                w.writerow([r["period"], r["tenant_name"], d["hostname"], "sim" if d["active"] else "não",
                            f"{(d['storage_bytes'] or 0) / 1024 ** 3:.2f}".replace(".", ","), d["executions"], d["success"]])
    return out.getvalue()


def _require_admin(request: Request) -> Dict[str, Any]:
    u = getattr(request.state, "user", None) or {}
    if (u.get("role") or "").lower() not in ("", "admin", "superadmin", "administrator"):
        raise HTTPException(403, "Somente administradores podem fechar ou reabrir o faturamento.")
    return u


@router.get("/preview")
async def preview(period: Optional[str] = None):
    period = period or date.today().strftime("%Y-%m")
    return {"status": "success", **(await asyncio.to_thread(compute, period)),
            "closed": bool(await asyncio.to_thread(closings, period))}


@router.post("/close")
async def close_period(request: Request):
    u = _require_admin(request)
    b = await request.json() or {}
    res = await asyncio.to_thread(close, str(b.get("period") or ""), u.get("username") or "?", bool(b.get("force")))
    return {"status": "success", **res}


@router.delete("/close/{period}")
async def reopen_period(period: str, request: Request):
    _require_admin(request)
    period_bounds(period)
    await asyncio.to_thread(_db_exec, "DELETE FROM billing_closings WHERE period=%s", (period,), False)
    return {"status": "success"}


@router.get("/closings")
async def list_closings(period: Optional[str] = None):
    rows = await asyncio.to_thread(closings, period)
    periods: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        p = periods.setdefault(r["period"], {"period": r["period"], "tenants": 0, "total": 0.0, "currency": r["currency"],
                                             "closed_at": r["closed_at"], "closed_by": r["closed_by"]})
        p["tenants"] += 1
        p["total"] = round(p["total"] + (r["amount"] or 0), 2)
    return {"status": "success", "periods": sorted(periods.values(), key=lambda p: p["period"], reverse=True), "rows": rows}


@router.get("/closings/{period}/export")
async def export_closing(period: str):
    rows = await asyncio.to_thread(closings, period)
    if not rows:
        raise HTTPException(404, "Mês não fechado")
    data = csv_export(rows).encode("utf-8-sig")
    return StreamingResponse(io.BytesIO(data), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename=GBOC_faturamento_{period}.csv"})


@router.get("/pricing")
async def get_pricing():
    await asyncio.to_thread(ensure_schema)
    rows = await asyncio.to_thread(_db_exec, "SELECT org_id, name, plan, max_agents, status, price_per_agent, price_per_tb, base_fee FROM msp_organizations ORDER BY name")
    cfg = await asyncio.to_thread(_settings)
    auto = await asyncio.to_thread(_db_exec, "SELECT value FROM server_settings WHERE category='reports' AND key='billing_auto_close'")
    return {"status": "success", "tenants": [_ser(r) for r in rows],
            "defaults": {"price_per_agent": _num(cfg.get("price_per_agent")), "price_per_tb": _num(cfg.get("price_per_tb")),
                         "base_fee": _num(cfg.get("billing_base_fee")), "currency": cfg.get("currency") or "BRL"},
            "auto_close": bool(auto and str(auto[0]["value"]).lower() == "true")}


@router.put("/pricing")
async def put_pricing(request: Request):
    _require_admin(request)
    b = await request.json() or {}
    await asyncio.to_thread(ensure_schema)

    def num_or_none(v):
        if v in (None, ""):
            return None
        f = float(v)
        if f < 0:
            raise HTTPException(400, "Valores não podem ser negativos")
        return f
    for t in b.get("tenants") or []:
        await asyncio.to_thread(_db_exec, "UPDATE msp_organizations SET price_per_agent=%s, price_per_tb=%s, base_fee=%s WHERE org_id=%s",
                                (num_or_none(t.get("price_per_agent")), num_or_none(t.get("price_per_tb")), num_or_none(t.get("base_fee")),
                                 t.get("org_id")), False)
    d = b.get("defaults") or {}
    for key, val in (("price_per_agent", d.get("price_per_agent")), ("price_per_tb", d.get("price_per_tb")),
                     ("billing_base_fee", d.get("base_fee")), ("currency", d.get("currency")),
                     ("billing_auto_close", None if b.get("auto_close") is None else ("true" if b.get("auto_close") else "false"))):
        if val is None:
            continue
        if key != "currency" and key != "billing_auto_close":
            val = str(num_or_none(val) or 0)
        await asyncio.to_thread(_db_exec, """INSERT INTO server_settings (category, key, value, type, description) VALUES ('reports', %s, %s, 'text', %s)
            ON CONFLICT (category, key) DO UPDATE SET value = EXCLUDED.value""", (key, str(val)[:20], "Faturamento"), False)
    return await get_pricing()
