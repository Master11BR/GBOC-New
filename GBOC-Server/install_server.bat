@REM ==============================================================================
@REM GBOC System v14.8.2 Enterprise Edition
@REM Copyright (c) 2026 Master11BR - Todos os direitos reservados.
@REM Propriedade Intelectual & Direitos Autorais Registrados.
@REM ==============================================================================

@echo off
cls
REM ========================================
REM GBOC Server v14.8.2 - Instalador Windows
REM ========================================

echo.
echo ========================================
echo   GBOC Server v14.8.2 - Instalador
echo ========================================
echo.

REM Python: ULTIMA versao estavel do python.org (reaproveita a instalada se ja for a mais nova) com as
REM dependencias do Server - scripts\gboc_prereqs.ps1. Se elas ainda nao instalarem na versao mais nova,
REM usa a anterior. O start_server.bat escolhe o Python sozinho: atualizar o Python depois nao quebra nada.
set "PYTHON_CMD="
set "PYEXE="
echo Verificando/instalando o Python mais recente (pode levar alguns minutos)...
set "GBOC_OUT=%TEMP%\gboc_py_path.txt"
del "%GBOC_OUT%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\gboc_prereqs.ps1" -Python -Requirements "%~dp0requirements.txt" -OutFile "%GBOC_OUT%"
if exist "%GBOC_OUT%" set /p PYEXE=<"%GBOC_OUT%"
if defined PYEXE if exist "%PYEXE%" (
    set PYTHON_CMD="%PYEXE%"
    goto :python_found
)

REM Sem internet/administrador: Python ja instalado (o launcher "py -3" usa a versao mais nova)
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py -3
    goto :python_found
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    goto :python_found
)

REM Python não encontrado
echo [ERRO] Python nao encontrado!
echo.
echo Instale o Python mais recente: https://www.python.org/downloads/
echo Durante a instalacao, marque "Add Python to PATH"
echo.
pause
exit /b 1

:python_found
echo [1/5] Python encontrado:
%PYTHON_CMD% --version
echo Comando: %PYTHON_CMD%
echo.

echo [2/5] Atualizando pip...
%PYTHON_CMD% -m pip install --upgrade pip
echo.

echo [3/5] Instalando dependencias do GBOC Server...
echo Isso pode levar alguns minutos...
echo.
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [AVISO] Algumas dependencias podem ter falhado.
    echo Tentando novamente componentes criticos...
    %PYTHON_CMD% -m pip install fastapi uvicorn psutil requests websockets
    echo.
)

echo.
echo [4/5] Instalando PostgreSQL driver (psycopg2-binary)...
echo.

REM Tentar instalar psycopg2-binary
%PYTHON_CMD% -m pip install --only-binary :all: psycopg2-binary
if errorlevel 1 (
    echo [AVISO] psycopg2-binary nao instalado
    echo Servidor funcionará com SQLite
) else (
    echo [OK] psycopg2-binary instalado - PostgreSQL habilitado!
)

echo.
echo [5/5] Verificando instalacao...
%PYTHON_CMD% -c "import fastapi; import uvicorn; import websockets; print('[OK] Dependencias principais')"
if errorlevel 1 (
    echo [AVISO] Falha ao importar FastAPI/Pydantic. Tentando auto-correcao...
    echo.
    echo Reinstalando stack FastAPI/Pydantic...
    %PYTHON_CMD% -m pip install --force-reinstall --no-cache-dir "pydantic==2.12.5" "pydantic-core==2.41.5" "fastapi==0.135.1" "starlette==0.52.1"
    echo.
    echo Validando novamente...
    %PYTHON_CMD% -c "import pydantic_core; import pydantic; import fastapi; import uvicorn; import websockets; print('[OK] Stack FastAPI/Pydantic corrigida')"
)

%PYTHON_CMD% -c "import psycopg2; print('[OK] psycopg2 - PostgreSQL habilitado')" 2>nul || echo [!] psycopg2 ausente - usando SQLite

echo.
echo ========================================
echo   Instalacao Concluida!
echo ========================================
echo.

REM ========================================
REM Configuração automática do banco de dados
REM ========================================

echo [6/6] Configurando banco de dados PostgreSQL...
echo.

set PSQL=

REM Localizar psql
if exist "C:\GBOC\Tools\PostgreSQL\pgsql\bin\psql.exe" (
    set PSQL=C:\GBOC\Tools\PostgreSQL\pgsql\bin\psql.exe
    set PGCTL=C:\GBOC\Tools\PostgreSQL\pgsql\bin\pg_ctl.exe
    set PGDATA=C:\GBOC\Tools\PostgreSQL\data
    echo [OK] PostgreSQL portatil encontrado
    goto :pg_found
)

REM PostgreSQL instalado (qualquer versao: servico, Program Files ou portatil) - a mais nova
set "PG_BIN="
set "GBOC_OUT=%TEMP%\gboc_pg_bin.txt"
del "%GBOC_OUT%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\gboc_prereqs.ps1" -Postgres -OutFile "%GBOC_OUT%" >nul 2>&1
if exist "%GBOC_OUT%" set /p PG_BIN=<"%GBOC_OUT%"
if defined PG_BIN if exist "%PG_BIN%\psql.exe" goto :pg_generic_ok
goto :pg_generic_next
:pg_generic_ok
set "PSQL=%PG_BIN%\psql.exe"
echo [OK] PostgreSQL encontrado: %PG_BIN%
goto :pg_found
:pg_generic_next

where psql >nul 2>&1
if %errorlevel% equ 0 (
    set PSQL=psql
    echo [OK] psql encontrado no PATH
    goto :pg_found
)

echo [AVISO] psql nao encontrado.
echo Instale o GBOC Agent primeiro (ele instala o PostgreSQL)
echo ou execute setup_database.sql manualmente.
goto :pg_done

:pg_found

REM Verificar se PostgreSQL está rodando
"%PSQL%" -U postgres -h localhost -c "SELECT 1;" >nul 2>&1
if %errorlevel% neq 0 (
    echo PostgreSQL nao esta rodando. Tentando iniciar...
    if defined PGCTL (
        start "" "%PGCTL%" start -D "%PGDATA%" -l "C:\GBOC\Tools\PostgreSQL\logfile.log"
        timeout /t 5 /nobreak >nul
        "%PSQL%" -U postgres -h localhost -c "SELECT 1;" >nul 2>&1
        if %errorlevel% neq 0 (
            echo [AVISO] Nao foi possivel iniciar PostgreSQL.
            echo Execute setup_database.bat manualmente apos iniciar o PostgreSQL.
            goto :pg_done
        )
        echo [OK] PostgreSQL iniciado
    ) else (
        echo [AVISO] PostgreSQL nao esta rodando e pg_ctl nao encontrado.
        echo Inicie o PostgreSQL e execute setup_database.bat.
        goto :pg_done
    )
)

echo [OK] PostgreSQL respondendo
echo.

REM Executar setup_database.sql
echo Criando banco de dados gboc...
"%PSQL%" -U postgres -h localhost -f "%~dp0setup_database.sql" 2>&1
if %errorlevel% equ 0 (
    echo.
    echo [OK] Banco de dados gboc configurado com sucesso!
    echo     Banco: gboc
    echo     Usuario: gboc_user
) else (
    echo.
    echo [AVISO] Houve avisos na criacao do banco.
    echo Verifique se o banco gboc foi criado corretamente.
)

:pg_done

echo.
echo Proximos passos:
echo   1. Execute: .\start_server.bat
echo.
pause
