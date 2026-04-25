#!/usr/bin/env python3
"""
📁 GBOC Agent - FS Browser API (para selecionar pastas do servidor via UI)
ATENÇÃO: Para produção real, depois devemos restringir paths permitidos e autenticar.
"""

import os
import ctypes
import platform
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/fs", tags=["filesystem"])


def _is_windows() -> bool:
    return os.name == "nt"


def _list_windows_drives() -> List[Dict[str, Any]]:
    """Lista drives no Windows sem bloquear em unidades de rede offline."""
    drives = []
    try:
        # Bitmask de drives disponíveis (A=bit0, B=bit1...)
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if mask & (1 << i):
                letter = chr(ord('A') + i)
                root = f"{letter}:\\"
                drives.append({"name": root, "path": root, "type": "drive"})
    except Exception:
        # Fallback defensivo
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{letter}:\\"
            if os.path.isdir(root):
                drives.append({"name": root, "path": root, "type": "drive"})

    # Se não detectar drives (cenário raro), usar C:\ como fallback visual
    if not drives:
        drives = [{"name": "C:\\", "path": "C:\\", "type": "drive"}]

    return drives


@router.get("/browse")
async def browse(path: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    """
    Lista diretórios do servidor.
    - Se path não for informado:
        - Windows: retorna lista de drives (C:\\, D:\\ ...)
        - Linux: retorna "/"
    - Se path informado: retorna subpastas
    """
    try:
        if not path:
            if _is_windows():
                return {"path": None, "items": _list_windows_drives(), "machine": platform.node()}
            return {"path": "/", "items": [{"name": "/", "path": "/", "type": "dir"}], "machine": platform.node()}

        # Normalizar e validar existência
        norm = os.path.normpath(path)

        # Se for drive root no Windows, normpath mantém "C:\"
        if _is_windows() and len(norm) == 2 and norm[1] == ":":
            norm += "\\"

        if not os.path.exists(norm):
            raise HTTPException(status_code=404, detail=f"Caminho não encontrado: {path}")

        if not os.path.isdir(norm):
            raise HTTPException(status_code=400, detail=f"Não é um diretório: {path}")

        items: List[Dict[str, Any]] = []
        with os.scandir(norm) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    items.append({
                        "name": entry.name,
                        "path": entry.path,
                        "type": "dir"
                    })

        items.sort(key=lambda x: x["name"].lower())
        return {"path": norm, "items": items, "machine": platform.node()}

    except HTTPException:
        raise
    except PermissionError:
        raise HTTPException(status_code=403, detail="Acesso negado ao diretório")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
