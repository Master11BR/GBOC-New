"""
GBOC Server — regra ÚNICA de agente online/offline.

Antes cada tela usava um critério:
  * agents.status — virava 'online' a cada heartbeat e NUNCA voltava a 'offline' quando o agente parava
    (só no "Desconectar" manual): o painel contava como online agentes parados há dias;
  * current_status — heartbeat nos últimos 60 minutos (fixo no código);
  * relatórios — configuração sync.agent_offline_threshold_minutes.
Resultado: a mesma máquina aparecia online numa aba e offline em outra.

Agora todas usam a configuração "Tempo para considerar agente offline" (sync.agent_offline_threshold_minutes):
  * online = último heartbeat dentro do limite;
  * uma rotina a cada 30 s grava esse resultado em agents.status, então quem lê a coluna também concorda.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("gboc.agent_presence")

DEFAULT_MINUTES = 10          # heartbeat padrão do agente: 2 min → 5 heartbeats perdidos
_LEGACY_DEFAULT = "60"        # valor semeado em versões anteriores (marcava offline só após 1 hora)
_cache = {"min": DEFAULT_MINUTES, "ts": 0.0}
_started = False


def _exec(sql: str, params: Any = (), fetch: bool = True):
    from modules.reports.report_schedules import _exec as ex
    return ex(sql, params, fetch)


def threshold_minutes() -> int:
    """Minutos sem heartbeat para considerar o agente offline (cache de 60 s)."""
    now = time.time()
    if now - _cache["ts"] < 60:
        return int(_cache["min"])
    val = DEFAULT_MINUTES
    try:
        rows = _exec("SELECT value FROM server_settings WHERE category='sync' AND key='agent_offline_threshold_minutes'")
        if rows and str(rows[0]["value"]).strip().isdigit():
            val = max(1, min(1440, int(str(rows[0]["value"]).strip())))
    except Exception as e:
        logger.debug(f"limite de presença: {e}")
    _cache.update(min=val, ts=now)
    return val


CUTOFF_FN = "gboc_agent_offline_cutoff()"
_FN_SQL = """CREATE OR REPLACE FUNCTION gboc_agent_offline_cutoff() RETURNS timestamp LANGUAGE sql STABLE AS $$
    SELECT LOCALTIMESTAMP - make_interval(mins => COALESCE(
        (SELECT LEAST(GREATEST(value::int, 1), 1440) FROM server_settings
          WHERE category = 'sync' AND key = 'agent_offline_threshold_minutes' AND value ~ '^[0-9]+$' LIMIT 1),
        %d))
$$"""


def ensure_function() -> bool:
    """Função SQL usada por todas as consultas de presença (limite lido da configuração a cada consulta)."""
    try:
        _exec(_FN_SQL % DEFAULT_MINUTES, (), False)
        return True
    except Exception as e:
        logger.warning(f"[PRESENÇA] função SQL não criada: {e}")
        return False


def presence_sql(column: str = "last_heartbeat") -> str:
    """Expressão SQL 'online'/'offline' com a regra única (para SELECT ... AS current_status)."""
    return f"CASE WHEN {column} IS NOT NULL AND {column} > {CUTOFF_FN} THEN 'online' ELSE 'offline' END"


def migrate_legacy_default() -> None:
    """Uma única vez: troca o padrão antigo de 60 min pelo novo (10 min). Valor alterado pelo usuário é mantido."""
    try:
        done = _exec("SELECT 1 FROM server_settings WHERE category='sync' AND key='agent_presence_migrated'")
        if done:
            return
        _exec("""UPDATE server_settings SET value=%s, description='Tempo sem heartbeat para considerar o agente offline (min)'
                 WHERE category='sync' AND key='agent_offline_threshold_minutes' AND value=%s""",
              (str(DEFAULT_MINUTES), _LEGACY_DEFAULT), False)
        _exec("""INSERT INTO server_settings (category, key, value, type, description)
                 VALUES ('sync', 'agent_presence_migrated', 'true', 'boolean', 'Regra única de presença aplicada')
                 ON CONFLICT (category, key) DO NOTHING""", (), False)
        _cache["ts"] = 0.0
    except Exception as e:
        logger.debug(f"migração do limite de presença: {e}")


def refresh_status() -> int:
    """Grava em agents.status o resultado da regra única. Retorna quantos agentes mudaram."""
    expr = presence_sql()
    rows = _exec(f"""UPDATE agents SET status = {expr}
                     WHERE COALESCE(status, '') IS DISTINCT FROM {expr} RETURNING agent_id""")
    return len(rows or [])


def start(notify: Optional[Callable[[], Any]] = None, interval: int = 30) -> None:
    """Rotina em segundo plano (idempotente)."""
    global _started
    if _started:
        return
    _started = True
    migrate_legacy_default()
    ensure_function()

    def _loop():
        while True:
            try:
                changed = refresh_status()
                if changed:
                    logger.info(f"[PRESENÇA] {changed} agente(s) mudaram de estado "
                                f"(offline após {threshold_minutes()} min sem heartbeat)")
                    if notify:
                        try:
                            notify()
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"[PRESENÇA] atualização: {e}")
            time.sleep(interval)

    threading.Thread(target=_loop, name="gboc-agent-presence", daemon=True).start()
