#!/usr/bin/env python3
"""
GBOC 11.7c - Unificador de Versões
Atualiza a versão do servidor e agente para 10.0a
"""

import os
import re
import logging
from pathlib import Path
from typing import List, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TARGET_VERSION = "11.7c"

class VersionUnifier:
    """Unifica versões do sistema GBOC"""
    
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.files_to_update = []
        self.updated_files = []
        self.failed_updates = []
        
    def unify_versions(self) -> bool:
        """Unifica todas as versões para 10.0a"""
        logger.info("=" * 80)
        logger.info(f"GBOC - UNIFICANDO VERSÕES PARA {TARGET_VERSION}")
        logger.info("=" * 80)
        
        # 1. Identificar arquivos
        self._identify_files()
        
        # 2. Atualizar versões
        self._update_versions()
        
        # 3. Imprimir resumo
        self._print_summary()
        
        return len(self.failed_updates) == 0
    
    def _identify_files(self):
        """Identifica arquivos que precisam de atualização de versão"""
        logger.info("\n[1/2] Identificando arquivos...")
        
        # Arquivos do agente
        agent_files = [
            ("agent_server.py", r'version="[^"]+"|__version__ = "[^"]+"', 'version="{}"|__version__ = "{}"'),
            ("engines/diagnostic_system.py", r'self\.version = "[^"]+"', 'self.version = "{}"'),
            ("engines/diagnostic_module.py", r'__version__ = "[^"]+"', '__version__ = "{}"'),
        ]
        
        for file_name, pattern, replacement_template in agent_files:
            file_path = self.base_dir / file_name
            if file_path.exists():
                self.files_to_update.append((file_path, pattern, replacement_template))
                logger.info(f"  • {file_name}")
        
        # Arquivo do servidor
        server_file = self.base_dir.parent / "GBOC-Server" / "gboc_server.py"
        if server_file.exists():
            self.files_to_update.append((
                server_file,
                r'SERVER_VERSION = "[^"]+"',
                'SERVER_VERSION = "{}"'
            ))
            logger.info(f"  • GBOC-Server/gboc_server.py")
        
        logger.info(f"\n✓ Total de arquivos a atualizar: {len(self.files_to_update)}")
    
    def _update_versions(self):
        """Atualiza versões nos arquivos"""
        logger.info("\n[2/2] Atualizando versões...")
        
        for file_path, pattern, replacement_template in self.files_to_update:
            try:
                # Ler arquivo
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Encontrar matches
                matches = re.findall(pattern, content)
                if not matches:
                    logger.warning(f"⚠ Nenhum match encontrado em {file_path.name}")
                    continue
                
                # Substituir versão
                if '|' in replacement_template:
                    # Múltiplos padrões possíveis
                    patterns = replacement_template.split('|')
                    for p in patterns:
                        replacement = p.format(TARGET_VERSION)
                        new_content = re.sub(pattern, replacement, content)
                        if new_content != content:
                            content = new_content
                            break
                else:
                    replacement = replacement_template.format(TARGET_VERSION)
                    new_content = re.sub(pattern, replacement, content)
                    content = new_content
                
                # Salvar arquivo
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                self.updated_files.append(str(file_path))
                logger.info(f"✓ {file_path.name} → {TARGET_VERSION}")
                
            except Exception as e:
                self.failed_updates.append((str(file_path), str(e)))
                logger.error(f"✗ Erro em {file_path.name}: {e}")
    
    def _print_summary(self):
        """Imprime resumo da atualização"""
        logger.info("\n" + "=" * 80)
        logger.info("RESUMO DA UNIFICAÇÃO")
        logger.info("=" * 80)
        
        logger.info(f"\n✓ Versão alvo: {TARGET_VERSION}")
        logger.info(f"✓ Arquivos atualizados: {len(self.updated_files)}")
        
        if self.updated_files:
            logger.info("\nArquivos atualizados:")
            for file in self.updated_files:
                logger.info(f"  • {file}")
        
        if self.failed_updates:
            logger.error(f"\n✗ Falhas: {len(self.failed_updates)}")
            for file, error in self.failed_updates:
                logger.error(f"  • {file}: {error}")
        else:
            logger.info("\n✓ Todas as versões foram unificadas com sucesso!")
        
        logger.info("\n" + "=" * 80)

def main():
    """Função principal"""
    unifier = VersionUnifier()
    success = unifier.unify_versions()
    return 0 if success else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())

