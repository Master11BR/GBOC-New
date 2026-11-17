"""
GBOC Agent — Confiança TLS na comunicação Agente → Servidor Central.

Padrão (compatível com instalações existentes): aceita o certificado autoassinado do Servidor
(verify=False), como antes. Para impedir que alguém na rede se passe pelo Servidor, configure UMA opção:

  GBOC_SERVER_CERT_SHA256 = <impressão SHA-256 do certificado do Servidor>   (pinning; recomendado)
      ex.: obtida com  certutil -hashfile server_cert.pem SHA256  ou exibida pelo Servidor
  GBOC_SERVER_CA_BUNDLE   = C:\\caminho\\ca.pem   (valida a cadeia com essa CA)
  GBOC_SERVER_TLS_VERIFY  = 1                     (valida com as CAs do sistema; certificado público)
"""
from __future__ import annotations

import logging
import os
from typing import Union

logger = logging.getLogger(__name__)


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "sim", "on")


def server_fingerprint() -> str:
    fp = (os.getenv("GBOC_SERVER_CERT_SHA256") or "").strip().replace(":", "").replace(" ", "").lower()
    return fp if len(fp) == 64 and all(c in "0123456789abcdef" for c in fp) else ""


def server_verify() -> Union[bool, str]:
    """Valor para o parâmetro verify= do requests nas chamadas ao Servidor."""
    bundle = (os.getenv("GBOC_SERVER_CA_BUNDLE") or "").strip()
    if bundle:
        if os.path.isfile(bundle):
            return bundle
        logger.error(f"[TLS] GBOC_SERVER_CA_BUNDLE aponta para arquivo inexistente: {bundle}")
    if _truthy(os.getenv("GBOC_SERVER_TLS_VERIFY", "")):
        return True
    return False


def configure_session(session) -> None:
    """Aplica a política TLS a uma requests.Session usada com o Servidor."""
    session.verify = server_verify()
    fp = server_fingerprint()
    if not fp:
        return
    try:
        from requests.adapters import HTTPAdapter

        class _PinnedAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                kwargs["assert_fingerprint"] = fp
                return super().init_poolmanager(*args, **kwargs)

            def proxy_manager_for(self, *args, **kwargs):
                kwargs["assert_fingerprint"] = fp
                return super().proxy_manager_for(*args, **kwargs)

        session.mount("https://", _PinnedAdapter())
        session.verify = False   # a confiança vem da impressão digital fixada (certificado autoassinado)
        logger.info("[TLS] Pinning do certificado do Servidor ativo (SHA-256).")
    except Exception as e:  # pragma: no cover - defensivo
        logger.error(f"[TLS] Falha ao ativar pinning do certificado: {e}")


def new_session():
    import requests
    s = requests.Session()
    configure_session(s)
    return s
