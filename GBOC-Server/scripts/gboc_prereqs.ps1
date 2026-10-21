<#
==============================================================================
GBOC System v14.8.2 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
==============================================================================

Pre-requisitos do GBOC sempre na ULTIMA versao estavel, descoberta na hora da instalacao:
  * Python      -> python.org (ultima versao com instalador Windows x64). Se as dependencias do GBOC
                   ainda nao instalarem na versao mais nova (pacote sem suporte), usa a anterior.
  * PostgreSQL  -> postgresql.org/versions.json + instalador EDB. Instalacao existente e mantida
                   (troca de versao principal exige migracao dos dados).
  * restic, Kopia, Duplicati -> ultima release do GitHub; versao instalada mais antiga e atualizada.
Antes as versoes eram fixas no codigo (Python 3.11.9, PostgreSQL 16.6, restic 0.17.3, Kopia 0.18.2,
Duplicati 2.1.0.2 beta) e envelheciam a cada release. Sem internet ou com a fonte fora do ar, cai
para uma versao conhecida (FALLBACK) e avisa.

Pacote de instalacao (build_installer_package, modo Completo): se existir a pasta Prereqs\ com
prereqs.json ao lado deste script (ou 1-2 niveis acima, ou em $env:GBOC_PACKAGE_DIR), cada programa
segue a ordem: JA INSTALADO na maquina -> mantem; senao -> instala o que veio no PACOTE (versao do
pacote, arquivo conferido por SHA-256); se nao estiver no pacote -> baixa da internet como acima.
Bibliotecas Python: instala das wheels do pacote sem internet; se faltar alguma, completa online.

Uso em outro script PowerShell (so define as funcoes):
    . "$PSScriptRoot\scripts\gboc_prereqs.ps1"
    $py = Install-GbocPython -Requirements "$PSScriptRoot\requirements.txt"
    $eng = Install-GbocEngines -ToolsDir "C:\GBOC\Tools"
Uso a partir de .bat (resultado gravado em -OutFile; tambem e a ultima linha da saida):
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\gboc_prereqs.ps1 -Python -Requirements requirements.txt -OutFile "%TEMP%\gboc_py.txt"
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\gboc_prereqs.ps1 -Postgres -OutFile "%TEMP%\gboc_pg.txt"   (pasta bin)
#>
# Nomes dos parametros com prefixo: ao ser carregado com "." num instalador, nao podem sobrescrever
# variaveis dele (ex.: $ToolsDir do Setup.ps1). Na linha de comando valem os apelidos (-Python, -ToolsDir...).
[CmdletBinding()]
param(
    [Alias("Python")][switch]$GbocDoPython,
    [Alias("Engines")][switch]$GbocDoEngines,
    [Alias("Postgres")][switch]$GbocDoPostgres,
    [Alias("Requirements")][string]$GbocRequirements = "",
    [Alias("ToolsDir")][string]$GbocToolsDir = "C:\GBOC\Tools",
    [Alias("OutFile")][string]$GbocOutFile = ""
)
$script:GbocMinPython = "3.11"
$script:GbocPrereqsDir = $PSScriptRoot          # pasta deste arquivo (para achar o Prereqs\ do pacote)

# Versoes usadas so quando a descoberta online falha
$script:GbocFallback = @{
    Python   = @("3.14.0", "3.13.9", "3.12.10")
    Postgres = "17.6-1"
    restic   = "0.19.1"
    kopia    = "0.23.1"
}

function Write-GbocInfo([string]$Msg) { Write-Host "    $Msg" -ForegroundColor Gray }
function Write-GbocOk([string]$Msg) { Write-Host "    [OK] $Msg" -ForegroundColor Green }
function Write-GbocWarn([string]$Msg) { Write-Host "    [!] $Msg" -ForegroundColor Yellow }

function Set-GbocTls {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch {}
}

function Get-GbocWeb([string]$Url, [int]$TimeoutSec = 30) {
    Set-GbocTls
    $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec -Headers @{ "User-Agent" = "GBOC-Installer" }
    return [string]$r.Content
}

function Test-GbocUrl([string]$Url) {
    Set-GbocTls
    try {
        $r = Invoke-WebRequest -Uri $Url -Method Head -UseBasicParsing -TimeoutSec 20 -Headers @{ "User-Agent" = "GBOC-Installer" }
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
    } catch { return $false }
}

function Save-GbocDownload([string]$Url, [string]$Destination, [int]$Retries = 3) {
    Set-GbocTls
    for ($i = 1; $i -le $Retries; $i++) {
        try {
            Write-GbocInfo "Baixando $(Split-Path $Url -Leaf) (tentativa $i/$Retries)..."
            $wc = New-Object System.Net.WebClient
            $wc.Headers.Add("User-Agent", "GBOC-Installer")
            $wc.DownloadFile($Url, $Destination)
            if ((Test-Path $Destination) -and (Get-Item $Destination).Length -gt 0) { return $true }
        } catch {
            Write-GbocWarn "Falha no download: $($_.Exception.Message)"
            Start-Sleep -Seconds 3
        }
    }
    return $false
}

# ============================================================================
# PACOTE DE INSTALACAO (pasta Prereqs\ criada pelo build_installer_package, modo Completo)
# ============================================================================

$script:GbocPkg = $null
$script:GbocPkgChecked = $false
$script:GbocPkgHashOk = @{}

function Set-GbocPackageDir([string]$Dir) {
    <# Usa explicitamente este pacote (pasta do pacote ou a propria Prereqs). Vazio = sem pacote. #>
    $script:GbocPkg = $null
    $script:GbocPkgChecked = $true
    if (-not $Dir) { return $null }
    foreach ($c in @((Join-Path $Dir "Prereqs"), $Dir)) {
        $m = Join-Path $c "prereqs.json"
        if (-not (Test-Path $m)) { continue }
        try {
            $j = Get-Content $m -Raw | ConvertFrom-Json
            if (-not $j.gboc_prereqs) { continue }
            $j | Add-Member -NotePropertyName root -NotePropertyValue (Resolve-Path $c).Path -Force
            $script:GbocPkg = $j
            Write-GbocInfo "Pacote de instalacao encontrado: $($j.root) (gerado em $($j.created_at))"
            return $j
        } catch {
            Write-GbocWarn "prereqs.json ilegivel em ${c}: $($_.Exception.Message)"
        }
    }
    return $null
}

