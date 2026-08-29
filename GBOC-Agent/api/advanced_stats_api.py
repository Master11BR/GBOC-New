#!/usr/bin/env python3
"""
GBOC 13.2.0 - API de Estatísticas Avançadas
Consulta diretamente o PostgreSQL via SharedCore
"""

from fastapi import APIRouter, HTTPException
import logging
from datetime import datetime, timedelta
from typing import Dict, Any
import statistics as stats_module
import psycopg2.extras
import time
import threading
import copy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/advanced-stats", tags=["Advanced Statistics"])

_COMPREHENSIVE_CACHE: dict[int, tuple[float, Dict[str, Any]]] = {}
_COMPREHENSIVE_CACHE_LOCK = threading.Lock()
_COMPREHENSIVE_CACHE_TTL_SECONDS = 10.0


def _log_endpoint_perf(endpoint: str, started_at: float, extra: str = "") -> None:
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    suffix = f" | {extra}" if extra else ""
    logger.info(f"[PERF] GET {endpoint} concluído em {elapsed_ms} ms{suffix}")


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


def _default_comprehensive():
    return {
        "backup_stats": {"success_rate": 0.0, "total_backups": 0, "failed": 0, "avg_daily_backups": 0.0},
        "performance_stats": {"avg_speed_mbps": 0.0, "avg_duration_minutes": 0.0, "total_files_processed": 0, "total_data_processed_gb": 0.0},
        "storage_stats": {"total_backup_size_gb": 0.0, "data_growth_period_gb": 0.0, "avg_daily_growth_gb": 0.0, "projected_monthly_growth_gb": 0.0},
        "predictions": {"storage_30d_gb": 0.0, "storage_60d_gb": 0.0, "storage_90d_gb": 0.0},
        "reliability_stats": {"reliability_score": 0.0, "uptime_percentage": 0.0, "mtbf_hours": 0.0, "total_failures": 0},
        "health_score": 0.0,
        "generated_at": datetime.now().isoformat()
    }


