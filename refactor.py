import os
import re

SERVER_PY = r"d:\GBOC-New\GBOC-New\GBOC-Server\gboc_server.py"
AGENT_PY = r"d:\GBOC-New\GBOC-New\GBOC-Agent\agent_server.py"
DASHBOARD_HTML = r"d:\GBOC-New\GBOC-New\GBOC-Server\dashboard.html"

def remove_html_routes(filepath):
    if not os.path.exists(filepath):
        print(f"Skipping {filepath}, not found.")
        return
        
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Regex patterns for HTML/JS/CSS static serving routes in FastAPI
    patterns = [
        r'@app\.get\("/static/.*?\n(?:@app\.get\(.*?\n)*async def .*?\(.*?\):\n(?: {4}.*\n)*',
        r'@app\.get\("/.*?\.(?:html|js|css)",.*?\n(?:@app\.get\(.*?\n)*async def .*?\(.*?\):\n(?: {4}.*\n)*',
        r'# Rota estática universal.*?\n@app\.get\("/static/.*?\nasync def serve_static_asset.*?\):\n(?: {4}.*\n)*',
        r'# Rota dinâmica universal.*?\n@app\.get\("/\{page_name:path\}\.html".*?\nasync def serve_any_html_page.*?\):\n(?: {4}.*\n)*',
        r'@app\.get\("/login\.html".*?\nasync def login_page.*?\):\n(?: {4}.*\n)*',
        r'@app\.get\("/"\)\nasync def index\(.*?\):\n(?: {4}.*\n)*'
    ]
    
    new_content = content
    for pattern in patterns:
        new_content = re.sub(pattern, '', new_content, flags=re.MULTILINE)
        
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Removed HTML routes from {filepath}")
    else:
        print(f"No routes to remove in {filepath} or regex failed")

def refactor_dashboard():
    if not os.path.exists(DASHBOARD_HTML):
        print("Dashboard not found.")
        return
        
    # Read dashboard HTML (could be UTF-16)
    try:
        with open(DASHBOARD_HTML, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(DASHBOARD_HTML, 'r', encoding='utf-16') as f:
            content = f.read()

    # We want to replace everything inside <main class="main-content"> ... </main>
    # with a dynamic loader container. But wait, the header and some other stuff is there.
    # We should just clear all <div class="tab-section" id="..."> except maybe overview?
    # Actually, if we clear them, we need to inject the fetch logic in switchTab.
    
    # 1. Replace switchTab
    old_switchTab = re.search(r'function switchTab\(id, btn\)\{(.*?)\}', content, flags=re.DOTALL)
    if old_switchTab:
        new_switchTab = """function switchTab(id, btn) {
            document.querySelectorAll('.sidebar .nav-link').forEach(l => l.classList.remove('active'));
            if (btn) btn.classList.add('active');
            
            const mainContainer = document.getElementById('dynamic-content-container');
            if (!mainContainer) return;
            
            mainContainer.innerHTML = '<div style="padding:40px; text-align:center; color:var(--text-muted)"><i class="fas fa-spinner fa-spin fa-3x"></i><br><br>Carregando módulo...</div>';
            
            // Tenta buscar da pasta modules
            fetch('/modules/' + id + '/' + id + '.html')
                .then(r => {
                    if (!r.ok) throw new Error('Módulo não encontrado: ' + id);
                    return r.text();
                })
                .then(html => {
                    mainContainer.innerHTML = html;
                    
                    // Remove script antigo se existir
                    const oldScript = document.getElementById('script-' + id);
                    if (oldScript) oldScript.remove();
                    
                    // Adiciona script dinâmico do módulo
                    const script = document.createElement('script');
                    script.id = 'script-' + id;
                    script.src = '/modules/' + id + '/' + id + '.js';
                    document.body.appendChild(script);
                })
                .catch(e => {
                    console.error(e);
                    // Se falhar, tenta procurar uma tab antiga ainda no DOM
                    const oldTab = document.getElementById('tab-' + id);
                    if (oldTab) {
                        document.querySelectorAll('.tab-section').forEach(s => s.classList.remove('active'));
                        oldTab.classList.add('active');
                        mainContainer.innerHTML = '';
                    } else {
                        mainContainer.innerHTML = '<div style="padding:40px; text-align:center; color:var(--danger)"><i class="fas fa-exclamation-triangle fa-3x"></i><br><br>Erro ao carregar o módulo: ' + id + '</div>';
                    }
                });
        }"""
        content = content.replace(old_switchTab.group(0), new_switchTab)
        
    # 2. Inject dynamic container after the header
    if '<div id="dynamic-content-container">' not in content:
        # Encontra o final do header
        header_end = content.find('</div>', content.find('<div class="header">')) + 6
        if header_end > 5:
            content = content[:header_end] + '\n            <div id="dynamic-content-container"></div>\n' + content[header_end:]
            
    # Save it back as UTF-8
    with open(DASHBOARD_HTML, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Refactored dashboard.html")

if __name__ == '__main__':
    remove_html_routes(SERVER_PY)
    remove_html_routes(AGENT_PY)
    refactor_dashboard()
