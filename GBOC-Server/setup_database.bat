@REM ==============================================================================
@REM GBOC System v14.8.1 Enterprise Edition
@REM Copyright (c) 2026 Master11BR - Todos os direitos reservados.
@REM Propriedade Intelectual & Direitos Autorais Registrados.
@REM ==============================================================================

@echo off
REM ========================================
REM GBOC Server - Setup do Banco de Dados
REM Usa o PostgreSQL instalado pelo Agent
REM ========================================

cd /d "%~dp0"

echo.
echo ========================================
echo  GBOC Server - Configuracao do Banco
echo ========================================
echo.

REM Tentar localizar psql
set PSQL=

REM 1. PostgreSQL portátil do Agent
if exist "C:\GBOC\Tools\PostgreSQL\pgsql\bin\psql.exe" (
	set PSQL=C:\GBOC\Tools\PostgreSQL\pgsql\bin\psql.exe
	echo [OK] PostgreSQL encontrado: C:\GBOC\Tools\PostgreSQL\pgsql\bin
	goto :found
)

REM 2. PostgreSQL instalado (qualquer versao: servico, Program Files ou portatil) - a mais nova
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
goto :found
:pg_generic_next

REM 3. No PATH
where psql >nul 2>&1
if %errorlevel% equ 0 (
	set PSQL=psql
	echo [OK] PostgreSQL encontrado no PATH
	goto :found
)

echo [ERRO] psql nao encontrado!
echo.
echo Opcoes:
echo   1. Instale o GBOC Agent primeiro (ele instala o PostgreSQL)
echo   2. Instale PostgreSQL manualmente
echo   3. Adicione psql ao PATH do sistema
echo.
pause
exit /b 1

:found
echo.

REM Verificar se PostgreSQL esta rodando
echo Verificando se PostgreSQL esta rodando...
"%PSQL%" -U postgres -h localhost -c "SELECT 1;" >nul 2>&1
if %errorlevel% neq 0 (
	echo.
	echo [AVISO] PostgreSQL nao esta respondendo em localhost.
	echo.

	REM Tentar iniciar o PostgreSQL portátil
	if exist "C:\GBOC\Tools\PostgreSQL\pgsql\bin\pg_ctl.exe" (
		echo Tentando iniciar PostgreSQL portatil...
		start "" "C:\GBOC\Tools\PostgreSQL\pgsql\bin\pg_ctl.exe" start -D "C:\GBOC\Tools\PostgreSQL\data" -l "C:\GBOC\Tools\PostgreSQL\logfile.log"
		timeout /t 5 /nobreak >nul

		"%PSQL%" -U postgres -h localhost -c "SELECT 1;" >nul 2>&1
		if %errorlevel% neq 0 (
			echo [ERRO] Nao foi possivel conectar ao PostgreSQL.
			echo Inicie o PostgreSQL manualmente e tente novamente.
			pause
			exit /b 1
		)
		echo [OK] PostgreSQL iniciado com sucesso.
	) else (
		echo Inicie o PostgreSQL e execute este script novamente.
		pause
		exit /b 1
	)
)

echo [OK] PostgreSQL respondendo.
echo.

REM Executar setup_database.sql
echo Executando setup_database.sql...
echo.

"%PSQL%" -U postgres -h localhost -f setup_database.sql

if %errorlevel% equ 0 (
	echo.
	echo ========================================
	echo  Banco de dados configurado com sucesso!
	echo ========================================
	echo.
	echo   Banco: gboc
	echo   Usuario: gboc_user
	echo   Senha: Stoms2025+
	echo   Host: localhost:5432
	echo.
	echo Agora execute: start_server.bat
) else (
	echo.
	echo [AVISO] Podem ter ocorrido avisos, mas o banco pode estar OK.
	echo Verifique as mensagens acima.
)

echo.
pause
