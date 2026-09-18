import os
import re
from collections import defaultdict

html_files = []
for folder in [r"GBOC-Agent\static", r"GBOC-Server"]:
    for root, _, files in os.walk(folder):
        for f in files:
            if f.endswith(".html"):
                html_files.append(os.path.join(root, f))

css_links_per_file = {}
style_blocks_per_file = {}
missing_standard_css = defaultdict(list)

for p in html_files:
    with open(p, "r", encoding="utf-8", errors="ignore") as fp:
        content = fp.read()
    
    links1 = re.findall(r'<link[^>]*rel=[\'"]stylesheet[\'"][^>]*href=[\'"]([^\'"]+)[\'"]', content, re.IGNORECASE)
    links2 = re.findall(r'<link[^>]*href=[\'"]([^\'"]+)[\'"][^>]*rel=[\'"]stylesheet[\'"]', content, re.IGNORECASE)
    links = links1 + links2
    
    styles = re.findall(r'<style[^>]*>(.*?)</style>', content, re.IGNORECASE | re.DOTALL)
    
    css_links_per_file[p] = links
    if styles:
        total_style_len = sum(len(s.strip()) for s in styles)
        style_blocks_per_file[p] = (len(styles), total_style_len)
    
    # Check standard CSS files
    has_layout = any("gboc-layout.css" in l for l in links)
    has_themes = any("gboc-themes.css" in l for l in links)
    has_style = any("style.css" in l for l in links)
    has_fa = any("font-awesome" in l or "all.min.css" in l for l in links)

    if not has_layout: missing_standard_css["missing_gboc_layout"].append(p)
    if not has_themes: missing_standard_css["missing_gboc_themes"].append(p)
    if not has_style: missing_standard_css["missing_style_css"].append(p)
    if not has_fa: missing_standard_css["missing_fontawesome"].append(p)

print(f"Total HTML files analyzed: {len(html_files)}")
all_links = set(l for links in css_links_per_file.values() for l in links)
print("\nDistinct CSS link targets found in codebase:")
for l in sorted(all_links):
    print("  *", l)

print("\nMissing Standard CSS counts:")
for k, v in missing_standard_css.items():
    print(f"  {k}: {len(v)} files")

print("\nTop 20 HTML files with largest <style> blocks:")
for p, (cnt, sz) in sorted(style_blocks_per_file.items(), key=lambda x: x[1][1], reverse=True)[:20]:
    print(f"  {sz:6d} bytes ({cnt} blocks): {p}")
