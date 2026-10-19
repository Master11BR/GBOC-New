<#
==============================================================================
GBOC System v14.8.1 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
#>

# ============================================================================
# GBOC Agent - Instalador Completo v14.8.1
# ============================================================================
# Instala e configura automaticamente, sempre na ULTIMA versao estavel (consultada na hora):
# - Python (python.org; se as dependencias ainda nao instalarem na mais nova, usa a anterior)
# - PostgreSQL (postgresql.org/EDB; instalacao existente e mantida)
# - Restic, Kopia, Duplicati (GitHub; versoes antigas sao atualizadas)
# - Dependências Python do Agent
# - Serviço Windows do Agent (opcional)
# ============================================================================

# Instalação em massa (GPO/Intune/script gerado no GBOC Server):
#   .\install_agent.ps1 -ServerURL "https://gboc.empresa.com.br:8000" -InstallToken "gbi_..." -Unattended
#   -Unattended responde automaticamente às perguntas (usa Python existente, instala o serviço) e aborta
#   em situações que exigiriam decisão manual (ex.: falha na instalação do PostgreSQL).
param(
	[string]$ServerURL = "",
	[string]$InstallToken = "",
	[switch]$Unattended
)

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================

$INSTALL_ROOT = "C:\GBOC"
$AGENT_DIR = "$INSTALL_ROOT\Agent"
$TOOLS_DIR = "$INSTALL_ROOT\Tools"
$PYTHON_DIR = "$TOOLS_DIR\Python"
$POSTGRES_DIR = "$TOOLS_DIR\PostgreSQL"
$RESTIC_DIR = "$TOOLS_DIR\Restic"
$KOPIA_DIR = "$TOOLS_DIR\Kopia"
$DUPLICATI_DIR = "$TOOLS_DIR\Duplicati"

# Versoes: nao ficam mais fixas aqui. scripts\gboc_prereqs.ps1 descobre a ultima versao estavel de cada
# programa no momento da instalacao (com versao conhecida de reserva se a consulta falhar).
$POSTGRES_VERSION = ""

$DB_NAME = "gboc_agent"
$DB_USER = "gboc"
$DB_PASSWORD = "gboc_$(Get-Random -Maximum 999999)"

$prereqs = @("$PSScriptRoot\scripts\gboc_prereqs.ps1", "$PSScriptRoot\gboc_prereqs.ps1") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $prereqs) {
	Write-Host "scripts\gboc_prereqs.ps1 nao encontrado. Execute o instalador a partir da pasta GBOC-Agent." -ForegroundColor Red
	exit 1
}
. $prereqs

# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================

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

function Write-Error {
	param([string]$Message)
	Write-Host "    ✗ $Message" -ForegroundColor Red
}

function Test-CommandExists {
	param([string]$Command)
	$null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

function Download-File {
	param(
		[string]$Url,
		[string]$Output
	)

	Write-Host "    Baixando de: $Url"
	try {
		$wc = New-Object System.Net.WebClient
		$wc.DownloadFile($Url, $Output)
		Write-Success "Download concluído"
		return $true
	}
	catch {
		Write-Error "Falha no download: $_"
		return $false
	}
}

# ============================================================================
# VERIFICAÇÕES INICIAIS
# ============================================================================

Write-Host @"

╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║          GBOC Agent - Instalador Completo v14.8.1           ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝

"@ -ForegroundColor Cyan

Write-Step "Verificando privilégios de administrador"
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
	Write-Error "Este script deve ser executado como Administrador!"
	exit 1
}
Write-Success "Executando como Administrador"

Write-Step "Verificando sistema operacional"
$os = Get-WmiObject Win32_OperatingSystem
Write-Success "$($os.Caption) ($($os.OSArchitecture))"

if ($os.OSArchitecture -ne "64-bit") {
	Write-Error "Este instalador requer Windows 64-bit"
	exit 1
}

# ============================================================================
# CRIAÇÃO DE DIRETÓRIOS
# ============================================================================

Write-Step "Criando estrutura de diretórios"

