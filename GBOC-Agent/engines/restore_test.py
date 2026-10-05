"""
GBOC Agent — Teste de restauração automatizado (evidência de recuperabilidade).

Restaura de verdade uma amostra de arquivos do snapshot mais recente de um repositório para uma
pasta temporária e confere cada arquivo:
  * motor nativo GBOC: SHA-256 do arquivo restaurado == SHA-256 gravado no manifesto do backup;
  * demais motores: tamanho igual ao do snapshot e, quando o arquivo de origem não mudou desde
    o snapshot, SHA-256 igual ao do arquivo original.
O resultado (com a lista de arquivos, hashes e tempo de restauração = RTO observado) fica na
tabela restore_tests e segue para o Server no inventário. A pasta temporária é apagada ao final.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import shutil
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("gboc_restore_test")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS restore_tests (
    id SERIAL PRIMARY KEY,
    repository_id TEXT,
    repository_name TEXT,
    engine TEXT,
    task_id INTEGER,
    task_name TEXT,
    snapshot_id TEXT,
    snapshot_time TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    files_tested INTEGER DEFAULT 0,
    files_ok INTEGER DEFAULT 0,
    files_hash_verified INTEGER DEFAULT 0,
    bytes_restored BIGINT DEFAULT 0,
    duration_seconds DOUBLE PRECISION DEFAULT 0,
    error_message TEXT,
    evidence_hash TEXT,
    details JSONB DEFAULT '[]'::jsonb,
    triggered_by TEXT,
    started_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
    completed_at TIMESTAMP
)"""

MAX_LIST_CALLS = 60


def _core():
    from shared_core import get_shared_core
    return get_shared_core()


