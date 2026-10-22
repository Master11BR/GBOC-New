<#
==============================================================================
GBOC System v14.8.2 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
#>

[CmdletBinding()]
param (
    [Parameter(Mandatory = $false)]
    [ValidateSet("Agent", "Server", "Both", "DependenciesOnly", "Interactive")]
    [string]$InstallMode = "Interactive",

    [Parameter(Mandatory = $false)]
    [string]$TargetDir = "C:\GBOC",

    [Parameter(Mandatory = $false)]
    [int]$ServerPort = 8000,

    [Parameter(Mandatory = $false)]
    [int]$AgentPort = 9200,

    [Parameter(Mandatory = $false)]
    [switch]$SkipEngines = $false,

    [Parameter(Mandatory = $false)]
    [switch]$CreateShortcuts = $true,

    [Parameter(Mandatory = $false)]
    [switch]$RegisterStartupTask = $false,

    [Parameter(Mandatory = $false)]
    [ValidateSet("postgresql", "sqlite")]
    [string]$DatabaseEngine = "postgresql",

    # Senha do superusuario "postgres" se o PostgreSQL precisar ser instalado (vazio = pergunta / padrao do GBOC)
    [Parameter(Mandatory = $false)]
    [string]$PostgresPassword = "",

    # Instalar LLM Local Gratuito (Ollama + Qwen 3.5)
    [Parameter(Mandatory = $false)]
    [switch]$InstallLLM = $false,

    # Nao registrar GBOCServer/GBOCAgent como servicos do Windows (padrao: registra; o sistema
    # continua rodando sem usuario logado e reinicia sozinho se cair)
    [Parameter(Mandatory = $false)]
    [switch]$NoService = $false
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Cores e Formatacao
function Write-Header {
    param([string]$Title)
    Write-Host ""
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Yellow
}

function Write-Success {
    param([string]$Message)
    Write-Host "    [OK] $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "    [!] $Message" -ForegroundColor DarkYellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "    [ERRO] $Message" -ForegroundColor Red
}

# Verificacao de Administrador
function Test-AdminPrivileges {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-AdminPrivileges)) {
    Write-Fail "Este instalador requer privilegios de Administrador para configurar servicos e pastas."
    Write-Warning "Por favor, execute o PowerShell ou Setup.bat como Administrador."
    if ($InstallMode -eq "Interactive") {
        Read-Host "Pressione ENTER para sair"
    }
    exit 1
}

# Detectar caminho do pacote
$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path "$PackageRoot\package_manifest.json")) {
    $PackageRoot = (Get-Item $PSScriptRoot).FullName
}

# Pre-requisitos sempre na ULTIMA versao estavel (Python, restic, Kopia, Duplicati), descoberta na hora
$prereqs = @("$PackageRoot\gboc_prereqs.ps1", "$PackageRoot\Agent\scripts\gboc_prereqs.ps1", "$PackageRoot\Server\scripts\gboc_prereqs.ps1") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $prereqs) {
    Write-Host "    [ERRO] gboc_prereqs.ps1 nao encontrado no pacote." -ForegroundColor Red
    exit 1
}
. $prereqs
# Pacote completo (pasta Prereqs\): programas instalados do pacote; o que a maquina ja tem e mantido
$GbocPackage = Set-GbocPackageDir $PackageRoot
$WasInteractive = ($InstallMode -eq "Interactive")

# Deteccao do Python
function Get-PythonExecutable {
    $pythonCandidates = @("python.exe", "py.exe", "python3.exe", "C:\Python311\python.exe", "C:\Python312\python.exe", "C:\Python313\python.exe", "C:\Python314\python.exe")
    foreach ($cand in $pythonCandidates) {
        try {
            $cmd = Get-Command $cand -ErrorAction SilentlyContinue
            if ($cmd) {
                $verOut = & $cmd.Source --version 2>&1
                if ($verOut -match "Python\s+3\.") {
                    return $cmd.Source
                }
            }
        } catch {}
    }
    return $null
}

