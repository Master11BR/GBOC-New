# GBOC - Ativa a protecao de dados no Git deste clone (hooks versionados em .githooks).
# Uso: powershell -ExecutionPolicy Bypass -File tools\instalar_protecao_git.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    git config core.hooksPath .githooks
    Write-Host "[GBOC] Protecao ativada: core.hooksPath = $(git config --get core.hooksPath)" -ForegroundColor Green
    Write-Host "       pre-commit: bloqueia bancos, logs, data/, acessos.txt, .env e segredos."
    Write-Host "       pre-push : reexamina commits e bloqueia push forcado / exclusao de branch."
} finally { Pop-Location }
