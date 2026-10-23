"""Chama todas as rotas GET e lista as que devolvem unknown/desconhecido/N/A nas respostas."""
import sys, os, json, ssl, re, urllib.request
port = sys.argv[1] if len(sys.argv) > 1 else "9200"
tok = open(os.path.join(os.path.dirname(__file__), "token.txt")).read().strip()
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
def get(p):
    req = urllib.request.Request(f"https://127.0.0.1:{port}{p}", headers={"Authorization": f"Bearer {tok}"})
    try:
        return urllib.request.urlopen(req, context=ctx, timeout=90).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", "replace")
    except Exception as e:
        return ""
spec = json.loads(get("/openapi.json"))
paths = [p for p, ops in spec["paths"].items() if "get" in ops and "{" not in p and not any(x in p for x in ("/download", "/stream", "/ws", "/export", "/logout", "/sse", "/events", "openapi", "/docs"))]
pat = re.compile(r'"([A-Za-z_]+)"\s*:\s*"(unknown|Unknown|UNKNOWN|desconhecid[oa]|Desconhecid[oa]|DESCONHECIDO|N/A)"')
hits = {}
for p in paths:
    body = get(p)
    for k, v in pat.findall(body):
        hits.setdefault(p, set()).add(f"{k}={v}")
print(f"rotas: {len(paths)} | com unknown/N/A: {len(hits)}")
for p, ks in sorted(hits.items()):
    print(" ", p, "->", ", ".join(sorted(ks))[:200])
