"""Novos recursos operacionais (sem rede/banco): atualização remota do agente, teste de restauração,
pacote do Server, marca nos relatórios e evidência de testes nos relatórios REP-09/REP-10."""
import os
import zipfile
from datetime import datetime, timedelta

import pytest

from core import agent_updater as upd
from engines import restore_test as rt
from modules.agents import fleet_ops as fo
from modules.reports import report_core as rc


# ───────── atualização remota do agente ─────────

def _make_pkg(path, files, prefix="GBOC-Agent/"):
    with zipfile.ZipFile(path, "w") as z:
        for n, data in files.items():
            z.writestr(prefix + n, data)
    return str(path)


@pytest.fixture
def agent_dir(tmp_path, monkeypatch):
    d = tmp_path / "agent"
    (d / "config").mkdir(parents=True)
    (d / "config" / "global_settings.json").write_text('{"keep": true}')
    (d / "agent_gboc.py").write_text("OLD = 1\n")
    (d / "version.py").write_text('GBOC_VERSION = "14.7.6"\n')
    monkeypatch.setattr(upd, "AGENT_DIR", str(d))
    monkeypatch.setattr(upd, "UPDATES_DIR", str(d / "updates"))
    monkeypatch.setattr(upd, "STATE_FILE", str(d / "updates" / "last_update.json"))
    monkeypatch.setattr(upd, "running_as_service", lambda: False)
    return d


def test_update_applies_code_and_preserves_local_data(agent_dir, tmp_path):
    pkg = _make_pkg(tmp_path / "p.zip", {"agent_gboc.py": "NEW = 2\n", "version.py": 'GBOC_VERSION = "14.9.0"\n',
                                         "config/global_settings.json": '{"overwritten": true}', "api/x.py": "X = 1\n",
                                         "logs/a.log": "x", "__pycache__/m.pyc": "x"})
    st = upd.apply_package(pkg, upd._sha256_file(pkg))
    assert st["to_version"] == "14.9.0" and st["files"] == 3
    assert (agent_dir / "agent_gboc.py").read_text() == "NEW = 2\n"
    assert (agent_dir / "config" / "global_settings.json").read_text() == '{"keep": true}'
    assert not (agent_dir / "logs").exists()
    upd.rollback(restart=False)
    assert (agent_dir / "agent_gboc.py").read_text() == "OLD = 1\n"


@pytest.mark.parametrize("files,msg", [
    ({"agent_gboc.py": "def x(:\n"}, "sintaxe"),
    ({"agent_gboc.py": "x = 1\n", "../evil.py": "x = 1\n"}, "inseguro"),
    ({"outro.py": "x = 1\n"}, "agent_gboc.py"),
])
def test_update_rejects_bad_packages(agent_dir, tmp_path, files, msg):
    pkg = _make_pkg(tmp_path / "bad.zip", files, prefix="")
    with pytest.raises(ValueError, match=msg):
        upd.apply_package(pkg, upd._sha256_file(pkg))
    assert (agent_dir / "agent_gboc.py").read_text() == "OLD = 1\n"


def test_update_rejects_wrong_hash(agent_dir, tmp_path):
    pkg = _make_pkg(tmp_path / "p.zip", {"agent_gboc.py": "NEW = 2\n"})
    with pytest.raises(ValueError, match="SHA-256"):
        upd.apply_package(pkg, "0" * 64)


def test_server_package_filters_and_versions(tmp_path):
    assert fo._include("api/x.py") and fo._include("static/vendor/chart.umd.min.js")
    for bad in ("config/a.json", "data/x.db", "logs/a.log", ".ruff_cache/x", "api/__pycache__/a.pyc", "tests/t.py", "x.log"):
        assert not fo._include(bad), bad
    pkg = _make_pkg(tmp_path / "p.zip", {"agent_gboc.py": "x = 1\n", "version.py": 'GBOC_VERSION = "14.8.0"\n'})
    assert fo._validate_zip(pkg) == {"files": 2, "version": "14.8.0"}
    assert fo._ver_tuple("14.7.4") < fo._ver_tuple("14.8.0") < fo._ver_tuple("v14.10.1")


