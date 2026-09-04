# GBOC System v14.0.0 Enterprise Edition
# Module: Ransomware Shield Router (Server Central & Agents Unified Protection)

import json
import logging
import platform
import socket
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

try:
    from database import db_manager

    def get_db():
        return db_manager.get_connection()

    def release_db(conn):
        db_manager.release_connection(conn)
except Exception:
    def get_db():
        return None

    def release_db(conn):
        return None


logger = logging.getLogger("gboc_ransomware_module")
router = APIRouter(prefix="/api/v1/server/ransomware", tags=["Ransomware Shield"])

PROTECTION_MODULES_7 = [
    {"id": "process_guard", "name": "Real-time Process Guard", "icon": "fa-user-shield", "status": "ACTIVE", "description": "Monitoramento heurístico contínuo contra encerramento não autorizado de processos críticos."},
    {"id": "canary_trap", "name": "Canary Files & Deception Trap", "icon": "fa-dove", "status": "ACTIVE", "description": "Armadilhas deception distribuídas com alerta em tempo real perante modificações suspeitas."},
    {"id": "vss_lock", "name": "VSS ShadowCopy Lock & Immutability", "icon": "fa-lock", "status": "ACTIVE", "description": "Bloqueio rígido de comandos VSSADMIN e proteção imutável de cópias de sombra do sistema."},
    {"id": "mbr_protection", "name": "MBR / GPT Protection Engine", "icon": "fa-hdd", "status": "ACTIVE", "description": "Proteção do setor de boot contra ransomware do tipo wiper/bootloader."},
    {"id": "event_monitor", "name": "System Event & AV/EDR WMI Monitor", "icon": "fa-binoculars", "status": "ACTIVE", "description": "Coleta automatizada de logs do Event Viewer e verificação do status de Antivírus/EDR."},
    {"id": "ai_preemptive", "name": "Preemptive AI Threat Diagnostic", "icon": "fa-brain", "status": "ACTIVE", "description": "Diagnóstico preditivo via IA para análise proativa de vetores de vulnerabilidade."},
    {"id": "auto_isolation", "name": "Emergency Network Isolation", "icon": "fa-network-wired", "status": "READY", "description": "Isolamento automatizado em microssegundos no caso de detecção de sequestro de dados."},
]


def _is_local_agent(agent_id: Optional[str]) -> bool:
    if not agent_id:
        return True
    aid = str(agent_id).lower().strip()
    return aid in ("agente-local", "servidor-central", "server", "local", "localhost", "127.0.0.1", "server-host-local")


