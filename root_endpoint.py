from fastapi.responses import HTMLResponse

# To be appended or inserted into gboc_server.py
@app.get("/")
async def root_redirect():
    html_content = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>GBOC Server - API Mode</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0e1525; color: #dce8f5; text-align: center; padding: 50px; }
            .container { background-color: #182035; padding: 40px; border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); max-width: 600px; margin: 0 auto; border: 1px solid #2a3f5f; }
            h1 { color: #4fa3e8; }
            p { font-size: 1.1em; line-height: 1.6; color: #7ea8cc; }
            .btn { display: inline-block; background-color: #4fa3e8; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: bold; margin-top: 20px; transition: background 0.3s; }
            .btn:hover { background-color: #3b82f6; }
            .code { background: #111928; padding: 10px; border-radius: 6px; font-family: monospace; color: #4ecb88; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>GBOC API Server Ativo</h1>
            <p>O servidor backend está operando perfeitamente e 100% otimizado.</p>
            <p>Para garantir o máximo de performance e aliviar o processamento, a Interface Gráfica (GUI) foi completamente separada do Python.</p>
            <p>Para acessar o Dashboard, execute o script na pasta raiz:</p>
            <div class="code">start_server_gui.bat</div>
            <a href="http://127.0.0.1:8080" class="btn" target="_blank">Acessar Nova Interface (Porta 8080)</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
