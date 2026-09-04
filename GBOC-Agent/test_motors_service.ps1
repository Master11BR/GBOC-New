<#
==============================================================================
GBOC System v14.0.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
#>

# ============================================================================
# GBOC Agent - Teste de Configuração de Motores (como Serviço)
# ============================================================================
# Verifica se os motores de backup estão configurados corretamente
# para execução como serviço do Windows (LocalSystem)
# ============================================================================

Write-Host @"

╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║     GBOC Agent - Teste de Motores como Serviço          ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝

"@ -ForegroundColor Cyan

# ============================================================================
# VERIFICAÇÕES
# ============================================================================

function Test-MotorAccessibility {
	param(
		[string]$Name,
		[string]$Path
	)

	Write-Host "`n==> Testando $Name" -ForegroundColor Cyan

	# Verificar se existe
	if (-not (Test-Path $Path)) {
		Write-Host "    ✗ NÃO ENCONTRADO: $Path" -ForegroundColor Red
		return $false
	}

	Write-Host "    ✓ Arquivo encontrado: $Path" -ForegroundColor Green

	# Verificar permissões (ACL)
	try {
		$acl = Get-Acl $Path
		$systemAccess = $acl.Access | Where-Object { 
			$_.IdentityReference -eq "NT AUTHORITY\SYSTEM" -and 
			$_.FileSystemRights -match "FullControl|ReadAndExecute"
		}

		if ($systemAccess) {
			Write-Host "    ✓ Permissões OK (NT AUTHORITY\SYSTEM)" -ForegroundColor Green
		}
		else {
			Write-Host "    ⚠ Permissões podem estar incorretas (NT AUTHORITY\SYSTEM)" -ForegroundColor Yellow
		}
	}
	catch {
		Write-Host "    ⚠ Não foi possível verificar permissões" -ForegroundColor Yellow
	}

	# Tentar executar (versão)
	try {
		$output = & $Path --version 2>&1 | Out-String
		if ($output) {
			Write-Host "    ✓ Executável responde: $($output.Trim())" -ForegroundColor Green
			return $true
		}
	}
	catch {
		Write-Host "    ✗ Falha ao executar: $_" -ForegroundColor Red
		return $false
	}

	return $false
}

# ============================================================================
# PATH DO SISTEMA
# ============================================================================

Write-Host "`n==> Verificando PATH do Sistema" -ForegroundColor Cyan

$systemPath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$requiredPaths = @(
	"C:\GBOC\Tools\Restic",
	"C:\GBOC\Tools\Kopia",
	"C:\GBOC\Tools\Duplicati",
	"C:\GBOC\Tools\Python",
	"C:\GBOC\Tools\PostgreSQL\bin"
)

$allFound = $true
foreach ($path in $requiredPaths) {
	if ($systemPath -like "*$path*") {
		Write-Host "    ✓ $path" -ForegroundColor Green
	}
	else {
		Write-Host "    ✗ FALTANDO: $path" -ForegroundColor Red
		$allFound = $false
	}
}

if ($allFound) {
	Write-Host "`n    ✓ Todos os caminhos estão no PATH do sistema" -ForegroundColor Green
}
else {
	Write-Host "`n    ✗ Alguns caminhos estão faltando no PATH" -ForegroundColor Red
}

# ============================================================================
# VARIÁVEIS DE AMBIENTE DO SISTEMA
# ============================================================================

Write-Host "`n==> Verificando Variáveis de Ambiente" -ForegroundColor Cyan

$envVars = @{
	"RESTIC_PATH" = "C:\GBOC\Tools\Restic\restic.exe"
	"KOPIA_PATH" = "C:\GBOC\Tools\Kopia\kopia.exe"
	"DUPLICATI_PATH" = "C:\GBOC\Tools\Duplicati\Duplicati.CommandLine.exe"
	"GBOC_TOOLS_DIR" = "C:\GBOC\Tools"
}

