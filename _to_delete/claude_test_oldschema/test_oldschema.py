# Teste: banco PostgreSQL real com esquema de versão antiga -> migração + importador.
import os, sys, json, logging, contextlib
AGENT = r"D:\GBOC-New\GBOC-New\GBOC-Agent"
sys.path.insert(0, AGENT); os.chdir(AGENT)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
import psycopg2
TEST_DB = "gboc_oldschema_test"
base = dict(host=os.getenv("POSTGRES_HOST","localhost"), port=int(os.getenv("POSTGRES_PORT",5432)),
            user=os.getenv("POSTGRES_USER","postgres"), password=os.getenv("POSTGRES_PASSWORD","Stoms2025+"))
adm = psycopg2.connect(dbname="postgres", **base); adm.autocommit = True
c = adm.cursor(); c.execute(f"DROP DATABASE IF EXISTS {TEST_DB}"); c.execute(f"CREATE DATABASE {TEST_DB}"); adm.close()
cfg = dict(dbname=TEST_DB, **base)
MODE = os.getenv("GBOC_TEST_MODE", "old")
if MODE == "copy":
    import subprocess
    pg = r"C:\Program Files\PostgreSQL\18\bin"
    env = dict(os.environ, PGPASSWORD=base["password"])
    dump = subprocess.run([pg + r"\pg_dump.exe", "-s", "-U", base["user"], "-h", base["host"], "gboc_agent"], capture_output=True, env=env, check=True).stdout
    subprocess.run([pg + r"\psql.exe", "-q", "-U", base["user"], "-h", base["host"], "-d", TEST_DB], input=dump, capture_output=True, env=env, check=True)
    def snap():
        k = psycopg2.connect(**cfg); q = k.cursor()
        q.execute("SELECT table_name, column_name, data_type, column_default FROM information_schema.columns WHERE table_schema='public' ORDER BY 1,2")
        r = q.fetchall(); k.close(); return r
    BEFORE = snap()
con = psycopg2.connect(**cfg); cur = con.cursor()
if MODE == "old": cur.execute("""
CREATE TABLE repositories (id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, type TEXT NOT NULL, path TEXT NOT NULL,
  password TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE tasks (id SERIAL PRIMARY KEY, name TEXT NOT NULL, repository_id INTEGER REFERENCES repositories(id),
  schedule TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE alerts (id SERIAL PRIMARY KEY, type TEXT, message TEXT, created_at TEXT);
CREATE TABLE audit_log (id SERIAL PRIMARY KEY, action TEXT, user_name TEXT, created_at TEXT);
CREATE TABLE job_failure_log (id SERIAL PRIMARY KEY, job_name TEXT, error TEXT, created_at TEXT);
INSERT INTO repositories (name,type,path,password,created_at) VALUES ('RepoAntigo','local','D:\\bk','x','2025-01-01T10:00:00');
INSERT INTO tasks (name,repository_id,schedule,created_at) VALUES ('TarefaAntiga',1,'daily','2025-01-01T10:00:00');
""")
con.commit(); con.close()

class Core:
    @contextlib.contextmanager
    def get_db_connection(self):
        k = psycopg2.connect(**cfg)
        try: yield k
        finally: k.close()
core = Core()

import shared_core
if shared_core.USE_POSTGRESQL:
    shared_core.SharedCore._initialize_database(core)   # mesmo passo da inicialização real
from database_migrator import run_auto_migrations
with core.get_db_connection() as k:
    res = run_auto_migrations(k)
print("MIGRATION RESULT:", json.dumps(res, ensure_ascii=False)[:1500])

def cols(t):
    with core.get_db_connection() as k:
        q = k.cursor(); q.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (t,))
        return sorted(r[0] for r in q.fetchall())
for t in ("job_failure_log","repositories","tasks"):
    print("COLS", t, cols(t))
if MODE == "copy":
    after = set(snap()); before = set(BEFORE)
    print("SCHEMA COPY: removed/changed:", sorted(before - after)[:20]); print("SCHEMA COPY: added:", sorted(after - before)[:40])

if "--import" in sys.argv:
    from engines.backup_importer import RealBackupImporter
    r = RealBackupImporter(core).import_all_to_native()
    print("IMPORT STATUS:", r.get("status"), "|", r.get("message"))
    for l in r.get("logs", [])[:40]: print("  ", l)
    with core.get_db_connection() as k:
        q = k.cursor(); q.execute("SELECT id,name,engine,type FROM repositories ORDER BY id"); print("REPOS", q.fetchall())
        q.execute("SELECT id,name,engine,repository_id,schedule_cron FROM tasks ORDER BY id"); print("TASKS", q.fetchall())