@($INSTALL_ROOT, $AGENT_DIR, $TOOLS_DIR, $PYTHON_DIR, $POSTGRES_DIR, $RESTIC_DIR, $KOPIA_DIR, $DUPLICATI_DIR) | ForEach-Object {
	if (-not (Test-Path $_)) {
		New-Item -ItemType Directory -Path $_ -Force | Out-Null
		Write-Success "Criado: $_"
	}
	else {
		Write-Warning "Já existe: $_"
	}
}

# ============================================================================
# INSTALAÇÃO DO PYTHON
# ============================================================================

Write-Step "Python (ultima versao estavel)"

# Instala a versao mais nova do python.org (para todos os usuarios, com o launcher "py") se ainda nao
# existir e ja instala as dependencias do Agente nela. Os scripts de inicializacao e o servico escolhem o
# Python sozinhos (scripts\gboc_python.ps1): atualizar o Python depois nao impede o Agente de iniciar.
$reqSource = if (Test-Path "$PSScriptRoot\requirements.txt") { "$PSScriptRoot\requirements.txt" } else { "$(Split-Path -Parent $PSScriptRoot)\requirements.txt" }
$pythonExe = Install-GbocPython -Requirements $reqSource
if (-not $pythonExe) {
	Write-Error "Nao foi possivel instalar o Python com as dependencias do GBOC"
	exit 1
}
$PYTHON_DIR = Split-Path -Parent $pythonExe
Write-Success "Python: $pythonExe"

# Adicionar Python ao PATH da sessão
$env:PATH = "$PYTHON_DIR;$PYTHON_DIR\Scripts;$env:PATH"

# ============================================================================
# INSTALAÇÃO DO POSTGRESQL
# ============================================================================

Write-Step "Verificando PostgreSQL"

$pgBin = "$POSTGRES_DIR\bin"
$pgExe = "$pgBin\postgres.exe"
$pgInstalled = Test-Path $pgExe

# PostgreSQL ja instalado em outro lugar (servico, Program Files): usa o existente em vez de instalar outro
if (-not $pgInstalled) {
	$existingPgBin = Find-GbocPostgresBin -ToolsDir $TOOLS_DIR
	if ($existingPgBin -and (Test-Path "$existingPgBin\postgres.exe")) {
		$pgBin = $existingPgBin
		$pgExe = "$pgBin\postgres.exe"
		$POSTGRES_DIR = Split-Path -Parent $pgBin
		$pgInstalled = $true
	}
}

