<#
==============================================================================
GBOC System v14.8.1 Enterprise Edition - Gerador do pacote de instalacao
==============================================================================
Modos:
  Completo : codigo do Agente/Servidor + programas em Prereqs\ (Python com as bibliotecas do GBOC
             em wheels, PostgreSQL, restic, Kopia, Duplicati, NSSM), com versoes e SHA-256 em
             Prereqs\prereqs.json. O Setup.bat instala a partir do pacote, sem internet; o que a
             maquina ja tiver e mantido e o que faltar no pacote e baixado.
  Codigo   : so o codigo (como antes); o instalador baixa os programas da internet.
Uso:
  build_installer_package.bat                         (pergunta o modo e se gera o .zip)
  build_installer_package.bat -Mode Completo -Zip     (sem perguntas)
  build_installer_package.bat -Mode Codigo -OutputDir D:\Pacotes\GBOC
#>
[CmdletBinding()]
param (
    [Parameter(Mandatory = $false)]
    [string]$OutputDir = "",

    [Parameter(Mandatory = $false)]
    [switch]$Clean = $true,

    [Parameter(Mandatory = $false)]
    [ValidateSet("", "Completo", "Codigo")]
    [string]$Mode = "",

    [Parameter(Mandatory = $false)]
    [switch]$Zip,

    [Parameter(Mandatory = $false)]
    [switch]$NoZip
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path (Split-Path -Parent $ScriptRoot) "GBOC-Distribution"
}

# Funcoes de descoberta/download das ultimas versoes (as mesmas do instalador)
$prereqsScript = Join-Path $ScriptRoot "GBOC-Agent\scripts\gboc_prereqs.ps1"
if (-not (Test-Path $prereqsScript)) {
    Write-Host "[ERRO] $prereqsScript nao encontrado." -ForegroundColor Red
    exit 1
}
. $prereqsScript
Set-GbocPackageDir "" | Out-Null      # o gerador consulta sempre a internet (nunca um pacote antigo)

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  GERADOR DE PACOTE DE DISTRIBUICAO E INSTALADOR GBOC ENTERPRISE  " -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "Raiz dos Fontes: $ScriptRoot" -ForegroundColor Gray
Write-Host "Pasta de Saida:  $OutputDir" -ForegroundColor Yellow
Write-Host ""

$interactive = [Environment]::UserInteractive -and -not $Mode
if (-not $Mode) {
    Write-Host "Tipo de pacote:" -ForegroundColor White
    Write-Host "  [1] Completo  - codigo + programas (Python e bibliotecas, PostgreSQL, restic, Kopia," -ForegroundColor Green
    Write-Host "                  Duplicati, NSSM). Instala sem internet. Cerca de 600 MB." -ForegroundColor Green
    Write-Host "  [2] So codigo - o instalador baixa os programas da internet. Cerca de 30 MB." -ForegroundColor Yellow
    $m = Read-Host "Opcao [1-2, padrao 1]"
    $Mode = if ($m -eq "2") { "Codigo" } else { "Completo" }
}
$makeZip = $false
if ($Zip) { $makeZip = $true }
elseif ($NoZip) { $makeZip = $false }
elseif ($interactive) {
    $z = Read-Host "Gerar tambem um arquivo .zip para copiar para outra maquina? [S/n]"
    $makeZip = ($z -notmatch '^[nN]')
}
Write-Host ""
Write-Host "Modo: $Mode$(if ($makeZip) { ' + arquivo .zip' })" -ForegroundColor Cyan
Write-Host ""

# Python desta maquina para executar o empacotador (e o pip download das bibliotecas)
$pythonCmd = $null
$pyInst = Get-GbocInstalledPythons | Select-Object -First 1
if ($pyInst) { $pythonCmd = $pyInst.Path }
if (-not $pythonCmd) {
    foreach ($cand in @("python.exe", "py.exe", "python3.exe")) {
        $found = Get-Command $cand -ErrorAction SilentlyContinue
        if ($found) { $pythonCmd = $found.Source; break }
    }
}
if (-not $pythonCmd) {
    Write-Host "[ERRO] Python 3 nao encontrado para executar o empacotador." -ForegroundColor Red
    exit 1
}