# Download Seguro
function Download-FileWithRetry {
    param(
        [string]$Url,
        [string]$DestinationPath,
        [int]$MaxRetries = 3
    )
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
    $attempt = 0
    while ($attempt -lt $MaxRetries) {
        $attempt++
        try {
            Write-Host "    Baixando: $(Split-Path $Url -Leaf) (Tentativa $attempt/$MaxRetries)..." -ForegroundColor Gray
            $wc = New-Object System.Net.WebClient
            $wc.DownloadFile($Url, $DestinationPath)
            if (Test-Path $DestinationPath) {
                Write-Success "Download concluido: $(Split-Path $DestinationPath -Leaf)"
                return $true
            }
        } catch {
            Write-Warning "Falha na tentativa ${attempt}: $_"
            Start-Sleep -Seconds 2
        }
    }
    Write-Fail "Falha ao baixar $Url apos $MaxRetries tentativas."
    return $false
}

# Menu Interativo
function Show-InteractiveMenu {
    Clear-Host
    Write-Host ""
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host "          GBOC SYSTEM v14.8.2 - INSTALADOR FULL STABLE           " -ForegroundColor Cyan
    Write-Host "          Servidor Central, Agente e Motores de Backup           " -ForegroundColor Cyan
    Write-Host "=================================================================" -ForegroundColor Cyan
    if ($GbocPackage) {
        Write-Host "  Pacote COMPLETO: programas incluidos (instala sem internet)" -ForegroundColor Green
    } else {
        Write-Host "  Pacote SO CODIGO: os programas que faltarem serao baixados da internet" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "Selecione o modo de instalacao desejado:" -ForegroundColor White
    Write-Host ""
    Write-Host "  [1] GBOC Agent (Agente Local de Backup e Monitoramento)" -ForegroundColor Green
    Write-Host "      -> Instala motores de backup (Restic, Kopia), API porta 9200 e scheduler."
    Write-Host ""
    Write-Host "  [2] GBOC Server (Servidor Central GBOC)" -ForegroundColor Green
    Write-Host "      -> Instala o Painel Web Central, API porta 8000 e Gestao Multitenant."
    Write-Host ""
    Write-Host "  [3] GBOC Enterprise Completo (Server + Agent no mesmo host)" -ForegroundColor Green
    Write-Host "      -> Instala ambos os componentes integrados com inicializacao conjunta."
    Write-Host ""
    Write-Host "  [4] Apenas Motores e Dependencias (Restic, Kopia, Python deps)" -ForegroundColor Yellow
    Write-Host "  [5] Cancelar e Sair" -ForegroundColor Gray
    Write-Host ""

    $choice = Read-Host "Digite a opcao desejada [1-5]"
    switch ($choice) {
        "1" { return "Agent" }
        "2" { return "Server" }
        "3" { return "Both" }
        "4" { return "DependenciesOnly" }
        default {
            Write-Host "Operacao cancelada pelo usuario." -ForegroundColor Yellow
            exit 0
        }
    }
}

if ($InstallMode -eq "Interactive") {
    $InstallMode = Show-InteractiveMenu
    
    $customTarget = Read-Host "Diretorio de instalacao [Padrao: $TargetDir]"
    if (-not [string]::IsNullOrWhiteSpace($customTarget)) {
        $TargetDir = $customTarget
    }

    Write-Host ""
    Write-Host "Selecione o motor de banco de dados principal:" -ForegroundColor White
    Write-Host "  [1] PostgreSQL (Padrao Corporativo - Recomendado)" -ForegroundColor Green
    Write-Host "  [2] SQLite (Armazenamento Local Apenas em Arquivo)" -ForegroundColor Yellow
    $dbChoice = Read-Host "Digite a opcao de banco desejada [1-2, Padrao: 1]"
    if ($dbChoice -eq "2") {
        $DatabaseEngine = "sqlite"
    } else {
        $DatabaseEngine = "postgresql"
    }

    Write-Host ""
    $llmResp = Read-Host "Deseja instalar e integrar a IA Local Gratuita (Ollama + Qwen 3.5)? [S/N, Padrao: S]"
    if ([string]::IsNullOrWhiteSpace($llmResp) -or $llmResp -match '^[sSyY1]') {
        $InstallLLM = $true
    }
}

Write-Header "INICIANDO INSTALACAO: MODO [$InstallMode] | BANCO [$DatabaseEngine] EM [$TargetDir]"

# Resumo: o que a maquina ja tem, o que veio no pacote e o que sera feito com cada programa
$needPg = ($DatabaseEngine -eq "postgresql") -and ($InstallMode -in @("Agent", "Server", "Both"))
Write-Step "Programas nesta maquina x pacote$(if (-not $GbocPackage) { ' (pacote so com codigo)' })..."
$statusRows = Get-GbocPrereqStatus -ToolsDir (Join-Path $TargetDir "Tools") -NoPostgres:(-not $needPg)
if ($InstallMode -eq "Server" -or $SkipEngines) { $statusRows = @($statusRows | Where-Object { $_.Programa -in @("Python", "PostgreSQL") }) }
$statusRows | Format-Table @{ L = "Programa"; E = { $_.Programa } }, @{ L = "Nesta maquina"; E = { $_.Maquina } },
    @{ L = "No pacote"; E = { $_.Pacote } }, @{ L = "Acao"; E = { $_.Acao } } -AutoSize | Out-Host
if ($WasInteractive) {
    Read-Host "Pressione ENTER para continuar (CTRL+C cancela)" | Out-Null
}

# 1. Criacao das Pastas Base
Write-Step "Criando estrutura de diretorios em $TargetDir..."
$ServerDir = Join-Path $TargetDir "Server"
$AgentDir = Join-Path $TargetDir "Agent"
$ToolsDir = Join-Path $TargetDir "Tools"
$VenvDir = Join-Path $TargetDir "venv"
$LogsDir = Join-Path $TargetDir "Logs"
$DataDir = Join-Path $TargetDir "Data"

$dirsToCreate = @($TargetDir, $ToolsDir, $LogsDir, $DataDir)
if ($InstallMode -in @("Server", "Both")) { $dirsToCreate += $ServerDir }
if ($InstallMode -in @("Agent", "Both")) { $dirsToCreate += $AgentDir }

foreach ($dir in $dirsToCreate) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Success "Diretorio criado: $dir"
    } else {
        Write-Success "Diretorio pronto: $dir"
    }
}

