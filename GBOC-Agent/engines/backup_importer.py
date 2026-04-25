"""
GBOC Agent - Importador de descoberta de backups
Scan de engines e caminhos comuns sem gravar execuções sintéticas.
"""

import os
import logging
import shutil
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class RealBackupImporter:
    def __init__(self, core):
        self.core = core

    def scan_system(self) -> Dict[str, Any]:
        """Escaneia engines disponíveis e possíveis repositórios locais."""
        logger.info("🔍 Scan de importação iniciado...")

        engines = self._detect_engines()

        common_paths = [
            "C:\\Backups", "D:\\Backups", "E:\\Backups",
            "/var/backups", "/opt/backups", "./backups"
        ]

        found_repos: List[Dict[str, Any]] = []
        total_size_imported = 0

        for path in common_paths:
            if not os.path.isdir(path):
                continue

            size = self._get_dir_size(path)
            total_size_imported += size
            found_repos.append({
                "name": f"Discovered_{os.path.basename(os.path.normpath(path)) or 'backups'}",
                "type": "local",
                "path": path,
                "size": size
            })

        return {
            "engines_detected": engines,
            "repositories_found": found_repos,
            "imported_size_bytes": total_size_imported,
            "mode": "discovery_only"
        }

    def _get_dir_size(self, path: str) -> int:
        total = 0
        try:
            for entry in os.scandir(path):
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += self._get_dir_size(entry.path)
                except Exception:
                    continue
        except Exception:
            return total
        return total

    def _detect_engines(self) -> Dict[str, Dict[str, Any]]:
        engines = {}
        for tool in ["restic", "kopia", "duplicati", "borg"]:
            path = shutil.which(tool)
            engines[tool] = {"available": path is not None, "path": path}
        return engines


# Compat wrapper usado pela API
# Mantido para compatibilidade, mas sem inserções sintéticas no banco.
def scan_and_import_real_data(core) -> Dict[str, Any]:
    importer = RealBackupImporter(core)
    return importer.scan_system()