$allVarsOk = $true
foreach ($varName in $envVars.Keys) {
	$expectedValue = $envVars[$varName]
	$actualValue = [Environment]::GetEnvironmentVariable($varName, "Machine")

	if ($actualValue -eq $expectedValue) {
		Write-Host "    ✓ $varName = $actualValue" -ForegroundColor Green
	}
	else {
		Write-Host "    ✗ $varName = $actualValue (esperado: $expectedValue)" -ForegroundColor Red
		$allVarsOk = $false
	}
}

if ($allVarsOk) {
	Write-Host "`n    ✓ Todas as variáveis estão corretas" -ForegroundColor Green
}

# ============================================================================
# MOTORES
# ============================================================================

$resticOk = Test-MotorAccessibility "Restic" "C:\GBOC\Tools\Restic\restic.exe"
$kopiaOk = Test-MotorAccessibility "Kopia" "C:\GBOC\Tools\Kopia\kopia.exe"
$duplicatiOk = Test-MotorAccessibility "Duplicati" "C:\GBOC\Tools\Duplicati\Duplicati.CommandLine.exe"

# ============================================================================
# SERVIÇO GBOC AGENT
# ============================================================================

Write-Host "`n==> Verificando Serviço GBOC Agent" -ForegroundColor Cyan

$service = Get-Service -Name "GBOCAgent" -ErrorAction SilentlyContinue

if ($service) {
	Write-Host "    ✓ Serviço encontrado: $($service.Name)" -ForegroundColor Green
	Write-Host "    Status: $($service.Status)" -ForegroundColor $(if ($service.Status -eq "Running") { "Green" } else { "Yellow" })
	Write-Host "    Tipo de inicialização: $($service.StartType)" -ForegroundColor Cyan

	# Verificar conta de execução
	$serviceWmi = Get-WmiObject Win32_Service -Filter "Name='GBOCAgent'"
	if ($serviceWmi) {
		Write-Host "    Conta de execução: $($serviceWmi.StartName)" -ForegroundColor Cyan

		if ($serviceWmi.StartName -eq "LocalSystem") {
			Write-Host "    ✓ Rodando como LocalSystem (acesso total)" -ForegroundColor Green
		}
		else {
			Write-Host "    ⚠ NÃO está rodando como LocalSystem!" -ForegroundColor Yellow
			Write-Host "    Recomendação: Reconfigure o serviço para usar LocalSystem" -ForegroundColor Yellow
		}
	}
}
else {
	Write-Host "    ✗ Serviço GBOCAgent não encontrado" -ForegroundColor Red
	Write-Host "    Execute o instalador novamente e escolha instalar como serviço" -ForegroundColor Yellow
}

# ============================================================================
# RESUMO FINAL
# ============================================================================

Write-Host @"

╔═══════════════════════════════════════════════════════════╗
║                     RESUMO DO TESTE                       ║
╚═══════════════════════════════════════════════════════════╝

"@ -ForegroundColor Cyan

$issues = @()

if (-not $allFound) { $issues += "PATH do sistema incompleto" }
if (-not $allVarsOk) { $issues += "Variáveis de ambiente incorretas" }
if (-not $resticOk) { $issues += "Restic não está acessível" }
if (-not $kopiaOk) { $issues += "Kopia não está acessível" }
if (-not $duplicatiOk) { $issues += "Duplicati não está acessível" }
if (-not $service) { $issues += "Serviço não está instalado" }
elseif ($service.Status -ne "Running") { $issues += "Serviço não está em execução" }

if ($issues.Count -eq 0) {
	Write-Host "✓ TUDO OK! Os motores estão configurados corretamente." -ForegroundColor Green
	Write-Host "  O Agent pode rodar backups agendados sem problemas." -ForegroundColor Green
}
else {
	Write-Host "✗ PROBLEMAS ENCONTRADOS:" -ForegroundColor Red
	foreach ($issue in $issues) {
		Write-Host "  • $issue" -ForegroundColor Yellow
	}
	Write-Host "`nRECOMENDAÇÃO:" -ForegroundColor Cyan
	Write-Host "  Execute o instalador novamente: .\install_agent.ps1" -ForegroundColor White
}

Write-Host "`nPressione qualquer tecla para sair..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
