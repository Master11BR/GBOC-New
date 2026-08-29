import os
import glob

def patch_fetches(directory, port):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.js') or file.endswith('.html'):
                filepath = os.path.join(root, file)
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    try:
                        with open(filepath, 'r', encoding='utf-16') as f:
                            content = f.read()
                    except:
                        continue
                        
                if "fetch('/api/" in content or "fetch(`/api/" in content or 'fetch("/api/' in content:
                    # Se não tem a definição, não precisamos injetar nela mesma, só substituir os fetch
                    content = content.replace("fetch('/api/v1", "fetch(window.GBOC_API_BASE + '/api/v1")
                    content = content.replace("fetch(`/api/v1", "fetch(window.GBOC_API_BASE + `/api/v1")
                    content = content.replace('fetch("/api/v1', 'fetch(window.GBOC_API_BASE + "/api/v1')
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content)
                    print(f"Patched {filepath}")

def inject_global_api(dashboard_path, port):
    if not os.path.exists(dashboard_path): return
    try:
        with open(dashboard_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except:
        with open(dashboard_path, 'r', encoding='utf-16') as f:
            content = f.read()
            
    if 'window.GBOC_API_BASE' not in content:
        static_port = '8080' if port == 8000 else '8081'
        injection = f"\n    <script>\n        window.GBOC_API_BASE = (window.location.protocol === 'https:' || window.location.port === '{static_port}' ? 'https:' : window.location.protocol) + '//' + window.location.hostname + ':' + (window.location.port === '{static_port}' ? '{port}' : (window.location.port || '{port}'));\n    </script>\n"
        content = content.replace('<head>', '<head>' + injection)
        
        # Corrige o const API se existir
        content = content.replace("const API = '/api/v1';", "const API = window.GBOC_API_BASE + '/api/v1';")
        content = content.replace("const API = window.location.protocol + '//' + window.location.hostname + ':8000/api/v1';", "const API = window.GBOC_API_BASE + '/api/v1';")
        
        with open(dashboard_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Injected global API into {dashboard_path}")

if __name__ == '__main__':
    # Server
    inject_global_api(r"d:\GBOC-New\GBOC-New\GBOC-Server\dashboard.html", 8000)
    patch_fetches(r"d:\GBOC-New\GBOC-New\GBOC-Server", 8000)
    
    # Agent
    inject_global_api(r"d:\GBOC-New\GBOC-New\GBOC-Agent\static\index.html", 9200)
    patch_fetches(r"d:\GBOC-New\GBOC-New\GBOC-Agent\static", 9200)
