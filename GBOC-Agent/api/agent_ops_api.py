"""
GBOC Agent — Operações acionadas pelo GBOC Server (ou pela própria interface do agente):
  * teste de restauração com evidência  (POST /api/agent-ops/restore-test, GET /api/agent-ops/restore-tests)
  * atualização remota do agente          (GET /api/agent-ops/update/status, POST /api/agent-ops/update,
                                           POST /api/agent-ops/update/rollback)
  * pausar/retomar agendamentos em lote   (POST /api/agent-ops/schedules)
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("gboc_agent_ops")
router = APIRouter(prefix="/api/agent-ops", tags=["Operações remotas"])
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")


async def _body(request: Request) -> Dict[str, Any]:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


@router.post("/restore-test")
async def restore_test(request: Request):
    from engines.restore_test import run_restore_test
    b = await _body(request)
    if not b.get("repository_id") and not b.get("task_id"):
        raise HTTPException(400, "Informe repository_id ou task_id")
    try:
        res = await asyncio.to_thread(run_restore_test, b.get("repository_id"), b.get("task_id"),
                                      int(b.get("sample_size") or 5), int(b.get("max_file_mb") or 100),
                                      str(b.get("triggered_by") or "manual")[:60])
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Teste de restauração não executado: {e}")
    return {"status": "success", "test": res}


@router.get("/restore-tests")
async def restore_tests(limit: int = 50):
    from engines.restore_test import list_restore_tests
    return {"status": "success", "tests": await asyncio.to_thread(list_restore_tests, limit)}


@router.get("/update/status")
async def update_status():
    from core.agent_updater import status
    return {"status": "success", **(await asyncio.to_thread(status))}


@router.post("/update")
async def update_agent(request: Request):
    from core.agent_updater import download_and_apply
    b = await _body(request)
    sha = str(b.get("sha256") or "")
    if not _SHA_RE.match(sha):
        raise HTTPException(400, "sha256 do pacote inválido")
    try:
        res = await asyncio.to_thread(download_and_apply, sha, bool(b.get("restart", True)))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Atualização não aplicada: {e}")
    return {"status": "success", "update": res}


@router.post("/update/rollback")
async def update_rollback(request: Request):
    from core.agent_updater import rollback
    b = await _body(request)
    try:
        res = await asyncio.to_thread(rollback, b.get("backup"), bool(b.get("restart", True)))
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    return {"status": "success", "rollback": res}


_PAUSED_FILE = "paused_schedules.json"


def _paused_path() -> str:
    import os
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(os.path.join(base, "data"), exist_ok=True)
    return os.path.join(base, "data", _PAUSED_FILE)


def _set_schedules(enabled: bool, task_ids: Optional[list]) -> Dict[str, Any]:
    """Pausar guarda quais tarefas estavam agendadas; retomar reativa exatamente essas
    (ou as task_ids informadas). O agendador lê o banco a cada minuto."""
    import json
    import os
    from shared_core import get_shared_core
    core = get_shared_core()
    path = _paused_path()
    try:
        with open(path, encoding="utf-8") as f:
            paused = set(int(x) for x in json.load(f))
    except Exception:
        paused = set()
    ids = [int(t) for t in task_ids] if task_ids else None
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        if not enabled:
            if ids:
                cur.execute("""UPDATE tasks SET schedule_enabled = FALSE WHERE id = ANY(%s) AND schedule_enabled = TRUE
                               RETURNING id, name""", (ids,))
            else:
                cur.execute("""UPDATE tasks SET schedule_enabled = FALSE WHERE schedule_enabled = TRUE
                               AND schedule_cron IS NOT NULL AND schedule_cron <> '' RETURNING id, name""")
            rows = cur.fetchall()
            paused |= {r[0] for r in rows}
        else:
            target = ids or sorted(paused)
            rows = []
            if target:
                cur.execute("""UPDATE tasks SET schedule_enabled = TRUE WHERE id = ANY(%s)
                               AND schedule_cron IS NOT NULL AND schedule_cron <> '' RETURNING id, name""", (target,))
                rows = cur.fetchall()
            paused -= {r[0] for r in rows} | set(ids or [])
        conn.commit()
        cur.close()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(paused), f)
    return {"changed": len(rows), "tasks": [{"id": r[0], "name": r[1]} for r in rows], "paused_task_ids": sorted(paused)}


@router.post("/schedules")
async def set_schedules(request: Request):
    """{"enabled": false} pausa os agendamentos (todas as tarefas agendadas ou task_ids); true retoma."""
    b = await _body(request)
    if "enabled" not in b:
        raise HTTPException(400, "Informe enabled (true para retomar, false para pausar)")
    res = await asyncio.to_thread(_set_schedules, bool(b["enabled"]), b.get("task_ids"))
    return {"status": "success", **res}


# ───────────────────────── janela de manutenção e limite de banda ─────────────────────────

@router.get("/operation")
async def get_operation():
    from engines import operation_settings as ops
    return {"status": "success", **(await asyncio.to_thread(ops.status))}


@router.put("/operation")
async def put_operation(request: Request):
    """{"maintenance_windows": [...], "bandwidth": {...}, "central_policy": {...}|null} — campos ausentes não mudam."""
    from engines import operation_settings as ops
    b = await _body(request)
    try:
        await asyncio.to_thread(ops.save, b.get("maintenance_windows"), b.get("bandwidth"),
                                b["central_policy"] if "central_policy" in b else "__keep__")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "success", **(await asyncio.to_thread(ops.status))}


# ───────────────────────── detalhes do repositório ─────────────────────────

@router.get("/repositories/{repo_id}/details")
async def repository_details(repo_id: str, live: bool = False):
    """Todas as configurações do repositório (segredos nunca são devolvidos); live=true consulta o provedor agora."""
    from engines import repo_inspect
    try:
        return {"status": "success", **(await asyncio.to_thread(repo_inspect.details, repo_id, live))}
    except ValueError as e:
        raise HTTPException(404, str(e))


# ───────────────────────── backup imutável ─────────────────────────

@router.get("/immutability")
async def immutability_overview():
    from engines import immutability as imm
    return {"status": "success", "repositories": await asyncio.to_thread(imm.overview)}


@router.put("/repositories/{repo_id}/immutability")
async def immutability_set(repo_id: str, request: Request):
    from engines import immutability as imm
    b = await _body(request)
    try:
        pol = await asyncio.to_thread(imm.set_policy, repo_id, str(b.get("mode") or "off"), int(b.get("days") or 0),
                                      str(b.get("lock_mode") or "COMPLIANCE").upper())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "success", "policy": pol}


@router.post("/repositories/{repo_id}/immutability/check")
async def immutability_check(repo_id: str):
    from engines import immutability as imm
    try:
        return {"status": "success", "result": await asyncio.to_thread(imm.check, repo_id)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Verificação não concluída: {e}")


@router.post("/repositories/{repo_id}/immutability/apply")
async def immutability_apply(repo_id: str, request: Request):
    from engines import immutability as imm
    b = await _body(request)
    try:
        if b.get("create_bucket"):
            res = await asyncio.to_thread(lambda: imm.create_locked_bucket(imm._repo_row(repo_id)))
        else:
            res = await asyncio.to_thread(imm.apply, repo_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(502, f"Não foi possível aplicar: {e}")
    return {"status": "success", "result": res}


# ───────────────────────── política central ─────────────────────────

@router.post("/apply-policy")
async def apply_policy(request: Request):
    from engines import central_policy
    b = await _body(request)
    try:
        rep = await asyncio.to_thread(central_policy.apply, b.get("policy") or b)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "success", "report": rep}
