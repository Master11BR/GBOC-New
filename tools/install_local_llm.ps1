<#
==============================================================================
GBOC System v14.8.2 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
==============================================================================
Instalador e Integrador Automatizado de LLM Gratuito e Local (Ollama)
Configura motor de inteligência artificial 100% privado, offline e gratuito
para diagnósticos preditivos, auto-reparo e assistente Copilot do GBOC.
==============================================================================
Uso:
    powershell -ExecutionPolicy Bypass -File tools\install_local_llm.ps1
    powershell -ExecutionPolicy Bypass -File tools\install_local_llm.ps1 -Model "qwen3.5:4b" -InstallRoot "C:\GBOC"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Model = "qwen3.5:4b",

    [Parameter(Mandatory = $false)]
    [string]$InstallRoot = "C:\GBOC",

    [Parameter(Mandatory = $false)]
    [switch]$Unattended
)

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "     GBOC SYSTEM - INSTALADOR DE IA / LLM LOCAL GRATUITO         " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "Motor: Ollama (100% gratuito, local, privado e sem nuvem)" -ForegroundColor White
Write-Host "Modelo recomendado: $Model" -ForegroundColor White
Write-Host "Destino GBOC: $InstallRoot" -ForegroundColor White
Write-Host ""

# Importa funcoes auxiliares de prereqs se disponivel
$prereqsScript = @(
    (Join-Path $PSScriptRoot "..\GBOC-Agent\scripts\gboc_prereqs.ps1"),
    (Join-Path $PSScriptRoot "..\GBOC-Server\scripts\gboc_prereqs.ps1"),
    "C:\GBOC\Agent\scripts\gboc_prereqs.ps1",
    "C:\GBOC\Server\scripts\gboc_prereqs.ps1"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($prereqsScript) {
    . $prereqsScript
    $res = Install-GbocOllama -Model $Model -InstallRoot $InstallRoot
} else {
    Write-Host "[!] Script gboc_prereqs.ps1 nao encontrado no caminho relativo. Executando rotina autonoma..." -ForegroundColor Yellow

    function Find-Ollama {
        $c = Get-Command ollama.exe -ErrorAction SilentlyContinue
        if ($c) { return $c.Source }
        foreach ($p in @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe", "$env:ProgramFiles\Ollama\ollama.exe")) {
            if (Test-Path $p) { return $p }
        }
        return $null
    }

    $ollamaExe = Find-Ollama
    if (-not $ollamaExe) {
        Write-Host "==> Baixando e instalando Ollama para Windows..." -ForegroundColor Cyan
        $setupUrl = "https://ollama.com/download/OllamaSetup.exe"
        $tmp = Join-Path ([System.IO.Path]::GetTempPath()) "OllamaSetup.exe"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($setupUrl, $tmp)
        if (Test-Path $tmp) {
            Start-Process -FilePath $tmp -ArgumentList "/silent" -Wait
            Start-Sleep -Seconds 3
            Remove-Item $tmp -Force -ErrorAction SilentlyContinue
            $ollamaExe = Find-Ollama
        }
    }

    if ($ollamaExe) {
        Write-Host "    [OK] Ollama operacional: $ollamaExe" -ForegroundColor Green
        # Iniciar daemon se inativo
        try {
            $test = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        } catch {
            Write-Host "==> Iniciando servico do Ollama em segundo plano..." -ForegroundColor Cyan
            Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
            Start-Sleep -Seconds 5
        }

        # Baixar modelo
        Write-Host "==> Baixando modelo gratuito '$Model'..." -ForegroundColor Cyan
        & $ollamaExe pull $Model

        # Configurar GBOC
        $aiCfg = @{
            provider      = "ollama"
            ollama_url    = "http://localhost:11434"
            ollama_host   = "http://localhost:11434"
            ollama_model  = $Model
            model         = $Model
            system_prompt = "Você é o GBOC Copilot AI, especialista em backup, recuperação de desastres, virtualização e administração do GBOC Enterprise."
        }
        $json = $aiCfg | ConvertTo-Json -Depth 4
        foreach ($d in @("$InstallRoot\Server\data", "$InstallRoot\Agent\data")) {
            if (Test-Path (Split-Path -Parent $d)) {
                New-Item -ItemType Directory -Path $d -Force | Out-Null
                Set-Content -Path (Join-Path $d "server_ai_config.json") -Value $json -Encoding UTF8
                Set-Content -Path (Join-Path $d "ai_config.json") -Value $json -Encoding UTF8
            }
        }
        Write-Host "    [OK] Integracao com GBOC concluida com sucesso!" -ForegroundColor Green
    } else {
        Write-Host "    [ERRO] Falha ao localizar ou instalar Ollama." -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "             CONCLUSAO DA CONFIGURACAO DE IA                     " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "Status: IA Local Gratuita integrada ao GBOC Enterprise." -ForegroundColor Green
Write-Host "Endpoint: http://localhost:11434" -ForegroundColor White
Write-Host "Modelo ativo: $Model" -ForegroundColor White
Write-Host ""
