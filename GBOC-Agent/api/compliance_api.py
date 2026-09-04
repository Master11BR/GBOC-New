#!/usr/bin/env python3
"""
GBOC 14.0.0 - Compliance API
Compliance score, policies CRUD, automated rules evaluation, audit trail.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging
import json
from decimal import Decimal
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compliance", tags=["Compliance"])


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


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


def _ensure_tables():
    """Create compliance tables if not exist."""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS compliance_policies (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    type VARCHAR(50) DEFAULT 'backup',
                    description TEXT,
                    enabled BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS compliance_audits (
                    id SERIAL PRIMARY KEY,
                    score REAL DEFAULT 0,
                    passing INTEGER DEFAULT 0,
                    failing INTEGER DEFAULT 0,
                    total_rules INTEGER DEFAULT 0,
                    details TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
    except Exception as e:
        logger.error(f"Compliance tables error: {e}")


_ensure_tables()


# ─── Compliance Rules Engine ──────────────────────────────────────

def _evaluate_rules():
    """Evaluate all compliance rules and return results."""
    core = _get_core()
    rules = []

    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            # Rule 1: All enabled tasks have a schedule
            cursor.execute("""
                SELECT COUNT(*)
                FROM tasks
                WHERE enabled = true
                  AND schedule_enabled = true
                  AND schedule_cron IS NOT NULL
                  AND schedule_cron <> ''
            """)
            scheduled = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM tasks WHERE enabled = true")
            total_tasks = cursor.fetchone()[0]
            rules.append({
                'name': 'Agendamento de Backup',
                'description': 'Todas as tarefas devem ter agendamento configurado',
                'status': 'pass' if total_tasks > 0 and scheduled == total_tasks else ('fail' if total_tasks > 0 else 'warn'),
                'fix': 'Configure um agendamento cron para cada tarefa' if scheduled < total_tasks else None,
            })

            # Rule 2: Recent backup exists (last 24h)
            cursor.execute("""
                SELECT COUNT(*) FROM task_executions
                WHERE started_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
                AND status = 'completed'
            """)
            recent_ok = cursor.fetchone()[0]

            # Verificar se é instalação recente (< 24h desde primeiro registro)
            cursor.execute("""
                SELECT MIN(created_at) FROM task_executions
            """)
            first_exec = cursor.fetchone()[0]
            is_new_install = first_exec is None  # Nenhuma execução = instalação nova

            rules.append({
                'name': 'Backup Recente (24h)',
                'description': 'Deve haver pelo menos 1 backup concluído nas últimas 24h',
                'status': 'pass' if recent_ok > 0 else ('warn' if is_new_install else 'fail'),
                'fix': 'Execute ou agende um backup imediatamente' if recent_ok == 0 and not is_new_install else ('Configure seu primeiro backup' if is_new_install and recent_ok == 0 else None),
            })

            # Rule 3: No consecutive failures
            cursor.execute("""
                SELECT COUNT(*) FROM (
                    SELECT status, LAG(status) OVER (ORDER BY started_at DESC) as prev
                    FROM task_executions ORDER BY started_at DESC LIMIT 10
                ) sub WHERE status = 'failed' AND prev = 'failed'
            """)
            consec_fails = cursor.fetchone()[0]
            rules.append({
                'name': 'Sem Falhas Consecutivas',
                'description': 'Não deve haver 2 ou mais falhas consecutivas',
                'status': 'pass' if consec_fails == 0 else 'fail',
                'fix': 'Investigue e corrija as causas de falha recorrentes' if consec_fails > 0 else None,
            })

            # Rule 4: Active repository exists
            cursor.execute("SELECT COUNT(*) FROM repositories WHERE status = 'active'")
            active_repos = cursor.fetchone()[0]

            # Verificar se existem repositórios cadastrados (mesmo inativos)
            cursor.execute("SELECT COUNT(*) FROM repositories")
            any_repos = cursor.fetchone()[0]
            is_fresh_install = any_repos == 0  # Nenhum repo = instalação nova

            rules.append({
                'name': 'Repositório Ativo',
                'description': 'Pelo menos 1 repositório deve estar ativo',
                'status': 'pass' if active_repos > 0 else ('warn' if is_fresh_install else 'fail'),
                'fix': 'Crie e ative um repositório de backup' if active_repos == 0 and not is_fresh_install else ('Configure seu primeiro repositório de backup' if is_fresh_install else None),
            })

            # Rule 5: Authentication enabled
            cursor.execute("SELECT COUNT(*) FROM auth_users")
            users_count = cursor.fetchone()[0]
            rules.append({
                'name': 'Autenticação Habilitada',
                'description': 'Sistema deve ter autenticação ativa com pelo menos 1 usuário',
                'status': 'pass' if users_count > 0 else 'fail',
                'fix': 'Configure autenticação com pelo menos 1 usuário admin' if users_count == 0 else None,
            })

            # Rule 6: Integrity check (last 7 days)
            try:
                cursor.execute("""
                    SELECT COUNT(*) FROM integrity_checks
                    WHERE COALESCE(finished_at, started_at) > CURRENT_TIMESTAMP - INTERVAL '7 days'
                    AND status IN ('passed', 'success', 'completed')
                """)
                integrity_recent = cursor.fetchone()[0]
            except Exception:
                integrity_recent = 0
            rules.append({
                'name': 'Verificação de Integridade (7d)',
                'description': 'Verificação de integridade deve ter sido executada nos últimos 7 dias',
                'status': 'pass' if integrity_recent > 0 else 'warn',
                'fix': 'Execute uma verificação de integridade dos backups' if integrity_recent == 0 else None,
            })

            # Rule 7: Success rate > 80%
            # Medir inicialmente desde a instalação/primeira atividade do sistema,
            # e depois exibir a janela efetiva (instalação, 7d, 15d, 30d...).
            cursor.execute("""
                SELECT COALESCE(
                    (SELECT MIN(updated_at) FROM settings),
                    (SELECT MIN(created_at) FROM repositories),
                    (SELECT MIN(created_at) FROM tasks),
                    (SELECT MIN(started_at) FROM task_executions),
                    CURRENT_TIMESTAMP
                )
            """)
            install_start = cursor.fetchone()[0]

            cursor.execute("""
                SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - %s)) / 86400.0
            """, (install_start,))
            age_days_row = cursor.fetchone()
            age_days = float(age_days_row[0] or 0) if age_days_row and age_days_row[0] is not None else 0

            if age_days < 7:
                window_label = 'desde a instalação'
                where_clause = 'started_at >= %s'
                where_params = (install_start,)
            elif age_days < 15:
                window_label = '7d'
                where_clause = "started_at > CURRENT_TIMESTAMP - INTERVAL '7 days'"
                where_params = ()
            elif age_days < 30:
                window_label = '15d'
                where_clause = "started_at > CURRENT_TIMESTAMP - INTERVAL '15 days'"
                where_params = ()
            else:
                window_label = '30d'
                where_clause = "started_at > CURRENT_TIMESTAMP - INTERVAL '30 days'"
                where_params = ()

            cursor.execute(f"""
                SELECT
                    COUNT(CASE WHEN status IN ('completed','success') THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0)
                FROM task_executions
                WHERE {where_clause}
            """, where_params)
            rate_row = cursor.fetchone()
            success_rate = float(rate_row[0] or 0) if rate_row and rate_row[0] else 0
            rules.append({
                'name': 'Taxa de Sucesso > 80%',
                'description': f'Taxa atual ({window_label}): {success_rate:.1f}%',
                'status': 'pass' if success_rate >= 80 else ('warn' if success_rate >= 50 else 'fail'),
                'fix': f'Taxa em {success_rate:.1f}% ({window_label}). Investigue falhas.' if success_rate < 80 else None,
            })

            # Rule 8: Motor de backup disponível
            try:
                from engines.engine_paths import get_engine_path
                available_engines = 0
                for engine_name in ('restic', 'kopia', 'duplicati', 'gboc_native'):
                    if engine_name == 'gboc_native' or get_engine_path(engine_name):
                        available_engines += 1

                # Também considerar motores configurados em repositórios como evidência adicional
                cursor.execute("SELECT COUNT(DISTINCT engine) FROM repositories WHERE enabled = TRUE")
                configured_engines = cursor.fetchone()[0] or 0
                engines = max(available_engines, configured_engines)
            except Exception:
                engines = 0
            rules.append({
                'name': 'Motor de Backup Disponível',
                'description': 'Pelo menos 1 motor de backup deve estar pronto',
                'status': 'pass' if engines >= 1 else 'fail',
                'fix': 'Instale e configure restic, kopia ou outro motor' if engines == 0 else None,
            })

    except Exception as e:
        logger.error(f"Rule evaluation error: {e}")

    return rules


# ─── Score endpoint ───────────────────────────────────────────────

@router.get("/score")
async def compliance_score():
    """Calculate and return current compliance score."""
    rules = _evaluate_rules()
    passing = sum(1 for r in rules if r['status'] == 'pass')
    failing = sum(1 for r in rules if r['status'] == 'fail')
    total = len(rules)
    score = round((passing / total) * 100) if total > 0 else 0

    # Count policies
    core = _get_core()
    total_policies = 0
    total_audits = 0
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM compliance_policies")
            total_policies = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM compliance_audits")
            total_audits = cursor.fetchone()[0]
    except Exception:
        pass

    return {
        "score": score,
        "passing": passing,
        "failing": failing,
        "total_rules": total,
        "total_policies": total_policies,
        "total_audits": total_audits,
    }


# ─── Rules endpoint ──────────────────────────────────────────────

@router.get("/rules")
async def get_compliance_rules():
    """Evaluate and list all compliance rules, ordered: FAIL > WARN > PASS."""
    rules = _evaluate_rules()
    status_order = {'fail': 0, 'warn': 1, 'pass': 2}
    rules.sort(key=lambda r: status_order.get(r.get('status', ''), 9))
    return {"rules": rules}


# ─── Policies CRUD ────────────────────────────────────────────────

class PolicyCreate(BaseModel):
    name: str
    type: str = "backup"
    description: Optional[str] = None


@router.get("/policies")
async def list_policies():
    """List all compliance policies."""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, type, description, enabled, created_at, updated_at
                FROM compliance_policies ORDER BY name
            """)
            cols = [d[0] for d in cursor.description]
            policies = [dict(zip(cols, row)) for row in cursor.fetchall()]
        return {"policies": _clean(policies)}
    except Exception as e:
        logger.error(f"List policies error: {e}")
        return {"policies": []}


