"""
GBOC Server — Políticas centrais de backup.

Uma política reúne o padrão de proteção e é aplicada a vários agentes de uma vez:
  * tarefas (todas ou as que contêm um texto no nome): agendamento, retenção, novas tentativas;
  * agente: janelas de manutenção e limite de banda;
  * backup imutável (dias e tipo de bloqueio) nos repositórios das tarefas.
Alvo: todos os agentes, um cliente (tenant) e/ou agentes escolhidos. Se um agente estiver em mais de uma
política, vale a de maior prioridade. A aplicação usa o canal do Gerenciamento Remoto (lote com resultado por
agente) e a conformidade compara a política com o que os agentes sincronizaram ("fora da política").

Rotas: /api/v1/policies (CRUD) · POST /{id}/apply · GET /compliance
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/v1/policies", tags=["Políticas centrais"])
SCHEMA = """CREATE TABLE IF NOT EXISTS backup_policies (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 100,
    scope_all BOOLEAN DEFAULT FALSE,
    tenant_id VARCHAR(100),
    agent_ids JSONB DEFAULT '[]'::jsonb,
    task_filter TEXT DEFAULT '',
    settings JSONB DEFAULT '{}'::jsonb,
    version INTEGER DEFAULT 1,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
    updated_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
    last_applied_at TIMESTAMP
)"""
_ready = False
_lock = threading.Lock()
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
RET_LABEL = {"days": "d", "weekly": "s", "monthly": "m", "yearly": "a"}


def _db_exec(sql: str, params: Any = (), fetch: bool = True) -> List[Dict[str, Any]]:
    from modules.reports.report_schedules import _exec
    return _exec(sql, params, fetch)


def ensure_schema() -> None:
    global _ready
    if not _ready:
        with _lock:
            if not _ready:
                _db_exec(SCHEMA, fetch=False)
                _ready = True


def _ser(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v.isoformat(sep=" ", timespec="seconds") if hasattr(v, "isoformat") else v) for k, v in r.items()}


def _windows(v: Any, what: str, need_mbps: bool = False) -> List[Dict[str, Any]]:
    out = []
    for w in v or []:
        days = sorted({int(d) for d in (w.get("days") or []) if str(d).isdigit() and 0 <= int(d) <= 6})
        s, e = str(w.get("start") or ""), str(w.get("end") or "")
        if not days or not _HHMM.match(s) or not _HHMM.match(e) or s == e:
            raise HTTPException(400, f"{what}: informe dias e horários HH:MM (início diferente do fim)")
        item = {"days": days, "start": s, "end": e}
        if need_mbps:
            item["mbps"] = max(0.0, float(w.get("mbps") or 0))
        else:
            item["label"] = str(w.get("label") or "")[:80]
        out.append(item)
    return out


def validate_settings(s: Dict[str, Any]) -> Dict[str, Any]:
    s = s or {}
    out: Dict[str, Any] = {}
    sch = s.get("schedule")
    if sch and (sch.get("cron") or sch.get("enabled") is not None):
        cron = str(sch.get("cron") or "").strip()
        if cron and len(cron.split()) != 5:
            raise HTTPException(400, "Agendamento: informe um cron de 5 campos (ex.: 0 22 * * *)")
        out["schedule"] = {"cron": cron or None, "enabled": None if sch.get("enabled") is None else bool(sch["enabled"])}
    ret = s.get("retention")
    if ret:
        r = {}
        for k in RET_LABEL:
            if ret.get(k) not in (None, ""):
                v = int(ret[k])
                if not 0 <= v <= 36500:
                    raise HTTPException(400, "Retenção fora do intervalo")
                r[k] = v
        if r:
            out["retention"] = r
    rt = s.get("retry")
    if rt and any(rt.get(k) is not None for k in ("enabled", "max_attempts", "delay_minutes")):
        out["retry"] = {"enabled": None if rt.get("enabled") is None else bool(rt["enabled"]),
                        "max_attempts": None if rt.get("max_attempts") in (None, "") else max(0, min(10, int(rt["max_attempts"]))),
                        "delay_minutes": None if rt.get("delay_minutes") in (None, "") else max(1, min(1440, int(rt["delay_minutes"])))}
    if s.get("maintenance_windows") is not None:
        out["maintenance_windows"] = _windows(s["maintenance_windows"], "Janela de manutenção")
    bw = s.get("bandwidth")
    if bw is not None:
        out["bandwidth"] = {"default_mbps": max(0.0, float(bw.get("default_mbps") or 0)),
                            "rules": _windows(bw.get("rules"), "Regra de banda", need_mbps=True)}
    im = s.get("immutability")
    if im and int(im.get("days") or 0) > 0:
        lm = str(im.get("lock_mode") or "COMPLIANCE").upper()
        if lm not in ("COMPLIANCE", "GOVERNANCE"):
            raise HTTPException(400, "Tipo de bloqueio inválido")
        out["immutability"] = {"days": max(1, min(3650, int(im["days"]))), "lock_mode": lm, "apply_bucket": bool(im.get("apply_bucket"))}
    if not out:
        raise HTTPException(400, "A política não define nada: preencha ao menos um item")
    return out


def _validate(b: Dict[str, Any]) -> Dict[str, Any]:
    name = str(b.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(400, "Informe o nome da política")
    ids = [str(a) for a in (b.get("agent_ids") or []) if str(a).strip()]
    scope_all = bool(b.get("scope_all"))
    tenant = (str(b.get("tenant_id")).strip() or None) if b.get("tenant_id") else None
    if not scope_all and not ids and not tenant:
        raise HTTPException(400, "Escolha o alvo: todos os agentes, um cliente ou agentes específicos")
    return {"name": name, "description": str(b.get("description") or "")[:500], "enabled": bool(b.get("enabled", True)),
            "priority": max(0, min(1000, int(b.get("priority") or 100))), "scope_all": scope_all, "tenant_id": tenant,
            "agent_ids": json.dumps(sorted(set(ids))), "task_filter": str(b.get("task_filter") or "").strip()[:100],
            "settings": json.dumps(validate_settings(b.get("settings") or {}))}


def _policies(enabled_only: bool = False) -> List[Dict[str, Any]]:
    ensure_schema()
    rows = _db_exec("SELECT * FROM backup_policies" + (" WHERE enabled" if enabled_only else "") + " ORDER BY priority DESC, id")
    return rows


def _agents() -> List[Dict[str, Any]]:
    return _db_exec("SELECT agent_id, hostname, tenant_id, status, last_heartbeat, agent_version FROM agents ORDER BY hostname")


def targets(policy: Dict[str, Any], agents: List[Dict[str, Any]]) -> List[str]:
    ids = set(policy.get("agent_ids") or [])
    return [a["agent_id"] for a in agents if policy.get("scope_all") or a["agent_id"] in ids or
            (policy.get("tenant_id") and a.get("tenant_id") == policy["tenant_id"])]


def effective_map(policies: List[Dict[str, Any]], agents: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Política efetiva por agente (maior prioridade; empate → a mais recente)."""
    eff: Dict[str, Dict[str, Any]] = {}
    for p in sorted([p for p in policies if p.get("enabled")], key=lambda p: (p.get("priority") or 0, p.get("id") or 0)):
        for aid in targets(p, agents):
            eff[aid] = p                       # sobrescreve com a de maior prioridade (ordenação crescente)
    return eff


