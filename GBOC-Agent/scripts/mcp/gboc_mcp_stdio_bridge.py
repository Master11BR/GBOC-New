#!/usr/bin/env python3
"""
Ponte stdio → HTTP para o servidor MCP do GBOC Agent.
Para clientes MCP que só aceitam servidores locais por comando (ex.: Claude Desktop).
Usa apenas a biblioteca padrão do Python.

Variáveis de ambiente:
  GBOC_MCP_URL     ex.: https://servidor-backup:9200/api/mcp
  GBOC_MCP_TOKEN   token gerado na tela "IA: Conhecimento, MCP e Treino" (gboc_mcp_...)
  GBOC_MCP_CA      (opcional) caminho do certificado do Agente (gboc_tls_cert.pem) para validar HTTPS autoassinado
  GBOC_MCP_INSECURE=1  (opcional, não recomendado) ignora a validação do certificado

Exemplo (claude_desktop_config.json):
  "gboc": {"command": "python", "args": ["C:/GBOC/Agent/scripts/mcp/gboc_mcp_stdio_bridge.py"],
           "env": {"GBOC_MCP_URL": "https://srv:9200/api/mcp", "GBOC_MCP_TOKEN": "gboc_mcp_..."}}
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.request


def main():
    url = os.environ.get("GBOC_MCP_URL", "").strip()
    token = os.environ.get("GBOC_MCP_TOKEN", "").strip()
    if not url or not token:
        sys.stderr.write("Defina GBOC_MCP_URL e GBOC_MCP_TOKEN.\n")
        sys.exit(2)
    ctx = None
    if url.startswith("https"):
        if os.environ.get("GBOC_MCP_INSECURE") == "1":
            ctx = ssl._create_unverified_context()
        elif os.environ.get("GBOC_MCP_CA"):
            ctx = ssl.create_default_context(cafile=os.environ["GBOC_MCP_CA"])
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "Authorization": f"Bearer {token}"}

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        req = urllib.request.Request(url, data=line.encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=600) as resp:
                body = resp.read().decode("utf-8")
                if resp.status == 202 or not body.strip():
                    continue
                sys.stdout.write(body.strip() + "\n")
                sys.stdout.flush()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            if isinstance(msg, dict) and "id" in msg:
                try:
                    payload = json.loads(detail)
                    if isinstance(payload, dict) and payload.get("jsonrpc"):
                        payload["id"] = msg["id"]
                        sys.stdout.write(json.dumps(payload) + "\n")
                        sys.stdout.flush()
                        continue
                except ValueError:
                    pass
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                                             "error": {"code": -32000, "message": f"HTTP {e.code}: {detail}"}}) + "\n")
                sys.stdout.flush()
        except Exception as e:
            if isinstance(msg, dict) and "id" in msg:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                                             "error": {"code": -32000, "message": f"GBOC Agent inacessível: {e}"}}) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