function Get-GbocPackage {
    if ($script:GbocPkgChecked) { return $script:GbocPkg }
    $cands = @()
    if ($env:GBOC_PACKAGE_DIR) { $cands += $env:GBOC_PACKAGE_DIR }
    if ($script:GbocPrereqsDir) {
        $cands += $script:GbocPrereqsDir
        $cands += (Join-Path $script:GbocPrereqsDir "..")
        $cands += (Join-Path $script:GbocPrereqsDir "..\..")
    }
    foreach ($c in $cands) {
        if ((Test-Path (Join-Path $c "Prereqs\prereqs.json")) -or (Test-Path (Join-Path $c "prereqs.json"))) {
            return (Set-GbocPackageDir $c)
        }
    }
    $script:GbocPkgChecked = $true
    return $null
}

function Get-GbocPackageFile($Item) {
    <# Caminho do arquivo do pacote se existir e o SHA-256 conferir; senao $null (vai para a internet). #>
    $pkg = Get-GbocPackage
    if (-not $pkg -or -not $Item -or -not $Item.file) { return $null }
    $path = Join-Path $pkg.root ([string]$Item.file)
    if (-not (Test-Path $path)) { return $null }
    if ($Item.sha256) {
        if (-not $script:GbocPkgHashOk.ContainsKey($path)) {
            $h = (Get-FileHash -Path $path -Algorithm SHA256).Hash
            $script:GbocPkgHashOk[$path] = ($h -eq ([string]$Item.sha256).ToUpperInvariant())
            if (-not $script:GbocPkgHashOk[$path]) { Write-GbocWarn "Arquivo do pacote corrompido (SHA-256 diferente): $path - sera baixado" }
        }
        if (-not $script:GbocPkgHashOk[$path]) { return $null }
    }
    return $path
}

function Get-GbocPackageEngine([string]$Key) {
    $pkg = Get-GbocPackage
    if (-not $pkg -or -not $pkg.engines) { return $null }
    $it = $pkg.engines.$Key
    $f = Get-GbocPackageFile $it
    if (-not $f) { return $null }
    return [pscustomobject]@{ Tag = [string]$it.version; Version = [string]$it.version; Url = ""; Name = (Split-Path $f -Leaf); File = $f }
}

# ============================================================================
# PYTHON
# ============================================================================

function Get-GbocPackagePythons {
    <# Versoes do Python que vieram no pacote (instalador conferido). #>
    $pkg = Get-GbocPackage
    $out = @()
    if ($pkg -and $pkg.python) {
        foreach ($it in @($pkg.python)) {
            $f = Get-GbocPackageFile $it
            if ($f) { $out += [pscustomobject]@{ Version = [version]$it.version; Url = ""; File = $f } }
        }
    }
    return @($out | Sort-Object Version -Descending)
}

function Get-GbocPythonReleases([int]$Minors = 3, [switch]$Online) {
    # Ultimo patch de cada uma das $Minors versoes mais novas que tenham instalador Windows x64.
    # Com pacote: as versoes do pacote (a internet so e consultada se o pacote nao trouxer o Python).
    if (-not $Online) {
        $null = Get-GbocPackage          # inicializa o pacote antes (no Windows PowerShell 5.1 a primeira chamada aninhada vinha vazia)
        $fromPkg = @(Get-GbocPackagePythons)
        if ($fromPkg.Count -gt 0) { return $fromPkg }
    }
    $out = @()
    try {
        $html = Get-GbocWeb "https://www.python.org/ftp/python/"
        $vers = [regex]::Matches($html, 'href="(\d+)\.(\d+)\.(\d+)/"') | ForEach-Object {
            [version]("{0}.{1}.{2}" -f $_.Groups[1].Value, $_.Groups[2].Value, $_.Groups[3].Value)
        } | Where-Object { $_ -ge [version]"$script:GbocMinPython.0" } | Sort-Object -Descending -Unique
        $byMinor = $vers | Group-Object { "$($_.Major).$($_.Minor)" } |
            Sort-Object { [version]($_.Name + ".0") } -Descending
        foreach ($g in $byMinor) {
            if ($out.Count -ge $Minors) { break }
            $checked = 0
            foreach ($v in ($g.Group | Sort-Object -Descending)) {
                if ($checked -ge 4) { break }       # patch anunciado mas sem instalador ainda (rc, em publicacao)
                $checked++
                $url = "https://www.python.org/ftp/python/$v/python-$v-amd64.exe"
                if (Test-GbocUrl $url) { $out += [pscustomobject]@{ Version = $v; Url = $url }; break }
            }
        }
    } catch {
        Write-GbocWarn "Nao foi possivel consultar python.org: $($_.Exception.Message)"
    }
    if ($out.Count -eq 0) {
        Write-GbocWarn "Usando versoes conhecidas do Python (sem acesso a lista do python.org)"
        foreach ($v in $script:GbocFallback.Python) {
            $out += [pscustomobject]@{ Version = [version]$v; Url = "https://www.python.org/ftp/python/$v/python-$v-amd64.exe" }
        }
    }
    return $out
}

function Get-GbocPythonVersion([string]$Exe) {
    $ErrorActionPreference = "Continue"
    try {
        $o = & $Exe -c "import sys;print('%d.%d.%d' % sys.version_info[:3])" 2>$null
        if ($LASTEXITCODE -eq 0 -and "$o" -match '(\d+\.\d+\.\d+)') { return [version]$Matches[1] }
    } catch {}
    return $null
}

