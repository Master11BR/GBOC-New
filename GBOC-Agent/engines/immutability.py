"""
GBOC Agent — Backup imutável.

Dois níveis, configurados por repositório (repositories.config → "immutability"):

1. Nuvem S3/Wasabi — S3 Object Lock (proteção real contra ransomware e exclusão, inclusive por quem tem
   a senha do repositório): o bucket recebe uma retenção padrão (COMPLIANCE ou GOVERNANCE, N dias). Todo
   objeto gravado por qualquer motor (restic, Kopia, Duplicati, nativo) fica bloqueado até a data de
   retenção — nem o próprio GBOC consegue apagar. O bucket precisa ter Object Lock habilitado (Wasabi:
   na criação; AWS: na criação ou ativado num bucket com versionamento).

2. Repositório local (motor nativo e restic) — proteção local: arquivos de backup já gravados ficam
   somente leitura e, no Windows, com ACL que nega exclusão para "Todos"; o GBOC recusa apagar/limpar
   esses dados antes do prazo. Reduz muito o risco de exclusão acidental ou por scripts, mas um
   administrador do servidor ainda pode remover a proteção — para ransomware use Object Lock na nuvem.
"""
from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("gboc_immutability")

MODES = ("off", "object_lock", "local_worm")
LOCK_MODES = ("COMPLIANCE", "GOVERNANCE")
MAX_DAYS = 3650
LOCAL_ENGINES = ("gboc_native", "native", "restic")


def _core():
    from shared_core import get_shared_core
    return get_shared_core()


def _repo_row(repo_id: Any) -> Dict[str, Any]:
    with _core().get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, type, path, engine, config FROM repositories WHERE CAST(id AS TEXT) = %s", (str(repo_id),))
        r = cur.fetchone()
        cur.close()
    if not r:
        raise ValueError(f"Repositório {repo_id} não encontrado")
    cfg = {}
    try:
        cfg = json.loads(r[5]) if isinstance(r[5], str) and r[5] else (r[5] or {})
    except ValueError:
        cfg = {}
    return {"id": r[0], "name": r[1], "type": (r[2] or "local").lower(), "path": r[3] or "", "engine": (r[4] or "").lower(), "config": cfg}


def get_policy(repo: Dict[str, Any]) -> Dict[str, Any]:
    p = (repo.get("config") or {}).get("immutability") or {}
    return {"mode": p.get("mode") if p.get("mode") in MODES else "off", "days": int(p.get("days") or 0),
            "lock_mode": p.get("lock_mode") if p.get("lock_mode") in LOCK_MODES else "COMPLIANCE",
            "updated_at": p.get("updated_at"), "last_check": p.get("last_check")}


def supported_modes(repo: Dict[str, Any]) -> List[str]:
    t, e = repo["type"], repo["engine"]
    if t in ("s3", "wasabi"):
        return ["off", "object_lock"]
    if t == "local" and e in LOCAL_ENGINES:
        return ["off", "local_worm"]
    return ["off"]


def set_policy(repo_id: Any, mode: str, days: int, lock_mode: str = "COMPLIANCE") -> Dict[str, Any]:
    repo = _repo_row(repo_id)
    if mode not in MODES:
        raise ValueError("Modo inválido (off, object_lock ou local_worm)")
    if mode not in supported_modes(repo):
        raise ValueError(f"Modo '{mode}' não suportado para repositório {repo['type']}/{repo['engine']} "
                         f"(suportados: {', '.join(supported_modes(repo))})")
    days = int(days or 0)
    if mode != "off" and not (1 <= days <= MAX_DAYS):
        raise ValueError(f"Informe o período de retenção entre 1 e {MAX_DAYS} dias")
    if lock_mode not in LOCK_MODES:
        raise ValueError("Tipo de bloqueio inválido (COMPLIANCE ou GOVERNANCE)")
    cfg = dict(repo["config"])
    prev = get_policy(repo)
    cfg["immutability"] = {"mode": mode, "days": days if mode != "off" else 0, "lock_mode": lock_mode,
                           "updated_at": datetime.now().isoformat(sep=" ", timespec="seconds"), "last_check": prev.get("last_check")}
    _save_config(repo["id"], cfg)
    return get_policy({"config": cfg})


def _save_config(repo_id: Any, cfg: Dict[str, Any]) -> None:
    with _core().get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE repositories SET config = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (json.dumps(cfg, ensure_ascii=False), repo_id))
        conn.commit()
        cur.close()


def _record_check(repo: Dict[str, Any], result: Dict[str, Any]) -> None:
    try:
        cfg = dict(_repo_row(repo["id"])["config"])
        imm = dict(cfg.get("immutability") or {})
        imm["last_check"] = {"at": datetime.now().isoformat(sep=" ", timespec="seconds"), "protected": result.get("protected"),
                             "summary": result.get("summary")}
        cfg["immutability"] = imm
        _save_config(repo["id"], cfg)
    except Exception as e:
        logger.debug(f"registro da verificação: {e}")