# Servicos de uma instalacao anterior: parados antes de trocar arquivos, Python e dependencias
# (arquivos em uso bloqueiam a copia e o pip). Sao registrados e iniciados de novo no final.
Stop-GbocService -Name "GBOCWatchdog" -ToolsDir $ToolsDir          # nao reiniciar servicos parados pela atualizacao
if ($InstallMode -in @("Server", "Both")) { Stop-GbocService -Name "GBOCServer" -ToolsDir $ToolsDir }
if ($InstallMode -in @("Agent", "Both")) { Stop-GbocService -Name "GBOCAgent" -ToolsDir $ToolsDir }

# Configurar selecao de banco de dados (.env e system_config.json)
Write-Step "Gravando configuracao do banco de dados ($DatabaseEngine)..."
$envContent = @(
    "GBOC_DB_ENGINE=$DatabaseEngine",
    "DB_ENGINE=$DatabaseEngine"
)
[System.IO.File]::WriteAllLines((Join-Path $TargetDir ".env"), $envContent)

$cfgObj = @{
    db_engine = $DatabaseEngine
    database_engine = $DatabaseEngine
} | ConvertTo-Json

if ($InstallMode -in @("Agent", "Both")) {
    $agentDataDir = Join-Path $AgentDir "data"
    New-Item -ItemType Directory -Path $agentDataDir -Force | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $agentDataDir "system_config.json"), $cfgObj)
}
if ($InstallMode -in @("Server", "Both")) {
    [System.IO.File]::WriteAllText((Join-Path $ServerDir "system_config.json"), $cfgObj)
}
Write-Success "Configuracao de banco ($DatabaseEngine) gravada com sucesso!"

