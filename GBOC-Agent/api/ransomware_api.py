#!/usr/bin/env python3
"""
GBOC 14.0.0 - Ransomware Detection API
Endpoints for scanning, canary management, and threat status.
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


class ScanRequest(BaseModel):
    target_path: str


class CanaryRequest(BaseModel):
    file_path: str


# ─── Scan endpoints ───────────────────────────────────────────────

@router.post("/scan")
async def trigger_scan(body: ScanRequest):
    """Run a full ransomware detection scan on a directory."""
    import os
    if not os.path.isdir(body.target_path):
        raise HTTPException(400, f"Path not found or not a directory: {body.target_path}")
    from engines.ransomware_detector import run_full_scan
    result = run_full_scan(body.target_path)
    return _clean(result)


@router.get("/scan/history")
async def scan_history(limit: int = 20):
    """Get recent ransomware scan history."""
    from engines.ransomware_detector import get_scan_history
    return {"scans": _clean(get_scan_history(limit))}


@router.get("/status")
async def protection_status():
    """Get overall ransomware protection status and integrated 7-tool stack."""
    from engines.ransomware_detector import get_protection_status
    return _clean(get_protection_status())


@router.get("/tools")
async def integrated_tools_status():
    """Get status and availability of the 7 integrated open-source security tools."""
    from engines.ransomware_detector import get_integrated_tools_status
    return {"status": "success", "tools": _clean(get_integrated_tools_status())}


@router.post("/tools/scan/{tool_id}")
async def run_tool_scan(tool_id: str, body: ScanRequest):
    """Run dedicated scan with one of the 7 tools or multi-tool integrated stack."""
    import os
    if not os.path.isdir(body.target_path):
        raise HTTPException(400, f"Caminho não encontrado ou inválido: {body.target_path}")

    from engines.ransomware_detector import (
        scan_with_clamav, scan_with_armadito, scan_with_clamwin_clamtk,
        scan_with_hypatia, scan_with_wazuh_hids, scan_with_yara, scan_with_rkhunter,
        run_integrated_multi_tool_scan
    )

    t = tool_id.lower().strip()
    if t == "clamav":
        return _clean(scan_with_clamav(body.target_path))
    elif t == "armadito":
        return _clean(scan_with_armadito(body.target_path))
    elif t in ("clamwin", "clamtk", "clamwin_clamtk"):
        return _clean(scan_with_clamwin_clamtk(body.target_path))
    elif t == "hypatia":
        return _clean(scan_with_hypatia(body.target_path))
    elif t in ("wazuh", "ossec", "wazuh_hids"):
        return _clean(scan_with_wazuh_hids())
    elif t == "yara":
        return _clean(scan_with_yara(body.target_path))
    elif t == "rkhunter":
        return _clean(scan_with_rkhunter())
    else:
        # Executa todas as 7 ferramentas de forma integrada
        return _clean(run_integrated_multi_tool_scan(body.target_path))


# ─── Canary endpoints ─────────────────────────────────────────────

@router.post("/canary")
async def create_canary_file(body: CanaryRequest):
    """Create a canary/honeypot file for ransomware detection."""
    from engines.ransomware_detector import create_canary
    try:
        result = create_canary(body.file_path)
        return _clean(result)
    except Exception as e:
        raise HTTPException(500, f"Failed to create canary: {e}")


@router.get("/canary/verify")
async def verify_canary_files():
    """Verify all registered canary files for tampering."""
    from engines.ransomware_detector import verify_canaries
    return _clean(verify_canaries())


@router.get("/canary/list")
async def list_canaries():
    """List all registered canary files."""
    from engines.ransomware_detector import _query, ensure_tables
    ensure_tables()
    canaries = _query("SELECT id, file_path, original_hash, is_compromised, last_verified_at, created_at FROM ransomware_canaries ORDER BY created_at DESC")
    return {"canaries": _clean(canaries)}


@router.delete("/canary/{canary_id}")
async def delete_canary(canary_id: int):
    """Remove a canary file registration."""
    from engines.ransomware_detector import _query, _execute
    existing = _query("SELECT file_path FROM ransomware_canaries WHERE id = %s", (canary_id,))
    if not existing:
        raise HTTPException(404, "Canary not found")
    _execute("DELETE FROM ransomware_canaries WHERE id = %s", (canary_id,))
    return {"deleted": True, "file_path": existing[0].get('file_path')}


# ─── Quick entropy check ──────────────────────────────────────────

@router.post("/entropy")
async def check_entropy(body: ScanRequest):
    """Quick entropy analysis of a directory (no DB record)."""
    import os
    if not os.path.isdir(body.target_path):
        raise HTTPException(400, f"Path not found: {body.target_path}")
    from engines.ransomware_detector import calculate_directory_entropy
    result = calculate_directory_entropy(body.target_path)
    return _clean(result)


# ─── Guardian (Auto-Response Watchdog) ────────────────────────────

class GuardianConfigRequest(BaseModel):
    check_interval_minutes: Optional[int] = None
    enabled: Optional[bool] = None


@router.get("/guardian/status")
async def guardian_status():
    """Get Ransomware Guardian watchdog status and recent incidents."""
    from engines.ransomware_guardian import get_guardian
    guardian = get_guardian()
    return _clean(guardian.get_guardian_status())


@router.post("/guardian/start")
async def guardian_start():
    """Start the Ransomware Guardian watchdog."""
    from engines.ransomware_guardian import get_guardian
    guardian = get_guardian()
    if guardian.is_alive():
        return {"status": "already_running"}
    guardian.enabled = True
    guardian.start()
    return {"status": "started", "check_interval_minutes": guardian.check_interval // 60}


@router.post("/guardian/stop")
async def guardian_stop():
    """Stop the Ransomware Guardian watchdog."""
    from engines.ransomware_guardian import get_guardian
    guardian = get_guardian()
    if not guardian.is_alive():
        return {"status": "already_stopped"}
    guardian.stop()
    return {"status": "stopped"}


@router.put("/guardian/config")
async def guardian_config(body: GuardianConfigRequest):
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
async def guardian_incidents(limit: int = 20):
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


@router.put("/guardian/incidents/{incident_id}/resolve")
async def resolve_incident(incident_id: int):
    """Mark a ransomware incident as resolved."""
    from engines.ransomware_detector import _query, _execute
    existing = _query("SELECT id FROM ransomware_incidents WHERE id = %s", (incident_id,))
    if not existing:
        raise HTTPException(404, "Incident not found")
    _execute("""
        UPDATE ransomware_incidents
        SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (incident_id,))
    return {"resolved": True, "incident_id": incident_id}


