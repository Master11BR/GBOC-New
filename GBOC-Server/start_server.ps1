<#
==============================================================================
GBOC System v14.0.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
#>

# ========================================
# GBOC Server v14.0.0 - Inicializacao
# ========================================

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  GBOC Server v14.0.0 - Iniciando..." -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

$PythonExe = $null
$PythonBaseArgs = @()

if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
        & py -3.14 --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $PythonExe = "py"
            $PythonBaseArgs = @("-3.14")
        }
    } catch {}
}

if (-not $PythonExe -and (Get-Command python -ErrorAction SilentlyContinue)) { $PythonExe = "python" }
if (-not $PythonExe -and (Get-Command py -ErrorAction SilentlyContinue)) { $PythonExe = "py" }
if (-not $PythonExe -and (Get-Command python3 -ErrorAction SilentlyContinue)) { $PythonExe = "python3" }

if (-not $PythonExe) {
    Write-Host "[ERRO] Python nao encontrado!" -ForegroundColor Red
    exit 1
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & $script:PythonExe @script:PythonBaseArgs @Args
}

Invoke-Python -c "import fastapi" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERRO] Dependencias nao instaladas! Execute install_server.ps1" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Iniciando GBOC Server v14.0.0..." -ForegroundColor Green
Write-Host "Comando Python: $PythonExe $($PythonBaseArgs -join ' ')`n" -ForegroundColor Gray

Write-Host "Servidor disponivel em:" -ForegroundColor Yellow
Write-Host "  - HTTP: http://0.0.0.0:8000 (acesso por IP da maquina)" -ForegroundColor Green
Write-Host "  - WebSocket: ws://0.0.0.0:8000/ws" -ForegroundColor Green
Write-Host "  - API Docs: http://0.0.0.0:8000/api/docs" -ForegroundColor Green
Write-Host ""

Write-Host "Verificando PostgreSQL em localhost:5432..." -ForegroundColor Yellow
try {
    $tcp = [System.Net.Sockets.TcpClient]::new("localhost", 5432)
    $tcp.Close()
    Write-Host "[OK] PostgreSQL acessivel." -ForegroundColor Green
} catch {
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
