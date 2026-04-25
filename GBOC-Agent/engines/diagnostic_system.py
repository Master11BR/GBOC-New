#!/usr/bin/env python3
"""
GBOC Agent 11.7c - Sistema de Diagnóstico
Engine para diagnósticos completos do sistema
"""

import os
import platform
import psutil
import subprocess
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import sqlite3

logger = logging.getLogger("DiagnosticSystem")

class DiagnosticSystem:
    """Sistema de diagnóstico completo para GBOC Agent"""
    
    def __init__(self, core):
        """Inicializa o sistema de diagnóstico"""
        self.core = core
        self.version = "11.7c"

        self.version = "11.7c"
        self.initialized = False
        
        try:
            self._initialize()
            logger.info("[SUCCESS] DiagnosticSystem inicializado")
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar DiagnosticSystem: {e}")
    
    def _initialize(self):
        """Inicialização interna"""
        # Verificar se pode acessar informações básicas do sistema
        try:
            psutil.cpu_percent(interval=0.1)
            psutil.virtual_memory()
            self.initialized = True
        except Exception as e:
            logger.warning(f"⚠️ Inicialização limitada: {e}")
    
    def run_quick_diagnostic(self) -> Dict[str, Any]:
        """Executa diagnóstico rápido"""
        try:
            start_time = datetime.now()
            
            # Métricas básicas
            cpu_percent = psutil.cpu_percent(interval=0.5)
            memory = psutil.virtual_memory()
            
            # Calcular health score
            health_score = self._calculate_health_score(cpu_percent, memory.percent)
            
            result = {
                "timestamp": datetime.now().isoformat(),
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "overall_health": health_score,
                "status": self._get_health_status(health_score),
                "system": {
                    "cpu_percent": round(cpu_percent, 1),
                    "memory_percent": round(memory.percent, 1),
                    "platform": platform.system(),
                    "hostname": platform.node()
                },
                "warnings": [],
                "recommendations": self._get_recommendations(cpu_percent, memory.percent)
            }
            
            # Adicionar warnings se necessário
            if cpu_percent > 80:
                result["warnings"].append("CPU usage high")
            if memory.percent > 85:
                result["warnings"].append("Memory usage high")
            
            logger.info(f"✅ Diagnóstico rápido concluído - Health: {health_score}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Erro no diagnóstico rápido: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "overall_health": 0,
                "status": "error",
                "error": str(e)
            }
    
    def run_full_diagnostic(self) -> Dict[str, Any]:
        """Executa diagnóstico completo"""
        try:
            start_time = datetime.now()
            
            # Coletar todas as informações
            system_info = self._get_system_info()
            hardware_info = self._get_hardware_info()
            storage_info = self._get_storage_info()
            network_info = self._get_network_info()
            process_info = self._get_process_info()
            backup_engines = self._check_backup_engines()
            database_info = self._check_database()
            
            # Calcular health score detalhado
            health_details = self._calculate_detailed_health({
                "system": system_info,
                "hardware": hardware_info,
                "storage": storage_info,
                "engines": backup_engines
            })
            
            result = {
                "timestamp": datetime.now().isoformat(),
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "overall_health": health_details["score"],
                "status": self._get_health_status(health_details["score"]),
                "details": {
                    "system": system_info,
                    "hardware": hardware_info,
                    "storage": storage_info,
                    "network": network_info,
                    "processes": process_info,
                    "backup_engines": backup_engines,
                    "database": database_info
                },
                "health_breakdown": health_details["breakdown"],
                "warnings": health_details["warnings"],
                "recommendations": health_details["recommendations"]
            }
            
            logger.info(f"✅ Diagnóstico completo concluído - Health: {health_details['score']}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Erro no diagnóstico completo: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "overall_health": 0,
                "status": "error",
                "error": str(e)
            }
    
    def check_system_requirements(self) -> Dict[str, Any]:
        """Verifica requisitos do sistema"""
        try:
            requirements = {
                "python_version": {"min": "3.8", "current": platform.python_version()},
                "memory_gb": {"min": 4, "current": round(psutil.virtual_memory().total / (1024**3), 1)},
                "disk_space_gb": {"min": 10, "current": round(psutil.disk_usage('/').free / (1024**3), 1)},
                "platform": {"supported": ["Windows", "Linux", "Darwin"], "current": platform.system()}
            }
            
            # Verificar cada requisito
            checks = {}
            for req_name, req_data in requirements.items():
                if req_name == "python_version":
                    current_version = tuple(map(int, req_data["current"].split('.')))
                    min_version = tuple(map(int, req_data["min"].split('.')))
                    checks[req_name] = current_version >= min_version
                elif req_name in ["memory_gb", "disk_space_gb"]:
                    checks[req_name] = req_data["current"] >= req_data["min"]
                elif req_name == "platform":
                    checks[req_name] = req_data["current"] in req_data["supported"]
            
            all_passed = all(checks.values())
            
            return {
                "all_requirements_met": all_passed,
                "requirements": requirements,
                "checks": checks,
                "status": "passed" if all_passed else "failed"
            }
            
        except Exception as e:
            logger.error(f"❌ Erro na verificação de requisitos: {e}")
            return {"status": "error", "error": str(e)}
    
    def _calculate_health_score(self, cpu_percent: float, memory_percent: float) -> int:
        """Calcula score de saúde básico"""
        try:
            score = 100
            
            # Penalidades baseadas no uso
            if cpu_percent > 90: score -= 30
            elif cpu_percent > 80: score -= 20
            elif cpu_percent > 70: score -= 10
            
            if memory_percent > 95: score -= 25
            elif memory_percent > 85: score -= 15
            elif memory_percent > 75: score -= 5
            
            return max(0, min(100, score))
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
    
    def _get_recommendations(self, cpu_percent: float, memory_percent: float) -> List[str]:
        """Gera recomendações baseadas nas métricas"""
        recommendations = []
        
        if cpu_percent > 80:
            recommendations.append("Considere otimizar ou reduzir processos de backup simultâneos")
        if memory_percent > 85:
            recommendations.append("Monitore uso de memória e considere aumentar RAM")
        if cpu_percent < 20 and memory_percent < 50:
            recommendations.append("Sistema com recursos disponíveis - pode executar mais tarefas")
        
        if not recommendations:
            recommendations.append("Sistema funcionando adequadamente")
        
        return recommendations
    
    def _get_system_info(self) -> Dict[str, Any]:
        """Coleta informações do sistema"""
        try:
            return {
                "platform": platform.system(),
                "platform_release": platform.release(),
                "platform_version": platform.version(),
                "architecture": platform.machine(),
                "hostname": platform.node(),
                "python_version": platform.python_version(),
                "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
                "uptime_hours": round((datetime.now() - datetime.fromtimestamp(psutil.boot_time())).total_seconds() / 3600, 1)
            }
        except Exception as e:
            logger.warning(f"Erro ao coletar info do sistema: {e}")
            return {}
    
    def _get_hardware_info(self) -> Dict[str, Any]:
        """Coleta informações de hardware"""
        try:
            cpu_freq = psutil.cpu_freq()
            return {
                "cpu_count_physical": psutil.cpu_count(logical=False),
                "cpu_count_logical": psutil.cpu_count(logical=True),
                "cpu_frequency_mhz": round(cpu_freq.current) if cpu_freq else None,
                "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
                "memory_available_gb": round(psutil.virtual_memory().available / (1024**3), 2)
            }
        except Exception as e:
            logger.warning(f"Erro ao coletar info de hardware: {e}")
            return {}
    
    def _get_storage_info(self) -> Dict[str, Any]:
        """Coleta informações de armazenamento"""
        try:
            partitions = []
            for partition in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    partitions.append({
                        "device": partition.device,
                        "mountpoint": partition.mountpoint,
                        "fstype": partition.fstype,
                        "total_gb": round(usage.total / (1024**3), 1),
                        "used_gb": round(usage.used / (1024**3), 1),
                        "free_gb": round(usage.free / (1024**3), 1),
                        "percent_used": round((usage.used / usage.total) * 100, 1)
                    })
                except PermissionError:
                    continue
            
            return {"partitions": partitions}
        except Exception as e:
            logger.warning(f"Erro ao coletar info de storage: {e}")
            return {}
    
    def _get_network_info(self) -> Dict[str, Any]:
        """Coleta informações de rede"""
        try:
            import socket
            
            hostname = socket.gethostname()
            try:
                local_ip = socket.gethostbyname(hostname)
            except:
                local_ip = "127.0.0.1"
            
            return {
                "hostname": hostname,
                "local_ip": local_ip,
                "network_interfaces": len(psutil.net_if_addrs())
            }
        except Exception as e:
            logger.warning(f"Erro ao coletar info de rede: {e}")
            return {}
    
    def _get_process_info(self) -> Dict[str, Any]:
        """Coleta informações de processos"""
        try:
            processes = list(psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']))
            gboc_processes = []
            
            for proc in processes:
                try:
                    if 'gboc' in proc.info['name'].lower() or 'agent' in proc.info['name'].lower():
                        gboc_processes.append(proc.info)
                except:
                    continue
            
            return {
                "total_processes": len(processes),
                "gboc_processes": len(gboc_processes)
            }
        except Exception as e:
            logger.warning(f"Erro ao coletar info de processos: {e}")
            return {}
    
    def _check_backup_engines(self) -> Dict[str, Dict[str, Any]]:
        """Verifica engines de backup instalados"""
        engines = {
            "restic": {"name": "Restic", "installed": False, "version": None},
            "kopia": {"name": "Kopia", "installed": False, "version": None},
            "duplicati": {"name": "Duplicati", "installed": False, "version": None},
            "borg": {"name": "Borg", "installed": False, "version": None}
        }
        
        for engine_name in engines.keys():
            try:
                if platform.system() == "Windows":
                    result = subprocess.run([engine_name, "--version"], 
                                          capture_output=True, timeout=5,
                                          creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    result = subprocess.run([engine_name, "--version"], 
                                          capture_output=True, timeout=5)
                
                if result.returncode == 0:
                    engines[engine_name]["installed"] = True
                    engines[engine_name]["version"] = result.stdout.decode().strip()[:100]
                    
            except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
                pass  # Engine não instalado ou erro - normal
            except Exception as e:
                logger.debug(f"Erro ao verificar {engine_name}: {e}")
        
        return engines
    
    def _check_database(self) -> Dict[str, Any]:
        """Verifica status do banco de dados"""
        try:
            if not os.path.exists(self.db_path):
                return {"status": "not_found", "size_mb": 0, "tables": 0}
            
            size_mb = round(os.path.getsize(self.db_path) / (1024 * 1024), 2)
            
            # Tentar conectar
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """)
                tables = [row[0] for row in cursor.fetchall()]
            
            return {
                "status": "connected",
                "size_mb": size_mb,
                "tables": len(tables),
                "table_names": tables
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "size_mb": 0,
                "tables": 0
            }
    
    def _calculate_detailed_health(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Calcula health score detalhado"""
        try:
            scores = {"cpu": 100, "memory": 100, "storage": 100, "engines": 100}
            warnings = []
            recommendations = []
            
            # Score hardware
            if "hardware" in data:
                hw = data["hardware"]
                memory_total = hw.get("memory_total_gb", 0)
                memory_available = hw.get("memory_available_gb", 0)
                
                if memory_total > 0:
                    memory_usage_percent = ((memory_total - memory_available) / memory_total) * 100
                    if memory_usage_percent > 85:
                        scores["memory"] = 50
                        warnings.append("High memory usage")
                        recommendations.append("Monitor memory usage")
            
            # Score storage
            if "storage" in data and data["storage"].get("partitions"):
                storage_issues = 0
                for partition in data["storage"]["partitions"]:
                    if partition.get("percent_used", 0) > 90:
                        storage_issues += 1
                
                if storage_issues > 0:
                    scores["storage"] = max(30, 100 - (storage_issues * 20))
                    warnings.append(f"{storage_issues} partition(s) almost full")
                    recommendations.append("Free up disk space")
            
            # Score engines
            if "engines" in data:
                installed_count = len([e for e in data["engines"].values() if e.get("installed")])
                total_count = len(data["engines"])
                if total_count > 0:
                    scores["engines"] = int((installed_count / total_count) * 100)
                    if scores["engines"] < 50:
                        warnings.append("Few backup engines installed")
                        recommendations.append("Install more backup engines")
            
            overall_score = int(sum(scores.values()) / len(scores))
            
            if not warnings:
                recommendations.append("System running optimally")
            
            return {
                "score": overall_score,
                "breakdown": scores,
                "warnings": warnings,
                "recommendations": recommendations
            }
            
        except Exception as e:
            logger.warning(f"Erro no cálculo de health detalhado: {e}")
            return {
                "score": 75,
                "breakdown": {"cpu": 75, "memory": 75, "storage": 75, "engines": 75},
                "warnings": ["Error calculating detailed health"],
                "recommendations": ["System check recommended"]
            }

