param(
    [string]$Database = "gboc",
    [string]$User = "postgres",
    [string]$DbHost = "localhost",
    [int]$Port = 5432,
    [string]$SuperUser = "postgres"
)

$ErrorActionPreference = "Stop"

$sqlPath = Join-Path $PSScriptRoot "fix_postgres_permissions.sql"
if (-not (Test-Path $sqlPath)) {
    Write-Host "[ERRO] SQL não encontrado: $sqlPath" -ForegroundColor Red
    exit 1
}

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
        $script:psqlCmd = $found
        Write-Host "[INFO] psql encontrado em: $found" -ForegroundColor Yellow
    } else {
        Write-Host "[ERRO] psql não encontrado no PATH nem em caminhos padrão." -ForegroundColor Red
        Write-Host "Instale PostgreSQL client tools ou execute o SQL manualmente no pgAdmin." -ForegroundColor Yellow
        exit 1
    }
} else {
    $script:psqlCmd = "psql"
}

Write-Host "Aplicando permissões no banco '$Database' para usuário '$User'..." -ForegroundColor Cyan

# SQL parametrizado para usuário alvo
$sql = @"
GRANT USAGE, CREATE ON SCHEMA public TO $User;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $User;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $User;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO $User;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $User;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $User;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO $User;
"@

$tempSql = Join-Path $env:TEMP "gboc_fix_permissions.sql"
Set-Content -Path $tempSql -Value $sql -Encoding UTF8

& $script:psqlCmd -h $DbHost -p $Port -U $SuperUser -d $Database -f $tempSql
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERRO] Falha ao aplicar permissões." -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Permissões aplicadas com sucesso." -ForegroundColor Green
Write-Host "Reinicie o servidor: .\start_server.ps1" -ForegroundColor Yellow
