#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for GBOC Watermarking & Verification Tool
================================================
"""

import os
import subprocess
import sys
import tempfile
import pytest

from tools.watermark_tool import (
    encode_watermark,
    decode_watermark,
    find_watermarks_in_text,
    strip_watermarks_from_text,
    embed_watermark_in_file,
    scan_path,
    generate_canary_code,
    ZW_REGEX
)


def test_encode_decode_watermark_roundtrip():
    payload = "GBOC_DEV_AUTHOR_PROOF_2026_KEYS_ABCD"
    encoded_zw = encode_watermark(payload)
    
    # Garantir que a string codificada contenha apenas caracteres de largura zero e delimitadores
    assert ZW_REGEX.search(encoded_zw) is not None
    
    # Decodificar
    decoded = decode_watermark(encoded_zw)
    assert decoded == payload


def test_find_watermarks_in_text():
    payload1 = "AUTORIA_PARTE_1"
    payload2 = "AUTORIA_PARTE_2"
    
    zw1 = encode_watermark(payload1)
    zw2 = encode_watermark(payload2)
    
    sample_text = f"def hello():\n    # Comment {zw1}\n    print('Hello World')\n    /* JS comment {zw2} */\n"
    
    matches = find_watermarks_in_text(sample_text)
    assert len(matches) == 2
    assert matches[0][1] == payload1
    assert matches[1][1] == payload2


def test_strip_watermarks_from_text():
    payload = "SECRET_WATERMARK"
    zw = encode_watermark(payload)
    original = "def foo(): return 42\n"
    watermarked = f"def foo():{zw} return 42\n"
    
    stripped = strip_watermarks_from_text(watermarked)
    assert stripped == original


def test_embed_and_scan_file():
    payload = "GBOC-TEST-SUITE-PAYLOAD-2026"
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_py_file = os.path.join(tmp_dir, "sample_module.py")
        with open(test_py_file, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n\ndef calculate():\n    return 100\n")
            
        # Inserir marca d'água
        success = embed_watermark_in_file(test_py_file, payload)
        assert success is True
        
        # Testar execução do arquivo Python alterado para garantir integridade sintática
        res = subprocess.run([sys.executable, test_py_file], capture_output=True, text=True)
        assert res.returncode == 0
        
        # Escanear arquivo
        report = scan_path(test_py_file)
        assert len(report) == 1
        assert report[0]["status"] == "WATERMARKED"
        assert report[0]["payload"] == payload


def test_generate_canary_code():
    dev_id = "DEV_GBOC_2026"
    canary = generate_canary_code(dev_id)
    
    assert canary["hex_constant"].startswith("0x")
    assert len(canary["sha256_hash"]) == 64
    assert dev_id in canary["python"]
    assert canary["hex_constant"] in canary["javascript"]
