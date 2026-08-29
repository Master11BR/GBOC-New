# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# A cópia, distribuição ou modificação não autorizada é estritamente proibida.
# ==============================================================================

"""
GBOC Server - Wrapper de Compatibilidade Reversa
Redireciona para o entrypoint padronizado: server_gboc.py
"""

import os
import sys

# Garante path correto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Exporta todos os símbolos do server_gboc
from server_gboc import *
from server_gboc import app, lifespan, manager, DB_CONFIG, SERVER_VERSION

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVER_PORT", 8000))
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    print(f"🚀 Iniciando GBOC Server (via wrapper gboc_server.py -> server_gboc.py)...")
    uvicorn.run("server_gboc:app", host=host, port=port, reload=False)