if ($pgInstalled) {
	Write-Warning "PostgreSQL já instalado ($pgBin) - mantido (trocar a versao principal exige migrar os dados)"
}
else {
	$pgRelease = Get-GbocPostgresRelease
	$POSTGRES_VERSION = $pgRelease.Version
	$POSTGRES_URL = $pgRelease.Url
	Write-Step "Instalando PostgreSQL $POSTGRES_VERSION"

	$pgInstaller = "$env:TEMP\postgres-installer.exe"

	# Pacote completo (Prereqs\): instalador do PostgreSQL ja vem no pacote, sem download
	$pgReady = $false
	if ($pgRelease.PSObject.Properties["File"] -and $pgRelease.File) {
		Write-Host "    Usando o instalador do PostgreSQL do pacote"
		Copy-Item $pgRelease.File $pgInstaller -Force
		$pgReady = Test-Path $pgInstaller
	} else {
		$pgReady = Download-File -Url $POSTGRES_URL -Output $pgInstaller
	}
	if ($pgReady) {
		Write-Host "    Instalando PostgreSQL (modo silencioso)..."
		Write-Host "    Senha do superusuário postgres: postgres" -ForegroundColor Yellow

		$installArgs = @(
			"--mode", "unattended",
			"--unattendedmodeui", "minimal",
			"--prefix", $POSTGRES_DIR,
			"--datadir", "$POSTGRES_DIR\data",
			"--superpassword", "postgres",
			"--serverport", "5432",
			"--servicename", "postgresql-gboc",
			"--locale", "C",
			"--enable-components", "server"
		)

		$process = Start-Process -FilePath $pgInstaller -ArgumentList $installArgs -Wait -NoNewWindow -PassThru

		# Verificar se instalou
		Start-Sleep -Seconds 5

		if (Test-Path $pgExe) {
			Write-Success "PostgreSQL instalado com sucesso"
		}
		else {
			Write-Warning "Instalação automática falhou (código: $($process.ExitCode))"
			Write-Host "`n    OPÇÕES:" -ForegroundColor Yellow
			Write-Host "    1. Instalar PostgreSQL manualmente (recomendado)"
			Write-Host "    2. Usar PostgreSQL existente no sistema"
			Write-Host "    3. Tentar instalação interativa"
			Write-Host "    4. Cancelar instalação"

			Write-Host "`n    Escolha uma opção (1-4): " -NoNewline -ForegroundColor Yellow
			if ($Unattended) {
				Write-Host "4 (modo automático: instale o PostgreSQL e execute novamente)"
				$choice = "4"
			}
			else {
				$choice = Read-Host
			}

			switch ($choice) {
				"1" {
					Write-Host "`n    Abrindo instalador manual do PostgreSQL..." -ForegroundColor Cyan
					Write-Host "    Configure com as seguintes opções:" -ForegroundColor Yellow
					Write-Host "      • Diretório: $POSTGRES_DIR"
					Write-Host "      • Porta: 5432"
					Write-Host "      • Senha: postgres"
					Write-Host "      • Locale: C ou Portuguese_Brazil.1252"
					Write-Host "`n    Pressione ENTER após concluir a instalação..." -NoNewline

					Start-Process -FilePath $pgInstaller -Wait
					Read-Host

					if (-not (Test-Path $pgExe)) {
						Write-Error "PostgreSQL não foi instalado. Abortando."
						Remove-Item $pgInstaller -Force -ErrorAction SilentlyContinue
						exit 1
					}
					Write-Success "PostgreSQL instalado manualmente"
				}
				"2" {
					Write-Host "`n    Localize a instalação existente do PostgreSQL" -ForegroundColor Cyan
					Write-Host "    Caminho padrão: C:\Program Files\PostgreSQL\16\bin" -ForegroundColor Yellow
					Write-Host "`n    Digite o caminho do diretório 'bin' do PostgreSQL: " -NoNewline
					$existingPgBin = Read-Host

					if (Test-Path "$existingPgBin\postgres.exe") {
						$POSTGRES_DIR = Split-Path -Parent $existingPgBin
						$pgBin = $existingPgBin
						$pgExe = "$pgBin\postgres.exe"
						Write-Success "Usando PostgreSQL existente: $POSTGRES_DIR"
					}
					else {
						Write-Error "PostgreSQL não encontrado em: $existingPgBin"
						exit 1
					}
				}
				"3" {
					Write-Host "`n    Abrindo instalador interativo..." -ForegroundColor Cyan
					Write-Host "    Use as configurações recomendadas acima."
					Start-Process -FilePath $pgInstaller -Wait

					if (-not (Test-Path $pgExe)) {
						Write-Error "PostgreSQL não foi instalado. Abortando."
						Remove-Item $pgInstaller -Force -ErrorAction SilentlyContinue
						exit 1
					}
					Write-Success "PostgreSQL instalado interativamente"
				}
				default {
					Write-Error "Instalação cancelada pelo usuário"
					Remove-Item $pgInstaller -Force -ErrorAction SilentlyContinue
					exit 1
				}
			}
		}

		Remove-Item $pgInstaller -Force -ErrorAction SilentlyContinue
	}
	else {
		Write-Error "Não foi possível baixar o PostgreSQL"
		exit 1
	}
}

# Adicionar PostgreSQL ao PATH da sessão
$env:PATH = "$pgBin;$env:PATH"

# Aguardar PostgreSQL inicializar
Write-Step "Aguardando PostgreSQL inicializar"
Start-Sleep -Seconds 10

# Iniciar serviço PostgreSQL
Write-Step "Iniciando serviço PostgreSQL"

# Tentar encontrar o serviço pelo nome
$pgService = Get-Service -Name "postgresql-*" -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not $pgService) {
	# Tentar nome alternativo
	$pgService = Get-Service -Name "postgresql-x64-*" -ErrorAction SilentlyContinue | Select-Object -First 1
}

