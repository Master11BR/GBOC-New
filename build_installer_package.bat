@echo off
REM ==============================================================================
REM GBOC System v14.0.0 Enterprise Edition
REM Launcher para gerar o pacote de instalacao completo
REM ==============================================================================

cd /d "%~dp0"
title Gerador de Pacote GBOC Enterprise

echo ========================================================
echo   Gerando Pacote de Instalacao GBOC...
echo ========================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_installer_package.ps1"

if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Ocorreu uma falha ao gerar o pacote.
    pause
    exit /b %errorlevel%
)

echo.
pause
