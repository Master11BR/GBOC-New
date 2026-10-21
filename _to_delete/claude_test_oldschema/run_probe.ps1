$ErrorActionPreference = "Stop"
. 'D:\GBOC-New\GBOC-New\GBOC-Agent\scripts\gboc_prereqs.ps1'
$base = 'D:\GBOC-New\GBOC-New\_to_delete\claude_test_oldschema'
Remove-Item "$base\svc_probe_result.txt" -ErrorAction SilentlyContinue
$ok = Register-GbocService -Name "GBOCProbeTest" -DisplayName "GBOC Probe (teste)" -Description "teste provisorio" `
  -Script "$base\probe_root\svc_probe.ps1" -ScriptArgs "-Service" -WorkDir "$base\probe_root" -LogDir "$base\probe_root\logs" `
  -ToolsDir "$base\Tools" -Environment @("AGENT_PORT=9299", "GBOC_TESTVAR=ok", "PYTHONIOENCODING=utf-8")
"register_result=$ok"
Get-CimInstance Win32_Service -Filter "Name='GBOCProbeTest'" | Select-Object Name, State, StartMode, StartName | Format-List | Out-String
& sc.exe qfailure GBOCProbeTest
for ($i=0; $i -lt 90 -and -not (Test-Path "$base\svc_probe_result.txt"); $i++) { Start-Sleep 1 }
Start-Sleep 2
"----- resultado gravado pelo servico:"
Get-Content "$base\svc_probe_result.txt" -ErrorAction SilentlyContinue
