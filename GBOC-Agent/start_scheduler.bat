@REM ==============================================================================
@REM GBOC System v13.2.0 Enterprise Edition
@REM Copyright (c) 2026 Master11BR - Todos os direitos reservados.
@REM Propriedade Intelectual & Direitos Autorais Registrados.
@REM ==============================================================================

@echo off
setlocal enabledelayedexpansion
CLS
title GBOC Scheduler Agent - Background Worker (v13.2.0)
color 0B

echo.
echo ======================================================================
echo   GBOC System v13.2.0 - Agente Autonomo de Backup e Restore Agendado
echo ======================================================================
echo.

cd /d "%~dp0"

REM Detectar comando Python
set PYTHON_CMD=

REM Preferir Python 3.14 explicitamente
py -3.14 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py -3.14
    goto :python_found
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    goto :python_found
)

py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py
    goto :python_found
)

python3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python3
    goto :python_found
)

echo [ERRO] Python nao encontrado!
echo Instale o Python 3.14 ou superior antes de executar.
echo.
pause
exit /b 1

:python_found

REM Verificar se PostgreSQL esta acessivel
echo [1/2] Verificando PostgreSQL em localhost:5432...
netstat -an | findstr LISTENING | findstr :5432 >nul
if not errorlevel 1 (
    echo [OK] PostgreSQL ativo e respondendo.
    goto :pg_ready
)

echo PostgreSQL nao esta respondendo. Tentando iniciar servico...

REM 1. Detectar servicos Windows PostgreSQL existentes
set PG_SERVICE=
for %%S in (postgresql-x64-18 postgresql-x64-17 postgresql-x64-16 postgresql-x64-15) do (
    sc query "%%S" >nul 2>&1
    if !errorlevel! equ 0 set PG_SERVICE=%%S
)

if defined PG_SERVICE (
    echo Servico PostgreSQL detectado: %PG_SERVICE%
    net start "%PG_SERVICE%" >nul 2>&1
    timeout /t 4 /nobreak >nul
    netstat -an | findstr LISTENING | findstr :5432 >nul
    if not errorlevel 1 (
        echo [OK] Servico PostgreSQL iniciado com sucesso.
        goto :pg_ready
    )
)

REM 2. Fallback portátil
if exist "C:\GBOC\Tools\PostgreSQL\pgsql\bin\pg_ctl.exe" (
    echo Usando PostgreSQL portatil em C:\GBOC\Tools\PostgreSQL...
    start "" "C:\GBOC\Tools\PostgreSQL\pgsql\bin\pg_ctl.exe" start -D "C:\GBOC\Tools\PostgreSQL\data" -l "C:\GBOC\Tools\PostgreSQL\logfile.log"
    timeout /t 5 /nobreak >nul
    netstat -an | findstr LISTENING | findstr :5432 >nul
    if not errorlevel 1 (
        echo [OK] PostgreSQL portatil iniciado.
        goto :pg_ready
    )
)

echo.
echo [AVISO] PostgreSQL nao respondeu imediatamente. O Scheduler tentara reconectar automaticamente.
echo.

:pg_ready
echo.
echo [2/2] Iniciando o Agente de Inicializacao do Scheduler...
echo Comando: %PYTHON_CMD% start_scheduler.py
echo.
echo [!] Pressione Ctrl+C para encerrar o servico.
echo ======================================================================
echo.

%PYTHON_CMD% start_scheduler.py

echo.
echo [!] Agente do Scheduler encerrado.
pause
