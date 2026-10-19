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
REM "py -3" usa o Python mais novo instalado (servidor estatico: nao precisa das dependencias do GBOC)
where py >nul 2>&1
if %errorlevel% equ 0 (py -3 -m http.server 8081) else (python -m http.server 8081)
pause
