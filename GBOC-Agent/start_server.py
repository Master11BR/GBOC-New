#!/usr/bin/env python3
"""
GBOC Agent 14.0.0 - Startup Script
Suporta HTTP/1.1 (uvicorn) e HTTP/2+TLS (hypercorn) via variável GBOC_HTTP2=true
Redireciona HTTP→HTTPS automaticamente (porta AGENT_HTTP_PORT, padrão 9201)
"""

import asyncio
import sys
import os
import logging
import ssl

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_http2 = os.getenv("GBOC_HTTP2", "true").lower() in ("1", "true", "yes")
# Selector loop apenas quando HTTP/2 está desligado
if sys.platform == 'win32' and not _http2:
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    from agent_gboc import app
except ImportError:
    from agent_server import app


async def _redirect_app(scope, receive, send):
    """App ASGI mínimo: redireciona toda requisição HTTP para HTTPS."""
    if scope["type"] == "http":
        _https_port = int(os.getenv("AGENT_PORT", "9200"))
        host = ""
        for name, value in scope.get("headers", []):
            if name == b"host":
                host = value.decode().split(":")[0]
                break
        path = scope.get("path", "/")
        qs = scope.get("query_string", b"")
        location = f"https://{host}:{_https_port}{path}"
        if qs:
            location += f"?{qs.decode()}"
        await send({"type": "http.response.start", "status": 301,
                    "headers": [[b"location", location.encode()],
                                [b"content-length", b"0"]]})
        await send({"type": "http.response.body", "body": b""})


def _run_hypercorn(host: str, port: int, http_port: int):
    """Inicia o servidor com Hypercorn + TLS (HTTP/2 completo para browsers)."""
    from hypercorn.config import Config
    from hypercorn.asyncio import serve
    from utils.tls_cert import ensure_tls_cert

    def _install_asyncio_ssl_ignore(loop: asyncio.AbstractEventLoop):
        previous_handler = loop.get_exception_handler()

        def _handler(current_loop, context):
            exc = context.get("exception")
            if isinstance(exc, ssl.SSLError) and "APPLICATION_DATA_AFTER_CLOSE_NOTIFY" in str(exc):
                return
            if previous_handler is not None:
                previous_handler(current_loop, context)
            else:
                current_loop.default_exception_handler(context)

        loop.set_exception_handler(_handler)

    # Filtro para suprimir erros SSL close-notify que são ruído benigno
    class SSLCloseNotifyFilter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage()
            return (
                "APPLICATION_DATA_AFTER_CLOSE_NOTIFY" not in msg
                and "application data after close notify" not in msg
                and "TLSV1_ALERT_UNKNOWN_CA" not in msg
                and "tlsv1 alert unknown ca" not in msg
            )

    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger.addFilter(SSLCloseNotifyFilter())

    cert, key = ensure_tls_cert(cn="GBOC-Agent", ip=host if host != "0.0.0.0" else "127.0.0.1")

    cfg_https = Config()
    cfg_https.bind = [f"{host}:{port}"]
    cfg_https.certfile = cert
    cfg_https.keyfile = key
    cfg_https.alpn_protocols = ["h2", "http/1.1"]
    cfg_https.loglevel = "info"
    cfg_https.graceful_timeout = 3
    cfg_https.shutdown_timeout = 10
    cfg_https.keep_alive_timeout = 5

    print(f"[GBOC Agent] HTTPS/HTTP2 em https://{host}:{port}")
    print(f"[GBOC Agent] Acesse: https://localhost:{port}")

    if http_port:
        cfg_http = Config()
        cfg_http.bind = [f"{host}:{http_port}"]
        cfg_http.loglevel = "warning"
        cfg_http.graceful_timeout = 3
        cfg_http.shutdown_timeout = 5
        print(f"[GBOC Agent] HTTP→HTTPS redirector em http://{host}:{http_port}")

        async def _run_both():
            print(f"[GBOC Agent] Ambos os servidores iniciados: HTTPS:{port} + HTTP-redirect:{http_port}")
            _install_asyncio_ssl_ignore(asyncio.get_running_loop())
            await asyncio.gather(
                serve(app, cfg_https),
                serve(_redirect_app, cfg_http),
            )

        asyncio.run(_run_both())
    else:
        async def _run_https_only():
            _install_asyncio_ssl_ignore(asyncio.get_running_loop())
            await serve(app, cfg_https)

        asyncio.run(_run_https_only())


def _run_uvicorn(host: str, port: int):
    """Inicia o servidor com Uvicorn (HTTP/1.1 — fallback sem TLS)."""
    import uvicorn
    print(f"[GBOC Agent] HTTP/1.1 via Uvicorn em http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    PORT = int(os.getenv("AGENT_PORT", "9200"))
    HOST = os.getenv("AGENT_HOST", "0.0.0.0")
    # Porta HTTP que redireciona para HTTPS (0 = desativado)
    HTTP_PORT = int(os.getenv("AGENT_HTTP_PORT", "9201"))

    if _http2:
        try:
            _run_hypercorn(HOST, PORT, HTTP_PORT)
        except ImportError:
            print("[GBOC Agent] hypercorn não encontrado — usando uvicorn (HTTP/1.1). Execute: pip install hypercorn[h2]")
            _run_uvicorn(HOST, PORT)
    else:
        _run_uvicorn(HOST, PORT)

