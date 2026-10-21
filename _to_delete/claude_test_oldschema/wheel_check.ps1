$py = 'C:\Users\Administrador\AppData\Local\Programs\Python\Python315\python.exe'
$d = 'D:\GBOC-New\GBOC-New\_to_delete\claude_test_oldschema\wheels315'
New-Item -ItemType Directory $d -Force | Out-Null
& $py --version
foreach ($req in @('D:\GBOC-New\GBOC-New\GBOC-Server\requirements.txt','D:\GBOC-New\GBOC-New\GBOC-Agent\requirements.txt','D:\GBOC-New\GBOC-New\GBOC-Agent\requirements-optional.txt')) {
  "== $req"
  foreach ($line in (Get-Content $req)) {
    $p = $line.Trim(); if (-not $p -or $p.StartsWith('#')) { continue }
    $o = & $py -m pip download --no-deps --only-binary=:all: -q -d $d $p 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { "FALHA  $p :: " + (($o -split "`n" | ? { $_ -match 'ERROR' } | Select -First 1)) } else { "ok     $p" }
  }
}
"== versoes mais novas:"
foreach ($p in 'pydantic','pydantic-core','pyyaml','zstandard') { & $py -m pip index versions $p 2>$null | Select -First 1 }
