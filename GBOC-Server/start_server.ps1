<#
==============================================================================
GBOC System v14.8.2 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
#>

# ========================================
# GBOC Server v14.8.2 - Inicializacao
# ========================================

Set-Location -Path $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
# Python 3.15+ usa UTF-8 por padrao; a saida dos comandos do Windows e cp850/cp1252 (mantem o comportamento anterior)
if (-not $env:PYTHONUTF8) { $env:PYTHONUTF8 = "0" }

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  GBOC Server v14.8.2 - Iniciando..." -ForegroundColor Cyan
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

$PythonExe = Resolve-GbocPython $PSScriptRoot "server"
if (-not $PythonExe) {
    Write-Host "[ERRO] Nenhum Python com as dependencias do GBOC foi encontrado." -ForegroundColor Red
    Write-Host "Execute install_server.bat ou: python -m pip install -r requirements.txt (detalhes: logs\python_runtime.log)" -ForegroundColor Yellow
    exit 1
}
$PythonBaseArgs = @()

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & $script:PythonExe @script:PythonBaseArgs @Args
}

Invoke-Python -c "import fastapi" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERRO] Dependencias nao instaladas! Execute install_server.ps1" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Iniciando GBOC Server v14.8.1..." -ForegroundColor Green
Write-Host "Python: $PythonExe`n" -ForegroundColor Gray

Write-Host "Servidor disponivel em:" -ForegroundColor Yellow
Write-Host "  - HTTP: http://0.0.0.0:8000 (acesso por IP da maquina)" -ForegroundColor Green
Write-Host "  - WebSocket: ws://0.0.0.0:8000/ws" -ForegroundColor Green
Write-Host "  - API Docs: http://0.0.0.0:8000/api/docs" -ForegroundColor Green
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

# Pré-check da porta do servidor
$portInUse = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($portInUse) {
    $pids = ($portInUse | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
    Write-Host "[ERRO] Porta 8000 ja esta em uso. PID(s): $pids" -ForegroundColor Red
    Write-Host "Feche o processo existente ou use: netstat -ano | findstr :8000" -ForegroundColor Yellow
    exit 1
}

$logFile = Join-Path $PSScriptRoot "startup_out.log"
$errFile = Join-Path $PSScriptRoot "startup_err.log"

# 1ª tentativa de start
Invoke-Python server_gboc.py 1> $logFile 2> $errFile

# Se caiu por erro de permissão no schema, tentar auto-fix e uma única retomada
$combined = ""
if (Test-Path $logFile) { $combined += (Get-Content $logFile -Raw) }
if (Test-Path $errFile) { $combined += "`n" + (Get-Content $errFile -Raw) }

if ($combined -match "permission denied for schema public") {
    Write-Host "[WARN] Detectado erro de permissao no schema public." -ForegroundColor Yellow
    $initScript = Join-Path $PSScriptRoot "scripts\init_db.ps1"
    if (Test-Path $initScript) {
        Write-Host "[INFO] Tentando corrigir permissões automaticamente..." -ForegroundColor Cyan
        try {
            & $initScript -DbHost "localhost" -DbPort 5432 -SuperUser "postgres"
            Write-Host "[INFO] Reintentando start do servidor..." -ForegroundColor Cyan
            Invoke-Python server_gboc.py
        } catch {
            Write-Host "[ERRO] Falha ao executar init_db.ps1: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "Execute manualmente: .\scripts\init_db.ps1" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[ERRO] Script de init DB nao encontrado: $initScript" -ForegroundColor Red
    }
} else {
    # Se não foi erro de schema, manter comportamento padrão (mostrar saída gravada)
    if (Test-Path $logFile) { Get-Content $logFile }
    if (Test-Path $errFile) { Get-Content $errFile }
}

Write-Host "`nServidor encerrado." -ForegroundColor Yellow