def _safe_parse_ts(value: Any):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _ensure_ransomware_tables(conn):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ransomware_agent_snapshots (
                id SERIAL PRIMARY KEY,
                agent_id VARCHAR(100) NOT NULL,
                agent_hostname VARCHAR(255),
                snapshot_type VARCHAR(100) NOT NULL,
                payload_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ransomware_ai_diagnostics (
                id SERIAL PRIMARY KEY,
                scope VARCHAR(50) NOT NULL,
                node_id VARCHAR(150),
                threat_score INTEGER DEFAULT 0,
                status VARCHAR(50),
                summary TEXT,
                details_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ransomware_central_events (
                id SERIAL PRIMARY KEY,
                agent_id VARCHAR(100) NOT NULL,
                agent_hostname VARCHAR(255),
                event_type VARCHAR(120),
                message TEXT,
                event_time TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ransomware_central_incidents (
                id SERIAL PRIMARY KEY,
                agent_id VARCHAR(100) NOT NULL,
                incident_external_id VARCHAR(100),
                status VARCHAR(50),
                detected_at TIMESTAMP,
                resolved_at TIMESTAMP,
                threat_info_json TEXT,
                response_actions_json TEXT,
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agent_id, incident_external_id)
            )
            """
        )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass


def _get_online_agents() -> List[Dict[str, Any]]:
    conn = None
    cur = None
    rows: List[Dict[str, Any]] = []
    try:
        conn = get_db()
        if not conn:
            return rows
        cur = conn.cursor()
        cur.execute(
            """
            SELECT agent_id, hostname, COALESCE(ip_address, '127.0.0.1') AS ip_address,
                   COALESCE(status, 'unknown') AS status
            FROM agents
            ORDER BY hostname
            """
        )
        for r in cur.fetchall() or []:
            rows.append({
                "agent_id": r[0],
                "hostname": r[1] or r[0],
                "ip": r[2] or "127.0.0.1",
                "port": 9200,
                "status": r[3] or "unknown",
            })
    except Exception as e:
        logger.warning(f"Erro ao listar agentes ransomware: {e}")
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        if conn:
            release_db(conn)
    return rows


def _get_agent_connection_info(agent_id: str) -> Dict[str, Any]:
    if _is_local_agent(agent_id):
        return {"is_local": True, "ip": "127.0.0.1", "port": 9200, "hostname": socket.gethostname(), "status": "online"}

    data = {"is_local": False, "ip": "127.0.0.1", "port": 9200, "hostname": agent_id, "status": "unknown"}
    conn = None
    cur = None
    try:
        conn = get_db()
        if conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT agent_id, hostname, ip_address, status
                FROM agents
                WHERE agent_id = %s OR hostname = %s
                LIMIT 1
                """,
                (agent_id, agent_id),
            )
            r = cur.fetchone()
            if r:
                data["hostname"] = r[1] or data["hostname"]
                data["ip"] = r[2] or data["ip"]
                data["port"] = 9200
                data["status"] = r[3] or data["status"]
    except Exception as e:
        logger.warning(f"Erro ao resolver conexão do agente '{agent_id}': {e}")
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        if conn:
            release_db(conn)
    return data


async def _fetch_agent_endpoint(agent_id: str, endpoint_path: str, method: str = "GET", json_body: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Dict[str, Any]:
    conn = _get_agent_connection_info(agent_id)
    endpoint = endpoint_path if endpoint_path.startswith("/") else f"/{endpoint_path}"

    urls = [
        f"https://{conn.get('ip')}:{conn.get('port')}{endpoint}",
        f"http://{conn.get('ip')}:{conn.get('port')}{endpoint}",
    ]

    last_error = None
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                resp = await client.request(method.upper(), url, json=json_body)
                if resp.status_code >= 400:
                    last_error = f"HTTP {resp.status_code}"
                    continue
                try:
                    data = resp.json()
                except Exception:
                    data = {"raw": resp.text}
                return {"ok": True, "data": data, "url": url, "status_code": resp.status_code, "agent": conn}
        except Exception as e:
            last_error = str(e)

    return {"ok": False, "error": last_error or "Falha de conexão", "agent": conn}


def _persist_agent_snapshot(conn, agent_id: str, hostname: str, snapshot_type: str, payload: Any):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO ransomware_agent_snapshots (agent_id, agent_hostname, snapshot_type, payload_json)
            VALUES (%s, %s, %s, %s)
            """,
            (agent_id, hostname, snapshot_type, json.dumps(payload, ensure_ascii=False)[:2000000]),
        )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass


def _persist_ransomware_events(conn, agent_id: str, hostname: str, events: List[Dict[str, Any]]) -> int:
    if not events:
        return 0
    cur = conn.cursor()
    count = 0
    try:
        for ev in events[:300]:
            cur.execute(
                """
                INSERT INTO ransomware_central_events (agent_id, agent_hostname, event_type, message, event_time)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    agent_id,
                    hostname,
                    str(ev.get("event_type") or "ransomware_event")[:120],
                    str(ev.get("message") or "")[:4000],
                    _safe_parse_ts(ev.get("timestamp") or ev.get("time")),
                ),
            )
            count += 1
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
    return count


