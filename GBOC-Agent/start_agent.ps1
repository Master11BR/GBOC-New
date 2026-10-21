<#
==============================================================================
GBOC System v14.8.2 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
#>

# ========================================
# GBOC Agent 14.8.2 - Inicializacao
# ========================================
# -Service: execucao pelo servico do Windows (NSSM). Sem perguntas; o codigo de saida e repassado
# para o servico reiniciar o Agente. O servico chama ESTE script (e nao um python.exe fixo), entao
# continua funcionando quando o Python e atualizado ou muda de pasta.
[CmdletBinding()]
param([switch]$Service)

$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  GBOC Agent 14.8.2 - Iniciando..." -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

function Resolve-GbocPython([string]$Root, [string]$Component) {
    # Python mais novo instalado que ja tenha as dependencias (scripts\gboc_python.ps1): nao depende de
    # versao fixa ("py -3.14") nem de caminho absoluto - atualizar o Python nao impede a inicializacao.
    $resolver = Join-Path $Root "scripts\gboc_python.ps1"
    if (Test-Path $resolver) {
        $exe = & $resolver -Root $Root -Component $Component | Select-Object -Last 1
        if ($exe -and (Test-Path -LiteralPath $exe)) { return [string]$exe }
    }
    Write-Host "[AVISO] Selecao automatica do Python indisponivel. Tentando o Python padrao do sistema..." -ForegroundColor Yellow
    foreach ($cand in @(@("py", "-3"), @("python"))) {
        if (-not (Get-Command $cand[0] -ErrorAction SilentlyContinue)) { continue }
        $extra = @($cand | Select-Object -Skip 1)
        $exe = & $cand[0] @extra -c "import sys, fastapi; print(sys.executable)" 2>$null | Select-Object -Last 1
        if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path -LiteralPath $exe)) { return [string]$exe }
    }
    return $null
}

function Test-GbocPort([int]$Port) {
    try { $c = [System.Net.Sockets.TcpClient]::new("localhost", $Port); $c.Close(); return $true } catch { return $false }
}

function Start-GbocPostgres([int]$WaitSec = 30) {
    # Qualquer versao instalada (postgresql-x64-NN, postgresql-gboc...): a mais nova primeiro
    if (Test-GbocPort 5432) { return $true }
    $svcs = @(Get-Service -Name "postgres*" -ErrorAction SilentlyContinue |
        Where-Object { $_.StartType -ne "Disabled" } | Sort-Object Name -Descending)
    foreach ($s in $svcs) {
        Write-Host "PostgreSQL parado. Iniciando o servico $($s.Name)..." -ForegroundColor Yellow
        try { Start-Service -Name $s.Name -ErrorAction Stop } catch { Write-Host "  Falha: $($_.Exception.Message)" -ForegroundColor Yellow; continue }
        for ($i = 0; $i -lt $WaitSec; $i++) { if (Test-GbocPort 5432) { return $true }; Start-Sleep -Seconds 1 }
    }
    foreach ($ctl in @("C:\GBOC\Tools\PostgreSQL\pgsql\bin\pg_ctl.exe", "C:\GBOC\Tools\PostgreSQL\bin\pg_ctl.exe")) {
        if ((Test-Path $ctl) -and (Test-Path "C:\GBOC\Tools\PostgreSQL\data")) {
            Write-Host "Iniciando PostgreSQL portatil..." -ForegroundColor Yellow
            Start-Process -FilePath $ctl -ArgumentList "start -D `"C:\GBOC\Tools\PostgreSQL\data`" -l `"C:\GBOC\Tools\PostgreSQL\logfile.log`"" -WindowStyle Hidden
            for ($i = 0; $i -lt $WaitSec; $i++) { if (Test-GbocPort 5432) { return $true }; Start-Sleep -Seconds 1 }
        }
    }
    return (Test-GbocPort 5432)
}

$PythonExe = Resolve-GbocPython $PSScriptRoot "agent"
if (-not $PythonExe) {
    Write-Host "[ERRO] Nenhum Python com as dependencias do GBOC foi encontrado." -ForegroundColor Red
    Write-Host "Execute install_agent.ps1 (como Administrador) ou: python -m pip install -r requirements.txt" -ForegroundColor Yellow
    Write-Host "Detalhes em: logs\python_runtime.log" -ForegroundColor Gray
    exit 1
}

Write-Host "[OK] Iniciando GBOC Agent 14.8.1..." -ForegroundColor Green
Write-Host "Python: $PythonExe`n" -ForegroundColor Gray

Write-Host "Servidor disponivel em:" -ForegroundColor Yellow
Write-Host "  - https://localhost:9200" -ForegroundColor Cyan
Write-Host "  - Dashboard: https://localhost:9200/" -ForegroundColor Green
Write-Host "  - Diagnostico: https://localhost:9200/diagnostic.html" -ForegroundColor Green
Write-Host "  - API Docs: https://localhost:9200/docs" -ForegroundColor Green
Write-Host ""

Write-Host "Verificando PostgreSQL em localhost:5432..." -ForegroundColor Yellow
if (Start-GbocPostgres) {
    Write-Host "[OK] PostgreSQL acessivel." -ForegroundColor Green
} else {
    Write-Host "[ERRO] PostgreSQL nao esta acessivel em localhost:5432" -ForegroundColor Red
    Write-Host "Inicie o servico PostgreSQL e tente novamente." -ForegroundColor Yellow
    Write-Host "Exemplo (Admin): Get-Service *postgres* | Start-Service" -ForegroundColor Gray
    exit 1
}
Write-Host ""

# Mesmo ponto de entrada do start_agent.bat (HTTPS/HTTP2 via Hypercorn + redirecionamento HTTP)
# Python 3.15+ usa UTF-8 por padrao; a saida dos comandos do Windows e cp850/cp1252 (mantem o comportamento anterior)
if (-not $env:PYTHONUTF8) { $env:PYTHONUTF8 = "0" }
$env:PYTHONIOENCODING = "utf-8"
& $PythonExe -u start_server.py
$code = $LASTEXITCODE
Write-Host "`nServidor encerrado." -ForegroundColor Yellow
exit $code
