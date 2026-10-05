"""
GBOC Server — Fonte de dados dos relatórios (adaptador do report_core para o banco do Server).

Lê as tabelas sincronizadas pelos agentes (inventário, execuções, repositórios, métricas,
logs, eventos, segurança, auditoria). Todas as consultas são somente leitura e filtradas
por período e, quando informado, por agente.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gboc_report_source")


def _db():
    from database import db_manager
    return db_manager


class ServerReportSource:
    def __init__(self):
        self._conn = None
        self._dbm = None

    # ── conexão (uma por relatório) ──
    def __enter__(self):
        self._dbm = _db()
        self._conn = self._dbm.get_connection()
        try:
            from modules.agents.inventory_sync import ensure_schema
            ensure_schema(self._conn)
        except Exception as exc:
            logger.debug(f"schema de inventário: {exc}")
        return self

    def __exit__(self, *exc):
        try:
            self._conn.rollback()
        except Exception:
            pass
        self._dbm.release_connection(self._conn)
        self._conn = None

    def _q(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        from psycopg2.extras import RealDictCursor
        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    def _qsafe(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        try:
            return self._q(sql, params)
        except Exception as exc:
            logger.warning(f"[RELATÓRIOS] consulta ignorada: {exc}")
            return []

    @staticmethod
    def _agent_clause(col: str, agent_ids: Optional[List[str]]):
        if agent_ids:
            return f" AND {col} = ANY(%s)", (list(agent_ids),)
        return "", ()

    # ── metadados ──
    def info(self) -> Dict[str, Any]:
        settings: Dict[str, Any] = {}
        for r in self._qsafe("SELECT category, key, value FROM server_settings WHERE category IN ('reports','sync','general')"):
            settings[r["key"]] = r["value"]
        try:
            from modules.config.config_router import get_reports_config, get_usd_to_brl_rate
            cfg = get_reports_config() or {}
            settings.setdefault("cloud_storage_cost_usd_per_tb", cfg.get("cloud_storage_cost_usd_per_tb"))
            settings.setdefault("usd_brl_rate", get_usd_to_brl_rate())
        except Exception:
            pass
        try:
            from version_control import __version__ as ver
        except Exception:
            ver = ""
        return {"product": "server", "server_version": ver, "recommended_agent_version": ver,
                "organization": settings.get("company_name") or settings.get("server_name") or "",
                "platform": f"GBOC Server {ver}".strip(), "settings": settings}

    def agents(self) -> List[Dict[str, Any]]:
        return self._q("""SELECT agent_id, hostname, ip_address, os_info, agent_version, registered_at, last_heartbeat, status,
                                 cpu_usage, ram_usage, disk_usage, tenant_id FROM agents ORDER BY hostname""")

    def tenants(self) -> List[Dict[str, Any]]:
        return [{"tenant_id": r["org_id"], "name": r["name"], "plan": r.get("plan"), "max_agents": r.get("max_agents")}
                for r in self._qsafe("SELECT org_id, name, plan, max_agents FROM msp_organizations")]

    def inventory_status(self) -> Dict[str, Any]:
        return {r["agent_id"]: r["last_inventory_at"] for r in self._qsafe("SELECT agent_id, last_inventory_at FROM agent_inventory_status")}

    # ── inventário ──
    def tasks(self, agent_ids=None) -> List[Dict[str, Any]]:
        cl, p = self._agent_clause("agent_id", agent_ids)
        rows = self._q(f"""SELECT agent_id, task_id, name, status, engine, task_type, repository_id, repository_name, source_paths,
                                  schedule_cron, schedule_enabled, enabled, retention_policy, last_run, last_status, removed_at
                           FROM agent_tasks WHERE 1=1 {cl}""", p)
        for r in rows:
            try:
                r["source_paths"] = json.loads(r["source_paths"]) if r.get("source_paths") else None
            except Exception:
                r["source_paths"] = [r["source_paths"]]
            r["retention"] = r.pop("retention_policy", None)
            r["removed"] = bool(r.pop("removed_at", None))
            r["type"] = r.pop("task_type", None)
        return rows

    def repositories(self, agent_ids=None) -> List[Dict[str, Any]]:
        cl, p = self._agent_clause("agent_id", agent_ids)
        rows = self._q(f"""SELECT agent_id, repo_id, name, engine, type, status, path, target, provider, size_bytes, snapshot_count,
                                  free_bytes, capacity_bytes, size_recorded_at, last_backup, removed_at
                           FROM agent_repositories WHERE 1=1 {cl}""", p)
        for r in rows:
            r["removed"] = bool(r.pop("removed_at", None))
        return rows

    def repo_size_history(self, start: datetime, agent_ids=None) -> List[Dict[str, Any]]:
        cl, p = self._agent_clause("agent_id", agent_ids)
        return self._qsafe(f"""SELECT agent_id, repo_id, repo_name, size_bytes, snapshot_count, free_bytes, capacity_bytes, recorded_at
                               FROM agent_repo_size_history WHERE recorded_at >= %s {cl} ORDER BY recorded_at""", (start,) + p)

    def runs(self, start: datetime, end: datetime, agent_ids=None) -> List[Dict[str, Any]]:
        cl, p = self._agent_clause("e.agent_id", agent_ids)
        rows = self._q(f"""
            SELECT e.agent_id, e.task_id, COALESCE(e.task_name, t.name) AS task_name,
                   COALESCE(e.repository_name, t.repository_name) AS repository_name, e.status AS raw_status,
                   e.started_at, e.completed_at, e.duration_seconds AS duration_s, e.bytes_processed AS bytes,
                   e.bytes_added, e.files_processed AS files, e.files_new, e.files_changed, e.avg_speed_bps AS speed_bps,
                   e.error_message AS error
            FROM agent_task_executions e
            LEFT JOIN agent_tasks t ON t.agent_id = e.agent_id AND t.task_id = e.task_id
            WHERE e.started_at >= %s AND e.started_at <= %s {cl}
            ORDER BY e.started_at LIMIT 300000""", (start, end) + p)
        # Agentes antigos que só reportam via /api/v1/backups/report
        cl2, p2 = self._agent_clause("b.agent_id", agent_ids)
        legacy = self._qsafe(f"""
            SELECT b.agent_id, NULL AS task_id, COALESCE(NULLIF(b.source_path, ''), b.backup_type) AS task_name, NULL AS repository_name,
                   b.status AS raw_status, b.start_time AS started_at, b.end_time AS completed_at, b.duration_seconds AS duration_s,
                   b.total_bytes AS bytes, NULL AS bytes_added, b.total_files AS files, b.files_new, b.files_changed,
                   NULL AS speed_bps, b.error_message AS error
            FROM backup_reports b
            WHERE b.start_time >= %s AND b.start_time <= %s {cl2}
              AND NOT EXISTS (SELECT 1 FROM agent_task_executions x WHERE x.agent_id = b.agent_id)
            LIMIT 100000""", (start, end) + p2)
        for r in legacy:
            r["task_id"] = f"legacy:{r.get('task_name')}"
        return rows + legacy

    def restores(self, start, end, agent_ids=None):
        cl, p = self._agent_clause("agent_id", agent_ids)
        return self._qsafe(f"""SELECT agent_id, restore_id, repository_name, snapshot_id, status, target_path, total_files, files_restored,
                                      bytes_restored, duration_seconds, error_message, created_at
                               FROM agent_restore_history WHERE created_at >= %s AND created_at <= %s {cl}""", (start, end) + p)

    def verifications(self, start, end, agent_ids=None):
        cl, p = self._agent_clause("agent_id", agent_ids)
        return self._qsafe(f"""SELECT agent_id, kind, ext_id, subject, status, started_at, finished_at, errors_found, summary
                               FROM agent_verifications WHERE COALESCE(finished_at, started_at) >= %s
                               AND COALESCE(finished_at, started_at) <= %s {cl}""", (start, end) + p)

    def restore_tests(self, start, end, agent_ids=None):
        cl, p = self._agent_clause("agent_id", agent_ids)
        return self._qsafe(f"""SELECT agent_id, ext_id, repository_id, repository_name, engine, task_name, snapshot_id, snapshot_time,
                                      status, files_tested, files_ok, files_hash_verified, bytes_restored, duration_seconds,
                                      error_message, evidence_hash, triggered_by, started_at, completed_at
                               FROM agent_restore_tests WHERE started_at >= %s AND started_at <= %s {cl}""", (start, end) + p)

    def immutability(self, agent_ids=None):
        cl, p = self._agent_clause("agent_id", agent_ids)
        out = []
        for r in self._qsafe(f"SELECT agent_id, immutability FROM agent_operation WHERE 1=1 {cl}", p):
            for item in (r.get("immutability") or []):
                out.append({**item, "agent_id": r["agent_id"]})
        return out

    def job_failures(self, start, end, agent_ids=None):
        cl, p = self._agent_clause("agent_id", agent_ids)
        return self._qsafe(f"""SELECT agent_id, ext_id, task_id, task_name, failure_reason, retry_count, max_retries, status, escalated,
                                      first_failed_at, last_retried_at, resolved_at
                               FROM agent_job_failures WHERE (first_failed_at >= %s OR resolved_at IS NULL) {cl}""", (start,) + p)

    def volumes(self, agent_ids=None):
        cl, p = self._agent_clause("agent_id", agent_ids)
        return self._qsafe(f"SELECT agent_id, mountpoint, fstype, total_bytes, used_bytes, free_bytes FROM agent_volumes WHERE 1=1 {cl}", p)

    def replication(self, agent_ids=None):
        cl, p = self._agent_clause("agent_id", agent_ids)
        return self._qsafe(f"""SELECT agent_id, policy_id, name, source_repository_name, dest_type, mode, status, enabled, last_run, total_bytes
                               FROM agent_replication WHERE 1=1 {cl}""", p)

    # ── telemetria, eventos, segurança, auditoria ──
    def metrics(self, start, end, agent_ids=None):
        cl, p = self._agent_clause("agent_id", agent_ids)
        # Amostragem horária: evita trazer milhões de linhas em frotas grandes
        return self._qsafe(f"""SELECT agent_id, date_trunc('hour', timestamp) AS ts, AVG(cpu_usage) AS cpu, AVG(ram_usage) AS ram,
                                      MAX(disk_usage) AS disk
                               FROM agent_metrics WHERE timestamp >= %s AND timestamp <= %s {cl}
                               GROUP BY agent_id, date_trunc('hour', timestamp)""", (start, end) + p)

    def events(self, start, end, agent_ids=None):
        rows = self._qsafe("""SELECT e.created_at AS ts, e.event_type AS type, e.message, e.agent_hostname AS agent, a.agent_id
                              FROM system_events e LEFT JOIN agents a ON a.hostname = e.agent_hostname
                              WHERE e.created_at >= %s AND e.created_at <= %s ORDER BY e.created_at DESC LIMIT 5000""", (start, end))
        for r in rows:
            t = str(r.get("type") or "").lower()
            r["severity"] = "critical" if "critical" in t else "error" if ("error" in t or "fail" in t) else "warning" if "warn" in t else "info"
        if agent_ids:
            s = set(agent_ids)
            rows = [r for r in rows if r.get("agent_id") in s]
        return rows

    def log_error_summary(self, start, end, agent_ids=None):
        cl, p = self._agent_clause("agent_id", agent_ids)
        return self._qsafe(f"""SELECT agent_id, source, UPPER(level) AS level, COUNT(*) AS count, MAX(timestamp) AS last,
                                      (ARRAY_AGG(LEFT(message, 220) ORDER BY timestamp DESC))[1] AS sample
                               FROM agent_logs
                               WHERE timestamp >= %s AND timestamp <= %s
                                 AND (level ILIKE 'err%%' OR level ILIKE 'crit%%' OR level ILIKE 'fatal%%' OR level ILIKE 'warn%%') {cl}
                               GROUP BY agent_id, source, UPPER(level) ORDER BY COUNT(*) DESC LIMIT 300""", (start, end) + p)

    def log_error_daily(self, start, end, agent_ids=None):
        cl, p = self._agent_clause("agent_id", agent_ids)
        return self._qsafe(f"""SELECT to_char(date_trunc('day', timestamp), 'YYYY-MM-DD') AS day, COUNT(*) AS count
                               FROM agent_logs WHERE timestamp >= %s AND timestamp <= %s
                                 AND (level ILIKE 'err%%' OR level ILIKE 'crit%%' OR level ILIKE 'fatal%%') {cl}
                               GROUP BY 1""", (start, end) + p)

    def security(self, start, end, agent_ids=None):
        cl, p = self._agent_clause("agent_id", agent_ids)
        inc = self._qsafe(f"""SELECT agent_id, id, incident_external_id AS external_id, status, detected_at, resolved_at, threat_info_json
                              FROM ransomware_central_incidents WHERE COALESCE(detected_at, created_at) >= %s {cl}""", (start,) + p)
        for i in inc:
            try:
                ti = json.loads(i.pop("threat_info_json") or "{}")
                i["summary"] = ti.get("summary") or ti.get("description") or ti.get("threat_type") or ""
            except Exception:
                i["summary"] = ""
        evs = self._qsafe(f"""SELECT agent_id, event_type AS type, message, COALESCE(event_time, created_at) AS ts
                              FROM ransomware_central_events WHERE COALESCE(event_time, created_at) >= %s
                              AND COALESCE(event_time, created_at) <= %s {cl} ORDER BY ts DESC LIMIT 5000""", (start, end) + p)
        return {"incidents": inc, "events": evs}

    def audit(self, start, end):
        rows = self._qsafe("""SELECT timestamp AS ts, username, action, ip_address AS ip, details FROM server_auth_audit
                              WHERE timestamp >= %s AND timestamp <= %s ORDER BY timestamp DESC LIMIT 20000""", (start, end))
        for r in rows:
            a = str(r.get("action") or "").lower()
            r["ok"] = not ("fail" in a or "denied" in a or "blocked" in a or "locked" in a)
        return rows
