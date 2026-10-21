@REM ==============================================================================
@REM GBOC System v14.8.2 Enterprise Edition
@REM Copyright (c) 2026 Master11BR - Todos os direitos reservados.
@REM Propriedade Intelectual & Direitos Autorais Registrados.
@REM ==============================================================================

@echo off
setlocal enabledelayedexpansion
REM "/service": execucao sem console (servico/tarefa agendada) - nao espera tecla
set "GBOC_PAUSE=pause"
if /i "%~1"=="/service" set "GBOC_PAUSE=rem"
CLS
REM ========================================
REM GBOC Server v14.8.2 - Inicializacao
REM ========================================

REM Garantir execução na pasta do script
cd /d "%~dp0"

echo.
echo ========================================
echo   GBOC Server v14.8.2 - Iniciando...
echo ========================================
echo.

REM Detectar Python: o mais novo instalado que ja tenha as dependencias do GBOC (scripts\gboc_python.ps1).
REM Nao fixa versao nem caminho: atualizar o Python (ex.: 3.14 -> 3.15, outra pasta) nao impede a inicializacao;
REM se a versao nova ainda nao tiver as dependencias, elas sao instaladas nela ou o sistema segue na anterior.
set "PYTHON_CMD="
set "PYEXE="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\gboc_python.ps1" -Root "%~dp0." -Component server`) do set "PYEXE=%%P"
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
echo Execute install_server.bat ou: python -m pip install -r requirements.txt
echo Detalhes em: logs\python_runtime.log
echo.
%GBOC_PAUSE%
exit /b 1

:python_found

REM Verificar se dependências estão instaladas
%PYTHON_CMD% -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Dependencias nao instaladas!
    echo Execute install_server.bat primeiro.
    echo.
    %GBOC_PAUSE%
    exit /b 1
)

REM Verificar se PostgreSQL esta acessivel
echo Verificando PostgreSQL em localhost:5432...
netstat -an | findstr LISTENING | findstr :5432 >nul
if not errorlevel 1 (
    echo [OK] PostgreSQL ja esta rodando.
    goto :pg_ready
)

echo PostgreSQL nao esta rodando. Tentando iniciar...

REM 1. Detectar servicos Windows PostgreSQL existentes (prioridade)
set PG_SERVICE=
REM Qualquer versao instalada (postgresql-x64-NN, postgresql-gboc...): nao depende de lista fixa de versoes
for /f "tokens=2 delims=: " %%S in ('sc query state^= all ^| findstr /i /r /c:"SERVICE_NAME: *postgres"') do set "PG_SERVICE=%%S"

if defined PG_SERVICE (
    echo Servico PostgreSQL detectado: %PG_SERVICE%
    net start "%PG_SERVICE%" >nul 2>&1
    echo Aguardando servico PostgreSQL...
    timeout /t 5 /nobreak >nul
    netstat -an | findstr LISTENING | findstr :5432 >nul
    if not errorlevel 1 (
        echo [OK] Servico PostgreSQL iniciado.
        goto :pg_ready
    )
    echo [AVISO] Servico PostgreSQL existe mas nao respondeu na porta 5432.
    echo         Verifique configuracao/porta da instancia instalada.
    goto :pg_fail
)

REM 2. Fallback: PostgreSQL portatil somente se nao houver servico instalado
if exist "C:\GBOC\Tools\PostgreSQL\pgsql\bin\pg_ctl.exe" (
    echo Nenhum servico PostgreSQL instalado detectado. Usando PostgreSQL portatil...
    start "" "C:\GBOC\Tools\PostgreSQL\pgsql\bin\pg_ctl.exe" start -D "C:\GBOC\Tools\PostgreSQL\data" -l "C:\GBOC\Tools\PostgreSQL\logfile.log"
    timeout /t 8 /nobreak >nul
    netstat -an | findstr LISTENING | findstr :5432 >nul
    if not errorlevel 1 (
        echo [OK] PostgreSQL portatil iniciado.
        goto :pg_ready
    )
    echo [AVISO] PostgreSQL portatil nao iniciou.
)

:pg_fail
echo.
echo [ERRO] PostgreSQL nao disponivel em localhost:5432
echo.
%GBOC_PAUSE%
exit /b 1

:pg_ready
echo.

echo [OK] Iniciando GBOC Server...
echo Comando Python: %PYTHON_CMD%
for %%I in (server_gboc.py) do echo Script: %%~fI
echo.

REM Validar sintaxe do script alvo antes de subir
%PYTHON_CMD% -m py_compile server_gboc.py >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Erro de sintaxe detectado em server_gboc.py
    %PYTHON_CMD% -m py_compile server_gboc.py
    echo.
    %GBOC_PAUSE%
    exit /b 1
)

echo Servidor disponivel em:
echo   - https://localhost:8000  (HTTPS/HTTP2)
echo   - http://localhost:8079   (redireciona automaticamente para HTTPS)
echo   - WebSocket: wss://0.0.0.0:8000/ws
echo   - API Docs: https://0.0.0.0:8000/api/docs
echo.
echo Aguardando conexoes de agentes...
echo.
echo Pressione Ctrl+C para parar o servidor
echo.
echo ========================================
echo.

REM Iniciar o servidor (PYTHONIOENCODING=utf-8 evita crash do Hypercorn com caracteres Unicode no Windows)
set PYTHONIOENCODING=utf-8
REM Python 3.15+ usa UTF-8 por padrao; a saida dos comandos do Windows e cp850/cp1252 (mantem o comportamento anterior)
if not defined PYTHONUTF8 set PYTHONUTF8=0
%PYTHON_CMD% -u server_gboc.py

echo.
echo Servidor encerrado.
%GBOC_PAUSE%