# ========================================
# GBOC Agent 11.7c - Inicializacao
# ========================================

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  GBOC Agent 11.7c - Iniciando..." -ForegroundColor Cyan
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
    Write-Host "[ERRO] Dependencias nao instaladas! Execute install_agent.ps1" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Iniciando GBOC Agent 11.7c..." -ForegroundColor Green
Write-Host "Comando Python: $PythonExe $($PythonBaseArgs -join ' ')`n" -ForegroundColor Gray

Write-Host "Servidor disponivel em:" -ForegroundColor Yellow
Write-Host "  - http://localhost:9200" -ForegroundColor Cyan
Write-Host "  - Dashboard: http://localhost:9200/" -ForegroundColor Green
Write-Host "  - Diagnostico: http://localhost:9200/diagnostic.html" -ForegroundColor Green
Write-Host "  - API Docs: http://localhost:9200/docs" -ForegroundColor Green
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

Invoke-Python agent_server.py
Write-Host "`nServidor encerrado." -ForegroundColor Yellow

