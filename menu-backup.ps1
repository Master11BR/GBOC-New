#Requires -RunAsAdministrator

# ==========================================
# FUNÇÕES DE APOIO
# ==========================================
function Invoke-ExternalCommand {
    param([string]$Command)
    Write-Host "Executando: $Command" -ForegroundColor DarkGray
    Invoke-Expression $Command > $null 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Ensure-Winget {
    try {
        $null = winget --version
    } catch {
        Write-Host "Winget não encontrado. Instalando App Installer..." -ForegroundColor Yellow
        Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe -ErrorAction SilentlyContinue
    }
}

function Test-AppInstalled {
    param($App)

    # 1. Checagem via Path do Sistema
    if ($App.CheckCommand -and (Get-Command $App.CheckCommand -ErrorAction SilentlyContinue)) { return $true }

    # 2. Checagem em diretórios físicos comuns
    $searchPaths = @(
        "$env:ProgramFiles\$($App.SearchName)",
        "$env:ProgramFiles(x86)\$($App.SearchName)",
        "$env:LocalAppData\Programs\$($App.SearchName)",
        "C:\tools\$($App.SearchName)" # Comum para Chocolatey/MSYS2
    )
    
    foreach ($path in $searchPaths) {
        if (Test-Path $path) { return $true }
    }

    # 3. Checagem via Registro do Windows (Painel de Controle)
    $regPaths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    
    foreach ($reg in $regPaths) {
        $key = Get-ItemProperty $reg -ErrorAction SilentlyContinue
        if ($key.DisplayName -and $key.DisplayName -match $App.SearchName) {
            return $true
        }
    }

    return $false
}

function Install-App {
    param($App)
    Write-Host "`n>>> Iniciando instalação de: $($App.Name)" -ForegroundColor Cyan
    
    # 1. Tentar Winget
    if ($App.WingetId -and (Invoke-ExternalCommand "winget install --id $($App.WingetId) --exact --silent --accept-package-agreements --accept-source-agreements")) {
        Write-Host "Sucesso: $($App.Name) instalado via Winget." -ForegroundColor Green
        return
    }

    # 2. Garantir Chocolatey (somente se necessário) e tentar
    if ($App.ChocoId) {
        if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
            Write-Host "Winget não resolveu. Instalando Chocolatey para suporte..." -ForegroundColor Yellow
            Set-ExecutionPolicy Bypass -Scope Process -Force
            [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
            Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
            $env:PATH += ";$env:ALLUSERSPROFILE\chocolatey\bin"
        }
        
        if (Invoke-ExternalCommand "choco install $($App.ChocoId) -y") {
            Write-Host "Sucesso: $($App.Name) instalado via Chocolatey." -ForegroundColor Green
            return
        }
    }
    
    # 3. Fallback manual
    if ($App.Fallback) {
        Write-Host "Winget/Choco falharam. Executando fallback manual..." -ForegroundColor Yellow
        try { & $App.Fallback } catch { Write-Error "Falha no fallback: $_" }
    }
}

# ==========================================
# DEFINIÇÃO DOS APLICATIVOS
# ==========================================
$Apps = @(
    [PSCustomObject]@{
        Id = 1; Name = "Restic"; SearchName = "restic"; 
        WingetId = "restic.restic"; ChocoId = "restic"; CheckCommand = "restic.exe"
        Fallback = {
            $url = "https://github.com/restic/restic/releases/latest/download/restic_0.17.2_windows_amd64.zip"
            $zip = "$env:TEMP\restic.zip"; $dest = "$env:ProgramFiles\restic"
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
            Expand-Archive -Path $zip -DestinationPath $dest -Force
            [Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";$dest", [EnvironmentVariableTarget]::Machine)
        }
    },
    [PSCustomObject]@{
        Id = 2; Name = "Kopia UI"; SearchName = "KopiaUI"; 
        WingetId = "Kopia.KopiaUI"; ChocoId = "kopia-ui"; CheckCommand = "KopiaUI.exe"
        Fallback = {
            $url = "https://github.com/kopia/kopia/releases/latest/download/KopiaUI-Setup-0.17.0.exe"
            $exe = "$env:TEMP\KopiaUI.exe"
            Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
            Start-Process -FilePath $exe -ArgumentList "/S" -Wait -NoNewWindow
        }
    },
    [PSCustomObject]@{
        Id = 3; Name = "Duplicati"; SearchName = "Duplicati"; 
        WingetId = "Duplicati.Duplicati"; ChocoId = "duplicati"; CheckCommand = "duplicati-cli.exe"
        Fallback = {
            $url = "https://updates.duplicati.com/stable/Duplicati.windows.x64.latest.exe"
            $exe = "$env:TEMP\Duplicati.exe"
            Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
            Start-Process -FilePath $exe -ArgumentList "/VERYSILENT /NORESTART" -Wait -NoNewWindow
        }
    },
    [PSCustomObject]@{
        Id = 4; Name = "Rclone"; SearchName = "rclone"; 
        WingetId = "Rclone.Rclone"; ChocoId = "rclone"; CheckCommand = "rclone.exe"
        Fallback = {
            $zipUrl = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"
            $zip = "$env:TEMP\rclone.zip"; $dest = "$env:ProgramFiles\rclone"
            Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing
            Expand-Archive -Path $zip -DestinationPath $dest -Force
            $rcloneFolder = Get-ChildItem -Path $dest -Filter "rclone-v*-windows-amd64" -Directory | Select-Object -First 1
            if ($rcloneFolder) {
                [Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";$($rcloneFolder.FullName)", [EnvironmentVariableTarget]::Machine)
            }
        }
    },
    [PSCustomObject]@{
        Id = 5; Name = "Borg (via MSYS2)"; SearchName = "msys64"; # MSYS2 é a base instalada no Windows
        WingetId = ""; ChocoId = "msys2"; CheckCommand = "msys2.exe"
        Fallback = {
            Write-Host "Instale o MSYS2 e use: pacman -S mingw-w64-x86_64-borg" -ForegroundColor Yellow
        }
    }
)

# ==========================================
# LOOP DO MENU
# ==========================================
Ensure-Winget

while ($true) {
    Clear-Host
    Write-Host "=========================================" -ForegroundColor Cyan
    Write-Host "   GERENCIADOR DE BACKUP - INSTALAÇÃO" -ForegroundColor White
    Write-Host "=========================================" -ForegroundColor Cyan

    foreach ($app in $Apps) {
        $isInstalled = Test-AppInstalled -App $app
        if ($isInstalled) {
            $status = "[ Instalado ]"
            $color = "Green"
        } else {
            $status = "[ Pendente  ]"
            $color = "Yellow"
        }
        
        Write-Host " [$($app.Id)] $($app.Name.PadRight(18)) - Status: " -NoNewline
        Write-Host $status -ForegroundColor $color
    }

    Write-Host "-----------------------------------------" -ForegroundColor Cyan
    Write-Host " [T] Instalar todos os Pendentes"
    Write-Host " [S] Sair do Instalador"
    Write-Host "=========================================" -ForegroundColor Cyan

    $choice = Read-Host "`nEscolha uma opção (Ex: 1,3 para múltiplos ou T/S)"

    if ($choice -match '^[sS]$') {
        Write-Host "Saindo... Lembre-se de reiniciar o terminal se alguma variável PATH foi alterada." -ForegroundColor Green
        break
    }

    $appsToInstall = @()

    if ($choice -match '^[tT]$') {
        $appsToInstall = $Apps | Where-Object { -not (Test-AppInstalled -App $_) }
        if ($appsToInstall.Count -eq 0) {
            Write-Host "`nTodos os aplicativos já estão instalados!" -ForegroundColor Green
            Start-Sleep -Seconds 2
            continue
        }
    } else {
        $selectedIds = $choice -split ',' | ForEach-Object { $_.Trim() }
        foreach ($id in $selectedIds) {
            $foundApp = $Apps | Where-Object { $_.Id -eq $id }
            if ($foundApp) {
                if (Test-AppInstalled -App $foundApp) {
                    Write-Host "`n$($foundApp.Name) já está instalado. Pulando..." -ForegroundColor DarkGray
                } else {
                    $appsToInstall += $foundApp
                }
            }
        }
    }

    if ($appsToInstall.Count -gt 0) {
        foreach ($app in $appsToInstall) {
            Install-App -App $app
        }
        Write-Host "`nProcesso concluído! Pressione ENTER para voltar ao menu." -ForegroundColor Green
        $null = Read-Host
    }
}