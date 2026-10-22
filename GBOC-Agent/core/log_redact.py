"""
GBOC - Redação de segredos nos logs.

Comandos de S3 (kopia, restic, rclone...) recebem a chave secreta na linha de comando. Quando um
comando falha, o Python monta mensagens como "Command ['kopia', ..., '--secret-access-key', 'XXX']"
e isso ia parar nos logs em texto puro. O filtro abaixo troca o valor do segredo por *** antes de
qualquer handler gravar a linha (arquivo, console, banco).
"""
from __future__ import annotations

import logging
import re
import traceback

_PATTERNS = [
    # --secret-access-key XXX | --secret-access-key=XXX | --aws-secret-access-key=XXX
    (re.compile(r"(--(?:aws-)?secret-access-key(?:=|\s+))([^\s'\"\],)]+)"), r"\1***"),
    # repr de lista Python: '--secret-access-key', 'XXX'
    (re.compile(r"(['\"]--(?:aws-)?secret-access-key['\"],\s*['\"])([^'\"]+)(['\"])"), r"\1***\3"),
    # repr de dict: 'secret_key': 'XXX' / 'aws_secret_key': 'XXX'
    (re.compile(r"(['\"](?:aws_)?secret_key['\"]\s*:\s*['\"])([^'\"]+)(['\"])"), r"\1***\3"),
    # variável de ambiente
    (re.compile(r"(AWS_SECRET_ACCESS_KEY=)(\S+)"), r"\1***"),
]


def redact(text: str) -> str:
    if not text:
        return text
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text


class SecretRedactFilter(logging.Filter):
    """Filtro de handler: redige a mensagem final e também o traceback de exceções."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        record.msg = redact(msg)
        record.args = ()
        if record.exc_info and record.exc_info[0] is not None:
            try:
                record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)))
            except Exception:
                pass
        return True


def install(*handlers: logging.Handler) -> None:
    for h in handlers:
        if h is not None and not any(isinstance(f, SecretRedactFilter) for f in h.filters):
            h.addFilter(SecretRedactFilter())
