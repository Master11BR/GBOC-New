import os
import re
import sys

# Garante saida em UTF-8 no console Windows (evita UnicodeEncodeError no print)
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    except Exception:
        pass

TARGET_VER = "15.0.0"

folders = [r"GBOC-Agent\static", r"GBOC-Agent\modules", r"GBOC-Server"]
updated_files = []
standalone_pages = []
fragment_templates = []

STANDARD_HEAD_INJECTIONS = f"""    <link rel="stylesheet" href="/static/vendor/fontawesome/css/all.min.css">
    <link rel="stylesheet" href="/static/ui/design-system/tokens.css?v={TARGET_VER}">
    <link rel="stylesheet" href="/static/ui/design-system/unocss-ds.css?v={TARGET_VER}">
    <link rel="stylesheet" href="/static/ui/models/modern/model.css?v={TARGET_VER}">
    <link rel="stylesheet" href="/static/ui/models/modern/components.css?v={TARGET_VER}">
    <link rel="stylesheet" href="/static/ui/models/modern/layout.css?v={TARGET_VER}">
    <link rel="stylesheet" href="/static/style.css?v={TARGET_VER}">
    <link rel="stylesheet" href="/static/gboc-themes.css?v={TARGET_VER}">
    <link rel="stylesheet" href="/static/gboc-layout.css?v={TARGET_VER}">
    <link rel="stylesheet" href="/static/ui/react/gboc-react.css?v={TARGET_VER}">
    <script src="/static/gboc-perf.js?v={TARGET_VER}"></script>
    <script src="/static/gboc-layout-manager.js?v={TARGET_VER}"></script>
    <script src="/static/gboc-modal.js?v={TARGET_VER}"></script>
    <script src="/static/ui/react/gboc-react-core.js?v={TARGET_VER}"></script>
    <script src="/static/ui/react/gboc-react-components.js?v={TARGET_VER}" defer></script>"""

for folder in folders:
    for root, dirs, files in os.walk(folder):
        # Evita varrer pastas de dados ou backups
        dirs[:] = [d for d in dirs if d not in ("repositorios", "data", "logs", "vendor", "__pycache__", "_bkp_obsoletos")]
        for f in files:
            if f.endswith(".html"):
                p = os.path.join(root, f)
                with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                    content = fp.read()

                original_content = content

                # Remove links bloqueantes de Google Fonts externos (Air-Gapped First Paint Optimization)
                content = re.sub(
                    r'\s*<link[^>]*href=[\'"][^\'"]*fonts\.(?:googleapis|gstatic)\.com[^\'"]*[\'"][^>]*>',
                    '',
                    content,
                    flags=re.IGNORECASE,
                )

                # Check if this is a standalone HTML page with <head>
                if "<head>" in content and "</head>" in content and not f.startswith("_"):
                    standalone_pages.append(p)

                    # Bump any old cache-busting versions to TARGET_VER
                    content = re.sub(
                        r'(\/static\/[^"\'>\s]+\.(?:css|js))\?v=[0-9.]+',
                        rf'\1?v={TARGET_VER}',
                        content,
                    )
                    head_part = content[content.find("<head>"):content.find("</head>")]

                    has_style = "style.css" in head_part
                    has_themes = "gboc-themes.css" in head_part
                    has_layout = "gboc-layout.css" in head_part
                    has_fa = "/static/vendor/fontawesome/css/all.min.css" in head_part
                    has_layout_mgr = "gboc-layout-manager.js" in head_part
                    has_modal = "gboc-modal.js" in head_part
                    has_perf = "gboc-perf.js" in head_part
                    has_tokens = "tokens.css" in head_part
                    has_unocss = "unocss-ds.css" in head_part
                    has_model = "/modern/model.css" in head_part
                    has_components = "/modern/components.css" in head_part
                    has_modern_layout = "/modern/layout.css" in head_part
                    has_react_core = "gboc-react-core.js" in head_part
                    has_react_comp = "gboc-react-components.js" in head_part
                    has_react_css = "gboc-react.css" in head_part

                    if not (
                        has_style and has_themes and has_layout and has_fa
                        and has_layout_mgr and has_modal and has_perf
                        and has_tokens and has_unocss and has_model
                        and has_components and has_modern_layout
                        and has_react_core and has_react_comp and has_react_css
                    ):
                        head_cleaned = head_part
                        for pattern in [
                            r'<link[^>]*href=[\'"][^\'"]*all\.min\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*style\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*gboc-themes\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*gboc-layout\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*gboc-react\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<script[^>]*src=[\'"][^\'"]*gboc-layout-manager\.js[^\'"]*[\'"][^>]*></script>\s*',
                            r'<script[^>]*src=[\'"][^\'"]*gboc-modal\.js[^\'"]*[\'"][^>]*></script>\s*',
                            r'<script[^>]*src=[\'"][^\'"]*gboc-perf\.js[^\'"]*[\'"][^>]*></script>\s*',
                            r'<script[^>]*src=[\'"][^\'"]*gboc-react-core\.js[^\'"]*[\'"][^>]*></script>\s*',
                            r'<script[^>]*src=[\'"][^\'"]*gboc-react-components\.js[^\'"]*[\'"][^>]*></script>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*tokens\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*unocss-ds\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*modern/model\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*modern/components\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*modern/layout\.css[^\'"]*[\'"][^>]*>\s*',
                        ]:
                            head_cleaned = re.sub(pattern, '', head_cleaned, flags=re.IGNORECASE)

                        if "<title>" in head_cleaned and "</title>" in head_cleaned:
                            head_cleaned = re.sub(
                                r'(</title>\s*)',
                                r'\1\n' + STANDARD_HEAD_INJECTIONS + '\n',
                                head_cleaned,
                                count=1,
                            )
                        else:
                            head_cleaned = head_cleaned.replace(
                                "<head>",
                                "<head>\n" + STANDARD_HEAD_INJECTIONS + "\n",
                            )

                        content = content[:content.find("<head>")] + head_cleaned + content[content.find("</head>"):]
                else:
                    fragment_templates.append(p)

                if content != original_content:
                    with open(p, "w", encoding="utf-8") as fp:
                        fp.write(content)
                    updated_files.append(p)

print("=== Auditoria e Padronizacao de Templates HTML (v15.0.0 + React 19) ===")
print(f"  Total de arquivos HTML verificados: {len(standalone_pages) + len(fragment_templates)}")
print(f"  Paginas completas padronizadas (com Universal CSS/JS + React 19 Head): {len(standalone_pages)}")
print(f"  Fragmentos e templates modulares injetados (isencao de <head>): {len(fragment_templates)}")
if updated_files:
    print(f"  Arquivos atualizados nesta execucao: {len(updated_files)}")
else:
    print("  [OK] Todas as paginas completas estao 100% em conformidade.")
