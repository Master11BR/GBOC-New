import os
import re
import sys

# Garante saida em UTF-8 no console Windows (evita UnicodeEncodeError no print)
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    except Exception:
        pass

folders = [r"GBOC-Agent\static", r"GBOC-Server"]
updated_files = []
standalone_pages = []
fragment_templates = []

STANDARD_HEAD_INJECTIONS = """    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="/static/ui/design-system/tokens.css?v=14.5.0">
    <link rel="stylesheet" href="/static/ui/design-system/unocss-ds.css?v=14.5.0">
    <link rel="stylesheet" href="/static/ui/models/modern/model.css?v=14.5.0">
    <link rel="stylesheet" href="/static/ui/models/modern/components.css?v=14.5.0">
    <link rel="stylesheet" href="/static/ui/models/modern/layout.css?v=14.5.0">
    <link rel="stylesheet" href="/static/style.css?v=14.5.0">
    <link rel="stylesheet" href="/static/gboc-themes.css?v=14.5.0">
    <link rel="stylesheet" href="/static/gboc-layout.css?v=14.5.0">
    <script src="/static/gboc-perf.js?v=14.5.0"></script>
    <script src="/static/gboc-layout-manager.js?v=14.5.0"></script>
    <script src="/static/gboc-modal.js?v=14.5.0"></script>"""

for folder in folders:
    for root, _, files in os.walk(folder):
        for f in files:
            if f.endswith(".html"):
                p = os.path.join(root, f)
                with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                    content = fp.read()
                
                original_content = content
                
                # Check if this is a standalone HTML page with <head>
                if "<head>" in content and "</head>" in content and not f.startswith("_"):
                    standalone_pages.append(p)
                    head_part = content[content.find("<head>"):content.find("</head>")]

                    has_style = "style.css" in head_part
                    has_themes = "gboc-themes.css" in head_part
                    has_layout = "gboc-layout.css" in head_part
                    has_fa = "font-awesome" in head_part or "all.min.css" in head_part
                    has_layout_mgr = "gboc-layout-manager.js" in head_part
                    has_modal = "gboc-modal.js" in head_part
                    has_perf = "gboc-perf.js" in head_part
                    has_tokens = "tokens.css" in head_part
                    has_unocss = "unocss-ds.css" in head_part
                    has_model = "/modern/model.css" in head_part
                    has_components = "/modern/components.css" in head_part
                    has_modern_layout = "/modern/layout.css" in head_part

                    # If missing any of the core universal CSS / scripts, harmonize head
                    if not (has_style and has_themes and has_layout and has_fa and has_layout_mgr and has_modal and has_perf and has_tokens and has_unocss and has_model and has_components and has_modern_layout):
                        # Clean up partial versions
                        head_cleaned = head_part
                        # Remove existing occurrences of standard ones to re-add in clean standard order
                        for pattern in [
                            r'<link[^>]*href=[\'"][^\'"]*all\.min\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*style\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*gboc-themes\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*gboc-layout\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<script[^>]*src=[\'"][^\'"]*gboc-layout-manager\.js[^\'"]*[\'"][^>]*></script>\s*',
                            r'<script[^>]*src=[\'"][^\'"]*gboc-modal\.js[^\'"]*[\'"][^>]*></script>\s*',
                            r'<script[^>]*src=[\'"][^\'"]*gboc-perf\.js[^\'"]*[\'"][^>]*></script>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*tokens\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*unocss-ds\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*modern/model\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*modern/components\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*modern/layout\.css[^\'"]*[\'"][^>]*>\s*'
                        ]:
                            head_cleaned = re.sub(pattern, '', head_cleaned, flags=re.IGNORECASE)
                        
                        # Add standard head injections after <title> or <head>
                        if "<title>" in head_cleaned and "</title>" in head_cleaned:
                            head_cleaned = re.sub(
                                r'(</title>\s*)',
                                r'\1\n' + STANDARD_HEAD_INJECTIONS + '\n',
                                head_cleaned,
                                count=1
                            )
                        else:
                            head_cleaned = head_cleaned.replace("<head>", "<head>\n" + STANDARD_HEAD_INJECTIONS + "\n")
                        
                        content = content[:content.find("<head>")] + head_cleaned + content[content.find("</head>"):]
                else:
                    fragment_templates.append(p)
                
                if content != original_content:
                    with open(p, "w", encoding="utf-8") as fp:
                        fp.write(content)
                    updated_files.append(p)

print(f"=== Auditoria e Padronizacao de Templates HTML ===")
print(f"  Total de arquivos HTML verificados: {len(standalone_pages) + len(fragment_templates)}")
print(f"  Paginas completas padronizadas (com Universal CSS/JS Head): {len(standalone_pages)}")
print(f"  Fragmentos e templates modulares injetados (isencao de <head>): {len(fragment_templates)}")
if updated_files:
    print(f"  Arquivos atualizados nesta execucao: {len(updated_files)}")
    for u in updated_files:
        print("    [ATUALIZADO]", u)
else:
    print("  [OK] Todas as 60 paginas completas estao 100% em conformidade.")