def agent_payload(p: Dict[str, Any]) -> Dict[str, Any]:
    s = p.get("settings") or {}
    return {"id": p["id"], "name": p["name"], "version": p.get("version") or 1, "task_filter": p.get("task_filter") or "", **s}


def _parse_ret(text: Optional[str]) -> Dict[str, int]:
    out = {}
    inv = {v: k for k, v in RET_LABEL.items()}
    for part in str(text or "").split("/"):
        m = re.match(r"\s*(\d+)\s*([dsma])\s*$", part)
        if m:
            out[inv[m.group(2)]] = int(m.group(1))
    return out


def _same_windows(a: Any, b: Any, keys=("days", "start", "end")) -> bool:
    norm = lambda L: sorted(json.dumps({k: w.get(k) for k in keys}, sort_keys=True) for w in (L or []))
    return norm(a) == norm(b)


def compliance() -> Dict[str, Any]:
    pols = _policies()
    agents = _agents()
    eff = effective_map(pols, agents)
    ops = {r["agent_id"]: r for r in _db_exec("SELECT * FROM agent_operation")} if _table_exists("agent_operation") else {}
    tasks: Dict[str, List[Dict[str, Any]]] = {}
    for t in _db_exec("SELECT agent_id, task_id, name, repository_id, schedule_cron, schedule_enabled, enabled, retention_policy FROM agent_tasks WHERE removed_at IS NULL"):
        tasks.setdefault(t["agent_id"], []).append(t)
    host = {a["agent_id"]: a for a in agents}
    rows = []
    for aid, p in eff.items():
        a = host.get(aid) or {}
        s = p.get("settings") or {}
        issues: List[str] = []
        op = ops.get(aid)
        marker = (op or {}).get("central_policy") or {}
        if not op:
            state = "sem dados"
            issues.append("Agente ainda não sincronizou o estado operacional (atualize o GBOC Agent)")
        else:
            if marker.get("id") != p["id"]:
                issues.append("Política nunca aplicada neste agente" if not marker else f"Aplicada outra política: {marker.get('name')}")
            elif int(marker.get("version") or 0) != int(p.get("version") or 1):
                issues.append(f"Versão aplicada v{marker.get('version')} — atual v{p.get('version')}")
            if "maintenance_windows" in s and not _same_windows(op.get("maintenance_windows"), s["maintenance_windows"]):
                issues.append("Janelas de manutenção diferentes da política")
            if "bandwidth" in s:
                bw = op.get("bandwidth") or {}
                if float(bw.get("default_mbps") or 0) != float(s["bandwidth"].get("default_mbps") or 0) or \
                        not _same_windows(bw.get("rules"), s["bandwidth"].get("rules"), ("days", "start", "end", "mbps")):
                    issues.append("Limite de banda diferente da política")
            if "immutability" in s:
                flt0 = (p.get("task_filter") or "").lower()
                repo_ids = {t.get("repository_id") for t in tasks.get(aid, []) if t.get("repository_id")
                            and (not flt0 or flt0 in str(t.get("name") or "").lower())}
                scope = [r for r in (op.get("immutability") or []) if not repo_ids or r.get("repo_id") in repo_ids]
                bad = [r for r in scope if r.get("supported_modes") and len(r["supported_modes"]) > 1
                       and (r.get("mode") == "off" or int(r.get("days") or 0) < s["immutability"]["days"])]
                if bad:
                    issues.append("Sem imutabilidade conforme a política: " + ", ".join(r.get("name") for r in bad[:5]))
                unprot = [r for r in scope if r.get("mode") not in (None, "off")
                          and (r.get("last_check") or {}).get("protected") is False]
                if unprot:
                    issues.append("Imutabilidade configurada mas não comprovada: " + ", ".join(r.get("name") for r in unprot[:5]))
            flt = (p.get("task_filter") or "").lower()
            for t in tasks.get(aid, []):
                if flt and flt not in str(t.get("name") or "").lower():
                    continue
                sch = s.get("schedule") or {}
                if sch.get("cron") and (t.get("schedule_cron") or "").strip() != sch["cron"]:
                    issues.append(f"Tarefa {t['name']}: agendamento {t.get('schedule_cron') or '—'} (política {sch['cron']})")
                if sch.get("enabled") is not None and bool(t.get("schedule_enabled")) != sch["enabled"]:
                    issues.append(f"Tarefa {t['name']}: agendamento {'ativo' if t.get('schedule_enabled') else 'desativado'}")
                ret = s.get("retention") or {}
                cur = _parse_ret(t.get("retention_policy"))
                diff = [k for k, v in ret.items() if int(cur.get(k) or 0) != int(v)]
                if diff:
                    issues.append(f"Tarefa {t['name']}: retenção {t.get('retention_policy') or '—'}")
            state = "conforme" if not issues else "fora da política"
        rows.append({"agent_id": aid, "hostname": a.get("hostname") or aid, "tenant_id": a.get("tenant_id"),
                     "policy_id": p["id"], "policy": p["name"], "version": p.get("version"), "state": state,
                     "applied": marker if marker else None, "issues": issues[:12]})
    rows.sort(key=lambda r: ({"fora da política": 0, "sem dados": 1, "conforme": 2}[r["state"]], str(r["hostname"]).lower()))
    no_policy = [{"agent_id": a["agent_id"], "hostname": a["hostname"]} for a in agents if a["agent_id"] not in eff]
    return {"agents": rows, "without_policy": no_policy,
            "summary": {"conforme": sum(1 for r in rows if r["state"] == "conforme"),
                        "fora": sum(1 for r in rows if r["state"] == "fora da política"),
                        "sem_dados": sum(1 for r in rows if r["state"] == "sem dados"), "sem_politica": len(no_policy)}}


