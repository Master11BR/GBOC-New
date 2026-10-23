#!/usr/bin/env python3
"""
GBOC 14.8.2 - Ransomware Detection API
Canaries, Guardian (resposta automática) e status do antivírus local.
Varredura/"7 ferramentas" e Shield removidos (out/2026): detecção de malware é papel do antivírus/EDR.
Rotas síncronas (def): o FastAPI as executa em threadpool, sem travar o event loop.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging
import json
from decimal import Decimal
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ransomware", tags=["Ransomware"])


class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        return super().default(o)


def _clean(obj):
    return json.loads(json.dumps(obj, cls=_Enc))


class CanaryRequest(BaseModel):
    file_path: str


@router.get("/status")
def protection_status():
    """Get overall ransomware protection status and integrated 7-tool stack."""
    from engines.ransomware_detector import get_protection_status
    return _clean(get_protection_status())


# ─── Canary endpoints ─────────────────────────────────────────────

@router.post("/canary")
def create_canary_file(body: CanaryRequest):
    """Create a canary/honeypot file for ransomware detection."""
    from engines.ransomware_detector import create_canary
    try:
        result = create_canary(body.file_path)
        return _clean(result)
    except Exception as e:
        raise HTTPException(500, f"Failed to create canary: {e}")


@router.get("/canary/verify")
def verify_canary_files():
    """Verify all registered canary files for tampering."""
    from engines.ransomware_detector import verify_canaries
    return _clean(verify_canaries())


@router.get("/canary/list")
def list_canaries():
    """List all registered canary files."""
    from engines.ransomware_detector import _query, ensure_tables
    ensure_tables()
    canaries = _query("SELECT id, file_path, original_hash, is_compromised, last_verified_at, created_at FROM ransomware_canaries ORDER BY created_at DESC")
    return {"canaries": _clean(canaries)}


@router.delete("/canary/{canary_id}")
def delete_canary(canary_id: int):
    """Remove a canary file registration."""
    from engines.ransomware_detector import _query, _execute
    existing = _query("SELECT file_path FROM ransomware_canaries WHERE id = %s", (canary_id,))
    if not existing:
        raise HTTPException(404, "Canary not found")
    _execute("DELETE FROM ransomware_canaries WHERE id = %s", (canary_id,))
    return {"deleted": True, "file_path": existing[0].get('file_path')}


# ─── Guardian (Auto-Response Watchdog) ────────────────────────────

class GuardianConfigRequest(BaseModel):
    check_interval_minutes: Optional[int] = None
    enabled: Optional[bool] = None


@router.get("/guardian/status")
def guardian_status():
    """Get Ransomware Guardian watchdog status and recent incidents."""
    from engines.ransomware_guardian import get_guardian
    guardian = get_guardian()
    return _clean(guardian.get_guardian_status())


@router.post("/guardian/start")
def guardian_start():
    """Start the Ransomware Guardian watchdog."""
    from engines.ransomware_guardian import get_guardian
    guardian = get_guardian()
    if guardian.is_alive():
        return {"status": "already_running"}
    guardian.enabled = True
    guardian.start()
    return {"status": "started", "check_interval_minutes": guardian.check_interval // 60}


@router.post("/guardian/stop")
def guardian_stop():
    """Stop the Ransomware Guardian watchdog."""
    from engines.ransomware_guardian import get_guardian
    guardian = get_guardian()
    if not guardian.is_alive():
        return {"status": "already_stopped"}
    guardian.stop()
    return {"status": "stopped"}


@router.put("/guardian/config")
def guardian_config(body: GuardianConfigRequest):
    """Update Guardian configuration (interval, enabled)."""
    from engines.ransomware_guardian import get_guardian
    guardian = get_guardian()
    changed = []

    if body.check_interval_minutes is not None:
        if body.check_interval_minutes < 1 or body.check_interval_minutes > 1440:
            raise HTTPException(400, "Interval must be between 1 and 1440 minutes")
        guardian.check_interval = body.check_interval_minutes * 60
        changed.append(f"interval={body.check_interval_minutes}min")

    if body.enabled is not None:
        guardian.enabled = body.enabled
        if body.enabled and not guardian.is_alive():
            guardian.start()
            changed.append("started")
        elif not body.enabled and guardian.is_alive():
            guardian.stop()
            changed.append("stopped")

    return {"status": "updated", "changes": changed, "running": guardian.is_alive()}


@router.get("/guardian/incidents")
def guardian_incidents(limit: int = 20):
    """List ransomware incidents detected by Guardian."""
    try:
        from engines.ransomware_detector import _query
        incidents = _query("""
            SELECT id, detected_at, status, threat_info, response_actions, resolved_at, resolved_by, notes
            FROM ransomware_incidents
            ORDER BY detected_at DESC LIMIT %s
        """, (limit,))
        return {"incidents": _clean(incidents)}
    except Exception:
        return {"incidents": []}


def _release_guardian_locks() -> dict:
    """
    Sem incidente ativo, devolve repositorios/tarefas travados pelo Guardian ao status anterior
    registrado na resposta do incidente (incidentes antigos nao registravam: volta para 'active').
    """
    from engines.ransomware_detector import _query, _execute
    active = _query("SELECT COUNT(*) AS n FROM ransomware_incidents WHERE status = 'active'")
    n_active = int((active[0] or {}).get("n", 0)) if active else 0
    if n_active:
        return {"restored_repositories": 0, "restored_tasks": 0,
                "note": f"{n_active} incidente(s) ainda ativo(s): repositórios e tarefas continuam bloqueados até o último ser resolvido."}
    prev_repo, prev_task = {}, {}
    for row in _query("SELECT response_actions FROM ransomware_incidents ORDER BY id ASC"):
        acts = row.get("response_actions") or []
        if isinstance(acts, str):
            try:
                acts = json.loads(acts)
            except ValueError:
                acts = []
        for a in acts if isinstance(acts, list) else []:
            res = (a or {}).get("result") or {}
            if a.get("action") == "repositories_locked":
                for r in res.get("repos") or []:
                    if r.get("previous_status") and r.get("previous_status") != "locked_ransomware":
                        prev_repo[r.get("id")] = r["previous_status"]
            elif a.get("action") == "backups_paused":
                for t in res.get("tasks") or []:
                    if t.get("previous_status") and t.get("previous_status") != "paused_ransomware":
                        prev_task[t.get("id")] = t["previous_status"]
    n_repo = n_task = 0
    for r in _query("SELECT id FROM repositories WHERE status = 'locked_ransomware'"):
        _execute("UPDATE repositories SET status = %s WHERE id = %s AND status = 'locked_ransomware'",
                 (prev_repo.get(r["id"], "active"), r["id"]))
        n_repo += 1
    for t in _query("SELECT id FROM tasks WHERE status = 'paused_ransomware'"):
        _execute("UPDATE tasks SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s AND status = 'paused_ransomware'",
                 (prev_task.get(t["id"], "active"), t["id"]))
        n_task += 1
    if n_repo or n_task:
        logger.info(f"[Guardian] Incidentes resolvidos: {n_repo} repositório(s) e {n_task} tarefa(s) desbloqueados")
    return {"restored_repositories": n_repo, "restored_tasks": n_task}


@router.put("/guardian/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: int):
    """Marca o incidente como resolvido; ao resolver o ultimo ativo, desfaz os bloqueios do Guardian."""
    from engines.ransomware_detector import _query, _execute
    existing = _query("SELECT id FROM ransomware_incidents WHERE id = %s", (incident_id,))
    if not existing:
        raise HTTPException(404, "Incident not found")
    _execute("""
        UPDATE ransomware_incidents
        SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (incident_id,))
    return {"resolved": True, "incident_id": incident_id, **_release_guardian_locks()}


