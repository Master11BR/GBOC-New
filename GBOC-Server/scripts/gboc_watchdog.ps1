<#
==============================================================================
GBOC System - Vigia anti-travamento (servico GBOCWatchdog)
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
==============================================================================
Verifica a cada 20 s se o GBOC Agent e o GBOC Server respondem (/api/watchdog/ping).
Servico em execucao que nao responde 3 vezes seguidas (processo vivo, mas congelado) e reiniciado;
se o Windows nao conseguir para-lo, a arvore de processos e encerrada.

  * Servico parado pelo administrador: respeitado (o vigia so atua em servico "Running").
  * Carencia de 3 min apos cada inicio do servico (migracoes do banco na inicializacao).
  * No maximo 3 reinicios por hora por servico (evita reiniciar sem parar se o problema persistir).
  * Escrito em PowerShell, sem Python: continua funcionando mesmo se o Python do GBOC quebrar.
  * O proprio GBOC grava a pilha das threads do travamento em logs\hang_*.log (vigia interno).

Uso:  gboc_watchdog.ps1 -Service            (laco continuo, chamado pelo servico)
      gboc_watchdog.ps1 -Once               (uma verificacao, para teste)
      gboc_watchdog.ps1 -Targets "GBOCAgent=https://127.0.0.1:9200/api/watchdog/ping"
#>
[CmdletBinding()]
param(
    [switch]$Service,
    [switch]$Once,
    [string]$Targets = "",
    [int]$IntervalSec = 20,
    [int]$TimeoutSec = 15,
    [int]$FailLimit = 3,
    [int]$GraceSec = 180,
    [int]$MaxRestartsPerHour = 3,
    [string]$LogDir = ""
)

$ErrorActionPreference = "Continue"
if (-not $LogDir) { $LogDir = Join-Path (Split-Path -Parent $PSScriptRoot) "logs" }
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$LogFile = Join-Path $LogDir "watchdog.log"

# certificado autoassinado do Agente (HTTPS local)
if (-not ("GbocTrustAll" -as [type])) {
    Add-Type -TypeDefinition @"
using System.Net;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
public static class GbocTrustAll {
    public static bool Ok(object s, X509Certificate c, X509Chain ch, SslPolicyErrors e) { return true; }
    public static void Enable() { ServicePointManager.ServerCertificateValidationCallback = Ok; }
}
"@
}
[GbocTrustAll]::Enable()
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13

function Write-WLog([string]$Msg) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Msg
    try {
        if ((Test-Path $LogFile) -and (Get-Item $LogFile).Length -gt 5MB) { Move-Item $LogFile "$LogFile.1" -Force }
        Add-Content -Path $LogFile -Value $line -Encoding UTF8
    } catch {}
    Write-Host $line
}

function Get-ServiceEnvValue([string]$Name, [string]$Key) {
    # porta do servico: AppEnvironmentExtra do NSSM (gravado pelo instalador)
    try {
        $p = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\$Name\Parameters" -ErrorAction Stop
        foreach ($kv in @($p.AppEnvironmentExtra)) {
            if ("$kv" -match "^$Key=(.+)$") { return $Matches[1] }
        }
    } catch {}
    return $null
}

function Get-Targets {
    $list = @()
    if ($Targets) {
        foreach ($t in ($Targets -split ';')) {
            $kv = $t -split '=', 2
            if ($kv.Count -eq 2 -and $kv[0].Trim()) { $list += [pscustomobject]@{ Name = $kv[0].Trim(); Url = $kv[1].Trim() } }
        }
        return $list
    }
    if (Get-Service -Name "GBOCAgent" -ErrorAction SilentlyContinue) {
        $port = Get-ServiceEnvValue "GBOCAgent" "AGENT_PORT"; if (-not $port) { $port = 9200 }
        $list += [pscustomobject]@{ Name = "GBOCAgent"; Url = "https://127.0.0.1:$port/api/watchdog/ping" }
    }
    if (Get-Service -Name "GBOCServer" -ErrorAction SilentlyContinue) {
        $port = Get-ServiceEnvValue "GBOCServer" "SERVER_PORT"; if (-not $port) { $port = 8000 }
        $list += [pscustomobject]@{ Name = "GBOCServer"; Url = "http://127.0.0.1:$port/api/watchdog/ping" }
    }
    return $list
}

