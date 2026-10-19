@REM ==============================================================================
@REM GBOC System v14.8.1 Enterprise Edition
@REM Copyright (c) 2026 Master11BR - Todos os direitos reservados.
@REM Propriedade Intelectual & Direitos Autorais Registrados.
@REM ==============================================================================

@echo off
setlocal enabledelayedexpansion
REM "/service": execucao sem console (servico/tarefa agendada) - nao espera tecla
set "GBOC_PAUSE=pause"
if /i "%~1"=="/service" set "GBOC_PAUSE=rem"
CLS
title GBOC Scheduler Agent - Background Worker (v14.8.1)
color 0B

echo.
echo ======================================================================
echo   GBOC System v14.8.1 - Agente Autonomo de Backup e Restore Agendado
echo ======================================================================
echo.

cd /d "%~dp0"

REM Detectar Python: o mais novo instalado que ja tenha as dependencias do GBOC (scripts\gboc_python.ps1).
REM Nao fixa versao nem caminho: atualizar o Python (ex.: 3.14 -> 3.15, outra pasta) nao impede a inicializacao;
REM se a versao nova ainda nao tiver as dependencias, elas sao instaladas nela ou o sistema segue na anterior.
set "PYTHON_CMD="
set "PYEXE="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\gboc_python.ps1" -Root "%~dp0." -Component scheduler`) do set "PYEXE=%%P"
if defined PYEXE (
    set PYTHON_CMD="!PYEXE!"
    goto :python_found
)

echo [AVISO] Selecao automatica do Python indisponivel. Tentando o Python padrao do sistema...
py -3 -c "import fastapi" >nul 2>&1
if !errorlevel! equ 0 (
    set PYTHON_CMD=py -3
    goto :python_found
)
python -c "import fastapi" >nul 2>&1
if !errorlevel! equ 0 (
    set PYTHON_CMD=python
    goto :python_found
)

echo [ERRO] Nenhum Python com as dependencias do GBOC foi encontrado.
echo Execute install_agent.ps1 (como Administrador) ou: python -m pip install -r requirements.txt
echo Detalhes em: logs\python_runtime.log
echo.
%GBOC_PAUSE%
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
REM Qualquer versao instalada (postgresql-x64-NN, postgresql-gboc...): nao depende de lista fixa de versoes
for /f "tokens=2 delims=: " %%S in ('sc query state^= all ^| findstr /i /r /c:"SERVICE_NAME: *postgres"') do set "PG_SERVICE=%%S"

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

REM Python 3.15+ usa UTF-8 por padrao; a saida dos comandos do Windows e cp850/cp1252 (mantem o comportamento anterior)
if not defined PYTHONUTF8 set PYTHONUTF8=0
%PYTHON_CMD% start_scheduler.py

echo.
echo [!] Agente do Scheduler encerrado.
%GBOC_PAUSE%