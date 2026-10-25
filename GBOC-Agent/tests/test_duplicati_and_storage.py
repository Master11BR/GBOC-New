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


def test_duplicati_target_parsing_and_b2_distinction():
    """Garante que destinos Duplicati não sejam falsamente classificados como B2 devido a substrings genéricas."""
    from core.integrations.duplicati_native import parse_duplicati_target_and_creds, get_duplicati_target_label

    cases = [
        # Wasabi
        ("s3://gboc-26/GBOC-server?s3-server-name=s3.eu-central-2.wasabisys.com&auth-username=AKIA&auth-password=SECRET", "wasabi", "Wasabi S3 Cloud"),
        # Amazon S3 padrão
        ("s3://empresa-backups/sub2/files?s3-server-name=s3.amazonaws.com&auth-username=AKIA&auth-password=SECRET", "s3", "Amazon S3 Cloud"),
        # S3 com caminho ou senha contendo "db2" ou "b2"
        ("s3://prod-db2-backup/daily?s3-server-name=s3.amazonaws.com&auth-username=user_b2&auth-password=pwd_b2_test", "s3", "Amazon S3 Cloud"),
        # Real Backblaze B2 nativo
        ("b2://my-b2-bucket/folder?auth-username=b2keyid&auth-password=b2key", "b2", "Backblaze B2 (Nativo)"),
        # Real Backblaze B2 via endpoint S3
        ("s3://b2-bucket/folder?s3-server-name=s3.us-west-004.backblazeb2.com", "b2", "Backblaze B2 (S3 API)"),
        # Azure Blob
        ("azure://container/folder?azure-account-name=myacc&azure-access-key=key", "azure", "Azure Blob Storage"),
        # Local
        ("file://C:\\GBOC-Backups\\job2", "local", "Disco Local / Pasta em Rede"),
        ("C:\\GBOC-Backups\\sub2", "local", "Disco Local / Pasta em Rede"),
        # Cifrado enc-v1 (não deve classificar como B2)
        ("enc-v1:B0EC2DD70BE266994F5C73CCF57EC3D330071A1385871B93F8FC7110D0893B9F", "cloud", "Destino Cifrado (Duplicati enc-v1)"),
    ]

    for url, exp_type, exp_label in cases:
        parsed = parse_duplicati_target_and_creds(url)
        assert parsed["repo_type"] == exp_type, f"Falha no tipo para '{url}': esperado {exp_type}, obtido {parsed['repo_type']}"
        assert parsed["target_label"] == exp_label, f"Falha no label para '{url}': esperado {exp_label}, obtido {parsed['target_label']}"
        if exp_type != "b2":
            assert "b2_account_id" not in parsed["config"], f"Config de '{exp_type}' não deve ter b2_account_id"
            assert "b2_account_key" not in parsed["config"], f"Config de '{exp_type}' não deve ter b2_account_key"
        else:
            assert "b2_account_id" in parsed["config"], f"Config de B2 deve ter b2_account_id"