@router.put("/guardian/incidents/resolve-active")
def resolve_all_active_incidents():
    """Resolve todos os incidentes ativos (ex.: alarmes falsos repetidos) e desfaz os bloqueios do Guardian."""
    from engines.ransomware_detector import _query, _execute
    rows = _query("SELECT COUNT(*) AS n FROM ransomware_incidents WHERE status = 'active'")
    n = int((rows[0] or {}).get("n", 0)) if rows else 0
    _execute("UPDATE ransomware_incidents SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP WHERE status = 'active'")
    return {"resolved": n, **_release_guardian_locks()}


@router.post("/guardian/test")
def guardian_test_response():
    """Simulate a threat detection to test the Guardian auto-response chain.
    This does NOT create real locks or snapshots - just tests notifications."""
    from engines.ransomware_guardian import get_guardian
    guardian = get_guardian()
    test_threat = {
        'threat_detected': True,
        'compromised': 0,
        'missing': 0,
        'total': 0,
        'details': [],
        'detected_at': datetime.now().isoformat(),
        'test_mode': True
    }
    # Only test notifications, not destructive actions
    notify_result = guardian._notify_all_channels(test_threat)
    return _clean({
        "test": True,
        "notifications": notify_result,
        "message": "Test notification sent to all configured channels"
    })