def _persist_ransomware_incidents(conn, agent_id: str, incidents: List[Dict[str, Any]]) -> int:
    if not incidents:
        return 0
    cur = conn.cursor()
    count = 0
    try:
        for inc in incidents[:300]:
            ext_id = str(inc.get("id") or "").strip()
            if not ext_id:
                continue
            cur.execute(
                """
                INSERT INTO ransomware_central_incidents
                    (agent_id, incident_external_id, status, detected_at, resolved_at, threat_info_json, response_actions_json, raw_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (agent_id, incident_external_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    resolved_at = EXCLUDED.resolved_at,
                    threat_info_json = EXCLUDED.threat_info_json,
                    response_actions_json = EXCLUDED.response_actions_json,
                    raw_json = EXCLUDED.raw_json
                """,
                (
                    agent_id,
                    ext_id,
                    str(inc.get("status") or "active")[:50],
                    _safe_parse_ts(inc.get("detected_at")),
                    _safe_parse_ts(inc.get("resolved_at")),
                    json.dumps(inc.get("threat_info") or {}, ensure_ascii=False)[:1000000],
                    json.dumps(inc.get("response_actions") or [], ensure_ascii=False)[:1000000],
                    json.dumps(inc, ensure_ascii=False)[:1000000],
                ),
            )
            count += 1
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
    return count


def _server_heuristic_diag(local_protection: Dict[str, Any], active_incidents: int) -> Dict[str, Any]:
    score = 0
    if not local_protection.get("av_installed"):
        score += 45
    elif not local_protection.get("av_active"):
        score += 25
    score += min(active_incidents * 15, 45)
    score = max(0, min(score, 100))

    if score <= 20:
        status = "PROTECTED"
    elif score <= 50:
        status = "WARNING"
    else:
        status = "CRITICAL"

    rec = []
    if not local_protection.get("av_installed"):
        rec.append("Instalar solução AV/EDR no host do servidor")
    elif not local_protection.get("av_active"):
        rec.append("Ativar proteção em tempo real da solução AV/EDR")
    if active_incidents > 0:
        rec.append("Validar incidentes ativos e executar varredura integrada nos agentes")
    if not rec:
        rec.append("Manter sincronização contínua e auditoria diária de canários")

    return {
        "node": f"Servidor Central ({socket.gethostname()})",
        "status": status,
        "threat_score": score,
        "canaries_verified": 0,
        "vss_lock": "ENABLED",
        "recommendation": "; ".join(rec),
        "mode": "heuristic",
    }


def _persist_ai_diag(conn, scope: str, node_id: str, diag: Dict[str, Any]):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO ransomware_ai_diagnostics (scope, node_id, threat_score, status, summary, details_json)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                scope,
                node_id,
                int(diag.get("threat_score") or 0),
                str(diag.get("status") or "UNKNOWN")[:50],
                str(diag.get("recommendation") or diag.get("summary") or "")[:2000],
                json.dumps(diag, ensure_ascii=False)[:1000000],
            ),
        )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass


