import argparse
import psycopg2


def run(admin_user: str, admin_password: str, host: str, port: int, dbname: str, app_user: str):
    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=admin_user,
        password=admin_password,
    )
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
    cur.execute(f"CREATE SCHEMA public AUTHORIZATION {app_user}")
    cur.execute(f"GRANT USAGE, CREATE ON SCHEMA public TO {app_user}")
    cur.execute(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {app_user}")
    cur.execute(f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {app_user}")
    cur.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {app_user}")
    cur.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {app_user}")

    cur.close()
    conn.close()
    print("[OK] Schema public resetado com sucesso.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--dbname", default="gboc")
    parser.add_argument("--admin-user", default="postgres")
    parser.add_argument("--admin-password", default="Stoms2025+")
    parser.add_argument("--app-user", default="gboc_user")
    args = parser.parse_args()

    run(args.admin_user, args.admin_password, args.host, args.port, args.dbname, args.app_user)
