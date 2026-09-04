<#
==============================================================================
GBOC System v14.0.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
#>

# ========================================
# GBOC Agent 14.0.0 - Shutdown Agent/Server
# ========================================
param(
    [switch]$Agent,
    [switch]$Server,
    [switch]$All,
    [switch]$ForceKill
)

if ($All) { $Agent = $true; $Server = $true }
if (-not ($Agent -or $Server)) {
    Write-Host "Use -Agent, -Server ou -All" -ForegroundColor Yellow
    exit 1
}

function Invoke-ShutdownApi {
    param([string]$Url)
    try {
        $r = Invoke-RestMethod -Uri $Url -Method Post -TimeoutSec 5
        Write-Host "[OK] $Url => $($r.message)" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "[WARN] Falha via API $Url: $($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
}

function Stop-PortProcess {
    param([int]$Port)
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) {
            if ($c.OwningProcess -gt 0) {
                Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
                Write-Host "[OK] Processo da porta $Port finalizado (PID=$($c.OwningProcess))" -ForegroundColor Green
            }
        }
    } catch {
        Write-Host "[WARN] Não foi possível finalizar processo na porta $Port" -ForegroundColor Yellow
    }
}

if ($Agent) {
    $ok = Invoke-ShutdownApi -Url "http://127.0.0.1:9200/api/system/shutdown"
    Start-Sleep -Milliseconds 900
    if ($ForceKill -and -not $ok) { Stop-PortProcess -Port 9200 }
}

if ($Server) {
    $ok = Invoke-ShutdownApi -Url "http://127.0.0.1:8000/api/v1/system/shutdown"
    Start-Sleep -Milliseconds 900
    if ($ForceKill -and -not $ok) { Stop-PortProcess -Port 8000 }
}

Write-Host "Concluído." -ForegroundColor Cyan

