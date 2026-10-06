#!/usr/bin/env python3
# ==============================================================================
# GBOC System v14.8.1 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# A cópia, distribuição ou modificação não autorizada é estritamente proibida.
# ==============================================================================

"""
GBOC — Auditoria e unificação de versões.

Procura nos arquivos do produto (Agente, Server, CSS compartilhado) versões 14.x diferentes da oficial
(version.py) em textos exibidos: títulos, rodapés, banners de scripts, fallbacks de API, comentários de cabeçalho.

  * Por padrão só RELATA (dry-run). Com apply=True regrava os arquivos, byte a byte (CRLF/LF e codificação
    preservados), trocando só o número da versão.
  * Não mexe em: versão mínima compatível (min_server_version/min_agent_version), marcos de recurso
    ("Agente 14.7.7+", "v14.5+"), CHANGELOG, testes, dados, logs e no build do instalador.

Uso: python utils/version_unifier.py [--apply]
"""

import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("VersionUnifier")

try:
    from version import GBOC_VERSION as TARGET_VERSION
except Exception:
    try:
        from version_control import __version__ as TARGET_VERSION
    except Exception:
        TARGET_VERSION = "14.8.1"

TARGET_EXTENSIONS = {".py", ".html", ".js", ".css", ".ps1", ".bat", ".txt"}
EXCLUDE_DIRS = {".git", ".vs", "__pycache__", ".venv", "venv", "logs", "data", "node_modules", "tests", "_claude_sync",
                "python_embed", "dist", "build", ".ruff_cache", ".pytest_cache", "docs"}
EXCLUDE_FILES = {"CHANGELOG.md", "build_installer_package.bat", "build_installer_package.ps1", "version_unifier.py"}
TOP_DIRS = ("GBOC-Agent", "GBOC-Server", "shared-css")

_KEEP_LINE = re.compile(rb"min_(server|agent)_version|\d+\.\d+(\.\d+)?\+|_ver_tuple")
_CONTEXT = re.compile(rb"gboc|version|vers\xc3\xa3o|release|user-agent|\?v=", re.I)


def _patterns(target: str):
    major = re.escape(target.split(".")[0]).encode()
    t = target.encode()
    # 14.x.y completo (com ou sem "v") e "GBOC ... v14.x" curto
    full = re.compile(rb"(?<![\d.])(v?)(" + major + rb"\.\d+\.\d+)(?![\d.])")
    short = re.compile(rb"(GBOC[^\n\"'<]{0,20}?v)(" + major + rb"\.\d+)(?![\d.])")

    def fix_full(m):
        return m.group(0) if m.group(2) == t else m.group(1) + t

    def fix_short(m):
        return m.group(0) if t.startswith(m.group(2) + b".") else m.group(1) + t
    return ((full, fix_full), (short, fix_short))


class VersionUnifier:
    """Compatível com /api/system/version/unify e run_complete_diagnostic.py."""

    def __init__(self, root_dir: Optional[Path] = None, target: Optional[str] = None, apply: bool = False):
        here = Path(__file__).resolve().parent.parent              # GBOC-Agent
        if root_dir is None:
            root_dir = here.parent if (here.parent / "GBOC-Server").is_dir() else here
        self.root_dir = Path(root_dir)
        self.target = target or TARGET_VERSION
        self.apply = apply
        self.scanned_files = 0
        self.updated_files = 0
        self.replacements_count = 0
        self.findings: List[Dict[str, object]] = []
        self.failed_updates: List[str] = []
        self.errors = self.failed_updates

    def _roots(self):
        tops = [self.root_dir / t for t in TOP_DIRS if (self.root_dir / t).is_dir()]
        return tops or [self.root_dir]

    def unify_versions(self) -> bool:
        pats = _patterns(self.target)
        for top in self._roots():
            for cur, dirs, files in os.walk(top):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for name in files:
                    if name in EXCLUDE_FILES or os.path.splitext(name)[1].lower() not in TARGET_EXTENSIONS:
                        continue
                    self._process(Path(cur) / name, pats)
        logger.info(f"Versão alvo {self.target}: {self.scanned_files} arquivo(s) analisado(s), "
                    f"{len(self.findings)} ocorrência(s) divergente(s), {self.updated_files} arquivo(s) atualizado(s)")
        return not self.failed_updates

    run = unify_versions

    def _process(self, path: Path, pats) -> None:
        self.scanned_files += 1
        try:
            data = path.read_bytes()
        except OSError as e:
            self.failed_updates.append(f"{path}: {e}")
            return
        if self.target.split(".")[0].encode() + b"." not in data:
            return
        lines = data.split(b"\n")
        changed = 0
        for i, line in enumerate(lines):
            if _KEEP_LINE.search(line) or not _CONTEXT.search(line):
                continue
            new = line
            for rx, fn in pats:
                new = rx.sub(fn, new)
            if new != line:
                changed += 1
                self.findings.append({"file": str(path.relative_to(self.root_dir)), "line": i + 1,
                                      "text": line.decode("utf-8", "replace").strip()[:160]})
                lines[i] = new
        if changed and self.apply:
            try:
                path.write_bytes(b"\n".join(lines))
                self.updated_files += 1
                self.replacements_count += changed
            except OSError as e:
                self.failed_updates.append(f"{path}: {e}")

    def report(self) -> Dict[str, object]:
        return {"target_version": self.target, "applied": self.apply, "scanned_files": self.scanned_files,
                "divergences": len(self.findings), "updated_files": self.updated_files,
                "findings": self.findings[:500], "failed_updates": self.failed_updates}


GlobalVersionUnifier = VersionUnifier          # nome antigo


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    u = VersionUnifier(apply="--apply" in sys.argv)
    ok = u.unify_versions()
    for f in u.findings:
        print(f"{f['file']}:{f['line']}: {f['text']}")
    sys.exit(0 if ok else 1)
