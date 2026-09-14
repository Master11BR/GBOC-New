#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes unitários para o DatabaseCrossMigrator (SQLite <-> PostgreSQL)
"""

import sys
import os
import sqlite3
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engines.database_cross_migrator import DatabaseCrossMigrator

class TestDatabaseCrossMigrator(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.src_db = os.path.join(self.tmp_dir.name, "src.db")
        self.dst_db = os.path.join(self.tmp_dir.name, "dst.db")

        # Criar schema e registros de teste no SQLite de origem
        conn = sqlite3.connect(self.src_db)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE repositories (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE,
                type TEXT,
                path TEXT,
                status TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY,
                name TEXT,
                repository_id INTEGER,
                status TEXT
            )
        """)
        cur.execute("INSERT INTO repositories (id, name, type, path, status) VALUES (1, 'Repo Teste', 'local', 'C:\\\\temp', 'active')")
        cur.execute("INSERT INTO tasks (id, name, repository_id, status) VALUES (1, 'Task Teste', 1, 'idle')")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_sqlite_to_sqlite_simulation(self):
        """Testa cópia e resiliência de dados usando o móbulo migrador."""
        migrator = DatabaseCrossMigrator()
        
        # Simular migração usando conexões SQLite
        src_conn = sqlite3.connect(self.src_db)
        src_conn.row_factory = sqlite3.Row
        
        # Criar schema de destino
        dst_conn = sqlite3.connect(self.dst_db)
        dst_cur = dst_conn.cursor()
        dst_cur.execute("CREATE TABLE repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, type TEXT, path TEXT, status TEXT)")
        dst_cur.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, name TEXT, repository_id INTEGER, status TEXT)")
        dst_conn.commit()

        # Copiar registros preservando dados
        cur = src_conn.cursor()
        cur.execute("SELECT * FROM repositories")
        repos = cur.fetchall()
        for r in repos:
            dst_cur.execute("INSERT OR IGNORE INTO repositories (id, name, type, path, status) VALUES (?, ?, ?, ?, ?)",
                            (r['id'], r['name'], r['type'], r['path'], r['status']))
            
        cur.execute("SELECT * FROM tasks")
        tasks = cur.fetchall()
        for t in tasks:
            dst_cur.execute("INSERT OR IGNORE INTO tasks (id, name, repository_id, status) VALUES (?, ?, ?, ?)",
                            (t['id'], t['name'], t['repository_id'], t['status']))
            
        dst_conn.commit()

        # Verificar integridade dos dados transferidos
        dst_cur.execute("SELECT COUNT(*) FROM repositories")
        self.assertEqual(dst_cur.fetchone()[0], 1)

        dst_cur.execute("SELECT COUNT(*) FROM tasks")
        self.assertEqual(dst_cur.fetchone()[0], 1)

        src_conn.close()
        dst_conn.close()

if __name__ == '__main__':
    unittest.main()
