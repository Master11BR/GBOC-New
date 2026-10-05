"""
GBOC Agent — detalhes completos de um repositório.

details(repo_id, live=False) devolve:
  * general     — nome, motor, tipo, status, datas
  * connection  — bucket/contêiner, prefixo, região, endpoint efetivo, chave de acesso (mascarada),
                  situação da chave secreta e da senha de criptografia (nunca o valor)
  * engine      — como o motor enxerga o repositório (ex.: RESTIC_REPOSITORY)
  * immutability, usage (último tamanho medido), tasks (tarefas que gravam nele)
  * local       — para repositórios em disco: existência, espaço livre/total
  * cloud       — (live=True) configurações lidas AGORA do provedor:
                  S3/Wasabi: latência, região do bucket, versionamento, Object Lock e retenção padrão,
                  criptografia, ciclo de vida, bloqueio de acesso público, política, ACL, tags, CORS,
                  logs de acesso, replicação, objetos sob o prefixo (quantidade, tamanho, mais antigo/recente,
                  classes) e retenção do objeto mais recente.
                  B2/Azure/GCS: existência do contêiner e objetos sob o prefixo (via Libcloud).
Nenhum valor é simulado: o que o provedor não permite ler aparece como "sem permissão"/"não suportado".
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LIST_MAX_OBJECTS = 200_000
LIST_MAX_SECONDS = 25
PROVIDERS = {"local": "Local (disco)", "s3": "Amazon S3", "wasabi": "Wasabi", "b2": "Backblaze B2",
             "azure": "Azure Blob Storage", "gcs": "Google Cloud Storage", "sftp": "SFTP"}


def _core():
    from shared_core import get_shared_core
    return get_shared_core()


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    return v.isoformat(sep=" ", timespec="seconds") if hasattr(v, "isoformat") else str(v)


def _mask(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    v = str(v)
    return v[:4] + "…" + v[-4:] if len(v) > 10 else v[:2] + "…"


def _raw_row(repo_id: Any) -> Dict[str, Any]:
    with _core().get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT id, name, type, path, engine, status, enabled, initialized, created_at, updated_at,
                              config, COALESCE(motor_password, '') <> '' AS has_pwd
                       FROM repositories WHERE CAST(id AS TEXT) = %s""", (str(repo_id),))
        r = cur.fetchone()
        cur.close()
    if not r:
        raise ValueError(f"Repositório {repo_id} não encontrado")
    try:
        cfg = json.loads(r[10]) if isinstance(r[10], str) and r[10] else (r[10] or {})
    except ValueError:
        cfg = {}
    return {"id": r[0], "name": r[1], "type": (r[2] or "local").lower(), "path": r[3] or "", "engine": (r[4] or "restic").lower(),
            "status": r[5], "enabled": r[6], "initialized": r[7], "created_at": _iso(r[8]), "updated_at": _iso(r[9]),
            "config": cfg if isinstance(cfg, dict) else {}, "has_pwd": bool(r[11])}


def _rows(sql: str, params: tuple) -> List[Dict[str, Any]]:
    try:
        with _core().get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            out = [dict(zip(cols, row)) for row in cur.fetchall()]
            cur.close()
            return out
    except Exception as e:
        logger.debug(f"consulta de detalhes: {e}")
        return []


def _effective(repo: Dict[str, Any]) -> Dict[str, Any]:
    from engines.immutability import resolve_region
    cfg = repo["config"]
    t = repo["type"]
    bucket = cfg.get("bucket") or (repo["path"] if t != "local" else None)
    region = resolve_region(cfg) if t in ("s3", "wasabi") else (cfg.get("region") or None)
    endpoint = cfg.get("endpoint") or (f"s3.{region}.wasabisys.com" if t == "wasabi" else
                                       ("s3.amazonaws.com" if region in (None, "us-east-1") else f"s3.{region}.amazonaws.com")
                                       if t == "s3" else None)
    return {"bucket": bucket, "prefix": cfg.get("prefix") or None, "region": region, "endpoint": endpoint,
            "region_informed": bool(cfg.get("region"))}


def _engine_target(repo: Dict[str, Any], eff: Dict[str, Any]) -> Dict[str, Any]:
    t, engine, path = repo["type"], repo["engine"], eff.get("bucket") or repo["path"]
    out: Dict[str, Any] = {"engine": engine}
    if t == "local":
        out["target"] = repo["path"]
    elif engine == "restic":
        out["variable"] = "RESTIC_REPOSITORY"
        out["target"] = {"s3": f"s3:s3.amazonaws.com/{path}", "wasabi": f"s3:{eff.get('endpoint')}/{path}",
                         "b2": f"b2:{path}"}.get(t, path)
    elif engine == "gboc_native":
        out["target"] = f"{PROVIDERS.get(t, t)} · bucket {eff.get('bucket')}" + (f" · prefixo {eff['prefix']}" if eff.get("prefix") else "")
    else:
        out["target"] = f"{eff.get('endpoint') or PROVIDERS.get(t, t)}/{path}" + (f"/{eff['prefix']}" if eff.get("prefix") else "")
    return out