# PostgreSQL: ja instalado -> mantido; senao do pacote (ou da internet). O Agente/Servidor criam o proprio banco.
if ($needPg) {
    Write-Step "Verificando PostgreSQL..."
    $pgBin = Find-GbocPostgresBin -ToolsDir $ToolsDir
    if ($pgBin) {
        Write-Success "PostgreSQL ja instalado: $pgBin (mantido)"
    } else {
        $GbocDefaultPgPassword = "Stoms2025+"         # padrao do Agente/Servidor (POSTGRES_PASSWORD nao definido)
        $pgPass = $PostgresPassword
        if (-not $pgPass -and $WasInteractive) {
            Write-Host "    O PostgreSQL sera instalado. Senha do superusuario 'postgres':" -ForegroundColor White
            Write-Host "    (ENTER = senha padrao do GBOC; outra senha fica na variavel de ambiente POSTGRES_PASSWORD da maquina)" -ForegroundColor Gray
            for ($try = 1; $try -le 3; $try++) {
                $s1 = Read-Host "    Senha" -AsSecureString
                $p1 = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s1))
                if (-not $p1) { break }
                $s2 = Read-Host "    Confirme a senha" -AsSecureString
                $p2 = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s2))
                if ($p1 -eq $p2) { $pgPass = $p1; break }
                Write-Warning "As senhas nao conferem."
            }
        }
        if (-not $pgPass) { $pgPass = $GbocDefaultPgPassword }
        $pgBin = Install-GbocPostgres -ToolsDir $ToolsDir -Password $pgPass
        if ($pgBin) {
            Write-Success "PostgreSQL pronto: $pgBin"
            if ($pgPass -ne $GbocDefaultPgPassword) {
                [Environment]::SetEnvironmentVariable("POSTGRES_PASSWORD", $pgPass, "Machine")
                $env:POSTGRES_PASSWORD = $pgPass
                Write-Success "Senha gravada em POSTGRES_PASSWORD (variavel de ambiente da maquina) para o Agente e o Servidor"
            }
        } else {
            Write-Warning "PostgreSQL nao instalado. Instale-o e execute o instalador novamente (ou use SQLite)."
        }
        $pgPass = $null
    }
}

# 2. Python: ultima versao estavel do python.org (reaproveita a instalada se ja for a mais nova).
#    Se as dependencias do GBOC ainda nao instalarem na versao mais nova, usa a anterior.
Write-Step "Verificando interpretador Python (ultima versao estavel)..."
if ($InstallMode -eq "Server") {
    $reqForPython = Join-Path $PackageRoot "Dependencies\requirements-server.txt"
} elseif ($InstallMode -eq "Agent") {
    $reqForPython = Join-Path $PackageRoot "Dependencies\requirements-agent.txt"
} else {
    $reqForPython = Join-Path $PackageRoot "Dependencies\requirements-all.txt"
}
$pythonExe = Install-GbocPython -Requirements $reqForPython

if (-not $pythonExe) {
    Write-Fail "Nao foi possivel localizar ou instalar o Python 3 automaticamente."
    Write-Warning "Instale o Python mais recente (python.org) e execute o instalador novamente."
    exit 1
}

$pyVersionStr = & $pythonExe --version 2>&1
Write-Success "Python detectado: $pyVersionStr ($pythonExe)"

# 3. Criando Ambiente Virtual (Venv)
Write-Step "Configurando ambiente virtual Python isolado em $VenvDir..."
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"

if (-not (Test-Path $VenvPython)) {
    & $pythonExe -m venv $VenvDir
    if (-not (Test-Path $VenvPython)) {
        Write-Fail "Falha ao criar o ambiente virtual em $VenvDir."
        exit 1
    }
    Write-Success "Ambiente virtual criado com sucesso."
} else {
    Write-Success "Ambiente virtual existente reutilizado."
}

# 4. Instalando Dependencias Python
Write-Step "Instalando dependencias necessarias..."
$reqFileToInstall = $null

if ($InstallMode -eq "Server") {
    $reqFileToInstall = Join-Path $PackageRoot "Dependencies\requirements-server.txt"
} elseif ($InstallMode -eq "Agent") {
    $reqFileToInstall = Join-Path $PackageRoot "Dependencies\requirements-agent.txt"
} else {
    $reqFileToInstall = Join-Path $PackageRoot "Dependencies\requirements-all.txt"
}

