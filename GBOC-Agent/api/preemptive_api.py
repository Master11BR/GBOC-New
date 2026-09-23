#!/usr/bin/env python3
"""
GBOC 14.6.0 - API de Diagnóstico Preemptivo
Consulta PostgreSQL via SharedCore
"""

from fastapi import APIRouter, HTTPException
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/preemptive", tags=["Preemptive Diagnostic"])


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


_last_check_ts = 0.0
_cached_check_result = None


def _run_check(force: bool = False):
    """Executa verificação preemptiva consultando PostgreSQL com cache TTL."""
    global _last_check_ts, _cached_check_result
    import time as _py_time
    now = _py_time.monotonic()
    if not force and _cached_check_result and (now - _last_check_ts < 10.0):
        return _cached_check_result

    core = _get_core()
    alerts = []
    warnings = []
    recommendations = []
    risk_level = "minimal"
    days_until_full = None

    # Sincronizar execuções reais do Duplicati Native se disponível (usando cache)
    try:
        from core.integrations.duplicati_native import get_duplicati_native_service
        get_duplicati_native_service().sync_to_gboc(core, force=False)
    except Exception as _sync_err:
        logger.debug(f"Sync Duplicati preemptive check bypass: {_sync_err}")

    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            # Verificar falhas recentes (últimas 24h)
            cursor.execute("""
                SELECT COUNT(*) FROM task_executions
                WHERE status = 'failed' AND started_at >= %s
            """, ((datetime.now() - timedelta(hours=24)).isoformat(),))
            recent_failures = cursor.fetchone()[0] or 0

            if recent_failures > 0:
                # Buscar detalhes reais dos erros recentes no banco
                try:
                    cursor.execute("""
                        SELECT te.id, te.task_id, t.name, t.engine, te.error_message, te.started_at
                        FROM task_executions te
                        JOIN tasks t ON te.task_id = t.id
                        WHERE te.status = 'failed' AND te.started_at >= %s
                        ORDER BY te.started_at DESC
                        LIMIT 5
                    """, ((datetime.now() - timedelta(hours=72)).isoformat(),))
                    for f_row in cursor.fetchall():
                        f_id, f_task_id, f_task_name, f_engine, f_error, f_started = f_row
                        alerts.append({
                            "type": "recent_failures",
                            "severity": "critical",
                            "message": f"Falha na tarefa '{f_task_name}' ({f_engine}): {f_error or 'Erro desconhecido'}",
                            "task_id": f_task_id,
                            "execution_id": f_id,
                            "started_at": str(f_started)
                        })
                except Exception as _e_fail:
                    alerts.append({
                        "type": "recent_failures",
                        "severity": "critical",
                        "message": f"{recent_failures} backup(s) falharam nas últimas 24 horas"
                    })
                risk_level = "high"

            # Verificar integridade geral (últimos 7 dias) - apenas tarefas ativas
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE te.status IN ('completed', 'repaired')) as success,
                    COUNT(*) FILTER (WHERE te.status = 'failed') as failed
                FROM task_executions te
                JOIN tasks t ON te.task_id = t.id
                WHERE te.started_at >= %s AND COALESCE(t.enabled, true) = true
            """, ((datetime.now() - timedelta(days=7)).isoformat(),))
            row = cursor.fetchone()
            total_7d = row[0] or 0
            success_7d = row[1] or 0
            failed_7d = row[2] or 0

            rate_7d = round((success_7d / total_7d) * 100, 1) if total_7d > 0 else 0

            if total_7d > 0 and rate_7d < 80:
                warnings.append({
                    "type": "low_success_rate",
                    "severity": "warning",
                    "message": f"Taxa de sucesso nos últimos 7 dias está em {rate_7d}% ({failed_7d} falhas de {total_7d} execuções)"
                })
                if risk_level != "high":
                    risk_level = "medium"

            # Verificar tarefas que nunca completaram com sucesso
            cursor.execute("""
                SELECT t.id, t.name, t.engine
                FROM tasks t
                WHERE COALESCE(t.enabled, true) = true
                  AND NOT EXISTS (
                      SELECT 1 FROM task_executions te
                      WHERE te.task_id = t.id AND te.status IN ('completed', 'repaired')
                  )
            """)
            never_completed = cursor.fetchall()
            for t_row in never_completed:
                t_id, t_name, t_engine = t_row
                cursor.execute("""
                    SELECT te.error_message, te.started_at
                    FROM task_executions te
                    WHERE te.task_id = %s AND te.status = 'failed'
                    ORDER BY te.started_at DESC LIMIT 1
                """, (t_id,))
                last_fail = cursor.fetchone()
                fail_reason = f" Último erro: {last_fail[0]}" if (last_fail and last_fail[0]) else ""
                
                warnings.append({
                    "type": "never_completed",
                    "severity": "warning",
                    "message": f"Tarefa '{t_name}' ({t_engine}) nunca completou um backup com sucesso.{fail_reason}"
                })

            # Verificar tarefas sem execução recente (mais de 48h)
            cursor.execute("""
                SELECT t.name, MAX(te.started_at) as last_run
                FROM tasks t
                JOIN task_executions te ON t.id = te.task_id
                WHERE COALESCE(t.enabled, true) = true
                GROUP BY t.id, t.name
                HAVING MAX(te.started_at) < %s
            """, ((datetime.now() - timedelta(hours=48)).isoformat(),))
            stale_tasks = cursor.fetchall()
            for st in stale_tasks:
                warnings.append({
                    "type": "stale_task",
                    "severity": "warning",
                    "message": f"Tarefa '{st[0]}' sem execução há mais de 48 horas (última: {st[1]})"
                })

            # Recomendações
            if recent_failures > 0:
                recommendations.append({
                    "type": "review_failures",
                    "message": "Revise os logs das tarefas que falharam para identificar a causa",
                    "priority": "high"
                })
            if total_7d == 0:
                recommendations.append({
                    "type": "schedule_backups",
                    "message": "Nenhum backup foi executado na última semana. Configure agendamentos.",
                    "priority": "high"
                })
            if total_7d > 0 and rate_7d == 100:
                recommendations.append({
                    "type": "system_healthy",
                    "message": "Sistema otimizado — todos os backups foram bem-sucedidos",
                    "priority": "low"
                })

    except Exception as e:
        logger.error(f"Erro no diagnóstico preemptivo: {e}", exc_info=True)

    check_res = {
        "alerts": alerts,
        "warnings": warnings,
        "risk_level": risk_level,
        "recommendations": recommendations,
        "checks": {"storage_capacity": {"days_until_full": days_until_full}}
    }
    _last_check_ts = _py_time.monotonic()
    _cached_check_result = check_res
    return check_res


@router.get("/check")
async def run_preemptive_check():
    """Executa verificação preemptiva"""
    try:
        report = _run_check()
        return {"status": "success", "data": report}
    except Exception as e:
        logger.warning(f"Preemptive fallback: {e}")
        return {"status": "success", "data": {"alerts": [], "warnings": [], "risk_level": "unknown", "recommendations": []}}


@router.get("/alerts")
async def get_alerts():
    """Obtém alertas do sistema"""
    try:
        report = _run_check()
        return {
            "status": "success",
            "alerts": report.get("alerts", []),
            "warnings": report.get("warnings", []),
            "risk_level": report.get("risk_level", "unknown")
        }
    except Exception as e:
        logger.warning(f"Alerts fallback: {e}")
        return {"status": "success", "alerts": [], "warnings": [], "risk_level": "unknown"}


@router.get("/recommendations")
async def get_recommendations():
    """Obtém recomendações do sistema"""
    try:
        report = _run_check()
        return {"status": "success", "recommendations": report.get("recommendations", [])}
    except Exception as e:
        return {"status": "success", "recommendations": []}


@router.get("/storage-forecast")
async def get_storage_forecast():
    """Obtém previsão de armazenamento"""
    try:
        report = _run_check()
        storage = report.get("checks", {}).get("storage_capacity", {})
        return {"status": "success", "storage": storage}
    except Exception as e:
        return {"status": "success", "storage": {}}


@router.get("/sla-compliance")
async def get_sla_compliance():
    """Calcula SLA compliance por tarefa — RPO, taxa de sucesso, última execução"""
    core = _get_core()
    try:
        try:
            from core.integrations.duplicati_native import get_duplicati_native_service
            get_duplicati_native_service().sync_to_gboc(core)
        except Exception:
            pass

        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT t.id, t.name, t.schedule_cron, t.schedule_enabled, t.engine,
                       t.retention_days,
                       (SELECT COUNT(*) FROM task_executions te
                        WHERE te.task_id = t.id AND te.status IN ('completed', 'repaired')
                        AND te.started_at >= NOW() - INTERVAL '30 days') as success_30d,
                       (SELECT COUNT(*) FROM task_executions te
                        WHERE te.task_id = t.id
                        AND te.started_at >= NOW() - INTERVAL '30 days') as total_30d,
                       (SELECT MAX(te.started_at) FROM task_executions te
                        WHERE te.task_id = t.id AND te.status IN ('completed', 'repaired')) as last_success,
                       (SELECT MAX(te.started_at) FROM task_executions te
                        WHERE te.task_id = t.id AND te.status = 'failed') as last_failure
                FROM tasks t WHERE t.enabled = true
                ORDER BY t.name
            """)

            tasks_sla = []
            for row in cursor.fetchall():
                tid, name, cron, sched_enabled, engine, ret_days, success_30d, total_30d, last_success, last_failure = row
                success_rate = (success_30d / total_30d * 100) if total_30d > 0 else 0

                # Calcular RPO (Recovery Point Objective) real
                rpo_hours = None
                if last_success:
                    rpo_hours = round((datetime.now() - last_success).total_seconds() / 3600, 1)

                # RPO esperado baseado no cron
                expected_rpo_hours = _estimate_rpo_from_cron(cron) if sched_enabled and cron else None

                # Compliance: RPO real <= 2x RPO esperado e taxa >= 90%
                rpo_ok = True
                if expected_rpo_hours and rpo_hours:
                    rpo_ok = rpo_hours <= (expected_rpo_hours * 2)

                compliance = "compliant" if (success_rate >= 90 and rpo_ok) else "non_compliant" if (success_rate < 70 or (rpo_hours and rpo_hours > 168)) else "at_risk"

                tasks_sla.append({
                    "id": tid,
                    "name": name,
                    "engine": engine,
                    "success_rate_30d": round(success_rate, 1),
                    "total_executions_30d": total_30d,
                    "successful_30d": success_30d,
                    "rpo_hours": rpo_hours,
                    "expected_rpo_hours": expected_rpo_hours,
                    "last_success": last_success.isoformat() if last_success else None,
                    "last_failure": last_failure.isoformat() if last_failure else None,
                    "compliance": compliance
                })

            # Calcular métricas globais
            total_tasks = len(tasks_sla)
            compliant = sum(1 for t in tasks_sla if t['compliance'] == 'compliant')
            at_risk = sum(1 for t in tasks_sla if t['compliance'] == 'at_risk')
            non_compliant = sum(1 for t in tasks_sla if t['compliance'] == 'non_compliant')
            overall_pct = (compliant / total_tasks * 100) if total_tasks > 0 else 100

            return {
                "status": "success",
                "summary": {
                    "total_tasks": total_tasks,
                    "compliant": compliant,
                    "at_risk": at_risk,
                    "non_compliant": non_compliant,
                    "compliance_pct": round(overall_pct, 1)
                },
                "tasks": tasks_sla
            }
    except Exception as e:
        logger.error(f"Erro no SLA compliance: {e}", exc_info=True)
        return {"status": "success", "summary": {"total_tasks": 0, "compliant": 0, "at_risk": 0, "non_compliant": 0, "compliance_pct": 100}, "tasks": []}


