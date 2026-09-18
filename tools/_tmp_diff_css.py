import os, re
from difflib import SequenceMatcher

a = r'GBOC-Server/style.css'
b = r'GBOC-Server/static/style.css'
c = r'GBOC-Agent/static/style.css'
with open(a,'rb') as fa, open(b,'rb') as fb, open(c,'rb') as fc:
    ca = fa.read()
    cb = fb.read()
    cc = fc.read()
print("=== style.css: Server/raiz vs Server/static vs Agent/static ===")
print(f"Server/raiz:   {len(ca):>7,} bytes ({ca.count(b'\n')} linhas)")
print(f"Server/static: {len(cb):>7,} bytes ({cb.count(b'\n')} linhas)")
print(f"Agent/static:  {len(cc):>7,} bytes ({cc.count(b'\n')} linhas)")
la = ca.decode('utf-8', errors='replace').splitlines()
lb = cb.decode('utf-8', errors='replace').splitlines()
lc = cc.decode('utf-8', errors='replace').splitlines()
print()
sm_ab = SequenceMatcher(None, la, lb).ratio() * 100
sm_ac = SequenceMatcher(None, la, lc).ratio() * 100
sm_bc = SequenceMatcher(None, lb, lc).ratio() * 100
print(f"Similaridade Server/raiz  vs Server/static: {sm_ab:.1f}%")
print(f"Similaridade Server/raiz  vs Agent/static:  {sm_ac:.1f}%")
print(f"Similaridade Server/static vs Agent/static: {sm_bc:.1f}%")
print()

def has_feature(lines, pat):
    return any(re.search(pat, l, re.I) for l in lines)

features = {
    "Sistema .modal/.modal-content/.modal-overlay": r'\.modal\b.*\{|\.modal-content|\.modal-overlay',
    ".gboc-topbar (Layout Manager moderno)": r'\.gboc-topbar\b',
    "gbocFadeIn / gbocModalScaleIn (anims)": r'gbocFadeIn|gbocModalScaleIn',
    "toast / toast_notifications": r'\.toast\b|\.gboc-toast',
    '[data-theme=neon]': r'\[data-theme="neon"\]',
    '[data-theme=unifi]': r'\[data-theme="unifi"\]',
    '[data-theme=contrast]': r'\[data-theme="contrast"\]',
    '[data-theme=bacula]': r'\[data-theme="bacula"\]',
    '[data-theme=fiorilli]': r'\[data-theme="fiorilli"\]',
}
print("=== Presenca de features por arquivo ===")
for name, pat in features.items():
    a_ok = "S" if has_feature(la, pat) else "N"
    b_ok = "S" if has_feature(lb, pat) else "N"
    c_ok = "S" if has_feature(lc, pat) else "N"
    print(f"  {a_ok} / {b_ok} / {c_ok}  {name}")
print("  ^ Srv/Raiz  ^ Srv/Static  ^ Agent")