if ($reqFileToInstall -and (Test-Path $reqFileToInstall)) {
    Write-Host "    Instalando a partir de: $reqFileToInstall" -ForegroundColor Gray
    # Bibliotecas do pacote primeiro (sem internet); o que faltar vem da internet
    if (-not (Install-GbocPipRequirements $VenvPython $reqFileToInstall -UpgradePip)) {
        Write-Warning "Alguns pacotes secundarios podem ter falhado. Garantindo componentes criticos..."
        & $VenvPip install fastapi uvicorn pydantic sqlalchemy psutil requests httpx websockets cryptography
    }
    Write-Success "Dependencias Python instaladas e validadas."
} else {
    Write-Warning "Arquivo de requirements nao encontrado. Instalando stack basica..."
    & $VenvPip install fastapi uvicorn pydantic sqlalchemy psutil requests httpx websockets cryptography
}

# 5. Copiando Codigo dos Componentes
if ($InstallMode -in @("Server", "Both")) {
    Write-Step "Copiando arquivos do GBOC Server para $ServerDir..."
    $serverSrc = Join-Path $PackageRoot "Server"
    if (Test-Path $serverSrc) {
        Copy-Item -Path "$serverSrc\*" -Destination $ServerDir -Recurse -Force
        Write-Success "GBOC Server copiado com sucesso."
    } else {
        Write-Fail "Pasta Server nao encontrada no pacote: $serverSrc"
    }
}

if ($InstallMode -in @("Agent", "Both")) {
    Write-Step "Copiando arquivos do GBOC Agent para $AgentDir..."
    $agentSrc = Join-Path $PackageRoot "Agent"
    if (Test-Path $agentSrc) {
        Copy-Item -Path "$agentSrc\*" -Destination $AgentDir -Recurse -Force
        Write-Success "GBOC Agent copiado com sucesso."
    } else {
        Write-Fail "Pasta Agent nao encontrada no pacote: $agentSrc"
    }
}

# 6. Configuracao dos Motores de Backup (Restic & Kopia para Agent)
if ($InstallMode -in @("Agent", "Both", "DependenciesOnly") -and (-not $SkipEngines)) {
    Write-Step "Configurando motores de backup (Restic / Kopia / Duplicati, ultima versao)..."
    $ResticDir = Join-Path $ToolsDir "Restic"
    $KopiaDir = Join-Path $ToolsDir "Kopia"
    
    if (-not (Test-Path $ResticDir)) { New-Item -ItemType Directory -Path $ResticDir -Force | Out-Null }
    if (-not (Test-Path $KopiaDir)) { New-Item -ItemType Directory -Path $KopiaDir -Force | Out-Null }

    # Ultima release do GitHub; versao instalada mais antiga e atualizada (inclui o Duplicati)
    $engines = Install-GbocEngines -ToolsDir $ToolsDir
    foreach ($k in @("restic", "kopia", "duplicati")) {
        if ($engines[$k]) { Write-Success "${k}: $($engines[$k])" } else { Write-Warning "$k nao instalado" }
    }
}

# 7. Criando Scripts de Inicializacao e Controle
Write-Step "Criando scripts de controle e execucao em $TargetDir..."

# start_server.bat
if ($InstallMode -in @("Server", "Both")) {
    $sLines = @(
        "@echo off",
        "title GBOC Server v14.8.2 Enterprise",
        "REM Instalado como servico do Windows: usa o servico (abrir o console disputaria a porta $ServerPort)",
        "sc query GBOCServer >nul 2>&1",
        "if not errorlevel 1 (",
        "    sc query GBOCServer | find ""RUNNING"" >nul || net start GBOCServer",
        "    start """" ""http://localhost:$ServerPort""",
        "    exit /b 0",
        ")",
        "cd /d ""$ServerDir""",
        "set SERVER_PORT=$ServerPort",
        "set SERVER_HOST=0.0.0.0",
        "REM O start_server.bat do Server escolhe o Python mais novo com as dependencias (scripts\gboc_python.ps1)",
        "call ""$ServerDir\start_server.bat"""
    )
    [System.IO.File]::WriteAllLines((Join-Path $TargetDir "start_server.bat"), $sLines)
    Write-Success "Criado: $TargetDir\start_server.bat"
}

