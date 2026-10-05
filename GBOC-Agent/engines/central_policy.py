"""
GBOC Agent — Aplicação de política central (enviada pelo GBOC Server).

Uma política define, de uma vez, para as tarefas do agente (todas ou as que contêm um texto no nome):
agendamento, retenção e novas tentativas; e para o agente: janelas de manutenção, limite de banda e
backup imutável. O agente aplica localmente e guarda a marca {id, nome, versão} da política para que o
Server identifique desvios (alteração local depois da aplicação).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gboc_central_policy")


def _core():
    from shared_core import get_shared_core
    return get_shared_core()


def _valid_cron(expr: str) -> bool:
    parts = str(expr or "").split()
    if len(parts) != 5:
        return False
    try:
        from engines.scheduler import cron_matches_now
        cron_matches_now(expr, datetime.now())
        return True
    except Exception:
        return False


def task_fields(policy: Dict[str, Any]) -> Dict[str, Any]:
    f: Dict[str, Any] = {}
    sch = policy.get("schedule")
    if sch:
        if sch.get("cron"):
            if not _valid_cron(sch["cron"]):
                raise ValueError(f"Agendamento (cron) inválido: {sch['cron']}")
            f["schedule_cron"] = sch["cron"]
        if sch.get("enabled") is not None:
            f["schedule_enabled"] = bool(sch["enabled"])
    ret = policy.get("retention")
    if ret:
        for k in ("days", "weekly", "monthly", "yearly"):
            if ret.get(k) is not None and str(ret.get(k)) != "":
                v = int(ret[k])
                if v < 0 or v > 36500:
                    raise ValueError("Retenção fora do intervalo")
                f[f"retention_{k}"] = v
    rt = policy.get("retry")
    if rt:
        if rt.get("enabled") is not None:
            f["retry_enabled"] = bool(rt["enabled"])
        if rt.get("max_attempts") is not None:
            f["retry_max_attempts"] = max(0, min(10, int(rt["max_attempts"])))
        if rt.get("delay_minutes") is not None:
            f["retry_delay_minutes"] = max(1, min(1440, int(rt["delay_minutes"])))
    return f


def _matching_tasks(task_filter: str) -> List[Dict[str, Any]]:
    with _core().get_db_connection() as conn:
        cur = conn.cursor()
        flt = (task_filter or "").strip()
        if flt:
            cur.execute("SELECT id, name, repository_id FROM tasks WHERE name ILIKE %s ORDER BY id", (f"%{flt}%",))
        else:
            cur.execute("SELECT id, name, repository_id FROM tasks ORDER BY id")
        rows = [{"id": r[0], "name": r[1], "repository_id": r[2]} for r in cur.fetchall()]
        cur.close()
    return rows


def apply(policy: Dict[str, Any]) -> Dict[str, Any]:
    from engines import immutability as imm
    from engines import operation_settings as ops

    if not policy.get("id"):
        raise ValueError("Política sem identificador")
    fields = task_fields(policy)
    report: Dict[str, Any] = {"policy": {"id": policy.get("id"), "name": policy.get("name"), "version": policy.get("version")},
                              "tasks": [], "operation": None, "immutability": [], "errors": []}

    tm = getattr(_core(), "task_manager", None)
    tasks = _matching_tasks(policy.get("task_filter") or "")
    if fields:
        for t in tasks:
            try:
                if tm is not None:
                    tm.update_task(t["id"], dict(fields))
                else:
                    raise RuntimeError("TaskManager indisponível")
                report["tasks"].append(t["name"])
            except Exception as e:
                report["errors"].append(f"Tarefa {t['name']}: {e}")

    marker = {"id": policy.get("id"), "name": policy.get("name"), "version": policy.get("version"),
              "applied_at": datetime.now().isoformat(sep=" ", timespec="seconds"), "task_filter": policy.get("task_filter") or "",
              "task_fields": fields}
    try:
        st = ops.save(policy.get("maintenance_windows") if policy.get("maintenance_windows") is not None else None,
                      policy.get("bandwidth") if policy.get("bandwidth") is not None else None, marker)
        report["operation"] = {"maintenance_windows": len(st.get(ops.KEY_WINDOWS) or []),
                               "bandwidth_default_mbps": (st.get(ops.KEY_BANDWIDTH) or {}).get("default_mbps")}
    except ValueError as e:
        report["errors"].append(f"Operação: {e}")

    im = policy.get("immutability")
    if im and int(im.get("days") or 0) > 0:
        repo_ids = {t["repository_id"] for t in tasks if t.get("repository_id")}
        for r in imm.overview():
            if repo_ids and r["id"] not in repo_ids:
                continue
            mode = "object_lock" if "object_lock" in r["supported_modes"] else ("local_worm" if "local_worm" in r["supported_modes"] else None)
            if not mode:
                report["immutability"].append({"repository": r["name"], "status": "não suportado"})
                continue
            try:
                imm.set_policy(r["id"], mode, int(im["days"]), str(im.get("lock_mode") or "COMPLIANCE").upper())
                if mode == "local_worm" or im.get("apply_bucket"):
                    res = imm.apply(r["id"])
                else:
                    res = imm.check(r["id"])
                report["immutability"].append({"repository": r["name"], "mode": mode, "protected": res.get("protected"),
                                               "summary": res.get("summary")})
            except Exception as e:
                report["immutability"].append({"repository": r["name"], "mode": mode, "protected": False, "summary": str(e)[:300]})
    logger.info(f"[POLÍTICA] '{policy.get('name')}' v{policy.get('version')} aplicada: {len(report['tasks'])} tarefa(s)")
    return report
