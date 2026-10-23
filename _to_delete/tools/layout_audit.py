"""Auditoria de layout das paginas do Agente (Edge headless). Uso: python layout_audit.py [pagina.html ...]"""
import sys, os, json, glob, time
sys.path.insert(0, r"D:\GBOC-New\GBOC-New\_to_delete\pwlib")
from playwright.sync_api import sync_playwright
ROOT = r"D:\GBOC-New\GBOC-New"; OUT = ROOT + r"\_to_delete\audit"
tok = open(ROOT + r"\_to_delete\tools\token.txt").read().strip()
pages = sys.argv[1:] or sorted(os.path.basename(p) for p in glob.glob(ROOT + r"\GBOC-Agent\static\*.html"))
skip = {"login.html", "index.html", "setup.html", "offline.html"}
JS = r"""
() => {
  const R = {hscroll: document.documentElement.scrollWidth > innerWidth + 2, sparse: [], overflow: [], overlap: [], nested: [], wrapBtn: [], tallEmpty: []};
  const vis = e => { const s = getComputedStyle(e); const r = e.getBoundingClientRect(); return s.display!=='none' && s.visibility!=='hidden' && r.width>0 && r.height>0; };
  const name = e => (e.id ? '#'+e.id : '') + '.' + [...e.classList].slice(0,2).join('.') + ' "' + (e.innerText||'').trim().slice(0,40).replace(/\s+/g,' ') + '"';
  const CARD = '.stat-card,.kpi-card,.metric-card,.card,.panel,.dashboard-card,.info-card,.summary-card';
  document.querySelectorAll(CARD).forEach(c => {
    if (!vis(c)) return;
    const r = c.getBoundingClientRect();
    // espaco vazio: altura muito maior que o conteudo
    let maxB = r.top, minT = r.bottom, n = 0;
    c.querySelectorAll('*').forEach(k => { if (!vis(k) || k.children.length) return; const kr = k.getBoundingClientRect(); if (kr.height < 2) return; n++; maxB = Math.max(maxB, kr.bottom); minT = Math.min(minT, kr.top); });
    const used = n ? (maxB - minT) : 0;
    if (r.height > 110 && n && used / r.height < 0.45 && c.matches('.stat-card,.kpi-card,.metric-card,.summary-card,.info-card'))
      R.sparse.push(`${name(c)} h=${Math.round(r.height)} conteudo=${Math.round(used)}`);
    if (c.parentElement && c.parentElement.closest(CARD) && c.matches('.panel,.card') && c.parentElement.closest('.panel,.card'))
      R.nested.push(name(c));
  });
  // texto cortado/estourando
  document.querySelectorAll('body *').forEach(e => {
    if (!vis(e) || e.children.length > 3) return;
    const s = getComputedStyle(e);
    if (['auto','scroll'].includes(s.overflowX) || e.tagName==='PRE' || e.tagName==='TEXTAREA' || e.tagName==='SELECT') return;
    const p = e.parentElement; if (!p) return;
    const r = e.getBoundingClientRect(), pr = p.getBoundingClientRect();
    if (s.overflow==='hidden' && s.textOverflow!=='ellipsis' && e.scrollWidth > e.clientWidth + 4 && e.innerText) R.overflow.push('cortado ' + name(e));
    else if (r.right > pr.right + 6 && getComputedStyle(p).overflowX==='visible' && r.width < innerWidth) R.overflow.push('estoura ' + name(e));
  });
  // irmaos sobrepostos dentro de grids/flex
  document.querySelectorAll('*').forEach(p => {
    const d = getComputedStyle(p).display; if (!/grid|flex/.test(d) || !vis(p)) return;
    const kids = [...p.children].filter(vis).filter(k => getComputedStyle(k).position==='static' || getComputedStyle(k).position==='relative');
    for (let i=0;i<kids.length;i++) for (let j=i+1;j<kids.length;j++){
      const a=kids[i].getBoundingClientRect(), b=kids[j].getBoundingClientRect();
      const ox=Math.min(a.right,b.right)-Math.max(a.left,b.left), oy=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top);
      if (ox>4 && oy>4) R.overlap.push(name(kids[i]) + ' x ' + name(kids[j]));
    }
  });
  document.querySelectorAll('button,.btn').forEach(b => { if (!vis(b)) return; const lh = parseFloat(getComputedStyle(b).lineHeight)||18; if ((b.innerText||'').trim() && b.getBoundingClientRect().height > lh*2.6 + 16) R.wrapBtn.push(name(b)); });
  for (const k of Object.keys(R)) if (Array.isArray(R[k])) R[k] = [...new Set(R[k])].slice(0, 8);
  return R;
}
"""
res = {}
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    for w, h in ((1600, 1000), (1280, 800)):
        ctx = b.new_context(viewport={"width": w, "height": h}, ignore_https_errors=True)
        ctx.add_cookies([{"name": "gboc_agent_token", "value": tok, "url": "https://127.0.0.1:9200"}])
        for pg in pages:
            if pg in skip: continue
            page = ctx.new_page(); errs = []
            page.on("pageerror", lambda e: errs.append(str(e)[:150]))
            try:
                page.goto(f"https://127.0.0.1:9200/{pg}", wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(4500)
                if "login" in page.url: res[pg] = {"login_redirect": True}; page.close(); continue
                r = page.evaluate(JS); r["jsErrors"] = errs[:4]
                if w == 1600: page.screenshot(path=f"{OUT}\\{pg[:-5]}.png", full_page=False)
                res.setdefault(pg, {})[str(w)] = {k: v for k, v in r.items() if v}
            except Exception as e:
                res.setdefault(pg, {})[str(w)] = {"erro": str(e)[:200]}
            page.close()
        ctx.close()
    b.close()
json.dump(res, open(OUT + r"\layout.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("paginas:", len(res))
