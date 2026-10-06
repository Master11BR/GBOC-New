"""Regra única de status: presença dos agentes no Server e ligação Agente → Server (sem banco)."""
from datetime import datetime, timedelta


def test_server_presence_sql_uses_single_cutoff():
    from modules.agents.agent_presence import presence_sql, CUTOFF_FN, _FN_SQL
    sql = presence_sql("a.last_heartbeat")
    assert CUTOFF_FN in sql and "a.last_heartbeat IS NOT NULL" in sql and "'online'" in sql
    assert "agent_offline_threshold_minutes" in _FN_SQL and "make_interval" in _FN_SQL


def _state(**kw):
    from core.link_state import compute_link_state
    base = dict(server_url="https://srv:8000", api_key="gboc_pk_" + "x" * 40, server_auth="ok", last_heartbeat=None,
                hb_fail_at=None, websocket_connected=False, started_at=datetime.now() - timedelta(hours=1))
    base.update(kw)
    return compute_link_state(**base)


def test_agent_link_state():
    now = datetime.now()
    assert _state(api_key=None)["state"] == "not_configured"
    assert _state(server_auth="rejected")["state"] == "key_rejected"
    assert _state(last_heartbeat=now - timedelta(minutes=1))["state"] == "connected"
    # heartbeat recente, mas o último envio falhou → sem contato
    assert _state(last_heartbeat=now - timedelta(minutes=3), hb_fail_at=now)["state"] == "no_contact"
    assert _state(last_heartbeat=now - timedelta(hours=2))["state"] == "no_contact"
    assert _state(started_at=now)["state"] == "starting"
    assert _state(websocket_connected=True)["connected"] is True
