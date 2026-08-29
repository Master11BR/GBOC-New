<#
==============================================================================
GBOC System v13.2.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
#>

param(
    [string]$DbHost = "localhost",
    [int]$DbPort = 5432,
    [string]$SuperUser = "postgres"
)

$ErrorActionPreference = "Stop"

$psqlCmd = $null
if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
    $candidateBins = @(
        "C:\Program Files\PostgreSQL\17\bin\psql.exe",
        "C:\Program Files\PostgreSQL\16\bin\psql.exe",
        "C:\Program Files\PostgreSQL\15\bin\psql.exe",
        "C:\Program Files\PostgreSQL\14\bin\psql.exe",
        "C:\Program Files\PostgreSQL\13\bin\psql.exe"
    )
    $found = $candidateBins | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($found) {
        $psqlCmd = $found
        Write-Host "[INFO] psql encontrado em: $found" -ForegroundColor Yellow
    } else {
        Write-Host "[ERRO] psql não encontrado no PATH." -ForegroundColor Red
        Write-Host "Instale PostgreSQL client tools ou execute setup_database.sql no pgAdmin." -ForegroundColor Yellow
        exit 1
    }
} else {
    $psqlCmd = "psql"
}

$sqlPath = Join-Path (Split-Path -Parent $PSScriptRoot) "setup_database.sql"
if (-not (Test-Path $sqlPath)) {
    Write-Host "[ERRO] setup_database.sql não encontrado: $sqlPath" -ForegroundColor Red
    exit 1
}

Write-Host "Inicializando banco gboc/gboc_user via setup_database.sql..." -ForegroundColor Cyan
& $psqlCmd -h $DbHost -p $DbPort -U $SuperUser -d postgres -f $sqlPath
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERRO] Falha ao inicializar banco." -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Banco inicializado/configurado com sucesso." -ForegroundColor Green
