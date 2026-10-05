"""
GBOC Server — resumo diário dos erros/avisos de log (agent_log_daily) e retenção de logs.

Os logs brutos (agent_logs) são apagados pela retenção (Configurações > Retenção ou Logs Globais),
mas os relatórios de eventos/erros usam o resumo diário — que é pequeno e fica guardado por mais tempo
(retention/log_aggregate_retention_days, padrão 730 dias). Assim limpar os logs não muda os relatórios.

* aggregate(): recalcula os dias recentes (logs que chegam atrasados de agentes offline) e preenche
  qualquer dia que ainda tenha logs brutos e nenhum resumo. Roda de hora em hora e antes de cada limpeza.
* cleanup(): resume e então apaga, em lotes, os logs brutos mais antigos que a retenção (0 = nunca apagar).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gboc.log_aggregates")

LEVEL_FILTER = "(level ILIKE 'err%%' OR level ILIKE 'crit%%' OR level ILIKE 'fatal%%' OR level ILIKE 'warn%%')"
RECOMPUTE_DAYS = 3
_lock = threading.Lock()
_ready = False


def _exec(sql: str, params: tuple = (), fetch: bool = True) -> List[Dict[str, Any]]:
    from modules.reports.report_schedules import _exec as ex
    return ex(sql, params, fetch)


def ensure_schema() -> None:
    global _ready
    if _ready:
        return
    _exec("""CREATE TABLE IF NOT EXISTS agent_log_daily (
                 day DATE NOT NULL,
                 agent_key VARCHAR(100) NOT NULL DEFAULT '',
                 source TEXT NOT NULL DEFAULT '',
                 level VARCHAR(20) NOT NULL,
                 count INTEGER NOT NULL,
                 last_ts TIMESTAMP,
                 sample TEXT,
                 PRIMARY KEY (day, agent_key, source, level))""", fetch=False)
    _exec("CREATE INDEX IF NOT EXISTS idx_agent_log_daily_day ON agent_log_daily (day)", fetch=False)
    _ready = True


def settings() -> Dict[str, Any]:
    rows = _exec("SELECT key, value FROM server_settings WHERE category = 'retention'")
    s = {r["key"]: r["value"] for r in rows}

    def num(k, d):
        try:
            return int(s.get(k, d))
        except (TypeError, ValueError):
            return d
    return {"logs_retention_days": num("logs_retention_days", 30),
            "log_aggregate_retention_days": num("log_aggregate_retention_days", 730),
            "last_cleanup": s.get("logs_last_cleanup"), "last_cleanup_result": s.get("logs_last_cleanup_result")}


def _set(key: str, value: Any, typ: str = "text", desc: str = "") -> None:
    _exec("""INSERT INTO server_settings (category, key, value, type, description) VALUES ('retention', %s, %s, %s, %s)
             ON CONFLICT (category, key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP""",
          (key, str(value), typ, desc), fetch=False)


def set_retention(days: int, aggregate_days: Optional[int] = None) -> Dict[str, Any]:
    if days < 0 or days > 3650:
        raise ValueError("Retenção de logs deve estar entre 0 (nunca apagar) e 3650 dias")
    _set("logs_retention_days", days, "number", "Retenção de logs (dias)")
    if aggregate_days is not None:
        if aggregate_days < 0 or aggregate_days > 3650:
            raise ValueError("Retenção do resumo deve estar entre 0 (nunca apagar) e 3650 dias")
        _set("log_aggregate_retention_days", aggregate_days, "number", "Retenção do resumo diário de erros de log (dias)")
    return settings()


def _aggregate_day(d: date) -> int:
    _exec("DELETE FROM agent_log_daily WHERE day = %s", (d,), fetch=False)
    _exec(f"""INSERT INTO agent_log_daily (day, agent_key, source, level, count, last_ts, sample)
              SELECT %s, COALESCE(agent_id, ''), COALESCE(source, ''), UPPER(COALESCE(level, '')), COUNT(*), MAX(timestamp),
                     (ARRAY_AGG(LEFT(message, 220) ORDER BY timestamp DESC))[1]
              FROM agent_logs
              WHERE timestamp >= %s AND timestamp < %s AND {LEVEL_FILTER}
              GROUP BY 2, 3, 4""", (d, datetime.combine(d, datetime.min.time()), datetime.combine(d + timedelta(days=1), datetime.min.time())),
          fetch=False)
    return 1


def aggregate(up_to: Optional[date] = None) -> Dict[str, Any]:
    """Resume os dias anteriores a hoje. Recalcula os últimos dias e preenche dias sem resumo."""
    ensure_schema()
    with _lock:
        today = date.today()
        last = min(up_to or (today - timedelta(days=1)), today - timedelta(days=1))
        raw_days = [r["d"] for r in _exec("""SELECT DISTINCT timestamp::date AS d FROM agent_logs
                                              WHERE timestamp < %s AND """ + LEVEL_FILTER, (datetime.combine(last + timedelta(days=1), datetime.min.time()),))]
        done = {r["day"] for r in _exec("SELECT DISTINCT day FROM agent_log_daily")}
        recent = {last - timedelta(days=i) for i in range(RECOMPUTE_DAYS)}
        todo = sorted(d for d in raw_days if d not in done or d in recent)
        for d in todo:
            _aggregate_day(d)
        return {"days_aggregated": len(todo)}


def _delete_raw(days: int, batch: int = 50000) -> int:
    total = 0
    while True:
        rows = _exec("""WITH del AS (DELETE FROM agent_logs WHERE ctid IN (
                            SELECT ctid FROM agent_logs WHERE timestamp < (LOCALTIMESTAMP - make_interval(days := %s)) LIMIT %s)
                          RETURNING 1) SELECT COUNT(*) AS n FROM del""", (days, batch))
        n = int(rows[0]["n"]) if rows else 0
        total += n
        if n < batch:
            return total


def cleanup(days: Optional[int] = None, by: str = "automático") -> Dict[str, Any]:
    """Resume e apaga logs brutos mais antigos que a retenção (0 = manter tudo)."""
    ensure_schema()
    st = settings()
    days = st["logs_retention_days"] if days is None else int(days)
    agg = aggregate()
    deleted = 0
    if days > 0:
        aggregate(up_to=date.today() - timedelta(days=1))
        deleted = _delete_raw(days)
    agg_days = st["log_aggregate_retention_days"]
    agg_deleted = 0
    if agg_days > 0:
        r = _exec("WITH d AS (DELETE FROM agent_log_daily WHERE day < CURRENT_DATE - %s RETURNING 1) SELECT COUNT(*) AS n FROM d", (agg_days,))
        agg_deleted = int(r[0]["n"]) if r else 0
    result = {"deleted": deleted, "retention_days": days, "aggregated_days": agg["days_aggregated"], "aggregate_rows_deleted": agg_deleted}
    _set("logs_last_cleanup", datetime.now().isoformat(sep=" ", timespec="seconds"))
    _set("logs_last_cleanup_result", f"{deleted} log(s) apagado(s) ({by}); retenção {days or 'sem limite'} dia(s)")
    if deleted:
        logger.info(f"[LOGS] Limpeza: {deleted} log(s) com mais de {days} dia(s) apagado(s) ({by})")
    return result


def overview() -> Dict[str, Any]:
    ensure_schema()
    st = settings()
    raw = _exec("SELECT COUNT(*) AS n, MIN(timestamp) AS oldest, MAX(timestamp) AS newest FROM agent_logs")[0]
    agg = _exec("SELECT MIN(day) AS oldest, MAX(day) AS newest, COUNT(DISTINCT day) AS days FROM agent_log_daily")[0]
    size = _exec("SELECT pg_total_relation_size('agent_logs') AS b")[0]["b"]
    iso = lambda v: v.isoformat(sep=" ", timespec="seconds") if isinstance(v, datetime) else (v.isoformat() if v else None)
    return {**st, "raw_count": raw["n"], "raw_oldest": iso(raw["oldest"]), "raw_newest": iso(raw["newest"]),
            "table_size_bytes": size, "aggregate_oldest": iso(agg["oldest"]), "aggregate_newest": iso(agg["newest"]),
            "aggregate_days": agg["days"]}


def coverage_start() -> Optional[datetime]:
    """Desde quando há dados de erro de log (resumo ou bruto) — para avisar nos relatórios."""
    ensure_schema()
    a = _exec("SELECT MIN(day) AS d FROM agent_log_daily")[0]["d"]
    r = _exec("SELECT MIN(timestamp) AS t FROM agent_logs")[0]["t"]
    cands = [datetime.combine(a, datetime.min.time())] if a else []
    if r:
        cands.append(r)
    return min(cands) if cands else None


def _loop() -> None:
    try:
        ensure_schema()
    except Exception as e:
        logger.warning(f"[LOGS] Tabela de resumo de logs não criada: {e}")
    time.sleep(120)
    while True:
        try:
            aggregate()
        except Exception as e:
            logger.warning(f"[LOGS] Resumo diário de logs falhou: {e}")
        time.sleep(3600)


def start_scheduler() -> None:
    threading.Thread(target=_loop, name="gboc-log-aggregates", daemon=True).start()