def _table_exists(name: str) -> bool:
    return bool(_db_exec("SELECT 1 FROM information_schema.tables WHERE table_name=%s", (name,)))


def _require_write(request: Request) -> Dict[str, Any]:
    u = getattr(request.state, "user", None) or {}
    role = (u.get("role") or "").lower()
    if role and role not in ("admin", "superadmin", "administrator", "operator"):
        raise HTTPException(403, "Requer perfil admin ou operator.")
    return u


@router.get("")
async def list_policies():
    rows = await asyncio.to_thread(_policies)
    agents = await asyncio.to_thread(_agents)
    eff = effective_map(rows, agents)
    out = []
    for r in rows:
        t = targets(r, agents)
        out.append({**_ser(r), "targets": len(t), "effective_on": sum(1 for a in t if eff.get(a, {}).get("id") == r["id"])})
    return {"status": "success", "policies": out}


@router.post("")
async def create_policy(request: Request):
    u = _require_write(request)
    v = _validate(await request.json() or {})
    await asyncio.to_thread(ensure_schema)
    rows = await asyncio.to_thread(_db_exec, """INSERT INTO backup_policies (name, description, enabled, priority, scope_all, tenant_id,
        agent_ids, task_filter, settings, created_by) VALUES (%(name)s, %(description)s, %(enabled)s, %(priority)s, %(scope_all)s,
        %(tenant_id)s, %(agent_ids)s::jsonb, %(task_filter)s, %(settings)s::jsonb, %(u)s) RETURNING *""", {**v, "u": u.get("username") or "?"})
    return {"status": "success", "policy": _ser(rows[0])}


