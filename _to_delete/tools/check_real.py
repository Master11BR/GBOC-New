import subprocess, json, sys
PY = sys.executable; T = r"D:\GBOC-New\GBOC-New\_to_delete\tools\api.py"
def call(u):
    o = subprocess.run([PY, T, "GET", u], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.splitlines()
    try: return json.loads(" ".join(o[1:]))
    except Exception: return {}
top = call("/api/v1/active-directory/topology"); t = top.get("topology", top)
print("AD:", {k: t.get(k) for k in ("is_domain_controller", "part_of_domain", "domain_name", "workgroup", "domain_role")})
h = call("/api/system/hardware")
txt = json.dumps(h, ensure_ascii=False)
import re
print("Discos:", re.findall(r'"name": "[^"]+", "media_type": "[^"]+", "bus_type": "[^"]+"', txt)[:3])
print("Temperatura:", sorted(set(re.findall(r'"temperature_status": "([^"]+)"', txt)))[:3])
d = call("/api/diagnostics/full")
txt = json.dumps(d, ensure_ascii=False)
print("Saude disco (diagnostico):", sorted(set(re.findall(r'"health_status": "([^"]+)"', txt)))[:4])
