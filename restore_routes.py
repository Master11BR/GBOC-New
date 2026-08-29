import os

SERVER_PY = r"d:\GBOC-New\GBOC-New\GBOC-Server\gboc_server.py"
AGENT_PY = r"d:\GBOC-New\GBOC-New\GBOC-Agent\agent_server.py"

def restore_routes(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
        
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Check if routes are already there
    if 'def serve_any_html_page' in content:
        print(f"Routes already present in {filepath}")
        return
        
    # Find the right place to inject: before auth endpoints or just at the end before main
    injection = """
# ===========================
# STATIC & HTML ROUTES (GUI)
# ===========================
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

@app.get("/login.html", include_in_schema=False)
async def login_page():
    _path = os.path.join(os.path.dirname(__file__), "login.html")
    if os.path.exists(_path):
        return FileResponse(_path)
    return HTMLResponse("<h1>Login page not found</h1>", status_code=404)

@app.get("/static/{filename:path}", include_in_schema=False)
async def serve_static_asset(filename: str):
    clean_fn = (filename or '').lstrip("/\\\\")
    if clean_fn.startswith("static/") or clean_fn.startswith("static\\\\"):
        clean_fn = clean_fn[7:]
    srv_file = os.path.join(os.path.dirname(__file__), clean_fn)
    if os.path.isfile(srv_file):
        return FileResponse(srv_file)
    return HTMLResponse("Not found", status_code=404)

@app.get("/{page_name:path}.html", include_in_schema=False)
async def serve_any_html_page(page_name: str):
    clean_p = (page_name or '').lstrip("/\\\\")
    if clean_p.startswith("static/") or clean_p.startswith("static\\\\"):
        clean_p = clean_p[7:]
    fname = f"{clean_p}.html" if not clean_p.endswith(".html") else clean_p
    
    # 1. Procurar na propria pasta
    srv_file = os.path.join(os.path.dirname(__file__), fname)
    if os.path.isfile(srv_file):
        return FileResponse(srv_file, media_type="text/html")
        
    # 2. Fallback para dashboard.html ou index.html
    dash_file = os.path.join(os.path.dirname(__file__), "dashboard.html")
    idx_file = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.isfile(dash_file):
        return FileResponse(dash_file, media_type="text/html")
    if os.path.isfile(idx_file):
        return FileResponse(idx_file, media_type="text/html")
        
    return HTMLResponse(f"Página '{fname}' não encontrada.", status_code=404)

@app.get("/{file:path}.js", include_in_schema=False)
async def serve_any_js_page(file: str):
    fname = f"{file}.js" if not file.endswith(".js") else file
    srv_file = os.path.join(os.path.dirname(__file__), fname)
    if os.path.isfile(srv_file):
        return FileResponse(srv_file, media_type="application/javascript")
    return HTMLResponse("Not found", status_code=404)

@app.get("/{file:path}.css", include_in_schema=False)
async def serve_any_css_page(file: str):
    fname = f"{file}.css" if not file.endswith(".css") else file
    srv_file = os.path.join(os.path.dirname(__file__), fname)
    if os.path.isfile(srv_file):
        return FileResponse(srv_file, media_type="text/css")
    return HTMLResponse("Not found", status_code=404)

"""
    # Remove the root_redirect if it exists
    import re
    content = re.sub(r'@app\.get\("/"\)\s*async def root_redirect\(\):.*?return HTMLResponse\(content=html_content\)', '', content, flags=re.DOTALL)
    
    # Add a clean root route
    root_route = """
from fastapi.responses import RedirectResponse
@app.get("/")
async def index():
    return RedirectResponse(url="/dashboard.html", status_code=302)
"""
    
    # Inject before if __name__ == "__main__":
    if 'if __name__ == "__main__":' in content:
        content = content.replace('if __name__ == "__main__":', injection + root_route + '\nif __name__ == "__main__":')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Restored GUI routes in {filepath}")
    else:
        print(f"Could not find main block in {filepath}")

if __name__ == '__main__':
    restore_routes(SERVER_PY)
    restore_routes(AGENT_PY)