@router.put("/{policy_id}")
async def update_policy(policy_id: int, request: Request):
    _require_write(request)
    v = _validate(await request.json() or {})
    rows = await asyncio.to_thread(_db_exec, """UPDATE backup_policies SET name=%(name)s, description=%(description)s, enabled=%(enabled)s,
        priority=%(priority)s, scope_all=%(scope_all)s, tenant_id=%(tenant_id)s, agent_ids=%(agent_ids)s::jsonb, task_filter=%(task_filter)s,
        version = version + CASE WHEN settings::text <> %(settings)s::jsonb::text OR task_filter <> %(task_filter)s THEN 1 ELSE 0 END,
        settings=%(settings)s::jsonb, updated_at=LOCALTIMESTAMP WHERE id=%(id)s RETURNING *""", {**v, "id": policy_id})
    if not rows:
        raise HTTPException(404, "Política não encontrada")
    return {"status": "success", "policy": _ser(rows[0])}


@router.delete("/{policy_id}")
async def delete_policy(policy_id: int, request: Request):
    _require_write(request)
    await asyncio.to_thread(_db_exec, "DELETE FROM backup_policies WHERE id=%s", (policy_id,), False)
    return {"status": "success"}


@router.get("/compliance")
async def get_compliance():
    await asyncio.to_thread(ensure_schema)
    return {"status": "success", **(await asyncio.to_thread(compliance))}


@router.post("/{policy_id}/apply")
async def apply_policy(policy_id: int, request: Request):
    """Aplica nos agentes onde esta política é a efetiva (lote no Gerenciamento Remoto)."""
    _require_write(request)
    pols = await asyncio.to_thread(_policies)
    p = next((x for x in pols if x["id"] == policy_id), None)
    if not p:
        raise HTTPException(404, "Política não encontrada")
    if not p.get("enabled"):
        raise HTTPException(400, "Política desativada")
    b = {}
    try:
        b = await request.json() or {}
    except Exception:
        pass
    agents = await asyncio.to_thread(_agents)
    eff = effective_map(pols, agents)
    ids = [a for a in targets(p, agents) if eff.get(a, {}).get("id") == p["id"]]
    if b.get("agent_ids"):
        ids = [a for a in ids if a in set(b["agent_ids"])]
    if not ids:
        raise HTTPException(400, "Nenhum agente tem esta política como efetiva (verifique o alvo e as prioridades)")
    from modules.agents.fleet_ops import start_job
    job = await start_job(request, "apply_policy", ids, {"policy_id": policy_id})
    await asyncio.to_thread(_db_exec, "UPDATE backup_policies SET last_applied_at=LOCALTIMESTAMP WHERE id=%s", (policy_id,), False)
    return {"status": "started", "job": job}
