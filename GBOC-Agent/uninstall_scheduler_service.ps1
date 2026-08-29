# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Service Uninstaller: GBOC Scheduler Agent
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

#Requires -RunAsAdministrator

[CmdletBinding()]
param()

$TaskName = "GBOC_Scheduler_Agent"

Write-Host "======================================================================" -ForegroundColor Yellow
Write-Host "  Desinstalador do Servico Autonomo: GBOC Scheduler Agent             " -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Yellow
Write-Host ""

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "✅ Servico/Tarefa '$TaskName' removido com sucesso." -ForegroundColor Green
} else {
    Write-Host "ℹ️ A tarefa '$TaskName' nao estava registrada." -ForegroundColor Cyan
}
