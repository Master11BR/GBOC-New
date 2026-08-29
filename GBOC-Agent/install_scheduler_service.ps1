# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Service Installer: GBOC Scheduler Agent (Windows Scheduled Task / Service)
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

#Requires -RunAsAdministrator

[CmdletBinding()]
param()

$TaskName = "GBOC_Scheduler_Agent"
$AgentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LauncherBat = Join-Path $AgentDir "start_scheduler.bat"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  Instalador do Servico Autonomo: GBOC Scheduler Agent (System)       " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Diretorio do Agente: $AgentDir"
Write-Host "Script de Execucao : $LauncherBat"
Write-Host ""

# Verificar se a tarefa ja existe
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[!] Removendo instancia anterior da tarefa agendada '$TaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Criar Acao
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$LauncherBat`"" -WorkingDirectory $AgentDir

# Criar Gatilho de Inicializacao do Sistema (Boot)
$TriggerBoot = New-ScheduledTaskTrigger -AtStartup

# Configuracoes de Resiliencia do Servico (Executa sem login, auto-restart se falhar, prioridade alta)
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -Priority 4

$Principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# Registrar a Tarefa no Windows
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $TriggerBoot `
    -Settings $Settings `
    -Principal $Principal `
    -Description "GBOC System v13.2.0 - Agente Autonomo de Backup e Restore Agendado (Execucao Continua em Segundo Plano)"

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "  ✅ Servico GBOC Scheduler Agent instalado com sucesso no Windows!  " -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Status: Configurado para iniciar automaticamente no Boot do sistema."
Write-Host "Contexto de Execucao: NT AUTHORITY\SYSTEM (Independente de usuario logado)."
Write-Host ""

# Iniciar agora
Write-Host "[+] Iniciando o servico agora..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $TaskName
Write-Host "[OK] Servico em execucao. Acompanhe os logs em: $AgentDir\logs\gboc_scheduler.log" -ForegroundColor Green
