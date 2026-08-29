import os
import re

DASHBOARD_PATH = r"d:\GBOC-New\GBOC-New\GBOC-Server\dashboard.html"
SIDEBAR_PATH = r"d:\GBOC-New\GBOC-New\GBOC-Server\_sidebar.html"

def extract_sidebar():
    if not os.path.exists(DASHBOARD_PATH):
        print("dashboard.html not found.")
        return

    try:
        with open(DASHBOARD_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(DASHBOARD_PATH, 'r', encoding='utf-16') as f:
            content = f.read()

    # Find <aside class="sidebar"> ... </aside>
    sidebar_match = re.search(r'(<aside class="sidebar">.*?</aside>)', content, flags=re.DOTALL)
    if not sidebar_match:
        print("Sidebar already extracted or not found.")
        return

    sidebar_html = sidebar_match.group(1)

    # Save to _sidebar.html
    with open(SIDEBAR_PATH, 'w', encoding='utf-8') as f:
        f.write(sidebar_html)
    print("Created _sidebar.html")

    # Replace with container and injection script
    replacement = '''
    <div id="sidebar-container"></div>
    <script>
        // Carrega o menu lateral dinamicamente para aliviar o HTML principal
        fetch('/_sidebar.html')
            .then(r => r.text())
            .then(html => {
                document.getElementById('sidebar-container').outerHTML = html;
                // Readiciona os eventos de clique, caso necessario (o switchTab ja deve funcionar)
                if (window._markActiveTopbarLink) {
                    _markActiveTopbarLink();
                }
            })
            .catch(err => console.error("Erro ao carregar menu lateral:", err));
    </script>
    '''

    content = content.replace(sidebar_html, replacement)

    # Save dashboard.html
    with open(DASHBOARD_PATH, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Updated dashboard.html to load sidebar dynamically.")

if __name__ == '__main__':
    extract_sidebar()