if ($pgService) {
	Write-Host "    Encontrado serviço: $($pgService.Name)" -ForegroundColor Cyan
	if ($pgService.Status -ne "Running") {
		try {
			Start-Service $pgService.Name -ErrorAction Stop
			Start-Sleep -Seconds 5
			Write-Success "Serviço PostgreSQL iniciado"
		}
		catch {
			Write-Warning "Falha ao iniciar serviço: $_"
			Write-Host "    Tentando inicialização manual..." -ForegroundColor Yellow

			# Tentar iniciar manualmente
			if (Test-Path "$pgBin\pg_ctl.exe") {
				$pgCtlArgs = @("start", "-D", "`"$POSTGRES_DIR\data`"", "-w", "-t", "60")
				$pgCtlProcess = Start-Process -FilePath "$pgBin\pg_ctl.exe" -ArgumentList $pgCtlArgs -Wait -NoNewWindow -PassThru

				if ($pgCtlProcess.ExitCode -eq 0) {
					Write-Success "PostgreSQL iniciado manualmente"
				}
				else {
					Write-Error "Não foi possível iniciar o PostgreSQL"
					Write-Host "    Tente iniciar manualmente: $pgBin\pg_ctl.exe start -D `"$POSTGRES_DIR\data`"" -ForegroundColor Yellow
					exit 1
				}
			}
		}
	}
	else {
		Write-Success "Serviço PostgreSQL já em execução"
	}
}
else {
	Write-Warning "Serviço PostgreSQL não encontrado como serviço Windows"
	Write-Host "    Tentando inicialização manual..." -ForegroundColor Yellow

	if (Test-Path "$pgBin\pg_ctl.exe") {
		# Verificar se já está rodando
		$pgRunning = Get-Process -Name "postgres" -ErrorAction SilentlyContinue

		if ($pgRunning) {
			Write-Success "PostgreSQL já está em execução (processo detectado)"
		}
		else {
			$pgCtlArgs = @("start", "-D", "`"$POSTGRES_DIR\data`"", "-w", "-t", "60")
			$pgCtlProcess = Start-Process -FilePath "$pgBin\pg_ctl.exe" -ArgumentList $pgCtlArgs -Wait -NoNewWindow -PassThru

			if ($pgCtlProcess.ExitCode -eq 0) {
				Write-Success "PostgreSQL iniciado manualmente"
			}
			else {
				Write-Error "Não foi possível iniciar o PostgreSQL"
				Write-Host "    Execute manualmente: $pgBin\pg_ctl.exe start -D `"$POSTGRES_DIR\data`"" -ForegroundColor Yellow
				exit 1
			}
		}
	}
	else {
		Write-Error "pg_ctl.exe não encontrado. Instalação incompleta."
		exit 1
	}
}

# Aguardar um pouco mais para garantir que está pronto
Start-Sleep -Seconds 5

# Criar banco e usuário
Write-Step "Configurando banco de dados GBOC"

$env:PGPASSWORD = "postgres"
$maxRetries = 3
$retryCount = 0
$dbCreated = $false

