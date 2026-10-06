"""Logs no Server: classificação gravada (coluna kind) e deduplicação do /sync/logs usando índice."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "GBOC-Server"))


def test_type_filter_uses_stored_kind_with_fallback():
    from modules.logs import logs_router as r
    for t, code in (("error", "e"), ("warning", "w"), ("success", "s"), ("info", "i")):
        cond = r._type_condition(t)
        assert cond.startswith("COALESCE(al.kind, CASE") and cond.endswith(f"= '{code}'")
    assert r._type_condition("") is None
    # mesma prioridade do dashboard: erro antes de aviso antes de sucesso
    case = r.kind_case("v")
    assert case.index("'e'") < case.index("'w'") < case.index("'s'") < case.index("'i'")
    assert "al." not in case and "v.message" in case


def test_sync_logs_dedup_is_index_friendly():
    src = (ROOT / "GBOC-Server/server_gboc.py").read_text(encoding="utf-8")
    body = src[src.index("async def sync_logs"):src.index('@app.post("/api/v1/sync/push")')]
    sql = body[body.index("INSERT INTO agent_logs"):]
    assert "IS NOT DISTINCT FROM" not in sql
    assert re.search(r"l\.agent_id = v\.agent_id AND l\.timestamp = v\.ts", sql)
    assert "DISTINCT ON" in sql and "statement_timeout" in body
