"""
GBOC Agent — compressão e paralelismo por repositório, traduzidos para cada motor.

Configuração do repositório (config JSON, tela Repositórios):
  compression:       auto (padrão) | max | fast | lzma2 | none
  parallel_uploads:  1..16 (conexões simultâneas ao enviar/baixar; vazio = automático)

  * GBOC Native v4 — zstd (zlib sem o pacote) por bloco; max = nível 15, fast = nível 1; none = sem compressão;
    lzma2 = LZMA2 (mesmo algoritmo do 7-Zip/.xz): menor tamanho que o zstd, bem mais lento — para arquivamento;
    conexões paralelas por thread (native_engine/store_v4.py).
  * Motores sem LZMA2 (restic, Kopia, Duplicati) tratam "lzma2" como "max".
  * restic — --compression auto|max|off (repositório formato 2, restic ≥ 0.14) e -o s3.connections / b2.connections.
  * Kopia — por padrão NÃO compacta: auto/fast passam a usar zstd-fastest, max = zstd-better-compression;
    snapshot com --parallel.
  * Duplicati — --zip-compression-level (max = 9, fast = 1, none = 0) e --asynchronous-concurrent-upload-limit.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

VALID = ("auto", "max", "fast", "lzma2", "none")


def settings(repo_config: Any) -> Dict[str, Any]:
    cfg = repo_config
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg or "{}")
        except ValueError:
            cfg = {}
    cfg = cfg or {}
    comp = str(cfg.get("compression") or "auto").lower()
    comp = {"zstd": "auto", "zlib": "auto", "off": "none", "store": "none", "maximum": "max",
            "lzma": "lzma2", "xz": "lzma2", "7z": "lzma2"}.get(comp, comp)
    if comp not in VALID:
        comp = "auto"
    try:
        par = int(cfg.get("parallel_uploads") or 0)
    except (TypeError, ValueError):
        par = 0
    return {"compression": comp, "parallel": max(0, min(16, par))}


def native_codec(s: Dict[str, Any]):
    """(codec, nível) para o motor nativo."""
    c = s["compression"]
    if c == "none":
        return "none", None
    if c == "lzma2":
        return "lzma2", None          # preset 6 (ver store_v4.compress)
    return "auto", {"max": 15, "fast": 1}.get(c)


def _external(s: Dict[str, Any]) -> str:
    """Nível para motores externos, que não têm LZMA2: lzma2 → max."""
    return "max" if s["compression"] == "lzma2" else s["compression"]


def restic_args(s: Dict[str, Any], repo_type: str) -> List[str]:
    out: List[str] = []
    if _external(s) in ("max", "none"):
        out += ["--compression", "max" if _external(s) == "max" else "off"]
    if s["parallel"] and repo_type in ("s3", "wasabi"):
        out += ["-o", f"s3.connections={s['parallel']}"]
    elif s["parallel"] and repo_type == "b2":
        out += ["-o", f"b2.connections={s['parallel']}"]
    return out


def kopia_policy_args(s: Dict[str, Any]) -> List[str]:
    algo = {"auto": "zstd-fastest", "fast": "zstd-fastest", "max": "zstd-better-compression", "none": "none"}[_external(s)]
    return [f"--compression={algo}"]


def kopia_snapshot_args(s: Dict[str, Any]) -> List[str]:
    return [f"--parallel={s['parallel']}"] if s["parallel"] else []


def duplicati_args(s: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    lvl = {"max": 9, "fast": 1, "none": 0}.get(_external(s))
    if lvl is not None:
        out.append(f"--zip-compression-level={lvl}")
    if s["parallel"]:
        out.append(f"--asynchronous-concurrent-upload-limit={s['parallel']}")
    return out
