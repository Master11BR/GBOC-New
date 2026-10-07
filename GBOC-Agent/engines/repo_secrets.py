"""
GBOC Agent — chave secreta do provedor de nuvem dos repositórios.

A chave secreta (S3/Wasabi secret key, B2 application key, Azure account key) é guardada
CRIPTOGRAFADA no config JSON do repositório (campo "secret_enc", Fernet/AES).
A chave de criptografia fica em data/.repo_secrets.key (somente o serviço/administradores);
alternativamente pode ser informada na variável de ambiente GBOC_REPO_SECRET_KEY.

Antes desta correção a chave secreta digitada na criação era descartada (RM08 removia o texto
puro e nada a substituía) e o agente passava a usar a senha do motor no lugar dela.
Repositórios antigos continuam com esse comportamento até a chave secreta ser informada em Editar.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SECRET_FIELDS = ("aws_secret_key", "secret_key", "b2_account_key", "azure_account_key")
MASK = "********"
_fernet = None


def _key_path() -> str:
    try:
        from shared_core import DATA_DIR
        base = DATA_DIR
    except Exception:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    return os.path.join(base, ".repo_secrets.key")


def _restrict(path: str) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", "*S-1-5-18:F", "*S-1-5-32-544:F"],
                           capture_output=True, timeout=20)
        else:
            os.chmod(path, 0o600)
    except Exception as e:
        logger.debug(f"permissões da chave: {e}")


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    from cryptography.fernet import Fernet
    env = (os.environ.get("GBOC_REPO_SECRET_KEY") or "").strip()
    if env:
        _fernet = Fernet(env.encode())
        return _fernet
    path = _key_path()
    if os.path.exists(path):
        with open(path, "rb") as f:
            key = f.read().strip()
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        key = Fernet.generate_key()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        _restrict(path)
        logger.info("Chave de criptografia das credenciais de nuvem criada em data/.repo_secrets.key "
                    "(inclua-a no backup de configuração do agente)")
    _fernet = Fernet(key)
    return _fernet


def encrypt(secret: str) -> str:
    return _get_fernet().encrypt(str(secret).encode("utf-8")).decode("ascii")


def decrypt(token: str) -> Optional[str]:
    if not token:
        return None
    try:
        return _get_fernet().decrypt(str(token).encode("ascii")).decode("utf-8")
    except Exception as e:
        logger.warning(f"Não foi possível descriptografar a chave secreta do repositório "
                       f"(chave data/.repo_secrets.key trocada ou ausente?): {type(e).__name__}")
        return None


def secret_from_data(data: Dict[str, Any]) -> Optional[str]:
    """Chave secreta informada num formulário/requisição (ignora vazio e máscara)."""
    for f in SECRET_FIELDS:
        v = data.get(f)
        if v is not None and str(v) != "" and str(v) != MASK:
            return str(v)
    v = data.get("cloud_password")
    if v is not None and str(v) != "" and str(v) != MASK:
        return str(v)
    return None


def secret_from_config(config: Optional[Dict[str, Any]]) -> str:
    """Chave secreta salva no config do repositório ('' se não houver)."""
    if not isinstance(config, dict):
        return ""
    return decrypt(config.get("secret_enc")) or ""


def has_secret(config: Optional[Dict[str, Any]], cloud_password: Optional[str] = None) -> bool:
    if cloud_password and str(cloud_password).strip() and str(cloud_password).strip() != MASK:
        return True
    return isinstance(config, dict) and bool(config.get("secret_enc"))


def inject(target: Dict[str, Any], config: Optional[Dict[str, Any]]) -> None:
    """Preenche os campos de chave secreta ausentes em target a partir do config criptografado ou cloud_password."""
    sec = secret_from_config(config) if has_secret(config) else ""
    if not sec and target.get("cloud_password") and str(target.get("cloud_password")).strip() != MASK:
        sec = str(target.get("cloud_password")).strip()
    if not sec:
        return
    for f in SECRET_FIELDS:
        if not target.get(f):
            target[f] = sec
    if not target.get("cloud_password"):
        target["cloud_password"] = sec
