"""
GBOC Native — criptografia do repositório (AES-256-GCM).

Sem isto o motor nativo gravava os blocos só compactados: quem tivesse acesso ao bucket lia os arquivos
(e os manifestos com nomes e caminhos). Agora, em repositório NOVO:

  * gboc-key.json (raiz do repositório): chave mestra aleatória de 64 bytes (32 para AES-256-GCM, 32 para
    HMAC-SHA256) protegida com a SENHA DO MOTOR do repositório (motor_password) via scrypt. Trocar a senha
    no futuro só regrava este arquivo;
  * cada bloco (objeto solto ou dentro de pacote) é gravado como  "E" | nonce(12) | AES-GCM(bloco compactado);
  * o id do bloco é HMAC-SHA256(chave, conteúdo) em vez do SHA-256 puro — o nome do objeto não revela se um
    arquivo conhecido está no backup; a deduplicação continua (mesmo conteúdo = mesmo id);
  * manifestos (nomes, caminhos, tamanhos, hash dos arquivos):  "GBOCENC1" | nonce | AES-GCM(zlib(JSON)).

Repositórios que já têm dados sem gboc-key.json continuam sem criptografia (lidos e gravados como antes);
o índice de pacotes (index/) segue sem criptografia: só tem ids HMAC, posições e tamanhos.
Perder a senha do motor = perder o backup (por isso ela vai no pacote de recuperação criptografado).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
import zlib
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger("gboc.native.crypto")

KEY_FILE = "gboc-key.json"
DOC_MAGIC = b"GBOCENC1"
BLOB_TAG = b"E"
_AAD_KEY = b"gboc-native-key-v1"
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 1 << 15, 8, 1
_init_lock = threading.Lock()
_cache: Dict[str, "RepoCipher"] = {}          # (arquivo de chave + senha) → cifra; evita scrypt a cada leitura


class RepoCipher:
    def __init__(self, master: bytes):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if len(master) != 64:
            raise ValueError("Chave mestra inválida")
        self._aes = AESGCM(master[:32])
        self._mac = master[32:]

    def chunk_id(self, data: bytes) -> str:
        return hmac.new(self._mac, data, hashlib.sha256).hexdigest()

    def seal(self, blob: bytes) -> bytes:
        nonce = os.urandom(12)
        return BLOB_TAG + nonce + self._aes.encrypt(nonce, blob, None)

    def open(self, blob: bytes) -> bytes:
        if blob[:1] != BLOB_TAG:
            return blob                       # bloco gravado sem criptografia
        from cryptography.exceptions import InvalidTag
        try:
            return self._aes.decrypt(blob[1:13], blob[13:], None)
        except InvalidTag:
            raise RuntimeError("Bloco não pôde ser descriptografado (corrompido ou de outro repositório)")

    def seal_doc(self, doc: Dict[str, Any]) -> bytes:
        nonce = os.urandom(12)
        raw = zlib.compress(json.dumps(doc, ensure_ascii=False).encode("utf-8"), 6)
        return DOC_MAGIC + nonce + self._aes.encrypt(nonce, raw, DOC_MAGIC)

    def open_doc(self, data: bytes) -> Dict[str, Any]:
        from cryptography.exceptions import InvalidTag
        try:
            raw = self._aes.decrypt(data[8:20], data[20:], DOC_MAGIC)
        except InvalidTag:
            raise RuntimeError("Manifesto não pôde ser descriptografado (corrompido ou de outro repositório)")
        return json.loads(zlib.decompress(raw).decode("utf-8"))


def is_encrypted_doc(data: bytes) -> bool:
    return data[:8] == DOC_MAGIC


def _kek(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(password.encode("utf-8"))


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def new_key_doc(password: str) -> Dict[str, Any]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    master, salt, nonce = os.urandom(64), os.urandom(16), os.urandom(12)
    wrapped = AESGCM(_kek(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)).encrypt(nonce, master, _AAD_KEY)
    return {"version": 1, "cipher": "AES-256-GCM", "id_hash": "HMAC-SHA256", "kdf": "scrypt",
            "n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P, "salt": _b64(salt), "nonce": _b64(nonce),
            "wrapped_key": _b64(wrapped), "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def unlock(doc: Dict[str, Any], password: str) -> RepoCipher:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ck = hashlib.sha256(json.dumps(doc, sort_keys=True).encode() + b"\0" + password.encode("utf-8")).hexdigest()
    if ck in _cache:
        return _cache[ck]
    try:
        kek = _kek(password, base64.b64decode(doc["salt"]), int(doc["n"]), int(doc["r"]), int(doc["p"]))
        master = AESGCM(kek).decrypt(base64.b64decode(doc["nonce"]), base64.b64decode(doc["wrapped_key"]), _AAD_KEY)
    except InvalidTag:
        raise RuntimeError("Senha do motor incorreta para este repositório criptografado (gboc-key.json)")
    c = RepoCipher(master)
    _cache[ck] = c
    return c


def _read_key_doc(backend) -> Optional[Dict[str, Any]]:
    from native_engine.store_v4 import _backend_get
    try:
        data = _backend_get(backend, KEY_FILE)
    except Exception:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError:
        raise RuntimeError("gboc-key.json do repositório está corrompido")


def has_data(names: Iterable[str]) -> bool:
    """Repositório já usado (o que não pode passar a ser criptografado retroativamente)."""
    for n in names:
        n = str(n).replace("\\", "/")
        if n == KEY_FILE or n.startswith("gboc-dr/"):
            continue
        return True
    return False


def open_repo(backend, password: Optional[str], names: Optional[Iterable[str]] = None,
              allow_init: bool = False) -> Optional[RepoCipher]:
    """Cifra do repositório ou None (repositório sem criptografia).
    allow_init: cria a chave se o repositório estiver vazio e houver senha do motor (só no backup)."""
    names = [str(n).replace("\\", "/") for n in names] if names is not None else None
    doc = _read_key_doc(backend)
    if doc is None and names is not None and KEY_FILE in names:
        # a listagem mostra a chave mas a leitura falhou (rede): nunca seguir como se fosse sem criptografia
        raise RuntimeError("Não foi possível ler gboc-key.json do repositório criptografado")
    if doc is None and allow_init and password:
        names = names if names is not None else [str(f).replace("\\", "/") for f in (backend.list_files() or [])]
        if has_data(names):
            return None
        with _init_lock:
            doc = _read_key_doc(backend)
            if doc is None:
                from native_engine.store_v4 import _backend_put
                r = _backend_put(backend, KEY_FILE, json.dumps(new_key_doc(password), indent=1).encode("utf-8"))
                if not r.get("success", False):
                    raise RuntimeError(f"Não foi possível gravar a chave do repositório: {r.get('error') or r.get('message')}")
                time.sleep(1.0)                              # outro agente iniciando o mesmo repositório: vale o gravado
                doc = _read_key_doc(backend)
                if doc is None:
                    raise RuntimeError("Chave do repositório gravada mas não encontrada na releitura")
                logger.info("Repositório novo do motor nativo: criptografia AES-256-GCM ativada (gboc-key.json)")
    if doc is None:
        return None
    if not password:
        raise RuntimeError("Repositório criptografado: informe a senha do motor do repositório")
    return unlock(doc, password)
