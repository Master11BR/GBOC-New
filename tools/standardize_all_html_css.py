import os
import re

folders = [r"GBOC-Agent\static", r"GBOC-Server"]
updated_files = []

STANDARD_HEAD_INJECTIONS = """    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="/static/style.css?v=14.5.0">
    <link rel="stylesheet" href="/static/gboc-themes.css?v=14.5.0">
    <link rel="stylesheet" href="/static/gboc-layout.css?v=14.5.0">
    <script src="/static/gboc-layout-manager.js?v=14.5.0"></script>
    <script src="/static/gboc-modal.js?v=14.5.0"></script>"""

for folder in folders:
    for root, _, files in os.walk(folder):
        for f in files:
            if f.endswith(".html") and not f.startswith("_"):
                p = os.path.join(root, f)
                with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                    content = fp.read()
                
                original_content = content
                
                # Check if head exists
                if "<head>" in content and "</head>" in content:
                    head_part = content[content.find("<head>"):content.find("</head>")]
                    
                    has_style = "style.css" in head_part
                    has_themes = "gboc-themes.css" in head_part
                    has_layout = "gboc-layout.css" in head_part
                    has_fa = "font-awesome" in head_part or "all.min.css" in head_part
                    has_layout_mgr = "gboc-layout-manager.js" in head_part
                    has_modal = "gboc-modal.js" in head_part

                    # If missing any of the core universal CSS / scripts, harmonize head
                    if not (has_style and has_themes and has_layout and has_fa and has_layout_mgr and has_modal):
                        # Clean up partial versions
                        head_cleaned = head_part
                        # Remove existing occurrences of standard ones to re-add in clean standard order
                        for pattern in [
                            r'<link[^>]*href=[\'"][^\'"]*all\.min\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*style\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*gboc-themes\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<link[^>]*href=[\'"][^\'"]*gboc-layout\.css[^\'"]*[\'"][^>]*>\s*',
                            r'<script[^>]*src=[\'"][^\'"]*gboc-layout-manager\.js[^\'"]*[\'"][^>]*></script>\s*',
                            r'<script[^>]*src=[\'"][^\'"]*gboc-modal\.js[^\'"]*[\'"][^>]*></script>\s*'
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
                
                if content != original_content:
                    with open(p, "w", encoding="utf-8") as fp:
                        fp.write(content)
                    updated_files.append(p)

print(f"Total HTML files standardized with Universal CSS & Modal Framework: {len(updated_files)}")
for u in updated_files:
    print("  ✓", u)