# ───────── teste de restauração (auxiliares) ─────────

def test_restore_test_path_helpers(tmp_path):
    assert rt._norm("/C/Users/Ana/doc.txt") == rt._norm("C:\\Users\\Ana\\doc.txt") == "c/users/ana/doc.txt"
    d = rt._parse_time("2026-10-04T10:00:00.123456789-03:00")
    assert d is not None and d.tzinfo is None
    assert rt._parse_time("20261004101500") == datetime(2026, 10, 4, 10, 15)
    f = tmp_path / "C" / "Users" / "Ana" / "doc.txt"
    f.parent.mkdir(parents=True)
    f.write_text("x")
    assert rt._find_restored(str(tmp_path), "/C/Users/Ana/doc.txt") == str(f)
    assert rt._find_restored(str(tmp_path), "/C/Users/Ana/outro.txt") is None


def test_restore_test_walk_collects_sized_files():
    tree = {"/": [{"path": "/d", "type": "dir"}, {"path": "/vazio.txt", "type": "file", "size": 0}],
            "/d": [{"path": f"/d/f{i}", "type": "file", "size": 100 + i} for i in range(6)] + [{"path": "/d/big", "type": "file", "size": 10 ** 12}]}

    class RM:
        def list_files(self, repo, snap, path):
            return tree.get(path, [])
    import random
    c = rt._walk_candidates(RM(), 1, "s", 3, 10 ** 6, random.Random(1))
    paths = {x["path"] for x in c}
    assert paths and paths <= {f"/d/f{i}" for i in range(6)}


# ───────── marca nos relatórios ─────────

def test_branding_validation_and_render():
    assert rc.clean_branding({"primary_color": "red", "logo_data": "data:text/html;base64,PHM+"}) is None
    b = rc.clean_branding({"display_name": "Cliente Alfa", "primary_color": "#4a3aa7", "provider_name": "Nuvem Segura",
                           "logo_data": "data:image/png;base64,iVBORw0KGgo="})
    assert b and b["primary_color"] == "#4a3aa7"
    rep = {"code": "REP-01", "title": "T", "category": "C", "description": "d", "scope": "s", "kpis": [], "charts": [], "tables": [],
           "findings": [], "recommendations": [], "notes": [], "period": {"start": "2026-01-01", "end": "2026-01-02", "days": 1},
           "generated_at": "2026-01-02T00:00:00", "integrity": "x", "engine_version": "1"}
    html = rc.render_html(rep, branding=b)
    assert "--brand:#4a3aa7" in html and "Relatório preparado por Nuvem Segura" in html and "<img" in html
    assert "--brand:#2a78d6" in rc.render_html(rep)


# ───────── evidência dos testes nos relatórios ─────────

def test_restore_tests_feed_rep09_and_rep10():
    from test_report_core import MemSource, NOW

    class Src(MemSource):
        def restore_tests(self, start, end, agent_ids=None):
            return [{"agent_id": "a1", "ext_id": 1, "repository_name": "Repo", "status": "passed", "files_tested": 5, "files_ok": 5,
                     "files_hash_verified": 5, "started_at": NOW - timedelta(days=1), "duration_seconds": 12, "evidence_hash": "ab" * 32,
                     "triggered_by": "server:schedule:1"},
                    {"agent_id": "a1", "ext_id": 2, "repository_name": "Repo", "status": "failed", "files_tested": 5, "files_ok": 3,
                     "started_at": NOW - timedelta(days=2), "error_message": "2 de 5 arquivo(s) não conferiram"}]
    r9 = rc.build_report(Src(), "REP-09", days=30)
    t = r9["tables"][0]
    assert t["title"].startswith("Testes de restauração") and len(t["rows"]) == 2
    assert any("com problema" in f["text"] for f in r9["findings"])
    r10 = rc.build_report(Src(), "REP-10", days=30)
    row = next(r for r in r10["tables"][0]["rows"] if r[0] == "SRV-A")
    assert rc.cell_text(row[4]) == "✔"                       # recuperação testada (teste aprovado)
    assert rc.cell_text(row[-2]).startswith("Aprovado")      # último teste de restauração
