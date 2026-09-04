# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Root PowerShell Launcher: GBOC Scheduler Agent
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

[CmdletBinding()]
param (
    [switch]$Background
)

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AgentScript = Join-Path $RootDir "GBOC-Agent\start_scheduler.ps1"

if ($Background) {
    & $AgentScript -Background
} else {
    & $AgentScript
}
