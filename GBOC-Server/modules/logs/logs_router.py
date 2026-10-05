# GBOC System — Module: Server Logs Router (logs sincronizados pelos agentes)
#
# Fonte única de /api/v1/logs e /api/v1/logs/stats (as rotas antigas em server_gboc.py
# delegam para cá).
#
# Robustez:
#   * Bases PostgreSQL criadas no Windows com ENCODING SQL_ASCII/WIN1252 podem conter
#     bytes que não são UTF-8 (ex.: "Não" gravado em cp1252). Com client_encoding UTF8
#     o PostgreSQL recusa o SELECT ("invalid byte sequence") e a lista ficava VAZIA enquanto
#     as contagens (que não leem texto) funcionavam. Agora há um modo seguro que lê os
#     textos como bytes e decodifica UTF-8 → cp1252.
#   * Erros nunca são escondidos: a resposta traz "error" para a interface exibir.
#   * Consultas síncronas rodam fora do event loop.

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

try:
    from database import db_manager

    def get_db():
        return db_manager.get_connection()

    def release_db(conn):
        db_manager.release_connection(conn)
except Exception:  # pragma: no cover
    def get_db():
        return None

    def release_db(conn):
        pass

logger = logging.getLogger("gboc_logs_module")
router = APIRouter(prefix="/api/v1/logs", tags=["Logs & Auditoria"])

_COLUMNS = ("id", "agent_id", "level", "source", "message", "details", "timestamp", "agent_name")
_MAX_DETAILS = 4000
_ENCODING_ERRORS = ("invalid byte sequence", "character with byte sequence", "codec can't decode",
                    "CharacterNotInRepertoire", "UntranslatableCharacter")


def _decode(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp1252", errors="replace")
    return value


# Níveis + marcadores na mensagem (agentes antigos gravam tudo como INFO com "[ERROR]", "falha"...).
# Mesmo critério de mapLogToType() no dashboard, para filtro, contagem e cor baterem.
_MSG_MARKERS = {
    "error": ["[error]", "[critical]", "falha", "error:"],
    "warning": ["[warning]", "[warn]", "alerta", "threshold=", "[perf-slow]"],
    "success": ["[success]", "[ok]", "sucesso", "concluíd", "concluido"],
}
_LEVEL_PATTERNS = {
    "error": ["err%%", "crit%%", "fatal%%"],
    "warning": ["warn%%"],
    "success": ["succ%%"],
}


def _group_sql(group: str) -> str:
    parts = [f"COALESCE(al.level,'') ILIKE '{p}'" for p in _LEVEL_PATTERNS[group]]
    if group == "success":
        parts.append("UPPER(COALESCE(al.level,'')) = 'OK'")
    parts += [f"COALESCE(al.message,'') ILIKE '%%{m}%%'" for m in _MSG_MARKERS[group]]
    return "(" + " OR ".join(parts) + ")"


def _type_condition(t: str) -> Optional[str]:
    t = (t or "").strip().lower()
    if t == "error":
        return _group_sql("error")
    # Prioridade igual à do dashboard: erro > aviso > sucesso > info
    if t == "warning":
        return f"({_group_sql('warning')} AND NOT {_group_sql('error')})"
    if t == "success":
        return f"({_group_sql('success')} AND NOT {_group_sql('error')} AND NOT {_group_sql('warning')})"
    if t == "info":
        return f"(NOT {_group_sql('error')} AND NOT {_group_sql('warning')} AND NOT {_group_sql('success')})"
    return None


SERVER_AGENT = "__server__"          # filtro "Servidor central" (logs do próprio servidor: agent_id NULL)


def _parse_day(v: Optional[str]):
    from datetime import datetime as _dt
    if not v:
        return None
    try:
        return _dt.strptime(str(v)[:10], "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Data inválida: {v} (use AAAA-MM-DD)")


def _build_where(level, search, source, agent_id, log_type, hours, start=None, end=None,
                 tenant_id=None) -> Tuple[str, List[Any]]:
    from datetime import timedelta as _td
    conditions: List[str] = []
    params: List[Any] = []
    d_start, d_end = _parse_day(start), _parse_day(end)
    if d_start or d_end:
        if d_start:
            conditions.append("al.timestamp >= %s")
            params.append(d_start)
        if d_end:
            conditions.append("al.timestamp < %s")
            params.append(d_end + _td(days=1))
    elif hours:
        conditions.append("al.timestamp >= LOCALTIMESTAMP - make_interval(hours := %s)")
        params.append(int(hours))
    if tenant_id:
        conditions.append("al.agent_id IN (SELECT agent_id FROM agents WHERE tenant_id = %s)")
        params.append(tenant_id)
    if level:
        conditions.append("UPPER(al.level) = UPPER(%s)")
        params.append(level)
    tc = _type_condition(log_type)
    if tc:
        conditions.append(tc)
    if agent_id == SERVER_AGENT:
        conditions.append("al.agent_id IS NULL")
    elif agent_id:
        conditions.append("al.agent_id = %s")
        params.append(agent_id)
    if source:
        conditions.append("al.source ILIKE %s")
        params.append(f"%{source}%")
    if search:
        conditions.append("(al.message ILIKE %s OR al.details ILIKE %s OR al.source ILIKE %s)")
        params.extend([f"%{search}%"] * 3)
    return ("WHERE " + " AND ".join(conditions)) if conditions else "", params


def _query_logs(where: str, params: List[Any], limit: int, offset: int = 0) -> List[Dict[str, Any]]:
    import psycopg2.extensions as ext

    sql = f"""
        SELECT al.id, al.agent_id, al.level, al.source, al.message,
               LEFT(al.details, {_MAX_DETAILS}) AS details, al.timestamp,
               COALESCE(a.hostname, al.agent_id, 'Servidor central') AS agent_name
        FROM agent_logs al
        LEFT JOIN agents a ON a.agent_id = al.agent_id
        {where}
        ORDER BY al.timestamp DESC NULLS LAST, al.id DESC
        LIMIT %s OFFSET {int(offset)}
    """
    conn = get_db()
    if conn is None:
        raise RuntimeError("Banco de dados não disponível")
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql, params + [limit])
            rows = cur.fetchall()
            safe_mode = False
        except Exception as exc:
            if not any(k in str(exc) or k in type(exc).__name__ for k in _ENCODING_ERRORS):
                raise
            # Modo seguro: textos lidos como bytes e decodificados aqui
            logger.warning(f"[LOGS] Texto fora de UTF-8 na base ({exc}); usando leitura tolerante.")
            conn.rollback()
            conn.set_client_encoding("SQL_ASCII")
            cur = conn.cursor()
            ext.register_type(ext.BYTES, cur)
            cur.execute(sql, params + [limit])
            rows = cur.fetchall()
            safe_mode = True
        cur.close()
        out = []
        for r in rows:
            item = {k: _decode(v) for k, v in zip(_COLUMNS, r)}
            ts = item.get("timestamp")
            item["timestamp"] = ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts else None)
            out.append(item)
        if safe_mode:
            conn.rollback()
            conn.set_client_encoding("UTF8")
        return out
    except Exception:
        try:
            conn.rollback()
            conn.set_client_encoding("UTF8")
        except Exception:
            pass
        raise
    finally:
        release_db(conn)


