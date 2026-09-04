<#
==============================================================================
GBOC System v14.0.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
#>

# ========================================
# GBOC Agent 14.0.0 - Force Cleanup External Engines
# ========================================
# Uso:
#   .\force_cleanup_external_engines.ps1 -RepositoryId 25
#   .\force_cleanup_external_engines.ps1 -RepositoryId 25 -RepoPath "E:\Backups\repo" -Bucket "gboc-25"
#   .\force_cleanup_external_engines.ps1 -RepositoryId 25 -DryRun
#   .\force_cleanup_external_engines.ps1 -RepositoryId 25 -ForceKill
#   .\force_cleanup_external_engines.ps1 -RepositoryId 25 -RepoPath "E:\Backups\repo" -Bucket "gboc-25" -ForceKill

param(
    [Parameter(Mandatory = $true)]
    [int]$RepositoryId,

    [string]$RepoPath = "",
    [string]$Bucket = "",
    [string]$Endpoint = "",
    [switch]$DryRun,
    [switch]$ForceKill
)

$ErrorActionPreference = "Stop"

function Write-Info($m) { Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Write-Ok($m) { Write-Host "[OK]   $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err($m) { Write-Host "[ERRO] $m" -ForegroundColor Red }

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " GBOC Agent 14.0.0 - Force Cleanup" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

$root = Split-Path -Parent $PSScriptRoot
$kopiaConfigDir = Join-Path $root "data\kopia_configs"

Write-Info "RepositoryId: $RepositoryId"
if ($RepoPath) { Write-Info "RepoPath: $RepoPath" }
if ($Bucket) { Write-Info "Bucket: $Bucket" }
if ($Endpoint) { Write-Info "Endpoint: $Endpoint" }
if ($DryRun) { Write-Warn "Modo DRY-RUN ativo (nenhum arquivo será removido)." }
if ($ForceKill) { Write-Warn "Modo FORCE-KILL ativo (processos de motores serão encerrados)." }

function Stop-ExternalEngineProcesses {
    param([switch]$DryRunMode)

    $names = @(
        'kopia',
        'restic',
        'duplicati-cli',
        'duplicati.commandline',
        'duplicati.server'
    )

    foreach ($n in $names) {
        $procs = @(Get-Process -Name $n -ErrorAction SilentlyContinue)
        foreach ($p in $procs) {
            if ($DryRunMode) {
                Write-Host "[DRY] finalizar processo $($p.ProcessName) (PID=$($p.Id))" -ForegroundColor DarkYellow
            } else {
                try {
                    Stop-Process -Id $p.Id -Force -ErrorAction Stop
                    Write-Ok "Processo finalizado: $($p.ProcessName) (PID=$($p.Id))"
                } catch {
                    Write-Warn "Não foi possível finalizar $($p.ProcessName) (PID=$($p.Id)): $($_.Exception.Message)"
                }
            }
        }
    }
}

if ($ForceKill) {
    Write-Info "Encerrando processos de motores externos..."
    Stop-ExternalEngineProcesses -DryRunMode:$DryRun
}

# 1) Limpar configs Kopia relacionadas ao repositório
$removed = 0
$checked = 0
if (Test-Path $kopiaConfigDir) {
    Write-Info "Varrendo configs Kopia em: $kopiaConfigDir"
    Get-ChildItem -Path $kopiaConfigDir -Filter "*.config" -File | ForEach-Object {
        $checked++
        $file = $_.FullName
        try {
            $json = Get-Content -Path $file -Raw | ConvertFrom-Json
            $storage = $json.storage.config
            $cfgBucket = [string]($storage.bucket)
            $cfgPath = [string]($storage.path)
            $cfgEndpoint = [string]($storage.endpoint)

            $match = $false
            if ($RepoPath -and $cfgPath -and ([string]::Equals($cfgPath, $RepoPath, [System.StringComparison]::OrdinalIgnoreCase))) {
                $match = $true
            }
            if ($Bucket -and $cfgBucket -and $cfgBucket -eq $Bucket) {
                $match = $true
            }
            if ($Endpoint -and $Bucket -and $cfgEndpoint -and $cfgBucket -and ($cfgEndpoint -eq $Endpoint) -and ($cfgBucket -eq $Bucket)) {
                $match = $true
            }

            # fallback: quando não houver metadados, tentar pelo nome padrão task_*.config
            if (-not $match -and $_.Name -match '^task_\d+\.config$' -and -not $RepoPath -and -not $Bucket -and -not $Endpoint) {
                $match = $true
            }

            if ($match) {
                if ($DryRun) {
                    Write-Host "[DRY] remover $file" -ForegroundColor DarkYellow
                } else {
                    Remove-Item -Path $file -Force -ErrorAction Stop
                    Write-Ok "Removido: $file"
                }
                $removed++
            }
        } catch {
            Write-Warn "Ignorando config inválida: $file ($($_.Exception.Message))"
        }
    }
    Write-Info "Configs verificadas: $checked"
    Write-Info "Configs removidas: $removed"
} else {
    Write-Warn "Diretório não encontrado: $kopiaConfigDir"
}

# 2) Opcional: limpar diretório local do repositório (quando fornecido)
if ($RepoPath) {
    if (Test-Path $RepoPath) {
        if ($DryRun) {
            Write-Host "[DRY] remover diretório local do repositório: $RepoPath" -ForegroundColor DarkYellow
        } else {
            try {
                Remove-Item -Path $RepoPath -Recurse -Force -ErrorAction Stop
                Write-Ok "Diretório local removido: $RepoPath"
            } catch {
                Write-Err "Falha ao remover diretório local: $($_.Exception.Message)"
                Write-Warn "Tente executar este script como Administrador."
            }
        }
    } else {
        Write-Warn "RepoPath informado não existe: $RepoPath"
    }
}

Write-Host "`nConcluído." -ForegroundColor Green

