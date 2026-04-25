@echo off
setlocal enabledelayedexpansion
CLS
REM ========================================
REM GBOC Agent v11.4a - Inicializacao
REM ========================================

echo.
echo ========================================
echo   GBOC Agent v11.4a - Iniciando...
echo ========================================
echo.

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
echo Execute install_agent.bat primeiro.
echo.
pause
exit /b 1

:python_found

REM Verificar se dependências estão instaladas
%PYTHON_CMD% -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Dependencias nao instaladas!
    echo Execute install_agent.bat primeiro.
    echo.
    pause
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
for %%S in (postgresql-x64-18 postgresql-x64-17 postgresql-x64-16 postgresql-x64-15) do (
    sc query "%%S" >nul 2>&1
    if !errorlevel! equ 0 set PG_SERVICE=%%S
)

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
pause
exit /b 1

:pg_ready
echo.

echo [OK] Iniciando GBOC Agent v11.4a...
echo Comando Python: %PYTHON_CMD%
echo.
echo Servidor disponivel em:
echo   - https://localhost:9200
echo   - Dashboard: https://localhost:9200/
echo   - Diagnostico: https://localhost:9200/diagnostic.html
echo   - API Docs: https://localhost:9200/docs
echo.
echo Pressione Ctrl+C para parar o servidor
echo.
echo ========================================
echo.

REM Iniciar o servidor (HTTP/2 + TLS via Hypercorn)
%PYTHON_CMD% start_server.py

echo.
echo Servidor encerrado.
pause