def _query_stats(agent_id: Optional[str], hours: int, start=None, end=None, tenant_id=None,
                 search=None, source=None) -> Dict[str, Any]:
    conn = get_db()
    if conn is None:
        raise RuntimeError("Banco de dados não disponível")
    try:
        cur = conn.cursor()
        where, params = _build_where(None, search, source, agent_id, None, hours, start, end, tenant_id)
        # Cada linha é classificada uma única vez (antes: 4 filtros com as mesmas comparações repetidas)
        cur.execute(f"""
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE t = 'e'), COUNT(*) FILTER (WHERE t = 'w'),
                   COUNT(*) FILTER (WHERE t = 's'), COUNT(*) FILTER (WHERE t = 'i'),
                   COUNT(DISTINCT agent_id), MIN(timestamp), MAX(timestamp),
                   COUNT(*) FILTER (WHERE agent_id IS NULL)
            FROM (SELECT al.agent_id, al.timestamp,
                         CASE WHEN {_group_sql('error')} THEN 'e' WHEN {_group_sql('warning')} THEN 'w'
                              WHEN {_group_sql('success')} THEN 's' ELSE 'i' END AS t
                  FROM agent_logs al {where}) x
        """, params)
        r = cur.fetchone()
        cur.close()
        iso = lambda v: v.isoformat() if hasattr(v, "isoformat") else v
        return {"total": r[0], "errors": r[1], "warnings": r[2], "success": r[3], "info": r[4],
                "agents_with_logs": r[5], "oldest": iso(r[6]), "newest": iso(r[7]), "server_logs": r[8],
                "hours": hours, "start": start, "end": end}
    finally:
        release_db(conn)