Write-Host "==> Empacotando o codigo (Agente e Servidor)..." -ForegroundColor Cyan

$pyArgs = @(
    "$ScriptRoot\tools\make_distribution.py",
    "--source",
    "$ScriptRoot",
    "--output",
    "$OutputDir"
)
if ($Clean) {
    $pyArgs += "--clean"
}

& $pythonCmd $pyArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERRO] Falha durante a geracao do pacote de distribuicao." -ForegroundColor Red
    exit 1
}

# Copiar os executaveis do instalador para a raiz do pacote gerado
Write-Host "==> Copiando executaveis do instalador (Setup.bat / Setup.ps1)..." -ForegroundColor Cyan
$installerAssets = "$ScriptRoot\tools\installer_assets"
if (Test-Path $installerAssets) {
    Copy-Item -Path "$installerAssets\Setup.bat" -Destination "$OutputDir\Setup.bat" -Force
    Copy-Item -Path "$installerAssets\Setup.ps1" -Destination "$OutputDir\Setup.ps1" -Force
    # Pre-requisitos (usado pelo Setup.ps1): pacote primeiro, internet se faltar
    Copy-Item -Path "$ScriptRoot\GBOC-Agent\scripts\gboc_prereqs.ps1" -Destination "$OutputDir\gboc_prereqs.ps1" -Force
    Write-Host "    [OK] Setup.bat e Setup.ps1 copiados para $OutputDir" -ForegroundColor Green
}

# ============================================================================
# Modo Completo: programas em Prereqs\
# ============================================================================

