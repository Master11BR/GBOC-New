@echo off
REM ===================================================
REM GBOC Server - Instalador Windows
REM Sistema de Gerenciamento Centralizado de Backups
REM ===================================================

echo.
echo ============================================
echo   GBOC Server - Instalacao para Windows
echo ============================================
echo.

REM Verifica se Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado!
    echo.
    echo Por favor, instale Python 3.8 ou superior:
    echo https://www.python.org/downloads/
    echo.
    echo Marque a opcao "Add Python to PATH" durante a instalacao
    pause
    exit /b 1
)

echo [OK] Python encontrado
python --version
echo.

REM Verifica se PostgreSQL esta instalado
psql --version >nul 2>&1
if errorlevel 1 (
    echo [AVISO] PostgreSQL nao encontrado!
    echo.
    echo Por favor, instale PostgreSQL 12 ou superior:
    echo https://www.postgresql.org/download/windows/
    echo.
    echo Apos instalar, execute novamente este script.
    pause
    exit /b 1
)

echo [OK] PostgreSQL encontrado
psql --version
echo.

REM Cria ambiente virtual
echo [1/6] Criando ambiente virtual Python...
if exist venv (
    echo     Ambiente virtual ja existe, pulando...
) else (
    python -m venv venv
    echo     [OK] Ambiente virtual criado
)
echo.

REM Ativa ambiente virtual e instala dependencias
echo [2/6] Instalando dependencias Python...
call venv\Scripts\activate.bat
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias
    pause
    exit /b 1
)
echo     [OK] Dependencias instaladas
echo.

REM Cria arquivo .env se nao existir
echo [3/6] Configurando variaveis de ambiente...
if exist .env (
    echo     [OK] Arquivo .env ja existe
) else (
    copy .env.example .env >nul
    echo     [OK] Arquivo .env criado
    echo.
    echo     IMPORTANTE: Edite o arquivo .env com suas credenciais!
    echo     Use o Bloco de Notas: notepad .env
    echo.
)
echo.

REM Solicita credenciais do PostgreSQL
echo [4/6] Configuracao do banco de dados...
echo.
echo Voce precisa criar o banco de dados GBOC no PostgreSQL.
echo.
echo Opcao 1 - Automatico (recomendado):
echo   Execute: psql -U postgres -f setup_database.sql
echo.
echo Opcao 2 - Manual:
echo   Abra pgAdmin ou psql e execute os comandos em setup_database.sql
echo.
set /p continuar="Banco de dados ja foi criado? (S/N): "
if /i not "%continuar%"=="S" (
    echo.
    echo Execute a criacao do banco e rode este script novamente.
    pause
    exit /b 0
)
echo.

REM Testa conexao com banco
echo [5/6] Testando conexao com banco de dados...
python -c "import psycopg2, os; from dotenv import load_dotenv; load_dotenv(); conn = psycopg2.connect(host=os.getenv('DB_HOST', 'localhost'), database=os.getenv('DB_NAME', 'gboc'), user=os.getenv('DB_USER', 'gboc_user'), password=os.getenv('DB_PASSWORD', 'gboc_password')); print('[OK] Conexao bem-sucedida'); conn.close()" 2>nul
if errorlevel 1 (
    echo [AVISO] Nao foi possivel conectar ao banco
    echo          Verifique as credenciais no arquivo .env
    echo.
) else (
    echo     [OK] Conexao com banco de dados OK
    echo.
)

REM Cria atalho para iniciar servidor
echo [6/6] Criando atalhos...
echo @echo off > start_server.bat
echo call venv\Scripts\activate.bat >> start_server.bat
echo python gboc_server.py >> start_server.bat
echo     [OK] Atalho criado: start_server.bat
echo.

echo ============================================
echo   Instalacao Concluida!
echo ============================================
echo.
echo Proximos passos:
echo.
echo 1. Edite o arquivo .env com suas credenciais
echo    notepad .env
echo.
echo 2. Crie o banco de dados (se ainda nao criou):
echo    psql -U postgres -f setup_database.sql
echo.
echo 3. Inicie o servidor:
echo    start_server.bat
echo.
echo 4. Acesse o dashboard:
echo    http://localhost:8000
echo.
echo ============================================
pause
