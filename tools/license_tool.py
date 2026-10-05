#!/usr/bin/env python3
"""
GBOC — Ferramenta do FORNECEDOR para emitir licenças (não vai no pacote de distribuição).

1) Gerar o par de chaves (uma única vez):
     python tools/license_tool.py keygen --private-key C:\\Seguro\\gboc_license_private.pem
   - grava a chave PRIVADA no caminho informado (guarde em local seguro, fora do projeto);
   - grava a chave PÚBLICA em GBOC-Server/license_public_key.pem (vai junto com o Server).

2) Emitir uma licença:
     python tools/license_tool.py issue --private-key C:\\Seguro\\gboc_license_private.pem ^
         --customer "Cliente X Ltda" --max-agents 50 --expires 2027-12-31
   Cole o texto gerado no Server: Multi-Tenant > Licença.

3) Conferir uma licença:
     python tools/license_tool.py show --token "<licença>"
"""
import argparse
import base64
import json
import os
import sys
import uuid
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_KEY = os.path.join(ROOT, "GBOC-Server", "license_public_key.pem")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def keygen(private_path: str, force: bool = False) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if os.path.exists(private_path) and not force:
        sys.exit(f"Já existe {private_path} (use --force para substituir — licenças antigas deixam de valer).")
    if os.path.abspath(private_path).startswith(os.path.join(ROOT, "GBOC-Server")) or \
            os.path.abspath(private_path).startswith(os.path.join(ROOT, "GBOC-Agent")):
        sys.exit("Não grave a chave privada dentro de GBOC-Server/GBOC-Agent (ela seria distribuída).")
    key = Ed25519PrivateKey.generate()
    os.makedirs(os.path.dirname(os.path.abspath(private_path)), exist_ok=True)
    with open(private_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with open(PUBLIC_KEY, "wb") as f:
        f.write(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    print(f"Chave privada: {private_path}  (GUARDE EM LOCAL SEGURO)")
    print(f"Chave pública: {PUBLIC_KEY}")


def issue(private_path: str, customer: str, max_agents: int, expires: str, features=None) -> str:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    date.fromisoformat(expires)
    with open(private_path, "rb") as f:
        key = load_pem_private_key(f.read(), password=None)
    payload = {"product": "GBOC", "id": str(uuid.uuid4()), "customer": customer, "max_agents": int(max_agents),
               "expires": expires, "issued": date.today().isoformat(), "features": features or []}
    body = _b64e(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return body + "." + _b64e(key.sign(body.encode("ascii")))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--private-key", required=True)
    k.add_argument("--force", action="store_true")
    i = sub.add_parser("issue")
    i.add_argument("--private-key", required=True)
    i.add_argument("--customer", required=True)
    i.add_argument("--max-agents", type=int, required=True)
    i.add_argument("--expires", required=True, help="AAAA-MM-DD")
    i.add_argument("--feature", action="append", default=[])
    s = sub.add_parser("show")
    s.add_argument("--token", required=True)
    a = p.parse_args()
    if a.cmd == "keygen":
        keygen(a.private_key, a.force)
    elif a.cmd == "issue":
        print(issue(a.private_key, a.customer, a.max_agents, a.expires, a.feature))
    else:
        body = a.token.split(".")[0]
        print(json.dumps(json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