@router.post("/policies")
async def create_policy(body: PolicyCreate):
    """Create a compliance policy."""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO compliance_policies (name, type, description)
                VALUES (%s, %s, %s) RETURNING id
            """, (body.name, body.type, body.description))
            pid = cursor.fetchone()[0]
            conn.commit()
        return {"id": pid, "status": "created"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/policies/{policy_id}")
async def delete_policy(policy_id: int):
    """Delete a compliance policy."""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM compliance_policies WHERE id = %s", (policy_id,))
            conn.commit()
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(500, str(e))


# ─── Audit ────────────────────────────────────────────────────────

@router.post("/audit")
async def run_audit():
    """Run a full compliance audit and record results."""
    rules = _evaluate_rules()
    passing = sum(1 for r in rules if r['status'] == 'pass')
    failing = sum(1 for r in rules if r['status'] == 'fail')
    total = len(rules)
    score = round((passing / total) * 100) if total > 0 else 0

    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO compliance_audits (score, passing, failing, total_rules, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (score, passing, failing, total, json.dumps(rules)))
            conn.commit()
    except Exception as e:
        logger.error(f"Record audit error: {e}")

    return {"score": score, "passing": passing, "failing": failing, "total_rules": total}


@router.get("/audit/history")
async def audit_history(limit: int = 20):
    """Get compliance audit history."""
    core = _get_core()
    try:
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, score, passing, failing, total_rules, timestamp
                FROM compliance_audits ORDER BY timestamp DESC LIMIT %s
            """, (limit,))
            cols = [d[0] for d in cursor.description]
            audits = [dict(zip(cols, row)) for row in cursor.fetchall()]
        return {"audits": _clean(audits)}
    except Exception as e:
        logger.error(f"Audit history error: {e}")
        return {"audits": []}