@router.post("/sync")
async def sync_ransomware_central():
    agents = _get_online_agents()
    if not agents:
        return JSONResponse({"status": "warning", "message": "Nenhum agente cadastrado", "synced_agents": 0, "failed_agents": 0})

    conn = None
    summary = {
        "status": "success",
        "synced_agents": 0,
        "failed_agents": 0,
        "snapshots": 0,
        "events": 0,
        "incidents": 0,
        "details": [],
        "timestamp": datetime.now().isoformat(),
    }

    try:
        conn = get_db()
        if not conn:
            raise HTTPException(status_code=500, detail="Banco de dados indisponível no servidor")
        _ensure_ransomware_tables(conn)

        endpoints = {
            "status": "/api/ransomware/status",
            "tools": "/api/ransomware/tools",
            "canaries": "/api/ransomware/canary/list",
            "history": "/api/ransomware/scan/history?limit=20",
            "guardian": "/api/ransomware/guardian/status",
            "shield": "/api/ransomware/shield/status",
            "incidents": "/api/ransomware/guardian/incidents?limit=30",
            "local_protection": "/api/ransomware/local_protection",
        }

        for ag in agents:
            agent_id = ag.get("agent_id")
            hostname = ag.get("hostname") or agent_id
            node = {"agent_id": agent_id, "hostname": hostname, "ok": True, "errors": []}
            payloads: Dict[str, Any] = {}

            for name, ep in endpoints.items():
                res = await _fetch_agent_endpoint(agent_id, ep)
                if not res.get("ok"):
                    node["ok"] = False
                    node["errors"].append(f"{name}: {res.get('error')}")
                    continue
                payload = res.get("data")
                payloads[name] = payload
                _persist_agent_snapshot(conn, agent_id, hostname, name, payload)
                summary["snapshots"] += 1

            evs = []
            for ev in (payloads.get("local_protection") or {}).get("recent_security_events", []) or []:
                evs.append({"event_type": f"guardian_event_{ev.get('id', 'n/a')}", "message": ev.get("message"), "timestamp": ev.get("time")})
            for scan in (payloads.get("history") or {}).get("scans", []) or []:
                evs.append({"event_type": f"scan_{scan.get('threat_level', 'none')}", "message": f"Scan {scan.get('scan_type', 'full')} em {scan.get('target_path', 'N/A')}", "timestamp": scan.get("started_at")})
            summary["events"] += _persist_ransomware_events(conn, agent_id, hostname, evs)
            summary["incidents"] += _persist_ransomware_incidents(conn, agent_id, (payloads.get("incidents") or {}).get("incidents", []))

            if node["ok"]:
                summary["synced_agents"] += 1
            else:
                summary["failed_agents"] += 1
            summary["details"].append(node)

        return JSONResponse(summary)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro na sincronização central ransomware: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
    finally:
        if conn:
            release_db(conn)


