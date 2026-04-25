#!/usr/bin/env python3
"""
GBOC 11.7c - Prometheus Metrics API
Exposes /metrics endpoint in Prometheus text exposition format.
Metrics: backup durations, sizes, success/failure counts, health score, SLA, storage.
"""

import logging
import time
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Metrics"])


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


def _query(sql: str, params: tuple = ()):
    core = _get_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _query_one(sql: str, params: tuple = ()):
    rows = _query(sql, params)
    return rows[0] if rows else None


def _safe(v, default=0):
    """Safely convert value to float for Prometheus output."""
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


# ─── Prometheus text format helpers ───────────────────────────────

def _metric(name, help_text, mtype, lines):
    """Build a Prometheus metric block."""
    out = []
    out.append(f"# HELP {name} {help_text}")
    out.append(f"# TYPE {name} {mtype}")
    for line in lines:
        out.append(line)
    return "\n".join(out)


@router.get("/metrics", response_class=PlainTextResponse,
            summary="Prometheus metrics endpoint",
            description="Returns all GBOC metrics in Prometheus text exposition format.")
async def prometheus_metrics():
    """
    Prometheus scrape endpoint.
    Configure in prometheus.yml:
      - job_name: 'gboc-agent'
        static_configs:
          - targets: ['<host>:9200']
        metrics_path: /metrics
    """
    start = time.monotonic()
    blocks = []

    try:
        # ── 1. Task execution metrics ──────────────────────────────
        execs = _query("""
            SELECT t.name AS task_name, t.engine,
                   te.status, te.duration_seconds, te.bytes_processed
            FROM task_executions te
            JOIN tasks t ON t.id = te.task_id
            WHERE te.started_at >= NOW() - INTERVAL '30 days'
        """)

        # Aggregate per task+engine
        task_totals = {}  # (task, engine) -> {success, failure, duration_sum, bytes_sum, count}
        for e in execs:
            key = (e.get('task_name', 'unknown'), e.get('engine', 'unknown'))
            if key not in task_totals:
                task_totals[key] = {'success': 0, 'failure': 0, 'duration_sum': 0, 'bytes_sum': 0, 'count': 0}
            agg = task_totals[key]
            agg['count'] += 1
            agg['duration_sum'] += _safe(e.get('duration_seconds'))
            agg['bytes_sum'] += _safe(e.get('bytes_processed'))
            if e.get('status') == 'success':
                agg['success'] += 1
            elif e.get('status') in ('failed', 'error'):
                agg['failure'] += 1

        # backup_executions_total
        lines = []
        for (task, engine), agg in task_totals.items():
            lines.append(f'gboc_backup_executions_total{{task="{task}",engine="{engine}",status="success"}} {agg["success"]}')
            lines.append(f'gboc_backup_executions_total{{task="{task}",engine="{engine}",status="failure"}} {agg["failure"]}')
        blocks.append(_metric("gboc_backup_executions_total",
                              "Total backup executions in last 30 days", "counter", lines))

        # backup_duration_seconds_sum
        lines = []
        for (task, engine), agg in task_totals.items():
            lines.append(f'gboc_backup_duration_seconds_sum{{task="{task}",engine="{engine}"}} {agg["duration_sum"]}')
        blocks.append(_metric("gboc_backup_duration_seconds_sum",
                              "Sum of backup durations in seconds", "counter", lines))

        # backup_bytes_total
        lines = []
        for (task, engine), agg in task_totals.items():
            lines.append(f'gboc_backup_bytes_total{{task="{task}",engine="{engine}"}} {agg["bytes_sum"]}')
        blocks.append(_metric("gboc_backup_bytes_total",
                              "Total bytes processed by backups", "counter", lines))

        # ── 2. Active tasks gauge ──────────────────────────────────
        active = _query_one("SELECT COUNT(*) AS cnt FROM tasks WHERE enabled = true")
        blocks.append(_metric("gboc_active_tasks",
                              "Number of enabled backup tasks", "gauge",
                              [f'gboc_active_tasks {_safe(active.get("cnt") if active else 0)}']))

        # ── 3. Repository metrics ──────────────────────────────────
        repos = _query("SELECT name, engine, repo_type FROM repositories")
        blocks.append(_metric("gboc_repositories_total",
                              "Total configured repositories", "gauge",
                              [f'gboc_repositories_total {len(repos)}']))

        lines = []
        for r in repos:
            lines.append(f'gboc_repository_info{{name="{r.get("name","")}",engine="{r.get("engine","")}",type="{r.get("repo_type","")}"}} 1')
        blocks.append(_metric("gboc_repository_info",
                              "Repository metadata", "gauge", lines))

        # ── 4. Health score ────────────────────────────────────────
        try:
            from engines.health_score import calculate_health_score
            hs = calculate_health_score()
            score = _safe(hs.get('score') if isinstance(hs, dict) else 0)
        except Exception:
            score = 0
        blocks.append(_metric("gboc_health_score",
                              "System health score (0-100)", "gauge",
                              [f'gboc_health_score {score}']))

        # ── 5. Overall success rate ────────────────────────────────
        total_ok = sum(a['success'] for a in task_totals.values())
        total_all = sum(a['count'] for a in task_totals.values())
        rate = (total_ok / total_all * 100) if total_all > 0 else 0
        blocks.append(_metric("gboc_backup_success_rate_percent",
                              "Backup success rate percentage (30d)", "gauge",
                              [f'gboc_backup_success_rate_percent {rate:.2f}']))

        # ── 6. SLA compliance ──────────────────────────────────────
        try:
            sla = _query_one("""
                SELECT COUNT(*) FILTER (WHERE sla_ok) AS compliant, COUNT(*) AS total
                FROM (
                    SELECT t.id,
                           CASE WHEN MAX(te.started_at) >= NOW() - (t.schedule_interval || ' seconds')::INTERVAL
                                THEN true ELSE false END AS sla_ok
                    FROM tasks t
                    LEFT JOIN task_executions te ON te.task_id = t.id AND te.status = 'success'
                    WHERE t.enabled = true
                    GROUP BY t.id, t.schedule_interval
                ) sub
            """)
            if sla and sla.get('total', 0) > 0:
                sla_pct = _safe(sla['compliant']) / _safe(sla['total']) * 100
            else:
                sla_pct = 0
        except Exception:
            sla_pct = 0
        blocks.append(_metric("gboc_sla_compliance_percent",
                              "SLA compliance percentage", "gauge",
                              [f'gboc_sla_compliance_percent {sla_pct:.2f}']))

        # ── 7. Alert counts ────────────────────────────────────────
        try:
            alert_counts = _query("""
                SELECT severity, COUNT(*) AS cnt FROM alerts
                WHERE acknowledged = false
                GROUP BY severity
            """)
            lines = []
            for ac in alert_counts:
                lines.append(f'gboc_alerts_active{{severity="{ac.get("severity","unknown")}"}} {_safe(ac.get("cnt"))}')
            if not lines:
                lines = ['gboc_alerts_active{severity="none"} 0']
            blocks.append(_metric("gboc_alerts_active",
                                  "Active (unacknowledged) alerts by severity", "gauge", lines))
        except Exception:
            blocks.append(_metric("gboc_alerts_active",
                                  "Active alerts by severity", "gauge",
                                  ['gboc_alerts_active{severity="none"} 0']))

        # ── 8. Engine-level aggregates ─────────────────────────────
        engine_agg = {}
        for (task, engine), agg in task_totals.items():
            if engine not in engine_agg:
                engine_agg[engine] = {'success': 0, 'failure': 0, 'bytes': 0}
            engine_agg[engine]['success'] += agg['success']
            engine_agg[engine]['failure'] += agg['failure']
            engine_agg[engine]['bytes'] += agg['bytes_sum']

        lines = []
        for eng, ea in engine_agg.items():
            lines.append(f'gboc_engine_backup_total{{engine="{eng}",status="success"}} {ea["success"]}')
            lines.append(f'gboc_engine_backup_total{{engine="{eng}",status="failure"}} {ea["failure"]}')
        blocks.append(_metric("gboc_engine_backup_total",
                              "Backups per engine (30d)", "counter", lines))

        # ── 9. System uptime ───────────────────────────────────────
        try:
            import psutil
            boot = psutil.boot_time()
            uptime = time.time() - boot
        except Exception:
            uptime = 0
        blocks.append(_metric("gboc_system_uptime_seconds",
                              "System uptime in seconds", "gauge",
                              [f'gboc_system_uptime_seconds {uptime:.0f}']))

        # ── 10. Scrape duration ────────────────────────────────────
        elapsed = time.monotonic() - start
        blocks.append(_metric("gboc_metrics_scrape_duration_seconds",
                              "Time taken to collect metrics", "gauge",
                              [f'gboc_metrics_scrape_duration_seconds {elapsed:.6f}']))

    except Exception as e:
        logger.error(f"Error collecting Prometheus metrics: {e}")
        blocks.append(f"# ERROR collecting metrics: {e}")

    return "\n\n".join(blocks) + "\n"

