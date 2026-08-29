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
python -m http.server 8080
pause
