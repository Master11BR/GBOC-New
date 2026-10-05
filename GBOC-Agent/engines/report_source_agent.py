"""
GBOC Agent — Fonte de dados dos relatórios (adaptador do report_core para o banco local).

Reaproveita o mesmo inventário que é enviado ao Server (core.central_inventory) para que
os números do relatório do Agente e do Server sejam idênticos para este host.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import socket
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
LOCAL_ID = "local"


class AgentReportSource:
    def __init__(self):
        self._core = None
        self._inv: Optional[Dict[str, Any]] = None
        self._days = 30

    def __enter__(self):
        from shared_core import get_shared_core
        self._core = get_shared_core()
        return self

    def __exit__(self, *exc):
        return False

    def prepare(self, days: int):
        self._days = days

    def _rows(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        from core.central_inventory import _rows
        with self._core.get_db_connection() as conn:
            cur = conn.cursor()
            try:
                return _rows(cur, sql, params)
            finally:
                try:
                    cur.close()
                except Exception:
                    pass

    def _inventory(self) -> Dict[str, Any]:
        if self._inv is None:
            from core.central_inventory import build_inventory
            with self._core.get_db_connection() as conn:
                self._inv = build_inventory(conn, days=max(self._days, 1) + 1, max_executions=200000)
        return self._inv

    @staticmethod
    def _tag(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for r in rows:
            r["agent_id"] = LOCAL_ID
        return rows

    # ── metadados ──
    def info(self) -> Dict[str, Any]:
        try:
            from version_control import __version__ as ver
        except Exception:
            ver = ""
        settings: Dict[str, Any] = {}
        for r in self._rows("SELECT key, value FROM settings WHERE category IN ('reports', 'general')"):
            settings[r.get("key")] = r.get("value")
        try:
            from api.reports_api import get_agent_reports_config, get_usd_to_brl_rate
            cfg = get_agent_reports_config() or {}
            settings.setdefault("cloud_storage_cost_usd_per_tb", cfg.get("cloud_storage_cost_usd_per_tb"))
            settings.setdefault("usd_brl_rate", get_usd_to_brl_rate())
        except Exception:
            pass
        return {"product": "agent", "server_version": ver, "recommended_agent_version": None,
                "hostname": socket.gethostname(), "organization": settings.get("company_name") or "",
                "platform": f"GBOC Agent {ver}".strip(), "settings": settings}

    def agents(self) -> List[Dict[str, Any]]:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.2)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage("C:\\" if os.name == "nt" else "/").percent
            boot = datetime.fromtimestamp(psutil.boot_time())
        except Exception:
            cpu = ram = disk = None
            boot = None
        try:
            from version_control import __version__ as ver
        except Exception:
            ver = ""
        ip = ""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
        return [{"agent_id": LOCAL_ID, "hostname": socket.gethostname(), "ip_address": ip,
                 "os_info": f"{platform.system()} {platform.release()}", "agent_version": ver, "registered_at": boot,
                 "last_heartbeat": datetime.now(), "status": "online", "cpu_usage": cpu, "ram_usage": ram,
                 "disk_usage": disk, "tenant_id": None}]

    def tenants(self) -> List[Dict[str, Any]]:
        return []

    def inventory_status(self) -> Dict[str, Any]:
        return {LOCAL_ID: datetime.now()}

    # ── inventário ──
    def tasks(self, agent_ids=None):
        out = []
        for t in self._inventory()["tasks"]:
            r = dict(t)
            r["task_id"] = r.pop("id", None)
            parts = []
            for key, label in (("retention_days", "d"), ("retention_weekly", "s"), ("retention_monthly", "m"), ("retention_yearly", "a")):
                if r.get(key):
                    parts.append(f"{r[key]}{label}")
            r["retention"] = " / ".join(parts)
            r["removed"] = False
            out.append(r)
        return self._tag(out)

    def repositories(self, agent_ids=None):
        out = []
        for rp in self._inventory()["repositories"]:
            r = dict(rp)
            r["repo_id"] = r.pop("id", None)
            r["removed"] = str(r.get("status") or "").lower() in ("deleted", "removed")
            out.append(r)
        return self._tag(out)

    def repo_size_history(self, start, agent_ids=None):
        names = {str(r.get("id")): r.get("name") for r in self._inventory()["repositories"]}
        rows = self._rows("""SELECT repository_id, repository_name, size_bytes, snapshot_count, recorded_at
                             FROM storage_usage_history WHERE recorded_at >= %s ORDER BY recorded_at""", (start,))
        out = []
        for r in rows:
            rid = str(r.get("repository_id"))
            if rid not in names:
                continue  # volumes do host (disk_*) não são repositórios
            out.append({"repo_id": int(rid) if rid.isdigit() else rid, "repo_name": names[rid], "size_bytes": r.get("size_bytes"),
                        "snapshot_count": r.get("snapshot_count"), "recorded_at": r.get("recorded_at")})
        return self._tag(out)

    def runs(self, start, end, agent_ids=None):
        out = []
        for e in self._inventory()["task_executions"]:
            out.append({"task_id": e.get("task_id"), "task_name": e.get("task_name"), "repository_name": e.get("repository_name"),
                        "raw_status": e.get("status"), "started_at": e.get("started_at"), "completed_at": e.get("completed_at"),
                        "duration_s": e.get("duration_seconds"), "bytes": e.get("bytes_processed"), "bytes_added": e.get("bytes_added"),
                        "files": e.get("files_processed"), "files_new": e.get("files_new"), "files_changed": e.get("files_changed"),
                        "speed_bps": e.get("avg_speed_bytes_per_sec"), "error": e.get("error_message")})
        return self._tag(out)

    def restores(self, start, end, agent_ids=None):
        out = []
        for r in self._inventory()["restores"]:
            r = dict(r)
            r["restore_id"] = r.pop("id", None)
            out.append(r)
        return self._tag(out)

    def verifications(self, start, end, agent_ids=None):
        return self._tag([dict(v) for v in self._inventory()["verifications"]])

    def restore_tests(self, start, end, agent_ids=None):
        return self._tag([dict(t, ext_id=t.get("id")) for t in self._inventory().get("restore_tests", [])])

    def immutability(self, agent_ids=None):
        return self._tag([dict(r) for r in self._inventory().get("immutability", [])])

    def job_failures(self, start, end, agent_ids=None):
        return self._tag([dict(f) for f in self._inventory()["job_failures"]])

    def volumes(self, agent_ids=None):
        return self._tag([dict(v) for v in self._inventory()["volumes"]])

    def replication(self, agent_ids=None):
        return self._tag([dict(p) for p in self._inventory().get("replication", [])])

    # ── telemetria, eventos, segurança, auditoria ──
    def metrics(self, start, end, agent_ids=None):
        rows = self._rows("""SELECT date_trunc('hour', recorded_at) AS ts, metric_name, AVG(value) AS v
                             FROM performance_metrics WHERE recorded_at >= %s AND recorded_at <= %s
                               AND metric_name IN ('cpu_percent', 'cpu_usage', 'memory_percent', 'ram_usage', 'disk_percent', 'disk_usage')
                             GROUP BY 1, 2""", (start, end))
        by_ts: Dict[Any, Dict[str, Any]] = {}
        for r in rows:
            d = by_ts.setdefault(r["ts"], {"ts": r["ts"]})
            n = r.get("metric_name") or ""
            key = "cpu" if n.startswith("cpu") else "ram" if (n.startswith("memory") or n.startswith("ram")) else "disk"
            d[key] = r.get("v")
        return self._tag(list(by_ts.values()))

    def events(self, start, end, agent_ids=None):
        rows = self._rows("""SELECT timestamp AS ts, type, severity, COALESCE(title || ': ', '') || COALESCE(message, '') AS message
                             FROM alerts WHERE timestamp >= %s AND timestamp <= %s ORDER BY timestamp DESC LIMIT 5000""", (start, end))
        return self._tag(rows)

    def log_error_summary(self, start, end, agent_ids=None):
        rows = self._rows("""SELECT source, UPPER(level) AS level, COUNT(*) AS count, MAX(timestamp) AS last,
                                    (ARRAY_AGG(LEFT(message, 220) ORDER BY timestamp DESC))[1] AS sample
                             FROM system_logs WHERE timestamp >= %s AND timestamp <= %s
                               AND (level ILIKE 'err%%' OR level ILIKE 'crit%%' OR level ILIKE 'fatal%%' OR level ILIKE 'warn%%')
                             GROUP BY source, UPPER(level) ORDER BY COUNT(*) DESC LIMIT 200""", (start.isoformat(), end.isoformat()))
        return self._tag(rows)

    def log_error_daily(self, start, end, agent_ids=None):
        return self._rows("""SELECT LEFT(timestamp::text, 10) AS day, COUNT(*) AS count FROM system_logs
                             WHERE timestamp >= %s AND timestamp <= %s
                               AND (level ILIKE 'err%%' OR level ILIKE 'crit%%' OR level ILIKE 'fatal%%')
                             GROUP BY 1""", (start.isoformat(), end.isoformat()))

    def security(self, start, end, agent_ids=None):
        scans = self._rows("""SELECT scan_type, target_path, status, threat_level, summary, started_at, completed_at
                              FROM ransomware_scans WHERE started_at >= %s ORDER BY started_at DESC LIMIT 2000""", (start,))
        incidents, events = [], []
        for s in scans:
            lvl = str(s.get("threat_level") or "").lower()
            if lvl in ("high", "critical", "alto", "crítico", "critico"):
                incidents.append({"id": None, "external_id": f"scan {s.get('scan_type')}", "status": s.get("status"),
                                  "detected_at": s.get("started_at"), "resolved_at": None,
                                  "summary": f"Ameaça {lvl} em {s.get('target_path')}"})
            events.append({"type": f"scan {s.get('scan_type') or ''}".strip(), "ts": s.get("started_at"),
                           "message": f"{s.get('target_path') or ''} — status {s.get('status')}, nível {s.get('threat_level') or 'n/d'}"})
        for a in self._rows("""SELECT timestamp AS ts, type, COALESCE(title || ': ', '') || COALESCE(message, '') AS message FROM alerts
                               WHERE timestamp >= %s AND (type ILIKE '%%ransom%%' OR source ILIKE '%%ransom%%' OR title ILIKE '%%ransom%%')""", (start,)):
            events.append(a)
        return {"incidents": self._tag(incidents), "events": self._tag(events)}

    def audit(self, start, end):
        rows = self._rows("""SELECT timestamp AS ts, username, action, ip_address AS ip, result, error_message,
                                    COALESCE(resource_type || ' ' || COALESCE(resource_name, ''), '') AS details
                             FROM audit_log WHERE timestamp >= %s AND timestamp <= %s ORDER BY timestamp DESC LIMIT 20000""", (start, end))
        for r in rows:
            res = str(r.get("result") or "").lower()
            act = str(r.get("action") or "").lower()
            r["ok"] = not (res in ("failure", "failed", "error", "denied") or "fail" in act)
        return rows
