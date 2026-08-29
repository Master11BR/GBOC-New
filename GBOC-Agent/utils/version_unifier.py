#!/usr/bin/env python3
# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# A cópia, distribuição ou modificação não autorizada é estritamente proibida.
# ==============================================================================

"""
GBOC System v13.2.0 Enterprise - Unificador Global de Versões e Auditoria Integrada
Varre todo o repositório GBOC e garante que 100% das referências residuais sejam unificadas para 13.2.0.
"""

import os
import re
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VersionUnifier")

TARGET_VERSION = "13.2.0"

LEGACY_EXACT_PATTERNS = [
    (r'v13\.1\.2', 'v13.2.0'),
    (r'13\.1\.2', '13.2.0'),
    (r'v13\.1\.1', 'v13.2.0'),
    (r'13\.1\.1', '13.2.0'),
    (r'v13\.1\.0', 'v13.2.0'),
    (r'13\.1\.0', '13.2.0'),
    (r'v13\.0\.0', 'v13.2.0'),
    (r'13\.0\.0', '13.2.0'),
    (r'v12\.0\.0', 'v13.2.0'),
    (r'12\.0\.0', '13.2.0')
]

TARGET_EXTENSIONS = {'.py', '.html', '.js', '.css', '.md', '.ps1', '.bat', '.txt'}
EXCLUDE_DIRS = {'.git', '__pycache__', '.venv', 'venv', 'logs', 'data', 'node_modules', '.gemini'}

class GlobalVersionUnifier:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.scanned_files = 0
        self.updated_files = 0
        self.replacements_count = 0
        self.errors = []

    def run(self) -> bool:
        logger.info("=" * 80)
        logger.info(f"🚀 INICIANDO VARREDURA GBOC PARA VERSÃO {TARGET_VERSION}")
        logger.info("=" * 80)

        for current_root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in files:
                file_path = Path(current_root) / file
                if file_path.suffix.lower() in TARGET_EXTENSIONS:
                    self._process_file(file_path)

        logger.info("\n" + "=" * 80)
        logger.info(f"✓ Arquivos Analisados: {self.scanned_files}")
        logger.info(f"✓ Arquivos Atualizados: {self.updated_files}")
        logger.info(f"✓ Substituições Realizadas: {self.replacements_count}")
        logger.info("=" * 80)
        return len(self.errors) == 0

    def _process_file(self, file_path: Path):
        self.scanned_files += 1
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            new_content = content
            file_replacements = 0

            for pattern, replacement in LEGACY_EXACT_PATTERNS:
                matches = len(re.findall(pattern, new_content))
                if matches > 0:
                    new_content = re.sub(pattern, replacement, new_content)
                    file_replacements += matches

            if file_replacements > 0 and new_content != content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                self.updated_files += 1
                self.replacements_count += file_replacements
                logger.info(f"  • {file_path.relative_to(self.root_dir)} → {file_replacements} ocorrência(s) atualizada(s)")

        except Exception as e:
            self.errors.append(f"Erro ao processar {file_path}: {e}")


if __name__ == "__main__":
    import sys
    base_dir = Path(__file__).resolve().parent.parent.parent
    unifier = GlobalVersionUnifier(base_dir)
    success = unifier.run()
    sys.exit(0 if success else 1)
