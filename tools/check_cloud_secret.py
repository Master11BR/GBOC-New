"""
GBOC — confere a chave secreta da nuvem (cloud_password) de cada repositório (somente leitura).

A chave secreta do provedor (S3, B2, Wasabi...) fica gravada em dois lugares:
  * coluna repositories.cloud_password;
  * cópia criptografada no config do repositório (secret_enc).
As duas deveriam ser sempre iguais. Este script compara as duas e também compara com a chave que o
Kopia usa para o mesmo bucket (data/kopia_configs), que é uma referência de chave que funciona.

Nenhuma chave é exibida: só "igual" / "diferente" e o tamanho.

    py -3.14 tools\\check_cloud_secret.py

Usa as mesmas variáveis POSTGRES_* do sistema.
"""
import glob
import json
import os
import sys

import psycopg2

AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "GBOC-Agent")
sys.path.insert(0, AGENT_DIR)
from engines import repo_secrets  # noqa: E402  (precisa do caminho do Agente)


def kopia_secrets():
    """{(bucket, access_key): secret} das configurações do Kopia."""
    out = {}
    for f in glob.glob(os.path.join(AGENT_DIR, "data", "kopia_configs", "*.config")):
        try:
            with open(f, encoding="utf-8") as h:
                st = ((json.load(h).get("storage") or {}).get("config")) or {}
        except (OSError, ValueError):
            continue
        if st.get("secretAccessKey"):
            out[(st.get("bucket"), st.get("accessKeyID"))] = st["secretAccessKey"]
    return out


def label(a, b):
    if not a or not b:
        return "sem valor"
    return "IGUAL" if a == b else "DIFERENTE"


conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST", "localhost"), port=int(os.getenv("POSTGRES_PORT", 5432)),
    dbname=os.getenv("POSTGRES_DB", "gboc_agent"), user=os.getenv("POSTGRES_USER", "postgres"),
    password=os.getenv("POSTGRES_PASSWORD", "Stoms2025+"), connect_timeout=5,
)
cur = conn.cursor()
cur.execute("SELECT id, name, type, path, cloud_password, motor_password, config FROM repositories "
            "WHERE lower(coalesce(type, 'local')) <> 'local' ORDER BY id")
kop = kopia_secrets()
for rid, name, rtype, path, col, motor, cfg in cur.fetchall():
    cfg = json.loads(cfg) if isinstance(cfg, str) and cfg else (cfg or {})
    enc = repo_secrets.secret_from_config(cfg)
    bucket = cfg.get("bucket") or path
    ak = cfg.get("aws_access_key") or cfg.get("access_key") or cfg.get("b2_account_id")
    ref = kop.get((bucket, ak))
    print(f"\nRepositório {rid} — {name} ({rtype}, bucket {bucket}, access key {str(ak or '')[:6]}…)")
    print(f"  coluna cloud_password : {'presente' if col else 'vazia'} ({len(col or '')} caracteres)"
          f"{'  <- igual à senha do motor (motor_password)!' if col and col == motor else ''}")
    print(f"  cópia criptografada   : {'presente' if enc else 'ausente'} ({len(enc)} caracteres)")
    print(f"  coluna x criptografada: {label(col, enc)}")
    if ref:
        print(f"  Kopia (mesmo bucket/chave, funciona): coluna {label(col, ref)} | criptografada {label(enc, ref)}")
    else:
        print("  Kopia: nenhuma configuração com o mesmo bucket e access key para comparar")
conn.close()