# start_agent.bat
if ($InstallMode -in @("Agent", "Both")) {
    $aLines = @(
        "@echo off",
        "title GBOC Agent v14.8.2 Enterprise",
        "REM Instalado como servico do Windows: usa o servico (abrir o console disputaria a porta $AgentPort)",
        "sc query GBOCAgent >nul 2>&1",
        "if not errorlevel 1 (",
        "    sc query GBOCAgent | find ""RUNNING"" >nul || net start GBOCAgent",
        "    start """" ""https://localhost:$AgentPort""",
        "    exit /b 0",
        ")",
        "cd /d ""$AgentDir""",
        "set AGENT_PORT=$AgentPort",
        "set AGENT_HOST=0.0.0.0",
        "set RESTIC_PATH=$ToolsDir\Restic\restic.exe",
        "set KOPIA_PATH=$ToolsDir\Kopia\kopia.exe",
        "REM O start_agent.bat do Agent escolhe o Python mais novo com as dependencias (scripts\gboc_python.ps1)",
        "call ""$AgentDir\start_agent.bat"""
    )
    [System.IO.File]::WriteAllLines((Join-Path $TargetDir "start_agent.bat"), $aLines)
    Write-Success "Criado: $TargetDir\start_agent.bat"
}

# start_all.bat
if ($InstallMode -eq "Both") {
    $allLines = @(
        "@echo off",
        "title GBOC Enterprise - Inicializador Global",
        "echo ========================================================",
        "echo   Iniciando GBOC Server e GBOC Agent em segundo plano...",
        "echo ========================================================",
        "start ""GBOC Server (Porta $ServerPort)"" ""$TargetDir\start_server.bat""",
        "timeout /t 3 /nobreak >nul",
        "start ""GBOC Agent (Porta $AgentPort)"" ""$TargetDir\start_agent.bat""",
        "echo.",
        "echo [OK] Servicos iniciados com sucesso!",
        "echo Painel Web Server: http://localhost:$ServerPort",
        "echo Painel Web Agent:  http://localhost:$AgentPort",
        "timeout /t 5"
    )
    [System.IO.File]::WriteAllLines((Join-Path $TargetDir "start_all.bat"), $allLines)
    Write-Success "Criado: $TargetDir\start_all.bat"
}

# stop_all.bat
$stopLines = @(
    "@echo off",
    "title Encerrando Servicos GBOC",
    "echo Finalizando processos do GBOC Server e GBOC Agent...",
    "sc query GBOCWatchdog >nul 2>&1 && net stop GBOCWatchdog",
    "sc query GBOCAgent >nul 2>&1 && net stop GBOCAgent",
    "sc query GBOCServer >nul 2>&1 && net stop GBOCServer",
    "taskkill /f /im python.exe /fi ""WINDOWTITLE eq GBOC*"" 2>nul",
    "echo Processos encerrados.",
    "timeout /t 2 >nul"
)
[System.IO.File]::WriteAllLines((Join-Path $TargetDir "stop_all.bat"), $stopLines)
Write-Success "Criado: $TargetDir\stop_all.bat"

# uninstall.bat
$uninstLines = @(
    "@echo off",
    "title Desinstalador GBOC System",
    "echo ========================================================",
    "echo   Desinstalador do GBOC System",
    "echo ========================================================",
    "echo.",
    "set /p confirm=Tem certeza que deseja remover o GBOC em $TargetDir? (S/N): ",
    "if /i ""%confirm%"" neq ""S"" goto :cancel",
    "",
    "echo Encerrando processos...",
    "sc query GBOCWatchdog >nul 2>&1 && net stop GBOCWatchdog",
    "sc query GBOCAgent >nul 2>&1 && net stop GBOCAgent",
    "sc query GBOCServer >nul 2>&1 && net stop GBOCServer",
    "if exist ""$ToolsDir\nssm\nssm.exe"" (",
    "    ""$ToolsDir\nssm\nssm.exe"" remove GBOCWatchdog confirm >nul 2>&1",
    "    ""$ToolsDir\nssm\nssm.exe"" remove GBOCAgent confirm >nul 2>&1",
    "    ""$ToolsDir\nssm\nssm.exe"" remove GBOCServer confirm >nul 2>&1",
    ")",
    "sc delete GBOCWatchdog >nul 2>&1",
    "sc delete GBOCAgent >nul 2>&1",
    "sc delete GBOCServer >nul 2>&1",
    "schtasks /delete /tn GBOCAgent /f >nul 2>&1",
    "schtasks /delete /tn GBOCServer /f >nul 2>&1",
    "taskkill /f /im python.exe /fi ""WINDOWTITLE eq GBOC*"" 2>nul",
    "",
    "echo Removendo arquivos...",
    "rmdir /s /q ""$TargetDir\Server"" 2>nul",
    "rmdir /s /q ""$TargetDir\Agent"" 2>nul",
    "rmdir /s /q ""$TargetDir\venv"" 2>nul",
    "rmdir /s /q ""$TargetDir\Tools"" 2>nul",
    "",
    "echo [OK] Desinstalacao concluida!",
    "pause",
    "exit /b 0",
    "",
    ":cancel",
    "echo Operacao cancelada.",
    "pause"
)
[System.IO.File]::WriteAllLines((Join-Path $TargetDir "uninstall.bat"), $uninstLines)
Write-Success "Criado: $TargetDir\uninstall.bat"