function Get-GbocInstalledPythons {
    $ErrorActionPreference = "Continue"
    $paths = @()
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($line in (& $py.Source -0p 2>$null)) {
            if ("$line" -match '^\s*-\S+\s+(?:\*\s+)?(.+?\.exe)\s*$') { $paths += $Matches[1].Trim() }
        }
    }
    foreach ($hive in @("HKLM:\SOFTWARE\Python\PythonCore", "HKCU:\SOFTWARE\Python\PythonCore")) {
        foreach ($k in (Get-ChildItem $hive -ErrorAction SilentlyContinue)) {
            $props = Get-ItemProperty (Join-Path $k.PSPath "InstallPath") -ErrorAction SilentlyContinue
            if ($props.ExecutablePath) { $paths += [string]$props.ExecutablePath }
            elseif ($props.'(default)') { $paths += (Join-Path ([string]$props.'(default)') "python.exe") }
        }
    }
    foreach ($g in @("$env:ProgramFiles\Python3*\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "C:\Python3*\python.exe")) {
        $paths += (Get-ChildItem $g -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    }
    $seen = @{}
    $list = @()
    foreach ($p in $paths) {
        if (-not $p -or $p -match '\\WindowsApps\\' -or (Split-Path -Leaf $p) -ne "python.exe" -or -not (Test-Path $p)) { continue }
        $k = $p.ToLowerInvariant()
        if ($seen.ContainsKey($k)) { continue }
        $seen[$k] = $true
        $v = Get-GbocPythonVersion $p
        if ($v) { $list += [pscustomobject]@{ Path = $p; Version = $v } }
    }
    return @($list | Sort-Object Version -Descending)
}

function Stop-GbocServicesForUpgrade {
    # Atualizar o Python em uso pelo servico falha com arquivos bloqueados
    foreach ($n in @("GBOCAgent", "GBOCServer")) {
        $s = Get-Service -Name $n -ErrorAction SilentlyContinue
        if ($s -and $s.Status -eq "Running") {
            Write-GbocInfo "Parando o servico $n para atualizar o Python..."
            Stop-Service $n -Force -ErrorAction SilentlyContinue
        }
    }
}

function Install-GbocPythonVersion($Release) {
    $fromPkg = [bool]($Release.PSObject.Properties["File"] -and $Release.File)
    if ($fromPkg) {
        $file = $Release.File
        Write-GbocInfo "Usando o instalador do Python $($Release.Version) do pacote"
    } else {
        $file = Join-Path ([System.IO.Path]::GetTempPath()) ("python-{0}-amd64.exe" -f $Release.Version)
        if (-not (Save-GbocDownload $Release.Url $file)) { return $null }
    }
    Write-GbocInfo "Instalando Python $($Release.Version) para todos os usuarios (silencioso)..."
    $p = Start-Process -FilePath $file -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=1 Include_test=0 Include_doc=0" -Wait -PassThru
    if (-not $fromPkg) { Remove-Item $file -Force -ErrorAction SilentlyContinue }
    $exe = Join-Path $env:ProgramFiles ("Python{0}{1}\python.exe" -f $Release.Version.Major, $Release.Version.Minor)
    if (Test-Path $exe) { return $exe }
    $found = Get-GbocInstalledPythons | Where-Object { $_.Version -eq $Release.Version } | Select-Object -First 1
    if ($found) { return $found.Path }
    Write-GbocWarn "Instalacao do Python $($Release.Version) nao confirmada (codigo $($p.ExitCode))"
    return $null
}

function Get-GbocWheelDir([string]$Exe) {
    <# Pasta de wheels do pacote para a versao (X.Y) deste Python, ou $null. #>
    $pkg = Get-GbocPackage
    if (-not $pkg -or -not $pkg.wheels) { return $null }
    $v = Get-GbocPythonVersion $Exe
    if (-not $v) { return $null }
    foreach ($w in @($pkg.wheels)) {
        if ([string]$w.python -eq ("{0}.{1}" -f $v.Major, $v.Minor)) {
            $d = Join-Path $pkg.root ([string]$w.dir)
            if (Test-Path $d) { return $d }
        }
    }
    return $null
}

function Install-GbocPipRequirements([string]$Exe, [string]$Req, [switch]$UpgradePip) {
    <# pip install -r: primeiro so com as wheels do pacote (sem internet); se faltar algo, completa online. #>
    $ErrorActionPreference = "Continue"     # avisos do pip no stderr nao podem abortar o instalador
    $wd = Get-GbocWheelDir $Exe
    $optReq = if ($Req) { Join-Path (Split-Path $Req) "requirements-optional.txt" } else { "" }
    $mainSuccess = $false

    if ($wd) {
        Write-GbocInfo "Bibliotecas Python do pacote: $wd"
        if ($UpgradePip) { & $Exe -m pip install --disable-pip-version-check --no-index --find-links $wd --upgrade pip setuptools wheel -q 2>&1 | Out-Null }
        & $Exe -m pip install --disable-pip-version-check --no-index --find-links $wd -r $Req -q 2>&1 | ForEach-Object { Write-Host ("    " + "$_") -ForegroundColor DarkGray }
        if ($LASTEXITCODE -eq 0) {
            $mainSuccess = $true
        } else {
            Write-GbocWarn "Bibliotecas do pacote nao cobriram tudo; completando pela internet..."
            & $Exe -m pip install --disable-pip-version-check --find-links $wd -r $Req -q 2>&1 | ForEach-Object { Write-Host ("    " + "$_") -ForegroundColor DarkGray }
            $mainSuccess = ($LASTEXITCODE -eq 0)
        }
        if ($optReq -and (Test-Path $optReq)) {
            Write-GbocInfo "Instalando pacotes opcionais de aceleracao do pacote..."
            & $Exe -m pip install --disable-pip-version-check --find-links $wd --only-binary :all: -r $optReq -q 2>&1 | Out-Null
        }
        return $mainSuccess
    }

    if ($UpgradePip) { & $Exe -m pip install --disable-pip-version-check --upgrade pip setuptools wheel -q 2>&1 | Out-Null }
    & $Exe -m pip install --disable-pip-version-check -r $Req -q 2>&1 | ForEach-Object { Write-Host ("    " + "$_") -ForegroundColor DarkGray }     # mostra, mas nao vira retorno
    $mainSuccess = ($LASTEXITCODE -eq 0)

    if ($optReq -and (Test-Path $optReq)) {
        Write-GbocInfo "Verificando pacotes opcionais de aceleracao (ex: zstandard)..."
        # Tenta com --only-binary :all: para evitar erro de compilador C++ no Windows
        & $Exe -m pip install --disable-pip-version-check --only-binary :all: -r $optReq -q 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            # Se nao tiver binary wheel pronta, tenta compilar caso haja compilador instalado no sistema
            & $Exe -m pip install --disable-pip-version-check -r $optReq -q 2>&1 | Out-Null
        }
    }

    return $mainSuccess
}

