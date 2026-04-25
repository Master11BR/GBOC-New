@echo off
REM ============================================================
REM GBOC Agent - Desinstalador v1.0
REM ============================================================

echo.
echo ============================================================
echo   GBOC Agent - Desinstalador
echo ============================================================
echo.
echo ATENCAO: Isto vai remover completamente o GBOC Agent!
echo.
echo O que sera removido:
echo   - Servico Windows GBOCAgent (se existir)
echo   - Arquivos em C:\GBOC\Agent
echo   - Configuracoes em C:\ProgramData\GBOC
echo.

set /p CONFIRM="Deseja continuar? (S/N): "
if /I not "%CONFIRM%"=="S" (
    echo Operacao cancelada.
    pause
    exit /b 0
)

echo.

REM 1. Parar e remover servico
echo [1/5] Removendo servico Windows...
sc query GBOCAgent >nul 2>&1
if %errorlevel% equ 0 (
    net stop GBOCAgent >nul 2>&1
    if exist "C:\GBOC\Tools\nssm\nssm.exe" (
        "C:\GBOC\Tools\nssm\nssm.exe" remove GBOCAgent confirm >nul 2>&1
    ) else (
        sc delete GBOCAgent >nul 2>&1
    )
    echo     Servico GBOCAgent removido
) else (
    echo     Servico nao encontrado (OK)
)

REM 2. Parar PostgreSQL
echo [2/5] Parando PostgreSQL...
if exist "C:\GBOC\Tools\PostgreSQL\pgsql\bin\pg_ctl.exe" (
    "C:\GBOC\Tools\PostgreSQL\pgsql\bin\pg_ctl.exe" stop -D "C:\GBOC\Tools\PostgreSQL\data" -m fast >nul 2>&1
    echo     PostgreSQL parado
    timeout /t 3 /nobreak >nul
)
taskkill /F /IM postgres.exe >nul 2>&1

REM 3. Remover Agent
echo [3/5] Removendo arquivos do Agent...
if exist "C:\GBOC\Agent" (
    rmdir /S /Q "C:\GBOC\Agent"
    echo     C:\GBOC\Agent removido
)

REM 4. Remover Tools
echo [4/5] Removendo ferramentas...
set /p REMOVE_TOOLS="Remover ferramentas compartilhadas (Python, PostgreSQL, motores)? (S/N): "
if /I "%REMOVE_TOOLS%"=="S" (
    if exist "C:\GBOC\Tools" (
        rmdir /S /Q "C:\GBOC\Tools"
        echo     C:\GBOC\Tools removido
    )
)

REM 5. Limpeza
echo [5/5] Limpeza final...
rmdir "C:\GBOC" >nul 2>&1
if exist "C:\ProgramData\GBOC" (
    rmdir /S /Q "C:\ProgramData\GBOC" >nul 2>&1
    echo     Configuracao limpa
)

echo.
echo ============================================================
echo   Desinstalacao do GBOC Agent concluida!
echo ============================================================
echo.
pause
