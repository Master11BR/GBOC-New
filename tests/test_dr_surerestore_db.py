import os
import sys
import pytest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Adicionar caminhos para importação
sys.path.insert(0, str(Path(__file__).parent.parent / "GBOC-Agent"))
sys.path.insert(0, str(Path(__file__).parent.parent / "GBOC-Server"))

from engines import database_backup
from engines.virtual_lab_engine import virtual_lab_engine


def test_sqlite_test_restore_valid():
    """Testa restauração de banco SQLite válido com PRAGMA integrity_check."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT);")
        conn.execute("INSERT INTO test_table (name) VALUES ('GBOC Test');")
        conn.commit()
        conn.close()

        with patch.object(database_backup, "_query", return_value=[{"id": 1, "file_path": db_path, "connection_id": 1}]), \
             patch.object(database_backup, "get_connection", return_value={"id": 1, "db_type": "sqlite"}):
            res = database_backup.test_restore(1)
            assert res["success"] is True
            assert res.get("tables") == 1
            assert res.get("integrity") == "ok"
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_pg_restore_explicit_failure_on_error():
    """Testa se pg_restore falha explicitamente quando retorna código != 0."""
    with tempfile.NamedTemporaryFile(suffix=".pgdump", delete=False) as f:
        dump_path = f.name

    try:
        with patch.object(database_backup, "_query", return_value=[{"id": 2, "file_path": dump_path, "connection_id": 2}]), \
             patch.object(database_backup, "get_connection", return_value={"id": 2, "db_type": "postgresql", "host": "localhost", "port": 5432, "username": "postgres", "password": "x"}), \
             patch("psycopg2.connect") as mock_pg_conn, \
             patch("subprocess.run") as mock_subproc:

            mock_conn = MagicMock()
            mock_pg_conn.return_value = mock_conn

            # Mock subprocess retornando erro no pg_restore
            mock_res = MagicMock()
            mock_res.returncode = 1
            mock_res.stderr = "pg_restore: error: input file does not appear to be a valid archive"
            mock_res.stdout = ""
            mock_subproc.return_value = mock_res

            res = database_backup.test_restore(2)
            assert res["success"] is False
            assert "pg_restore falhou (código 1)" in res["error"]
    finally:
        if os.path.exists(dump_path):
            os.remove(dump_path)


def test_virtual_lab_status_handling():
    """Testa se o motor do Virtual Lab executa validação e retorna estados reais auditáveis."""
    res = virtual_lab_engine.run_isolated_boot_verification("snap-test-123", disk_path="non_existent_path.vhdx")
    assert "status" in res
    assert res["status"] in ["Aprovado", "Reprovado", "Inconclusivo", "Expirado"]
    assert "logs" in res
    assert len(res["logs"]) > 0
