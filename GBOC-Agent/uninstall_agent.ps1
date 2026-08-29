<#
==============================================================================
GBOC System v13.2.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
#>

# ============================================================================
# GBOC Agent - Desinstalador Completo v13.2.0
# ============================================================================

#Requires -RunAsAdministrator

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

$INSTALL_ROOT = "C:\GBOC"
$AGENT_DIR = "$INSTALL_ROOT\Agent"
$TOOLS_DIR = "$INSTALL_ROOT\Tools"
$NSSM_EXE = "$TOOLS_DIR\nssm\nssm.exe"
$SERVICE_NAME = "GBOCAgent"

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "    ✓ $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "    ⚠ $Message" -ForegroundColor Yellow
}

function Write-ErrorMsg {
    param([string]$Message)
    Write-Host "    ✗ $Message" -ForegroundColor Red
}

Write-Host @"

╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║         GBOC Agent - Desinstalador Completo v13.2.0        ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝

"@ -ForegroundColor Yellow

# 1. Verificar privilégios de administrador
Write-Step "Verificando privilégios de Administrador"
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-ErrorMsg "Este script de desinstalação deve ser executado como Administrador!"
    exit 1
}
Write-Success "Privilégios de Administrador confirmados"

# 2. Confirmar desinstalação
Write-Host "`nDeseja realmente desinstalar o GBOC Agent deste sistema? (S/N): " -NoNewline -ForegroundColor Yellow
$confirm = Read-Host
if ($confirm -ne "S" -and $confirm -ne "s") {
    Write-Host "`nOperação de desinstalação cancelada pelo usuário." -ForegroundColor Gray
    exit 0
}

# 3. Opção de expurgo de dados
Write-Host "`nEscolha o nível de remoção dos dados:" -ForegroundColor Yellow
Write-Host "  [1] Manter Banco de Dados e Logs (recomendado se for reinstalar)" -ForegroundColor Cyan
Write-Host "  [2] Expurgo Completo (Remover arquivos, banco de dados e logs)" -ForegroundColor Red
Write-Host "Opção (1/2): " -NoNewline -ForegroundColor Yellow
$purgeChoice = Read-Host
$purgeData = ($purgeChoice -eq "2")

# 4. Parar e Remover Serviço Windows
Write-Step "Parando e removendo serviço Windows ($SERVICE_NAME)"
$service = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($service) {
    try {
        if ($service.Status -eq 'Running') {
            Write-Host "    Parando serviço $SERVICE_NAME..."
            Stop-Service -Name $SERVICE_NAME -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
        
        if (Test-Path $NSSM_EXE) {
            & $NSSM_EXE stop $SERVICE_NAME *>$null
            & $NSSM_EXE remove $SERVICE_NAME confirm *>$null
        } else {
            sc.exe delete $SERVICE_NAME *>$null
        }
        Write-Success "Serviço $SERVICE_NAME removido com sucesso"
    } catch {
        Write-Warning "Falha ao remover serviço via NSSM: $_"
    }
} else {
    Write-Success "Serviço $SERVICE_NAME não estava registrado"
}

# 5. Encerrar processos em execução
Write-Step "Encerrando processos ativos do GBOC Agent"
$procs = Get-Process | Where-Object { $_.ProcessName -like "*python*" -and ($_.CommandLine -like "*agent_gboc.py*" -or $_.CommandLine -like "*agent_server.py*") }
foreach ($p in $procs) {
    try {
        Stop-Process -Id $p.Id -Force
        Write-Success "Processo do Agent (PID $($p.Id)) encerrado"
    } catch {}
}

# 6. Remover Regras de Firewall
Write-Step "Removendo regras de Firewall do Windows"
try {
    Remove-NetFirewallRule -DisplayName "GBOC Agent" -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName "GBOC Backup Agent" -ErrorAction SilentlyContinue
    Write-Success "Regras de Firewall removidas"
} catch {
    Write-Warning "Não foi possível remover regras do Firewall"
}

# 7. Limpeza de Diretórios
Write-Step "Limpando arquivos da instalação"
if ($purgeData) {
    Write-Host "    Executando expurgo completo em $INSTALL_ROOT..." -ForegroundColor Red
    if (Test-Path $INSTALL_ROOT) {
        try {
            Remove-Item -Path $INSTALL_ROOT -Recurse -Force -ErrorAction SilentlyContinue
            Write-Success "Diretório $INSTALL_ROOT removido completamente"
        } catch {
            Write-Warning "Alguns arquivos não puderam ser removidos imediatamente: $_"
        }
    }
} else {
    Write-Host "    Preservando banco de dados e logs..." -ForegroundColor Cyan
    if (Test-Path "$AGENT_DIR\.env") { Remove-Item "$AGENT_DIR\.env" -Force -ErrorAction SilentlyContinue }
    if (Test-Path "$AGENT_DIR\start_agent.bat") { Remove-Item "$AGENT_DIR\start_agent.bat" -Force -ErrorAction SilentlyContinue }
    Write-Success "Arquivos executáveis removidos. Dados preservados em $INSTALL_ROOT."
}

Write-Host @"

╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║       DESINSTALAÇÃO CONCLUÍDA COM SUCESSO! ✓              ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝

"@ -ForegroundColor Green

Write-Host "Pressione qualquer tecla para sair..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
