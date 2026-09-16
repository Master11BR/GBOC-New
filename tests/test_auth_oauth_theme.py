#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes de Integridade da Autenticação, Provedores OAuth e Padrão de Iluminação Amber
GBOC System v14.4 Enterprise Edition
"""

import os
import sys
from pathlib import Path

# Adiciona GBOC-Server ao path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "GBOC-Server"))

def test_oauth_config_flags():
    import config
    assert hasattr(config, "AUTH_GOOGLE_ENABLED")
    assert hasattr(config, "AUTH_APPLE_ENABLED")
    assert isinstance(config.AUTH_GOOGLE_ENABLED, bool)
    assert isinstance(config.AUTH_APPLE_ENABLED, bool)

def test_available_themes_includes_amber():
    from modules.v2.system_v2_router import router
    # Verifica que o arquivo tokens.css contém o tema amber
    tokens_path = BASE_DIR / "GBOC-Server" / "static" / "ui" / "design-system" / "tokens.css"
    content = tokens_path.read_text(encoding="utf-8")
    assert 'data-color-theme="amber"' in content
    assert "--primary-color:    #f59e0b" in content or "--primary-color: #f59e0b" in content

def test_server_login_html_contains_v7_elements():
    login_path = BASE_DIR / "GBOC-Server" / "login.html"
    content = login_path.read_text(encoding="utf-8")

    # Verifica elementos do modelo V7 anexado
    assert "glow-pulse" in content
    assert "path-animate-1" in content
    assert "path-animate-2" in content
    assert "path-animate-3" in content
    assert "perspective-1000" in content
    assert "card-wrapper" in content

    # Verifica funções essenciais
    assert "switchForm" in content
    assert "togglePassword" in content
    assert "setIllumination" in content
    assert "handleOAuth" in content

    # Verifica botões Google e Apple
    assert "btn-oauth-google" in content
    assert "btn-oauth-apple" in content

def test_agent_login_html_parity():
    agent_login_path = BASE_DIR / "GBOC-Agent" / "static" / "login.html"
    content = agent_login_path.read_text(encoding="utf-8")

    assert "glow-pulse" in content
    assert "path-animate-1" in content
    assert "switchForm" in content
    assert "setIllumination" in content
    assert "btn-oauth-google" in content
    assert "btn-oauth-apple" in content

def test_system_wide_animated_background():
    # Verifica estilos globais no themes.css
    themes_css = (BASE_DIR / "GBOC-Server" / "gboc-themes.css").read_text(encoding="utf-8")
    assert "gboc-ambient-background" in themes_css
    assert "pulseGlow" in themes_css
    assert "drawLine" in themes_css
    assert "path-animate-1" in themes_css

    # Verifica injeção do background no layout manager (Server e Agent)
    server_lm = (BASE_DIR / "GBOC-Server" / "gboc-layout-manager.js").read_text(encoding="utf-8")
    agent_lm = (BASE_DIR / "GBOC-Agent" / "static" / "gboc-layout-manager.js").read_text(encoding="utf-8")
    assert "_ensureAnimatedBackgroundLoaded" in server_lm
    assert "_ensureAnimatedBackgroundLoaded" in agent_lm
    assert "gboc-ambient-background" in server_lm
    assert "gboc-ambient-background" in agent_lm

