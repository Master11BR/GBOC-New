"""Gráficos: períodos/agrupamento da API do Agente e componente comum idêntico no Agente e no Server."""
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_agent_period_window_and_bucket():
    from fastapi import HTTPException
    from api.advanced_stats_api import _period_window, _bucket
    s, e = _period_window(7)
    assert 6.9 < (datetime.now() - s).days + 1 <= 8 and e > datetime.now()
    s, e = _period_window(0)
    assert s.year == 1970
    s, e = _period_window(7, "2026-09-01", "2026-09-30")
    assert s == datetime(2026, 9, 1) and e == datetime(2026, 10, 1)
    with pytest.raises(HTTPException):
        _period_window(7, "01/09/2026", None)
    with pytest.raises(HTTPException):
        _period_window(7, "2026-10-01", "2026-09-01")
    now = datetime.now()
    assert _bucket("auto", now - timedelta(days=30), now) == "day"
    assert _bucket("auto", now - timedelta(days=365), now) == "week"
    assert _bucket("auto", datetime(1970, 1, 1), now) == "month"
    assert _bucket("week", now - timedelta(days=7), now) == "week"


def test_chart_component_same_everywhere():
    paths = ["GBOC-Agent/static/gboc-charts.js", "GBOC-Server/static/gboc-charts.js", "GBOC-Server/gboc-charts.js", "shared-css/gboc-charts.js"]
    digests = {hashlib.md5((ROOT / p).read_bytes()).hexdigest() for p in paths}
    assert len(digests) == 1
    js = (ROOT / paths[0]).read_text(encoding="utf-8")
    for feature in ("Período", "Formato", "Exportar CSV", "Exportar imagem PNG", "Expandir", "config.options"):
        assert feature in js
    lm = (ROOT / "GBOC-Agent/static/gboc-layout-manager.js").read_text(encoding="utf-8")
    assert "gboc-charts.js" in lm
