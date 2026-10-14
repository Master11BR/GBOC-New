"""
GBOC Agent — configuração SMTP (tabela smtp_config).

Existem duas versões da tabela nos bancos instalados:
  * a criada pela tela SMTP (api/smtp.py): id fixo 1, coluna `server`, `from_name`;
  * a criada pelo migrador (core/database_migrator.py): id SERIAL, coluna `host`, sem `from_name`.
Com a do migrador, salvar na tela falhava com 'column "server" of relation "smtp_config" does not exist'
e o envio de e-mails não achava a configuração. Aqui a tabela é completada com as colunas que faltam
(nada é apagado), `server` e `host` são gravados juntos e a leitura aceita as duas.
"""
from typing import Any, Dict, Optional

DEFAULT_FROM_NAME = "GBOC Backup System"

_COLUMNS = (
    ("server", "TEXT"), ("host", "TEXT"), ("port", "INTEGER DEFAULT 587"), ("username", "TEXT"),
    ("password", "TEXT"), ("use_tls", "BOOLEAN DEFAULT TRUE"), ("from_email", "TEXT"),
    ("from_name", "TEXT DEFAULT 'GBOC Backup System'"), ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
)


def ensure_schema(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS smtp_config (
            id INTEGER PRIMARY KEY DEFAULT 1,
            server TEXT,
            port INTEGER NOT NULL DEFAULT 587,
            username TEXT,
            password TEXT,
            use_tls BOOLEAN NOT NULL DEFAULT TRUE,
            from_email TEXT,
            from_name TEXT NOT NULL DEFAULT 'GBOC Backup System',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for col, ddl in _COLUMNS:
        cur.execute(f"ALTER TABLE smtp_config ADD COLUMN IF NOT EXISTS {col} {ddl}")


def _row(cur) -> Optional[Dict[str, Any]]:
    # id 1 primeiro (tela SMTP); na tabela do migrador o registro pode ter outro id
    cur.execute("SELECT * FROM smtp_config ORDER BY (id = 1) DESC, id LIMIT 1")
    r = cur.fetchone()
    if not r:
        return None
    return dict(zip([d[0] for d in cur.description], r))


def load(cur) -> Optional[Dict[str, Any]]:
    """Configuração normalizada (server, port, username, password, use_tls, from_email, from_name) ou None."""
    try:
        d = _row(cur)
    except Exception:
        return None
    if not d:
        return None
    d["server"] = d.get("server") or d.get("host")
    d["from_email"] = d.get("from_email") or d.get("username")
    d["from_name"] = d.get("from_name") or DEFAULT_FROM_NAME
    d["port"] = int(d.get("port") or 587)
    d["use_tls"] = True if d.get("use_tls") is None else bool(d.get("use_tls"))
    return d


def save(cur, server: str, port: int, username: str, password: str, use_tls: bool,
         from_email: str, from_name: str) -> None:
    """Grava (atualiza o registro existente ou cria o id 1). server e host recebem o mesmo valor."""
    ensure_schema(cur)
    vals = (server, server, int(port or 587), username, password, bool(use_tls), from_email,
            from_name or DEFAULT_FROM_NAME)
    existing = _row(cur)
    if existing:
        cur.execute("""UPDATE smtp_config SET server = %s, host = %s, port = %s, username = %s, password = %s,
                       use_tls = %s, from_email = %s, from_name = %s, updated_at = NOW() WHERE id = %s""",
                    (*vals, existing["id"]))
    else:
        cur.execute("""INSERT INTO smtp_config (id, server, host, port, username, password, use_tls, from_email,
                       from_name, updated_at) VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, NOW())""", vals)


def load_from_core() -> Optional[Dict[str, Any]]:
    try:
        from shared_core import get_shared_core
        with get_shared_core().get_db_connection() as conn:
            return load(conn.cursor())
    except Exception:
        return None