# ───────────────────────── S3 / Wasabi (Object Lock) ─────────────────────────

def resolve_region(cfg: Dict[str, Any]) -> str:
    """Região informada; senão extraída do endpoint (s3.<região>.wasabisys.com); senão us-east-1."""
    region = str(cfg.get("region") or "").strip()
    if region:
        return region
    parts = str(cfg.get("endpoint") or "").replace("https://", "").replace("http://", "").split(".")
    if len(parts) >= 3 and parts[0] == "s3" and parts[1] not in ("wasabisys", "amazonaws"):
        return parts[1]
    return "us-east-1"


def _s3(repo: Dict[str, Any]):
    import boto3
    from botocore.config import Config
    cfg = repo["config"]
    ak = cfg.get("aws_access_key") or cfg.get("access_key")
    sk = cfg.get("aws_secret_key") or cfg.get("secret_key")
    if not sk:
        from engines import repo_secrets
        sk = repo_secrets.secret_from_config(cfg)
    if not ak or not sk:
        raise ValueError("Credenciais do bucket não configuradas no repositório")
    region = resolve_region(cfg)
    endpoint = cfg.get("endpoint") or (f"s3.{region}.wasabisys.com" if repo["type"] == "wasabi" else None)
    if endpoint and not endpoint.startswith("http"):
        endpoint = "https://" + endpoint
    return boto3.client("s3", aws_access_key_id=ak, aws_secret_access_key=sk, region_name=region, endpoint_url=endpoint,
                        config=Config(retries={"max_attempts": 3}, connect_timeout=10, read_timeout=30))


def _bucket_prefix(repo: Dict[str, Any]) -> Tuple[str, str]:
    cfg = repo["config"]
    bucket = cfg.get("bucket") or repo["path"]
    bucket = str(bucket or "").replace("s3:", "").strip("/")
    prefix = (cfg.get("prefix") or "").strip("/")
    if "/" in bucket:                       # "bucket/pasta" (formato usado pelo restic)
        bucket, rest = bucket.split("/", 1)
        prefix = (rest + "/" + prefix).strip("/") if prefix else rest
    if not bucket:
        raise ValueError("Bucket não informado no repositório")
    return bucket, prefix


def check_object_lock(repo: Dict[str, Any]) -> Dict[str, Any]:
    from botocore.exceptions import ClientError
    s3 = _s3(repo)
    bucket, prefix = _bucket_prefix(repo)
    pol = get_policy(repo)
    out: Dict[str, Any] = {"bucket": bucket, "prefix": prefix, "object_lock_enabled": False, "default_retention": None,
                           "versioning": None, "sample": None}
    try:
        v = s3.get_bucket_versioning(Bucket=bucket)
        out["versioning"] = v.get("Status") or "Desativado"
    except ClientError as e:
        out["versioning_error"] = str(e)
    try:
        c = s3.get_object_lock_configuration(Bucket=bucket).get("ObjectLockConfiguration") or {}
        out["object_lock_enabled"] = c.get("ObjectLockEnabled") == "Enabled"
        dr = (c.get("Rule") or {}).get("DefaultRetention") or {}
        if dr:
            days = dr.get("Days") or (dr.get("Years") or 0) * 365
            out["default_retention"] = {"mode": dr.get("Mode"), "days": days}
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code not in ("ObjectLockConfigurationNotFoundError",):
            out["error"] = f"{code}: {e}"
    # evidência: retenção efetiva de um objeto recente do repositório
    try:
        kw = {"Bucket": bucket, "MaxKeys": 50}
        if prefix:
            kw["Prefix"] = prefix + "/"
        objs = sorted(s3.list_objects_v2(**kw).get("Contents") or [], key=lambda o: o["LastModified"], reverse=True)
        if objs:
            h = s3.head_object(Bucket=bucket, Key=objs[0]["Key"])
            until = h.get("ObjectLockRetainUntilDate")
            out["sample"] = {"key": objs[0]["Key"], "mode": h.get("ObjectLockMode"),
                             "retain_until": until.isoformat() if until else None,
                             "locked": bool(until and until > datetime.now(timezone.utc))}
    except ClientError as e:
        out["sample_error"] = str(e)
    dr = out["default_retention"] or {}
    want = pol["days"]
    out["protected"] = bool(out["object_lock_enabled"] and dr and (not want or (dr.get("days") or 0) >= want))
    if not out["object_lock_enabled"]:
        out["summary"] = "Object Lock NÃO está habilitado neste bucket — os backups podem ser apagados."
    elif not dr:
        out["summary"] = "Object Lock habilitado, mas sem retenção padrão — aplique a retenção para proteger os novos backups."
    elif want and (dr.get("days") or 0) < want:
        out["summary"] = f"Retenção padrão de {dr.get('days')} dia(s), menor que a política ({want} dias)."
    elif out.get("sample") and not out["sample"].get("locked"):
        out["protected"] = False
        out["summary"] = ("A retenção padrão está ativa, mas o objeto mais recente do repositório NÃO está bloqueado "
                          "(gravado antes da configuração ou não aceito pelo motor). Faça um backup e verifique novamente.")
    else:
        out["summary"] = f"Protegido: retenção {dr.get('mode')} de {dr.get('days')} dia(s) em todos os novos objetos."
    return out


