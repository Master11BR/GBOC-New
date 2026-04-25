# ========================================
# GBOC Agent 11.7c - Instalador PowerShell
# ========================================

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  GBOC Agent 11.7c - Instalador" -ForegroundColor Cyan
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

Write-Host "[1/5] Python encontrado:" -ForegroundColor Yellow
$pythonVersion = (Invoke-Python --version) 2>&1
Write-Host "✓ $pythonVersion" -ForegroundColor Green
Write-Host "Comando: $PythonExe $($PythonBaseArgs -join ' ')" -ForegroundColor Gray

Write-Host "`n[2/5] Atualizando pip..." -ForegroundColor Yellow
Invoke-Python -m pip install --upgrade pip

Write-Host "`n[3/5] Instalando dependencias do GBOC Agent..." -ForegroundColor Yellow
Invoke-Python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "[AVISO] Algunas dependencias falharam. Tentando fallback..." -ForegroundColor Yellow
    Invoke-Python -m pip install -r requirements_minimal.txt
}

Write-Host "`n[4/5] Instalando PostgreSQL driver (psycopg2-binary)..." -ForegroundColor Yellow
Invoke-Python -m pip install --only-binary :all: psycopg2-binary
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] psycopg2-binary instalado - PostgreSQL habilitado!" -ForegroundColor Green
} else {
    Write-Host "[AVISO] psycopg2-binary nao instalado - fallback SQLite" -ForegroundColor Yellow
}

Write-Host "`n[5/5] Verificando instalacao..." -ForegroundColor Yellow
Invoke-Python -c "import fastapi; import uvicorn; import websockets; print('[OK] Dependencias principais')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[AVISO] Falha ao importar FastAPI/Pydantic. Tentando auto-correcao..." -ForegroundColor Yellow
    Invoke-Python -m pip install --force-reinstall --no-cache-dir "pydantic==2.12.5" "pydantic-core==2.41.5" "fastapi==0.135.1" "starlette==0.52.1"
    Invoke-Python -c "import pydantic_core; import pydantic; import fastapi; import uvicorn; import websockets; print('[OK] Stack FastAPI/Pydantic corrigida')"
}

Invoke-Python -c "import psycopg2; print('[OK] psycopg2 - PostgreSQL habilitado')" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] psycopg2 ausente - usando SQLite" -ForegroundColor Yellow
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  ✓ Instalacao Concluida" -ForegroundColor Green
Write-Host "========================================`n" -ForegroundColor Cyan
Write-Host "Proximos passos:" -ForegroundColor Cyan
Write-Host "  1. Execute: .\start_agent.ps1"
Write-Host "  2. Acesse: http://localhost:9200"

