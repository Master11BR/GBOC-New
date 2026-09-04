@echo off
REM ==============================================================================
REM GBOC System v14.0.0 Full Stable Enterprise Edition
REM Copyright (c) 2026 Master11BR. Todos os direitos reservados.
REM ==============================================================================

setlocal EnableDelayedExpansion
title Instalador GBOC System v14.0.0 Enterprise

REM Verifica privilégios de Administrador
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Solicitando privilegios de Administrador...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb runAs"
    exit /b
)

cd /d "%~dp0"

echo ========================================================
echo   Iniciando Instalador GBOC Enterprise...
echo ========================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup.ps1"

if %errorlevel% neq 0 (
    echo.
    echo [ERRO] A instalacao foi interrompida ou ocorreu uma falha.
    pause
)
