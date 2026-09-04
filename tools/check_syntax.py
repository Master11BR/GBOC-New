from pathlib import Path

path = Path(r"d:\GBOC-New\GBOC-New\tools\installer_assets\Setup.ps1")
lines = path.read_text(encoding="utf-8").splitlines()

for idx, line in enumerate(lines, 1):
    # count non-escaped single quotes
    sq = line.count("'")
    dq = line.count('"')
    if "opcao" in line or "Instalando" in line or "Erro" in line or "test" in line:
        pass
    if line.strip().startswith("#"):
        continue
    # check for backticks
    if "`" in line:
        pass
print("Total lines:", len(lines))
