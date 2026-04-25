#!/usr/bin/env python3
"""
API de Logs - Lê do banco de dados system_logs
"""

from fastapi import APIRouter, Query
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime, timedelta

from shared_core import get_shared_core

logger = logging.getLogger("API-Logs")
router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/")
async def get_logs(
        level: Optional[str] = None,
        source: Optional[str] = None,
        module: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = Query(500, ge=1, le=5000),
        offset: int = Query(0, ge=0),
        hours: int = Query(24, ge=1, le=720)
) -> Dict[str, Any]:
    """
    Lista logs do sistema

    Args:
        level: Filtrar por nível (INFO, WARNING, ERROR, CRITICAL)
        source: Filtrar por fonte (ex: SharedCore, BackupEngine)
        module: Filtrar por módulo (backup, repository, scheduler, api, system, server, diagnostic)
        search: Buscar texto na mensagem ou detalhes
        limit: Máximo de registros
        offset: Pular N registros
        hours: Últimas N horas (padrão: 24)
    """
    try:
        core = get_shared_core()

        # Mapeamento de módulo para keywords de source
        module_keywords = {
            "backup": ["backup", "task", "engine"],
            "repository": ["repo", "storage"],
            "scheduler": ["scheduler", "cron"],
            "api": ["api", "route"],
            "system": ["system", "core", "shared"],
            "server": ["server", "sync", "websocket"],
            "diagnostic": ["diagnostic", "stats", "preemptive"]
        }

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM system_logs WHERE timestamp >= %s"
            params = [(datetime.now() - timedelta(hours=hours)).isoformat()]

            if level:
                query += " AND level = %s"
                params.append(level.upper())

            if source:
                query += " AND source LIKE %s"
                params.append(f"%{source}%")

            if module and module in module_keywords:
                kw = module_keywords[module]
                conditions = " OR ".join(["source ILIKE %s" for _ in kw])
                query += f" AND ({conditions})"
                params.extend([f"%{k}%" for k in kw])

            if search:
                query += " AND (message LIKE %s OR details LIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])

            query += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cursor.execute(query, params)
            columns = [desc[0] for desc in cursor.description]
            logs = [dict(zip(columns, row)) for row in cursor.fetchall()]

            # Contar total
            count_query = "SELECT COUNT(*) FROM system_logs WHERE timestamp >= %s"
            count_params = [(datetime.now() - timedelta(hours=hours)).isoformat()]

            if level:
                count_query += " AND level = %s"
                count_params.append(level.upper())

            if source:
                count_query += " AND source LIKE %s"
                count_params.append(f"%{source}%")

            if module and module in module_keywords:
                kw = module_keywords[module]
                conditions = " OR ".join(["source ILIKE %s" for _ in kw])
                count_query += f" AND ({conditions})"
                count_params.extend([f"%{k}%" for k in kw])

            if search:
                count_query += " AND (message LIKE %s OR details LIKE %s)"
                count_params.extend([f"%{search}%", f"%{search}%"])

            cursor.execute(count_query, count_params)
            total = cursor.fetchone()[0]

            return {
                "status": "success",
                "logs": logs,
                "total": total,
                "showing": len(logs),
                "filters": {
                    "level": level,
                    "source": source,
                    "module": module,
                    "hours": hours,
                    "search": search
                }
            }

    except Exception as e:
        logger.error(f"Erro ao buscar logs: {e}")
        return {
            "status": "error",
            "message": str(e),
            "logs": []
        }


@router.get("/stats")
async def get_log_stats(hours: int = Query(24, ge=1, le=720)) -> Dict[str, Any]:
    """Estatísticas de logs"""
    try:
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            since = (datetime.now() - timedelta(hours=hours)).isoformat()

            # Contar por nível
            cursor.execute("""
                SELECT level, COUNT(*) as count
                FROM system_logs
                WHERE timestamp >= %s
                GROUP BY level
                ORDER BY count DESC
            """, (since,))

            by_level = {row[0]: row[1] for row in cursor.fetchall()}

            # Contar por fonte
            cursor.execute("""
                SELECT source, COUNT(*) as count
                FROM system_logs
                WHERE timestamp >= %s
                GROUP BY source
                ORDER BY count DESC
                LIMIT 10
            """, (since,))

            by_source = {row[0]: row[1] for row in cursor.fetchall()}

            # Contar por módulo (extrair módulo do source)
            cursor.execute("""
                SELECT 
                    CASE 
                        WHEN source ILIKE '%%backup%%' OR source ILIKE '%%task%%' OR source ILIKE '%%engine%%' THEN 'Backup'
                        WHEN source ILIKE '%%repo%%' OR source ILIKE '%%storage%%' THEN 'Repositório'
                        WHEN source ILIKE '%%scheduler%%' OR source ILIKE '%%cron%%' THEN 'Agendamento'
                        WHEN source ILIKE '%%api%%' OR source ILIKE '%%route%%' THEN 'API'
                        WHEN source ILIKE '%%system%%' OR source ILIKE '%%core%%' OR source ILIKE '%%shared%%' THEN 'Sistema'
                        WHEN source ILIKE '%%server%%' OR source ILIKE '%%sync%%' OR source ILIKE '%%websocket%%' THEN 'Servidor'
                        WHEN source ILIKE '%%diagnostic%%' OR source ILIKE '%%stats%%' OR source ILIKE '%%preemptive%%' THEN 'Diagnóstico'
                        ELSE 'Outro'
                    END as module,
                    COUNT(*) as count
                FROM system_logs
                WHERE timestamp >= %s
                GROUP BY module
                ORDER BY count DESC
            """, (since,))

            by_module = {row[0]: row[1] for row in cursor.fetchall()}

            return {
                "status": "success",
                "period_hours": hours,
                "by_level": by_level,
                "by_source": by_source,
                "by_module": by_module,
                "total": sum(by_level.values())
            }

    except Exception as e:
        logger.error(f"Erro ao buscar estatísticas: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/modules")
async def get_log_modules() -> Dict[str, Any]:
    """Lista módulos disponíveis para filtro"""
    return {
        "status": "success",
        "modules": [
            {"id": "backup", "name": "Backup", "keywords": ["backup", "task", "engine"]},
            {"id": "repository", "name": "Repositório", "keywords": ["repo", "storage"]},
            {"id": "scheduler", "name": "Agendamento", "keywords": ["scheduler", "cron"]},
            {"id": "api", "name": "API", "keywords": ["api", "route"]},
            {"id": "system", "name": "Sistema", "keywords": ["system", "core", "shared"]},
            {"id": "server", "name": "Servidor", "keywords": ["server", "sync", "websocket"]},
            {"id": "diagnostic", "name": "Diagnóstico", "keywords": ["diagnostic", "stats", "preemptive"]}
        ]
    }


@router.post("/clear")
async def clear_old_logs(days: int = Query(30, ge=1, le=365)) -> Dict[str, Any]:
    """
    Limpa logs antigos

    Args:
        days: Manter apenas logs dos últimos N dias
    """
    try:
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

            cursor.execute("""
                DELETE FROM system_logs
                WHERE timestamp < %s
            """, (cutoff,))

            deleted = cursor.rowcount
            conn.commit()

            logger.info(f"Limpeza de logs: {deleted} registros removidos (> {days} dias)")

            return {
                "status": "success",
                "deleted": deleted,
                "kept_days": days
            }

    except Exception as e:
        logger.error(f"Erro ao limpar logs: {e}")
        return {"status": "error", "message": str(e)}
