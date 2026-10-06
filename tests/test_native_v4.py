"""Motor nativo formato 4: deduplicação em blocos, compressão, detecção rápida, versões, verificação e retenção."""
import os
import time
from datetime import datetime, timedelta

import pytest

from native_engine import store_v4
from native_engine.engine import GBOCNativeEngine
from storage_backends.local import LocalStorageBackend


def _engine(repo, src, **kw):
    be = LocalStorageBackend({"path": str(repo)})
    cfg = {"source_paths": [str(s) for s in (src if isinstance(src, list) else [src])]}
    cfg.update(kw.pop("cfg", {}))
    return GBOCNativeEngine(cfg, be, backend_factory=lambda: be, workers=kw.pop("workers", 2))


def _objects(repo):
    return [p for p in (repo / "objects").rglob("*") if p.is_file()] if (repo / "objects").exists() else []


@pytest.fixture
def data(tmp_path):
    src = tmp_path / "dados"
    (src / "sub").mkdir(parents=True)
    (src / "texto.txt").write_text("linha de log repetida\n" * 20000)            # muito compactável
    (src / "foto.jpg").write_bytes(os.urandom(300_000))                         # já compactado
    (src / "sub" / "copia.txt").write_text("linha de log repetida\n" * 20000)   # conteúdo idêntico
    big = os.urandom(store_v4.CHUNK_SIZE * 2 + 1234)
    (src / "grande.bin").write_bytes(big)
    return tmp_path, src


def test_backup_dedup_compression_and_fast_incremental(data):
    tmp, src = data
    repo = tmp / "repo"
    eng = _engine(repo, src)
    r1 = eng.run_backup()
    assert r1["success"] and r1["files"] == 4
    man = eng._load_manifest(r1["snapshot_id"])
    assert man["version"] == 4 and all("chunks" in e for e in man["entries"])
    # texto e cópia idênticos → 1 objeto; grande = 3 blocos; foto = 1  → 5 objetos
    assert len(_objects(repo)) == 5
    txt_obj = next(p for p in _objects(repo) if p.name == man["entries"][[e["path"] for e in man["entries"]].index("texto.txt")]["chunks"][0])
    assert txt_obj.read_bytes()[:1] in (b"S", b"Z") and txt_obj.stat().st_size < 50_000      # compactado
    jpg = next(e for e in man["entries"] if e["path"] == "foto.jpg")
    assert (repo / store_v4.object_name(jpg["chunks"][0])).read_bytes()[:1] == b"R"          # não recompacta
    assert r1["bytes_uploaded"] < r1["bytes"]

    time.sleep(1.1)
    r2 = _engine(repo, src).run_backup()                                        # nada mudou
    assert r2["success"] and r2["bytes_uploaded"] == 0 and r2["files_unchanged"] == 4

    # muda só o fim do arquivo grande → só o último bloco sobe
    with open(src / "grande.bin", "r+b") as f:
        f.seek(store_v4.CHUNK_SIZE * 2 + 10)
        f.write(b"ALTERADO")
    time.sleep(1.1)
    r3 = _engine(repo, src).run_backup()
    assert r3["objects_uploaded"] == 1 and r3["files_new"] == 1


def test_restore_versions_and_verify(data):
    tmp, src = data
    repo = tmp / "repo"
    s1 = _engine(repo, src).run_backup()["snapshot_id"]
    original = (src / "texto.txt").read_bytes()
    mtime = os.stat(src / "texto.txt").st_mtime
    (src / "texto.txt").write_text("versão nova\n")
    time.sleep(1.1)
    eng = _engine(repo, src)
    s2 = eng.run_backup()["snapshot_id"]

    out = tmp / "restaurado"
    r = eng.run_restore({"snapshot_id": s1, "destination_path": str(out)})
    assert r["success"] and r["restored"] == 4
    assert (out / "texto.txt").read_bytes() == original
    assert abs(os.stat(out / "texto.txt").st_mtime - mtime) < 0.01
    assert (out / "grande.bin").read_bytes() == (src / "grande.bin").read_bytes()

    vers = eng.file_versions("/texto.txt")
    assert [v["snapshot_id"] for v in vers] == [s2, s1] and all(v["changed"] for v in vers)
    out2 = tmp / "so_um"
    r = eng.run_restore({"snapshot_id": s1, "destination_path": str(out2), "files": ["/sub"]})
    assert r["success"] and r["restored"] == 1 and (out2 / "sub" / "copia.txt").exists()

    assert eng.verify(read_data=True)["success"]
    victim = _objects(repo)[0]
    victim.write_bytes(b"R" + b"lixo")
    v = eng.verify(read_data=True)
    assert not v["success"] and v["corrupt"]
    victim.unlink()
    v = eng.verify()
    assert not v["success"] and v["missing"]