def apply_object_lock(repo: Dict[str, Any]) -> Dict[str, Any]:
    from botocore.exceptions import ClientError
    pol = get_policy(repo)
    if pol["mode"] != "object_lock" or not pol["days"]:
        raise ValueError("Defina a política de imutabilidade (Object Lock e dias) antes de aplicar")
    s3 = _s3(repo)
    bucket, _prefix = _bucket_prefix(repo)
    rule = {"ObjectLockEnabled": "Enabled", "Rule": {"DefaultRetention": {"Mode": pol["lock_mode"], "Days": pol["days"]}}}
    try:
        s3.put_object_lock_configuration(Bucket=bucket, ObjectLockConfiguration=rule)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("InvalidBucketState", "ObjectLockConfigurationNotFoundError", "InvalidRequest"):
            raise RuntimeError("O bucket não tem Object Lock habilitado. Crie um bucket novo com Object Lock "
                               "(Wasabi exige na criação; na AWS também é possível habilitar com versionamento ativo) "
                               f"e aponte o repositório para ele. Detalhe: {code}")
        raise RuntimeError(f"Falha ao aplicar a retenção: {code} {e}")
    return check_object_lock(repo)


def create_locked_bucket(repo: Dict[str, Any]) -> Dict[str, Any]:
    """Cria o bucket do repositório já com Object Lock (útil para novos repositórios)."""
    s3 = _s3(repo)
    bucket, _ = _bucket_prefix(repo)
    region = repo["config"].get("region") or "us-east-1"
    kw: Dict[str, Any] = {"Bucket": bucket, "ObjectLockEnabledForBucket": True}
    if region != "us-east-1" and repo["type"] == "s3":
        kw["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3.create_bucket(**kw)
    return apply_object_lock(repo)


# ───────────────────────── repositório local (proteção local) ─────────────────────────

def _local_targets(repo: Dict[str, Any]) -> List[str]:
    base = repo["path"]
    if not base or not os.path.isdir(base):
        return []
    if repo["engine"] == "restic":
        d = os.path.join(base, "data")          # packs do restic nunca são reescritos (só removidos por prune)
        return [d] if os.path.isdir(d) else []
    return [os.path.join(base, d) for d in os.listdir(base) if d.isdigit() and os.path.isdir(os.path.join(base, d))]


def _iter_files(paths: List[str]):
    for p in paths:
        for root, _dirs, files in os.walk(p):
            for fn in files:
                yield os.path.join(root, fn)


def _is_ro(path: str) -> bool:
    return not (os.stat(path).st_mode & stat.S_IWRITE)


def _win_deny_delete(folder: str, on: bool) -> bool:
    if os.name != "nt":
        return False
    try:
        if on:
            cmd = ["icacls", folder, "/deny", "*S-1-1-0:(OI)(CI)(DE,DC)", "/C", "/Q"]
        else:
            cmd = ["icacls", folder, "/remove:d", "*S-1-1-0", "/C", "/Q"]
        return subprocess.run(cmd, capture_output=True, timeout=120).returncode == 0
    except Exception as e:
        logger.debug(f"icacls: {e}")
        return False


def lock_local(repo: Dict[str, Any], max_age_days: Optional[int] = None) -> Dict[str, Any]:
    """Protege os arquivos de backup ainda dentro do período de retenção (somente leitura + ACL no Windows)."""
    pol = get_policy(repo)
    days = pol["days"] or 0
    now = datetime.now()
    locked = already = 0
    for f in _iter_files(_local_targets(repo)):
        try:
            age = (now - datetime.fromtimestamp(os.path.getmtime(f))).days
            if days and age >= days:
                continue
            if _is_ro(f):
                already += 1
            else:
                os.chmod(f, stat.S_IREAD)
                locked += 1
        except OSError as e:
            logger.debug(f"bloqueio {f}: {e}")
    acl = 0
    if os.name == "nt":
        for t in _local_targets(repo):
            if repo["engine"] != "restic":          # pastas de snapshot do motor nativo são imutáveis por completo
                acl += 1 if _win_deny_delete(t, True) else 0
    return {"locked_now": locked, "already_locked": already, "acl_folders": acl}


def unlock_expired(repo: Dict[str, Any]) -> Dict[str, Any]:
    """Remove a proteção local de arquivos que já passaram do período de retenção."""
    pol = get_policy(repo)
    if not pol["days"]:
        return {"unlocked": 0}
    now = datetime.now()
    n = 0
    for f in _iter_files(_local_targets(repo)):
        try:
            if (now - datetime.fromtimestamp(os.path.getmtime(f))).days >= pol["days"] and _is_ro(f):
                os.chmod(f, stat.S_IREAD | stat.S_IWRITE)
                n += 1
        except OSError:
            pass
    if os.name == "nt" and repo["engine"] != "restic":
        for t in _local_targets(repo):
            age = (now - datetime.fromtimestamp(os.path.getmtime(t))).days
            if age >= pol["days"]:
                _win_deny_delete(t, False)
    return {"unlocked": n}


def check_local(repo: Dict[str, Any]) -> Dict[str, Any]:
    pol = get_policy(repo)
    now = datetime.now()
    total = ro = in_ret = in_ret_ro = 0
    for f in _iter_files(_local_targets(repo)):
        try:
            total += 1
            r = _is_ro(f)
            ro += r
            if not pol["days"] or (now - datetime.fromtimestamp(os.path.getmtime(f))).days < pol["days"]:
                in_ret += 1
                in_ret_ro += r
        except OSError:
            pass
    protected = pol["mode"] == "local_worm" and in_ret > 0 and in_ret_ro == in_ret
    summary = (f"{in_ret_ro} de {in_ret} arquivo(s) dentro da retenção protegidos (somente leitura"
               + (" + ACL" if os.name == "nt" and repo["engine"] != "restic" else "") + ")."
               if in_ret else "Nenhum arquivo de backup no período de retenção.")
    return {"files": total, "read_only": ro, "in_retention": in_ret, "in_retention_protected": in_ret_ro,
            "protected": protected, "summary": summary,
            "note": "Proteção local: impede exclusão acidental/por scripts; para ransomware, use Object Lock na nuvem."}


def is_locked_path(repo_base: str, file_path: str) -> bool:
    """True se o arquivo pertence a um repositório com proteção local ativa e ainda está na retenção."""
    try:
        with _core().get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM repositories WHERE path = %s", (repo_base,))
            r = cur.fetchone()
            cur.close()
        if not r:
            return False
        repo = _repo_row(r[0])
        pol = get_policy(repo)
        if pol["mode"] != "local_worm" or not pol["days"]:
            return False
        age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(file_path))).days
        return age < pol["days"]
    except Exception:
        return False


