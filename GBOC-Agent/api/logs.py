#!/usr/bin/env python3
"""
API de Logs - Lê do banco de dados system_logs
"""

from fastapi import APIRouter, HTTPException, Query, Request
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime, timedelta

from shared_core import get_shared_core

logger = logging.getLogger("API-Logs")
router = APIRouter(prefix="/api/logs", tags=["logs"])

RETENTION_KEY = "logs_retention_days"
RETENTION_DEFAULT = 90


def _time_conditions(hours: int, start: Optional[str], end: Optional[str]):
    """Período: datas (AAAA-MM-DD, fim inclusivo) têm prioridade; hours=0 = todo o período."""
    conds, params = [], []
    if start or end:
        try:
            if start:
                conds.append("timestamp >= %s")
                params.append(datetime.strptime(start[:10], "%Y-%m-%d").isoformat())
            if end:
                conds.append("timestamp < %s")
                params.append((datetime.strptime(end[:10], "%Y-%m-%d") + timedelta(days=1)).isoformat())
        except ValueError:
            raise HTTPException(400, "Data inválida (use AAAA-MM-DD)")
    elif hours:
        conds.append("timestamp >= %s")
        params.append((datetime.now() - timedelta(hours=hours)).isoformat())
    return conds, params


@router.get("/")
def get_logs(
        level: Optional[str] = None,
        source: Optional[str] = None,
        module: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = Query(500, ge=1, le=5000),
        offset: int = Query(0, ge=0),
        hours: int = Query(24, ge=0, le=87600),
        start: Optional[str] = None,
        end: Optional[str] = None,
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
        hours: Últimas N horas (padrão: 24; 0 = todo o período)
        start/end: período por datas AAAA-MM-DD (fim inclusivo; tem prioridade sobre hours)
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
            tconds, tparams = _time_conditions(hours, start, end)
            query = "SELECT * FROM system_logs WHERE " + (" AND ".join(tconds) or "TRUE")
            params = list(tparams)

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
            count_query = "SELECT COUNT(*) FROM system_logs WHERE " + (" AND ".join(tconds) or "TRUE")
            count_params = list(tparams)

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
                    "start": start,
                    "end": end,
                    "search": search
                },
                "has_more": offset + len(logs) < total
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao buscar logs: {e}")
        return {
            "status": "error",
            "message": str(e),
            "logs": []
        }


@router.get("/stats")
def get_log_stats(hours: int = Query(24, ge=0, le=87600), start: Optional[str] = None,
                        end: Optional[str] = None) -> Dict[str, Any]:
    """Estatísticas de logs no período (hours=0 = todo o período; start/end por datas)."""
    try:
        core = get_shared_core()
        tconds, tparams = _time_conditions(hours, start, end)
        where = " AND ".join(tconds) or "TRUE"

        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            # Contar por nível
            cursor.execute("""
                SELECT level, COUNT(*) as count
                FROM system_logs
                WHERE {where}
                GROUP BY level
                ORDER BY count DESC
            """.format(where=where), tparams)

            by_level = {row[0]: row[1] for row in cursor.fetchall()}

            # Contar por fonte
            cursor.execute("""
                SELECT source, COUNT(*) as count
                FROM system_logs
                WHERE {where}
                GROUP BY source
                ORDER BY count DESC
                LIMIT 10
            """.format(where=where), tparams)

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
                WHERE {where}
                GROUP BY module
                ORDER BY count DESC
            """.format(where=where), tparams)

            by_module = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute(f"SELECT MIN(timestamp), MAX(timestamp) FROM system_logs WHERE {where}", tparams)
            oldest, newest = cursor.fetchone()

            return {
                "status": "success",
                "period_hours": hours,
                "oldest": str(oldest) if oldest else None,
                "newest": str(newest) if newest else None,
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
def clear_old_logs(days: int = Query(30, ge=1, le=365)) -> Dict[str, Any]:
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


# ───────────────────────── retenção automática ─────────────────────────
# Antes os logs do agente cresciam sem limite (só havia limpeza manual). Agora: retenção em dias
# (settings.logs_retention_days, padrão 90; 0 = manter tudo), aplicada 1x por dia.

def _get_retention() -> int:
    try:
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key = %s", (RETENTION_KEY,))
            r = cur.fetchone()
            return int(r[0]) if r and str(r[0]).strip() != "" else RETENTION_DEFAULT
    except Exception:
        return RETENTION_DEFAULT


def _set_retention(days: int) -> None:
    core = get_shared_core()
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""INSERT INTO settings (category, key, value, type, description, updated_at)
                       VALUES ('logs', %s, %s, 'int', 'Retenção dos logs do agente (dias, 0 = manter tudo)', %s)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at""",
                    (RETENTION_KEY, str(int(days)), datetime.now()))
        conn.commit()


def apply_retention(days: Optional[int] = None) -> Dict[str, Any]:
    days = _get_retention() if days is None else int(days)
    if days <= 0:
        return {"deleted": 0, "retention_days": 0}
    core = get_shared_core()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    total = 0
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        while True:      # lotes curtos para não travar a tabela
            cur.execute("DELETE FROM system_logs WHERE id IN (SELECT id FROM system_logs WHERE timestamp < %s LIMIT 20000)", (cutoff,))
            n = cur.rowcount or 0
            conn.commit()
            total += n
            if n < 20000:
                break
    if total:
        logger.info(f"Retenção de logs: {total} registro(s) com mais de {days} dia(s) removido(s)")
    return {"deleted": total, "retention_days": days}


@router.get("/retention")
async def get_retention() -> Dict[str, Any]:
    import asyncio

    def info():
        core = get_shared_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM system_logs")
            n, oldest, newest = cur.fetchone()
            try:
                cur.execute("SELECT pg_total_relation_size('system_logs')")
                size = cur.fetchone()[0]
            except Exception:
                conn.rollback()
                size = None
        return {"status": "success", "logs_retention_days": _get_retention(), "count": n,
                "oldest": str(oldest) if oldest else None, "newest": str(newest) if newest else None, "size_bytes": size}
    return await asyncio.to_thread(info)


@router.put("/retention")
async def put_retention(request: Request) -> Dict[str, Any]:
    import asyncio
    b = await request.json()
    try:
        days = int(b.get("logs_retention_days"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Informe logs_retention_days (0 = manter tudo)")
    if days < 0 or days > 3650:
        raise HTTPException(400, "Retenção deve estar entre 0 e 3650 dias")
    await asyncio.to_thread(_set_retention, days)
    return await get_retention()


@router.post("/cleanup")
async def cleanup_now() -> Dict[str, Any]:
    import asyncio
    res = await asyncio.to_thread(apply_retention)
    return {"status": "success", **res}


def start_retention_loop() -> None:
    import threading
    import time

    def loop():
        time.sleep(300)
        while True:
            try:
                apply_retention()
            except Exception as e:
                logger.warning(f"Retenção automática de logs falhou: {e}")
            time.sleep(24 * 3600)
    threading.Thread(target=loop, name="gboc-log-retention", daemon=True).start()
