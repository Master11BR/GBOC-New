# ==============================================================================
# GBOC System v14.8.1 Enterprise Edition
# PowerShell Launcher: GBOC Scheduler Agent & Background Task Runner
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

[CmdletBinding()]
param (
    [switch]$Background
)

$AgentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $AgentDir

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  GBOC System v14.8.1 - Agente Autonomo de Backup e Restore Agendado  " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

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

$PythonExe = Resolve-GbocPython $AgentDir "scheduler"
if (-not $PythonExe) {
    Write-Error "Nenhum Python com as dependencias do GBOC foi encontrado. Execute install_agent.ps1 (detalhes: logs\python_runtime.log)."
    exit 1
}
if (-not (Start-GbocPostgres)) {
    Write-Host "[AVISO] PostgreSQL nao respondeu. O Scheduler tentara reconectar automaticamente." -ForegroundColor Yellow
}

# Python 3.15+ usa UTF-8 por padrao; a saida dos comandos do Windows e cp850/cp1252 (mantem o comportamento anterior)
if (-not $env:PYTHONUTF8) { $env:PYTHONUTF8 = "0" }
# Iniciar em Background ou Interativo
if ($Background) {
    Write-Host "[+] Iniciando GBOC Scheduler Agent em segundo plano..." -ForegroundColor Green
    Start-Process -FilePath $PythonExe -ArgumentList "start_scheduler.py" -WorkingDirectory $AgentDir -WindowStyle Hidden
    Write-Host "[OK] Processo em background iniciado. Logs em: $AgentDir\logs\gboc_scheduler.log" -ForegroundColor Green
} else {
    Write-Host "[+] Executando GBOC Scheduler Agent em modo interativo..." -ForegroundColor Green
    & $PythonExe start_scheduler.py
    exit $LASTEXITCODE
}
