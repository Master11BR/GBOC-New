"""Imutabilidade, janela/banda, políticas, inscrição, licença, faturamento e portal (sem banco/rede)."""
import os
import stat
from datetime import date, datetime

import pytest

from engines import immutability as imm
from engines import operation_settings as ops


# ───────── janela de manutenção e banda ─────────

def test_windows_overnight_and_validation():
    w = ops.validate_windows([{"days": [4], "start": "22:00", "end": "06:00"}])[0]     # sexta 22h → sábado 6h
    assert ops._active(w, datetime(2026, 10, 9, 23, 0))        # sexta 23h
    assert ops._active(w, datetime(2026, 10, 10, 5, 59))       # sábado 5h59
    assert not ops._active(w, datetime(2026, 10, 10, 6, 0))
    assert not ops._active(w, datetime(2026, 10, 8, 23, 0))    # quinta
    with pytest.raises(ValueError):
        ops.validate_windows([{"days": [9], "start": "25:00", "end": "x"}])
    assert ops.mbps_to_kib(8) == 976 and ops.mbps_to_kib(0) == 0


def test_throttled_reader_limits_rate(tmp_path):
    import io
    import time
    data = io.BytesIO(b"x" * 200_000)
    t0 = time.monotonic()
    out = b"".join(ops.ThrottledReader(data, 1_000_000))       # 1 MB/s → ~0,2 s
    assert len(out) == 200_000 and time.monotonic() - t0 >= 0.15


# ───────── backup imutável ─────────

def _local_repo(tmp_path, days=30):
    snap = tmp_path / "20261001120000"
    snap.mkdir()
    for i in range(3):
        (snap / f"f{i}.zip").write_bytes(b"data")
    return {"id": 1, "name": "Local", "type": "local", "path": str(tmp_path), "engine": "gboc_native",
            "config": {"immutability": {"mode": "local_worm", "days": days}}}


def test_local_worm_lock_check_and_delete_guard(tmp_path):
    repo = _local_repo(tmp_path)
    assert imm.supported_modes(repo) == ["off", "local_worm"]
    assert not imm.check_local(repo)["protected"]
    r = imm.lock_local(repo)
    assert r["locked_now"] == 3
    st = imm.check_local(repo)
    assert st["protected"] and st["in_retention_protected"] == 3
    from storage_backends.local import LocalStorageBackend
    be = LocalStorageBackend({"path": str(tmp_path)})
    res = be.delete_file("20261001120000/f0.zip")
    assert res["success"] is False and "imutável" in res["error"]
    old = 1_600_000_000                                       # arquivo além da retenção → liberado
    os.utime(tmp_path / "20261001120000" / "f1.zip", (old, old))
    assert imm.unlock_expired(repo)["unlocked"] == 1
    assert os.stat(tmp_path / "20261001120000" / "f1.zip").st_mode & stat.S_IWRITE


def test_object_lock_with_moto():
    moto = pytest.importorskip("moto")
    import boto3
    with moto.mock_aws():
        repo = {"id": 1, "name": "Nuvem", "type": "s3", "path": "bkp-imutavel/srv01", "engine": "restic",
                "config": {"access_key": "AK", "secret_key": "SK", "region": "us-east-1",
                           "immutability": {"mode": "object_lock", "days": 30, "lock_mode": "COMPLIANCE"}}}
        s3 = boto3.client("s3", region_name="us-east-1", aws_access_key_id="AK", aws_secret_access_key="SK")
        s3.create_bucket(Bucket="sem-lock")
        plain = dict(repo, path="sem-lock")
        assert not imm.check_object_lock(plain)["protected"]
        with pytest.raises(RuntimeError, match="Object Lock"):
            imm.apply_object_lock(plain)
        res = imm.create_locked_bucket(repo)                     # bucket novo já com retenção padrão
        assert res["object_lock_enabled"] and res["default_retention"] == {"mode": "COMPLIANCE", "days": 30}
        import base64
        import hashlib
        s3.put_object(Bucket="bkp-imutavel", Key="srv01/data/pack1", Body=b"x",
                      ContentMD5=base64.b64encode(hashlib.md5(b"x").digest()).decode())
        res = imm.check_object_lock(repo)
        assert res["protected"] and res["sample"]["locked"] and res["sample"]["mode"] == "COMPLIANCE"
        assert res["lifecycle"] == {"rule": "gboc-imutavel-limpeza", "noncurrent_days": 31}


