import subprocess, json, sys, time
PY = sys.executable; T = r"D:\GBOC-New\GBOC-New\_to_delete\tools\api.py"
def call(m, u, body=None):
    args = [PY, T, m, u, "9200"] + ([json.dumps(body)] if body is not None else [])
    o = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip().splitlines()
    code = o[0] if o else "?"; txt = " ".join(o[1:])
    try: data = json.loads(txt)
    except Exception: data = txt
    return code, data
def show(name, r, keys=None):
    code, d = r
    if isinstance(d, dict) and keys: d = {k: d.get(k) for k in keys}
    print(f"[{code}] {name}: {str(d)[:330]}")
show("healthcheck last_24h", call("GET", "/api/v1/system/health"), ["status", "last_24h"])
show("rmm servico inexistente", call("POST", "/api/v1/rmm/service/control", {"name": "GBOC_nao_existe", "action": "restart"}))
show("rmm injecao", call("POST", "/api/v1/rmm/service/control", {"name": "x'; Get-Date; '", "action": "restart"}))
show("cbt unidade invalida", call("POST", "/api/v1/cbt/vss-snapshot", {"drive": "C:'); Get-Date; ('"}))
show("bitrot 1a", call("POST", "/api/v1/power-tools/bitrot/scrub", {"target_path": r"D:\GBOC-New\GBOC-New\GBOC-Agent\repositorios"}), ["success", "files_scanned", "files_compared", "files_new_reference", "silent_corruptions"])
show("bitrot 2a", call("POST", "/api/v1/power-tools/bitrot/scrub", {"target_path": r"D:\GBOC-New\GBOC-New\GBOC-Agent\repositorios"}), ["success", "files_scanned", "files_compared", "files_new_reference", "silent_corruptions"])
show("virtual lab caminho invalido", call("POST", "/api/v1/dr/virtual-lab/test", {"snapshot_id": "abc", "vm_name": "t'x", "disk_path": "C:\\x'y.vhdx"}), ["success", "status", "error"])
show("virtual lab sem imagem", call("POST", "/api/v1/dr/virtual-lab/test", {"snapshot_id": "naoexiste123"}), ["success", "status", "error"])
show("cdp rollback", call("POST", "/api/v1/enterprise/cdp/rollback", {"checkpoint_id": "chk_1"}))
c, d = call("GET", "/api/v1/enterprise/compliance/certificate")
for ch in (d.get("certificate", {}).get("audit_checks", []) if isinstance(d, dict) else []):
    print(f"   laudo: {ch['status']:13} {ch['rule']} -> {ch['evidence'][:110]}")
c, d = call("GET", "/api/v1/active-directory/backup/history")
print("[%s] historico AD: %s" % (c, str(d)[:200]))
