"""Varredura de padroes de defeito no GBOC-Agent."""
import ast, os, re, sys, json
ROOT = sys.argv[1]
SUB = {"run", "Popen", "call", "check_call", "check_output"}
SUCCESS = re.compile(r"sucesso|success|✅|🎉|concluíd|concluid|validad", re.I)
findings = {"unchecked_success": [], "fake_progress": [], "random": [], "english_parse": [], "ps_inject": [], "text_console": [], "fixed_success": []}

def src(node, lines):
    return "\n".join(lines[node.lineno - 1: getattr(node, "end_lineno", node.lineno)])

for dp, dn, fn in os.walk(ROOT):
    if "__pycache__" in dp or "_to_delete" in dp or "tests" in dp.split(os.sep): continue
    for f in fn:
        if not f.endswith(".py"): continue
        p = os.path.join(dp, f); rel = os.path.relpath(p, ROOT)
        try:
            text = open(p, encoding="utf-8", errors="replace").read(); tree = ast.parse(text)
        except Exception: continue
        lines = text.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
            body = src(node, lines)
            calls = [c for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in SUB
                     and isinstance(c.func.value, ast.Name) and c.func.value.id == "subprocess"]
            if calls:
                checked = ("returncode" in body) or ("check=True" in body) or ("check_output" in body) or ("check_call" in body)
                if not checked and SUCCESS.search(body):
                    findings["unchecked_success"].append(f"{rel}:{node.lineno} {node.name}")
                for c in calls:
                    seg = src(c, lines)
                    if ("text=True" in seg or "universal_newlines" in seg) and "encoding" not in seg and re.search(r"vssadmin|wmic|netsh|sc\b|\"sc\"|'sc'|ipconfig|systeminfo|bcdedit|reg\b|schtasks|tasklist|manage-bde|fsutil|wbadmin|dism|ntdsutil|icacls|net\b|\"net\"", seg):
                        findings["text_console"].append(f"{rel}:{c.lineno} {node.name}: {seg.strip().splitlines()[0][:120]}")
            if re.search(r"time\.sleep\(", body) and re.search(r"\[[\"']progress[\"']\]\s*=|progress\s*=\s*", body) and not calls and "poll()" not in body:
                findings["fake_progress"].append(f"{rel}:{node.lineno} {node.name}")
            if re.search(r"\brandom\.(randint|random|uniform|choice|gauss)\(", body):
                findings["random"].append(f"{rel}:{node.lineno} {node.name}")
            for m in re.finditer(r"startswith\([\"'](Writer name|State|Last error|Status|STATE|SERVICE_NAME|Default Gateway|Physical Address|IPv4 Address|Name|Description)\b|[\"'](Writer name|Last error|Physical Address|IPv4 Address|Default Gateway|Total Physical Memory|OS Name)[\"'] in ", body):
                findings["english_parse"].append(f"{rel}:{node.lineno} {node.name}: {m.group(0)[:60]}")
                break
            # PowerShell em f-string com parametro da funcao entre aspas simples
            params = {a.arg for a in node.args.args} - {"self", "cls"}
            for js in [n for n in ast.walk(node) if isinstance(n, ast.JoinedStr)]:
                seg = src(js, lines)
                if re.search(r"Get-|New-|Set-|Remove-|Start-|Stop-|Invoke-|\$ErrorActionPreference", seg):
                    used = {v.value.id for v in ast.walk(js) if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name)}
                    hit = used & params
                    if hit and re.search(r"'\{(" + "|".join(hit) + r")[^}]*\}'", seg):
                        findings["ps_inject"].append(f"{rel}:{js.lineno} {node.name}: {sorted(hit)}")
                        break
            # retorno de sucesso fixo dentro de except
            for h in [n for n in ast.walk(node) if isinstance(n, ast.ExceptHandler)]:
                hs = src(h, lines)
                if re.search(r"return\s*\{[^}]*[\"'](status|success)[\"']\s*:\s*(True|[\"']success[\"'])", hs):
                    findings["fixed_success"].append(f"{rel}:{h.lineno} {node.name}")
                    break
json.dump(findings, open(os.path.join(os.path.dirname(__file__), "scan.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for k, v in findings.items(): print(k, len(v))
