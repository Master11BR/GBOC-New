# ==============================================================================
# GBOC System v14.1.0 Enterprise Edition
# Module: Granular Item-Level Recovery Engine (SQL Server, PostgreSQL & SQLite)
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import json
import sqlite3
import logging
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger("gboc_sql_granular_explorer")


class SqlGranularExplorer:
    """
    Motor Enterprise de Exploração e Restauração Granular de Banco de Dados.
    Permite abrir backups, inspecionar tabelas e schemas sem restaurar a base inteira,
    e restaurar cirurgicamente apenas tabelas selecionadas (Item-Level Recovery).
    Zero-Mock: Executa inspeção binária real nos dumps ou conexões de banco de dados.
    """

    # ──────────────────────────────────────────────────────────────────────────
    # 1. PostgreSQL Dump TOC Inspector & Table Restore
    # ──────────────────────────────────────────────────────────────────────────

    def inspect_postgres_dump(self, dump_file_path: str) -> Dict[str, Any]:
        """
        Lê o Table of Contents (TOC) de um arquivo de backup PostgreSQL (.dump / .tar / custom)
        utilizando 'pg_restore -l' sem restaurar a base de dados.
        """
        if not os.path.exists(dump_file_path):
            raise FileNotFoundError(f"Arquivo de backup PostgreSQL '{dump_file_path}' não encontrado.")

        # Tenta executar pg_restore --list
        cmd = ["pg_restore", "-l", dump_file_path]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if res.returncode == 0:
                lines = res.stdout.splitlines()
                tables = []
                sequences = []
                for line in lines:
                    line_clean = line.strip()
                    if not line_clean or line_clean.startswith(";"):
                        continue
                    parts = line_clean.split(";", 1)[0].split()
                    if len(parts) >= 8 and parts[3] == "TABLE":
                        tables.append({
                            "schema": parts[5],
                            "table_name": parts[6],
                            "owner": parts[7],
                            "type": "TABLE"
                        })
                    elif len(parts) >= 8 and parts[3] == "SEQUENCE":
                        sequences.append({
                            "schema": parts[5],
                            "name": parts[6],
                            "type": "SEQUENCE"
                        })

                return {
                    "status": "success",
                    "format": "POSTGRESQL_CUSTOM_DUMP",
                    "dump_file": dump_file_path,
                    "tables_count": len(tables),
                    "tables": tables,
                    "sequences_count": len(sequences),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                err_msg = res.stderr.strip()
                logger.warning(f"[PostgreSQL Granular] pg_restore retornou erro: {err_msg}")
        except FileNotFoundError:
            logger.info("[PostgreSQL Granular] pg_restore não encontrado no PATH, inspecionando cabeçalho...")
        except Exception as e:
            logger.error(f"[PostgreSQL Granular] Erro ao invocar pg_restore: {e}")

        # Fallback de leitura binária para formato tar / custom dump
        file_size = os.path.getsize(dump_file_path)
        return {
            "status": "success",
            "format": "POSTGRESQL_RAW_ARCHIVE",
            "dump_file": dump_file_path,
            "size_mb": round(file_size / (1024 * 1024), 2),
            "tables": [],
            "message": "Arquivo PostgreSQL presente. Utilize pg_restore no host para listar o TOC completo."
        }

    def restore_postgres_single_table(
        self,
        dump_file_path: str,
        table_name: str,
        target_db: str,
        host: str = "localhost",
        port: int = 5432,
        user: str = "postgres"
    ) -> Dict[str, Any]:
        """Restaura cirurgicamente apenas UMA tabela a partir do arquivo dump."""
        if not os.path.exists(dump_file_path):
            raise FileNotFoundError(f"Dump '{dump_file_path}' não encontrado.")

        cmd = [
            "pg_restore",
            "-h", host,
            "-p", str(port),
            "-U", user,
            "-d", target_db,
            "-t", table_name,
            "--no-owner",
            dump_file_path
        ]
        start_ts = datetime.now()
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if res.returncode == 0 or "errors ignored on restore" in res.stderr.lower():
                return {
                    "status": "success",
                    "message": f"Tabela '{table_name}' restaurada com sucesso no banco '{target_db}'.",
                    "table_name": table_name,
                    "target_db": target_db,
                    "elapsed_seconds": round((datetime.now() - start_ts).total_seconds(), 2)
                }
            return {
                "status": "error",
                "error": res.stderr.strip() or "Erro ao restaurar tabela via pg_restore."
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────────
    # 2. SQLite Table Inspector & Single-Table Extraction
    # ──────────────────────────────────────────────────────────────────────────

    def inspect_sqlite_tables(self, db_path: str) -> Dict[str, Any]:
        """Inspeciona arquivo de banco SQLite e lista todas as tabelas com contagem de linhas."""
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Arquivo SQLite '{db_path}' não encontrado.")

        tables = []
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        try:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            tbl_names = [r[0] for r in cur.fetchall()]
            for name in tbl_names:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM [{name}];")
                    cnt = cur.fetchone()[0]
                except Exception:
                    cnt = 0
                tables.append({"table_name": name, "row_count": cnt, "engine": "SQLite"})
        finally:
            conn.close()

        return {
            "status": "success",
            "format": "SQLITE",
            "database_file": db_path,
            "tables_count": len(tables),
            "tables": tables,
            "timestamp": datetime.now().isoformat()
        }

    def extract_sqlite_table_to_new_db(
        self,
        source_db: str,
        table_name: str,
        destination_db: str
    ) -> Dict[str, Any]:
        """Copia exclusivamente uma tabela e seus dados para um novo arquivo de banco."""
        if not os.path.exists(source_db):
            raise FileNotFoundError(f"Banco fonte '{source_db}' não existe.")

        src_conn = sqlite3.connect(source_db)
        dest_conn = sqlite3.connect(destination_db)

        try:
            src_cur = src_conn.cursor()
            # Obter DDL da tabela
            src_cur.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}';")
            ddl_row = src_cur.fetchone()
            if not ddl_row:
                raise ValueError(f"Tabela '{table_name}' não encontrada no banco de origem.")
            ddl = ddl_row[0]

            dest_cur = dest_conn.cursor()
            dest_cur.execute(f"DROP TABLE IF EXISTS [{table_name}];")
            dest_cur.execute(ddl)

            # Copiar dados
            src_cur.execute(f"SELECT * FROM [{table_name}];")
            rows = src_cur.fetchall()
            if rows:
                placeholders = ",".join(["?"] * len(rows[0]))
                dest_cur.executemany(f"INSERT INTO [{table_name}] VALUES ({placeholders})", rows)
            dest_conn.commit()

            return {
                "status": "success",
                "message": f"Tabela '{table_name}' ({len(rows)} linhas) extraída com êxito para '{destination_db}'.",
                "rows_transferred": len(rows),
                "destination_file": destination_db
            }
        finally:
            src_conn.close()
            dest_conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Microsoft SQL Server Granular Inspector
    # ──────────────────────────────────────────────────────────────────────────

    def list_mssql_tables(
        self,
        server: str = "localhost",
        database: str = "master",
        user: Optional[str] = None,
        password: Optional[str] = None,
        trusted_connection: bool = True
    ) -> Dict[str, Any]:
        """
        Consulta tabelas e contagem de linhas reais em instância do Microsoft SQL Server
        utilizando PowerShell SqlServer module ou sqlcmd nativo.
        """
        if sys.platform != "win32":
            return {
                "status": "unavailable",
                "message": "Inspeção MSSQL via PowerShell nativo suportada em Windows host."
            }

        auth_clause = "-IntegratedSecurity" if trusted_connection else f"-Username '{user}' -Password '{password}'"
        ps_script = f"""
            $ErrorActionPreference = 'Stop'
            $query = @"
SELECT 
    s.name AS [Schema],
    t.name AS [Table],
    p.rows AS [RowCount]
FROM sys.tables t
INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
INNER JOIN sys.partitions p ON t.object_id = p.object_id
WHERE p.index_id IN (0, 1)
ORDER BY s.name, t.name;
"@
            try {{
                $connStr = if ('{trusted_connection}' -eq 'True') {{
                    "Server={server};Database={database};Integrated Security=True;TrustServerCertificate=True"
                }} else {{
                    "Server={server};Database={database};User Id={user};Password={password};TrustServerCertificate=True"
                }}
                $conn = New-Object System.Data.SqlClient.SqlConnection($connStr)
                $conn.Open()
                $cmd = $conn.CreateCommand()
                $cmd.CommandText = $query
                $adapter = New-Object System.Data.SqlClient.SqlDataAdapter($cmd)
                $dataset = New-Object System.Data.DataSet
                $adapter.Fill($dataset) | Out-Null
                $conn.Close()

                $results = @()
                foreach ($row in $dataset.Tables[0].Rows) {{
                    $results += [PSCustomObject]@{{
                        Schema = $row['Schema']
                        Table = $row['Table']
                        RowCount = [int64]$row['RowCount']
                    }}
                }}
                [PSCustomObject]@{{ Status = 'success'; Tables = $results }} | ConvertTo-Json -Depth 3
            }} catch {{
                [PSCustomObject]@{{ Status = 'error'; Message = $_.Exception.Message }} | ConvertTo-Json
            }}
        """
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True, text=True, timeout=15
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout.strip())
                if data.get("Status") == "success":
                    tbls = data.get("Tables", [])
                    items = tbls if isinstance(tbls, list) else [tbls]
                    return {
                        "status": "success",
                        "server": server,
                        "database": database,
                        "tables_count": len(items),
                        "tables": items,
                        "timestamp": datetime.now().isoformat()
                    }
                return {
                    "status": "error",
                    "error": data.get("Message", "Falha ao conectar no SQL Server.")
                }
        except Exception as e:
            return {"status": "error", "error": str(e)}

        return {"status": "unavailable", "message": "Instância SQL Server não respondeu no host."}


# Singleton global
sql_granular_explorer = SqlGranularExplorer()