def stored(repo_id: Any) -> Dict[str, Any]:
    from engines import immutability, repo_secrets
    repo = _raw_row(repo_id)
    cfg, t = repo["config"], repo["type"]
    eff = _effective(repo)
    access = cfg.get("aws_access_key") or cfg.get("access_key") or cfg.get("b2_account_id") or cfg.get("azure_account_name") \
        or cfg.get("gcs_project_id")
    out: Dict[str, Any] = {
        "general": {"id": repo["id"], "name": repo["name"], "engine": repo["engine"], "type": t,
                    "provider": PROVIDERS.get(t, t), "status": repo["status"], "enabled": repo["enabled"],
                    "initialized": repo["initialized"], "created_at": repo["created_at"], "updated_at": repo["updated_at"]},
        "connection": {"path": repo["path"] if t == "local" else None, **({} if t == "local" else eff),
                       "access_key": _mask(access) if t != "local" else None,
                       "secret": None if t == "local" else ("salva (criptografada)" if repo_secrets.has_secret(cfg) else
                                                            "NÃO salva — o agente usa a senha do motor no lugar; informe a chave secreta em Editar"),
                       "secret_saved": repo_secrets.has_secret(cfg) if t != "local" else None,
                       "encryption_password": "definida" if repo["has_pwd"] else "não definida"},
        "engine": _engine_target(repo, eff),
        "immutability": immutability.get_policy(repo),
    }
    extra = {k: v for k, v in cfg.items() if k not in ("bucket", "region", "endpoint", "prefix", "aws_access_key", "access_key",
                                                       "b2_account_id", "azure_account_name", "gcs_project_id", "immutability",
                                                       "secret_enc") and not isinstance(v, (dict, list))
             and "secret" not in k and "password" not in k and "key" not in k}
    if extra:
        out["other_settings"] = extra
    usage = _rows("""SELECT size_bytes, snapshot_count, recorded_at FROM storage_usage_history
                     WHERE repository_id = %s ORDER BY recorded_at DESC LIMIT 1""", (repo["id"],))
    if usage:
        out["usage"] = {"size_bytes": usage[0]["size_bytes"], "snapshot_count": usage[0]["snapshot_count"],
                        "recorded_at": _iso(usage[0]["recorded_at"])}
    out["tasks"] = [{"id": r["id"], "name": r["name"], "enabled": r["enabled"], "schedule_enabled": r["schedule_enabled"],
                     "schedule_cron": r["schedule_cron"], "retention_days": r["retention_days"],
                     "last_run": _iso(r["last_run"]), "last_status": r["last_status"]}
                    for r in _rows("""SELECT id, name, enabled, schedule_enabled, schedule_cron, retention_days, last_run, last_status
                                      FROM tasks WHERE repository_id = %s ORDER BY name""", (repo["id"],))]
    if t == "local":
        p = repo["path"]
        loc: Dict[str, Any] = {"exists": bool(p) and os.path.isdir(p)}
        if loc["exists"]:
            try:
                du = shutil.disk_usage(p)
                loc.update({"disk_total_bytes": du.total, "disk_free_bytes": du.free, "disk_used_pct": round(du.used / du.total * 100, 1)})
            except OSError as e:
                loc["error"] = str(e)
            loc["writable"] = os.access(p, os.W_OK)
        out["local"] = loc
    return out


# ───────────────────────── leitura ao vivo do provedor ─────────────────────────

def _err(e: Exception) -> Dict[str, Any]:
    code = ""
    try:
        code = e.response.get("Error", {}).get("Code", "")        # botocore ClientError
    except Exception:
        pass
    absent = {"NoSuchLifecycleConfiguration", "ServerSideEncryptionConfigurationNotFoundError", "NoSuchBucketPolicy",
              "NoSuchPublicAccessBlockConfiguration", "NoSuchTagSet", "NoSuchCORSConfiguration",
              "ObjectLockConfigurationNotFoundError", "ReplicationConfigurationNotFoundError"}
    if code in absent:
        return {"configured": False}
    if code in ("AccessDenied", "AllAccessDisabled", "Forbidden", "403"):
        return {"error": "sem permissão para ler (a chave de acesso não tem esta permissão)"}
    if code in ("NotImplemented", "MethodNotAllowed", "501", "UnsupportedOperation", "XNotImplemented"):
        return {"error": "não suportado pelo provedor"}
    return {"error": f"{code or type(e).__name__}: {str(e)[:200]}"}