while (-not $dbCreated -and $retryCount -lt $maxRetries) {
	try {
		$retryCount++
		Write-Host "    Tentativa $retryCount de $maxRetries..." -ForegroundColor Cyan

		# Verificar se psql existe
		if (-not (Test-Path "$pgBin\psql.exe")) {
			throw "psql.exe não encontrado em $pgBin"
		}

		# Testar conexão primeiro
		$testResult = & "$pgBin\psql.exe" -U postgres -h localhost -p 5432 -d postgres -c "SELECT version();" 2>&1

		if ($LASTEXITCODE -ne 0) {
			throw "Não foi possível conectar ao PostgreSQL: $testResult"
		}

		Write-Host "    Conexão estabelecida com sucesso" -ForegroundColor Green

		# Criar banco de dados
		$createDbScript = @"
-- Criar banco se não existir
SELECT 'CREATE DATABASE $DB_NAME' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec

-- Criar usuário se não existir
DO `$`$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$DB_USER') THEN
	  CREATE USER $DB_USER WITH ENCRYPTED PASSWORD '$DB_PASSWORD';
   END IF;
END
`$`$;

-- Conceder privilégios
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
"@

		$createDbScript | & "$pgBin\psql.exe" -U postgres -h localhost -p 5432 -d postgres -f - 2>&1 | Out-Null

		if ($LASTEXITCODE -eq 0) {
			# Conceder privilégios no schema public
			$grantScript = "GRANT ALL ON SCHEMA public TO $DB_USER;"
			$grantScript | & "$pgBin\psql.exe" -U postgres -h localhost -p 5432 -d $DB_NAME -f - 2>&1 | Out-Null

			Write-Success "Banco $DB_NAME criado com usuário $DB_USER"
			$dbCreated = $true
		}
		else {
			throw "Erro ao executar script de criação"
		}
	}
	catch {
		Write-Warning "Erro: $_"
		if ($retryCount -lt $maxRetries) {
			Write-Host "    Aguardando 5 segundos antes de tentar novamente..." -ForegroundColor Yellow
			Start-Sleep -Seconds 5
		}
	}
}

if (-not $dbCreated) {
	Write-Error "Não foi possível criar o banco de dados após $maxRetries tentativas"
	Write-Host "`n    SOLUÇÃO MANUAL:" -ForegroundColor Yellow
	Write-Host "    1. Abra o psql:" -ForegroundColor Cyan
	Write-Host "       cd $pgBin"
	Write-Host "       .\psql.exe -U postgres"
	Write-Host "    2. Execute os comandos:" -ForegroundColor Cyan
	Write-Host "       CREATE DATABASE $DB_NAME;"
	Write-Host "       CREATE USER $DB_USER WITH ENCRYPTED PASSWORD '$DB_PASSWORD';"
	Write-Host "       GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
	Write-Host "       \c $DB_NAME"
	Write-Host "       GRANT ALL ON SCHEMA public TO $DB_USER;"
	Write-Host "`n    Deseja continuar mesmo assim? (S/N): " -NoNewline -ForegroundColor Yellow
	$continue = if ($Unattended) { Write-Host "N (automático)"; "N" } else { Read-Host }

	if ($continue -ne "S" -and $continue -ne "s") {
		exit 1
	}
}

# ============================================================================
# INSTALAÇÃO DOS MOTORES DE BACKUP
# ============================================================================

Write-Step "Instalando/atualizando motores de backup (ultima versao)"

# restic, Kopia e Duplicati na ultima release do GitHub; versao instalada mais antiga e atualizada.
# Tambem define RESTIC_PATH / KOPIA_PATH / DUPLICATI_PATH (maquina).
$engines = Install-GbocEngines -ToolsDir $TOOLS_DIR
foreach ($k in @("restic", "kopia", "duplicati")) {
	if ($engines[$k]) { Write-Success "${k}: $($engines[$k])" } else { Write-Warning "$k nao instalado" }
}

# Adicionar motores ao PATH do SISTEMA (não apenas da sessão)
Write-Step "Configurando PATH do sistema"
$systemPath = [Environment]::GetEnvironmentVariable("Path", "Machine")
# Python fica fora: o instalador do Python cuida do PATH dele (pasta de versao fixa ficaria velha ao atualizar)
$pathsToAdd = @($RESTIC_DIR, $KOPIA_DIR, $DUPLICATI_DIR, $pgBin)

$updated = $false
foreach ($pathToAdd in $pathsToAdd) {
	if ($systemPath -notlike "*$pathToAdd*") {
		$systemPath = "$systemPath;$pathToAdd"
		$updated = $true
		Write-Success "Adicionado ao PATH: $pathToAdd"
	}
}

if ($updated) {
	[Environment]::SetEnvironmentVariable("Path", $systemPath, "Machine")
	Write-Success "PATH do sistema atualizado"
}
else {
	Write-Success "PATH já está configurado"
}

