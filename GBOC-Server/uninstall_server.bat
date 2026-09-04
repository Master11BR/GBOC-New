@REM ==============================================================================
@REM GBOC System v14.0.0 Enterprise Edition
@REM Copyright (c) 2026 Master11BR - Todos os direitos reservados.
@REM Propriedade Intelectual & Direitos Autorais Registrados.
@REM ==============================================================================

@echo off
REM ============================================================
REM GBOC Server - Desinstalador v14.0.0
REM ============================================================

echo.
echo ============================================================
echo   GBOC Server - Desinstalador
echo ============================================================
echo.
echo ATENCAO: Isto vai remover completamente o GBOC Server!
echo.
echo O que sera removido:
echo   - Servico Windows GBOCServer (se existir)
echo   - Banco de dados 'gboc' e usuario 'gboc_user'
echo   - Arquivos em C:\GBOC\Server (se instalado la)
echo.

set /p CONFIRM="Deseja continuar? (S/N): "
if /I not "%CONFIRM%"=="S" (
    echo Operacao cancelada.
    pause
    exit /b 0
)

echo.

REM 1. Parar e remover servico
echo [1/4] Removendo servico Windows...
sc query GBOCServer >nul 2>&1
if %errorlevel% equ 0 (
    net stop GBOCServer >nul 2>&1
    if exist "C:\GBOC\Tools\nssm\nssm.exe" (
        "C:\GBOC\Tools\nssm\nssm.exe" remove GBOCServer confirm >nul 2>&1
    ) else (
        sc delete GBOCServer >nul 2>&1
    )
    echo     Servico GBOCServer removido
) else (
    echo     Servico nao encontrado (OK)
)

REM 2. Remover banco de dados do Server
echo [2/4] Removendo banco de dados...

set PSQL=
if exist "C:\GBOC\Tools\PostgreSQL\pgsql\bin\psql.exe" (
    set PSQL=C:\GBOC\Tools\PostgreSQL\pgsql\bin\psql.exe
) else if exist "C:\Program Files\PostgreSQL\18\bin\psql.exe" (
    set PSQL=C:\Program Files\PostgreSQL\18\bin\psql.exe
) else if exist "C:\Program Files\PostgreSQL\17\bin\psql.exe" (
    set PSQL=C:\Program Files\PostgreSQL\17\bin\psql.exe
) else if exist "C:\Program Files\PostgreSQL\16\bin\psql.exe" (
    set PSQL=C:\Program Files\PostgreSQL\16\bin\psql.exe
)

if defined PSQL (
    set /p DROP_DB="Remover banco de dados 'gboc' do PostgreSQL? (S/N): "
    if /I "!DROP_DB!"=="S" (
        "%PSQL%" -U postgres -h localhost -c "DROP DATABASE IF EXISTS gboc;" >nul 2>&1
        "%PSQL%" -U postgres -h localhost -c "DROP USER IF EXISTS gboc_user;" >nul 2>&1
        echo     Banco 'gboc' e usuario 'gboc_user' removidos
    ) else (
        echo     Banco mantido
    )
) else (
    echo     psql nao encontrado - remova o banco manualmente se necessario
)

REM 3. Remover arquivos do Server
echo [3/4] Removendo arquivos do Server...
if exist "C:\GBOC\Server" (
    rmdir /S /Q "C:\GBOC\Server"
    echo     C:\GBOC\Server removido
) else (
    echo     C:\GBOC\Server nao encontrado (OK)
)

REM 4. Limpeza
echo [4/4] Limpeza final...
rmdir "C:\GBOC" >nul 2>&1

echo.
echo ============================================================
echo   Desinstalacao do GBOC Server concluida!
echo ============================================================
echo.
echo Nota: Se o Server estava rodando em D:\GBOC\GBOC-New\GBOC-Server,
echo os arquivos fonte NAO foram removidos.
echo.
pause
