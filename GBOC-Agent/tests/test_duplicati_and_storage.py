#!/usr/bin/env python3
"""
Testes unitários e de integração para criação de jobs Duplicati,
criação automática de repositórios ao importar, e histórico de crescimento de storage.
"""

import os
import sys
import pytest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.integrations.duplicati_native import get_duplicati_native_service
from engines.storage_monitor import collect_repository_sizes, get_storage_history
from engines.backup_importer import RealBackupImporter
from shared_core import get_shared_core


def test_duplicati_service_list_and_normalize():
    service = get_duplicati_native_service()
    res = service.list_backups()
    assert res.get("status") == "success"
    items = res.get("items", [])
    assert isinstance(items, list)
    for item in items:
        assert "id" in item
        assert "name" in item
        assert "target_label" in item
        assert "last_run" in item
        assert "last_status" in item


def test_storage_monitor_collection_and_history():
    # Coletar tamanhos reais
    sizes = collect_repository_sizes()
    assert isinstance(sizes, list)
    assert len(sizes) > 0

    # Verificar se histórico retorna dados sem erro de SQL
    history = get_storage_history(days=30)
    assert isinstance(history, list)
    assert len(history) > 0

    # Testar histórico filtrado por repositório específico
    first_repo_id = sizes[0]["repository_id"]
    repo_history = get_storage_history(repository_id=first_repo_id, days=30)
    assert isinstance(repo_history, list)


def test_backup_importer_creates_repositories():
    core = get_shared_core()
    importer = RealBackupImporter(core)
    res = importer.import_all_to_native()
    assert res.get("status") == "success"

    # Verificar se todas as tarefas duplicati possuem repository_id preenchido
    with core.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, repository_id FROM tasks WHERE engine = 'duplicati'")
        dup_tasks = cur.fetchall()
        for t_id, t_name, repo_id in dup_tasks:
            assert repo_id is not None, f"Tarefa {t_name} (#{t_id}) está sem repository_id"
