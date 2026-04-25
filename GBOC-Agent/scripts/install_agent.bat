@echo off
cls
REM ========================================
REM GBOC Agent v11.4a - Instalador Windows
REM PostgreSQL + SQLite fallback
REM ========================================

echo.
echo ========================================
echo   GBOC Agent v11.4a - Instalador
echo   (PostgreSQL habilitado)
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
pause
exit /b 1

:python_found
echo [1/5] Python encontrado:
%PYTHON_CMD% --version
echo Comando: %PYTHON_CMD%
echo.

REM Verificar versão Python
for /f "tokens=2" %%i in ('%PYTHON_CMD% --version 2^>^&1') do set PY_VERSION=%%i
echo Versao Python: %PY_VERSION%
echo.

echo [2/5] Atualizando pip...
%PYTHON_CMD% -m pip install --upgrade pip
echo.

echo [3/5] Instalando dependencias do GBOC Agent...
echo Isso pode levar alguns minutos...
echo.
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [AVISO] Algumas dependencias podem ter falhado.
    echo Tentando fallback com requirements_minimal.txt...
    %PYTHON_CMD% -m pip install -r requirements_minimal.txt
    if errorlevel 1 (
        echo.
        echo [AVISO] Fallback falhou. Tentando componentes criticos...
        %PYTHON_CMD% -m pip install "fastapi==0.135.1" "uvicorn==0.41.0" "pydantic==2.12.5" "pydantic-core==2.41.5" "starlette==0.52.1" requests psutil websockets
    )
    echo.
)

echo.
echo [4/5] Instalando PostgreSQL driver (psycopg2-binary)...
echo.

REM Tentar instalar psycopg2-binary (pré-compilado)
%PYTHON_CMD% -m pip install --only-binary :all: psycopg2-binary
if errorlevel 1 (
    echo [AVISO] Não foi possível instalar psycopg2-binary pré-compilado
    echo Sistema funcionará com SQLite
    echo.
    echo Para usar PostgreSQL, instale manualmente:
    echo   1. Baixe: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
    echo   2. Depois: py -m pip install psycopg2-binary
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
    %PYTHON_CMD% -m pip install --force-reinstall --no-cache-dir "pydantic==2.12.5" "pydantic-core==2.41.5" "fastapi==0.135.1" "starlette==0.52.1" "uvicorn==0.41.0"
    echo.
    echo Validando novamente...
    %PYTHON_CMD% -c "import pydantic_core; import pydantic; import fastapi; import uvicorn; import websockets; print('[OK] Stack FastAPI/Pydantic corrigida')"
)

set ALL_OK=1

echo Verificando modulos criticos:
%PYTHON_CMD% -c "import fastapi" 2>nul && (echo   [OK] fastapi) || (echo   [X] fastapi - CRITICO! & set ALL_OK=0)
%PYTHON_CMD% -c "import uvicorn" 2>nul && (echo   [OK] uvicorn) || (echo   [X] uvicorn - CRITICO! & set ALL_OK=0)
%PYTHON_CMD% -c "import requests" 2>nul && (echo   [OK] requests) || (echo   [X] requests - CRITICO! & set ALL_OK=0)
%PYTHON_CMD% -c "import psutil" 2>nul && (echo   [OK] psutil) || (echo   [!] psutil - recomendado)
%PYTHON_CMD% -c "import websockets" 2>nul && (echo   [OK] websockets) || (echo   [!] websockets - recomendado)
%PYTHON_CMD% -c "import psycopg2" 2>nul && (echo   [OK] psycopg2 - PostgreSQL habilitado) || (echo   [!] psycopg2 ausente - usando SQLite)

echo.

if %ALL_OK%==0 (
    echo ========================================
    echo   ERRO: Modulos criticos faltando!
    echo ========================================
    echo.
    echo Tente:
    echo 1. Usar Python 3.14 (recomendado)
    echo 2. Reexecutar: install_agent.bat
    echo 3. Instalar manualmente:
    echo    py -m pip install "pydantic==2.12.5" "pydantic-core==2.41.5" "fastapi==0.135.1" "starlette==0.52.1" "uvicorn==0.41.0"
    echo.
    pause
    exit /b 1
)

echo ========================================
echo   Instalacao Concluida!
echo ========================================
echo.
echo PostgreSQL: habilitado quando psycopg2 estiver instalado.
echo Banco esperado do agente: gboc_agent.
echo.
echo Proximos passos:
echo   1. Execute: start_agent.bat
echo   2. Acesse: http://localhost:9200
echo.
pause
