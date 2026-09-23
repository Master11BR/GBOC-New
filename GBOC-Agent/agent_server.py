# ==============================================================================
# GBOC System v14.6.0 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# A cópia, distribuição ou modificação não autorizada é estritamente proibida.
# ==============================================================================

"""
GBOC Agent - Wrapper de Compatibilidade Reversa
Redireciona para o entrypoint padronizado: agent_gboc.py
"""

import os
import sys

# Garante path correto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Exporta todos os símbolos do agent_gboc
from agent_gboc import *
from agent_gboc import app, AGENT_VERSION

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("AGENT_PORT", 9200))
    host = os.getenv("AGENT_HOST", "0.0.0.0")
    print(f"🚀 Iniciando GBOC Agent (via wrapper agent_server.py -> agent_gboc.py)...")
    _uv_kwargs = {"reload": False}
    try:
        import httptools  # noqa: F401
        _uv_kwargs["http"] = "httptools"
    except Exception:
        pass
    if sys.platform != "win32":
        try:
            import uvloop  # noqa: F401
            _uv_kwargs["loop"] = "uvloop"
        except Exception:
            pass
    uvicorn.run("agent_gboc:app", host=host, port=port, **_uv_kwargs)
