@REM ==============================================================================
@REM GBOC System v14.0.0 Enterprise Edition
@REM Copyright (c) 2026 Master11BR - Todos os direitos reservados.
@REM Propriedade Intelectual & Direitos Autorais Registrados.
@REM ==============================================================================

@echo off
REM ========================================
REM GBOC Agent v14.0.0 - Instalador COMPLETO
REM Inclui PostgreSQL e outras dependências avançadas
REM Requer: Build Tools e PostgreSQL instalados
REM ========================================

echo.
echo ========================================
echo   GBOC Agent v14.0.0 - Instalador COMPLETO
echo   (Inclui PostgreSQL e deps avancadas)
echo ========================================
echo.
echo AVISO: Este instalador requer:
echo   - Microsoft Build Tools
echo   - PostgreSQL (se usar psycopg2)
echo   - Rust (se usar versoes novas pydantic)
echo.
echo Se nao tiver esses pre-requisitos, use:
echo   install_agent.bat (versao simples)
echo.
pause

REM Detectar comando Python
set PYTHON_CMD=
py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py
    goto :python_found
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    goto :python_found
)

echo [ERRO] Python nao encontrado!
pause
exit /b 1

:python_found
echo [OK] Python encontrado: %PYTHON_CMD%
echo.

echo Instalando dependencias completas...
%PYTHON_CMD% -m pip install --upgrade pip
%PYTHON_CMD% -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [ERRO] Falha na instalacao completa!
    echo.
    echo Recomendacao: Use install_agent.bat ao inves deste.
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] Instalacao completa concluida!
pause
