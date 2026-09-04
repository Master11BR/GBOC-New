[CmdletBinding()]
param (
    [Parameter(Mandatory = $false)]
    [string]$OutputDir = "",

    [Parameter(Mandatory = $false)]
    [switch]$Clean = $true
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path (Split-Path -Parent $ScriptRoot) "GBOC-Distribution"
}

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  GERADOR DE PACOTE DE DISTRIBUICAO E INSTALADOR GBOC ENTERPRISE  " -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "Raiz dos Fontes: $ScriptRoot" -ForegroundColor Gray
Write-Host "Pasta de Saida:  $OutputDir" -ForegroundColor Yellow
Write-Host ""

# Detectar Python
$pythonCmd = $null
$candidates = @("python.exe", "py.exe", "python3.exe", "C:\Python311\python.exe", "C:\Python312\python.exe", "C:\Python313\python.exe", "C:\Python314\python.exe")
foreach ($cand in $candidates) {
    try {
        $found = Get-Command $cand -ErrorAction SilentlyContinue
        if ($found) {
            $ver = & $found.Source --version 2>&1
            if ($ver -match "Python\s+3\.") {
                $pythonCmd = $found.Source
                break
            }
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "[ERRO] Python 3 nao encontrado no PATH para executar o empacotador." -ForegroundColor Red
    exit 1
}

Write-Host "==> Executando script de empacotamento..." -ForegroundColor Cyan

$pyArgs = @(
    "$ScriptRoot\tools\make_distribution.py",
    "--source",
    "$ScriptRoot",
    "--output",
    "$OutputDir"
)
if ($Clean) {
    $pyArgs += "--clean"
}

& $pythonCmd $pyArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERRO] Falha durante a geracao do pacote de distribuicao." -ForegroundColor Red
    exit 1
}

# Copiar os executaveis do instalador para a raiz do pacote gerado
Write-Host "==> Copiando executaveis do instalador (Setup.bat / Setup.ps1)..." -ForegroundColor Cyan
$installerAssets = "$ScriptRoot\tools\installer_assets"
if (Test-Path $installerAssets) {
    Copy-Item -Path "$installerAssets\Setup.bat" -Destination "$OutputDir\Setup.bat" -Force
    Copy-Item -Path "$installerAssets\Setup.ps1" -Destination "$OutputDir\Setup.ps1" -Force
    Write-Host "    [OK] Setup.bat e Setup.ps1 copiados para $OutputDir" -ForegroundColor Green
}

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Green
Write-Host "  PACOTE DE INSTALACAO GERADO COM SUCESSO!                       " -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Green
Write-Host "Pasta criada: $OutputDir" -ForegroundColor White
Write-Host "Para instalar, execute: $OutputDir\Setup.bat" -ForegroundColor Yellow
Write-Host ""