def _s3_live(repo: Dict[str, Any]) -> Dict[str, Any]:
    from engines.immutability import _s3, _bucket_prefix
    s3 = _s3(repo)
    bucket, prefix = _bucket_prefix(repo)
    out: Dict[str, Any] = {"bucket": bucket, "prefix": prefix or None, "endpoint": s3.meta.endpoint_url}
    t0 = time.monotonic()
    try:
        s3.head_bucket(Bucket=bucket)
        out["reachable"] = True
        out["latency_ms"] = round((time.monotonic() - t0) * 1000)
    except Exception as e:
        out["reachable"] = False
        out["error"] = _err(e).get("error") or str(e)
        return out

    def get(name, fn):
        try:
            out[name] = fn()
        except Exception as e:
            out[name] = _err(e)

    get("location", lambda: {"region": s3.get_bucket_location(Bucket=bucket).get("LocationConstraint") or "us-east-1"})
    get("versioning", lambda: (lambda v: {"status": v.get("Status") or "Nunca ativado", "mfa_delete": v.get("MFADelete") or "Desativado"})(
        s3.get_bucket_versioning(Bucket=bucket)))

    def lock():
        c = s3.get_object_lock_configuration(Bucket=bucket).get("ObjectLockConfiguration") or {}
        dr = (c.get("Rule") or {}).get("DefaultRetention") or {}
        return {"enabled": c.get("ObjectLockEnabled") == "Enabled", "default_mode": dr.get("Mode"),
                "default_days": dr.get("Days"), "default_years": dr.get("Years")}
    get("object_lock", lock)

    def enc():
        rules = s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"]
        return {"configured": True, "rules": [{"algorithm": (r.get("ApplyServerSideEncryptionByDefault") or {}).get("SSEAlgorithm"),
                                               "kms_key": (r.get("ApplyServerSideEncryptionByDefault") or {}).get("KMSMasterKeyID"),
                                               "bucket_key": r.get("BucketKeyEnabled")} for r in rules]}
    get("encryption", enc)

    def lifecycle():
        rules = s3.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules") or []
        return {"configured": True, "rules": [{
            "id": r.get("ID"), "status": r.get("Status"),
            "prefix": r.get("Prefix") if r.get("Prefix") is not None else ((r.get("Filter") or {}).get("Prefix")),
            "expiration_days": (r.get("Expiration") or {}).get("Days"),
            "noncurrent_expiration_days": (r.get("NoncurrentVersionExpiration") or {}).get("NoncurrentDays"),
            "abort_multipart_days": (r.get("AbortIncompleteMultipartUpload") or {}).get("DaysAfterInitiation"),
            "transitions": [f"{x.get('StorageClass')} após {x.get('Days')} dia(s)" for x in (r.get("Transitions") or [])]}
            for r in rules]}
    get("lifecycle", lifecycle)

    def pab():
        c = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
        return {"configured": True, **c}
    get("public_access_block", pab)
    get("policy_status", lambda: {"is_public": s3.get_bucket_policy_status(Bucket=bucket)["PolicyStatus"].get("IsPublic")})
    get("policy", lambda: {"configured": bool(s3.get_bucket_policy(Bucket=bucket).get("Policy"))})

    def acl():
        a = s3.get_bucket_acl(Bucket=bucket)
        grants = []
        for g in a.get("Grants") or []:
            gr = g.get("Grantee") or {}
            who = gr.get("DisplayName") or gr.get("URI") or gr.get("ID") or gr.get("EmailAddress") or "?"
            if isinstance(who, str) and who.startswith("http://acs.amazonaws.com/groups/global/AllUsers"):
                who = "TODOS (público)"
            grants.append(f"{who}: {g.get('Permission')}")
        return {"owner": (a.get("Owner") or {}).get("DisplayName") or (a.get("Owner") or {}).get("ID"), "grants": grants}
    get("acl", acl)
    get("tags", lambda: {"configured": True, "tags": {t["Key"]: t["Value"] for t in s3.get_bucket_tagging(Bucket=bucket).get("TagSet") or []}})
    get("cors", lambda: {"configured": True, "rules": len(s3.get_bucket_cors(Bucket=bucket).get("CORSRules") or [])})

    def logging_():
        le = s3.get_bucket_logging(Bucket=bucket).get("LoggingEnabled")
        return {"configured": bool(le), "target": f"{le.get('TargetBucket')}/{le.get('TargetPrefix') or ''}" if le else None}
    get("access_logging", logging_)

    def repl():
        r = s3.get_bucket_replication(Bucket=bucket)["ReplicationConfiguration"]
        return {"configured": True, "rules": [{"id": x.get("ID"), "status": x.get("Status"),
                                               "destination": (x.get("Destination") or {}).get("Bucket")} for x in r.get("Rules") or []]}
    get("replication", repl)

    # objetos sob o prefixo
    def objects():
        count = size = 0
        oldest = newest = None
        newest_key = None
        classes: Dict[str, int] = {}
        partial = False
        start = time.monotonic()
        kw = {"Bucket": bucket}
        if prefix:
            kw["Prefix"] = prefix + "/"
        for page in s3.get_paginator("list_objects_v2").paginate(**kw, PaginationConfig={"PageSize": 1000}):
            for o in page.get("Contents") or []:
                count += 1
                size += o.get("Size") or 0
                lm = o.get("LastModified")
                if lm and (oldest is None or lm < oldest):
                    oldest = lm
                if lm and (newest is None or lm > newest):
                    newest, newest_key = lm, o["Key"]
                sc = o.get("StorageClass") or "STANDARD"
                classes[sc] = classes.get(sc, 0) + 1
            if count >= LIST_MAX_OBJECTS or time.monotonic() - start > LIST_MAX_SECONDS:
                partial = page.get("IsTruncated", False)
                break
        res = {"count": count, "size_bytes": size, "oldest": _iso(oldest), "newest": _iso(newest),
               "storage_classes": classes, "partial": partial}
        if newest_key:
            try:
                h = s3.head_object(Bucket=bucket, Key=newest_key)
                until = h.get("ObjectLockRetainUntilDate")
                res["newest_object"] = {"key": newest_key, "encryption": h.get("ServerSideEncryption"),
                                        "lock_mode": h.get("ObjectLockMode"), "retain_until": _iso(until),
                                        "locked": bool(until and until > datetime.now(timezone.utc)),
                                        "legal_hold": h.get("ObjectLockLegalHoldStatus")}
            except Exception as e:
                res["newest_object"] = {"key": newest_key, **_err(e)}
        return res
    get("objects", objects)
    return out