def ensure_table(conn) -> None:
    cur = conn.cursor()
    cur.execute(_SCHEMA)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_restore_tests_started ON restore_tests(started_at DESC)")
    conn.commit()
    cur.close()


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_time(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    s = str(v).strip().replace("Z", "")
    if "." in s:  # restic usa nanossegundos
        head, frac = s.split(".", 1)
        tz = ""
        for sep in ("+", "-"):
            if sep in frac:
                frac, tz = frac.split(sep, 1)
                tz = sep + tz
                break
        s = head + "." + frac[:6] + tz
    for cand in (s, s[:19]):
        try:
            d = datetime.fromisoformat(cand)
            if d.tzinfo is not None:
                d = d.astimezone().replace(tzinfo=None)
            return d
        except ValueError:
            continue
    try:
        return datetime.strptime(s[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _norm(p: str) -> str:
    """Normaliza caminhos de snapshot e de disco para comparação por sufixo."""
    p = str(p or "").replace("\\", "/").strip("/")
    parts = [x for x in p.split("/") if x]
    if parts and parts[0].endswith(":"):
        parts[0] = parts[0][:-1]
    return "/".join(parts).lower()


def _local_source_path(snapshot_path: str) -> Optional[str]:
    """Caminho do arquivo original no disco a partir do caminho no snapshot (restic/kopia)."""
    p = str(snapshot_path or "")
    if os.name == "nt":
        q = p.replace("\\", "/").lstrip("/")
        parts = q.split("/")
        if parts and len(parts[0]) == 1 and parts[0].isalpha():          # /C/Users/x → C:\Users\x
            return parts[0].upper() + ":\\" + "\\".join(parts[1:])
        if parts and len(parts[0]) == 2 and parts[0][1] == ":":           # C:/Users/x
            return parts[0].upper() + "\\" + "\\".join(parts[1:])
        return None
    return p if p.startswith("/") else None


def _load_task_and_repo(conn, repository_id: Any, task_id: Optional[int]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    cur = conn.cursor()
    task: Dict[str, Any] = {}
    if task_id:
        cur.execute("SELECT id, name, repository_id, source_paths FROM tasks WHERE id = %s", (task_id,))
        r = cur.fetchone()
        if not r:
            raise ValueError(f"Tarefa {task_id} não encontrada")
        task = {"id": r[0], "name": r[1], "repository_id": r[2], "source_paths": r[3]}
        if not repository_id:
            repository_id = r[2]
    if not repository_id:
        raise ValueError("Informe o repositório ou uma tarefa com repositório definido")
    cur.execute("SELECT id, name, engine FROM repositories WHERE CAST(id AS TEXT) = %s", (str(repository_id),))
    r = cur.fetchone()
    if not r:
        raise ValueError(f"Repositório {repository_id} não encontrado")
    repo = {"id": r[0], "name": r[1], "engine": r[2]}
    if not task:
        cur.execute("SELECT id, name, repository_id, source_paths FROM tasks WHERE repository_id = %s ORDER BY id LIMIT 1", (r[0],))
        t = cur.fetchone()
        if t:
            task = {"id": t[0], "name": t[1], "repository_id": t[2], "source_paths": t[3]}
    cur.close()
    return task, repo


def _latest_snapshot(snaps: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not snaps:
        return None
    return max(snaps, key=lambda s: (_parse_time(s.get("time")) or datetime.min, str(s.get("id"))))


def _native_candidates(core, repo_id: Any, snapshot_id: str, max_bytes: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from native_engine.engine import GBOCNativeEngine
    backend = core.repository_manager.get_backend(repo_id)
    eng = GBOCNativeEngine(task_config={"repository": {"id": repo_id}}, storage_backend=backend)
    manifest = eng._load_manifest(snapshot_id) or {}
    out = []
    for e in manifest.get("entries", []):
        size = int(e.get("size") or 0)
        if 0 < size <= max_bytes:
            out.append({"path": e["path"], "restore_key": e["path"], "size": size, "expected_hash": e.get("hash") or ""})
    return out, manifest


def _walk_candidates(rm, repo_id: Any, snapshot_id: str, want: int, max_bytes: int, rnd: random.Random) -> List[Dict[str, Any]]:
    """Caminhada aleatória pelas pastas do snapshot até reunir candidatos suficientes."""
    cache: Dict[str, List[Dict[str, Any]]] = {}
    calls = 0

    def ls(path: str) -> List[Dict[str, Any]]:
        nonlocal calls
        if path not in cache:
            calls += 1
            cache[path] = rm.list_files(repo_id, snapshot_id, path) or []
        return cache[path]

    found: Dict[str, Dict[str, Any]] = {}
    sized_any = False
    for _ in range(want * 6):
        path = "/"
        for _depth in range(14):
            if calls >= MAX_LIST_CALLS:
                break
            items = ls(path)
            files = [i for i in items if str(i.get("type")) in ("file", "f") and not i.get("is_dir")]
            dirs = [i for i in items if str(i.get("type")) in ("dir", "d", "directory") or i.get("is_dir")]
            for f in files:
                size = int(f.get("size") or 0)
                sized_any = sized_any or size > 0
                if size <= max_bytes:
                    found.setdefault(f["path"], {"path": f["path"], "restore_key": f["path"], "size": size, "expected_hash": ""})
            if not dirs or (files and rnd.random() < 0.5):
                break
            path = rnd.choice(dirs)["path"]
        if len(found) >= want * 3 or calls >= MAX_LIST_CALLS:
            break
    cands = list(found.values())
    if sized_any:
        cands = [c for c in cands if c["size"] > 0]
    return cands


def _find_restored(target: str, snapshot_path: str) -> Optional[str]:
    want = _norm(snapshot_path)
    best = None
    for root, _dirs, files in os.walk(target):
        for fn in files:
            full = os.path.join(root, fn)
            rel = _norm(os.path.relpath(full, target))
            if rel == want or want.endswith("/" + rel) or rel.endswith("/" + want) or rel.endswith(want):
                if best is None or len(rel) > len(_norm(os.path.relpath(best, target))):
                    best = full
    return best


def _insert(conn, row: Dict[str, Any]) -> Tuple[int, Any]:
    cur = conn.cursor()
    cur.execute("""INSERT INTO restore_tests (repository_id, repository_name, engine, task_id, task_name, triggered_by, status)
                   VALUES (%s, %s, %s, %s, %s, %s, 'running') RETURNING id, started_at""",
                (str(row["repository_id"]), row["repository_name"], row["engine"], row.get("task_id"), row.get("task_name"),
                 row.get("triggered_by")))
    rid, started = cur.fetchone()
    conn.commit()
    cur.close()
    return rid, started


def _finish(conn, rid: int, res: Dict[str, Any]) -> Any:
    cur = conn.cursor()
    cur.execute("""UPDATE restore_tests SET snapshot_id=%s, snapshot_time=%s, status=%s, files_tested=%s, files_ok=%s,
                       files_hash_verified=%s, bytes_restored=%s, duration_seconds=%s, error_message=%s, evidence_hash=%s,
                       details=%s::jsonb, completed_at=LOCALTIMESTAMP WHERE id=%s RETURNING completed_at""",
                (res.get("snapshot_id"), res.get("snapshot_time"), res["status"], res.get("files_tested", 0), res.get("files_ok", 0),
                 res.get("files_hash_verified", 0), res.get("bytes_restored", 0), res.get("duration_seconds", 0),
                 res.get("error_message"), res.get("evidence_hash"), json.dumps(res.get("details") or [], ensure_ascii=False), rid))
    done = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return done


def run_restore_test(repository_id: Any = None, task_id: Optional[int] = None, sample_size: int = 5,
                     max_file_mb: int = 100, triggered_by: str = "manual", keep_files: bool = False) -> Dict[str, Any]:
    core = _core()
    rm = getattr(core, "restore_manager", None)
    if rm is None:
        raise RuntimeError("Módulo de restauração indisponível neste agente")
    sample_size = max(1, min(50, int(sample_size or 5)))
    max_bytes = max(1, int(max_file_mb or 100)) * 1024 * 1024

    with core.get_db_connection() as conn:
        ensure_table(conn)
        task, repo = _load_task_and_repo(conn, repository_id, task_id)
        rid, started = _insert(conn, {"repository_id": repo["id"], "repository_name": repo["name"], "engine": repo["engine"],
                             "task_id": task.get("id"), "task_name": task.get("name"), "triggered_by": triggered_by})

    res: Dict[str, Any] = {"id": rid, "repository_id": repo["id"], "repository_name": repo["name"], "engine": repo["engine"],
                           "task_id": task.get("id"), "task_name": task.get("name"), "triggered_by": triggered_by,
                           "details": [], "status": "failed", "files_tested": 0, "files_ok": 0, "files_hash_verified": 0,
                           "bytes_restored": 0,
                           "started_at": started.isoformat(sep=" ", timespec="seconds") if hasattr(started, "isoformat") else str(started)}
    target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "restore_tests", f"rt_{rid}")
    t0 = time.time()
    try:
        snaps = rm.list_snapshots(repo["id"]) or []
        snap = _latest_snapshot(snaps)
        if not snap:
            raise RuntimeError("O repositório não tem nenhum snapshot para testar")
        sid = str(snap.get("full_id") or snap.get("id"))
        snap_dt = _parse_time(snap.get("time"))
        res["snapshot_id"] = sid
        res["snapshot_time"] = snap_dt.isoformat(sep=" ") if snap_dt else str(snap.get("time") or "")

        rnd = random.SystemRandom()
        if repo["engine"] == "gboc_native":
            cands, _manifest = _native_candidates(core, repo["id"], sid, max_bytes)
        else:
            cands = _walk_candidates(rm, repo["id"], sid, sample_size, max_bytes, rnd)
        if not cands:
            raise RuntimeError("Nenhum arquivo elegível no snapshot (vazio ou todos acima do limite de tamanho)")
        sample = rnd.sample(cands, min(sample_size, len(cands)))

        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        os.makedirs(target, exist_ok=True)
        t_restore = time.time()
        out = rm.restore_files(repo["id"], sid, [c["restore_key"] for c in sample], target, {"overwrite": True})
        restore_seconds = time.time() - t_restore
        if isinstance(out, dict) and str(out.get("status")) == "failed" and out.get("error_message"):
            res["error_message"] = f"Motor de restauração: {out['error_message']}"[:900]

        ok = hashed = 0
        total_bytes = 0
        for c in sample:
            item = {"path": c["path"], "expected_size": c["size"] or None}
            found = _find_restored(target, c["path"])
            if not found:
                item.update(ok=False, check="ausente", note="Arquivo não foi restaurado")
                res["details"].append(item)
                continue
            size = os.path.getsize(found)
            digest = _sha256(found)
            total_bytes += size
            item.update(restored_size=size, sha256=digest)
            if c["size"] and size != c["size"]:
                item.update(ok=False, check="tamanho", note=f"Tamanho diferente do snapshot ({size} ≠ {c['size']})")
            elif c.get("expected_hash"):
                good = digest.lower() == str(c["expected_hash"]).lower()
                item.update(ok=good, check="hash_manifesto",
                            note="SHA-256 igual ao gravado no backup" if good else "SHA-256 diferente do gravado no backup")
                hashed += 1 if good else 0
            else:
                src = _local_source_path(c["path"])
                if src and os.path.isfile(src) and snap_dt and datetime.fromtimestamp(os.path.getmtime(src)) <= snap_dt:
                    good = _sha256(src) == digest
                    item.update(ok=good, check="hash_origem",
                                note="Conteúdo idêntico ao arquivo original" if good else "Conteúdo diferente do original inalterado")
                    hashed += 1 if good else 0
                else:
                    item.update(ok=True, check="tamanho",
                                note="Tamanho confere com o snapshot" + ("; original alterado depois do backup" if src and os.path.isfile(src) else ""))
            ok += 1 if item.get("ok") else 0
            res["details"].append(item)

        res.update(files_tested=len(sample), files_ok=ok, files_hash_verified=hashed, bytes_restored=total_bytes,
                   restore_seconds=round(restore_seconds, 2))
        res["status"] = "passed" if ok == len(sample) else ("partial" if ok else "failed")
        if res["status"] != "passed" and not res.get("error_message"):
            res["error_message"] = f"{len(sample) - ok} de {len(sample)} arquivo(s) não conferiram"
    except Exception as e:
        logger.warning(f"[TESTE-RESTORE] Repositório {repo['name']}: {e}")
        # Sem nenhum arquivo testado = teste não executado (snapshot ausente, motor indisponível...);
        # "failed" fica para quando a restauração foi tentada e os arquivos não conferiram.
        res["status"] = "error" if not res.get("files_tested") else "failed"
        res["error_message"] = str(e)[:900]
    finally:
        if not keep_files:
            shutil.rmtree(target, ignore_errors=True)
    res["duration_seconds"] = round(time.time() - t0, 2)
    evidence = json.dumps({k: res.get(k) for k in ("repository_id", "snapshot_id", "status", "details")}, sort_keys=True,
                          default=str, ensure_ascii=False)
    res["evidence_hash"] = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
    with core.get_db_connection() as conn:
        done = _finish(conn, rid, res)
    res["completed_at"] = done.isoformat(sep=" ", timespec="seconds") if hasattr(done, "isoformat") else str(done)
    logger.info(f"[TESTE-RESTORE] #{rid} {repo['name']}: {res['status']} ({res.get('files_ok', 0)}/{res.get('files_tested', 0)})")
    return res


def list_restore_tests(limit: int = 50) -> List[Dict[str, Any]]:
    core = _core()
    with core.get_db_connection() as conn:
        ensure_table(conn)
        cur = conn.cursor()
        cur.execute("""SELECT id, repository_id, repository_name, engine, task_id, task_name, snapshot_id, snapshot_time, status,
                              files_tested, files_ok, files_hash_verified, bytes_restored, duration_seconds, error_message,
                              evidence_hash, details, triggered_by, started_at, completed_at
                       FROM restore_tests ORDER BY started_at DESC LIMIT %s""", (max(1, min(500, int(limit))),))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
    for r in rows:
        for k in ("started_at", "completed_at"):
            if hasattr(r.get(k), "isoformat"):
                r[k] = r[k].isoformat(sep=" ")
        if isinstance(r.get("details"), str):
            try:
                r["details"] = json.loads(r["details"])
            except ValueError:
                pass
    return rows