def test_object_lock_region_and_lifecycle_merge():
    moto = pytest.importorskip("moto")
    import boto3
    with moto.mock_aws():
        repo = {"id": 2, "name": "UE", "type": "s3", "path": "bkp-ue", "engine": "restic",
                "config": {"access_key": "AK", "secret_key": "SK", "region": "eu-central-1",
                           "immutability": {"mode": "object_lock", "days": 10, "lock_mode": "GOVERNANCE"}}}
        res = imm.create_locked_bucket(repo)                      # fora de us-east-1 → LocationConstraint
        assert res["object_lock_enabled"] and res["lifecycle"]["applied"]
        s3 = boto3.client("s3", region_name="eu-central-1", aws_access_key_id="AK", aws_secret_access_key="SK")
        assert s3.get_bucket_location(Bucket="bkp-ue")["LocationConstraint"] == "eu-central-1"
        rules = s3.get_bucket_lifecycle_configuration(Bucket="bkp-ue")["Rules"]
        s3.put_bucket_lifecycle_configuration(Bucket="bkp-ue", LifecycleConfiguration={"Rules": rules + [
            {"ID": "regra-do-cliente", "Status": "Enabled", "Filter": {"Prefix": "tmp/"}, "Expiration": {"Days": 3}}]})
        imm.apply_object_lock(repo)                               # reaplicar mantém regras de terceiros, sem duplicar
        ids = sorted(r["ID"] for r in s3.get_bucket_lifecycle_configuration(Bucket="bkp-ue")["Rules"])
        assert ids == ["gboc-imutavel-limpeza", "gboc-imutavel-limpeza-marcadores", "regra-do-cliente"]
        with pytest.raises(RuntimeError, match="já existe"):
            imm.create_locked_bucket(repo)
    assert imm.resolve_region({"endpoint": "https://s3.eu-central-2.wasabisys.com"}) == "eu-central-2"


# ───────── políticas ─────────

def test_policy_validation_and_effective_priority():
    from fastapi import HTTPException
    from modules.agents import policies as pol
    s = pol.validate_settings({"schedule": {"cron": "0 22 * * *", "enabled": True}, "retention": {"days": 60, "weekly": ""},
                               "bandwidth": {"default_mbps": 0, "rules": [{"days": [0], "start": "08:00", "end": "18:00", "mbps": 20}]}})
    assert s["retention"] == {"days": 60} and s["bandwidth"]["rules"][0]["mbps"] == 20
    with pytest.raises(HTTPException):
        pol.validate_settings({"schedule": {"cron": "toda noite"}})
    with pytest.raises(HTTPException):
        pol.validate_settings({})
    agents = [{"agent_id": "a", "tenant_id": "t1"}, {"agent_id": "b", "tenant_id": None}]
    p1 = {"id": 1, "enabled": True, "priority": 100, "scope_all": True, "agent_ids": []}
    p2 = {"id": 2, "enabled": True, "priority": 200, "scope_all": False, "tenant_id": "t1", "agent_ids": []}
    eff = pol.effective_map([p1, p2], agents)
    assert eff["a"]["id"] == 2 and eff["b"]["id"] == 1
    assert pol._parse_ret("60d / 8s / 6m / 1a") == {"days": 60, "weekly": 8, "monthly": 6, "yearly": 1}


def test_agent_policy_task_fields():
    from engines.central_policy import task_fields
    f = task_fields({"schedule": {"cron": "0 22 * * *", "enabled": True}, "retention": {"days": 45},
                     "retry": {"enabled": True, "max_attempts": 99, "delay_minutes": 0}})
    assert f == {"schedule_cron": "0 22 * * *", "schedule_enabled": True, "retention_days": 45, "retry_enabled": True,
                 "retry_max_attempts": 10, "retry_delay_minutes": 1}
    with pytest.raises(ValueError):
        task_fields({"schedule": {"cron": "x"}})


# ───────── inscrição, licença, faturamento, portal ─────────

def test_bootstrap_script_and_token_hash():
    from modules.agents import enrollment as en
    s = en.bootstrap_script("https://gboc.exemplo.com:8000", "gbi_TESTE")
    assert "$Token = 'gbi_TESTE'" in s and "/api/v1/enroll/package?token=$Token" in s and "-Unattended" in s
    assert en._hash("gbi_x") == en._hash(" gbi_x ") and len(en._hash("a")) == 64


def test_license_signature(tmp_path):
    import base64
    import json
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from modules.multitenant import licensing as lic
    key = Ed25519PrivateKey.generate()
    body = base64.urlsafe_b64encode(json.dumps({"product": "GBOC", "customer": "X", "max_agents": 5,
                                                "expires": "2030-01-01"}).encode()).decode().rstrip("=")
    tok = body + "." + base64.urlsafe_b64encode(key.sign(body.encode())).decode().rstrip("=")
    assert lic.decode_license(tok, key.public_key())["max_agents"] == 5
    with pytest.raises(ValueError, match="Assinatura"):
        lic.decode_license(tok, Ed25519PrivateKey.generate().public_key())
    with pytest.raises(ValueError):
        lic.decode_license(tok[:-4] + "AAAA", key.public_key())


def test_billing_period_bounds():
    from fastapi import HTTPException
    from modules.reports.billing import period_bounds
    s, e = period_bounds("2026-02")
    assert s == datetime(2026, 2, 1) and e == datetime(2026, 2, 28, 23, 59, 59)
    with pytest.raises(HTTPException):
        period_bounds("2026-13")


def test_client_role_is_restricted_to_portal():
    from modules.users.auth_guard import client_blocked
    c = {"role": "client", "tenant_id": "t1"}
    assert not client_blocked(c, "/api/v1/portal/summary")
    assert not client_blocked(c, "/api/v1/auth/status")
    assert client_blocked(c, "/api/v1/agents")
    assert client_blocked(c, "/api/v1/users")
    assert not client_blocked({"role": "admin"}, "/api/v1/users")
