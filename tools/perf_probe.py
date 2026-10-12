"""
GBOC — sonda de latência das rotas reais (somente leitura, só GET).

Mede quanto cada rota da API demora no Agente/Server EM EXECUÇÃO, para achar o
gargalo real da lentidão antes de mexer em frontend/backend.

Uso (PowerShell, na máquina do Agente/Server):
    python tools\\perf_probe.py --base https://127.0.0.1:9200 --token SEU_TOKEN
    python tools\\perf_probe.py --base https://127.0.0.1:9200 --token SEU_TOKEN --rounds 5 --concurrent 8

O token é o valor de localStorage 'gboc_token' (Agente) ou 'gboc_server_token' (Server)
— F12 > Application > Local Storage na página já logada.

--concurrent N dispara N requisições ao mesmo tempo: se a latência de TODAS sobe junto,
há uma rota bloqueando o event loop (trabalho síncrono dentro de 'async def').
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import ssl
import statistics
import time
import urllib.error
import urllib.request

AGENT_ROUTES = [
    "/api/auth/status", "/api/system/info", "/api/server/status", "/api/overview/",
    "/api/repositories/", "/api/tasks/", "/api/tasks/running/detailed",
    "/api/duplicati-native/backups", "/api/notification-channels",
    "/api/database-backup/connections", "/api/preemptive/alerts",
    "/api/preemptive/sla-compliance", "/api/restore/status/",
]
SERVER_ROUTES = [
    "/api/system/info", "/api/server/status", "/api/system/hardware",
    "/api/v1/version", "/api/v2/system/version", "/api/v1/jobs/failed",
]


# O Agente usa HTTPS com certificado próprio em localhost: não validar o certificado aqui (só leitura local).
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def hit(base: str, path: str, token: str | None, timeout: float) -> tuple[str, int, float, int]:
    req = urllib.request.Request(base.rstrip("/") + path, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            body = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        body, code = e.read() or b"", e.code
    except Exception:
        body, code = b"", 0
    return path, code, (time.perf_counter() - t0) * 1000, len(body)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="ex.: https://127.0.0.1:9200")
    ap.add_argument("--token", default=None)
    ap.add_argument("--target", choices=["agent", "server"], default="agent")
    ap.add_argument("--routes", nargs="*", help="rotas extras/alternativas")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--concurrent", type=int, default=0, help="teste de bloqueio do event loop")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--json", dest="json_out", help="salva resultado bruto em JSON")
    a = ap.parse_args()

    routes = a.routes or (AGENT_ROUTES if a.target == "agent" else SERVER_ROUTES)
    res: dict[str, list[float]] = {r: [] for r in routes}
    codes: dict[str, int] = {}
    sizes: dict[str, int] = {}

    for _ in range(a.rounds):                       # sequencial: latência própria de cada rota
        for r in routes:
            p, c, ms, n = hit(a.base, r, a.token, a.timeout)
            res[p].append(ms); codes[p] = c; sizes[p] = n

    print(f"\n{'rota':45} {'HTTP':>4} {'med ms':>8} {'máx ms':>8} {'KB':>7}")
    print("-" * 76)
    for r in sorted(routes, key=lambda x: -statistics.median(res[x])):
        med, mx = statistics.median(res[r]), max(res[r])
        flag = "  <-- LENTA" if med > 500 else ""
        print(f"{r:45} {codes[r]:>4} {med:8.0f} {mx:8.0f} {sizes[r]/1024:7.1f}{flag}")
    total = sum(statistics.median(v) for v in res.values())
    print(f"\nSoma das medianas (uma tela que chame todas em série): {total:.0f} ms")

    conc = None
    if a.concurrent:
        light = "/api/auth/status" if a.target == "agent" else "/api/v1/version"
        _, _, base_ms, _ = hit(a.base, light, a.token, a.timeout)
        with cf.ThreadPoolExecutor(max_workers=a.concurrent + 1) as ex:
            heavy = [ex.submit(hit, a.base, r, a.token, a.timeout) for r in routes[: a.concurrent]]
            time.sleep(0.05)
            probe = ex.submit(hit, a.base, light, a.token, a.timeout).result()
            [f.result() for f in heavy]
        conc = {"rota_leve": light, "sozinha_ms": round(base_ms), "durante_carga_ms": round(probe[2])}
        print(f"\nTeste de bloqueio: {light} sozinha {base_ms:.0f} ms | com {a.concurrent} rotas em paralelo {probe[2]:.0f} ms")
        if probe[2] > max(300, base_ms * 5):
            print("  -> A rota leve esperou as pesadas: há trabalho SÍNCRONO bloqueando o event loop.")
        else:
            print("  -> Sem sinal de bloqueio do event loop.")

    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump({"base": a.base, "results": res, "codes": codes, "sizes": sizes, "concurrency": conc}, f, indent=2)
        print(f"\nJSON salvo em {a.json_out}")


if __name__ == "__main__":
    main()
