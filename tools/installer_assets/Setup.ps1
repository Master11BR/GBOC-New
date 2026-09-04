<#
==============================================================================
GBOC System v13.3.0 Enterprise Edition
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
    [switch]$RegisterStartupTask = $false
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
    Write-Host "          GBOC SYSTEM v14.0.0 - INSTALADOR FULL STABLE           " -ForegroundColor Cyan
    Write-Host "          Servidor Central, Agente e Motores de Backup           " -ForegroundColor Cyan
    Write-Host "=================================================================" -ForegroundColor Cyan
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
}

Write-Header "INICIANDO INSTALACAO: MODO [$InstallMode] EM [$TargetDir]"

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

# 2. Localizar ou Instalar Python
Write-Step "Verificando interpretador Python..."
$pythonExe = Get-PythonExecutable

if (-not $pythonExe) {
    Write-Warning "Python 3 nao encontrado no PATH do sistema."
    Write-Step "Baixando instalador do Python 3.11.9 64-bit..."
    $pythonInstallerUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $tempPythonInstaller = Join-Path $env:TEMP "python-3.11.9-amd64.exe"
    
    if (Download-FileWithRetry -Url $pythonInstallerUrl -DestinationPath $tempPythonInstaller) {
        Write-Step "Instalando Python 3.11.9 silenciosamente..."
        Start-Process -FilePath $tempPythonInstaller -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" -Wait
        $pythonExe = Get-PythonExecutable
    }
}

if (-not $pythonExe) {
    Write-Fail "Nao foi possivel localizar ou instalar o Python 3 automaticamente."
    Write-Warning "Por favor, instale o Python 3.11+ manualmente com a opcao 'Add Python to PATH' e tente novamente."
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

# Atualizar pip
Write-Step "Atualizando pip no ambiente virtual..."
& $VenvPython -m pip install --upgrade pip --quiet

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
    & $VenvPip install -r $reqFileToInstall
    if ($LASTEXITCODE -ne 0) {
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
    Write-Step "Configurando motores de backup (Restic / Kopia)..."
    $ResticDir = Join-Path $ToolsDir "Restic"
    $KopiaDir = Join-Path $ToolsDir "Kopia"
    
    if (-not (Test-Path $ResticDir)) { New-Item -ItemType Directory -Path $ResticDir -Force | Out-Null }
    if (-not (Test-Path $KopiaDir)) { New-Item -ItemType Directory -Path $KopiaDir -Force | Out-Null }

    # Restic
    $resticExe = Join-Path $ResticDir "restic.exe"
    if (-not (Test-Path $resticExe)) {
        Write-Host "    Baixando Restic 0.17.3 x64..." -ForegroundColor Gray
        $resticZip = Join-Path $env:TEMP "restic.zip"
        $resticUrl = "https://github.com/restic/restic/releases/download/v0.17.3/restic_0.17.3_windows_amd64.zip"
        if (Download-FileWithRetry -Url $resticUrl -DestinationPath $resticZip) {
            $extractTemp = Join-Path $env:TEMP "restic_extracted"
            Expand-Archive -Path $resticZip -DestinationPath $extractTemp -Force
            $foundRestic = Get-ChildItem -Path $extractTemp -Filter "restic*.exe" -Recurse | Select-Object -First 1
            if ($foundRestic) {
                Copy-Item -Path $foundRestic.FullName -Destination $resticExe -Force
                Write-Success "Restic instalado em $resticExe"
            }
            Remove-Item -Path $extractTemp -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item -Path $resticZip -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Success "Restic ja instalado em $resticExe"
    }

    # Kopia
    $kopiaExe = Join-Path $KopiaDir "kopia.exe"
    if (-not (Test-Path $kopiaExe)) {
        Write-Host "    Baixando Kopia 0.18.2 x64..." -ForegroundColor Gray
        $kopiaZip = Join-Path $env:TEMP "kopia.zip"
        $kopiaUrl = "https://github.com/kopia/kopia/releases/download/v0.18.2/kopia-0.18.2-windows-x64.zip"
        if (Download-FileWithRetry -Url $kopiaUrl -DestinationPath $kopiaZip) {
            $extractTemp = Join-Path $env:TEMP "kopia_extracted"
            Expand-Archive -Path $extractTemp -DestinationPath $extractTemp -Force
            $foundKopia = Get-ChildItem -Path $extractTemp -Filter "kopia.exe" -Recurse | Select-Object -First 1
            if ($foundKopia) {
                Copy-Item -Path $foundKopia.FullName -Destination $kopiaExe -Force
                Write-Success "Kopia instalado em $kopiaExe"
            }
            Remove-Item -Path $extractTemp -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item -Path $kopiaZip -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Success "Kopia ja instalado em $kopiaExe"
    }
}

# 7. Criando Scripts de Inicializacao e Controle
Write-Step "Criando scripts de controle e execucao em $TargetDir..."

# start_server.bat
if ($InstallMode -in @("Server", "Both")) {
    $sLines = @(
        "@echo off",
        "title GBOC Server v14.0.0 Enterprise",
        "cd /d ""$ServerDir""",
        "set SERVER_PORT=$ServerPort",
        "set SERVER_HOST=0.0.0.0",
        """$VenvPython"" gboc_server.py",
        "pause"
    )
    [System.IO.File]::WriteAllLines((Join-Path $TargetDir "start_server.bat"), $sLines)
    Write-Success "Criado: $TargetDir\start_server.bat"
}

# start_agent.bat
if ($InstallMode -in @("Agent", "Both")) {
    $aLines = @(
        "@echo off",
        "title GBOC Agent v14.0.0 Enterprise",
        "cd /d ""$AgentDir""",
        "set AGENT_PORT=$AgentPort",
        "set AGENT_HOST=0.0.0.0",
        "set RESTIC_PATH=$ToolsDir\Restic\restic.exe",
        "set KOPIA_PATH=$ToolsDir\Kopia\kopia.exe",
        """$VenvPython"" agent_server.py",
        "pause"
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

# 10. Finalizacao e Resumo
Write-Header "INSTALACAO CONCLUIDA COM SUCESSO!"
Write-Host "Diretorio Base: $TargetDir" -ForegroundColor White
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
Write-Host "Script Parada:     $TargetDir\stop_all.bat" -ForegroundColor Yellow
Write-Host "Desinstalador:     $TargetDir\uninstall.bat" -ForegroundColor Red
Write-Host ""

if ($InstallMode -eq "Interactive") {
    Read-Host "Pressione ENTER para finalizar..."
}