function Test-GbocPythonDeps([string]$Exe) {
    $ErrorActionPreference = "Continue"
    & $Exe -c "import fastapi, uvicorn, psycopg2, cryptography, pydantic" 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Install-GbocRequirements([string]$Exe, [string]$Req) {
    if (-not $Req -or -not (Test-Path $Req)) { return $true }
    Write-GbocInfo "Instalando dependencias do GBOC no Python $(Get-GbocPythonVersion $Exe)..."
    if (-not (Install-GbocPipRequirements $Exe $Req -UpgradePip)) { return $false }
    return (Test-GbocPythonDeps $Exe)
}

function Install-GbocPython([string]$Requirements = "") {
    <# Garante o Python estavel mais novo com as dependencias do GBOC. Retorna o caminho do python.exe.
       Ordem: versao mais nova do python.org; se as dependencias falharem nela, a anterior, e assim por diante.
       Python ja instalado na mesma versao (ou patch mais novo) e reaproveitado. #>
    $releases = Get-GbocPythonReleases
    $installed = Get-GbocInstalledPythons
    $pkgMode = [bool](($releases | Select-Object -First 1) -and $releases[0].PSObject.Properties["File"] -and $releases[0].File)
    Write-GbocInfo ("Python {0}: {1} | instalados: {2}" -f $(if ($pkgMode) { "do pacote" } else { "mais novo disponivel" }),
        $(if ($releases) { $releases[0].Version } else { "-" }),
        $(if ($installed) { ($installed | ForEach-Object { $_.Version }) -join ", " } else { "nenhum" }))
    if ($pkgMode) {
        # Com pacote, programa ja instalado e mantido: Python que ja roda o GBOC (ou da mesma serie do pacote) serve
        foreach ($i in $installed) {
            if ($i.Version -lt [version]"$script:GbocMinPython.0") { continue }
            if (Test-GbocPythonDeps $i.Path) {
                Write-GbocOk "Python $($i.Version) ja instalado com as dependencias do GBOC: $($i.Path)"
                if (Install-GbocRequirements $i.Path $Requirements) { return $i.Path }
            }
        }
    }
    $stopped = $false
    foreach ($rel in $releases) {
        $same = $installed | Where-Object { $_.Version.Major -eq $rel.Version.Major -and $_.Version.Minor -eq $rel.Version.Minor } |
            Select-Object -First 1
        $exe = $null
        if ($same -and ($pkgMode -or $same.Version -ge $rel.Version)) {
            $exe = $same.Path
            Write-GbocOk "Python $($same.Version) ja instalado: $exe"
        } else {
            if ($same -and -not $stopped) { Stop-GbocServicesForUpgrade; $stopped = $true }
            $exe = Install-GbocPythonVersion $rel
            if ($exe) {
                Write-GbocOk "Python $($rel.Version) instalado: $exe"
            } elseif ($same) {
                # Atualizacao do patch falhou: segue na versao ja instalada da mesma serie (nao instala outra serie)
                $exe = $same.Path
                Write-GbocWarn "Atualizacao para o Python $($rel.Version) falhou; mantido o $($same.Version)"
            } else {
                continue
            }
        }
        if (Install-GbocRequirements $exe $Requirements) { return $exe }
        Write-GbocWarn "Dependencias do GBOC ainda nao instalam no Python $($rel.Version); tentando a versao anterior"
    }
    # Ultimo recurso: algum Python ja instalado que tenha (ou aceite) as dependencias
    foreach ($i in (Get-GbocInstalledPythons)) {
        if ($i.Version -lt [version]"$script:GbocMinPython.0") { continue }
        if (Install-GbocRequirements $i.Path $Requirements) { return $i.Path }
    }
    return $null
}

# ============================================================================
# GITHUB (restic, Kopia, Duplicati)
# ============================================================================

function Get-GbocGitHubRelease([string]$Repo, [string]$AssetPattern) {
    try {
        $j = Get-GbocWeb "https://api.github.com/repos/$Repo/releases/latest" | ConvertFrom-Json
        $asset = $j.assets | Where-Object { $_.name -match $AssetPattern } | Select-Object -First 1
        if ($asset) {
            $ver = ([regex]::Match([string]$j.tag_name, '\d+(\.\d+)+')).Value
            return [pscustomobject]@{ Tag = [string]$j.tag_name; Version = $ver; Url = [string]$asset.browser_download_url; Name = [string]$asset.name }
        }
        Write-GbocWarn "Release $($j.tag_name) de $Repo sem arquivo '$AssetPattern'"
    } catch {
        Write-GbocWarn "Nao foi possivel consultar a ultima versao de ${Repo}: $($_.Exception.Message)"
    }
    return $null
}

function Get-GbocToolVersion([string]$Dir, [string]$Exe) {
    $ErrorActionPreference = "Continue"
    $marker = Join-Path $Dir ".gboc_version"
    if (Test-Path $marker) { return (Get-Content $marker -Raw).Trim() }
    if ($Exe -and (Test-Path $Exe)) {
        try {
            $o = (& $Exe version 2>$null) + " " + (& $Exe --version 2>$null)
            $m = [regex]::Match("$o", '\d+\.\d+\.\d+(\.\d+)?')
            if ($m.Success) { return $m.Value }
        } catch {}
    }
    return ""
}

function Test-GbocNewer([string]$Latest, [string]$Current) {
    if (-not $Current) { return $true }
    try { return ([version]$Latest -gt [version]$Current) } catch { return ($Latest -ne $Current) }
}

function Get-GbocEngineDefs {
    <# Motores de backup: fonte (GitHub), arquivo, pasta no GBOC e onde podem ja estar instalados. #>
    $fr = $script:GbocFallback.restic
    $fk = $script:GbocFallback.kopia
    return @(
        [pscustomobject]@{ Key = "restic"; Name = "restic"; Repo = "restic/restic"; Pattern = '^restic_[\d.]+_windows_amd64\.zip$'
            DirName = "Restic"; ExeName = "restic.exe"; ExeFilter = "restic*.exe"; EnvVar = "RESTIC_PATH"; WholeFolder = $false
            FallbackUrl = "https://github.com/restic/restic/releases/download/v$fr/restic_${fr}_windows_amd64.zip"; FallbackVersion = $fr
            Known = @() },
        [pscustomobject]@{ Key = "kopia"; Name = "Kopia"; Repo = "kopia/kopia"; Pattern = '^kopia-[\d.]+-windows-x64\.zip$'
            DirName = "Kopia"; ExeName = "kopia.exe"; ExeFilter = "kopia.exe"; EnvVar = "KOPIA_PATH"; WholeFolder = $false
            FallbackUrl = "https://github.com/kopia/kopia/releases/download/v$fk/kopia-$fk-windows-x64.zip"; FallbackVersion = $fk
            Known = @("$env:ProgramFiles\KopiaUI\resources\server\kopia.exe") },
        # Duplicati 2.1+: aplicativo completo e autossuficiente (nao precisa mais de .NET instalado)
        [pscustomobject]@{ Key = "duplicati"; Name = "Duplicati"; Repo = "duplicati/duplicati"; Pattern = 'win-x64-gui\.zip$'
            DirName = "Duplicati"; ExeName = "Duplicati.CommandLine.exe"; ExeFilter = "Duplicati.CommandLine.exe"; EnvVar = "DUPLICATI_PATH"
            WholeFolder = $true; FallbackUrl = ""; FallbackVersion = ""
            Known = @("$env:ProgramFiles\Duplicati 2\Duplicati.CommandLine.exe", "${env:ProgramFiles(x86)}\Duplicati 2\Duplicati.CommandLine.exe") }
    )
}

function Find-GbocExistingTool([string]$ExeName, [string]$EnvVar, [string[]]$Known, [string]$Dir) {
    <# Instalacao do programa fora da pasta do GBOC (variavel de ambiente, Program Files, PATH). #>
    $cands = @()
    if ($EnvVar) {
        foreach ($scope in @("Process", "Machine", "User")) {
            $v = [Environment]::GetEnvironmentVariable($EnvVar, $scope)
            if ($v) { $cands += $v }
        }
    }
    $cands += $Known
    $cmd = Get-Command $ExeName -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { $cands += $cmd.Source }
    foreach ($c in $cands) {
        if (-not $c -or -not (Test-Path $c -PathType Leaf)) { continue }
        if ($Dir -and ((Split-Path -Parent (Resolve-Path $c).Path) -eq (Resolve-Path $Dir -ErrorAction SilentlyContinue).Path)) { continue }
        return (Resolve-Path $c).Path
    }
    return $null
}

function Install-GbocZipTool {
    param([string]$Name, [string]$Repo, [string]$Pattern, [string]$Dir, [string]$ExeName,
          [string]$ExeFilter, [string]$FallbackUrl = "", [string]$FallbackVersion = "", [switch]$WholeFolder,
          [string]$Key = "", [string]$EnvVar = "", [string[]]$Known = @())
    $exe = Join-Path $Dir $ExeName
    $rel = $null
    if ($Key) { $rel = Get-GbocPackageEngine $Key }          # versao do pacote (sem consultar o GitHub)
    $fromPkg = [bool]$rel
    if (-not $rel) { $rel = Get-GbocGitHubRelease $Repo $Pattern }
    if (-not $rel -and $FallbackUrl) {
        $rel = [pscustomobject]@{ Tag = $FallbackVersion; Version = $FallbackVersion; Url = $FallbackUrl; Name = (Split-Path $FallbackUrl -Leaf) }
        Write-GbocWarn "$Name`: usando a versao conhecida $FallbackVersion"
    }
    $current = Get-GbocToolVersion $Dir $exe
    if (-not (Test-Path $exe)) {
        # Ja instalado na maquina fora da pasta do GBOC: mantem, a nao ser que seja mais antigo que o alvo
        $other = Find-GbocExistingTool $ExeName $EnvVar $Known $Dir
        if ($other) {
            $ov = Get-GbocToolVersion (Split-Path -Parent $other) $other
            if (-not $rel -or -not $ov -or -not (Test-GbocNewer $rel.Version $ov)) {
                Write-GbocOk "$Name ja instalado na maquina$(if ($ov) { " ($ov)" }): $other - mantido"
                return $other
            }
            Write-GbocInfo "$Name $ov em $other e mais antigo que $($rel.Version); instalando a versao nova em $Dir"
        }
    }
    if (-not $rel) {
        if (Test-Path $exe) { Write-GbocWarn "$Name`: mantida a versao instalada ($current)"; return $exe }
        Write-GbocWarn "$Name nao instalado (sem acesso ao GitHub)"
        return $null
    }
    if ((Test-Path $exe) -and -not (Test-GbocNewer $rel.Version $current)) {
        Write-GbocOk "$Name $current ja instalado$(if ($fromPkg) { ' (pacote: ' + $rel.Version + ')' } else { ' - e a versao mais nova' })"
        return $exe
    }
    if ($fromPkg) {
        $zip = $rel.File
        Write-GbocInfo "$Name $($rel.Version): usando o arquivo do pacote"
    } else {
        $zip = Join-Path ([System.IO.Path]::GetTempPath()) $rel.Name
        if (-not (Save-GbocDownload $rel.Url $zip)) {
            if (Test-Path $exe) { Write-GbocWarn "$Name`: download falhou, mantida a versao $current"; return $exe }
            return $null
        }
    }
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("gboc_" + $Name + "_" + [guid]::NewGuid().ToString("N"))
    try {
        Expand-Archive -Path $zip -DestinationPath $tmp -Force -ErrorAction Stop
        New-Item -ItemType Directory -Path $Dir -Force | Out-Null
        if ($WholeFolder) {
            # Aplicativo completo (Duplicati): conteudo da pasta raiz do zip para $Dir
            $rootDir = $tmp
            $kids = @(Get-ChildItem $tmp)
            if ($kids.Count -eq 1 -and $kids[0].PSIsContainer) { $rootDir = $kids[0].FullName }
            Copy-Item -Path (Join-Path $rootDir "*") -Destination $Dir -Recurse -Force -ErrorAction Stop
            $found = Get-ChildItem $Dir -Recurse -Filter $ExeFilter -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { $exe = $found.FullName }
        } else {
            $found = Get-ChildItem $tmp -Recurse -Filter $ExeFilter | Select-Object -First 1
            if (-not $found) { throw "executavel $ExeFilter nao encontrado no pacote" }
            Copy-Item $found.FullName $exe -Force -ErrorAction Stop        # restic_0.19.1_windows_amd64.exe -> restic.exe
        }
        Set-Content -Path (Join-Path $Dir ".gboc_version") -Value $rel.Version -Encoding ASCII
        Write-GbocOk "$Name $($rel.Version) instalado$(if ($current) { " (antes: $current)" })"
    } catch {
        Write-GbocWarn "$Name`: falha ao instalar ($($_.Exception.Message))$(if (Test-Path $exe) { "; mantida a versao $current" })"
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
        if (-not $fromPkg) { Remove-Item $zip -Force -ErrorAction SilentlyContinue }
    }
    if (Test-Path $exe) { return $exe }
    return $null
}

function Install-GbocEngines([string]$ToolsDir = "C:\GBOC\Tools", [switch]$NoMachineEnv) {
    <# restic, Kopia e Duplicati na ultima versao em $ToolsDir. Retorna @{restic=; kopia=; duplicati=}.
       Atualiza versoes antigas; define RESTIC_PATH / KOPIA_PATH / DUPLICATI_PATH (maquina). #>
    $res = @{}
    foreach ($d in (Get-GbocEngineDefs)) {
        $res[$d.Key] = Install-GbocZipTool -Name $d.Name -Repo $d.Repo -Pattern $d.Pattern -Dir (Join-Path $ToolsDir $d.DirName) `
            -ExeName $d.ExeName -ExeFilter $d.ExeFilter -FallbackUrl $d.FallbackUrl -FallbackVersion $d.FallbackVersion `
            -WholeFolder:$d.WholeFolder -Key $d.Key -EnvVar $d.EnvVar -Known $d.Known
    }
    if (-not $NoMachineEnv) {
        if ($res.restic) { [Environment]::SetEnvironmentVariable("RESTIC_PATH", $res.restic, "Machine") }
        if ($res.kopia) { [Environment]::SetEnvironmentVariable("KOPIA_PATH", $res.kopia, "Machine") }
        if ($res.duplicati) { [Environment]::SetEnvironmentVariable("DUPLICATI_PATH", $res.duplicati, "Machine") }
        [Environment]::SetEnvironmentVariable("GBOC_TOOLS_DIR", $ToolsDir, "Machine")
    }
    if ($res.restic) { $env:RESTIC_PATH = $res.restic }
    if ($res.kopia) { $env:KOPIA_PATH = $res.kopia }
    if ($res.duplicati) { $env:DUPLICATI_PATH = $res.duplicati }
    return $res
}

# ============================================================================
# POSTGRESQL
# ============================================================================

function Find-GbocPostgresBin([string]$ToolsDir = "C:\GBOC\Tools") {
    <# Pasta bin de um PostgreSQL ja instalado (servico, Program Files ou portatil do GBOC), a mais nova. #>
    $bins = @()
    foreach ($s in (Get-CimInstance Win32_Service -Filter "Name LIKE 'postgres%'" -ErrorAction SilentlyContinue)) {
        if ("$($s.PathName)" -match '^"?([^"]+\\bin)\\pg_ctl\.exe') { $bins += $Matches[1] }
    }
    $bins += (Get-ChildItem "$env:ProgramFiles\PostgreSQL\*\bin" -Directory -ErrorAction SilentlyContinue |
        Sort-Object { try { [version](($_.Parent.Name -replace '[^\d.]', '') + ".0") } catch { [version]"0.0" } } -Descending |
        ForEach-Object { $_.FullName })
    foreach ($p in @("$ToolsDir\PostgreSQL\bin", "$ToolsDir\PostgreSQL\pgsql\bin")) { $bins += $p }
    foreach ($b in $bins) { if ($b -and (Test-Path (Join-Path $b "psql.exe"))) { return $b } }
    return $null
}

function Get-GbocPostgresRelease([switch]$Binaries) {
    <# Ultima versao suportada do PostgreSQL e a URL do instalador (ou zip de binarios) da EDB.
       Com pacote: o instalador do pacote (propriedade File = caminho local). #>
    $suffix = if ($Binaries) { "windows-x64-binaries.zip" } else { "windows-x64.exe" }
    $pkg = Get-GbocPackage
    if ($pkg -and -not $Binaries -and $pkg.postgres) {
        $f = Get-GbocPackageFile $pkg.postgres
        if ($f) { return [pscustomobject]@{ Version = [string]$pkg.postgres.version; Url = ""; File = $f } }
    }
    try {
        $j = Get-GbocWeb "https://www.postgresql.org/versions.json" | ConvertFrom-Json
        $sup = @($j | Where-Object { "$($_.supported)" -eq "True" } |
            Sort-Object { [double]("$($_.major)" -replace '[^\d.]', '') } -Descending)
        foreach ($v in $sup) {
            $ver = "{0}.{1}" -f $v.major, $v.latestMinor
            foreach ($build in 1..4) {
                $url = "https://get.enterprisedb.com/postgresql/postgresql-$ver-$build-$suffix"
                if (Test-GbocUrl $url) { return [pscustomobject]@{ Version = $ver; Url = $url } }
            }
            Write-GbocWarn "PostgreSQL $ver ainda sem instalador Windows da EDB; tentando a versao anterior"
        }
    } catch {
        Write-GbocWarn "Nao foi possivel consultar postgresql.org: $($_.Exception.Message)"
    }
    $fb = $script:GbocFallback.Postgres
    Write-GbocWarn "Usando a versao conhecida do PostgreSQL $fb"
    return [pscustomobject]@{ Version = ($fb -replace '-\d+$', ''); Url = "https://get.enterprisedb.com/postgresql/postgresql-$fb-$suffix" }
}

function Install-GbocPostgres([string]$ToolsDir = "C:\GBOC\Tools", [string]$Password, [string]$ServiceName = "postgresql-gboc", [int]$Port = 5432) {
    <# PostgreSQL ja instalado -> mantido (retorna a pasta bin). Senao instala do pacote (ou baixa), silencioso,
       como o install_agent.ps1: servico $ServiceName, porta $Port, pasta $ToolsDir\PostgreSQL. #>
    $bin = Find-GbocPostgresBin -ToolsDir $ToolsDir
    if ($bin) { Write-GbocOk "PostgreSQL ja instalado: $bin - mantido"; return $bin }
    if (-not $Password) { Write-GbocWarn "Senha do superusuario do PostgreSQL nao informada; PostgreSQL nao instalado"; return $null }
    $rel = Get-GbocPostgresRelease
    $fromPkg = [bool]($rel.PSObject.Properties["File"] -and $rel.File)
    if ($fromPkg) {
        $inst = $rel.File
        Write-GbocInfo "PostgreSQL $($rel.Version): usando o instalador do pacote"
    } else {
        $inst = Join-Path ([System.IO.Path]::GetTempPath()) (Split-Path $rel.Url -Leaf)
        if (-not (Save-GbocDownload $rel.Url $inst)) { Write-GbocWarn "Download do PostgreSQL falhou"; return $null }
    }
    $prefix = Join-Path $ToolsDir "PostgreSQL"
    Write-GbocInfo "Instalando PostgreSQL $($rel.Version) em $prefix (silencioso, pode levar alguns minutos)..."
    $pgArgs = @("--mode", "unattended", "--unattendedmodeui", "minimal", "--prefix", "`"$prefix`"", "--datadir", "`"$prefix\data`"",
                "--superpassword", "`"$Password`"", "--serverport", "$Port", "--servicename", $ServiceName,
                "--locale", "C", "--enable-components", "server")
    $p = Start-Process -FilePath $inst -ArgumentList $pgArgs -Wait -PassThru
    if (-not $fromPkg) { Remove-Item $inst -Force -ErrorAction SilentlyContinue }
    $bin = Find-GbocPostgresBin -ToolsDir $ToolsDir
    if ($bin) { Write-GbocOk "PostgreSQL $($rel.Version) instalado: $bin"; return $bin }
    Write-GbocWarn "Instalacao do PostgreSQL nao confirmada (codigo $($p.ExitCode))"
    return $null
}

# ============================================================================
# NSSM (servico do Windows para o Agente)
# ============================================================================

function Install-GbocNssm([string]$ToolsDir = "C:\GBOC\Tools") {
    $dir = Join-Path $ToolsDir "nssm"
    $exe = Join-Path $dir "nssm.exe"
    if (Test-Path $exe) { return $exe }
    $pkg = Get-GbocPackage
    $zip = $null
    $fromPkg = $false
    if ($pkg -and $pkg.nssm) { $zip = Get-GbocPackageFile $pkg.nssm; $fromPkg = [bool]$zip }
    if (-not $zip) {
        $zip = Join-Path ([System.IO.Path]::GetTempPath()) "nssm-2.24.zip"
        if (-not (Save-GbocDownload "https://nssm.cc/release/nssm-2.24.zip" $zip)) { return $null }
    }
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("gboc_nssm_" + [guid]::NewGuid().ToString("N"))
    try {
        Expand-Archive -Path $zip -DestinationPath $tmp -Force -ErrorAction Stop
        $found = Get-ChildItem $tmp -Recurse -Filter nssm.exe | Where-Object { $_.FullName -match '\\win64\\' } | Select-Object -First 1
        if (-not $found) { throw "nssm.exe (win64) nao encontrado no zip" }
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Copy-Item $found.FullName $exe -Force
        Write-GbocOk "NSSM instalado$(if ($fromPkg) { ' (do pacote)' }): $exe"
    } catch {
        Write-GbocWarn "NSSM: falha ao instalar ($($_.Exception.Message))"
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
        if (-not $fromPkg) { Remove-Item $zip -Force -ErrorAction SilentlyContinue }
    }
    if (Test-Path $exe) { return $exe }
    return $null
}

# ============================================================================
# Resumo: o que a maquina ja tem x o que veio no pacote
# ============================================================================

function Get-GbocPrereqStatus([string]$ToolsDir = "C:\GBOC\Tools", [switch]$NoPostgres) {
    $ErrorActionPreference = "Continue"
    $pkg = Get-GbocPackage
    $rows = @()
    $pys = @(Get-GbocInstalledPythons)
    $py = $pys | Select-Object -First 1
    $pp = Get-GbocPackagePythons | Select-Object -First 1
    $withDeps = $pys | Where-Object { $_.Version -ge [version]"$script:GbocMinPython.0" -and (Test-GbocPythonDeps $_.Path) } | Select-Object -First 1
    $sameMinor = if ($pp) { $pys | Where-Object { $_.Version.Major -eq $pp.Version.Major -and $_.Version.Minor -eq $pp.Version.Minor } | Select-Object -First 1 }
    $pyAcao = if ($withDeps) { "manter ($($withDeps.Version) ja tem as bibliotecas do GBOC)" }
              elseif ($sameMinor) { "manter $($sameMinor.Version) e instalar as bibliotecas" }
              elseif ($pp) { "instalar do pacote$(if ($py) { ' (os ja instalados ficam)' })" }
              elseif ($py) { "manter ou atualizar pela internet" } else { "baixar" }
    $rows += [pscustomobject]@{ Programa = "Python"; Maquina = $(if ($py) { ($pys | ForEach-Object { "$($_.Version)" }) -join ", " } else { "-" })
        Pacote = $(if ($pp) { "$($pp.Version)" } else { "-" }); Acao = $pyAcao }
    if (-not $NoPostgres) {
        $bin = Find-GbocPostgresBin -ToolsDir $ToolsDir
        $pv = "-"
        if ($bin) { $pv = (& (Join-Path $bin "postgres.exe") --version 2>$null) -replace '^.*\)\s*', ''; if (-not $pv) { $pv = "instalado" } }
        $pkgPg = $null
        if ($pkg -and $pkg.postgres -and (Get-GbocPackageFile $pkg.postgres)) { $pkgPg = [string]$pkg.postgres.version }
        $rows += [pscustomobject]@{ Programa = "PostgreSQL"; Maquina = $pv; Pacote = $(if ($pkgPg) { $pkgPg } else { "-" })
            Acao = $(if ($bin) { "manter" } elseif ($pkgPg) { "instalar do pacote" } else { "baixar" }) }
    }
    foreach ($d in (Get-GbocEngineDefs)) {
        $dir = Join-Path $ToolsDir $d.DirName
        $exe = Join-Path $dir $d.ExeName
        $where = $null
        if (Test-Path $exe) { $where = $exe } else { $where = Find-GbocExistingTool $d.ExeName $d.EnvVar $d.Known $dir }
        $cur = $(if ($where) { Get-GbocToolVersion (Split-Path -Parent $where) $where } else { "" })
        $pe = Get-GbocPackageEngine $d.Key
        $acao = if (-not $where) { $(if ($pe) { "instalar do pacote" } else { "baixar" }) }
                elseif ($pe -and $cur -and (Test-GbocNewer $pe.Version $cur)) { "atualizar pelo pacote" }
                elseif ($pe -or (Test-Path $exe)) { "manter" } else { "manter" }
        $rows += [pscustomobject]@{ Programa = $d.Name; Maquina = $(if ($where) { $(if ($cur) { $cur } else { "instalado" }) } else { "-" })
            Pacote = $(if ($pe) { $pe.Version } else { "-" }); Acao = $acao }
    }
    return $rows
}

# ============================================================================
# LLM LOCAL GRATUITO (OLLAMA)
# ============================================================================

function Find-GbocOllamaExe {
    $cands = @()
    $cmd = Get-Command ollama.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { $cands += $cmd.Source }
    $cands += "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    $cands += "$env:ProgramFiles\Ollama\ollama.exe"
    $cands += "${env:ProgramFiles(x86)}\Ollama\ollama.exe"
    foreach ($c in $cands) {
        if ($c -and (Test-Path $c -PathType Leaf)) { return (Resolve-Path $c).Path }
    }
    return $null
}

function Test-GbocOllamaRunning([string]$HostUrl = "http://localhost:11434") {
    try {
        $r = Invoke-WebRequest -Uri "$HostUrl/api/tags" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
    } catch { return $false }
}

function Start-GbocOllamaService([string]$ExePath) {
    if (Test-GbocOllamaRunning) { return $true }
    if (-not $ExePath -or -not (Test-Path $ExePath)) { return $false }
    Write-GbocInfo "Iniciando motor de IA Local Ollama em segundo plano..."
    Start-Process -FilePath $ExePath -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        if (Test-GbocOllamaRunning) { return $true }
    }
    return (Test-GbocOllamaRunning)
}

function Configure-GbocAiSystem([string]$InstallRoot = "C:\GBOC", [string]$Model = "qwen3.5:4b") {
    $aiCfg = @{
        provider      = "ollama"
        ollama_url    = "http://localhost:11434"
        ollama_host   = "http://localhost:11434"
        ollama_model  = $Model
        model         = $Model
        system_prompt = "Você é o GBOC Copilot AI, especialista em backup, recuperação de desastres, virtualização e administração do GBOC Enterprise. Responda em português brasileiro com clareza técnica baseando-se estritamente nos dados reais do sistema."
    }
    $jsonContent = $aiCfg | ConvertTo-Json -Depth 4
    $dirs = @(
        (Join-Path $InstallRoot "Server\data"),
        (Join-Path $InstallRoot "Agent\data"),
        "C:\GBOC\Server\data",
        "C:\GBOC\Agent\data"
    )
    foreach ($d in $dirs) {
        if (Test-Path (Split-Path -Parent $d)) {
            New-Item -ItemType Directory -Path $d -Force | Out-Null
            Set-Content -Path (Join-Path $d "server_ai_config.json") -Value $jsonContent -Encoding UTF8
            Set-Content -Path (Join-Path $d "ai_config.json") -Value $jsonContent -Encoding UTF8
        }
    }
    [Environment]::SetEnvironmentVariable("GBOC_AI_PROVIDER", "ollama", "Machine")
    [Environment]::SetEnvironmentVariable("GBOC_OLLAMA_URL", "http://localhost:11434", "Machine")
    [Environment]::SetEnvironmentVariable("GBOC_AI_MODEL", $Model, "Machine")
    $env:GBOC_AI_PROVIDER = "ollama"
    $env:GBOC_OLLAMA_URL = "http://localhost:11434"
    $env:GBOC_AI_MODEL = $Model
    Write-GbocOk "Integracao de IA configurada com sucesso no GBOC (Provedor: Ollama | Modelo: $Model)"
}

function Install-GbocOllama([string]$Model = "qwen3.5:4b", [string]$InstallRoot = "C:\GBOC") {
    <# Instala o Ollama (LLM Local Gratuito) caso nao exista, garante que esteja rodando,
       faz o download (pull) do modelo gratuito recomendado e integra com a configuracao do GBOC. #>
    Write-Host "==> Verificando motor de IA Local Gratuito (Ollama)..." -ForegroundColor Cyan
    $exe = Find-GbocOllamaExe

    if (-not $exe) {
        Write-GbocInfo "Ollama nao detectado no host. Iniciando instalacao automatica..."
        $installed = $false

        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if ($winget) {
            Write-GbocInfo "Instalando Ollama via winget..."
            & winget install Ollama.Ollama --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
            $exe = Find-GbocOllamaExe
            if ($exe) { $installed = $true }
        }

        if (-not $installed) {
            Write-GbocInfo "Baixando instalador oficial do Ollama para Windows..."
            $tmpSetup = Join-Path ([System.IO.Path]::GetTempPath()) "OllamaSetup.exe"
            $dlOk = Save-GbocDownload "https://ollama.com/download/OllamaSetup.exe" $tmpSetup
            if ($dlOk -and (Test-Path $tmpSetup)) {
                Write-GbocInfo "Executando instalacao silenciosa do Ollama..."
                $proc = Start-Process -FilePath $tmpSetup -ArgumentList "/silent" -Wait -PassThru
                Start-Sleep -Seconds 3
                Remove-Item $tmpSetup -Force -ErrorAction SilentlyContinue
                $exe = Find-GbocOllamaExe
                if ($exe) { $installed = $true }
            }
        }

        if (-not $exe) {
            Write-GbocWarn "Nao foi possivel instalar o Ollama automaticamente. Instale manualmente em https://ollama.com"
            return $null
        }
        Write-GbocOk "Ollama instalado com sucesso: $exe"
    } else {
        Write-GbocOk "Ollama ja instalado no sistema: $exe"
    }

    $running = Start-GbocOllamaService $exe
    if (-not $running) {
        Write-GbocWarn "O motor Ollama nao respondeu em http://localhost:11434. Verifique a porta 11434."
        return $exe
    }
    Write-GbocOk "Motor de IA Ollama operacional em http://localhost:11434"

    $hasModel = $false
    try {
        $tags = (Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5).models
        if ($tags | Where-Object { $_.name -like "$Model*" }) {
            $hasModel = $true
            Write-GbocOk "Modelo de IA gratuito $Model ja disponivel localmente."
        }
    } catch {}

    if (-not $hasModel) {
        Write-Host "==> Baixando modelo LLM gratuito '$Model' para operacao offline..." -ForegroundColor Cyan
        Write-GbocInfo "Download do modelo pode levar alguns minutos na primeira vez..."
        & $exe pull $Model
        if ($LASTEXITCODE -eq 0) {
            Write-GbocOk "Modelo $Model baixado e pronto para uso."
        } else {
            Write-GbocWarn "Download automatico do modelo $Model pendente. Execute manualmente: ollama pull $Model"
        }
    }

    Configure-GbocAiSystem -InstallRoot $InstallRoot -Model $Model
    return $exe
}

# ============================================================================
# Execucao direta (.bat): a ultima linha da saida e o resultado
# ============================================================================
if ($MyInvocation.InvocationName -ne '.') {
    $ErrorActionPreference = "Continue"
    $last = ""
    if ($GbocDoEngines) {
        $e = Install-GbocEngines -ToolsDir $GbocToolsDir
        $last = "restic=$($e.restic);kopia=$($e.kopia);duplicati=$($e.duplicati)"
    }
    if ($GbocDoPostgres) {
        $bin = Find-GbocPostgresBin -ToolsDir $GbocToolsDir     # pasta bin do PostgreSQL instalado (vazio se nenhum)
        if ($bin) { $last = $bin }
    }
    if ($GbocDoPython) {
        $exe = Install-GbocPython -Requirements $GbocRequirements
        if (-not $exe) { Write-GbocWarn "Nenhum Python com as dependencias do GBOC pode ser instalado"; exit 1 }
        $last = $exe
    }
    if ($last) {
        # -OutFile: o .bat le o resultado do arquivo (a saida na tela fica livre para o progresso)
        if ($GbocOutFile) { Set-Content -Path $GbocOutFile -Value $last -Encoding ASCII }
        Write-Output $last
    }
    exit 0
}