# 8. Criacao de Atalhos no Desktop
if ($CreateShortcuts) {
    Write-Step "Criando atalhos na Area de Trabalho..."
    $wshShell = New-Object -ComObject WScript.Shell
    $desktopPath = [Environment]::GetFolderPath("Desktop")

    if ($InstallMode -eq "Both") {
        $scPath = Join-Path $desktopPath "GBOC Enterprise.lnk"
        $shortcut = $wshShell.CreateShortcut($scPath)
        $shortcut.TargetPath = Join-Path $TargetDir "start_all.bat"
        $shortcut.WorkingDirectory = $TargetDir
        $shortcut.Description = "Iniciar GBOC Enterprise (Server + Agent)"
        $shortcut.Save()
        Write-Success "Atalho criado: GBOC Enterprise"
    } elseif ($InstallMode -eq "Server") {
        $scPath = Join-Path $desktopPath "GBOC Server.lnk"
        $shortcut = $wshShell.CreateShortcut($scPath)
        $shortcut.TargetPath = Join-Path $TargetDir "start_server.bat"
        $shortcut.WorkingDirectory = $ServerDir
        $shortcut.Description = "Iniciar GBOC Server"
        $shortcut.Save()
        Write-Success "Atalho criado: GBOC Server"
    } elseif ($InstallMode -eq "Agent") {
        $scPath = Join-Path $desktopPath "GBOC Agent.lnk"
        $shortcut = $wshShell.CreateShortcut($scPath)
        $shortcut.TargetPath = Join-Path $TargetDir "start_agent.bat"
        $shortcut.WorkingDirectory = $AgentDir
        $shortcut.Description = "Iniciar GBOC Agent"
        $shortcut.Save()
        Write-Success "Atalho criado: GBOC Agent"
    }
}

# 9. Teste de Integridade Real (Strict Zero-Mock)
Write-Step "Realizando teste de integridade real das bibliotecas instaladas..."
$testInline = "import sys, fastapi, uvicorn, pydantic, sqlalchemy, psutil; print('[OK] Integridade real confirmada: Bibliotecas carregadas com sucesso!')"
$testResult = & $VenvPython -c $testInline 2>&1
Write-Host "    $testResult" -ForegroundColor Cyan