@router.get("")
async def get_logs_list(
    level: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None, description="ID do agente ou __server__ (logs do próprio servidor)"),
    tenant_id: Optional[str] = Query(None, description="Organização/cliente"),
    type: Optional[str] = Query(None, description="success | info | warning | error (agrupa variações de nível)"),
    hours: int = Query(168, ge=0, le=24 * 3650, description="Janela em horas (0 = todo o período)"),
    start: Optional[str] = Query(None, description="Data inicial AAAA-MM-DD (substitui hours)"),
    end: Optional[str] = Query(None, description="Data final AAAA-MM-DD (inclusive)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0, le=10_000_000),
    with_total: bool = Query(False, description="Conta quantos registros atendem ao filtro"),
):
    """Logs reais dos agentes e do próprio servidor, do mais recente para o mais antigo."""
    try:
        where, params = _build_where(level, search, source, agent_id, type, hours, start, end, tenant_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"status": "error", "logs": [], "error": str(e), "message": str(e)})
    try:
        logs = await asyncio.to_thread(_query_logs, where, params, limit, offset)
        total = None
        if with_total:
            total = await asyncio.to_thread(_count, where, params)
        return JSONResponse({"status": "success", "logs": logs, "count": len(logs), "showing": len(logs),
                             "total": total if total is not None else len(logs), "matched": total, "offset": offset,
                             "has_more": (total is not None and offset + len(logs) < total) or (total is None and len(logs) == limit),
                             "filters": {"level": level, "type": type, "agent_id": agent_id, "tenant_id": tenant_id, "hours": hours,
                                         "start": start, "end": end, "search": search}})
    except Exception as e:
        logger.error(f"[LOGS] Erro ao consultar logs: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "logs": [], "count": 0,
                                                      "error": f"Erro ao consultar logs: {e}",
                                                      "message": f"Erro ao consultar logs: {e}"})


def _count(where: str, params: List[Any]) -> int:
    conn = get_db()
    if conn is None:
        raise RuntimeError("Banco de dados não disponível")
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM agent_logs al {where}", params)
        n = cur.fetchone()[0]
        cur.close()
        return int(n)
    finally:
        release_db(conn)


@router.get("/stats")
async def get_logs_stats(agent_id: Optional[str] = Query(None), tenant_id: Optional[str] = Query(None),
                         hours: int = Query(168, ge=0, le=24 * 3650), start: Optional[str] = Query(None),
                         end: Optional[str] = Query(None), search: Optional[str] = Query(None),
                         source: Optional[str] = Query(None)):
    """Contagens por tipo com os mesmos filtros da lista (período, agente/servidor, cliente, busca)."""
    try:
        stats = await asyncio.to_thread(_query_stats, agent_id, hours, start, end, tenant_id, search, source)
        return {"status": "success", **stats}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"status": "error", "error": str(e), "message": str(e)})
    except Exception as e:
        logger.error(f"[LOGS] Erro nas estatísticas: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e), "message": str(e)})


# ───────────────────────── retenção e limpeza ─────────────────────────

def _require_admin(request: Request) -> None:
    from fastapi import HTTPException
    role = str(((getattr(request.state, "user", None) or {}).get("role") or "")).lower()
    if role and role not in ("admin", "superadmin", "administrator"):
        raise HTTPException(403, "Somente administradores alteram a retenção ou apagam logs")


@router.get("/retention")
async def get_retention():
    """Retenção configurada, período disponível nos logs brutos e no resumo diário usado pelos relatórios."""
    from modules.logs import log_aggregates as la
    try:
        return {"status": "success", **(await asyncio.to_thread(la.overview))}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e), "message": str(e)})


@router.put("/retention")
async def put_retention(request: Request):
    from modules.logs import log_aggregates as la
    _require_admin(request)
    b = await request.json()
    try:
        days = int(b.get("logs_retention_days"))
        agg = b.get("log_aggregate_retention_days")
        await asyncio.to_thread(la.set_retention, days, int(agg) if agg not in (None, "") else None)
    except (TypeError, ValueError) as e:
        return JSONResponse(status_code=400, content={"status": "error", "error": str(e), "message": str(e)})
    return {"status": "success", **(await asyncio.to_thread(la.overview))}


@router.post("/cleanup")
async def post_cleanup(request: Request):
    """Resume os erros/avisos por dia (para os relatórios) e apaga os logs brutos mais antigos que a retenção."""
    from modules.logs import log_aggregates as la
    _require_admin(request)
    user = (getattr(request.state, "user", None) or {}).get("username") or "manual"
    try:
        res = await asyncio.to_thread(la.cleanup, None, f"manual por {user}")
    except Exception as e:
        logger.error(f"[LOGS] Limpeza falhou: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e), "message": str(e)})
    return {"status": "success", "result": res, **(await asyncio.to_thread(la.overview))}


@router.get("/agents/{agent_id}")
async def get_agent_logs_by_id(agent_id: str, level: Optional[str] = Query(None),
                               limit: int = Query(50, ge=1, le=500), hours: int = Query(168, ge=0, le=24 * 365)):
    """Logs de um agente específico (mesma leitura tolerante da lista principal)."""
    where, params = _build_where(level, None, None, agent_id, None, hours)
    try:
        logs = await asyncio.to_thread(_query_logs, where, params, limit)
        return {"status": "success", "logs": logs, "total": len(logs), "agent_id": agent_id}
    except Exception as e:
        logger.error(f"[LOGS] Erro ao consultar logs do agente {agent_id}: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "logs": [], "error": str(e), "message": str(e)})
