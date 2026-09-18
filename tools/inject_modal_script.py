import os
import re

folders = [r"GBOC-Agent\static", r"GBOC-Server"]
patched = []

for folder in folders:
    for root, _, files in os.walk(folder):
        for f in files:
            if f.endswith(".html") and not f.startswith("_"):
                p = os.path.join(root, f)
                with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                    content = fp.read()
                if "gboc-modal.js" not in content:
                    if "gboc-layout-manager.js" in content:
                        new_content = re.sub(
                            r'(<script\s+src=[\'"][^\'"]*gboc-layout-manager\.js[^\'"]*[\'"]\s*></script>)',
                            r'\1\n    <script src="/static/gboc-modal.js"></script>',
                            content,
                            count=1
                        )
                    elif "</head>" in content:
                        new_content = content.replace("</head>", '    <script src="/static/gboc-modal.js"></script>\n</head>')
                    else:
                        continue
                    
                    if new_content != content:
                        with open(p, "w", encoding="utf-8") as fp:
                            fp.write(new_content)
                        patched.append(p)

print(f"Total de paginas HTML atualizadas com gboc-modal.js: {len(patched)}")
for item in patched:
    print(" +", item)
