"""
GBOC - compatibilidade de encoding com Python 3.15+ no Windows.

A partir do Python 3.15 o "modo UTF-8" passa a ser o padrao (PEP 686). Com isso, toda chamada
subprocess com text=True e sem encoding passou a decodificar a saida dos comandos do Windows
(vssadmin, wmic, sc, netsh... que escrevem em cp850/cp1252) como UTF-8, e a thread de leitura caia com
"UnicodeDecodeError: 'utf-8' codec can't decode byte 0x87" - o resultado vinha vazio (None).

Os scripts de inicializacao definem PYTHONUTF8=0 (mesmo comportamento das versoes anteriores).
Este modulo cobre quando o Python e iniciado por outro caminho: so no Windows e so com o modo UTF-8
ativo sem ter sido pedido (PYTHONUTF8=1 respeitado), chamadas subprocess em modo texto SEM encoding
explicito usam a codificacao do Windows (a mesma que o Python usava antes do 3.15) com errors="replace".
Chamadas que ja informam encoding nao mudam.
"""
import locale
import os
import subprocess
import sys

_applied = False


def _windows_encoding() -> str:
    try:
        return locale.getencoding()          # Python 3.11+: codificacao ANSI, ignora o modo UTF-8
    except AttributeError:
        return locale.getpreferredencoding(False)


def apply(force: bool = False) -> bool:
    """Ativa a compatibilidade; retorna True se ativou."""
    global _applied
    if _applied:
        return True
    if not force:
        if sys.platform != "win32" or not getattr(sys.flags, "utf8_mode", 0):
            return False
        if os.environ.get("PYTHONUTF8", "").strip() == "1":
            return False                     # UTF-8 pedido explicitamente
    enc = _windows_encoding()
    original_init = subprocess.Popen.__init__

    def _init(self, *args, **kwargs):
        if (kwargs.get("text") or kwargs.get("universal_newlines")) and kwargs.get("encoding") is None:
            kwargs["encoding"] = enc
            if kwargs.get("errors") is None:
                kwargs["errors"] = "replace"
        original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _init
    _applied = True
    return True


apply()
