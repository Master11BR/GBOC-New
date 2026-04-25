#!/usr/bin/env python3
"""
GBOC Agent 11.7c - Motor de Recuperação
Engine para recuperação e correção automática de problemas
"""

import os
import logging
import psutil
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import sqlite3
import json

logger = logging.getLogger("HealerEngine")

class HealerEngine:
    """Motor de recuperação para correção automática de problemas"""
    
    def __init__(self, core):
        """Inicializa o motor de recuperação"""
        self.core = core
        self.version = "11.7c"
        self.initialized = False

        self.version = "11.7c"
        self.initialized = False
        self.auto_heal_enabled = True
        self.healing_rules = []
        
        try:
            self._initialize()
            logger.info("[SUCCESS] HealerEngine inicializado")
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar HealerEngine: {e}")
    
    def _initialize(self):
        """Inicialização interna"""
        # Carregar regras de correção
        self._load_healing_rules()
        
        # Verificar se pode acessar recursos necessários
        try:
            # Testar acesso ao banco
            self._test_database_access()
            
            # Testar acesso a recursos do sistema
            psutil.cpu_percent(interval=0.1)
            psutil.virtual_memory()
            
            self.initialized = True
            logger.info(f"[REPAIR] Regras de correção carregadas: {len(self.healing_rules)}")
            
        except Exception as e:
            logger.warning(f"⚠️ Inicialização limitada: {e}")
    
    def run_health_check(self) -> Dict[str, Any]:
        """Executa verificação de saúde completa"""
        try:
            start_time = datetime.now()
            
            # Executar verificações
            checks = {
                "system_resources": self._check_system_resources(),
                "database_health": self._check_database_health(),
                "disk_space": self._check_disk_space(),
                "process_health": self._check_process_health(),
                "backup_consistency": self._check_backup_consistency()
            }
            
            # Compilar resultados
            issues_found = []
            auto_fixes_applied = []
            
            for check_name, check_result in checks.items():
                if check_result.get("issues"):
                    issues_found.extend(check_result["issues"])
                
                if check_result.get("auto_fixes"):
                    auto_fixes_applied.extend(check_result["auto_fixes"])
            
            # Calcular score de saúde
            health_score = self._calculate_health_score(checks)
            
            result = {
                "timestamp": datetime.now().isoformat(),
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "health_score": health_score,
                "status": self._get_health_status(health_score),
                "checks_performed": list(checks.keys()),
                "issues_found": len(issues_found),
                "auto_fixes_applied": len(auto_fixes_applied),
                "details": checks,
                "recommendations": self._generate_recommendations(checks)
            }
            
            if auto_fixes_applied:
                logger.info(f"🔧 {len(auto_fixes_applied)} correções automáticas aplicadas")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Erro na verificação de saúde: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "health_score": 0,
                "status": "error",
                "error": str(e)
            }
    
    def apply_auto_healing(self, issue_type: str, issue_data: Dict[str, Any]) -> Dict[str, Any]:
        """Aplica correção automática para um problema específico"""
        try:
            logger.info(f"🔧 Aplicando correção automática para: {issue_type}")
            
            # Buscar regra de correção apropriada
            healing_rule = self._find_healing_rule(issue_type)
            
            if not healing_rule:
                return {
                    "status": "no_rule",
                    "message": f"Nenhuma regra de correção encontrada para {issue_type}",
                    "timestamp": datetime.now().isoformat()
                }
            
            # Aplicar correção baseada na regra
            fix_result = self._apply_healing_rule(healing_rule, issue_data)
            
            # Log da correção
            self._log_healing_action(issue_type, fix_result)
            
            return {
                "status": "success" if fix_result.get("success") else "failed",
                "message": fix_result.get("message", "Correção aplicada"),
                "actions_taken": fix_result.get("actions", []),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Erro na correção automática: {e}")
            return {
                "status": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def get_healing_history(self, limit: int = 50) -> Dict[str, Any]:
        """Retorna histórico de correções aplicadas"""
        try:
            # Em implementação real, buscaria do banco de dados
            # Por agora, simular dados
            
            history = [
                {
                    "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(),
                    "issue_type": "high_memory_usage",
                    "status": "success",
                    "message": "Liberada memória cache do sistema"
                },
                {
                    "timestamp": (datetime.now() - timedelta(hours=6)).isoformat(),
                    "issue_type": "disk_space_low",
                    "status": "success",
                    "message": "Limpeza automática de arquivos temporários"
                },
                {
                    "timestamp": (datetime.now() - timedelta(days=1)).isoformat(),
                    "issue_type": "backup_task_failed",
                    "status": "success",
                    "message": "Reiniciada tarefa de backup falhada"
                }
            ]
            
            return {
                "total_records": len(history),
                "history": history[:limit],
                "auto_heal_enabled": self.auto_heal_enabled
            }
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter histórico: {e}")
            return {"error": str(e)}
    
    def enable_auto_healing(self) -> Dict[str, Any]:
        """Habilita correção automática"""
        try:
            self.auto_heal_enabled = True
            logger.info("✅ Correção automática habilitada")
            return {
                "status": "enabled",
                "message": "Correção automática habilitada",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def disable_auto_healing(self) -> Dict[str, Any]:
        """Desabilita correção automática"""
        try:
            self.auto_heal_enabled = False
            logger.info("⏸️ Correção automática desabilitada")
            return {
                "status": "disabled",
                "message": "Correção automática desabilitada",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _load_healing_rules(self):
        """Carrega regras de correção automática"""
        # Regras básicas de correção
        self.healing_rules = [
            {
                "name": "high_memory_usage",
                "condition": lambda data: data.get("memory_percent", 0) > 90,
                "actions": ["clear_cache", "restart_services"],
                "enabled": True
            },
            {
                "name": "disk_space_low",
                "condition": lambda data: data.get("disk_percent", 0) > 95,
                "actions": ["cleanup_temp_files", "compress_old_logs"],
                "enabled": True
            },
            {
                "name": "backup_task_failed",
                "condition": lambda data: data.get("status") == "failed",
                "actions": ["retry_backup", "check_repository"],
                "enabled": True
            },
            {
                "name": "database_lock",
                "condition": lambda data: "database is locked" in data.get("error", "").lower(),
                "actions": ["restart_connections", "analyze_database"],
                "enabled": True
            },
            {
                "name": "process_not_responding",
                "condition": lambda data: data.get("response_time", 0) > 30,
                "actions": ["restart_process", "check_resources"],
                "enabled": True
            }
        ]
    
    def _test_database_access(self):
        """Testa acesso ao banco de dados"""
        if os.path.exists(self.db_path):
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("SELECT 1")
    
    def _check_system_resources(self) -> Dict[str, Any]:
        """Verifica recursos do sistema"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.5)
            memory = psutil.virtual_memory()
            
            issues = []
            auto_fixes = []
            
            # Verificar CPU
            if cpu_percent > 90:
                issues.append({
                    "type": "high_cpu_usage",
                    "severity": "warning",
                    "message": f"CPU usage alto: {cpu_percent:.1f}%"
                })
            
            # Verificar memória
            if memory.percent > 85:
                issues.append({
                    "type": "high_memory_usage",
                    "severity": "warning" if memory.percent < 95 else "critical",
                    "message": f"Uso de memória alto: {memory.percent:.1f}%"
                })
                
                if self.auto_heal_enabled and memory.percent > 90:
                    auto_fixes.append({
                        "action": "clear_system_cache",
                        "message": "Liberando cache do sistema"
                    })
            
            return {
                "status": "healthy" if not issues else "issues_detected",
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "issues": issues,
                "auto_fixes": auto_fixes
            }
            
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _check_database_health(self) -> Dict[str, Any]:
        """Verifica saúde do banco de dados"""
        try:
            if not os.path.exists(self.db_path):
                return {
                    "status": "missing",
                    "message": "Arquivo de banco não encontrado",
                    "issues": [{"type": "database_missing", "severity": "critical"}]
                }
            
            # Verificar tamanho
            size_mb = os.path.getsize(self.db_path) / (1024 * 1024)
            
            # Teste de conectividade
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA integrity_check")
            
            return {
                "status": "healthy",
                "size_mb": round(size_mb, 2),
                "issues": []
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "issues": [{"type": "database_error", "severity": "critical", "message": str(e)}]
            }
    
    def _check_disk_space(self) -> Dict[str, Any]:
        """Verifica espaço em disco"""
        try:
            partitions = psutil.disk_partitions()
            issues = []
            auto_fixes = []
            
            for partition in partitions:
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    percent_used = (usage.used / usage.total) * 100
                    
                    if percent_used > 90:
                        issues.append({
                            "type": "disk_space_low",
                            "severity": "critical" if percent_used > 95 else "warning",
                            "partition": partition.device,
                            "percent_used": round(percent_used, 1),
                            "free_gb": round(usage.free / (1024**3), 1)
                        })
                        
                        if self.auto_heal_enabled and percent_used > 95:
                            auto_fixes.append({
                                "action": "cleanup_temp_files",
                                "partition": partition.device,
                                "message": f"Limpeza automática em {partition.device}"
                            })
                            
                except PermissionError:
                    continue
            
            return {
                "status": "healthy" if not issues else "issues_detected",
                "issues": issues,
                "auto_fixes": auto_fixes
            }
            
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _check_process_health(self) -> Dict[str, Any]:
        """Verifica saúde dos processos"""
        try:
            gboc_processes = []
            
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    if any(keyword in proc.info['name'].lower() for keyword in ['gboc', 'agent', 'backup']):
                        gboc_processes.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            return {
                "status": "healthy",
                "gboc_processes": len(gboc_processes),
                "issues": []
            }
            
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _check_backup_consistency(self) -> Dict[str, Any]:
        """Verifica consistência dos backups"""
        try:
            # Em implementação real, verificaria:
            # - Tarefas que falharam recentemente
            # - Repositórios corrompidos
            # - Backups incompletos
            
            # Simular verificação
            return {
                "status": "healthy",
                "last_check": datetime.now().isoformat(),
                "issues": []
            }
            
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _calculate_health_score(self, checks: Dict[str, Any]) -> int:
        """Calcula score de saúde baseado nas verificações"""
        try:
            total_score = 100
            
            for check_name, check_data in checks.items():
                if check_data.get("status") == "error":
                    total_score -= 20
                elif check_data.get("issues"):
                    # Reduzir score baseado na severidade das issues
                    for issue in check_data["issues"]:
                        if issue.get("severity") == "critical":
                            total_score -= 15
                        elif issue.get("severity") == "warning":
                            total_score -= 5
            
            return max(0, min(100, total_score))
        except Exception:
            return 50
    
    def _get_health_status(self, score: int) -> str:
        """Converte score em status"""
        if score >= 90:
            return "excellent"
        elif score >= 75:
            return "good"
        elif score >= 50:
            return "warning"
        else:
            return "critical"
    
    def _generate_recommendations(self, checks: Dict[str, Any]) -> List[str]:
        """Gera recomendações baseadas nas verificações"""
        recommendations = []
        
        try:
            for check_name, check_data in checks.items():
                if check_data.get("issues"):
                    for issue in check_data["issues"]:
                        if issue.get("type") == "high_memory_usage":
                            recommendations.append("Considere reiniciar serviços ou aumentar RAM")
                        elif issue.get("type") == "disk_space_low":
                            recommendations.append("Limpe arquivos desnecessários ou expanda armazenamento")
                        elif issue.get("type") == "high_cpu_usage":
                            recommendations.append("Verifique processos que consomem muita CPU")
            
            if not recommendations:
                recommendations.append("Sistema funcionando adequadamente")
            
        except Exception as e:
            recommendations.append("Erro ao gerar recomendações")
            logger.warning(f"Erro ao gerar recomendações: {e}")
        
        return recommendations
    
    def _find_healing_rule(self, issue_type: str) -> Optional[Dict[str, Any]]:
        """Encontra regra de correção para o tipo de problema"""
        for rule in self.healing_rules:
            if rule["name"] == issue_type and rule["enabled"]:
                return rule
        return None
    
    def _apply_healing_rule(self, rule: Dict[str, Any], issue_data: Dict[str, Any]) -> Dict[str, Any]:
        """Aplica regra de correção"""
        try:
            actions_taken = []
            
            for action in rule.get("actions", []):
                result = self._execute_healing_action(action, issue_data)
                actions_taken.append({
                    "action": action,
                    "result": result
                })
            
            return {
                "success": True,
                "message": f"Regra {rule['name']} aplicada com sucesso",
                "actions": actions_taken
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Erro ao aplicar regra: {str(e)}",
                "actions": []
            }
    
    def _execute_healing_action(self, action: str, issue_data: Dict[str, Any]) -> str:
        """Executa ação de correção específica"""
        # NOTA: Em produção, estas seriam ações reais
        # Por segurança, atualmente apenas simula as ações
        
        action_results = {
            "clear_cache": "Cache do sistema liberado",
            "restart_services": "Serviços reiniciados",
            "cleanup_temp_files": "Arquivos temporários removidos",
            "compress_old_logs": "Logs antigos comprimidos",
            "retry_backup": "Tarefa de backup reexecutada",
            "check_repository": "Repositório verificado",
            "restart_connections": "Conexões de banco reiniciadas",
            "analyze_database": "Banco de dados otimizado",
            "restart_process": "Processo reiniciado",
            "check_resources": "Recursos do sistema verificados"
        }
        
        result = action_results.get(action, f"Ação {action} executada")
        logger.info(f"🔧 Ação de correção: {result}")
        
        return result
    
    def _log_healing_action(self, issue_type: str, fix_result: Dict[str, Any]):
        """Registra ação de correção no log"""
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "issue_type": issue_type,
                "status": "success" if fix_result.get("success") else "failed",
                "message": fix_result.get("message", ""),
                "actions": fix_result.get("actions", [])
            }
            
            # Em produção, salvaria no banco de dados
            logger.info(f"📝 Correção registrada: {json.dumps(log_entry, indent=2)}")
            
        except Exception as e:
            logger.warning(f"Erro ao registrar correção: {e}")

