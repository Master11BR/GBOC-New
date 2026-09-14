#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GBOC Agent 14.1.0 - Database Cross Migrator (SQLite <-> PostgreSQL)
Migração de dados completa e sem perda de informações históricas entre bancos de dados.
"""

import os
import sqlite3
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("DatabaseCrossMigrator")

TABLES_TO_MIGRATE = [
    "repositories",
    "tasks",
    "task_executions",
    "backup_statistics",
    "settings",
    "alerts",
    "system_logs",
    "integrity_checks",
    "restore_history",
    "users"
]

class DatabaseCrossMigrator:
    """Engine para migração bidirecional sem perda de dados entre SQLite e PostgreSQL."""

    def __init__(self, core=None):
        self.core = core

    def migrate_sqlite_to_postgres(self, sqlite_db_path: str, pg_conn) -> Dict[str, Any]:
        """Migra todos os dados históricos do SQLite local para o PostgreSQL central/agente."""
        if not os.path.exists(sqlite_db_path):
            return {"status": "skipped", "message": f"Banco SQLite de origem não existe: {sqlite_db_path}"}

        logger.info(f"🔄 Iniciando migração de histórico: SQLite ({sqlite_db_path}) ➔ PostgreSQL")
        summary = {"status": "success", "migrated": {}, "errors": []}

        try:
            sqlite_conn = sqlite3.connect(sqlite_db_path)
            sqlite_conn.row_factory = sqlite3.Row
            sqlite_cur = sqlite_conn.cursor()

            with pg_conn.cursor() as pg_cur:
                for table in TABLES_TO_MIGRATE:
                    try:
                        # Verificar se tabela existe no SQLite
                        sqlite_cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                        if not sqlite_cur.fetchone():
                            continue

                        # Buscar todos os registros do SQLite
                        sqlite_cur.execute(f"SELECT * FROM {table}")
                        rows = sqlite_cur.fetchall()
                        if not rows:
                            continue

                        cols = rows[0].keys()
                        col_names = ", ".join(cols)
                        placeholders = ", ".join(["%s"] * len(cols))

                        # Inserção no PostgreSQL com ON CONFLICT (id) DO NOTHING
                        insert_query = f"""
                            INSERT INTO {table} ({col_names})
                            VALUES ({placeholders})
                            ON CONFLICT DO NOTHING
                        """

                        count = 0
                        for row in rows:
                            values = [row[c] for c in cols]
                            pg_cur.execute(insert_query, values)
                            count += 1

                        summary["migrated"][table] = count
                        logger.info(f"  ✅ {table}: {count} registro(s) migrado(s) para PostgreSQL.")

                        # Resetar a sequência serial do PostgreSQL se houver a coluna 'id'
                        if 'id' in cols:
                            try:
                                pg_cur.execute(f"""
                                    SELECT setval(pg_get_serial_sequence('{table}', 'id'),
                                           COALESCE((SELECT MAX(id) FROM {table}), 1), true);
                                """)
                            except Exception:
                                pass

                    except Exception as e_table:
                        err_msg = f"Erro ao migrar tabela {table}: {e_table}"
                        logger.warning(f"  ⚠️ {err_msg}")
                        summary["errors"].append(err_msg)

                pg_conn.commit()

            sqlite_conn.close()
            logger.info("🎉 Migração SQLite ➔ PostgreSQL concluída com sucesso!")
            return summary

        except Exception as e:
            logger.error(f"❌ Erro crítico na migração SQLite ➔ PostgreSQL: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "migrated": summary.get("migrated", {})}

    def migrate_postgres_to_sqlite(self, pg_conn, sqlite_db_path: str) -> Dict[str, Any]:
        """Migra todos os dados históricos do PostgreSQL para o banco SQLite local."""
        logger.info(f"🔄 Iniciando migração de histórico: PostgreSQL ➔ SQLite ({sqlite_db_path})")
        summary = {"status": "success", "migrated": {}, "errors": []}

        try:
            os.makedirs(os.path.dirname(os.path.abspath(sqlite_db_path)), exist_ok=True)
            sqlite_conn = sqlite3.connect(sqlite_db_path)
            sqlite_cur = sqlite_conn.cursor()

            with pg_conn.cursor() as pg_cur:
                for table in TABLES_TO_MIGRATE:
                    try:
                        # Verificar se a tabela existe no PG
                        pg_cur.execute("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables 
                                WHERE table_schema = 'public' AND table_name = %s
                            );
                        """, (table,))
                        if not pg_cur.fetchone()[0]:
                            continue

                        # Buscar nomes de colunas
                        pg_cur.execute(f"SELECT * FROM {table} LIMIT 0;")
                        cols = [desc[0] for desc in pg_cur.description]
                        if not cols:
                            continue

                        # Buscar todos os dados
                        pg_cur.execute(f"SELECT {', '.join(cols)} FROM {table};")
                        rows = pg_cur.fetchall()
                        if not rows:
                            continue

                        col_names = ", ".join(cols)
                        placeholders = ", ".join(["?"] * len(cols))
                        insert_query = f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})"

                        count = 0
                        for row in rows:
                            # Formatar datetime objetos para string isoformat no SQLite
                            formatted_row = []
                            for val in row:
                                if isinstance(val, datetime):
                                    formatted_row.append(val.isoformat())
                                else:
                                    formatted_row.append(val)
                            sqlite_cur.execute(insert_query, formatted_row)
                            count += 1

                        summary["migrated"][table] = count
                        logger.info(f"  ✅ {table}: {count} registro(s) migrado(s) para SQLite.")

                    except Exception as e_table:
                        err_msg = f"Erro ao migrar tabela {table}: {e_table}"
                        logger.warning(f"  ⚠️ {err_msg}")
                        summary["errors"].append(err_msg)

                sqlite_conn.commit()

            sqlite_conn.close()
            logger.info("🎉 Migração PostgreSQL ➔ SQLite concluída com sucesso!")
            return summary

        except Exception as e:
            logger.error(f"❌ Erro crítico na migração PostgreSQL ➔ SQLite: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "migrated": summary.get("migrated", {})}
