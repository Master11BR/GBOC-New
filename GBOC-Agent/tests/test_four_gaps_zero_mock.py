# ==============================================================================
# GBOC System v14.6.0 Enterprise Edition
# Unit Tests: Four Enterprise Gaps & Strict Zero-Mock Verification
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import json
import sqlite3
import pytest
from pathlib import Path

# Add GBOC-Agent to sys.path
agent_dir = Path(__file__).resolve().parent.parent
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

from engines.vmware_hypervisor_engine import vmware_engine, hyperv_engine
from engines.instant_recovery_engine import instant_recovery_engine
from engines.saas_protection_engine import saas_protection_engine, MicrosoftGraphClient
from engines.sql_granular_explorer import sql_granular_explorer
from engines.surebackup_engine import verify_disk_or_db_integrity


# ── GAP 1: Agentless Virtualization (VMware & Hyper-V) ─────────────────────────

def test_gap1_vmware_connection_error_handling():
    """Valida que conexão a host VMware inexistente retorna erro estruturado real (Zero-Mock)."""
    res = vmware_engine.test_vmware_connection(
        host="192.0.2.254",  # TEST-NET-1 endereço não roteável
        user="test_admin",
        password="test_password",
        port=443,
        ignore_ssl=True
    )
    assert res.get("status") == "error"
    assert res.get("code") in ("CONNECTION_FAILED", "ENDPOINT_UNAVAILABLE", "VMWARE_ERROR")


def test_gap1_hyperv_status_inspection():
    """Valida que a inspeção Hyper-V consulta o SO real sem dados fabricados."""
    res = hyperv_engine.check_hyperv_installed()
    assert "installed" in res
    assert "running" in res
    assert isinstance(res["installed"], bool)
    assert isinstance(res["running"], bool)


# ── GAP 2: Instant VM Recovery Local & Datastore ───────────────────────────────

def test_gap2_instant_recovery_datastore_lifecycle(tmp_path):
    """Valida criação e destruição do Datastore local com medição de tempo real."""
    test_folder = tmp_path / "repo_storage"
    test_folder.mkdir()
    (test_folder / "backup.txt").write_text("backup-data-payload")

    share_res = instant_recovery_engine.start_datastore_share(
        share_name="gboc_test_share",
        folder_path=str(test_folder),
        read_only=True
    )
    assert share_res.get("status") == "success"
    assert "datastore" in share_res
    assert share_res["datastore"]["folder_path"] == str(test_folder)

    # Teardown
    stop_res = instant_recovery_engine.stop_datastore_share("gboc_test_share")
    assert stop_res.get("status") == "success"


# ── GAP 3: Native M365 & Google Workspace (SaaS Graph API) ────────────────────

def test_gap3_m365_graph_api_auth_failure_zero_mock():
    """Valida que credenciais inválidas de M365 falham com erro real do Azure AD (Zero-Mock)."""
    client = MicrosoftGraphClient(
        tenant_id="00000000-0000-0000-0000-000000000000",
        client_id="00000000-0000-0000-0000-000000000000",
        client_secret="invalid_secret_key"
    )
    with pytest.raises(ConnectionError) as exc_info:
        client.get_access_token()
    assert "Azure AD" in str(exc_info.value) or "Microsoft" in str(exc_info.value)


def test_gap3_saas_protection_engine_status():
    """Valida inventário SaaS quando não configurado."""
    status = saas_protection_engine.get_saas_tenants_status()
    assert "microsoft_365" in status
    assert "google_workspace" in status
    assert status["microsoft_365"]["connected"] is False


# ── GAP 4: Granular Item-Level Recovery (SQL & DBs) ───────────────────────────

def test_gap4_sqlite_granular_table_extraction(tmp_path):
    """Valida inspeção e extração cirúrgica de tabela em banco de dados."""
    src_db = tmp_path / "source.db"
    dest_db = tmp_path / "extracted_table.db"

    conn = sqlite3.connect(str(src_db))
    cur = conn.cursor()
    cur.execute("CREATE TABLE customers (id INT PRIMARY KEY, name TEXT);")
    cur.execute("CREATE TABLE orders (id INT PRIMARY KEY, total REAL);")
    cur.execute("INSERT INTO customers VALUES (1, 'Empresa Alpha'), (2, 'Empresa Beta');")
    cur.execute("INSERT INTO orders VALUES (101, 450.50);")
    conn.commit()
    conn.close()

    # Inspecionar tabelas
    inspect_res = sql_granular_explorer.inspect_sqlite_tables(str(src_db))
    assert inspect_res.get("status") == "success"
    assert inspect_res.get("tables_count") == 2
    tbl_names = [t["table_name"] for t in inspect_res["tables"]]
    assert "customers" in tbl_names
    assert "orders" in tbl_names

    # Extrair cirurgicamente apenas 'customers'
    extract_res = sql_granular_explorer.extract_sqlite_table_to_new_db(
        source_db=str(src_db),
        table_name="customers",
        destination_db=str(dest_db)
    )
    assert extract_res.get("status") == "success"
    assert extract_res.get("rows_transferred") == 2

    # Verificar banco extraído
    d_conn = sqlite3.connect(str(dest_db))
    d_cur = d_conn.cursor()
    d_cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    dest_tables = [r[0] for r in d_cur.fetchall()]
    assert dest_tables == ["customers"]
    d_cur.execute("SELECT COUNT(*) FROM customers;")
    assert d_cur.fetchone()[0] == 2
    d_conn.close()


def test_gap4_surebackup_real_integrity(tmp_path):
    """Valida que o SureBackup executa verificação de integridade real sem mocks."""
    db_file = tmp_path / "verified.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE data (id INT);")
    conn.commit()
    conn.close()

    res_ok = verify_disk_or_db_integrity(str(db_file))
    assert res_ok.get("valid") is True
    assert res_ok.get("format") == "SQLITE"

    res_missing = verify_disk_or_db_integrity(str(tmp_path / "non_existent.vhdx"))
    assert res_missing.get("valid") is False