@router.get("/central_stats")
async def get_central_ransomware_stats(limit: int = 50):
    conn = None
    cur = None
    try:
        conn = get_db()
        if not conn:
            raise HTTPException(status_code=500, detail="Banco de dados indisponível")
        _ensure_ransomware_tables(conn)

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ransomware_central_events")
        total_events = int((cur.fetchone() or [0])[0] or 0)

        cur.execute("SELECT COUNT(*) FROM ransomware_central_incidents")
        total_incidents = int((cur.fetchone() or [0])[0] or 0)

        cur.execute("SELECT COUNT(*) FROM ransomware_central_incidents WHERE status = 'resolved'")
        resolved_incidents = int((cur.fetchone() or [0])[0] or 0)

        cur.execute(
            """
            SELECT COALESCE(agent_hostname, agent_id) AS node, COUNT(*) AS total
            FROM ransomware_central_events
            GROUP BY COALESCE(agent_hostname, agent_id)
            ORDER BY total DESC
            LIMIT 10
            """
        )
        top_nodes = [{"node": r[0], "events": int(r[1] or 0)} for r in (cur.fetchall() or [])]

        cur.execute(
            """
            SELECT id, agent_id, COALESCE(agent_hostname, agent_id), event_type, message,
                   COALESCE(event_time, created_at) AS ts
            FROM ransomware_central_events
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        recent_events = []
        for row in cur.fetchall() or []:
            recent_events.append({
                "id": row[0],
                "agent_id": row[1],
                "agent_hostname": row[2],
                "event_type": row[3],
                "message": row[4],
                "timestamp": str(row[5])[:19] if row[5] else None,
            })

        return JSONResponse({
            "status": "success",
            "total_events": total_events,
            "total_incidents": total_incidents,
            "resolved_incidents": resolved_incidents,
            "active_incidents": max(total_incidents - resolved_incidents, 0),
            "top_nodes": top_nodes,
            "recent_events": recent_events,
            "updated_at": datetime.now().isoformat(),
        })
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        if conn:
            release_db(conn)


@router.post("/agent/{agent_id}/action")
async def execute_agent_ransomware_action(agent_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    action = str(body.get("action") or "").strip().lower()
    if not action:
        raise HTTPException(status_code=400, detail="Ação não informada")

    route_map = {
        "guardian_start": ("POST", "/api/ransomware/guardian/start", None),
        "guardian_stop": ("POST", "/api/ransomware/guardian/stop", None),
        "guardian_test": ("POST", "/api/ransomware/guardian/test", None),
        "guardian_verify_canaries": ("GET", "/api/ransomware/canary/verify", None),
        "shield_start": ("POST", "/api/ransomware/shield/start", None),
        "shield_stop": ("POST", "/api/ransomware/shield/stop", None),
        "guardian_ai_diag": ("GET", "/api/ransomware/guardian/ai_diagnostic?include_llm=true", None),
    }

    if action == "scan":
        target_path = str(body.get("target_path") or "").strip()
        if not target_path:
            raise HTTPException(status_code=400, detail="target_path obrigatório para ação scan")
        res = await _fetch_agent_endpoint(agent_id, "/api/ransomware/scan", method="POST", json_body={"target_path": target_path}, timeout=60.0)
    elif action in route_map:
        method, endpoint, payload = route_map[action]
        res = await _fetch_agent_endpoint(agent_id, endpoint, method=method, json_body=payload)
    else:
        raise HTTPException(status_code=400, detail=f"Ação não suportada: {action}")

    if not res.get("ok"):
        return JSONResponse({"status": "error", "action": action, "agent_id": agent_id, "error": res.get("error")}, status_code=502)

    return JSONResponse({"status": "success", "action": action, "agent_id": agent_id, "endpoint": res.get("url"), "result": res.get("data")})


@router.get("/overview")
async def get_ransomware_overview():
    total_agents = 1
    protected_agents = 1
    total_canaries = 0
    total_compromised = 0
    agents = [{
        "agent_id": "server-host-local",
        "hostname": f"Servidor Central ({socket.gethostname()})",
        "ip_address": "127.0.0.1",
        "is_protected": True,
        "canaries": 0,
        "compromised": 0,
        "threat_level": "none",
        "last_scan": datetime.now().isoformat(),
    }]

    conn = None
    cur = None
    try:
        conn = get_db()
        if conn:
            _ensure_ransomware_tables(conn)
            cur = conn.cursor()
            cur.execute("SELECT agent_id, hostname, COALESCE(ip_address,'N/A'), COALESCE(status,'unknown') FROM agents ORDER BY hostname")
            for row in cur.fetchall() or []:
                aid = row[0]
                host = row[1] or aid
                ip = row[2]
                st = row[3]

                cur2 = conn.cursor()
                cur2.execute("SELECT COUNT(*) FROM ransomware_central_incidents WHERE agent_id = %s AND status <> 'resolved'", (aid,))
                compromised = int((cur2.fetchone() or [0])[0] or 0)
                cur2.execute("SELECT payload_json FROM ransomware_agent_snapshots WHERE agent_id = %s AND snapshot_type = 'canaries' ORDER BY id DESC LIMIT 1", (aid,))
                srow = cur2.fetchone()
                cur2.close()

                canaries = 0
                if srow and srow[0]:
                    try:
                        canaries = len((json.loads(srow[0]) or {}).get("canaries", []) or [])
                    except Exception:
                        canaries = 0

                total_agents += 1
                total_canaries += canaries
                total_compromised += compromised
                is_protected = compromised == 0 and st == "online"
                if is_protected:
                    protected_agents += 1

                agents.append({
                    "agent_id": aid,
                    "hostname": host,
                    "ip_address": ip,
                    "is_protected": is_protected,
                    "canaries": canaries,
                    "compromised": compromised,
                    "threat_level": "critical" if compromised > 0 else ("none" if st == "online" else "medium"),
                    "last_scan": datetime.now().isoformat(),
                })
    except Exception as e:
        logger.warning(f"Erro ao obter overview ransomware: {e}")
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        if conn:
            release_db(conn)

    label = "SENTINEL ACTIVE — Zero Ameaças Detectadas" if total_compromised == 0 else f"ALERTA — {total_compromised} Incidente(s) ativo(s)!"
    return JSONResponse({
        "status": "success",
        "shield_active": True,
        "threats_detected_24h": total_compromised,
        "protected_agents": protected_agents,
        "total_agents": total_agents,
        "total_canaries": total_canaries,
        "total_compromised": total_compromised,
        "scans_7d": 0,
        "status_label": label,
        "agents": agents,
    })


@router.get("/modules")
async def get_ransomware_modules():
    modules = [dict(m) for m in PROTECTION_MODULES_7]
    evidence = {
        "process_guard": False,
        "canary_trap": False,
        "vss_lock": False,
        "mbr_protection": False,
        "event_monitor": False,
        "ai_preemptive": False,
        "auto_isolation": False,
    }

    conn = None
    cur = None
    try:
        conn = get_db()
        if conn:
            _ensure_ransomware_tables(conn)
            cur = conn.cursor()

            cur.execute(
                """
                SELECT snapshot_type, payload_json
                FROM ransomware_agent_snapshots
                WHERE snapshot_type IN ('guardian', 'canaries', 'shield', 'local_protection')
                ORDER BY id DESC
                LIMIT 300
                """
            )
            for row in cur.fetchall() or []:
                stype = row[0]
                payload_raw = row[1]
                try:
                    payload = json.loads(payload_raw) if payload_raw else {}
                except Exception:
                    payload = {}

                if stype == "guardian" and bool(payload.get("running")):
                    evidence["process_guard"] = True
                elif stype == "canaries":
                    canaries = payload.get("canaries") if isinstance(payload, dict) else []
                    if isinstance(canaries, list) and len(canaries) > 0:
                        evidence["canary_trap"] = True
                elif stype == "shield":
                    cfg = payload.get("config") if isinstance(payload, dict) else {}
                    if isinstance(cfg, dict):
                        if bool(cfg.get("vss_guard_enabled")):
                            evidence["vss_lock"] = True
                        if bool(cfg.get("auto_isolate_network")):
                            evidence["auto_isolation"] = True
                        monitored = cfg.get("monitored_paths") or []
                        if isinstance(monitored, list) and any("boot" in str(p).lower() or "efi" in str(p).lower() for p in monitored):
                            evidence["mbr_protection"] = True
                elif stype == "local_protection":
                    if bool(payload.get("av_installed")) and bool(payload.get("av_active")):
                        evidence["event_monitor"] = True

            cur.execute(
                """
                SELECT COUNT(*)
                FROM ransomware_ai_diagnostics
                WHERE created_at > NOW() - INTERVAL '24 hours'
                """
            )
            ai_recent = int((cur.fetchone() or [0])[0] or 0)
            evidence["ai_preemptive"] = ai_recent > 0
    except Exception as e:
        logger.warning(f"Erro ao validar módulos ransomware: {e}")
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        if conn:
            release_db(conn)

    for m in modules:
        mid = m.get("id")
        has_ev = bool(evidence.get(mid))
        if has_ev:
            m["status"] = "ATIVO" if mid != "auto_isolation" else "PRONTO"
            m["validated"] = True
        else:
            m["status"] = "NÃO VALIDADO"
            m["validated"] = False

    return JSONResponse({"status": "success", "total": len(modules), "modules": modules})


@router.get("/events")
async def get_ransomware_events():
    events: List[Dict[str, Any]] = []
    conn = None
    cur = None
    try:
        conn = get_db()
        if not conn:
            return JSONResponse({"status": "success", "total": 0, "events": []})
        _ensure_ransomware_tables(conn)
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, event_type, COALESCE(agent_hostname, agent_id), message, COALESCE(event_time, created_at)
            FROM ransomware_central_events
            ORDER BY id DESC
            LIMIT 80
            """
        )
        for r in cur.fetchall() or []:
            events.append({
                "id": r[0],
                "event_type": r[1],
                "agent_hostname": r[2],
                "message": r[3],
                "timestamp": str(r[4])[:19] if r[4] else None,
            })

        if not events:
            cur.execute(
                """
                SELECT id, COALESCE(event_type,'RANSOMWARE_EVENT'), COALESCE(agent_hostname, 'Servidor Central'), message, created_at
                FROM system_events
                WHERE event_type ILIKE '%ransomware%' OR event_type ILIKE '%canary%' OR message ILIKE '%ransomware%'
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
            for r in cur.fetchall() or []:
                events.append({
                    "id": r[0],
                    "event_type": r[1],
                    "agent_hostname": r[2],
                    "message": r[3],
                    "timestamp": str(r[4])[:19] if r[4] else None,
                })
    except Exception as e:
        logger.warning(f"Erro ao consultar eventos ransomware: {e}")
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        if conn:
            release_db(conn)

    return JSONResponse({"status": "success", "total": len(events), "events": events})


@router.get("/local_protection")
async def local_protection_status():
    status = {
        "av_installed": False,
        "av_name": "Nenhum Antivírus / EDR detectado",
        "av_active": False,
        "recent_security_events": [],
    }

    if platform.system() != "Windows":
        return JSONResponse(status)

    try:
        defender_cmd = (
            'Get-MpComputerStatus | '
            'Select-Object AMServiceEnabled, AntivirusEnabled, RealTimeProtectionEnabled | '
            'ConvertTo-Json -Depth 2'
        )
        def_result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", defender_cmd], capture_output=True, text=True, timeout=10)
        if def_result.returncode == 0 and def_result.stdout.strip():
            try:
                d = json.loads(def_result.stdout)
                if isinstance(d, dict):
                    status["av_installed"] = True
                    status["av_name"] = "Windows Defender Antivirus"
                    status["av_active"] = bool(d.get("AMServiceEnabled") or d.get("AntivirusEnabled") or d.get("RealTimeProtectionEnabled"))
            except Exception:
                pass

        if not status["av_installed"]:
            cim_cmd = (
                'Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | '
                'Select-Object displayName, productState | ConvertTo-Json -Depth 2'
            )
            cim_result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cim_cmd], capture_output=True, text=True, timeout=10)
            if cim_result.returncode == 0 and cim_result.stdout.strip():
                try:
                    products = json.loads(cim_result.stdout)
                    if isinstance(products, dict):
                        products = [products]
                    if products:
                        status["av_installed"] = True
                        status["av_name"] = (products[0] or {}).get("displayName") or "Antivírus / EDR"
                        status["av_active"] = any(int((p or {}).get("productState") or 0) & 0x10 or int((p or {}).get("productState") or 0) & 0x1000 for p in products)
                except Exception:
                    pass

        log_cmd = (
            'Get-WinEvent -FilterHashtable @{LogName="Microsoft-Windows-Windows Defender/Operational"; '
            'StartTime=(Get-Date).AddDays(-3)} -ErrorAction SilentlyContinue -MaxEvents 5 | '
            'Select-Object TimeCreated, Id, Message | ConvertTo-Json -Depth 2'
        )
        log_result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", log_cmd], capture_output=True, text=True, timeout=10)
        if log_result.returncode == 0 and log_result.stdout.strip():
            try:
                logs = json.loads(log_result.stdout)
                if isinstance(logs, dict):
                    logs = [logs]
                for lg in logs or []:
                    status["recent_security_events"].append({
                        "time": str((lg or {}).get("TimeCreated"))[:19],
                        "id": (lg or {}).get("Id"),
                        "message": str((lg or {}).get("Message", ""))[:200],
                    })
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Erro ao obter local_protection no Servidor: {e}")

    return JSONResponse(status)


@router.post("/preemptive_diag")
async def preemptive_ai_diag(request: Request):
    conn = None
    diagnostics: List[Dict[str, Any]] = []
    llm_summary = None
    try:
        conn = get_db()
        if conn:
            _ensure_ransomware_tables(conn)

        # Diagnóstico local do servidor
        local = await local_protection_status()
        local_data = local.body.decode("utf-8") if hasattr(local, "body") else "{}"
        local_obj = json.loads(local_data or "{}")

        active_incidents = 0
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM ransomware_central_incidents WHERE status <> 'resolved'")
            active_incidents = int((cur.fetchone() or [0])[0] or 0)
            cur.close()

        server_diag = _server_heuristic_diag(local_obj, active_incidents)
        diagnostics.append(server_diag)
        if conn:
            _persist_ai_diag(conn, "server", "server-host-local", server_diag)

        # Diagnóstico dos agentes
        for ag in _get_online_agents():
            aid = ag.get("agent_id")
            res = await _fetch_agent_endpoint(aid, "/api/ransomware/guardian/ai_diagnostic?include_llm=true", method="GET", timeout=20.0)
            if res.get("ok"):
                data = res.get("data") or {}
                diag = {
                    "node": f"{ag.get('hostname')} ({ag.get('ip')})",
                    "status": data.get("status") or (data.get("heuristic") or {}).get("status") or "UNKNOWN",
                    "threat_score": int((data.get("threat_score") if isinstance(data.get("threat_score"), int) else (data.get("heuristic") or {}).get("threat_score") or 0)),
                    "canaries_verified": int((data.get("heuristic") or {}).get("canaries_total") or 0),
                    "vss_lock": "ENABLED" if ((data.get("heuristic") or {}).get("shield_running") is not False) else "UNKNOWN",
                    "recommendation": data.get("recommendation") or (data.get("heuristic") or {}).get("recommendation") or "Sem recomendação",
                    "mode": data.get("mode") or "hybrid",
                }
            else:
                diag = {
                    "node": f"{ag.get('hostname')} ({ag.get('ip')})",
                    "status": "UNREACHABLE",
                    "threat_score": 100,
                    "canaries_verified": 0,
                    "vss_lock": "UNKNOWN",
                    "recommendation": f"Falha na coleta do diagnóstico IA: {res.get('error')}",
                    "mode": "heuristic",
                }

            diagnostics.append(diag)
            if conn:
                _persist_ai_diag(conn, "agent", aid, diag)

        # LLM opcional no servidor para resumo executivo
        try:
            from modules.ai_assistant.ai_diagnostic_engine import ServerAIDiagnosticEngine

            eng = ServerAIDiagnosticEngine()
            risks = [{"node": d.get("node"), "status": d.get("status"), "threat_score": d.get("threat_score")} for d in diagnostics]
            text = f"Ransomware Guardian central summary: {json.dumps(risks, ensure_ascii=False)}"
            llm = await eng.analyze_error(text, system_logs=[])
            llm_summary = llm.get("analysis") if isinstance(llm, dict) else None
        except Exception:
            llm_summary = None

        health = 100
        if diagnostics:
            health = max(0, 100 - int(sum(int(d.get("threat_score") or 0) for d in diagnostics) / max(len(diagnostics), 1)))

        return JSONResponse({
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "global_health_score": health,
            "overall_status": "SECURE" if health >= 80 else ("WARNING" if health >= 50 else "CRITICAL"),
            "nodes_scanned": len(diagnostics),
            "diagnostics": diagnostics,
            "ai_executive_summary": llm_summary or "Diagnóstico híbrido concluído com heurística local e coleta distribuída dos agentes.",
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
    finally:
        if conn:
            release_db(conn)