def _libcloud_live(repo_id: Any, repo: Dict[str, Any]) -> Dict[str, Any]:
    rm = _core().repository_manager
    backend = rm.get_backend(int(repo_id))
    eff = _effective(repo)
    out: Dict[str, Any] = {"bucket": eff.get("bucket"), "prefix": eff.get("prefix")}
    t0 = time.monotonic()
    chk = backend.check_connection()
    out["reachable"] = bool(chk.get("success"))
    out["latency_ms"] = round((time.monotonic() - t0) * 1000)
    if not out["reachable"]:
        out["error"] = chk.get("message") or chk.get("error")
        return out
    count = size = 0
    newest = oldest = None
    partial = False
    start = time.monotonic()
    pre = (eff.get("prefix") or "").strip("/")
    for o in backend.driver.iterate_container_objects(backend.container, prefix=(pre + "/") if pre else None):
        count += 1
        size += int(o.size or 0)
        lm = (o.extra or {}).get("last_modified")
        if lm:
            oldest = lm if oldest is None or str(lm) < str(oldest) else oldest
            newest = lm if newest is None or str(lm) > str(newest) else newest
        if count >= LIST_MAX_OBJECTS or time.monotonic() - start > LIST_MAX_SECONDS:
            partial = True
            break
    out["objects"] = {"count": count, "size_bytes": size, "oldest": str(oldest) if oldest else None,
                      "newest": str(newest) if newest else None, "partial": partial}
    out["note"] = "Para este provedor são exibidos a conexão e os objetos; as demais configurações ficam no painel do provedor."
    return out


def live(repo_id: Any) -> Dict[str, Any]:
    from engines import repo_secrets
    repo = _raw_row(repo_id)
    t = repo["type"]
    if t == "local":
        return {"error": "Repositório local — não há configurações de nuvem"}
    if not repo_secrets.has_secret(repo["config"]):
        return {"error": "A chave secreta do provedor não está salva neste repositório. Informe-a em Editar e consulte novamente.",
                "secret_missing": True}
    started = datetime.now()
    try:
        data = _s3_live(repo) if t in ("s3", "wasabi") else _libcloud_live(repo_id, repo)
    except Exception as e:
        logger.warning(f"consulta ao provedor do repositório {repo_id}: {e}")
        data = {"reachable": False, "error": str(e)[:300]}
    data["checked_at"] = started.isoformat(sep=" ", timespec="seconds")
    data["duration_s"] = round((datetime.now() - started).total_seconds(), 1)
    return data


def details(repo_id: Any, include_live: bool = False) -> Dict[str, Any]:
    out = stored(repo_id)
    if include_live:
        out["cloud"] = live(repo_id)
    return out
