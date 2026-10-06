"""Retenção das tarefas aplicada de verdade (restic real e motor nativo incremental), sem banco."""
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta

import pytest

from engines import retention as ret


def test_policy_respects_immutability_and_disabled():
    t = {"retention_days": 7, "retention_weekly": 4, "retention_monthly": 0, "retention_yearly": 0,
         "repo_config": json.dumps({"immutability": {"mode": "object_lock", "days": 30}})}
    p = ret.policy_for(t)
    assert p["days"] == 30 and p["lock_days"] == 30 and p["enabled"]
    assert not ret.policy_for({"retention_days": 0})["enabled"]
    assert ret.duplicati_retention_arg({"days": 7, "weekly": 4}) == "--retention-policy=7D:0s,4W:1W"


def test_select_keep_buckets():
    now = datetime(2026, 10, 5, 12)
    times = {f"s{i}": now - timedelta(days=i * 3) for i in range(40)}       # um a cada 3 dias, 117 dias
    keep = ret.select_keep(times, {"days": 10, "weekly": 4, "monthly": 3, "yearly": 0}, now)
    assert {"s0", "s1", "s2", "s3"} <= keep                                  # últimos 10 dias
    assert "s39" not in keep and len(keep) < 15


# ───────── restic real ─────────

def _restic(env, *a):
    return subprocess.run(["restic", *a], env=env, capture_output=True, text=True, check=True)


@pytest.mark.skipif(not shutil.which("restic"), reason="restic não instalado")
def test_restic_forget_only_this_task(tmp_path):
    from engines.task_manager import TaskManager
    env = dict(os.environ, RESTIC_PASSWORD="senha-teste", RESTIC_REPOSITORY=str(tmp_path / "repo"))
    a, b = tmp_path / "origem_a", tmp_path / "origem_b"
    a.mkdir(); b.mkdir()
    _restic(env, "init")
    base = datetime.now()
    for d in (60, 40, 20, 5, 1, 0):
        (a / "f.txt").write_text(str(d))
        _restic(env, "backup", str(a), "--time", (base - timedelta(days=d)).strftime("%Y-%m-%d %H:%M:%S"))
    _restic(env, "backup", str(b), "--time", (base - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S"))
    tm = TaskManager.__new__(TaskManager)
    task = {"retention_days": 10, "retention_weekly": 0, "retention_monthly": 0, "retention_yearly": 0}
    res = tm._restic_retention("restic", env, task, [str(a)])
    assert res == {"success": True, "removed": 3}
    snaps = json.loads(_restic(env, "snapshots", "--json").stdout)
    assert sorted(len(s["paths"]) and s["paths"][0] for s in snaps).count(str(a)) == 3
    assert any(s["paths"] == [str(b)] for s in snaps)                        # outra tarefa intacta
    _restic(env, "check")                                                     # repositório íntegro após o prune


# ───────── motor nativo (incremental em cadeia) ─────────

class _Clock:
    t = None

    @classmethod
    def now(cls):
        return cls.t

    @staticmethod
    def strptime(*a):
        return datetime.strptime(*a)


def test_native_prune_keeps_incremental_chain(tmp_path, monkeypatch):
    from native_engine import engine as ne
    from native_engine.engine import GBOCNativeEngine
    from storage_backends.local import LocalStorageBackend
    monkeypatch.setattr(ne, "datetime", _Clock)
    src = tmp_path / "dados"
    src.mkdir()
    (src / "fixo.txt").write_text("nunca muda")
    backend = LocalStorageBackend({"path": str(tmp_path / "repo")})
    eng = GBOCNativeEngine({"source_paths": [str(src)], "format": 3}, backend)   # formato antigo (cadeia)
    now = datetime.now().replace(microsecond=0)
    for d in (40, 20, 10, 1, 0):
        _Clock.t = now - timedelta(days=d)
        (src / "muda.txt").write_text(f"versão {d}")
        assert eng.run_backup()["success"]
    monkeypatch.setattr(ne, "datetime", datetime)
    first = (now - timedelta(days=40)).strftime("%Y%m%d%H%M%S")
    res = ret.prune_native(eng, {"enabled": 1, "days": 15, "weekly": 0, "monthly": 0, "yearly": 0}, [str(src)])
    assert res["pruned"] == 2 and res["blocked"] == 0 and res["chain_kept"] == 2
    files = backend.list_files()
    assert all("\\" not in f for f in files)
    assert f"{first}/fixo.txt.zip" in files and f"{first}/muda.txt.zip" not in files
    assert f"{first}/manifest.chain.json" in files and f"{first}/manifest.json" not in files
    assert len(eng.list_snapshots()) == 3
    out = tmp_path / "restaurado"
    latest = eng.list_snapshots()[0]["id"]
    r = eng.run_restore({"snapshot_id": latest, "destination_path": str(out)})
    assert r["success"], r
    got = {p.name: p.read_text() for p in out.rglob("*.txt")}
    assert got == {"fixo.txt": "nunca muda", "muda.txt": "versão 0"}
    # Nova execução: nada mais a remover e a cadeia continua válida
    res2 = ret.prune_native(eng, {"enabled": 1, "days": 15, "weekly": 0, "monthly": 0, "yearly": 0}, [str(src)])
    assert res2["pruned"] == 0 and f"{first}/fixo.txt.zip" in backend.list_files()
