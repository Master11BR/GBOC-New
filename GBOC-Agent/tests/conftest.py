# Testes com o mesmo ambiente de execução do Agente: no Python 3.15+ (modo UTF-8 padrão) a saída dos comandos do
# Windows é lida na codificação do sistema, como start_server.py/start_scheduler.py fazem ao importar este módulo.
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import gboc_encoding_compat  # noqa: E402,F401