def test_retention_gc_keeps_shared_objects(data, monkeypatch):
    from native_engine import engine as ne
    from engines import retention as ret

    class _Clock:
        t = None

        @classmethod
        def now(cls):
            return cls.t

        @staticmethod
        def strptime(*a):
            return datetime.strptime(*a)

    tmp, src = data
    repo = tmp / "repo"
    monkeypatch.setattr(ne, "datetime", _Clock)
    now = datetime.now().replace(microsecond=0)
    for d in (40, 20, 0):
        _Clock.t = now - timedelta(days=d)
        (src / "muda.txt").write_text(f"conteúdo único {d} " * 1000)
        assert _engine(repo, src).run_backup()["success"]
    monkeypatch.setattr(ne, "datetime", datetime)
    eng = _engine(repo, src)
    before = len(_objects(repo))
    res = ret.prune_native(eng, {"enabled": 1, "days": 10, "weekly": 0, "monthly": 0, "yearly": 0}, [str(src)])
    assert res["pruned"] == 2 and res["objects_deleted"] == 2          # só os 2 "muda.txt" antigos
    assert len(_objects(repo)) == before - 2
    out = tmp / "r"
    latest = eng.list_snapshots()[0]["id"]
    assert eng.run_restore({"snapshot_id": latest, "destination_path": str(out)})["success"]
    assert (out / "texto.txt").read_text().startswith("linha de log")


def test_old_format_still_restores_after_upgrade(data):
    tmp, src = data
    repo = tmp / "repo"
    old = _engine(repo, src, cfg={"format": 3}).run_backup()
    assert old["success"] and _engine(repo, src, cfg={"format": 3})._load_manifest(old["snapshot_id"])["version"] == 3
    time.sleep(1.1)
    new = _engine(repo, src).run_backup()
    assert new["success"]
    eng = _engine(repo, src)
    for sid in (old["snapshot_id"], new["snapshot_id"]):
        out = tmp / ("out_" + sid)
        r = eng.run_restore({"snapshot_id": sid, "destination_path": str(out)})
        assert r["success"], r
        assert (out / "grande.bin").read_bytes() == (src / "grande.bin").read_bytes()


def test_codec_roundtrip():
    for codec in ("zstd", "zlib", "none"):
        data = b"abc" * 10000
        assert store_v4.decompress(store_v4.compress(data, store_v4.resolve_codec(codec))) == data
    assert store_v4.resolve_codec("none") == "none"


def test_restore_wizard_options(data):
    tmp, src = data
    repo = tmp / "repo"
    eng = _engine(repo, src)
    sid = eng.run_backup()["snapshot_id"]
    out = tmp / "tudo"
    r = eng.run_restore({"snapshot_id": sid, "destination_path": str(out), "files": ["*"]})   # assistente envia "*"
    assert r["success"] and r["restored"] == 4
    out2 = tmp / "filtro"
    r = eng.run_restore({"snapshot_id": sid, "destination_path": str(out2), "files": ["*"], "options": {"file_filter": "*.txt"}})
    assert r["restored"] == 2 and not (out2 / "foto.jpg").exists()
    # local original + não sobrescrever: o que já existe fica como está
    (src / "texto.txt").write_text("editado depois do backup")
    (src / "foto.jpg").unlink()
    r = eng.run_restore({"snapshot_id": sid, "destination_path": "/", "files": ["*"], "options": {"overwrite": False}})
    assert r["success"] and (src / "foto.jpg").exists() and (src / "texto.txt").read_text() == "editado depois do backup"
    r = eng.run_restore({"snapshot_id": sid, "destination_path": "/", "files": ["/texto.txt"], "options": {"overwrite": True}})
    assert (src / "texto.txt").read_text().startswith("linha de log")


@pytest.mark.skipif(not __import__("shutil").which("restic"), reason="restic não instalado")
def test_restic_file_versions(tmp_path, monkeypatch):
    import subprocess
    from engines.real_restore_manager import RestoreManager as RealRestoreManager
    repo_dir, src = tmp_path / "repo", tmp_path / "src"
    src.mkdir()
    env = dict(os.environ, RESTIC_PASSWORD="x", RESTIC_REPOSITORY=str(repo_dir))
    subprocess.run(["restic", "init"], env=env, check=True, capture_output=True)
    for txt in ("v1", None, "v2 maior"):                 # None = arquivo não mexido entre os backups
        if txt:
            (src / "doc.txt").write_text(txt)
        subprocess.run(["restic", "backup", str(src)], env=env, check=True, capture_output=True)
        time.sleep(1.05)
    rm = RealRestoreManager.__new__(RealRestoreManager)
    monkeypatch.setattr(rm, "_load_repository", lambda _id: {"id": 1, "engine": "restic", "type": "local", "path": str(repo_dir)}, raising=False)
    monkeypatch.setattr(rm, "_get_password", lambda _r: "x", raising=False)
    monkeypatch.setattr("engines.real_restore_manager.get_engine_path_or_raise", lambda _n: "restic")
    res = rm.file_versions(1, str(src / "doc.txt"))
    assert [v["changed"] for v in res["versions"]] == [True, False, True]
    assert rm.verify_repository(1)["success"]