@router.get("/tasks-at-risk")
async def get_tasks_at_risk():
    """Identifica tarefas em risco — falhas consecutivas, sem backup recente, RPO violado"""
    core = _get_core()
    try:
        try:
            from core.integrations.duplicati_native import get_duplicati_native_service
            get_duplicati_native_service().sync_to_gboc(core)
        except Exception:
            pass

        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            risks = []

            # Tarefas com falhas consecutivas recentes
            cursor.execute("""
                SELECT t.id, t.name, t.engine,
                    (SELECT COUNT(*) FROM task_executions te
                     WHERE te.task_id = t.id AND te.status = 'failed'
                     AND te.started_at >= NOW() - INTERVAL '48 hours') as recent_fails,
                    (SELECT te.error_message FROM task_executions te
                     WHERE te.task_id = t.id AND te.status = 'failed'
                     ORDER BY te.started_at DESC LIMIT 1) as last_error,
                    (SELECT MAX(te.started_at) FROM task_executions te
                     WHERE te.task_id = t.id AND te.status IN ('completed', 'repaired')) as last_success
                FROM tasks t WHERE t.enabled = true
            """)

            for row in cursor.fetchall():
                tid, name, engine, recent_fails, last_error, last_success = row
                risk_factors = []

                if recent_fails >= 3:
                    risk_factors.append({"type": "consecutive_failures", "detail": f"{recent_fails} falhas em 48h", "severity": "critical"})
                elif recent_fails >= 1:
                    risk_factors.append({"type": "recent_failure", "detail": f"{recent_fails} falha(s) em 48h", "severity": "warning"})

                if last_success is None:
                    risk_factors.append({"type": "never_succeeded", "detail": "Nenhum backup concluído com sucesso", "severity": "critical"})
                elif (datetime.now() - last_success).days > 7:
                    days = (datetime.now() - last_success).days
                    risk_factors.append({"type": "stale_backup", "detail": f"Último sucesso há {days} dias", "severity": "critical" if days > 14 else "warning"})

                if risk_factors:
                    risks.append({
                        "id": tid,
                        "name": name,
                        "engine": engine,
                        "risk_factors": risk_factors,
                        "last_error": (last_error or '')[:200],
                        "last_success": last_success.isoformat() if last_success else None,
                        "risk_level": "critical" if any(r['severity'] == 'critical' for r in risk_factors) else "warning"
                    })

            risks.sort(key=lambda r: (0 if r['risk_level'] == 'critical' else 1))

            return {"status": "success", "tasks_at_risk": risks, "total": len(risks)}
    except Exception as e:
        logger.error(f"Erro tasks-at-risk: {e}", exc_info=True)
        return {"status": "success", "tasks_at_risk": [], "total": 0}


