"""
GBOC — mostra o que o PostgreSQL está esperando AGORA (somente leitura).

Rode em outra janela enquanto o Agente/Server estiver travado na inicialização:
    py -3.14 tools\\pg_waits.py              (banco gboc_agent)
    py -3.14 tools\\pg_waits.py gboc_server  (banco do Server)

Usa as mesmas variáveis POSTGRES_* do sistema.
"""
import os
import sys

import psycopg2

db = sys.argv[1] if len(sys.argv) > 1 else os.getenv("POSTGRES_DB", "gboc_agent")
conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST", "localhost"), port=int(os.getenv("POSTGRES_PORT", 5432)),
    dbname=db, user=os.getenv("POSTGRES_USER", "postgres"),
    password=os.getenv("POSTGRES_PASSWORD", "Stoms2025+"), connect_timeout=5,
)
conn.autocommit = True
cur = conn.cursor()
cur.execute("""
    SELECT pid, application_name, client_addr, state, wait_event_type, wait_event,
           pg_blocking_pids(pid) AS bloqueado_por,
           now() - xact_start AS tempo_transacao,
           left(regexp_replace(query, '\\s+', ' ', 'g'), 110) AS consulta
    FROM pg_stat_activity
    WHERE datname = %s AND pid <> pg_backend_pid()
    ORDER BY xact_start NULLS LAST
""", (db,))
rows = cur.fetchall()
print(f"\nSessões no banco '{db}': {len(rows)}\n")
for r in rows:
    pid, app, addr, state, wtype, wev, blk, tx, q = r
    flag = "  <== BLOQUEADA" if blk else ("  <== transação aberta parada" if state == "idle in transaction" else "")
    print(f"pid={pid} estado={state} espera={wtype}/{wev} bloqueado_por={blk} tx={tx}{flag}")
    print(f"    {q}")
cur.execute("SHOW synchronous_standby_names"); print("\nsynchronous_standby_names =", cur.fetchone()[0] or "(vazio)")
cur.execute("SHOW synchronous_commit"); print("synchronous_commit        =", cur.fetchone()[0])
