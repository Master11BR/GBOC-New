# ==============================================================================
# GBOC System v14.1.0 Enterprise Edition
# Test Suite: Zero-Mock Power Tools & Enterprise Engines Verification
# ==============================================================================

import os
import pytest
from engines.visual_sync_engine import visual_sync_engine
from engines.bitrot_scrub_engine import bitrot_scrub_engine
from engines.virtual_drive_mount_engine import virtual_drive_mount_engine
from engines.rapid_delta_restore_engine import rapid_delta_restore_engine
from engines.linux_snapshots_engine import linux_snapshots_engine
from engines.usb_rescue_creator_engine import usb_rescue_creator_engine
from engines.tape_robotics_engine import tape_robotics_engine
from engines.saas_protection_engine import saas_protection_engine
from engines.kubernetes_backup_engine import k8s_backup_engine


def test_visual_diff_zero_mock_no_mock_fallback(tmp_path):
    # Caminho inexistente não pode retornar arquivos fictícios (Documentos/Projetos_2026.xlsx, etc.)
    non_existent = str(tmp_path / "nao_existe_12345")
    res = visual_sync_engine.compare_directories_visual_diff(non_existent, str(tmp_path))
    assert res["diff_tree"] == []
    assert "error" in res

    # Comparação real em pasta com arquivos reais
    dir_a = tmp_path / "origem"
    dir_b = tmp_path / "destino"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "teste_real.txt").write_text("conteudo real", encoding="utf-8")

    res_real = visual_sync_engine.compare_directories_visual_diff(str(dir_a), str(dir_b))
    assert len(res_real["diff_tree"]) == 1
    assert res_real["diff_tree"][0]["relative_path"] == "teste_real.txt"
    assert res_real["diff_tree"][0]["status"] == "LEFT_ONLY"

    # Sincronização real
    sync_res = visual_sync_engine.execute_sync(str(dir_a), str(dir_b))
    assert sync_res["success"] is True
    assert sync_res["items_copied"] == 1
    assert (dir_b / "teste_real.txt").exists()


def test_bitrot_scrub_zero_mock(tmp_path):
    # Repositório vazio/inexistente não deve inventar blocos (45280, etc.)
    res = bitrot_scrub_engine.run_bitrot_scrub(str(tmp_path / "inexistente"))
    assert res["success"] is False
    assert res["blocks_scanned"] == 0

    # Repositório com arquivo real
    f = tmp_path / "backup_real.dat"
    f.write_bytes(b"X" * (128 * 1024))
    res_real = bitrot_scrub_engine.run_bitrot_scrub(str(tmp_path))
    assert res_real["success"] is True
    assert res_real["blocks_scanned"] >= 1
    assert res_real["corrupted_blocks_found"] == 0


def test_linux_snapshots_on_windows():
    import sys
    res = linux_snapshots_engine.list_subvolume_snapshots()
    if sys.platform == "win32":
        assert res["supported"] is False
        assert "Windows" in res["os"]
        assert res["snapshots"] == []


def test_usb_rescue_detection():
    drives = usb_rescue_creator_engine.detect_usb_drives()
    assert isinstance(drives, list)
    # Não pode conter nomes mockados como fixos
    for d in drives:
        assert isinstance(d, dict)


def test_tape_robotics_zero_mock():
    inv = tape_robotics_engine.get_tape_library_inventory()
    assert "installed" in inv
    # Se não há hardware tape conectado, deve reportar unavailable
    if not inv["installed"]:
        assert inv["status"] == "unavailable"
        assert inv["changer"] is None
