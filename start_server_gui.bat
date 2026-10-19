@echo off
title GBOC GUI Server (Frontend)
color 0B

echo ===================================================
echo GBOC System - GUI Frontend
echo Iniciando servidor estatico para a Interface Grafica
echo ===================================================

cd "%~dp0\GBOC-Server"

:: Inicia o servidor HTTP estático na porta 8080
echo.
echo [!] Acessando o Dashboard em: http://127.0.0.1:8080
echo.

:: Inicia o navegador
start http://127.0.0.1:8080

:: Executa o servidor Python
REM "py -3" usa o Python mais novo instalado (servidor estatico: nao precisa das dependencias do GBOC)
where py >nul 2>&1
if %errorlevel% equ 0 (py -3 -m http.server 8080) else (python -m http.server 8080)
pause