# Atualizar PATH da sessão atual
$env:PATH = "$RESTIC_DIR;$KOPIA_DIR;$DUPLICATI_DIR;$PYTHON_DIR;$PYTHON_DIR\Scripts;$pgBin;$env:PATH"

# Configurar permissões de acesso para o serviço LocalSystem
Write-Step "Configurando permissões de sistema"

$foldersToSecure = @($AGENT_DIR, $TOOLS_DIR, $RESTIC_DIR, $KOPIA_DIR, $DUPLICATI_DIR)

foreach ($folder in $foldersToSecure) {
	if (Test-Path $folder) {
		try {
			# Dar permissões full control para SYSTEM e Administrators
			$acl = Get-Acl $folder

			# Regra para NT AUTHORITY\SYSTEM
			$systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
				"NT AUTHORITY\SYSTEM",
				"FullControl",
				"ContainerInherit,ObjectInherit",
				"None",
				"Allow"
			)
			$acl.AddAccessRule($systemRule)

			# Regra para BUILTIN\Administrators
			$adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
				"BUILTIN\Administrators",
				"FullControl",
				"ContainerInherit,ObjectInherit",
				"None",
				"Allow"
			)
			$acl.AddAccessRule($adminRule)

			Set-Acl -Path $folder -AclObject $acl
			Write-Success "Permissões configuradas: $folder"
		}
		catch {
			Write-Warning "Não foi possível configurar permissões em: $folder"
		}
	}
}

# Criar variáveis de ambiente do sistema para os motores
Write-Step "Criando variáveis de ambiente do sistema"

[Environment]::SetEnvironmentVariable("RESTIC_PATH", "$RESTIC_DIR\restic.exe", "Machine")
[Environment]::SetEnvironmentVariable("KOPIA_PATH", "$KOPIA_DIR\kopia.exe", "Machine")
[Environment]::SetEnvironmentVariable("DUPLICATI_PATH", "$DUPLICATI_DIR\Duplicati.CommandLine.exe", "Machine")
[Environment]::SetEnvironmentVariable("GBOC_TOOLS_DIR", $TOOLS_DIR, "Machine")

Write-Success "Variáveis de ambiente criadas"

# ============================================================================
# INSTALAÇÃO DO GBOC AGENT
# ============================================================================

Write-Step "Instalando GBOC Agent"

# Copiar arquivos do Agent (instalador na pasta do Agent ou em uma subpasta dela)
$sourceDir = if (Test-Path "$PSScriptRoot\agent_server.py") { $PSScriptRoot } else { Split-Path -Parent $PSScriptRoot }
if (Test-Path "$sourceDir\agent_server.py") {
	Write-Host "    Copiando arquivos do Agent..."
	Copy-Item -Path "$sourceDir\*" -Destination $AGENT_DIR -Recurse -Force
	Write-Success "Arquivos do Agent copiados"
}
else {
	Write-Error "Não foi possível localizar os arquivos do Agent"
	Write-Host "    Execute este instalador a partir do diretório GBOC-Agent" -ForegroundColor Yellow
	exit 1
}

# Instalar dependências Python e Stack de Segurança
Write-Step "Instalando dependências Python e Stack de Segurança"
$requirementsPath = "$AGENT_DIR\requirements.txt"

if (Test-Path $requirementsPath) {
	& "$PYTHON_DIR\python.exe" -m pip install --upgrade pip --quiet
	& "$PYTHON_DIR\python.exe" -m pip install -r $requirementsPath --quiet
	& "$PYTHON_DIR\python.exe" -m pip install yara-python --quiet
	Write-Success "Dependências e Stack YARA/Segurança instaladas com sucesso"
}
else {
	Write-Error "Arquivo requirements.txt não encontrado"
	exit 1
}

# Configurar Regra de Firewall
Write-Step "Configurando Firewall do Windows"
try {
	New-NetFirewallRule -DisplayName "GBOC Agent" -Direction Inbound -LocalPort 9200 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue | Out-Null
	Write-Success "Regra de Firewall liberada na porta 9200 (TCP)"
} catch {
	Write-Warning "Não foi possível criar a regra de Firewall automaticamente"
}

