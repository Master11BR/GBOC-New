<#
==============================================================================
GBOC System v14.8.2 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
#>

# ============================================================================
# GBOC Agent - Instalador Simplificado v1.1
# ============================================================================
# Versão alternativa que usa PostgreSQL portátil (sem instalador EDB)
# Mais rápido e confiável para ambientes corporativos
# ============================================================================

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Clear-Host

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

# Versoes: descobertas na hora da instalacao (ultima estavel) por scripts\gboc_prereqs.ps1
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

function Download-File {
	param(
		[string]$Url,
		[string]$Output
	)

	Write-Host "    Baixando: $(Split-Path $Url -Leaf)"
	try {
		[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
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
# BANNER
# ============================================================================

Write-Host @"

╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║     GBOC Agent - Instalador Simplificado v1.1            ║
║     (PostgreSQL Portátil)                                ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝

"@ -ForegroundColor Cyan

Write-Step "Verificando privilégios de administrador"
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
	Write-Error "Execute este script como Administrador!"
	exit 1
}
Write-Success "Executando como Administrador"

# ============================================================================
# CRIAÇÃO DE DIRETÓRIOS
# ============================================================================

Write-Step "Criando estrutura de diretórios"

@($INSTALL_ROOT, $AGENT_DIR, $TOOLS_DIR, $PYTHON_DIR, $POSTGRES_DIR, $RESTIC_DIR, $KOPIA_DIR, $DUPLICATI_DIR) | ForEach-Object {
	if (-not (Test-Path $_)) {
		New-Item -ItemType Directory -Path $_ -Force | Out-Null
		Write-Success "Criado: $_"
	}
}

# ============================================================================
# PYTHON
# ============================================================================

Write-Step "Python (ultima versao estavel)"
# Ultima versao do python.org (reaproveita a instalada se ja for a mais nova) com as dependencias do Agente.
# A inicializacao escolhe o Python sozinha (scripts\gboc_python.ps1): atualizar depois nao quebra nada.
$PYTHON_CMD = Install-GbocPython -Requirements "$PSScriptRoot\requirements.txt"
if (-not $PYTHON_CMD) {
	Write-Error "Nao foi possivel instalar o Python com as dependencias do GBOC"
	exit 1
}
$PYTHON_DIR = Split-Path $PYTHON_CMD -Parent
$env:PATH = "$PYTHON_DIR;$PYTHON_DIR\Scripts;$env:PATH"
Write-Success "Usando: $PYTHON_CMD"

# ============================================================================
# POSTGRESQL PORTÁTIL
# ============================================================================

Write-Step "PostgreSQL (portátil)"

$pgBin = "$POSTGRES_DIR\pgsql\bin"
$pgExe = "$pgBin\postgres.exe"
$pgData = "$POSTGRES_DIR\data"

if (Test-Path $pgExe) {
	Write-Warning "PostgreSQL já instalado"
}
else {
	$pgRelease = Get-GbocPostgresRelease -Binaries
	$POSTGRES_VERSION = $pgRelease.Version
	Write-Host "    Ultima versao: PostgreSQL $POSTGRES_VERSION"
	$pgZip = "$env:TEMP\postgres.zip"
	if (Download-File -Url $pgRelease.Url -Output $pgZip) {
		Write-Host "    Extraindo PostgreSQL..."
		Expand-Archive -Path $pgZip -DestinationPath $POSTGRES_DIR -Force
		Remove-Item $pgZip -Force

		if (Test-Path $pgExe) {
			Write-Success "PostgreSQL extraído"
		}
		else {
			Write-Error "Falha ao extrair PostgreSQL"
			exit 1
		}
	}
}

# Garantir permissões no diretório de dados
if (Test-Path $pgData) {
	# Se data existe mas sem postgresql.conf, limpar tentativa anterior
	if (-not (Test-Path "$pgData\postgresql.conf")) {
		Write-Host "    Limpando diretório de dados incompleto..."
		Remove-Item -Recurse -Force $pgData
		New-Item -ItemType Directory -Path $pgData -Force | Out-Null
	}
}
else {
	New-Item -ItemType Directory -Path $pgData -Force | Out-Null
}

# Conceder permissões totais para o usuário atual
Write-Host "    Configurando permissões..."
$acl = Get-Acl $POSTGRES_DIR
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$permission = New-Object System.Security.AccessControl.FileSystemAccessRule(
	$currentUser,
	"FullControl",
	"ContainerInherit,ObjectInherit",
	"None",
	"Allow"
)
$acl.SetAccessRule($permission)
Set-Acl -Path $POSTGRES_DIR -AclObject $acl

# Aplicar recursivamente
Get-ChildItem -Path $POSTGRES_DIR -Recurse | ForEach-Object {
	try {
		$itemAcl = Get-Acl $_.FullName
		$itemAcl.SetAccessRule($permission)
		Set-Acl -Path $_.FullName -AclObject $itemAcl -ErrorAction SilentlyContinue
	}
	catch {
		# Ignorar erros de permissão em arquivos específicos
	}
}

Write-Success "Permissões configuradas"

# Inicializar cluster se não existir
if (-not (Test-Path "$pgData\postgresql.conf")) {
	Write-Host "    Inicializando banco de dados..."

	$initResult = & "$pgBin\initdb.exe" -D $pgData -U postgres -A trust --locale=C --encoding=UTF8 2>&1

	if (Test-Path "$pgData\postgresql.conf") {
		Write-Success "Cluster inicializado"

		# Configurar postgresql.conf para aceitar conexões locais
		$pgConf = Get-Content "$pgData\postgresql.conf"
		$pgConf = $pgConf -replace "#listen_addresses = 'localhost'", "listen_addresses = 'localhost'"
		$pgConf = $pgConf -replace "#port = 5432", "port = 5432"
		Set-Content "$pgData\postgresql.conf" -Value $pgConf

		# Configurar pg_hba.conf para trust local
		$hbaConf = @"
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     trust
host    all             all             127.0.0.1/32            trust
host    all             all             ::1/128                 trust
"@
		Set-Content "$pgData\pg_hba.conf" -Value $hbaConf
		Write-Success "Configurações aplicadas"
	}
	else {
		Write-Error "Falha ao inicializar cluster"
		Write-Host "    Output:" -ForegroundColor Yellow
		$initResult | ForEach-Object { Write-Host "    $_" }
		exit 1
	}
}

$env:PATH = "$pgBin;$env:PATH"

# Iniciar PostgreSQL
Write-Step "Iniciando PostgreSQL"

$pgProcess = Get-Process -Name "postgres" -ErrorAction SilentlyContinue
if ($pgProcess) {
	Write-Warning "PostgreSQL já em execução"
}
else {
	Write-Host "    Iniciando servidor..."

	$logFile = "$POSTGRES_DIR\logfile.log"

	# Usar Start-Process para não bloquear o script
	Start-Process -FilePath "$pgBin\pg_ctl.exe" -ArgumentList "start -D $pgData -l $logFile -w" -NoNewWindow -Wait:$false

	# Aguardar inicialização
	Write-Host "    Aguardando PostgreSQL..." -NoNewline
	$ready = $false
	for ($i = 0; $i -lt 15; $i++) {
		Start-Sleep -Seconds 1
		Write-Host "." -NoNewline
		$pgProc = Get-Process -Name "postgres" -ErrorAction SilentlyContinue
		if ($pgProc) { $ready = $true; break }
	}
	Write-Host ""

	if ($ready) {
		Start-Sleep -Seconds 2
		Write-Success "PostgreSQL iniciado"
	}
	else {
		Write-Warning "PostgreSQL pode não ter iniciado"
		Write-Host "    Log: $logFile" -ForegroundColor Yellow
		if (Test-Path $logFile) {
			Get-Content $logFile -Tail 5 | ForEach-Object { Write-Host "    $_" }
		}
		Write-Host "`n    Continuar mesmo assim? (S/N): " -NoNewline -ForegroundColor Yellow
		$continue = Read-Host
		if ($continue -ne "S" -and $continue -ne "s") { exit 1 }
	}
}

# Criar banco
Write-Step "Criando banco de dados $DB_NAME"

Start-Sleep -Seconds 3

try {
	# Verificar se o banco já existe
	$dbExists = & "$pgBin\psql.exe" -U postgres -h localhost -lqt 2>&1 | Select-String -Pattern $DB_NAME -Quiet

	if (-not $dbExists) {
		# Criar usuário
		& "$pgBin\psql.exe" -U postgres -h localhost -c "CREATE USER $DB_USER WITH ENCRYPTED PASSWORD '$DB_PASSWORD';" 2>&1 | Out-Null

		# Criar banco
		& "$pgBin\createdb.exe" -U postgres -h localhost -O $DB_USER $DB_NAME 2>&1 | Out-Null

		# Conceder privilégios
		& "$pgBin\psql.exe" -U postgres -h localhost -d $DB_NAME -c "GRANT ALL ON SCHEMA public TO $DB_USER;" 2>&1 | Out-Null

		Write-Success "Banco $DB_NAME criado com usuário $DB_USER"
	}
	else {
		Write-Warning "Banco $DB_NAME já existe"
		& "$pgBin\psql.exe" -U postgres -h localhost -d $DB_NAME -c "GRANT ALL ON SCHEMA public TO $DB_USER;" 2>&1 | Out-Null
	}
}
catch {
	Write-Warning "Erro ao criar banco do Agent: $_"
}

# Criar banco do Server (gboc) se Agent e Server rodam no mesmo host
Write-Step "Criando banco de dados do Server (gboc)"

try {
	$srvDbExists = & "$pgBin\psql.exe" -U postgres -h localhost -lqt 2>&1 | Select-String -Pattern "\bgboc\b" -Quiet

	if (-not $srvDbExists) {
		# Criar usuário gboc_user se não existir
		& "$pgBin\psql.exe" -U postgres -h localhost -c "DO `$`$BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gboc_user') THEN CREATE ROLE gboc_user LOGIN PASSWORD 'Stoms2025+'; END IF; END`$`$;" 2>&1 | Out-Null

		# Criar banco
		& "$pgBin\createdb.exe" -U postgres -h localhost -O gboc_user gboc 2>&1 | Out-Null

		# Conceder privilégios
		& "$pgBin\psql.exe" -U postgres -h localhost -d gboc -c "ALTER SCHEMA public OWNER TO gboc_user; GRANT ALL ON SCHEMA public TO gboc_user;" 2>&1 | Out-Null

		# Permissões padrão
		& "$pgBin\psql.exe" -U postgres -h localhost -d gboc -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO gboc_user; ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO gboc_user;" 2>&1 | Out-Null

		Write-Success "Banco gboc criado com usuário gboc_user"
	}
	else {
		Write-Warning "Banco gboc já existe"
	}
}
catch {
	Write-Warning "Erro ao criar banco do Server: $_"
	Write-Host "    Pode ser criado depois com: setup_database.bat no GBOC-Server" -ForegroundColor Yellow
}

# NOTA: PostgreSQL portátil será iniciado automaticamente pelos scripts
# start_agent.bat e start_server.bat quando necessário.

# ============================================================================
# MOTORES DE BACKUP
# ============================================================================

Write-Step "Instalando motores de backup"

# restic, Kopia e Duplicati na ultima release (versoes antigas sao atualizadas)
$engines = Install-GbocEngines -ToolsDir $TOOLS_DIR

$env:PATH = "$RESTIC_DIR;$KOPIA_DIR;$DUPLICATI_DIR;$env:PATH"

# Persistir paths dos motores no PATH do sistema
Write-Step "Configurando PATH do sistema para motores de backup"

$systemPath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$pathsToAdd = @($RESTIC_DIR, $KOPIA_DIR, $DUPLICATI_DIR, $pgBin) | Where-Object { 
    $_ -and (Test-Path $_) -and ($systemPath -notlike "*$_*") 
}

if ($pathsToAdd) {
    $newPath = ($systemPath.TrimEnd(';') + ';' + ($pathsToAdd -join ';'))
    [Environment]::SetEnvironmentVariable("Path", $newPath, "Machine")
    foreach ($p in $pathsToAdd) {
        Write-Success "Adicionado ao PATH: $p"
    }
}
else {
    Write-Warning "Paths já configurados no sistema"
}

# ============================================================================
# GBOC AGENT
# ============================================================================

Write-Step "Instalando GBOC Agent"

$sourceDir = $PSScriptRoot
if (Test-Path "$sourceDir\agent_server.py") {
	Copy-Item -Path "$sourceDir\*" -Destination $AGENT_DIR -Recurse -Force -Exclude "install*.ps1"
	Write-Success "Arquivos copiados"
}

# Dependências Python
Write-Step "Instalando dependências Python"
if (Test-Path "$AGENT_DIR\requirements.txt") {
	& $PYTHON_CMD -m pip install --upgrade pip --quiet
	& $PYTHON_CMD -m pip install -r "$AGENT_DIR\requirements.txt" --quiet
	Write-Success "Dependências instaladas"
}

# Arquivo .env
Write-Step "Criando configuração"

$envContent = @"
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
AGENT_PORT=9200
SECRET_KEY=$(New-Guid)
RESTIC_PATH=$RESTIC_DIR\restic.exe
KOPIA_PATH=$KOPIA_DIR\kopia.exe
DUPLICATI_PATH=$DUPLICATI_DIR\Duplicati.CommandLine.exe
LOG_LEVEL=INFO
"@

Set-Content -Path "$AGENT_DIR\.env" -Value $envContent
Write-Success "Configuração criada"

# Scripts de inicialização
# start_agent.bat do pacote ja escolhe o Python (scripts\gboc_python.ps1) e inicia o PostgreSQL portatil.
# Antes era gerado aqui um start_agent.bat com o python.exe fixo, que parava de funcionar ao atualizar o Python.

$stopScript = @"
@echo off
title Parando GBOC Agent
echo ============================================
echo  GBOC Agent - Parando servicos...
echo ============================================
echo.

echo Parando PostgreSQL...
"$pgBin\pg_ctl.exe" stop -D "$pgData" -m fast
echo.
echo Servicos parados.
echo.
pause
"@

Set-Content -Path "$AGENT_DIR\stop_agent.bat" -Value $stopScript

$statusScript = @"
@echo off
title GBOC Agent - Status
echo ============================================
echo  GBOC Agent - Status dos Servicos
echo ============================================
echo.

echo PostgreSQL:
"$pgBin\pg_ctl.exe" status -D "$pgData"
echo.

echo Python/Agent:
tasklist /FI "IMAGENAME eq python.exe" | find /I "python.exe" >nul
if errorlevel 1 (
	echo Nao detectado
) else (
	echo Em execucao
)
echo.

pause
"@

Set-Content -Path "$AGENT_DIR\status.bat" -Value $statusScript

Write-Success "Scripts criados (stop_agent.bat, status.bat)"

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

Write-Host "INFORMAÇÕES:" -ForegroundColor Cyan
Write-Host "  • Agent: $AGENT_DIR"
Write-Host "  • Banco: $DB_NAME"
Write-Host "  • Usuário: $DB_USER"
Write-Host "  • Senha: $DB_PASSWORD"
Write-Host "  • URL: http://localhost:9200"

Write-Host "`nPARA INICIAR:" -ForegroundColor Yellow
Write-Host "  cd $AGENT_DIR"
Write-Host "  .\start_agent.bat"

Write-Host "`nPressione qualquer tecla para iniciar o Agent agora..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

Set-Location $AGENT_DIR
Start-Process -FilePath "$AGENT_DIR\start_agent.bat"
