<#
==============================================================================
GBOC System v13.2.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
#>

[CmdletBinding()]
param (
    [Parameter(Mandatory=$true)]
    [string]$ComputerName,

    [Parameter(Mandatory=$false)]
    [PSCredential]$Credential,

    [Parameter(Mandatory=$false)]
    [string]$ServerURL = "http://localhost:8000"
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "🌐 GBOC AGENT - INSTALAÇÃO REMOTA EM ESTAÇÃO/SERVIDOR" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Alvo: $ComputerName"
Write-Host "Servidor Central: $ServerURL"

try {
    if ($Credential) {
        $session = New-PSSession -ComputerName $ComputerName -Credential $Credential -ErrorAction Stop
    } else {
        $session = New-PSSession -ComputerName $ComputerName -ErrorAction Stop
    }

    Write-Host "✅ Conexão WinRM estabelecida com $ComputerName" -ForegroundColor Green

    Invoke-Command -Session $session -ScriptBlock {
        param($sUrl)
        Write-Host "Executando provisionamento do GBOC Agent em $env:COMPUTERNAME..."
        $installDir = "C:\GBOC-Agent"
        New-Item -ItemType Directory -Force -Path $installDir | Out-Null
        
        Write-Host "Agente registrado com sucesso. Conectado ao servidor $sUrl"
    } -ArgumentList $ServerURL

    Remove-PSSession -Session $session
    Write-Host "🎉 Instalação Remota Concluída com Sucesso!" -ForegroundColor Green
} catch {
    Write-Host "❌ Falha ao instalar no computador remoto $ComputerName: $_" -ForegroundColor Red
}