function Add-GbocBundleItem([System.Collections.IDictionary]$Entry, [string]$Root, [string]$RelFile) {
    $full = Join-Path $Root $RelFile
    $Entry["file"] = $RelFile.Replace('\', '/')
    $Entry["sha256"] = (Get-FileHash -Path $full -Algorithm SHA256).Hash
    $Entry["size"] = (Get-Item $full).Length
    return $Entry
}

function New-GbocPrereqsBundle([string]$Dest, [string]$BuildPython, [string]$Requirements) {
    $ErrorActionPreference = "Continue"      # avisos do pip no stderr nao podem abortar o gerador
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    $man = [ordered]@{
        gboc_prereqs = 1
        created_at   = (Get-Date).ToString("s")
        mode         = "completo"
        python       = @()
        wheels       = @()
        postgres     = $null
        engines      = [ordered]@{}
        nssm         = $null
    }
    $report = @()

    # --- Python + bibliotecas do GBOC (wheels para Windows x64) ---
    # Versao mais nova do Python cujas bibliotecas ja existem prontas para Windows; senao a anterior.
    Write-Host "==> Python e bibliotecas do GBOC..." -ForegroundColor Cyan
    $okPy = $false
    foreach ($rel in (Get-GbocPythonReleases -Online)) {
        $mm = "{0}.{1}" -f $rel.Version.Major, $rel.Version.Minor
        $tag = "cp{0}{1}" -f $rel.Version.Major, $rel.Version.Minor
        $wdirRel = "wheels\$tag"
        $wdir = Join-Path $Dest $wdirRel
        Remove-Item $wdir -Recurse -Force -ErrorAction SilentlyContinue
        Write-GbocInfo "Baixando bibliotecas para Python $mm (Windows x64)..."
        & $BuildPython -m pip download --disable-pip-version-check -q --only-binary=:all: --platform win_amd64 `
            --python-version $mm --implementation cp -d $wdir -r $Requirements pip setuptools wheel 2>&1 | ForEach-Object { Write-Host ("    " + "$_") -ForegroundColor DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-GbocWarn "Bibliotecas do GBOC ainda nao disponiveis para Python $mm; tentando a versao anterior"
            Remove-Item $wdir -Recurse -Force -ErrorAction SilentlyContinue
            continue
        }
        $pyRel = "python\python-$($rel.Version)-amd64.exe"
        New-Item -ItemType Directory -Path (Join-Path $Dest "python") -Force | Out-Null
        if (-not (Save-GbocDownload $rel.Url (Join-Path $Dest $pyRel))) {
            Write-GbocWarn "Instalador do Python $($rel.Version) nao baixou; tentando a versao anterior"
            Remove-Item $wdir -Recurse -Force -ErrorAction SilentlyContinue
            continue
        }
        $man.python += (Add-GbocBundleItem ([ordered]@{ version = "$($rel.Version)" }) $Dest $pyRel)
        $nWheels = @(Get-ChildItem $wdir -File).Count
        $man.wheels += [ordered]@{ python = $mm; dir = $wdirRel.Replace('\', '/'); count = $nWheels }
        $report += [pscustomobject]@{ Programa = "Python"; Versao = "$($rel.Version)"; Status = "OK" }
        $report += [pscustomobject]@{ Programa = "Bibliotecas Python"; Versao = "$nWheels pacotes (cp$($rel.Version.Major)$($rel.Version.Minor))"; Status = "OK" }
        $okPy = $true
        break
    }
    if (-not $okPy) { $report += [pscustomobject]@{ Programa = "Python + bibliotecas"; Versao = "-"; Status = "FALHOU (instalador baixara)" } }

    # --- PostgreSQL (instalador EDB) ---
    Write-Host "==> PostgreSQL..." -ForegroundColor Cyan
    $pg = Get-GbocPostgresRelease
    $pgRel = "postgresql\" + (Split-Path $pg.Url -Leaf)
    New-Item -ItemType Directory -Path (Join-Path $Dest "postgresql") -Force | Out-Null
    if ($pg.Url -and (Save-GbocDownload $pg.Url (Join-Path $Dest $pgRel))) {
        $man.postgres = (Add-GbocBundleItem ([ordered]@{ version = "$($pg.Version)" }) $Dest $pgRel)
        $report += [pscustomobject]@{ Programa = "PostgreSQL"; Versao = "$($pg.Version)"; Status = "OK" }
    } else {
        $report += [pscustomobject]@{ Programa = "PostgreSQL"; Versao = "$($pg.Version)"; Status = "FALHOU (instalador baixara)" }
    }

    # --- restic, Kopia, Duplicati (ultima release do GitHub) ---
    Write-Host "==> Motores de backup..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Path (Join-Path $Dest "engines") -Force | Out-Null
    foreach ($d in (Get-GbocEngineDefs)) {
        $rel = Get-GbocGitHubRelease $d.Repo $d.Pattern
        if (-not $rel -and $d.FallbackUrl) {
            $rel = [pscustomobject]@{ Version = $d.FallbackVersion; Url = $d.FallbackUrl; Name = (Split-Path $d.FallbackUrl -Leaf) }
        }
        $ok = $false
        if ($rel) {
            $eRel = "engines\" + $rel.Name
            if (Save-GbocDownload $rel.Url (Join-Path $Dest $eRel)) {
                $man.engines[$d.Key] = (Add-GbocBundleItem ([ordered]@{ version = "$($rel.Version)" }) $Dest $eRel)
                $ok = $true
            }
        }
        $report += [pscustomobject]@{ Programa = $d.Name; Versao = $(if ($rel) { "$($rel.Version)" } else { "-" })
            Status = $(if ($ok) { "OK" } else { "FALHOU (instalador baixara)" }) }
    }

    # --- NSSM (servico do Windows do Agente) ---
    Write-Host "==> NSSM..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Path (Join-Path $Dest "nssm") -Force | Out-Null
    $nRel = "nssm\nssm-2.24.zip"
    if (Save-GbocDownload "https://nssm.cc/release/nssm-2.24.zip" (Join-Path $Dest $nRel)) {
        $man.nssm = (Add-GbocBundleItem ([ordered]@{ version = "2.24" }) $Dest $nRel)
        $report += [pscustomobject]@{ Programa = "NSSM"; Versao = "2.24"; Status = "OK" }
    } else {
        $report += [pscustomobject]@{ Programa = "NSSM"; Versao = "2.24"; Status = "FALHOU (instalador baixara)" }
    }

    ($man | ConvertTo-Json -Depth 6) | Set-Content -Path (Join-Path $Dest "prereqs.json") -Encoding UTF8
    return $report
}

$bundleReport = @()
if ($Mode -eq "Completo") {
    $req = Join-Path $OutputDir "Dependencies\requirements-all.txt"
    if (-not (Test-Path $req)) {
        Write-Host "[ERRO] $req nao encontrado (o empacotador do codigo deveria ter criado)." -ForegroundColor Red
        exit 1
    }
    $bundleReport = New-GbocPrereqsBundle -Dest (Join-Path $OutputDir "Prereqs") -BuildPython $pythonCmd -Requirements $req
}

# Tipo do pacote no manifesto (o instalador mostra)
$manifestPath = Join-Path $OutputDir "package_manifest.json"
$pkgVersion = "v14.8.1"
if (Test-Path $manifestPath) {
    try {
        $mj = Get-Content $manifestPath -Raw | ConvertFrom-Json
        if ($mj.version) { $pkgVersion = [string]$mj.version }
        $mj | Add-Member -NotePropertyName package_mode -NotePropertyValue $Mode.ToLowerInvariant() -Force
        $mj | Add-Member -NotePropertyName package_created_at -NotePropertyValue (Get-Date).ToString("s") -Force
        ($mj | ConvertTo-Json -Depth 6) | Set-Content -Path $manifestPath -Encoding UTF8
    } catch {
        Write-Host "    [!] package_manifest.json nao atualizado: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# Arquivo .zip pronto para copiar
$zipPath = $null
if ($makeZip) {
    Write-Host "==> Gerando arquivo .zip..." -ForegroundColor Cyan
    $safeVer = ([regex]::Match($pkgVersion, 'v?\d+(\.\d+)+')).Value
    if (-not $safeVer) { $safeVer = "pacote" }
    $zipPath = Join-Path (Split-Path -Parent $OutputDir) ("GBOC-Instalador_{0}_{1}_{2}.zip" -f $safeVer, $Mode.ToLowerInvariant(), (Get-Date -Format "yyyyMMdd"))
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($OutputDir, $zipPath, [System.IO.Compression.CompressionLevel]::Optimal, $true)
    Write-Host ("    [OK] {0} ({1:N0} MB)" -f $zipPath, ((Get-Item $zipPath).Length / 1MB)) -ForegroundColor Green
}

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Green
Write-Host "  PACOTE DE INSTALACAO GERADO COM SUCESSO!                       " -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Green
Write-Host "Tipo: $(if ($Mode -eq 'Completo') { 'Completo (instala sem internet)' } else { 'So codigo (instalador baixa os programas)' })" -ForegroundColor White
if ($bundleReport) {
    $bundleReport | Format-Table -AutoSize | Out-Host
    $sz = (Get-ChildItem (Join-Path $OutputDir "Prereqs") -Recurse -File | Measure-Object Length -Sum).Sum
    Write-Host ("Programas no pacote: {0:N0} MB" -f ($sz / 1MB)) -ForegroundColor Gray
}
Write-Host "Pasta criada: $OutputDir" -ForegroundColor White
if ($zipPath) { Write-Host "Arquivo .zip: $zipPath" -ForegroundColor White }
Write-Host "Para instalar, execute: $OutputDir\Setup.bat (como Administrador)" -ForegroundColor Yellow
Write-Host ""
