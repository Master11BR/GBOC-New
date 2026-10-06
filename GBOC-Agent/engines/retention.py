"""
GBOC Agent — aplicação da retenção das tarefas de backup.

Antes a retenção (dias / semanais / mensais / anuais) era só gravada na tarefa — nenhum motor apagava
backups antigos: o armazenamento crescia sem limite e a "retenção" das políticas centrais não tinha efeito.

Regras (iguais para todos os motores):
  * mantém TODOS os backups dos últimos `days` dias;
  * mais 1 por semana nas últimas `weekly` semanas, 1 por mês nos últimos `monthly` meses e 1 por ano nos
    últimos `yearly` anos;
  * nunca apaga o backup mais recente;
  * com backup imutável ativo no repositório, o período mínimo mantido é o da imutabilidade
    (não tenta apagar o que está bloqueado);
  * days = weekly = monthly = yearly = 0 → retenção desativada (nada é apagado).

Por motor:
  * restic      → `restic forget --keep-within Nd --keep-weekly W --keep-monthly M --keep-yearly Y --prune`
                  limitado a este host e aos caminhos da tarefa (não mexe em outras tarefas do mesmo repositório)
  * Kopia       → `kopia policy set <caminhos> --keep-daily … --keep-weekly … --keep-monthly … --keep-annual …`
                  antes do snapshot (o Kopia aplica a política ao criar o snapshot)
  * Duplicati   → `--retention-policy=ND:0s,WW:1W,MM:1M,YY:1Y` no próprio backup
  * Nativo GBOC → remove os snapshots da tarefa (manifest com os mesmos caminhos) fora da política
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set

logger = logging.getLogger("gboc.retention")


def _int(v: Any, default: int = 0) -> int:
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return default


def policy_for(task: Dict[str, Any]) -> Dict[str, int]:
    """Retenção da tarefa, já respeitando o período de imutabilidade do repositório."""
    p = {"days": _int(task.get("retention_days")), "weekly": _int(task.get("retention_weekly")),
         "monthly": _int(task.get("retention_monthly")), "yearly": _int(task.get("retention_yearly"))}
    lock = 0
    try:
        cfg = task.get("repo_config")
        cfg = json.loads(cfg) if isinstance(cfg, str) and cfg else (cfg or {})
        imm = (cfg or {}).get("immutability") or {}
        if imm.get("mode") in ("object_lock", "local_worm"):
            lock = _int(imm.get("days"))
    except (ValueError, TypeError):
        pass
    p["lock_days"] = lock
    p["enabled"] = int(any(p[k] for k in ("days", "weekly", "monthly", "yearly")))
    if p["enabled"] and lock and p["days"] < lock:
        p["days"] = lock
    return p


def select_keep(times: Dict[str, datetime], pol: Dict[str, int], now: Optional[datetime] = None) -> Set[str]:
    """Quais snapshots manter (ids) segundo a política. `times`: id → data do snapshot."""
    now = now or datetime.now()
    if not times:
        return set()
    ordered = sorted(times.items(), key=lambda kv: kv[1], reverse=True)
    keep: Set[str] = {ordered[0][0]}                                  # sempre o mais recente
    if pol.get("days"):
        limit = now - timedelta(days=pol["days"])
        keep |= {sid for sid, t in ordered if t >= limit}
    buckets = (("weekly", lambda t: t.isocalendar()[:2], lambda n: now - timedelta(weeks=n)),
               ("monthly", lambda t: (t.year, t.month), lambda n: now - timedelta(days=31 * n)),
               ("yearly", lambda t: t.year, lambda n: now - timedelta(days=366 * n)))
    for name, key, horizon in buckets:
        n = pol.get(name) or 0
        if not n:
            continue
        seen = set()
        oldest = horizon(n)
        for sid, t in ordered:                                         # mais recente de cada período
            k = key(t)
            if k in seen:
                continue
            if len(seen) >= n or t < oldest:
                break
            seen.add(k)
            keep.add(sid)
    return keep


def restic_forget_args(pol: Dict[str, int], hostname: str, paths: Iterable[str]) -> List[str]:
    args = ["forget", "--prune", "--host", hostname]
    for p in paths:
        args += ["--path", str(p)]
    if pol.get("days"):
        args += ["--keep-within", f"{pol['days']}d"]
    if pol.get("weekly"):
        args += ["--keep-weekly", str(pol["weekly"])]
    if pol.get("monthly"):
        args += ["--keep-monthly", str(pol["monthly"])]
    if pol.get("yearly"):
        args += ["--keep-yearly", str(pol["yearly"])]
    args += ["--keep-last", "1"]
    return args


def kopia_policy_args(pol: Dict[str, int]) -> List[str]:
    return ["--keep-latest", "1", "--keep-hourly", "0", "--keep-daily", str(max(pol.get("days") or 0, 1)),
            "--keep-weekly", str(pol.get("weekly") or 0), "--keep-monthly", str(pol.get("monthly") or 0),
            "--keep-annual", str(pol.get("yearly") or 0)]


def duplicati_retention_arg(pol: Dict[str, int]) -> str:
    parts = []
    if pol.get("days"):
        parts.append(f"{pol['days']}D:0s")
    if pol.get("weekly"):
        parts.append(f"{pol['weekly']}W:1W")
    if pol.get("monthly"):
        parts.append(f"{pol['monthly']}M:1M")
    if pol.get("yearly"):
        parts.append(f"{pol['yearly']}Y:1Y")
    return "--retention-policy=" + ",".join(parts)


CHAIN_MANIFEST = "manifest.chain.json"


def _norm(f: str) -> str:
    return str(f).replace("\\", "/")


def prune_native(engine, pol: Dict[str, int], source_paths: List[str]) -> Dict[str, Any]:
    """Remove snapshots do motor nativo desta tarefa (mesmos caminhos) fora da política.

    O motor nativo é incremental: um arquivo inalterado NÃO é copiado de novo — o snapshot novo aponta
    (ref_snapshot) para o anterior, em cadeia. Por isso não basta apagar a pasta do snapshot antigo:
      * arquivos .zip de snapshots removidos que ainda são usados por snapshots mantidos (desta ou de outra
        tarefa do mesmo repositório) são preservados;
      * se a cadeia de algum snapshot mantido passa pelo removido, o manifesto dele vira `manifest.chain.json`
        (some da lista de restauração, mas continua resolvendo a cadeia);
      * o restante é apagado. Snapshots só-cadeia que deixaram de ser necessários são apagados por completo.
    """
    if not pol.get("enabled"):
        return {"pruned": 0, "skipped": "retenção desativada"}
    want = sorted(str(p) for p in (source_paths or []))
    all_files = [_norm(f) for f in engine.backend.list_files()]
    by_snap: Dict[str, List[str]] = {}
    for f in all_files:
        if "/" in f:
            by_snap.setdefault(f.split("/", 1)[0], []).append(f)

    manifests: Dict[str, Dict[str, Any]] = {}     # todos os snapshots do repositório (inclusive só-cadeia)
    listed: Set[str] = set()                       # snapshots com manifest.json (restauráveis)
    for sid, files in by_snap.items():
        names = {f.split("/", 1)[1] for f in files}
        if "manifest.json" in names:
            m = engine._load_manifest(sid)
            if m:
                manifests[sid] = m
                listed.add(sid)
        elif CHAIN_MANIFEST in names:
            m = _load_chain_manifest(engine, sid)
            if m:
                manifests[sid] = m

    times: Dict[str, datetime] = {}
    for sid in listed:
        if sorted(str(p) for p in (manifests[sid].get("source_paths") or [])) != want:
            continue                                                   # snapshot de outra tarefa
        try:
            times[sid] = datetime.strptime(sid[:14], "%Y%m%d%H%M%S")
        except ValueError:
            continue
    keep = select_keep(times, pol)
    remove = {sid for sid in times if sid not in keep}

    # Snapshots que continuam valendo: os mantidos desta tarefa + todos os das outras tarefas
    roots = [sid for sid in listed if sid not in remove]
    need_files: Set[str] = set()
    need_manifests: Set[str] = set(roots)
    for sid in roots:
        for e in manifests[sid].get("entries") or []:
            if e.get("archive"):
                need_files.add(_norm(e["archive"]))
                continue
            cur, seen = e.get("ref_snapshot"), set()
            while cur and cur not in seen and cur in manifests:      # mesma busca da restauração
                seen.add(cur)
                need_manifests.add(cur)
                nxt = None
                for pe in manifests[cur].get("entries") or []:
                    if pe.get("path") == e.get("path") and pe.get("hash") == e.get("hash"):
                        if pe.get("archive"):
                            need_files.add(_norm(pe["archive"]))
                        else:
                            nxt = pe.get("ref_snapshot")
                        break
                cur = nxt

    chain_only = {sid for sid in manifests if sid not in listed}
    pruned, blocked, kept_for_chain, freed = 0, 0, 0, 0
    for sid in sorted(remove | chain_only):
        if sid in need_manifests and sid in remove:
            if not _write_chain_manifest(engine, sid, manifests[sid]):
                blocked += 1
                continue
        ok = True
        for f in by_snap.get(sid, []):
            name = f.split("/", 1)[1]
            if f in need_files or (sid in need_manifests and name == CHAIN_MANIFEST):
                continue
            if sid in need_manifests and name == "manifest.json" and sid not in remove:
                continue
            r = engine.backend.delete_file(f)
            if isinstance(r, dict) and not r.get("success", True):
                ok = False
            else:
                freed += 1
        if sid in remove:
            if ok:
                pruned += 1
                kept_for_chain += 1 if sid in need_manifests else 0
            else:
                blocked += 1
    # Formato 4: blocos deduplicados em objects/ — apaga os que nenhum snapshot restante usa
    objs_deleted = objs_blocked = 0
    obj_files = by_snap.get("objects", [])
    if obj_files and (pruned or chain_only):
        from native_engine.store_v4 import referenced_objects
        remaining = [manifests[s] for s in roots if s in manifests] + \
                    [manifests[s] for s in need_manifests if s in manifests and s not in roots]
        ref = referenced_objects(remaining)
        for f in obj_files:
            if f.rsplit("/", 1)[-1] in ref:
                continue
            r = engine.backend.delete_file(f)
            if isinstance(r, dict) and not r.get("success", True):
                objs_blocked += 1
            else:
                objs_deleted += 1
    return {"pruned": pruned, "kept": len(keep), "blocked": blocked, "chain_kept": kept_for_chain,
            "files_deleted": freed, "objects_deleted": objs_deleted, "objects_blocked": objs_blocked}


def _load_chain_manifest(engine, sid: str) -> Optional[Dict[str, Any]]:
    import os
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="gboc_chain_")
    try:
        local = os.path.join(tmp, CHAIN_MANIFEST)
        dl = engine.backend.download_file(f"{sid}/{CHAIN_MANIFEST}", local)
        if not dl.get("success", False):
            return None
        with open(local, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _write_chain_manifest(engine, sid: str, manifest: Dict[str, Any]) -> bool:
    import os
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="gboc_chain_")
    try:
        local = os.path.join(tmp, CHAIN_MANIFEST)
        with open(local, "w", encoding="utf-8") as f:
            json.dump(dict(manifest, retained_for_chain=True), f)
        r = engine.backend.upload_file(local, f"{sid}/{CHAIN_MANIFEST}")
        return bool(r.get("success", False))
    except OSError as e:
        logger.warning(f"[RETENÇÃO] manifesto de cadeia {sid}: {e}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
