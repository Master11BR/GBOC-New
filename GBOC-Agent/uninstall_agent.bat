@echo off
:: ==============================================================================
:: GBOC System v13.2.0 Enterprise Edition
:: Desinstalador do GBOC Agent para Windows (CMD Batch Wrapper)
:: ==============================================================================

:: Verificar privilégios de Administrador
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERRO] Este desinstalador precisa ser executado como Administrador!
    echo Solicitando privilégios elevados...
    powershell -Command "Start-Process '%~0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall_agent.ps1"
pause
