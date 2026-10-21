<#
==============================================================================
GBOC System v14.8.2 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
==============================================================================

Localiza o Python que vai rodar o GBOC (Agente, Servidor ou Agendador) e escreve o caminho do
python.exe na saida padrao (stdout). Usado pelos .bat/.ps1 de inicializacao e pelo servico.

Por que existe: os scripts fixavam "py -3.14" ou um caminho absoluto (C:\Program Files\Python314\
python.exe, C:\GBOC\venv\...). Quando o Python e atualizado (3.14 -> 3.15) o caminho muda, o "py"
passa a abrir a versao nova sem as dependencias, e o sistema nao subia.

Regras:
  1. Variavel GBOC_PYTHON (caminho de um python.exe) tem prioridade, se funcionar.
     GBOC_PYTHON_CANDIDATES (caminhos separados por ";") acrescenta instalacoes fora do padrao.
  2. Procura TODOS os Python instalados: launcher "py -0p", registro (PythonCore), pastas padrao
     (Program Files, AppData, C:\PythonXY, C:\GBOC\Tools\Python*), ambientes venv do GBOC e o PATH.
  3. Usa a versao MAIS NOVA que ja tenha as dependencias do GBOC.
  4. Se existir uma versao mais nova sem as dependencias, instala o requirements.txt nela
     (pip). Deu certo: passa a usar a nova. Falhou (sem internet, pacote ainda sem suporte):
     continua na versao anterior e so tenta de novo depois de 24 h. A inicializacao nunca para
     por causa disso.
  5. A escolha fica em data\python_runtime.json e o historico em logs\python_runtime.log.

Uso:
  $py = & .\scripts\gboc_python.ps1 -Root C:\GBOC\Agent -Component agent
  for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\gboc_python.ps1 -Root "%~dp0." -Component agent`) do set "PYEXE=%%P"
#>
[CmdletBinding()]
param(
    [string]$Root = "",
    [ValidateSet("agent", "server", "scheduler")]
    [string]$Component = "agent",
    [switch]$NoInstall,
    [string]$MinVersion = "3.11"
)

$ErrorActionPreference = "Continue"
if (-not $Root) { $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
$Root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')

$Modules = @{
    agent     = "fastapi,uvicorn,hypercorn,psycopg2,cryptography,pydantic"
    scheduler = "fastapi,psycopg2,cryptography,pydantic"
    server    = "fastapi,uvicorn,hypercorn,psycopg2,cryptography,pydantic"
}[$Component]
$Requirements = Join-Path $Root "requirements.txt"
$DataDir = Join-Path $Root "data"
$LogDir = Join-Path $Root "logs"
$StateFile = Join-Path $DataDir "python_runtime.json"
$LogFile = Join-Path $LogDir "python_runtime.log"
$RetryHours = 24

function Write-Log([string]$Msg) {
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Component, $Msg
    try {
        if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
        Add-Content -Path $LogFile -Value $line -Encoding UTF8
    } catch {}
    [Console]::Error.WriteLine("[PYTHON] $Msg")
}

function Invoke-Exe([string]$Exe, [string]$Arguments, [int]$TimeoutSec = 30) {
    # Executa e devolve @{Code; Out; Err}. Nunca trava: mata o processo apos o tempo limite.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = $Arguments
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $Root
    $psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"
    try {
        $p = [System.Diagnostics.Process]::Start($psi)
    } catch {
        return @{ Code = -1; Out = ""; Err = $_.Exception.Message }
    }
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    if (-not $p.WaitForExit($TimeoutSec * 1000)) {
        try { $p.Kill() } catch {}
        return @{ Code = -2; Out = ""; Err = "tempo esgotado ($TimeoutSec s)" }
    }
    $p.WaitForExit()
    return @{ Code = $p.ExitCode; Out = $outTask.Result; Err = $errTask.Result }
}

function Get-PyVersion([string]$Exe) {
    # Versao e executavel real: atalhos (PyManager "python.exe") apontam para a versao padrao do momento,
    # que muda quando outra versao e instalada - usa-se sempre o python.exe real da instalacao
    $r = Invoke-Exe $Exe "-c `"import sys;print('%d.%d.%d' % sys.version_info[:3]);print(sys.executable)`"" 20
    if ($r.Code -ne 0) { return $null }
    $lines = @(($r.Out -split "`r?`n") | Where-Object { $_.Trim() })
    if ($lines.Count -lt 1 -or $lines[0] -notmatch '(\d+\.\d+\.\d+)') { return $null }
    $ver = [version]$Matches[1]
    $real = $Exe
    if ($lines.Count -ge 2) {
        $x = $lines[1].Trim()
        if ($x -and (Test-Path -LiteralPath $x)) { $real = (Resolve-Path -LiteralPath $x).Path }
    }
    return [pscustomobject]@{ Version = $ver; Real = $real }
}

