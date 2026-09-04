#!/usr/bin/env python3
"""
GBOC 14.0.0 - Módulo Unificado de Health Score
Cálculo padronizado de saúde do sistema usado em todos os endpoints.

Pesos:
  - Sistema (CPU/Mem/Disco) ........... 30%
  - Ferramentas instaladas ............ 10%
  - Taxa de sucesso de backups ........ 30%
  - Repositórios ....................... 15%
  - Desempenho de tarefas ............. 15%

Status:
  >= 85  →  excellent
  >= 70  →  good
  >= 50  →  warning
  <  50  →  critical
"""

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds padrão
# ---------------------------------------------------------------------------
THRESHOLD_EXCELLENT = 85
THRESHOLD_GOOD = 70
THRESHOLD_WARNING = 50


def get_health_status(score: float) -> str:
    """Converte score numérico em status textual padronizado."""
    if score >= THRESHOLD_EXCELLENT:
        return "excellent"
    elif score >= THRESHOLD_GOOD:
        return "good"
    elif score >= THRESHOLD_WARNING:
        return "warning"
    else:
        return "critical"


def get_health_status_label(score: float) -> str:
    """Retorna label em português para o frontend."""
    if score >= THRESHOLD_EXCELLENT:
        return "Sistema saudável e operacional"
    elif score >= THRESHOLD_GOOD:
        return "Atenção: algumas métricas precisam de revisão"
    elif score >= THRESHOLD_WARNING:
        return "Aviso: sistema requer monitoramento"
    else:
        return "Crítico: intervenção necessária"


# ---------------------------------------------------------------------------
# Cálculos parciais
# ---------------------------------------------------------------------------

def _score_system(cpu_percent: float = 0, memory_percent: float = 0,
                  disk_percent: float = 0) -> float:
    """Score de recursos do sistema (0-100)."""
    score = 100.0

    # CPU
    if cpu_percent > 95:
        score -= 35
    elif cpu_percent > 85:
        score -= 25
    elif cpu_percent > 75:
        score -= 15
    elif cpu_percent > 60:
        score -= 5

    # Memória
    if memory_percent > 95:
        score -= 35
    elif memory_percent > 85:
        score -= 25
    elif memory_percent > 75:
        score -= 15
    elif memory_percent > 60:
        score -= 5

    # Disco
    if disk_percent > 95:
        score -= 30
    elif disk_percent > 90:
        score -= 20
    elif disk_percent > 80:
        score -= 10

    return max(0.0, score)


def _score_tools(installed_count: int = 0, total_count: int = 3) -> float:
    """Score de ferramentas de backup instaladas (0-100)."""
    if total_count == 0:
        return 100.0
    if installed_count == 0:
        return 0.0
    ratio = installed_count / total_count
    return min(100.0, ratio * 100.0)


def _score_backup_success(success_rate: float = 0, total_backups: int = 0) -> float:
    """Score de taxa de sucesso de backups (0-100).

    Se não há backups, retorna 50 (neutro).
    """
    if total_backups == 0:
        return 50.0
    return min(100.0, max(0.0, success_rate))


def _score_repositories(total_repos: int = 0, active_repos: int = 0) -> float:
    """Score de saúde dos repositórios (0-100).

    Se não há repos, retorna 50 (neutro).
    """
    if total_repos == 0:
        return 50.0
    ratio = active_repos / total_repos
    return min(100.0, ratio * 100.0)


def _score_tasks(success_rate: float = 0, total_tasks: int = 0,
                 running_tasks: int = 0) -> float:
    """Score de desempenho de tarefas (0-100).

    Se não há tarefas, retorna 50 (neutro).
    """
    if total_tasks == 0:
        return 50.0
    return min(100.0, max(0.0, success_rate))


# ---------------------------------------------------------------------------
# Issue-based scoring (para healer_engine)
# ---------------------------------------------------------------------------

def score_from_issues(checks: Dict[str, Any]) -> float:
    """Calcula score baseado em checks com issues (usado pelo HealerEngine).

    Cada check pode ter:
      - status == 'error' → -20
      - issues com severity 'critical' → -15
      - issues com severity 'warning' → -5
    """
    score = 100.0
    try:
        for check_name, check_data in checks.items():
            if check_data.get("status") == "error":
                score -= 20
            elif check_data.get("issues"):
                for issue in check_data["issues"]:
                    if issue.get("severity") == "critical":
                        score -= 15
                    elif issue.get("severity") == "warning":
                        score -= 5
    except Exception:
        score = 50.0
    return max(0.0, min(100.0, score))


# ---------------------------------------------------------------------------
# Função principal — cálculo completo
# ---------------------------------------------------------------------------

