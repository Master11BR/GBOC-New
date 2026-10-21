$files = @('D:\GBOC-New\GBOC-New\tools\installer_assets\Setup.ps1','D:\GBOC-New\GBOC-New\GBOC-Agent\scripts\gboc_prereqs.ps1','D:\GBOC-New\GBOC-New\GBOC-Server\scripts\gboc_prereqs.ps1')
foreach ($f in $files) {
  $t = $null; $e = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$t, [ref]$e)
  "{0} PS{1}: {2} erro(s)" -f (Split-Path $f -Leaf), $PSVersionTable.PSVersion.Major, $e.Count
  $e | Select-Object -First 5 | ForEach-Object { "   L$($_.Extent.StartLineNumber): $($_.Message)" }
}