function Get-Candidates {
    $paths = New-Object System.Collections.Generic.List[string]

    # 1. Launcher do Windows (lista todas as versoes registradas)
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $r = Invoke-Exe $pyLauncher.Source "-0p" 20
        foreach ($line in ($r.Out -split "`r?`n")) {
            if ($line -match '^\s*-\S+\s+(?:\*\s+)?(.+?\.exe)\s*$') { $paths.Add($Matches[1].Trim()) }
        }
    }

    # 2. Registro (instalacoes do python.org para todos os usuarios ou so para o usuario)
    foreach ($hive in @("HKLM:\SOFTWARE\Python\PythonCore", "HKCU:\SOFTWARE\Python\PythonCore",
                        "HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore")) {
        if (-not (Test-Path $hive)) { continue }
        foreach ($k in (Get-ChildItem $hive -ErrorAction SilentlyContinue)) {
            $ip = Join-Path $k.PSPath "InstallPath"
            if (-not (Test-Path $ip)) { continue }
            $props = Get-ItemProperty $ip -ErrorAction SilentlyContinue
            if ($props.ExecutablePath) { $paths.Add([string]$props.ExecutablePath) }
            elseif ($props.'(default)') { $paths.Add((Join-Path ([string]$props.'(default)') "python.exe")) }
        }
    }

    # 3. Pastas padrao e ambientes do GBOC
    $globs = @(
        "$env:ProgramFiles\Python3*\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:LOCALAPPDATA\Python\pythoncore-3*\python.exe",
        # Servico do Windows (LocalSystem): %LOCALAPPDATA% e o perfil do sistema; o Python instalado
        # "so para o usuario" fica no perfil de quem instalou e nao era encontrado (servico nao subia)
        "$env:SystemDrive\Users\*\AppData\Local\Programs\Python\Python3*\python.exe",
        "$env:SystemDrive\Users\*\AppData\Local\Python\pythoncore-3*\python.exe",
        "C:\Python3*\python.exe",
        "C:\GBOC\Tools\Python*\python.exe",
        "C:\GBOC\Tools\Python\*\python.exe"
    )
    foreach ($g in $globs) {
        foreach ($f in (Get-ChildItem -Path $g -ErrorAction SilentlyContinue)) { $paths.Add($f.FullName) }
    }
    $parent = Split-Path -Parent $Root
    foreach ($v in @("$Root\venv", "$Root\.venv", "$parent\venv", "$parent\.venv")) {
        $vp = Join-Path $v "Scripts\python.exe"
        if (Test-Path $vp) { $paths.Add($vp) }
    }

    # 4. PATH
    foreach ($c in (Get-Command python.exe -All -ErrorAction SilentlyContinue)) { $paths.Add($c.Source) }

    # 5. Caminhos extras (instalacoes fora do padrao), separados por ";"
    if ($env:GBOC_PYTHON_CANDIDATES) {
        foreach ($x in ($env:GBOC_PYTHON_CANDIDATES -split ';')) { if ($x.Trim()) { $paths.Add($x.Trim()) } }
    }

    $seen = @{}
    $list = @()
    foreach ($p in $paths) {
        if (-not $p) { continue }
        if ($p -match '\\WindowsApps\\') { continue }            # atalho da Microsoft Store
        if ((Split-Path -Leaf $p) -notmatch '^python(\.exe)?$') { continue }   # ignora python3.14t.exe etc.
        if (-not (Test-Path -LiteralPath $p)) { continue }
        $full = (Resolve-Path -LiteralPath $p).Path
        $key = $full.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $info = Get-PyVersion $full
        if (-not $info -or $info.Version -lt [version]$MinVersion) { continue }
        $ver = $info.Version
        $full = $info.Real                                       # atalho -> python.exe real
        $rkey = "real:" + $full.ToLowerInvariant()
        if ($seen.ContainsKey($rkey)) { continue }
        $seen[$rkey] = $true
        $list += [pscustomobject]@{ Path = $full; Version = $ver; Venv = ($full -match '\\\.?venv\\') }
    }
    # Mais nova primeiro; na mesma versao, o venv do GBOC primeiro (foi onde o instalador colocou as dependencias)
    return @($list | Sort-Object @{ Expression = { $_.Version }; Descending = $true }, @{ Expression = { $_.Venv }; Descending = $true })
}

