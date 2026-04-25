#!/usr/bin/env python3
"""
GBOC 11.7c - Sistema de Detecção e Integração de Arquivos Órfãos
Encontra e integra arquivos que não estão sendo utilizados pelo sistema
"""

import os
import re
import ast
import logging
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OrphanFileDetector:
    """Detecta e integra arquivos órfãos no sistema"""
    
    def __init__(self):
        self.base_dir = Path(__file__).parent.parent
        self.orphan_files = []
        self.integration_suggestions = []
        self.imported_modules = set()
        self.all_python_files = []
        
    def scan_system(self) -> Dict[str, Any]:
        """Escaneia sistema completo"""
        logger.info("=" * 80)
        logger.info("GBOC 11.7c - DETECTOR DE ARQUIVOS ÓRFÃOS")
        logger.info("=" * 80)
        
        # 1. Mapear todos os arquivos Python
        self._map_python_files()
        
        # 2. Identificar importações
        self._identify_imports()
        
        # 3. Encontrar órfãos
        self._find_orphans()
        
        # 4. Gerar sugestões de integração
        self._generate_integration_suggestions()
        
        # 5. Gerar relatório
        report = self._generate_report()
        
        # 6. Salvar relatório
        self._save_report(report)
        
        return report
    
    def _map_python_files(self):
        """Mapeia todos os arquivos Python"""
        logger.info("\n[1/5] Mapeando arquivos Python...")
        
        exclude_dirs = {'venv', '__pycache__', '.vs', '.git', 'node_modules'}
        
        for py_file in self.base_dir.rglob("*.py"):
            # Verificar se está em diretório excluído
            if any(excluded in py_file.parts for excluded in exclude_dirs):
                continue
            
            self.all_python_files.append(py_file)
        
        logger.info(f"✓ Encontrados {len(self.all_python_files)} arquivos Python")
    
    def _identify_imports(self):
        """Identifica todas as importações no sistema"""
        logger.info("\n[2/5] Identificando importações...")
        
        for py_file in self.all_python_files:
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Encontrar imports usando regex
                import_patterns = [
                    r'import\s+([a-zA-Z0-9_\.]+)',
                    r'from\s+([a-zA-Z0-9_\.]+)\s+import',
                ]
                
                for pattern in import_patterns:
                    matches = re.findall(pattern, content)
                    for match in matches:
                        # Extrair módulo base
                        module = match.split('.')[0]
                        self.imported_modules.add(module)
                
            except Exception as e:
                logger.warning(f"Erro ao processar {py_file.name}: {e}")
        
        logger.info(f"✓ Identificados {len(self.imported_modules)} módulos importados")
    
    def _find_orphans(self):
        """Encontra arquivos órfãos"""
        logger.info("\n[3/5] Procurando arquivos órfãos...")
        
        for py_file in self.all_python_files:
            module_name = py_file.stem
            
            # Ignorar arquivos especiais
            if module_name.startswith('__') or module_name.startswith('test_'):
                continue
            
            # Verificar se é importado
            if module_name not in self.imported_modules:
                # Verificar se é script principal
                try:
                    with open(py_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Scripts principais geralmente têm if __name__ == '__main__'
                    is_main_script = 'if __name__ == "__main__"' in content or 'if __name__ == \'__main__\'' in content
                    
                    # Analisar conteúdo para determinar propósito
                    purpose = self._analyze_file_purpose(py_file, content)
                    
                    orphan_info = {
                        "file": str(py_file.relative_to(self.base_dir)),
                        "name": module_name,
                        "size_kb": round(py_file.stat().st_size / 1024, 2),
                        "modified": datetime.fromtimestamp(py_file.stat().st_mtime).isoformat(),
                        "is_main_script": is_main_script,
                        "purpose": purpose,
                        "line_count": len(content.splitlines()),
                        "has_classes": "class " in content,
                        "has_functions": "def " in content
                    }
                    
                    self.orphan_files.append(orphan_info)
                    
                except Exception as e:
                    logger.warning(f"Erro ao analisar {py_file.name}: {e}")
        
        logger.info(f"✓ Encontrados {len(self.orphan_files)} arquivos órfãos")
        
        if self.orphan_files:
            logger.info("\nArquivos órfãos detectados:")
            for orphan in self.orphan_files:
                logger.info(f"  • {orphan['file']} ({orphan['purpose']})")
    
    def _analyze_file_purpose(self, file_path: Path, content: str) -> str:
        """Analisa o propósito de um arquivo"""
        content_lower = content.lower()
        file_name = file_path.stem.lower()
        
        # Analisar por nome e conteúdo
        if 'test' in file_name or 'test' in content_lower[:200]:
            return "test"
        
        if 'config' in file_name or 'configuration' in content_lower[:200]:
            return "configuration"
        
        if 'util' in file_name or 'helper' in file_name:
            return "utility"
        
        if 'engine' in file_name or 'class ' in content[:1000]:
            return "engine/module"
        
        if 'api' in file_name or '@app.route' in content or '@router' in content:
            return "api"
        
        if 'model' in file_name or 'class ' in content and 'Base' in content:
            return "model"
        
        if 'client' in file_name or 'server' in file_name:
            return "client/server"
        
        if 'script' in file_name or 'if __name__' in content:
            return "script"
        
        return "unknown"
    
    def _generate_integration_suggestions(self):
        """Gera sugestões de integração"""
        logger.info("\n[4/5] Gerando sugestões de integração...")
        
        for orphan in self.orphan_files:
            suggestions = []
            purpose = orphan['purpose']
            file_path = orphan['file']
            
            # Sugestões baseadas no propósito
            if purpose == "engine/module":
                suggestions.append({
                    "action": "integrate_as_engine",
                    "location": "engines/",
                    "import_in": ["agent_server.py", "shared_core.py"],
                    "description": "Integrar como engine no sistema de engines"
                })
            
            elif purpose == "api":
                suggestions.append({
                    "action": "integrate_as_api",
                    "location": "api/",
                    "import_in": ["agent_server.py"],
                    "description": "Adicionar ao roteador de APIs"
                })
            
            elif purpose == "utility":
                suggestions.append({
                    "action": "integrate_as_utility",
                    "location": "utils/ (create if needed)",
                    "import_in": ["various modules"],
                    "description": "Disponibilizar como utilitário do sistema"
                })
            
            elif purpose == "configuration":
                suggestions.append({
                    "action": "integrate_as_config",
                    "location": "config/",
                    "import_in": ["agent_server.py", "shared_core.py"],
                    "description": "Integrar ao sistema de configuração"
                })
            
            elif purpose == "script":
                suggestions.append({
                    "action": "document_as_tool",
                    "location": "tools/ (create if needed)",
                    "description": "Documentar como ferramenta/script auxiliar"
                })
            
            elif purpose == "test":
                suggestions.append({
                    "action": "organize_tests",
                    "location": "tests/",
                    "description": "Organizar na estrutura de testes"
                })
            
            else:
                suggestions.append({
                    "action": "review_manually",
                    "description": "Revisar manualmente para determinar utilidade"
                })
            
            orphan['integration_suggestions'] = suggestions
            self.integration_suggestions.extend(suggestions)
        
        logger.info(f"✓ Geradas {len(self.integration_suggestions)} sugestões")
    
    def _generate_report(self) -> Dict[str, Any]:
        """Gera relatório completo"""
        logger.info("\n[5/5] Gerando relatório...")
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "total_python_files": len(self.all_python_files),
            "imported_modules": len(self.imported_modules),
            "orphan_files": len(self.orphan_files),
            "orphans": self.orphan_files,
            "integration_suggestions": self.integration_suggestions,
            "summary": {
                "by_purpose": self._group_by_purpose(),
                "total_size_kb": sum(o['size_kb'] for o in self.orphan_files),
                "total_lines": sum(o['line_count'] for o in self.orphan_files)
            },
            "recommendations": self._generate_recommendations()
        }
        
        return report
    
    def _group_by_purpose(self) -> Dict[str, int]:
        """Agrupa órfãos por propósito"""
        purposes = {}
        for orphan in self.orphan_files:
            purpose = orphan['purpose']
            purposes[purpose] = purposes.get(purpose, 0) + 1
        return purposes
    
    def _generate_recommendations(self) -> List[str]:
        """Gera recomendações gerais"""
        recommendations = []
        
        if len(self.orphan_files) > 10:
            recommendations.append("Alto número de arquivos órfãos - considere reorganização do projeto")
        
        purpose_counts = self._group_by_purpose()
        
        if purpose_counts.get('engine/module', 0) > 0:
            recommendations.append(f"Integrar {purpose_counts['engine/module']} engine(s) ao sistema")
        
        if purpose_counts.get('api', 0) > 0:
            recommendations.append(f"Adicionar {purpose_counts['api']} API(s) ao roteador")
        
        if purpose_counts.get('utility', 0) > 0:
            recommendations.append("Criar diretório utils/ e organizar utilitários")
        
        if purpose_counts.get('test', 0) > 0:
            recommendations.append("Organizar testes em estrutura adequada")
        
        if purpose_counts.get('unknown', 0) > 0:
            recommendations.append(f"Revisar {purpose_counts['unknown']} arquivo(s) de propósito desconhecido")
        
        return recommendations
    
    def _save_report(self, report: Dict[str, Any]):
        """Salva relatório em arquivo"""
        logs_dir = self.base_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        
        report_file = logs_dir / f"orphan_files_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            import json
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info(f"\n✓ Relatório salvo em: {report_file}")
        except Exception as e:
            logger.error(f"✗ Erro ao salvar relatório: {e}")
        
        # Salvar também versão texto
        text_file = logs_dir / f"orphan_files_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            with open(text_file, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("GBOC 11.7c - RELATÓRIO DE ARQUIVOS ÓRFÃOS\n")
                f.write("=" * 80 + "\n\n")
                
                f.write(f"Data: {report['timestamp']}\n\n")
                f.write(f"Total de arquivos Python: {report['total_python_files']}\n")
                f.write(f"Módulos importados: {report['imported_modules']}\n")
                f.write(f"Arquivos órfãos: {report['orphan_files']}\n\n")
                
                f.write("=" * 80 + "\n")
                f.write("ARQUIVOS ÓRFÃOS DETECTADOS\n")
                f.write("=" * 80 + "\n\n")
                
                for orphan in self.orphan_files:
                    f.write(f"Arquivo: {orphan['file']}\n")
                    f.write(f"  Propósito: {orphan['purpose']}\n")
                    f.write(f"  Tamanho: {orphan['size_kb']} KB\n")
                    f.write(f"  Linhas: {orphan['line_count']}\n")
                    f.write(f"  Modificado: {orphan['modified']}\n")
                    f.write(f"  É script principal: {orphan['is_main_script']}\n")
                    
                    if orphan.get('integration_suggestions'):
                        f.write(f"  Sugestões de integração:\n")
                        for suggestion in orphan['integration_suggestions']:
                            f.write(f"    - {suggestion.get('action', 'N/A')}: {suggestion.get('description', 'N/A')}\n")
                    
                    f.write("\n")
                
                if report['recommendations']:
                    f.write("=" * 80 + "\n")
                    f.write("RECOMENDAÇÕES\n")
                    f.write("=" * 80 + "\n\n")
                    for rec in report['recommendations']:
                        f.write(f"• {rec}\n")
            
            logger.info(f"✓ Relatório texto salvo em: {text_file}")
        except Exception as e:
            logger.error(f"✗ Erro ao salvar relatório texto: {e}")
    
    def auto_integrate_safe_files(self) -> List[str]:
        """Integra automaticamente arquivos seguros (experimental)"""
        logger.info("\n[AUTO-INTEGRAÇÃO] Integrando arquivos seguros...")
        
        integrated = []
        
        # Por enquanto, apenas sugerir - não fazer automaticamente
        logger.info("⚠ Auto-integração desabilitada por segurança")
        logger.info("  Use as sugestões do relatório para integração manual")
        
        return integrated

def main():
    """Função principal"""
    detector = OrphanFileDetector()
    report = detector.scan_system()
    
    # Imprimir resumo
    print("\n" + "=" * 80)
    print("RESUMO")
    print("=" * 80)
    print(f"\n✓ Total de arquivos Python: {report['total_python_files']}")
    print(f"✓ Módulos importados: {report['imported_modules']}")
    print(f"✓ Arquivos órfãos: {report['orphan_files']}")
    print(f"\nPor propósito:")
    for purpose, count in report['summary']['by_purpose'].items():
        print(f"  • {purpose}: {count}")
    
    if report['recommendations']:
        print(f"\nRecomendações:")
        for rec in report['recommendations']:
            print(f"  • {rec}")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()