def _compute_comprehensive(days: int = 30) -> Dict[str, Any]:
    """Calcula estatísticas abrangentes consultando o PostgreSQL."""
    now = time.monotonic()
    with _COMPREHENSIVE_CACHE_LOCK:
        cached = _COMPREHENSIVE_CACHE.get(days)
        if cached and (now - cached[0]) <= _COMPREHENSIVE_CACHE_TTL_SECONDS:
            logger.debug(f"[PERF][CACHE] advanced-stats cache hit days={days}")
            return copy.deepcopy(cached[1])

    core = _get_core()
    date_limit = (datetime.now() - timedelta(days=days)).isoformat()

    backup_stats = {"total_backups": 0, "successful": 0, "failed": 0, "success_rate": 0.0, "avg_daily_backups": 0.0}
    perf_stats = {"avg_speed_mbps": 0.0, "avg_duration_minutes": 0.0, "total_files_processed": 0, "total_data_processed_gb": 0.0}
    storage_stats = {"total_backup_size_gb": 0.0, "data_growth_period_gb": 0.0, "avg_daily_growth_gb": 0.0, "projected_monthly_growth_gb": 0.0}
    reliability_stats = {"reliability_score": 0.0, "uptime_percentage": 0.0, "mtbf_hours": 0.0, "total_failures": 0}
    predictions = {"storage_30d_gb": 0.0, "storage_60d_gb": 0.0, "storage_90d_gb": 0.0}

    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            # ── Backup stats ──
            cursor.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)
                FROM task_executions
                WHERE started_at >= %s
            """, (date_limit,))
            row = cursor.fetchone()
            total = row[0] or 0
            successful = row[1] or 0
            failed = row[2] or 0
            success_rate = (successful / total * 100) if total > 0 else 0.0

            cursor.execute("""
                SELECT started_at::date AS day, COUNT(*) AS cnt
                FROM task_executions
                WHERE started_at >= %s
                GROUP BY started_at::date
                ORDER BY day DESC
            """, (date_limit,))
            daily_rows = cursor.fetchall()
            avg_daily = stats_module.mean([r[1] for r in daily_rows]) if daily_rows else 0.0

            backup_stats = {
                "total_backups": total,
                "successful": successful,
                "failed": failed,
                "success_rate": round(success_rate, 2),
                "avg_daily_backups": round(avg_daily, 2)
            }

            # ── Performance stats ──
            cursor.execute("""
                SELECT
                    AVG(duration_seconds),
                    SUM(files_processed),
                    SUM(bytes_processed)
                FROM task_executions
                WHERE started_at >= %s AND status = 'completed'
            """, (date_limit,))
            row = cursor.fetchone()
            avg_dur = float(row[0] or 0)
            total_files = int(row[1] or 0)
            total_bytes = float(row[2] or 0)
            avg_speed = (total_bytes / avg_dur / (1024**2)) if avg_dur and total_bytes else 0.0
            total_gb = total_bytes / (1024**3) if total_bytes else 0.0

            perf_stats = {
                "avg_speed_mbps": round(avg_speed, 2),
                "avg_duration_minutes": round(avg_dur / 60, 2) if avg_dur else 0.0,
                "total_files_processed": total_files,
                "total_data_processed_gb": round(total_gb, 2)
            }

            # ── Storage stats ──
            growth = total_bytes
            daily_growth = growth / days if days > 0 else 0

            storage_stats = {
                "total_backup_size_gb": round(total_gb, 2),
                "data_growth_period_gb": round(growth / (1024**3), 2),
                "avg_daily_growth_gb": round(daily_growth / (1024**3), 4),
                "projected_monthly_growth_gb": round(daily_growth * 30 / (1024**3), 2)
            }

            # ── Reliability stats ──
            reliability = (successful / total * 100) if total > 0 else 0.0

            cursor.execute("""
                SELECT started_at
                FROM task_executions
                WHERE started_at >= %s AND status = 'failed'
                ORDER BY started_at
            """, (date_limit,))
            failure_rows = cursor.fetchall()
            mtbf_hours = 0.0
            if len(failure_rows) > 1:
                diffs = []
                for i in range(1, len(failure_rows)):
                    prev_t = failure_rows[i-1][0]
                    curr_t = failure_rows[i][0]
                    if prev_t and curr_t:
                        diff = (curr_t - prev_t).total_seconds() / 3600
                        diffs.append(diff)
                mtbf_hours = stats_module.mean(diffs) if diffs else 0.0

            reliability_stats = {
                "reliability_score": round(reliability, 2),
                "uptime_percentage": round(reliability, 2),
                "mtbf_hours": round(mtbf_hours, 2),
                "total_failures": failed
            }

            # ── Predictions ──
            cursor.execute("""
                SELECT bytes_processed
                FROM task_executions
                WHERE status = 'completed'
                ORDER BY started_at DESC
                LIMIT 30
            """)
            recent = [r[0] for r in cursor.fetchall() if r[0]]
            if len(recent) >= 1:
                avg_size = stats_module.mean(recent)
                predictions = {
                    "storage_30d_gb": round(avg_size * 30 / (1024**3), 2),
                    "storage_60d_gb": round(avg_size * 60 / (1024**3), 2),
                    "storage_90d_gb": round(avg_size * 90 / (1024**3), 2)
                }

    except Exception as e:
        logger.error(f"Erro ao calcular estatísticas: {e}", exc_info=True)

    # ── Health Score ──
    scores = []
    if reliability_stats.get("reliability_score"):
        scores.append(reliability_stats["reliability_score"] * 0.4)
    if perf_stats.get("avg_speed_mbps"):
        perf_score = min(perf_stats["avg_speed_mbps"] / 10 * 100, 100)
        scores.append(perf_score * 0.3)
    if backup_stats.get("success_rate"):
        scores.append(backup_stats["success_rate"] * 0.3)
    health_score = round(sum(scores), 2) if scores else 0.0

    result = {
        "period_days": days,
        "generated_at": datetime.now().isoformat(),
        "backup_stats": backup_stats,
        "performance_stats": perf_stats,
        "storage_stats": storage_stats,
        "reliability_stats": reliability_stats,
        "predictions": predictions,
        "health_score": health_score
    }

    with _COMPREHENSIVE_CACHE_LOCK:
        _COMPREHENSIVE_CACHE[days] = (time.monotonic(), copy.deepcopy(result))

    return result


@router.get("/comprehensive")
async def get_comprehensive_stats(days: int = 30):
    """Obtém estatísticas abrangentes"""
    request_start = time.perf_counter()
    try:
        data = _compute_comprehensive(days)
        return {"status": "success", "data": data}
    except Exception as e:
        logger.warning(f"Advanced stats fallback: {e}")
        return {"status": "success", "data": _default_comprehensive(), "note": "advanced_stats_fallback_error"}
    finally:
        _log_endpoint_perf("/api/advanced-stats/comprehensive", request_start, f"days={days}")

@router.get("/health-score")
async def get_health_score():
    """Obtém score de saúde do sistema"""
    request_start = time.perf_counter()
    try:
        data = _compute_comprehensive(7)
        return {
            "status": "success",
            "health_score": data.get("health_score", 0),
            "timestamp": data.get("generated_at")
        }
    except Exception as e:
        logger.warning(f"Health score fallback: {e}")
        return {"status": "success", "health_score": 0, "timestamp": datetime.now().isoformat(), "note": "advanced_stats_fallback_error"}
    finally:
        _log_endpoint_perf("/api/advanced-stats/health-score", request_start)

@router.get("/predictions")
async def get_predictions():
    """Obtém previsões do sistema"""
    request_start = time.perf_counter()
    try:
        data = _compute_comprehensive(30)
        return {"status": "success", "predictions": data.get("predictions", {})}
    except Exception as e:
        return {"status": "success", "predictions": {"storage_30d_gb": 0, "storage_60d_gb": 0, "storage_90d_gb": 0}}
    finally:
        _log_endpoint_perf("/api/advanced-stats/predictions", request_start)

@router.get("/trends")
async def get_trends(days: int = 30):
    """Obtém análise de tendências"""
    request_start = time.perf_counter()
    try:
        core = _get_core()
        date_limit = (datetime.now() - timedelta(days=days)).isoformat()
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT started_at::date AS day,
                       COUNT(CASE WHEN status = 'completed' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS success_rate
                FROM task_executions
                WHERE started_at >= %s
                GROUP BY started_at::date
                ORDER BY day
            """, (date_limit,))
            daily = cursor.fetchall()

        trend = "insufficient_data"
        if len(daily) >= 7:
            recent = stats_module.mean([float(r[1] or 0) for r in daily[-7:]])
            older = stats_module.mean([float(r[1] or 0) for r in daily[:7]])
            trend = "improving" if recent > older else ("declining" if recent < older else "stable")

        return {
            "status": "success",
            "trends": {
                "success_trend": trend,
                "daily_success_rates": [(str(d), round(float(r or 0), 2)) for d, r in daily]
            }
        }
    except Exception as e:
        logger.warning(f"Trends fallback: {e}")
        return {"status": "success", "trends": {}}
    finally:
        _log_endpoint_perf("/api/advanced-stats/trends", request_start, f"days={days}")