function Test-Deps([string]$Exe) {
    $r = Invoke-Exe $Exe "-c `"import $Modules`"" 90
    return ($r.Code -eq 0)
}

function Read-State {
    if (Test-Path $StateFile) {
        try { return (Get-Content $StateFile -Raw | ConvertFrom-Json) } catch {}
    }
    return $null
}

function Save-State($chosen, $failed) {
    try {
        if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir -Force | Out-Null }
        $obj = [ordered]@{
            path       = $chosen.Path
            version    = $chosen.Version.ToString()
            component  = $Component
            checked_at = (Get-Date).ToString("s")
            failed     = $failed
        }
        ($obj | ConvertTo-Json -Depth 4) | Set-Content -Path $StateFile -Encoding UTF8
    } catch {}
}

function Install-Deps($cand) {
    if (-not (Test-Path $Requirements)) { return $false }
    Write-Log "Instalando dependencias no Python $($cand.Version) ($($cand.Path)) - pode levar alguns minutos..."
    $r = Invoke-Exe $cand.Path "-m pip install --disable-pip-version-check -q -r `"$Requirements`"" 1800
    if ($r.Code -ne 0) {
        $tail = (($r.Err + "`n" + $r.Out) -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 3) -join " | "
        Write-Log "Falhou a instalacao das dependencias no Python $($cand.Version): $tail"
        return $false
    }
    return (Test-Deps $cand.Path)
}

# ---------------------------------------------------------------------------------------------
# 1. Caminho fixado pelo administrador
if ($env:GBOC_PYTHON -and (Test-Path -LiteralPath $env:GBOC_PYTHON)) {
    if (Test-Deps $env:GBOC_PYTHON) {
        Write-Output (Resolve-Path -LiteralPath $env:GBOC_PYTHON).Path
        exit 0
    }
    Write-Log "GBOC_PYTHON=$env:GBOC_PYTHON nao tem as dependencias; procurando outro Python"
}

$state = Read-State
$failed = @{}
if ($state -and $state.failed) {
    foreach ($p in $state.failed.PSObject.Properties) {
        $v = 0L
        if ([int64]::TryParse([string]$p.Value, [ref]$v)) { $failed[$p.Name] = $v }   # segundos desde 1970 (UTC)
    }
}

$cands = Get-Candidates
if (-not $cands -or $cands.Count -eq 0) {
    Write-Log "Nenhum Python $MinVersion+ encontrado. Instale o Python (python.org) e execute o instalador do GBOC."
    exit 1
}

$chosen = $null
$newest = $cands[0]
foreach ($c in $cands) {
    if (Test-Deps $c.Path) { $chosen = $c; break }
}

# Existe Python mais novo que o escolhido (ou nenhum tem as dependencias): instala nele
if (-not $NoInstall -and ((-not $chosen) -or ($newest.Version -gt $chosen.Version))) {
    $key = "$($newest.Path)|$($newest.Version)"
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $lastFail = 0L
    if ($failed.ContainsKey($key)) { $lastFail = [int64]$failed[$key] }
    if ((-not $chosen) -or ($lastFail -eq 0) -or (($now - $lastFail) / 3600) -ge $RetryHours) {
        if (Install-Deps $newest) {
            Write-Log "Python $($newest.Version) pronto (dependencias instaladas)"
            $chosen = $newest
            $failed.Remove($key)
        } else {
            $failed[$key] = $now
            if ($chosen) { Write-Log "Continuando no Python $($chosen.Version); nova tentativa no $($newest.Version) em $RetryHours h" }
        }
    }
}

if (-not $chosen) {
    Write-Log "Nenhum Python com as dependencias do GBOC ($Modules). Execute o instalador ou: python -m pip install -r requirements.txt"
    exit 1
}

if (-not $state -or $state.path -ne $chosen.Path -or $state.version -ne $chosen.Version.ToString()) {
    $prev = if ($state -and $state.path) { "$($state.version) ($($state.path))" } else { "nenhum" }
    Write-Log "Usando Python $($chosen.Version): $($chosen.Path) (antes: $prev)"
}
Save-State $chosen $failed
Write-Output $chosen.Path
exit 0
