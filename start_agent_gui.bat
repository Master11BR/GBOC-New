@echo off
title GBOC GUI Agent (Frontend)
color 0A

echo ===================================================
echo GBOC System - GUI Frontend (Agent)
echo Iniciando servidor estatico para a Interface Grafica
echo ===================================================

cd "%~dp0\GBOC-Agent\static"

:: Inicia o servidor HTTP estático na porta 8081
echo.
echo [!] Acessando o Dashboard do Agente em: http://127.0.0.1:8081
echo.

:: Inicia o navegador
start http://127.0.0.1:8081

:: Executa o servidor Python
python -m http.server 8081
pause