# ───────────────────────── orquestração ─────────────────────────

def check(repo_id: Any) -> Dict[str, Any]:
    repo = _repo_row(repo_id)
    pol = get_policy(repo)
    if repo["type"] in ("s3", "wasabi"):
        res = check_object_lock(repo)
    elif repo["type"] == "local" and repo["engine"] in LOCAL_ENGINES:
        res = check_local(repo)
    else:
        res = {"protected": False, "summary": "Imutabilidade não suportada para este tipo de repositório."}
    res["policy"] = pol
    _record_check(repo, res)
    return res


def apply(repo_id: Any) -> Dict[str, Any]:
    repo = _repo_row(repo_id)
    pol = get_policy(repo)
    if pol["mode"] == "object_lock":
        res = apply_object_lock(repo)
    elif pol["mode"] == "local_worm":
        lock_local(repo)
        res = check_local(repo)
    else:
        raise ValueError("A imutabilidade está desativada neste repositório")
    res["policy"] = pol
    _record_check(repo, res)
    return res


def after_backup(repository_id: Any) -> Optional[Dict[str, Any]]:
    """Chamado após cada backup com sucesso: protege os arquivos novos (repositório local)."""
    try:
        repo = _repo_row(repository_id)
        if get_policy(repo)["mode"] != "local_worm":
            return None
        res = lock_local(repo)
        unlock_expired(repo)
        return res
    except Exception as e:
        logger.warning(f"[IMUTÁVEL] Proteção pós-backup do repositório {repository_id} falhou: {e}")
        return None


def overview() -> List[Dict[str, Any]]:
    with _core().get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM repositories WHERE COALESCE(status,'active') <> 'deleted' ORDER BY id")
        ids = [r[0] for r in cur.fetchall()]
        cur.close()
    out = []
    for i in ids:
        try:
            r = _repo_row(i)
            out.append({"id": r["id"], "name": r["name"], "type": r["type"], "engine": r["engine"],
                        "policy": get_policy(r), "supported_modes": supported_modes(r)})
        except Exception:
            continue
    return out
