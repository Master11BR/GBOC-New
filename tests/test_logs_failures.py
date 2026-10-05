"""Logs Globais (filtros/período), logs do próprio servidor e central de falhas (sem banco)."""
import logging

import pytest


def test_logs_where_period_server_and_tenant():
    from modules.logs.logs_router import _build_where
    w, p = _build_where(None, None, None, "__server__", None, 0, "2026-09-01", "2026-09-30", "org1")
    assert "al.agent_id IS NULL" in w and "tenant_id = %s" in w and "make_interval" not in w
    assert p[0].day == 1 and p[1].day == 1 and p[1].month == 10        # fim inclusivo → < dia seguinte
    w, p = _build_where(None, None, None, None, None, 0)
    assert w == "" and p == []                                         # todo o período
    w, p = _build_where(None, None, None, "a1", "error", 168)
    assert "make_interval" in w and "al.agent_id = %s" in w
    with pytest.raises(ValueError):
        _build_where(None, None, None, None, None, 0, "01/09/2026")


def test_server_log_sink_dedupes_and_ignores_recursion():
    from modules.logs import server_log_sink as sink
    while not sink._QUEUE.empty():
        sink._QUEUE.get_nowait()
    h = sink.ServerDBLogHandler(logging.WARNING)
    lg = logging.getLogger("gboc.teste_sink")
    rec = lambda msg: lg.makeRecord(lg.name, logging.ERROR, __file__, 1, msg, (), None)
    h.emit(rec("Falha X"))
    h.emit(rec("Falha X"))                       # repetida em < 60 s: agrupada
    h.emit(rec("Falha Y"))
    h.emit(logging.getLogger("uvicorn.access").makeRecord("uvicorn.access", logging.ERROR, __file__, 1, "GET /", (), None))
    items = [sink._QUEUE.get_nowait() for _ in range(sink._QUEUE.qsize())]
    assert [i[2] for i in items] == ["Falha X", "Falha Y"]
    assert items[0][0] == "ERROR" and items[0][1] == "server.gboc.teste_sink"
    sink._LOCAL.busy = True                      # gravando: não pode gerar novos registros
    h.emit(rec("durante gravação"))
    sink._LOCAL.busy = False
    assert sink._QUEUE.empty()


def test_alert_event_severity():
    from modules.alerts.alerts_router import _event_sev
    assert _event_sev("alert_critical") == "critical" and _event_sev("backup_failure") == "critical"
    assert _event_sev("warning") == "warning" and _event_sev("info") == "info" and _event_sev("error") == "error"


def test_rejection_batching(monkeypatch):
    from modules.job_alert import failures as fl
    flushed = []
    monkeypatch.setattr(fl, "_flush_rejections", lambda b: flushed.append(b))
    monkeypatch.setattr(fl, "_rej_last_flush", 0.0)
    fl._rej_pending.clear()
    fl.note_rejection("ag1", "10.0.0.5", "/api/v1/agents/heartbeat")       # 1ª: grava
    fl.note_rejection("ag1", "10.0.0.5", "/api/v1/agents/heartbeat")       # < 30 s: acumula
    import time
    time.sleep(0.1)
    assert flushed and flushed[0][("ag1", "10.0.0.5")]["count"] == 1
    assert fl._rej_pending[("ag1", "10.0.0.5")]["count"] == 1


def test_agent_logs_period_conditions():
    from fastapi import HTTPException
    from api.logs import _time_conditions
    assert _time_conditions(0, None, None) == ([], [])                       # todo o período
    c, p = _time_conditions(24, None, None)
    assert c == ["timestamp >= %s"] and len(p) == 1
    c, p = _time_conditions(24, "2026-09-01", "2026-09-30")                  # datas têm prioridade
    assert c == ["timestamp >= %s", "timestamp < %s"] and p[1].startswith("2026-10-01")
    with pytest.raises(HTTPException):
        _time_conditions(0, "01/09/2026", None)
