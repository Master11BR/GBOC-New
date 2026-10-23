"""Uso: python api.py GET /api/v1/storage/usage [porta]  -> cria sessao temporaria (1 h) e chama a API local."""
import sys, os, json, secrets, ssl, urllib.request
from datetime import datetime, timedelta
AG = r"D:\GBOC-New\GBOC-New\GBOC-Agent"
sys.path.insert(0, AG); os.chdir(AG)
import gboc_encoding_compat
tokf = os.path.join(os.path.dirname(__file__), "token.txt")
tok = open(tokf).read().strip() if os.path.exists(tokf) and (datetime.now().timestamp() - os.path.getmtime(tokf)) < 3000 else None
if not tok:
    from shared_core import SharedCore
    sc = SharedCore()
    tok = "tmpaudit_" + secrets.token_hex(24)
    with sc.get_db_connection() as c:
        cur = c.cursor()
        cur.execute("SELECT id FROM auth_users ORDER BY id LIMIT 1")
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO auth_sessions (user_id, token, ip_address, user_agent, expires_at) VALUES (%s,%s,%s,%s,%s)",
                    (uid, tok, "127.0.0.1", "gboc-audit", (datetime.now() + timedelta(hours=1)).astimezone().isoformat()))
        c.commit()
    open(tokf, "w").write(tok)
method, path = sys.argv[1], sys.argv[2]
port = sys.argv[3] if len(sys.argv) > 3 else "9200"
body = sys.argv[4].encode() if len(sys.argv) > 4 else None
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request(f"https://127.0.0.1:{port}{path}", data=body, method=method,
                             headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
try:
    r = urllib.request.urlopen(req, context=ctx, timeout=120); print(r.status); print(r.read().decode()[:6000])
except urllib.error.HTTPError as e:
    print(e.code); print(e.read().decode()[:3000])