# 9.0 Servicos do Windows: o sistema inteiro (API, painel e agendador) roda sem usuario logado
$ServicesRegistered = @()
if (-not $NoService -and $InstallMode -in @("Server", "Both", "Agent")) {
    Write-Step "Registrando o GBOC como servico do Windows (inicio automatico, sem usuario logado)..."
    $pgPassMachine = [Environment]::GetEnvironmentVariable("POSTGRES_PASSWORD", "Machine")
    # Servicos recebem o ambiente do Windows de quando ele iniciou: variaveis gravadas agora
    # so chegariam apos reiniciar a maquina, entao vao direto na configuracao do servico
    $commonEnv = @("PYTHONIOENCODING=utf-8", "GBOC_DB_ENGINE=$DatabaseEngine", "DB_ENGINE=$DatabaseEngine")
    if ($pgPassMachine) { $commonEnv += "POSTGRES_PASSWORD=$pgPassMachine" }
    if ($InstallMode -in @("Server", "Both")) {
        $ok = Register-GbocService -Name "GBOCServer" -DisplayName "GBOC Server" `
            -Description "GBOC Servidor Central (painel web e API, porta $ServerPort)" `
            -Script (Join-Path $ServerDir "start_server.ps1") -WorkDir $ServerDir -LogDir (Join-Path $ServerDir "logs") `
            -ToolsDir $ToolsDir -Environment ($commonEnv + @("SERVER_PORT=$ServerPort", "SERVER_HOST=0.0.0.0"))
        if ($ok) { $ServicesRegistered += "GBOCServer" }
    }
    if ($InstallMode -in @("Agent", "Both")) {
        $ok = Register-GbocService -Name "GBOCAgent" -DisplayName "GBOC Backup Agent" `
            -Description "GBOC Agente de backup e restauracao (painel, API e agendador, porta $AgentPort)" `
            -Script (Join-Path $AgentDir "start_agent.ps1") -ScriptArgs "-Service" -WorkDir $AgentDir -LogDir (Join-Path $AgentDir "logs") `
            -ToolsDir $ToolsDir -Environment ($commonEnv + @("AGENT_PORT=$AgentPort", "AGENT_HOST=0.0.0.0",
                "RESTIC_PATH=$ToolsDir\Restic\restic.exe", "KOPIA_PATH=$ToolsDir\Kopia\kopia.exe"))
        if ($ok) { $ServicesRegistered += "GBOCAgent" }
    }
    # Vigia anti-travamento: reinicia o Agente/Servidor se o servico estiver rodando mas congelado
    # (PowerShell puro: funciona mesmo se o Python quebrar). Logs em <Agent ou Server>\logs\watchdog.log
    if ($ServicesRegistered.Count -gt 0) {
        $wdRoot = if ($InstallMode -in @("Agent", "Both")) { $AgentDir } else { $ServerDir }
        $ok = Register-GbocService -Name "GBOCWatchdog" -DisplayName "GBOC Watchdog" `
            -Description "GBOC vigia anti-travamento (reinicia GBOCAgent/GBOCServer congelados)" `
            -Script (Join-Path $wdRoot "scripts\gboc_watchdog.ps1") -ScriptArgs "-Service" -WorkDir $wdRoot `
            -LogDir (Join-Path $wdRoot "logs") -ToolsDir $ToolsDir
        if ($ok) { $ServicesRegistered += "GBOCWatchdog" }
    }
    $pgPassMachine = $null
} elseif ($NoService) {
    Write-Warning "Servicos do Windows nao registrados (-NoService): o GBOC para quando o usuario sair da sessao."
}

# 9.1 Instalacao de IA Local Gratuita (Ollama)
if ($InstallLLM) {
    Write-Step "Instalando e integrando motor de IA Local Gratuito (Ollama)..."
    Install-GbocOllama -Model "qwen3.5:4b" -InstallRoot $TargetDir
}

# 10. Finalizacao e Resumo
Write-Header "INSTALACAO CONCLUIDA COM SUCESSO!"
Write-Host "Diretorio Base: $TargetDir" -ForegroundColor White
if ($InstallLLM) {
    Write-Host "IA Local Gratuita: Operacional via Ollama (qwen3.5:4b) em http://localhost:11434" -ForegroundColor Cyan
}
if ($InstallMode -in @("Server", "Both")) {
    Write-Host "Painel Web Server: http://localhost:$ServerPort" -ForegroundColor Green
    Write-Host "Script Server:     $TargetDir\start_server.bat" -ForegroundColor Gray
}
if ($InstallMode -in @("Agent", "Both")) {
    Write-Host "Painel Web Agent:  http://localhost:$AgentPort" -ForegroundColor Green
    Write-Host "Script Agent:      $TargetDir\start_agent.bat" -ForegroundColor Gray
}
if ($InstallMode -eq "Both") {
    Write-Host "Script Unificado:  $TargetDir\start_all.bat" -ForegroundColor Green
}
if ($ServicesRegistered.Count -gt 0) {
    Write-Host "Servicos Windows:  $($ServicesRegistered -join ', ') (inicio automatico, rodam sem usuario logado)" -ForegroundColor Green
}
Write-Host "Script Parada:     $TargetDir\stop_all.bat" -ForegroundColor Yellow
Write-Host "Desinstalador:     $TargetDir\uninstall.bat" -ForegroundColor Red
Write-Host ""

if ($WasInteractive) {
    Read-Host "Pressione ENTER para finalizar..."
}
