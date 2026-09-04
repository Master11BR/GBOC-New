#!/usr/bin/env python3
"""
GBOC 14.0.0 - Sistema de Diagnóstico Completo
Diagnóstico unificado de servidor e agente com correção automática
"""

import os
import sys
import json
import logging
import platform
import psutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VERSION = "14.0.0"

class SystemDiagnostic:
    """Diagnóstico completo do sistema GBOC"""
    
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.issues = []
        self.warnings = []
        self.improvements = []
        self.orphan_files = []
        self.version_mismatches = []
        
    def run_complete_diagnostic(self) -> Dict[str, Any]:
        """Executa diagnóstico completo"""
        logger.info("=" * 80)
        logger.info(f"GBOC v{VERSION} - DIAGNÓSTICO COMPLETO DO SISTEMA")
        logger.info("=" * 80)
        
        report = {
            "version": VERSION,
            "timestamp": datetime.now().isoformat(),
            "system_info": self._check_system(),
            "agent_status": self._check_agent(),
            "server_status": self._check_server(),
            "database_status": self._check_database(),
            "file_structure": self._check_file_structure(),
            "orphan_files": self._find_orphan_files(),
            "version_consistency": self._check_version_consistency(),
            "performance": self._check_performance(),
            "issues": self.issues,
            "warnings": self.warnings,
            "improvements": self.improvements,
            "auto_fixes": []
        }
        
        # Executar correções automáticas
        report["auto_fixes"] = self._apply_auto_fixes()
        
        # Salvar relatório
        self._save_report(report)
        
        # Imprimir resumo
        self._print_summary(report)
        
        return report
    
    def _check_system(self) -> Dict[str, Any]:
        """Verifica informações do sistema"""
        logger.info("\n[1/9] Verificando Sistema Operacional...")
        
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            info = {
                "platform": platform.system(),
                "platform_release": platform.release(),
                "platform_version": platform.version(),
                "architecture": platform.machine(),
                "hostname": platform.node(),
                "processor": platform.processor(),
                "cpu_count": psutil.cpu_count(),
                "cpu_percent": cpu_percent,
                "memory_total_gb": round(memory.total / (1024**3), 2),
                "memory_used_gb": round(memory.used / (1024**3), 2),
                "memory_percent": memory.percent,
                "disk_total_gb": round(disk.total / (1024**3), 2),
                "disk_used_gb": round(disk.used / (1024**3), 2),
                "disk_percent": disk.percent,
                "python_version": platform.python_version(),
                "status": "OK"
            }
            
            # Verificar recursos
            if cpu_percent > 80:
                self.warnings.append(f"CPU usage high: {cpu_percent}%")
            if memory.percent > 85:
                self.warnings.append(f"Memory usage high: {memory.percent}%")
            if disk.percent > 90:
                self.issues.append(f"Disk space critical: {disk.percent}%")
            
            logger.info(f"✓ Sistema: {info['platform']} {info['platform_release']}")
            logger.info(f"✓ CPU: {info['cpu_count']} cores @ {cpu_percent}%")
            logger.info(f"✓ RAM: {info['memory_used_gb']}/{info['memory_total_gb']} GB ({memory.percent}%)")
            logger.info(f"✓ Disco: {info['disk_used_gb']}/{info['disk_total_gb']} GB ({disk.percent}%)")
            
            return info
            
        except Exception as e:
            self.issues.append(f"System check error: {str(e)}")
            return {"status": "ERROR", "error": str(e)}
    
    def _check_agent(self) -> Dict[str, Any]:
        """Verifica status do agente"""
        logger.info("\n[2/9] Verificando GBOC Agent...")
        
        agent_status = {
            "installed": False,
            "version": None,
            "database": None,
            "config": None,
            "engines": [],
            "issues": []
        }
        
        # Verificar arquivo principal
        agent_file = self.base_dir / "agent_server.py"
        if agent_file.exists():
            agent_status["installed"] = True
            logger.info("✓ Agent instalado")
            
            # Verificar versão
            try:
                with open(agent_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if 'version="9.0"' in content:
                        agent_status["version"] = "9.0"
                        self.version_mismatches.append(("agent_server.py", "9.0", VERSION))
                    elif f'version="{VERSION}"' in content:
                        agent_status["version"] = VERSION
                        logger.info(f"✓ Versão: {VERSION}")
                    else:
                        agent_status["version"] = "Unknown"
                        self.issues.append("Agent version not detected")
            except Exception as e:
                agent_status["issues"].append(f"Version check failed: {str(e)}")
            
            # Verificar banco de dados
            db_file = self.base_dir / "data" / "gboc.db"
            if db_file.exists():
                agent_status["database"] = "OK"
                logger.info(f"✓ Database: {db_file}")
            else:
                agent_status["database"] = "MISSING"
                self.issues.append("Agent database not found")
            
            # Verificar engines
            engines_dir = self.base_dir / "engines"
            if engines_dir.exists():
                engine_files = list(engines_dir.glob("*.py"))
                agent_status["engines"] = [f.stem for f in engine_files]
                logger.info(f"✓ Engines: {len(agent_status['engines'])} módulos")
            
        else:
            agent_status["issues"].append("Agent not installed")
            self.issues.append("Agent server not found")
            logger.error("✗ Agent não encontrado")
        
        return agent_status
    
    def _check_server(self) -> Dict[str, Any]:
        """Verifica status do servidor central"""
        logger.info("\n[3/9] Verificando GBOC Server...")
        
        server_status = {
            "installed": False,
            "version": None,
            "database_config": None,
            "issues": []
        }
        
        server_file = self.base_dir.parent / "GBOC-Server" / "gboc_server.py"
        if server_file.exists():
            server_status["installed"] = True
            logger.info("✓ Server instalado")
            
            # Verificar versão
            try:
                with open(server_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if 'SERVER_VERSION = "3.0.0-realtime"' in content:
                        server_status["version"] = "3.0.0-realtime"
                        self.version_mismatches.append(("gboc_server.py", "3.0.0-realtime", VERSION))
                    elif f'SERVER_VERSION = "{VERSION}"' in content:
                        server_status["version"] = VERSION
                        logger.info(f"✓ Versão: {VERSION}")
            except Exception as e:
                server_status["issues"].append(f"Version check failed: {str(e)}")
            
            # Verificar configuração PostgreSQL
            try:
                with open(server_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if "DB_CONFIG" in content:
                        server_status["database_config"] = "PostgreSQL"
                        logger.info("✓ Database: PostgreSQL configurado")
            except Exception as e:
                server_status["issues"].append(f"DB config check failed: {str(e)}")
        else:
            server_status["issues"].append("Server not installed")
            self.issues.append("Central server not found")
            logger.error("✗ Server não encontrado")
        
        return server_status
    
    def _check_database(self) -> Dict[str, Any]:
        """Verifica integridade do banco de dados"""
        logger.info("\n[4/9] Verificando Banco de Dados...")
        
        db_status = {
            "agent_db": None,
            "server_db": None,
            "issues": []
        }
        
        # Verificar banco do agente
        agent_db = self.base_dir / "data" / "gboc.db"
        if agent_db.exists():
            try:
                conn = sqlite3.connect(agent_db)
                cursor = conn.cursor()
                
                # Verificar tabelas
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                
                db_status["agent_db"] = {
                    "status": "OK",
                    "size_mb": round(agent_db.stat().st_size / (1024**2), 2),
                    "tables": tables,
                    "table_count": len(tables)
                }
                
                logger.info(f"✓ Agent DB: {len(tables)} tabelas, {db_status['agent_db']['size_mb']} MB")
                
                # Verificar integridade
                cursor.execute("PRAGMA integrity_check")
                integrity = cursor.fetchone()[0]
                if integrity != "ok":
                    self.issues.append(f"Agent database integrity issue: {integrity}")
                    db_status["agent_db"]["integrity"] = integrity
                else:
                    db_status["agent_db"]["integrity"] = "OK"
                    logger.info("✓ Integridade: OK")
                
                conn.close()
                
            except Exception as e:
                db_status["agent_db"] = {"status": "ERROR", "error": str(e)}
                self.issues.append(f"Agent database error: {str(e)}")
        else:
            db_status["agent_db"] = {"status": "NOT_FOUND"}
            self.issues.append("Agent database not found")
        
        # Servidor usa PostgreSQL - apenas verificar configuração
        db_status["server_db"] = {"type": "PostgreSQL", "status": "Not checked (remote)"}
        
        return db_status
    
    def _check_file_structure(self) -> Dict[str, Any]:
        """Verifica estrutura de arquivos"""
        logger.info("\n[5/9] Verificando Estrutura de Arquivos...")
        
        structure = {
            "agent": {
                "root": str(self.base_dir),
                "directories": {},
                "critical_files": {}
            },
            "server": {
                "root": str(self.base_dir.parent / "GBOC-Server"),
                "critical_files": {}
            }
        }
        
        # Verificar diretórios do agente
        required_dirs = ["data", "logs", "static", "api", "engines", "storage_backends"]
        for dir_name in required_dirs:
            dir_path = self.base_dir / dir_name
            structure["agent"]["directories"][dir_name] = {
                "exists": dir_path.exists(),
                "path": str(dir_path)
            }
            if dir_path.exists():
                logger.info(f"✓ /{dir_name}/")
            else:
                logger.warning(f"✗ /{dir_name}/ MISSING")
                self.issues.append(f"Directory missing: {dir_name}")
        
        # Verificar arquivos críticos do agente
        critical_files = [
            "agent_server.py",
            "start_server.py",
            "models.py",
            "shared_core.py",
            "server_client.py",
            "server_config.py"
        ]
        
        for file_name in critical_files:
            file_path = self.base_dir / file_name
            structure["agent"]["critical_files"][file_name] = {
                "exists": file_path.exists(),
                "path": str(file_path)
            }
            if file_path.exists():
                logger.info(f"✓ {file_name}")
            else:
                logger.error(f"✗ {file_name} MISSING")
                self.issues.append(f"Critical file missing: {file_name}")
        
        # Verificar servidor
        server_file = self.base_dir.parent / "GBOC-Server" / "gboc_server.py"
        structure["server"]["critical_files"]["gboc_server.py"] = {
            "exists": server_file.exists(),
            "path": str(server_file)
        }
        
        return structure
    
    def _find_orphan_files(self) -> List[Dict[str, Any]]:
        """Encontra arquivos órfãos que podem ser integrados"""
        logger.info("\n[6/9] Procurando Arquivos Órfãos...")
        
        orphans = []
        
        # Procurar por arquivos Python não integrados
        for py_file in self.base_dir.rglob("*.py"):
            # Ignorar venv, __pycache__, etc
            if any(x in str(py_file) for x in ["venv", "__pycache__", ".vs", "tests"]):
                continue
            
            # Verificar se é importado em algum lugar
            file_name = py_file.stem
            is_imported = False
            
            # Procurar importações
            for check_file in self.base_dir.rglob("*.py"):
                if check_file == py_file:
                    continue
                try:
                    with open(check_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if f"import {file_name}" in content or f"from {file_name}" in content:
                            is_imported = True
                            break
                except:
                    pass
            
            if not is_imported:
                orphans.append({
                    "file": str(py_file.relative_to(self.base_dir)),
                    "size_kb": round(py_file.stat().st_size / 1024, 2),
                    "modified": datetime.fromtimestamp(py_file.stat().st_mtime).isoformat(),
                    "type": "python_module"
                })
        
        if orphans:
            logger.info(f"⚠ Encontrados {len(orphans)} arquivos órfãos")
            for orphan in orphans:
                logger.info(f"  - {orphan['file']} ({orphan['size_kb']} KB)")
                self.improvements.append(f"Consider integrating: {orphan['file']}")
        else:
            logger.info("✓ Nenhum arquivo órfão encontrado")
        
        self.orphan_files = orphans
        return orphans
    
    def _check_version_consistency(self) -> Dict[str, Any]:
        """Verifica consistência de versões"""
        logger.info("\n[7/9] Verificando Consistência de Versões...")
        
        versions = {
            "target_version": VERSION,
            "agent_version": None,
            "server_version": None,
            "mismatches": []
        }
        
        # Verificar versão do agente
        agent_file = self.base_dir / "agent_server.py"
        if agent_file.exists():
            try:
                with open(agent_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if 'version="' in content:
                        import re
                        match = re.search(r'version="([^"]+)"', content)
                        if match:
                            versions["agent_version"] = match.group(1)
            except:
                pass
        
        # Verificar versão do servidor
        server_file = self.base_dir.parent / "GBOC-Server" / "gboc_server.py"
        if server_file.exists():
            try:
                with open(server_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if 'SERVER_VERSION = "' in content:
                        import re
                        match = re.search(r'SERVER_VERSION = "([^"]+)"', content)
                        if match:
                            versions["server_version"] = match.group(1)
            except:
                pass
        
        # Verificar inconsistências
        versions["mismatches"] = self.version_mismatches
        
        if versions["agent_version"] != VERSION:
            logger.warning(f"⚠ Agent version mismatch: {versions['agent_version']} != {VERSION}")
            self.warnings.append(f"Agent version: {versions['agent_version']} (should be {VERSION})")
        else:
            logger.info(f"✓ Agent version: {VERSION}")
        
        if versions["server_version"] != VERSION:
            logger.warning(f"⚠ Server version mismatch: {versions['server_version']} != {VERSION}")
            self.warnings.append(f"Server version: {versions['server_version']} (should be {VERSION})")
        else:
            logger.info(f"✓ Server version: {VERSION}")
        
        return versions
    
    def _check_performance(self) -> Dict[str, Any]:
        """Verifica performance e sugere melhorias"""
        logger.info("\n[8/9] Analisando Performance...")
        
        perf = {
            "recommendations": [],
            "metrics": {}
        }
        
        # Verificar uso de recursos
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        
        perf["metrics"] = {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_available_gb": round(memory.available / (1024**3), 2)
        }
        
        # Recomendações baseadas no Duplicati
        if memory.percent > 70:
            perf["recommendations"].append("Consider increasing system memory for better performance")
            self.improvements.append("Performance: Increase system memory")
        
        if cpu_percent > 60:
            perf["recommendations"].append("High CPU usage detected - consider optimizing backup schedules")
            self.improvements.append("Performance: Optimize backup schedules")
        
        # Verificar cache do banco de dados
        agent_db = self.base_dir / "data" / "gboc.db"
        if agent_db.exists():
            size_mb = agent_db.stat().st_size / (1024**2)
            if size_mb > 100:
                perf["recommendations"].append("Database size is large - consider implementing data retention policy")
                self.improvements.append("Database: Implement retention policy")
        
        # Sugerir melhorias do Duplicati
        duplicati_features = [
            "Add compression support (like Duplicati's)",
            "Implement deduplication for storage optimization",
            "Add encryption for backup data",
            "Implement incremental backups",
            "Add backup verification system",
            "Implement auto-throttling for network operations",
            "Add retention policies for old backups",
            "Implement backup chain management"
        ]
        
        perf["duplicati_inspired_improvements"] = duplicati_features
        logger.info("✓ Performance analysis complete")
        
        for feature in duplicati_features:
            self.improvements.append(f"Feature: {feature}")
        
        return perf
    
    def _apply_auto_fixes(self) -> List[Dict[str, Any]]:
        """Aplica correções automáticas"""
        logger.info("\n[9/9] Aplicando Correções Automáticas...")
        
        fixes = []
        
        # 1. Criar diretórios faltantes
        required_dirs = ["data", "logs", "static", "api", "engines"]
        for dir_name in required_dirs:
            dir_path = self.base_dir / dir_name
            if not dir_path.exists():
                try:
                    dir_path.mkdir(parents=True, exist_ok=True)
                    fixes.append({
                        "type": "directory_created",
                        "path": str(dir_path),
                        "status": "SUCCESS"
                    })
                    logger.info(f"✓ Created: {dir_path}")
                except Exception as e:
                    fixes.append({
                        "type": "directory_creation_failed",
                        "path": str(dir_path),
                        "status": "FAILED",
                        "error": str(e)
                    })
        
        # 2. Atualizar versões (será feito em outro passo)
        if self.version_mismatches:
            fixes.append({
                "type": "version_update_needed",
                "files": [f[0] for f in self.version_mismatches],
                "status": "PENDING",
                "note": "Version update will be applied separately"
            })
        
        logger.info(f"✓ Applied {len(fixes)} auto-fixes")
        return fixes
    
    def _save_report(self, report: Dict[str, Any]):
        """Salva relatório em arquivo"""
        report_dir = self.base_dir / "logs"
        report_dir.mkdir(exist_ok=True)
        
        report_file = report_dir / f"diagnostic_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info(f"\n✓ Relatório salvo em: {report_file}")
        except Exception as e:
            logger.error(f"✗ Erro ao salvar relatório: {e}")
    
    def _print_summary(self, report: Dict[str, Any]):
        """Imprime resumo do diagnóstico"""
        logger.info("\n" + "=" * 80)
        logger.info("RESUMO DO DIAGNÓSTICO")
        logger.info("=" * 80)
        
        logger.info(f"\n✓ Sistema: {report['system_info'].get('platform')} {report['system_info'].get('platform_release')}")
        logger.info(f"✓ Python: {report['system_info'].get('python_version')}")
        
        logger.info(f"\n📊 ESTATÍSTICAS:")
        logger.info(f"  • Issues Críticos: {len(self.issues)}")
        logger.info(f"  • Warnings: {len(self.warnings)}")
        logger.info(f"  • Melhorias Sugeridas: {len(self.improvements)}")
        logger.info(f"  • Arquivos Órfãos: {len(self.orphan_files)}")
        logger.info(f"  • Correções Aplicadas: {len(report['auto_fixes'])}")
        
        if self.issues:
            logger.info(f"\n❌ ISSUES CRÍTICOS:")
            for issue in self.issues:
                logger.info(f"  • {issue}")
        
        if self.warnings:
            logger.info(f"\n⚠️ WARNINGS:")
            for warning in self.warnings:
                logger.info(f"  • {warning}")
        
        if self.improvements:
            logger.info(f"\n💡 MELHORIAS SUGERIDAS:")
            for improvement in self.improvements[:10]:  # Mostrar top 10
                logger.info(f"  • {improvement}")
            if len(self.improvements) > 10:
                logger.info(f"  ... e mais {len(self.improvements) - 10} melhorias")
        
        logger.info("\n" + "=" * 80)

def main():
    """Função principal"""
    diagnostic = SystemDiagnostic()
    report = diagnostic.run_complete_diagnostic()
    
    # Retornar código de saída baseado em issues
    if diagnostic.issues:
        logger.error(f"\n❌ Diagnostic completed with {len(diagnostic.issues)} critical issues")
        return 1
    else:
        logger.info(f"\n✓ Diagnostic completed successfully!")
        return 0

if __name__ == "__main__":
    sys.exit(main())