@router.get("/trend")
async def get_trend(days: int = 7):
    """Daily backup trend (success/failed per day) — used by Dashboard charts + heatmap."""
    request_start = time.perf_counter()
    try:
        core = _get_core()
        date_limit = (datetime.now() - timedelta(days=days)).isoformat()
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT started_at::date AS day,
                       COUNT(CASE WHEN status = 'completed' THEN 1 END) AS success,
                       COUNT(CASE WHEN status = 'failed' THEN 1 END) AS failed
                FROM task_executions
                WHERE started_at >= %s
                GROUP BY started_at::date
                ORDER BY day
            """, (date_limit,))
            rows = cursor.fetchall()
        trend = [{"date": str(r[0]), "success": r[1], "failed": r[2]} for r in rows]
        return {"trend": trend, "daily": trend, "days": days}
    except Exception as e:
        logger.warning(f"Trend fallback: {e}")
        return {"trend": [], "daily": [], "days": days}
    finally:
        _log_endpoint_perf("/api/advanced-stats/trend", request_start, f"days={days}")


@router.get("/distribution")
async def get_distribution():
    """Task execution status distribution (for pie/doughnut chart)."""
    request_start = time.perf_counter()
    try:
        core = _get_core()
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM task_executions
                WHERE started_at > CURRENT_TIMESTAMP - INTERVAL '30 days'
                GROUP BY status
            """)
            rows = cursor.fetchall()
        distribution = {r[0]: r[1] for r in rows} if rows else {}
        return {"distribution": distribution, "status_distribution": distribution}
    except Exception as e:
        logger.warning(f"Distribution fallback: {e}")
        return {"distribution": {}, "status_distribution": {}}
    finally:
        _log_endpoint_perf("/api/advanced-stats/distribution", request_start)


@router.get("/recent-executions")
async def get_recent_executions(limit: int = 30):
    """Recent task executions for timeline widget."""
    request_start = time.perf_counter()
    try:
        core = _get_core()
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT te.id, te.task_id, t.name as task_name,
                       te.status, te.started_at, te.completed_at,
                       te.duration_seconds, te.files_processed, te.bytes_processed,
                       te.error_message
                FROM task_executions te
                LEFT JOIN tasks t ON t.id = te.task_id
                ORDER BY te.started_at DESC
                LIMIT %s
            """, (limit,))
            cols = [d[0] for d in cursor.description]
            rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        # Serialize datetimes
        import json
        from decimal import Decimal as Dec
        class E(json.JSONEncoder):
            def default(self, o):
                if hasattr(o, 'isoformat'): return o.isoformat()
                if isinstance(o, Dec): return float(o)
                return super().default(o)
        clean = json.loads(json.dumps(rows, cls=E))
        return {"executions": clean}
    except Exception as e:
        logger.warning(f"Recent executions fallback: {e}")
        return {"executions": []}
    finally:
        _log_endpoint_perf("/api/advanced-stats/recent-executions", request_start, f"limit={limit}")

