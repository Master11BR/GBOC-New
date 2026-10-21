$ErrorActionPreference = "Stop"
. 'D:\GBOC-New\GBOC-New\GBOC-Agent\scripts\gboc_prereqs.ps1'
$base = 'D:\GBOC-New\GBOC-New\_to_delete\claude_test_oldschema'
$py = 'C:\Users\Administrador\AppData\Local\Programs\Python\Python315\python.exe'
Remove-Item "$base\venv315" -Recurse -Force -ErrorAction SilentlyContinue
& $py -m venv "$base\venv315"
$vpy = "$base\venv315\Scripts\python.exe"
$t = Measure-Command { $ok = Install-GbocPipRequirements $vpy "$base\deps315\requirements-all.txt" -UpgradePip }
"resultado_instalacao=$ok em $([int]$t.TotalSeconds)s"
& $vpy -c "import sys,pydantic,pydantic_core,fastapi,yaml; print(sys.version.split()[0], 'pydantic', pydantic.VERSION, 'core', pydantic_core.__version__, 'fastapi', fastapi.__version__, 'yaml', yaml.__version__)"
& $vpy -c "import zstandard" 2>$null; "zstandard_opcional_instalado=$($LASTEXITCODE -eq 0)"