@router.post("/guardian/test")
async def guardian_test_response():
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


# ─── Shield (Real-time Prevention) ───────────────────────────────

class ShieldConfigRequest(BaseModel):
    monitored_paths: Optional[list] = None
    burst_threshold: Optional[int] = None
    burst_window_seconds: Optional[int] = None
    auto_kill_process: Optional[bool] = None
    auto_isolate_network: Optional[bool] = None
    entropy_threshold: Optional[float] = None
    vss_guard_enabled: Optional[bool] = None
    simulation_mode: Optional[bool] = None


class ShieldPathRequest(BaseModel):
    path: str


@router.get("/shield/status")
async def shield_status():
    """Get real-time protection status."""
    from engines.ransomware_shield import get_shield
    shield = get_shield()
    metrics = shield.get_metrics()
    return _clean({
        "running": shield.running,
        "metrics": metrics.__dict__ if hasattr(metrics, '__dict__') else {},
        "config": dict(shield.config._config),
        "recent_threats": shield.get_recent_threats(10),
        "components": {
            "watchdog_available": shield.observer is not None,
            "vss_guard_alive": shield.vss_guard.is_alive() if shield.vss_guard else False,
            "entropy_worker_alive": shield.entropy_thread.is_alive() if shield.entropy_thread else False,
        }
    })


@router.post("/shield/start")
async def shield_start():
    """Start real-time ransomware prevention."""
    from engines.ransomware_shield import get_shield
    shield = get_shield()
    if shield.running:
        return {"status": "already_running"}
    metrics = shield.start()
    return _clean({
        "status": "started",
        "metrics": metrics.__dict__ if hasattr(metrics, '__dict__') else {},
    })


@router.post("/shield/stop")
async def shield_stop():
    """Stop real-time ransomware prevention."""
    from engines.ransomware_shield import get_shield
    shield = get_shield()
    if not shield.running:
        return {"status": "already_stopped"}
    shield.stop()
    return {"status": "stopped"}


@router.put("/shield/config")
async def shield_config(body: ShieldConfigRequest):
    """Update Shield configuration."""
    from engines.ransomware_shield import get_shield
    shield = get_shield()
    updates = {k: v for k, v in body.dict().items() if v is not None}
    shield.config.update(updates)
    return _clean({"status": "updated", "changes": list(updates.keys())})


@router.post("/shield/path/add")
async def shield_add_path(body: ShieldPathRequest):
    """Add a directory to real-time monitoring."""
    from engines.ransomware_shield import get_shield
    shield = get_shield()
    success = shield.add_monitored_path(body.path)
    if not success:
        raise HTTPException(400, f"Falha ao adicionar path: {body.path} (não existe ou watchdog indisponível)")
    return {"status": "added", "path": body.path}


@router.get("/shield/threats")
async def shield_threats(limit: int = 50):
    """Get recent threats detected by shield."""
    from engines.ransomware_shield import get_shield
    shield = get_shield()
    return {"threats": _clean(shield.get_recent_threats(limit))}


@router.get("/local_protection")
async def local_protection_status():
    """Get local antivirus and event log protection status."""
    from engines.ransomware_detector import get_local_protection_status
    return _clean(get_local_protection_status())