@router.get("/guardian/ai_diagnostic")
async def guardian_ai_diagnostic(include_llm: bool = True):
    """Diagnóstico IA híbrido do Guardian: heurística local + LLM opcional."""
    from engines.ransomware_guardian import get_guardian
    from engines.ransomware_detector import get_local_protection_status

    guardian = get_guardian()
    g = _clean(guardian.get_guardian_status() or {})
    incidents = g.get("recent_incidents") or []
    running = bool(g.get("running"))
    canary_count = int(g.get("canary_count") or 0)
    local = _clean(get_local_protection_status() or {})

    score = 0
    if not running:
        score += 30
    if canary_count <= 0:
        score += 30
    if not local.get("av_installed"):
        score += 25
    elif not local.get("av_active"):
        score += 15
    score += min(len(incidents) * 10, 30)
    score = max(0, min(score, 100))

    if score <= 20:
        status = "PROTECTED"
    elif score <= 50:
        status = "WARNING"
    else:
        status = "CRITICAL"

    rec = []
    if not running:
        rec.append("Ativar Guardian imediatamente")
    if canary_count <= 0:
        rec.append("Criar canary files em caminhos críticos")
    if not local.get("av_installed"):
        rec.append("Instalar AV/EDR no host")
    elif not local.get("av_active"):
        rec.append("Ativar proteção em tempo real do AV/EDR")
    if incidents:
        rec.append("Investigar incidentes recentes e validar integridade dos repositórios")
    if not rec:
        rec.append("Manter monitoramento contínuo e sincronização com servidor")

    heuristic = {
        "status": status,
        "threat_score": score,
        "recommendation": "; ".join(rec),
        "guardian_running": running,
        "canaries_total": canary_count,
        "recent_incidents": len(incidents),
        "av_installed": bool(local.get("av_installed")),
        "av_active": bool(local.get("av_active")),
        "timestamp": datetime.now().isoformat(),
    }

    llm_analysis = None
    if include_llm:
        try:
            from engines.ai_diagnostic_engine import ai_diagnostic_engine

            ctx = (
                f"Guardian status: running={running}, canaries={canary_count}, "
                f"recent_incidents={len(incidents)}, av_installed={local.get('av_installed')}, "
                f"av_active={local.get('av_active')}, heuristic_score={score}."
            )
            llm_res = await ai_diagnostic_engine.analyze_error(ctx)
            if isinstance(llm_res, dict):
                llm_analysis = {
                    "cause": llm_res.get("cause"),
                    "solution": llm_res.get("solution"),
                    "recommended_action": llm_res.get("recommended_action"),
                    "analysis": llm_res.get("analysis"),
                    "is_llm_real": bool(llm_res.get("is_llm_real")),
                    "provider": llm_res.get("provider"),
                    "llm_error": llm_res.get("llm_error"),
                }
        except Exception as e:
            llm_analysis = {"error": str(e)}

    return _clean({
        "status": status,
        "threat_score": score,
        "recommendation": heuristic["recommendation"],
        "mode": "hybrid" if include_llm else "heuristic",
        "heuristic": heuristic,
        "llm": llm_analysis,
    })


@router.get("/local_protection")
def local_protection_status():
    """Get local antivirus and event log protection status."""
    from engines.ransomware_detector import get_local_protection_status
    return _clean(get_local_protection_status())