def calculate_health_score(
    cpu_percent: float = 0,
    memory_percent: float = 0,
    disk_percent: float = 0,
    installed_engines: int = 0,
    total_engines: int = 3,
    backup_success_rate: float = 0,
    total_backups: int = 0,
    total_repos: int = 0,
    active_repos: int = 0,
    task_success_rate: float = 0,
    total_tasks: int = 0,
    running_tasks: int = 0,
) -> Dict[str, Any]:
    """
    Calcula o health score unificado do sistema.

    Retorna:
        {
            "score": float (0-100),
            "status": str,
            "label": str,
            "breakdown": {
                "system": float,
                "tools": float,
                "backups": float,
                "repositories": float,
                "tasks": float
            }
        }
    """
    try:
        sys_score = _score_system(cpu_percent, memory_percent, disk_percent)
        tool_score = _score_tools(installed_engines, total_engines)
        backup_score = _score_backup_success(backup_success_rate, total_backups)
        repo_score = _score_repositories(total_repos, active_repos)
        task_score = _score_tasks(task_success_rate, total_tasks, running_tasks)

        # Média ponderada
        overall = (
            sys_score * 0.30 +
            tool_score * 0.10 +
            backup_score * 0.30 +
            repo_score * 0.15 +
            task_score * 0.15
        )
        overall = round(max(0.0, min(100.0, overall)), 1)

        return {
            "score": overall,
            "status": get_health_status(overall),
            "label": get_health_status_label(overall),
            "breakdown": {
                "system": round(sys_score, 1),
                "tools": round(tool_score, 1),
                "backups": round(backup_score, 1),
                "repositories": round(repo_score, 1),
                "tasks": round(task_score, 1),
            }
        }
    except Exception as e:
        logger.error(f"Erro ao calcular health score: {e}")
        return {
            "score": 50.0,
            "status": "warning",
            "label": "Erro ao calcular saúde do sistema",
            "breakdown": {
                "system": 50.0,
                "tools": 50.0,
                "backups": 50.0,
                "repositories": 50.0,
                "tasks": 50.0,
            }
        }


# ---------------------------------------------------------------------------
# Helper: coleta métricas e calcula em um só passo
# ---------------------------------------------------------------------------

def calculate_health_score_auto() -> Dict[str, Any]:
    """
    Coleta automaticamente todas as métricas (psutil + DB) e calcula o score.
    Útil para endpoints que não têm as métricas pré-coletadas.
    """
    import psutil
    import platform

    # 1. Métricas do sistema
    cpu_percent = psutil.cpu_percent(interval=0.3)
    memory_percent = psutil.virtual_memory().percent
    try:
        disk_percent = psutil.disk_usage('C:\\' if platform.system() == 'Windows' else '/').percent
    except Exception:
        disk_percent = 0

    # 2. Ferramentas instaladas
    installed_engines = 0
    total_engines = 3
    try:
        from engines.engine_paths import detect_all_engines
        engines = detect_all_engines()
        installed_engines = len([e for e in engines if e.get('detected')])
    except Exception:
        try:
            import shutil
            for eng in ['restic', 'kopia', 'duplicati']:
                if shutil.which(eng) or shutil.which(f"{eng}.exe"):
                    installed_engines += 1
        except Exception:
            pass

    # 3. Dados do banco (backups, repos, tasks)
    backup_success_rate = 0.0
    total_backups = 0
    total_repos = 0
    active_repos = 0
    task_success_rate = 0.0
    total_tasks = 0
    running_tasks = 0

    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()

            # Backups (últimos 30 dias)
            cur.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)
                FROM task_executions
                WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
            """)
            row = cur.fetchone()
            total_backups = row[0] or 0
            successful = row[1] or 0
            backup_success_rate = (successful / total_backups * 100) if total_backups > 0 else 0.0

            # Repositórios
            cur.execute("SELECT COUNT(*) FROM repositories")
            total_repos = cur.fetchone()[0] or 0
            active_repos = total_repos  # Todos são considerados ativos por padrão

            # Tarefas
            cur.execute("SELECT COUNT(*) FROM tasks WHERE enabled = true")
            total_tasks = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM tasks WHERE status = 'running'")
            running_tasks = cur.fetchone()[0] or 0

            # Taxa de sucesso das tarefas
            task_success_rate = backup_success_rate  # Mesma base de dados

    except Exception as e:
        logger.warning(f"Erro ao coletar métricas do banco para health score: {e}")

    return calculate_health_score(
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
        disk_percent=disk_percent,
        installed_engines=installed_engines,
        total_engines=total_engines,
        backup_success_rate=backup_success_rate,
        total_backups=total_backups,
        total_repos=total_repos,
        active_repos=active_repos,
        task_success_rate=task_success_rate,
        total_tasks=total_tasks,
        running_tasks=running_tasks,
    )

