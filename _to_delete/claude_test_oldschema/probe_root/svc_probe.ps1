param([switch]$Service)
$out = 'D:\GBOC-New\GBOC-New\_to_delete\claude_test_oldschema\svc_probe_result.txt'
$l = @("whoami=$(whoami)")
$py = & "$PSScriptRoot\scripts\gboc_python.ps1" -Root $PSScriptRoot -Component agent -NoInstall 2>$null | Select-Object -Last 1
$l += "python=$py"
if ($py) {
  $l += (& $py -c "import sys; sys.path.insert(0, r'D:\GBOC-New\GBOC-New\GBOC-Agent'); from core.integrations.duplicati_native import _other_profile_duplicati_dbs as f; import os; p=os.path.expandvars(r'%LOCALAPPDATA%\Duplicati\Duplicati-server.sqlite'); print('dup_db_no_perfil_do_processo', os.path.isfile(p)); print('dup_db_outros_perfis', f([p]))" 2>&1)
}
$l | Out-File $out -Encoding utf8
Start-Sleep -Seconds 600
