"""python shot.py pagina.html largura [porta] [full] -> _to_delete/audit/shot_<pagina>_<largura>.png"""
import sys
sys.path.insert(0, r"D:\GBOC-New\GBOC-New\_to_delete\pwlib")
from playwright.sync_api import sync_playwright
pg, w = sys.argv[1], int(sys.argv[2]); port = sys.argv[3] if len(sys.argv) > 3 else "9200"
full = len(sys.argv) > 4 and sys.argv[4] == "full"
js = sys.argv[5] if len(sys.argv) > 5 else None
suffix = sys.argv[6] if len(sys.argv) > 6 else ""
tok = open(r"D:\GBOC-New\GBOC-New\_to_delete\tools\token.txt").read().strip()
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    c = b.new_context(viewport={"width": w, "height": 900}, ignore_https_errors=True)
    c.add_cookies([{"name": "gboc_agent_token", "value": tok, "url": f"https://127.0.0.1:{port}"}])
    page = c.new_page(); page.goto(f"https://127.0.0.1:{port}/{pg}", wait_until="domcontentloaded"); page.wait_for_timeout(5000)
    if js:
        page.evaluate(js); page.wait_for_timeout(4000)
    out = rf"D:\GBOC-New\GBOC-New\_to_delete\audit\shot_{pg[:-5]}{suffix}_{w}.png"; page.screenshot(path=out, full_page=full); print(out)
    b.close()
