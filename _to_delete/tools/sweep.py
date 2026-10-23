"""Chama todas as rotas GET sem parametro de caminho e lista 5xx e lentas."""
import sys, os, json, ssl, time, urllib.request
port = sys.argv[1] if len(sys.argv) > 1 else "9200"
tok = open(os.path.join(os.path.dirname(__file__), "token.txt")).read().strip()
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
def get(p, timeout=60):
    req = urllib.request.Request(f"https://127.0.0.1:{port}{p}", headers={"Authorization": f"Bearer {tok}"})
    t = time.time()
    try:
        r = urllib.request.urlopen(req, context=ctx, timeout=timeout); return r.status, time.time() - t, r.read()[:300]
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t, e.read()[:300]
    except Exception as e:
        return -1, time.time() - t, str(e).encode()[:300]
code, _, body = get("/openapi.json")
spec = json.loads(urllib.request.urlopen(urllib.request.Request(f"https://127.0.0.1:{port}/openapi.json", headers={"Authorization": f"Bearer {tok}"}), context=ctx, timeout=60).read())
paths = [p for p, ops in spec["paths"].items() if "get" in ops and "{" not in p and not any(x in p for x in ("/download", "/stream", "/ws", "/export", "/logout", "/sse", "/events"))]
errs, slow = [], []
for p in paths:
    c, dt, b = get(p)
    if c >= 500 or c == -1: errs.append((p, c, b.decode("utf-8", "replace")[:160]))
    if dt > 3: slow.append((p, round(dt, 1)))
print(f"rotas GET chamadas: {len(paths)} | erros 5xx/conexao: {len(errs)}")
for e in errs: print("  ERRO", e)
for s in sorted(slow, key=lambda x: -x[1])[:10]: print("  lenta", s)