function Test-Alive([string]$Url) {
    # qualquer resposta HTTP (ate 401/404 de versao antiga) prova que o processo nao esta congelado
    try {
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.Timeout = $TimeoutSec * 1000
        $req.ReadWriteTimeout = $TimeoutSec * 1000
        $req.KeepAlive = $false
        $resp = $req.GetResponse()
        $resp.Close()
        return $true
    } catch [System.Net.WebException] {
        if ($_.Exception.Response) { $_.Exception.Response.Close(); return $true }
        return $false
    } catch {
        return $false
    }
}

function Get-ServicePid([string]$Name) {
    $s = Get-CimInstance Win32_Service -Filter "Name='$Name'" -ErrorAction SilentlyContinue
    if ($s) { return [int]$s.ProcessId }
    return 0
}

function Restart-Frozen([string]$Name) {
    $svcPid = Get-ServicePid $Name
    Write-WLog "[$Name] reiniciando (PID $svcPid)..."
    Stop-Service -Name $Name -Force -ErrorAction SilentlyContinue -NoWait
    for ($i = 0; $i -lt 30; $i++) {
        if ((Get-Service -Name $Name).Status -eq "Stopped") { break }
        Start-Sleep -Seconds 1
    }
    if ((Get-Service -Name $Name).Status -ne "Stopped") {
        $svcPid = Get-ServicePid $Name
        if ($svcPid -gt 0) {
            Write-WLog "[$Name] nao parou em 30 s: encerrando a arvore de processos (PID $svcPid)"
            & taskkill.exe /PID $svcPid /T /F *> $null
        }
        for ($i = 0; $i -lt 20; $i++) {
            if ((Get-Service -Name $Name).Status -eq "Stopped") { break }
            Start-Sleep -Seconds 1
        }
    }
    Start-Service -Name $Name -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    $st = (Get-Service -Name $Name).Status
    Write-WLog "[$Name] estado apos reinicio: $st (PID $(Get-ServicePid $Name))"
}

$fails = @{}
$restarts = @{}
Write-WLog "Vigia anti-travamento iniciado (intervalo $IntervalSec s, limite $FailLimit falhas, carencia $GraceSec s)"
while ($true) {
    foreach ($t in (Get-Targets)) {
        $n = $t.Name
        if (-not $fails.ContainsKey($n)) { $fails[$n] = 0; $restarts[$n] = @() }
        $svc = Get-Service -Name $n -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -ne "Running") { $fails[$n] = 0; continue }      # parado: decisao do admin / NSSM
        if ($svc) {
            $svcPid = Get-ServicePid $n
            $started = $null
            if ($svcPid -gt 0) { $started = (Get-Process -Id $svcPid -ErrorAction SilentlyContinue).StartTime }
            if ($started -and ((Get-Date) - $started).TotalSeconds -lt $GraceSec) { $fails[$n] = 0; continue }
        }
        if (Test-Alive $t.Url) {
            if ($fails[$n] -gt 0) { Write-WLog "[$n] voltou a responder" }
            $fails[$n] = 0
            continue
        }
        $fails[$n]++
        Write-WLog "[$n] sem resposta em $($t.Url) ($($fails[$n])/$FailLimit)"
        if ($fails[$n] -ge $FailLimit) {
            $fails[$n] = 0
            if (-not $svc) { Write-WLog "[$n] nao e um servico do Windows: nada a reiniciar"; continue }
            $recent = @($restarts[$n] | Where-Object { ((Get-Date) - $_).TotalMinutes -lt 60 })
            if ($recent.Count -ge $MaxRestartsPerHour) {
                Write-WLog "[$n] ja reiniciado $($recent.Count)x na ultima hora: aguardando (verifique logs\hang_*.log)"
                $restarts[$n] = $recent
                continue
            }
            Restart-Frozen $n
            $restarts[$n] = $recent + @(Get-Date)
        }
    }
    if ($Once -or -not $Service) { break }
    Start-Sleep -Seconds $IntervalSec
}