@router.get("/error-classification")
async def get_error_classification():
    """Classifica e agrupa erros por tipo/padrão"""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT te.error_message, COUNT(*) as count,
                       MAX(te.started_at) as last_occurrence,
                       t.name as task_name, t.engine
                FROM task_executions te
                JOIN tasks t ON te.task_id = t.id
                WHERE te.status = 'failed' AND te.error_message IS NOT NULL
                AND te.started_at >= NOW() - INTERVAL '30 days'
                GROUP BY te.error_message, t.name, t.engine
                ORDER BY count DESC
                LIMIT 50
            """)

            errors = []
            categories = {}

            for row in cursor.fetchall():
                error_msg, count, last_occurrence, task_name, engine = row
                category = _classify_error(error_msg or '')

                errors.append({
                    "message": (error_msg or '')[:300],
                    "count": count,
                    "category": category,
                    "task_name": task_name,
                    "engine": engine,
                    "last_occurrence": last_occurrence.isoformat() if last_occurrence else None
                })

                categories[category] = categories.get(category, 0) + count

            return {
                "status": "success",
                "errors": errors,
                "categories": categories,
                "total_errors": sum(categories.values())
            }
    except Exception as e:
        logger.error(f"Erro na classificação: {e}", exc_info=True)
        return {"status": "success", "errors": [], "categories": {}, "total_errors": 0}


def _classify_error(error_msg: str) -> str:
    """Classifica uma mensagem de erro em categoria"""
    msg = error_msg.lower()
    if any(w in msg for w in ['timeout', 'timed out', 'tempo limite']):
        return 'timeout'
    if any(w in msg for w in ['permission', 'permissão', 'denied', 'access', 'acesso']):
        return 'permission'
    if any(w in msg for w in ['network', 'connection', 'conexão', 'unreachable', 'dns', 'socket']):
        return 'network'
    if any(w in msg for w in ['disk', 'space', 'espaço', 'no space', 'storage full']):
        return 'storage'
    if any(w in msg for w in ['password', 'senha', 'auth', 'credential', 'token', '401', '403']):
        return 'authentication'
    if any(w in msg for w in ['not found', 'não encontrado', 'missing', 'no such file']):
        return 'not_found'
    if any(w in msg for w in ['corrupt', 'corrompido', 'invalid', 'inválido', 'damaged']):
        return 'corruption'
    if any(w in msg for w in ['lock', 'bloqueado', 'locked', 'already running']):
        return 'lock_conflict'
    return 'other'


def _estimate_rpo_from_cron(cron: str) -> float:
    """Estima RPO em horas baseado na expressão cron"""
    if not cron:
        return None
    parts = cron.strip().split()
    if len(parts) < 5:
        return None
    minute, hour, dom, month, dow = parts[:5]

    # Diário (hora fixa)
    if hour != '*' and dom == '*' and dow == '*':
        return 24.0
    # Semanal (dia da semana)
    if dow != '*' and dom == '*':
        days = len(dow.split(',')) if ',' in dow else 1
        return round(168.0 / days, 1)
    # A cada X horas
    if '/' in hour:
        try:
            interval = int(hour.split('/')[1])
            return float(interval)
        except (ValueError, IndexError):
            pass
    # A cada X minutos
    if '/' in minute:
        try:
            interval = int(minute.split('/')[1])
            return round(interval / 60.0, 1)
        except (ValueError, IndexError):
            pass
    return 24.0

