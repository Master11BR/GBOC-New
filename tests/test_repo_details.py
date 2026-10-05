"""Chave secreta de nuvem criptografada e detalhes do repositório (sem banco/rede)."""
import json

import pytest
from cryptography.fernet import Fernet

from engines import repo_secrets


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("GBOC_REPO_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(repo_secrets, "_fernet", None)
    yield
    repo_secrets._fernet = None


def _rm():
    from engines.repository_manager import RepositoryManager
    return RepositoryManager.__new__(RepositoryManager)


def test_secret_roundtrip_and_mask():
    tok = repo_secrets.encrypt("s3cr3t")
    assert "s3cr3t" not in tok and repo_secrets.decrypt(tok) == "s3cr3t"
    assert repo_secrets.secret_from_data({"secret_key": "********"}) is None
    assert repo_secrets.secret_from_data({"aws_secret_key": "", "secret_key": "abc"}) == "abc"
    assert repo_secrets.decrypt("lixo") is None


def test_secret_is_persisted_encrypted_and_restored():
    rm = _rm()
    cfg = rm._build_config_data({"bucket": "b", "access_key": "AK", "secret_key": "REAL", "motor_password": "MotorPass1"}, "wasabi")
    assert "secret_key" not in cfg and "REAL" not in json.dumps(cfg) and cfg["secret_enc"]
    norm = rm._normalize_repository_config({"type": "wasabi", "motor_password": "MotorPass1", "config": json.dumps(cfg)})
    assert norm["secret_key"] == "REAL" and norm["aws_secret_key"] == "REAL" and "secret_enc" not in norm
    # repositório antigo (sem chave salva) mantém o comportamento anterior
    old = rm._normalize_repository_config({"type": "wasabi", "motor_password": "MotorPass1", "config": json.dumps({"bucket": "b"})})
    assert old["secret_key"] == "MotorPass1"
    assert "secret_enc" not in rm._build_config_data({"path": "/x", "secret_key": "y"}, "local")


def test_api_never_returns_secret_enc():
    from api.repositories import _strip_secret_enc
    d = {"config": json.dumps({"bucket": "b", "secret_enc": repo_secrets.encrypt("x")}), "secret_enc": "t"}
    _strip_secret_enc(d)
    assert "secret_enc" not in d and "secret_enc" not in d["config"] and d["secret_configured"] is True


def test_region_from_endpoint():
    from engines.immutability import resolve_region
    assert resolve_region({"endpoint": "s3.eu-central-2.wasabisys.com"}) == "eu-central-2"
    assert resolve_region({"endpoint": "https://s3.wasabisys.com"}) == "us-east-1"
    assert resolve_region({"region": "sa-east-1", "endpoint": "s3.us-west-1.wasabisys.com"}) == "sa-east-1"


def test_live_bucket_settings_with_moto():
    moto = pytest.importorskip("moto")
    import base64
    import hashlib

    import boto3
    from engines import repo_inspect
    with moto.mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1", aws_access_key_id="AK", aws_secret_access_key="SK")
        s3.create_bucket(Bucket="bkt", ObjectLockEnabledForBucket=True)
        s3.put_object_lock_configuration(Bucket="bkt", ObjectLockConfiguration={
            "ObjectLockEnabled": "Enabled", "Rule": {"DefaultRetention": {"Mode": "GOVERNANCE", "Days": 3}}})
        s3.put_bucket_tagging(Bucket="bkt", Tagging={"TagSet": [{"Key": "cliente", "Value": "ACME"}]})
        for i in range(3):
            body = b"x" * (i + 1)
            s3.put_object(Bucket="bkt", Key=f"srv/data/{i}", Body=body, ContentMD5=base64.b64encode(hashlib.md5(body).digest()).decode())
        s3.put_object(Bucket="bkt", Key="outro/arquivo", Body=b"y", ContentMD5=base64.b64encode(hashlib.md5(b"y").digest()).decode())
        repo = {"id": 1, "type": "s3", "path": "bkt", "engine": "gboc_native",
                "config": {"bucket": "bkt", "prefix": "srv", "aws_access_key": "AK", "secret_enc": repo_secrets.encrypt("SK")}}
        out = repo_inspect._s3_live(repo)
        assert out["reachable"] and out["versioning"]["status"] == "Enabled"
        assert out["object_lock"]["enabled"] and out["object_lock"]["default_days"] == 3
        assert out["tags"]["tags"] == {"cliente": "ACME"}
        assert out["lifecycle"] == {"configured": False} and out["encryption"] == {"configured": False}
        ob = out["objects"]
        assert ob["count"] == 3 and ob["size_bytes"] == 6 and not ob["partial"]       # só o prefixo do repositório
        assert ob["newest_object"]["locked"] and ob["newest_object"]["lock_mode"] == "GOVERNANCE"