# Criar arquivo .env
Write-Step "Configurando variáveis de ambiente"

$envContent = @"
# GBOC Agent - Configuração
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
AGENT_PORT=9200
SECRET_KEY=$(New-Guid)
RESTIC_PATH=$RESTIC_DIR\restic.exe
KOPIA_PATH=$KOPIA_DIR\kopia.exe
DUPLICATI_PATH=$DUPLICATI_DIR\Duplicati.CommandLine.exe
LOG_LEVEL=INFO
"@

Set-Content -Path "$AGENT_DIR\.env" -Value $envContent
Write-Success "Arquivo .env criado"

# start_agent.bat / start_agent.ps1 copiados do pacote escolhem o Python sozinhos (scripts\gboc_python.ps1).
# Antes era gerado aqui um start_agent.bat com o caminho do python.exe fixo e o ponto de entrada antigo.

# ============================================================================
# CONFIGURAÇÃO DO SERVIÇO WINDOWS (OPCIONAL)
# ============================================================================

Write-Host "`n"
Write-Host "Deseja instalar o GBOC Agent como serviço do Windows? (S/N): " -NoNewline -ForegroundColor Yellow
$installService = if ($Unattended) { Write-Host "S (automático)"; "S" } else { Read-Host }

if ($installService -eq "S" -or $installService -eq "s") {
	Write-Step "Configurando serviço Windows"

	# NSSM (Non-Sucking Service Manager) para criar serviço: do pacote (Prereqs\) ou da internet.
	# Antes o nssm.exe era movido para "$TOOLS_DIR\nssm" sem a pasta existir (virava um arquivo "nssm") e o serviço não era criado.
	$nssmDir = "$TOOLS_DIR\nssm"
	if (-not (Install-GbocNssm -ToolsDir $TOOLS_DIR)) {
		Write-Warning "NSSM não disponível (sem pacote e sem acesso a nssm.cc); serviço do Windows não será criado"
	}

	$serviceName = "GBOCAgent"
	$existingService = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

	if ($existingService) {
		Write-Warning "Serviço $serviceName já existe. Removendo..."
		& "$nssmDir\nssm.exe" stop $serviceName
		& "$nssmDir\nssm.exe" remove $serviceName confirm
	}

	Write-Host "    Criando serviço $serviceName..."
	# O servico executa start_agent.ps1 -Service (e nao um python.exe com caminho fixo): a cada inicio o
	# script escolhe o Python mais novo com as dependencias. Atualizar ou trocar a pasta do Python nao
	# derruba o servico. (AGENT_DIR sem espacos: C:\GBOC\Agent)
	New-Item -ItemType Directory -Path "$AGENT_DIR\logs" -Force | Out-Null
	$psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
	& "$nssmDir\nssm.exe" install $serviceName $psExe
	& "$nssmDir\nssm.exe" set $serviceName AppParameters "-NoProfile -ExecutionPolicy Bypass -File $AGENT_DIR\start_agent.ps1 -Service"
	& "$nssmDir\nssm.exe" set $serviceName AppDirectory $AGENT_DIR
	& "$nssmDir\nssm.exe" set $serviceName AppRestartDelay 15000
	& "$nssmDir\nssm.exe" set $serviceName DisplayName "GBOC Backup Agent"
	& "$nssmDir\nssm.exe" set $serviceName Description "GBOC Agent de backup e restauração"
	& "$nssmDir\nssm.exe" set $serviceName Start SERVICE_AUTO_START

	# Configurar serviço para rodar como LocalSystem (acesso total ao sistema)
	& "$nssmDir\nssm.exe" set $serviceName ObjectName LocalSystem

	# Configurar variáveis de ambiente do serviço
	& "$nssmDir\nssm.exe" set $serviceName AppEnvironmentExtra "RESTIC_PATH=$RESTIC_DIR\restic.exe" "KOPIA_PATH=$KOPIA_DIR\kopia.exe" "DUPLICATI_PATH=$DUPLICATI_DIR\Duplicati.CommandLine.exe" "PYTHONIOENCODING=utf-8"

	# Configurar stdout/stderr para logs
	& "$nssmDir\nssm.exe" set $serviceName AppStdout "$AGENT_DIR\logs\service_stdout.log"
	& "$nssmDir\nssm.exe" set $serviceName AppStderr "$AGENT_DIR\logs\service_stderr.log"
	& "$nssmDir\nssm.exe" set $serviceName AppRotateFiles 1
	& "$nssmDir\nssm.exe" set $serviceName AppRotateSeconds 86400
	& "$nssmDir\nssm.exe" set $serviceName AppRotateBytes 10485760

	Write-Host "    Iniciando serviço..."
	Start-Service $serviceName
	Write-Success "Serviço $serviceName criado e iniciado (LocalSystem)"
}

