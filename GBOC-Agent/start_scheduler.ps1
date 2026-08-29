# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
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
Write-Host "  GBOC System v13.2.0 - Agente Autonomo de Backup e Restore Agendado  " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# Detectar Python
$pythonCmd = $null
if (Get-Command "py" -ErrorAction SilentlyContinue) {
    $ver = & py -3.14 --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $pythonCmd = @("py", "-3.14")
    } else {
        $pythonCmd = @("py")
    }
} elseif (Get-Command "python" -ErrorAction SilentlyContinue) {
    $pythonCmd = @("python")
} elseif (Get-Command "python3" -ErrorAction SilentlyContinue) {
    $pythonCmd = @("python3")
}

if (-not $pythonCmd) {
    Write-Error "Python nao encontrado! Instale Python 3.14 ou superior."
    exit 1
}

# Iniciar em Background ou Interativo
if ($Background) {
    Write-Host "[+] Iniciando GBOC Scheduler Agent em segundo plano..." -ForegroundColor Green
    Start-Process -FilePath $pythonCmd[0] -ArgumentList ($pythonCmd[1..($pythonCmd.Length-1)] + "start_scheduler.py") -WorkingDirectory $AgentDir -WindowStyle Hidden
    Write-Host "[OK] Processo em background iniciado. Logs em: $AgentDir\logs\gboc_scheduler.log" -ForegroundColor Green
} else {
    Write-Host "[+] Executando GBOC Scheduler Agent em modo interativo..." -ForegroundColor Green
    & $pythonCmd[0] ($pythonCmd[1..($pythonCmd.Length-1)] + "start_scheduler.py")
}