# ============================================================================
# INSCRIÇÃO NO GBOC SERVER (token de instalação)
# ============================================================================

if ($ServerURL -and $InstallToken) {
	Write-Step "Inscrevendo o agente no GBOC Server ($ServerURL)"
	Push-Location $AGENT_DIR
	$prevEap = $ErrorActionPreference
	$ErrorActionPreference = "Continue"
	try {
		$enrollOut = & "$PYTHON_DIR\python.exe" -m core.enrollment --server $ServerURL --token $InstallToken 2>&1 | Out-String
	}
	finally { $ErrorActionPreference = $prevEap; Pop-Location }
	if ($LASTEXITCODE -eq 0) {
		Write-Success "Agente inscrito no Server: $($enrollOut.Trim())"
	}
	else {
		# Sem rede/Server no momento: o serviço tenta novamente sozinho (enroll.json)
		$seedDir = "$AGENT_DIR\data\central"     # dentro da pasta do Agente (antes: C:\ProgramData\GBOC)
		New-Item -ItemType Directory -Force -Path $seedDir | Out-Null
		@{ server_url = $ServerURL; install_token = $InstallToken } | ConvertTo-Json | Set-Content -Path "$seedDir\enroll.json" -Encoding UTF8
		Write-Warning "Inscrição não concluída agora ($($enrollOut.Trim())). O serviço tentará novamente a cada 5 minutos."
	}
	$svc = Get-Service -Name "GBOCAgent" -ErrorAction SilentlyContinue
	if ($svc) { Restart-Service "GBOCAgent" -ErrorAction SilentlyContinue }
}

# ============================================================================
# FINALIZAÇÃO
# ============================================================================

Write-Host @"

╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║          INSTALAÇÃO CONCLUÍDA COM SUCESSO! ✓             ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝

"@ -ForegroundColor Green

Write-Host "INFORMAÇÕES DA INSTALAÇÃO:" -ForegroundColor Cyan
Write-Host "  • Agent instalado em: $AGENT_DIR"
Write-Host "  • Python: $pythonExe (escolhido a cada inicio: scripts\gboc_python.ps1)"
Write-Host "  • PostgreSQL: $POSTGRES_DIR"
Write-Host "  • Banco de dados: $DB_NAME"
Write-Host "  • Usuário do banco: $DB_USER"
Write-Host "  • Senha do banco: $DB_PASSWORD"
Write-Host "  • Restic: $RESTIC_DIR\restic.exe"
Write-Host "  • Kopia: $KOPIA_DIR\kopia.exe"
Write-Host "  • Duplicati: $DUPLICATI_DIR\Duplicati.CommandLine.exe"

Write-Host "`nPRÓXIMOS PASSOS:" -ForegroundColor Yellow
Write-Host "  1. Acesse: https://localhost:9200"
Write-Host "  2. Faça login com as credenciais padrão"
Write-Host "  3. Configure repositórios e tarefas de backup"

if ($installService -eq "S" -or $installService -eq "s") {
	Write-Host "`n  O serviço GBOCAgent foi iniciado automaticamente." -ForegroundColor Green
}
else {
	Write-Host "`n  Para iniciar o Agent manualmente:" -ForegroundColor Yellow
	Write-Host "  cd $AGENT_DIR"
	Write-Host "  .\start_agent.bat"
}

Write-Host "`nPressione qualquer tecla para sair..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
