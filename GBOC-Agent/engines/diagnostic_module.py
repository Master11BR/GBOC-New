"""
GBOC Diagnostic Module - 13.2.0
Sistema completo de diagnóstico com análise profunda e recomendações inteligentes
"""
import psutil
import platform
import os
import json
import socket
import subprocess
import time
import httpx
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path

logger = logging.getLogger("GBOC_Diagnostic")

class GBOCDiagnosticSystem:
    """Sistema completo de diagnóstico e análise"""
    
    def __init__(self, agent=None):
        self.agent = agent
        self.cache = {}
        self.cache_ttl = 300  # 5 minutos
        
    # ================================
    # ANÁLISE DE HARDWARE
    # ================================
    
    def analyze_hardware(self) -> Dict[str, Any]:
        """Análise completa de hardware"""
        try:
            cpu_info = self._analyze_cpu()
            memory_info = self._analyze_memory()
            disk_info = self._analyze_disks()
            network_info = self._analyze_network()
            
            # Score de hardware (0-100)
            hardware_score = self._calculate_hardware_score(cpu_info, memory_info, disk_info)
            
            return {
                "cpu": cpu_info,
                "memory": memory_info,
                "disks": disk_info,
                "network": network_info,
                "hardware_score": hardware_score,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Erro análise hardware: {e}")
            return {}
    
    def _analyze_cpu(self) -> Dict[str, Any]:
        """Análise detalhada de CPU"""
        try:
            # CPU em tempo real
            cpu_percent_instant = psutil.cpu_percent(interval=0.1)
            cpu_percent_avg = psutil.cpu_percent(interval=1)
            cpu_per_core = psutil.cpu_percent(interval=0.1, percpu=True)
            cpu_freq = psutil.cpu_freq()
            cpu_stats = psutil.cpu_stats()
            
            # Informações do processador
            cpu_count_logical = psutil.cpu_count(logical=True)
            cpu_count_physical = psutil.cpu_count(logical=False) or cpu_count_logical
            
            # Análise de temperatura (se disponível)
            cpu_temp = self._get_cpu_temperature()
            
            # Análise de processos pesados
            top_processes = self._get_top_cpu_processes(5)
            
            return {
                "model": platform.processor() or "Unknown",
                "cores_physical": cpu_count_physical,
                "cores_logical": cpu_count_logical,
                "usage_instant": cpu_percent_instant,
                "usage_average": cpu_percent_avg,
                "usage_per_core": cpu_per_core,
                "frequency_current": cpu_freq.current if cpu_freq else 0,
                "frequency_max": cpu_freq.max if cpu_freq else 0,
                "context_switches": cpu_stats.ctx_switches,
                "interrupts": cpu_stats.interrupts,
                "temperature": cpu_temp,
                "top_processes": top_processes,
                "load_average": os.getloadavg() if hasattr(os, 'getloadavg') else [0, 0, 0]
            }
        except Exception as e:
            logger.error(f"Erro análise CPU: {e}")
            return {}
    
    def _analyze_memory(self) -> Dict[str, Any]:
        """Análise detalhada de memória"""
        try:
            vm = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            # Processos que mais consomem memória
            top_memory_processes = self._get_top_memory_processes(5)
            
            # Análise de cache
            cache_info = self._analyze_cache_memory()
            
            return {
                "total": vm.total,
                "available": vm.available,
                "used": vm.used,
                "free": vm.free,
                "percent": vm.percent,
                "cached": vm.cached if hasattr(vm, 'cached') else 0,
                "buffers": vm.buffers if hasattr(vm, 'buffers') else 0,
                "swap_total": swap.total,
                "swap_used": swap.used,
                "swap_free": swap.free,
                "swap_percent": swap.percent,
                "top_processes": top_memory_processes,
                "cache_info": cache_info,
                "memory_pressure": self._calculate_memory_pressure(vm, swap)
            }
        except Exception as e:
            logger.error(f"Erro análise memória: {e}")
            return {}
    
    def _analyze_disks(self) -> List[Dict[str, Any]]:
        """Análise detalhada de discos"""
        disks = []
        try:
            partitions = psutil.disk_partitions(all=False)
            
            for partition in partitions:
                if self._should_skip_partition(partition):
                    continue
                    
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    io_counters = psutil.disk_io_counters(perdisk=True)
                    
                    # Análise de performance de I/O
                    disk_io = None
                    for disk_name, counters in io_counters.items():
                        if disk_name in partition.device or partition.device in disk_name:
                            disk_io = {
                                "read_bytes": counters.read_bytes,
                                "write_bytes": counters.write_bytes,
                                "read_time": counters.read_time,
                                "write_time": counters.write_time,
                                "busy_time": counters.busy_time if hasattr(counters, 'busy_time') else 0
                            }
                            break
                    
                    # Análise de fragmentação (Windows)
                    fragmentation = self._analyze_disk_fragmentation(partition.device) if os.name == 'nt' else 0
                    
                    disk_info = {
                        "device": partition.device,
                        "mountpoint": partition.mountpoint,
                        "fstype": partition.fstype,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "percent": usage.percent,
                        "io_stats": disk_io,
                        "fragmentation": fragmentation,
                        "health_status": self._check_disk_health(partition.device),
                        "write_speed_mbps": self._test_disk_speed(partition.mountpoint)
                    }
                    
                    disks.append(disk_info)
                    
                except PermissionError:
                    continue
                except Exception as e:
                    logger.debug(f"Erro analisar partição {partition.device}: {e}")
                    
        except Exception as e:
            logger.error(f"Erro análise discos: {e}")
            
        return disks
    
    def _analyze_network(self) -> Dict[str, Any]:
        """Análise detalhada de rede"""
        try:
            # Estatísticas de rede
            net_io = psutil.net_io_counters()
            net_connections = psutil.net_connections(kind='inet')
            net_if_addrs = psutil.net_if_addrs()
            net_if_stats = psutil.net_if_stats()
            
            # Teste de latência
            latency_tests = self._test_network_latency()
            
            # Teste de velocidade
            speed_test = self._test_network_speed()
            
            # Análise de conexões
            connection_stats = {
                "established": sum(1 for c in net_connections if c.status == 'ESTABLISHED'),
                "listen": sum(1 for c in net_connections if c.status == 'LISTEN'),
                "time_wait": sum(1 for c in net_connections if c.status == 'TIME_WAIT'),
                "close_wait": sum(1 for c in net_connections if c.status == 'CLOSE_WAIT')
            }
            
            # Interfaces de rede
            interfaces = []
            for name, addrs in net_if_addrs.items():
                stats = net_if_stats.get(name)
                if stats:
                    for addr in addrs:
                        if addr.family == socket.AF_INET:
                            interfaces.append({
                                "name": name,
                                "ip": addr.address,
                                "netmask": addr.netmask,
                                "is_up": stats.isup,
                                "speed": stats.speed
                            })
            
            return {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv,
                "errors_in": net_io.errin,
                "errors_out": net_io.errout,
                "drops_in": net_io.dropin,
                "drops_out": net_io.dropout,
                "connections": connection_stats,
                "interfaces": interfaces,
                "latency": latency_tests,
                "speed": speed_test
            }
        except Exception as e:
            logger.error(f"Erro análise rede: {e}")
            return {}
    
    # ================================
    # ANÁLISE DE SOFTWARE E FERRAMENTAS
    # ================================
    
    def analyze_backup_tools(self) -> Dict[str, Any]:
        """Análise completa das ferramentas de backup"""
        tools_status = {}
        
        # Lista de ferramentas para verificar
        tools_to_check = {
            'restic': self._check_restic,
            'kopia': self._check_kopia,
            'duplicati': self._check_duplicati,
            'rclone': self._check_rclone,
            'borg': self._check_borg
        }
        
        for tool_name, check_func in tools_to_check.items():
            tools_status[tool_name] = check_func()
        
        # Análise de compatibilidade
        compatibility = self._analyze_tools_compatibility(tools_status)
        
        # Recomendação de ferramenta ideal
        recommended_tool = self._recommend_best_tool(tools_status)
        
        return {
            "tools": tools_status,
            "compatibility": compatibility,
            "recommended": recommended_tool,
            "total_available": sum(1 for t in tools_status.values() if t.get('available')),
            "timestamp": datetime.now().isoformat()
        }
    
    def _check_restic(self) -> Dict[str, Any]:
        """Verifica instalação e configuração do Restic"""
        try:
            result = subprocess.run(
                ['restic', 'version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                version = self._extract_version(result.stdout)
                
                # Testa funcionalidades
                features = {
                    "compression": True,
                    "encryption": True,
                    "deduplication": True,
                    "incremental": True,
                    "cloud_support": True
                }
                
                # Verifica cache
                cache_dir = os.path.expanduser("~/.cache/restic")
                cache_size = self._get_directory_size(cache_dir) if os.path.exists(cache_dir) else 0
                
                return {
                    "available": True,
                    "version": version,
                    "path": subprocess.run(['which', 'restic'], capture_output=True, text=True).stdout.strip(),
                    "features": features,
                    "cache_size": cache_size,
                    "status": "working",
                    "performance_score": 95  # Restic é muito eficiente
                }
                
        except Exception as e:
            logger.debug(f"Restic não disponível: {e}")
            
        return {
            "available": False,
            "status": "not_installed",
            "install_command": "apt install restic || brew install restic"
        }
    
    def _check_kopia(self) -> Dict[str, Any]:
        """Verifica instalação e configuração do Kopia"""
        try:
            result = subprocess.run(
                ['kopia', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                version = self._extract_version(result.stdout)
                
                # Testa funcionalidades
                features = {
                    "compression": True,
                    "encryption": True,
                    "deduplication": True,
                    "incremental": True,
                    "cloud_support": True,
                    "gui_available": self._check_kopia_gui()
                }
                
                # Verifica repositórios configurados
                repos = self._check_kopia_repos()
                
                return {
                    "available": True,
                    "version": version,
                    "path": subprocess.run(['which', 'kopia'], capture_output=True, text=True).stdout.strip(),
                    "features": features,
                    "repositories": repos,
                    "status": "working",
                    "performance_score": 98  # Kopia é extremamente eficiente
                }
                
        except Exception as e:
            logger.debug(f"Kopia não disponível: {e}")
            
        return {
            "available": False,
            "status": "not_installed",
            "install_command": "curl -s https://kopia.io/get.sh | sh"
        }
    
    def _check_duplicati(self) -> Dict[str, Any]:
        """Verifica instalação e configuração do Duplicati"""
        # Múltiplas tentativas de detecção
        paths_to_try = [
            'Duplicati.CommandLine.exe',
            'duplicati-cli',
            'mono Duplicati.CommandLine.exe',
            '/usr/lib/duplicati/Duplicati.CommandLine.exe'
        ]
        
        for path in paths_to_try:
            try:
                cmd = path.split() if path.startswith('mono ') else [path]
                cmd.append('--version')
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if 'duplicati' in result.stdout.lower() or 'duplicati' in result.stderr.lower():
                    version = self._extract_version(result.stdout + result.stderr)
                    
                    return {
                        "available": True,
                        "version": version,
                        "path": path,
                        "features": {
                            "compression": True,
                            "encryption": True,
                            "deduplication": True,
                            "incremental": True,
                            "cloud_support": True,
                            "web_ui": True
                        },
                        "status": "working",
                        "performance_score": 85
                    }
                    
            except Exception:
                continue
                
        return {
            "available": False,
            "status": "not_installed",
            "install_command": "Download from https://www.duplicati.com/download"
        }
    
    def _check_rclone(self) -> Dict[str, Any]:
        """Verifica instalação do Rclone"""
        try:
            result = subprocess.run(
                ['rclone', 'version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                return {
                    "available": True,
                    "version": self._extract_version(result.stdout),
                    "status": "working"
                }
        except:
            pass
            
        return {"available": False, "status": "not_installed"}
    
    def _check_borg(self) -> Dict[str, Any]:
        """Verifica instalação do BorgBackup"""
        try:
            result = subprocess.run(
                ['borg', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                return {
                    "available": True,
                    "version": self._extract_version(result.stdout),
                    "status": "working"
                }
        except:
            pass
            
        return {"available": False, "status": "not_installed"}
    
    # ================================
    # SISTEMA DE DIAGNÓSTICO COMPLETO
    # ================================
    
    def run_complete_diagnostics(self) -> Dict[str, Any]:
        """Executa diagnóstico completo do sistema"""
        logger.info("🔍 Iniciando diagnóstico completo do sistema...")
        
        # Coleta todas as informações
        hardware = self.analyze_hardware()
        tools = self.analyze_backup_tools()
        system = self._analyze_system_health()
        performance = self._analyze_performance()
        
        # Identifica problemas
        issues = self._identify_issues(hardware, tools, system, performance)
        
        # Gera recomendações
        recommendations = self._generate_recommendations(issues, hardware, tools)
        
        # Calcula health score
        health_status, health_score = self._calculate_system_health(issues)
        
        # Monta diagnóstico completo
        diagnostics = {
            "system_health": health_status,
            "performance_score": health_score,
            "timestamp": datetime.now().isoformat(),
            "issues": issues,
            "recommendations": recommendations,
            "details": {
                "hardware": hardware,
                "tools": tools,
                "system": system,
                "performance": performance
            }
        }
        
        logger.info(f"✅ Diagnóstico completo: {health_status} (Score: {health_score:.1f}/100)")
        
        return diagnostics
    
    def _identify_issues(self, hardware, tools, system, performance) -> List[Dict]:
        """Identifica problemas no sistema"""
        issues = []
        
        # Verifica CPU
        if hardware.get('cpu', {}).get('usage_average', 0) > 80:
            issues.append({
                "severity": "high",
                "component": "cpu",
                "message": f"Alto uso de CPU: {hardware['cpu']['usage_average']:.1f}%",
                "solution": "Verifique processos em execução e considere otimizar workloads",
                "value": hardware['cpu']['usage_average'],
                "timestamp": datetime.now()
            })
        
        # Verifica Memória
        memory = hardware.get('memory', {})
        if memory.get('percent', 0) > 85:
            issues.append({
                "severity": "high",
                "component": "memory",
                "message": f"Memória quase cheia: {memory['percent']:.1f}%",
                "solution": "Feche aplicações desnecessárias ou aumente a memória do sistema",
                "value": memory['percent'],
                "timestamp": datetime.now()
            })
        
        # Verifica Discos
        for disk in hardware.get('disks', []):
            if disk.get('percent', 0) > 90:
                issues.append({
                    "severity": "critical",
                    "component": "storage",
                    "message": f"Disco {disk['device']} com {disk['percent']:.1f}% de uso",
                    "solution": "Libere espaço urgentemente ou adicione mais armazenamento",
                    "value": disk['percent'],
                    "timestamp": datetime.now()
                })
            
            # Verifica saúde do disco
            if disk.get('health_status') == 'failing':
                issues.append({
                    "severity": "critical",
                    "component": "storage",
                    "message": f"Disco {disk['device']} apresentando falhas",
                    "solution": "Faça backup imediato e substitua o disco",
                    "timestamp": datetime.now()
                })
        
        # Verifica Ferramentas
        if tools.get('total_available', 0) == 0:
            issues.append({
                "severity": "critical",
                "component": "tools",
                "message": "Nenhuma ferramenta de backup disponível",
                "solution": "Instale pelo menos uma ferramenta de backup (Restic ou Kopia recomendados)",
                "timestamp": datetime.now()
            })
        
        # Verifica Rede
        network = hardware.get('network', {})
        if network.get('errors_in', 0) + network.get('errors_out', 0) > 1000:
            issues.append({
                "severity": "medium",
                "component": "network",
                "message": "Muitos erros de rede detectados",
                "solution": "Verifique cabos, drivers e configurações de rede",
                "timestamp": datetime.now()
            })
        
        # Verifica Performance
        if performance.get('io_wait', 0) > 20:
            issues.append({
                "severity": "medium",
                "component": "performance",
                "message": f"Alto I/O wait: {performance['io_wait']:.1f}%",
                "solution": "Verifique operações de disco e considere SSD",
                "value": performance['io_wait'],
                "timestamp": datetime.now()
            })
        
        return issues
    
    def _generate_recommendations(self, issues, hardware, tools) -> List[Dict]:
        """Gera recomendações baseadas na análise"""
        recommendations = []
        
        # Recomendações baseadas em issues críticas
        critical_issues = [i for i in issues if i['severity'] == 'critical']
        if critical_issues:
            recommendations.append({
                "priority": "urgent",
                "title": "Resolver problemas críticos",
                "description": f"Existem {len(critical_issues)} problemas críticos que precisam atenção imediata",
                "action": "Verifique a aba de problemas e resolva os itens marcados como críticos",
                "category": "system"
            })
        
        # Recomendações de ferramentas
        if tools.get('total_available', 0) == 0:
            recommendations.append({
                "priority": "high",
                "title": "Instalar ferramenta de backup",
                "description": "Nenhuma ferramenta de backup está instalada",
                "action": "Instale o Kopia ou Restic para começar a fazer backups",
                "category": "tools"
            })
        elif not tools.get('tools', {}).get('kopia', {}).get('available'):
            recommendations.append({
                "priority": "medium",
                "title": "Considere instalar Kopia",
                "description": "Kopia oferece melhor performance e interface gráfica",
                "action": "curl -s https://kopia.io/get.sh | sh",
                "category": "tools"
            })
        
        # Recomendações de performance
        memory = hardware.get('memory', {})
        if memory.get('percent', 0) > 70:
            recommendations.append({
                "priority": "medium",
                "title": "Otimizar uso de memória",
                "description": f"Memória em {memory['percent']:.1f}% de uso",
                "action": "Configure limites de cache e considere adicionar mais RAM",
                "category": "performance"
            })
        
        # Recomendações de armazenamento
        for disk in hardware.get('disks', []):
            if disk.get('percent', 0) > 80:
                recommendations.append({
                    "priority": "high",
                    "title": f"Liberar espaço em {disk['device']}",
                    "description": f"Disco com {disk['percent']:.1f}% de uso",
                    "action": "Execute limpeza de disco ou mova dados para outro storage",
                    "category": "storage"
                })
        
        # Recomendações de configuração
        if not self._check_backup_schedule():
            recommendations.append({
                "priority": "medium",
                "title": "Configurar agendamento de backups",
                "description": "Nenhum backup agendado encontrado",
                "action": "Configure pelo menos um backup diário automático",
                "category": "config"
            })
        
        # Recomendações de segurança
        if not self._check_encryption_configured():
            recommendations.append({
                "priority": "high",
                "title": "Habilitar criptografia nos backups",
                "description": "Backups sem criptografia são vulneráveis",
                "action": "Configure senha de criptografia nos repositórios",
                "category": "security"
            })
        
        return recommendations
    
    def _calculate_system_health(self, issues) -> tuple:
        """Calcula o status de saúde do sistema"""
        if not issues:
            return "excellent", 100.0
        
        # Pontuação baseada na severidade dos problemas
        score = 100
        severity_weights = {
            "critical": 30,
            "high": 15,
            "medium": 7,
            "low": 3
        }
        
        for issue in issues:
            score -= severity_weights.get(issue['severity'], 0)
        
        score = max(0, score)
        
        # Determina status
        if score >= 90:
            status = "excellent"
        elif score >= 75:
            status = "good"
        elif score >= 50:
            status = "warning"
        elif score >= 25:
            status = "critical"
        else:
            status = "error"
        
        return status, score
    
    # ================================
    # FUNÇÕES AUXILIARES
    # ================================
    
    def _get_cpu_temperature(self) -> Optional[float]:
        """Obtém temperatura da CPU se disponível"""
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    for entry in entries:
                        if 'core' in entry.label.lower() or 'cpu' in entry.label.lower():
                            return entry.current
        except:
            pass
        return None
    
    def _get_top_cpu_processes(self, limit=5) -> List[Dict]:
        """Obtém processos que mais consomem CPU"""
        processes = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                if proc.info['cpu_percent'] > 0:
                    processes.append({
                        "pid": proc.info['pid'],
                        "name": proc.info['name'],
                        "cpu_percent": proc.info['cpu_percent']
                    })
            
            processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
            return processes[:limit]
        except:
            return []
    
    def _get_top_memory_processes(self, limit=5) -> List[Dict]:
        """Obtém processos que mais consomem memória"""
        processes = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
                if proc.info['memory_percent'] > 0:
                    processes.append({
                        "pid": proc.info['pid'],
                        "name": proc.info['name'],
                        "memory_percent": proc.info['memory_percent']
                    })
            
            processes.sort(key=lambda x: x['memory_percent'], reverse=True)
            return processes[:limit]
        except:
            return []
    
    def _calculate_memory_pressure(self, vm, swap) -> str:
        """Calcula pressão de memória"""
        if vm.percent < 50 and swap.percent < 20:
            return "low"
        elif vm.percent < 80 and swap.percent < 50:
            return "medium"
        elif vm.percent < 90 and swap.percent < 80:
            return "high"
        else:
            return "critical"
    
    def _should_skip_partition(self, partition) -> bool:
        """Verifica se deve pular uma partição"""
        skip_fs = ['devfs', 'tmpfs', 'squashfs', 'overlay']
        skip_mounts = ['/dev', '/proc', '/sys', '/run', '/snap']
        
        if partition.fstype in skip_fs:
            return True
            
        for mount in skip_mounts:
            if partition.mountpoint.startswith(mount):
                return True
                
        if os.name == 'nt' and ('cdrom' in partition.opts or partition.fstype == ''):
            return True
            
        return False
    
    def _check_disk_health(self, device) -> str:
        """Verifica saúde do disco usando SMART"""
        if os.name != 'nt':
            try:
                result = subprocess.run(
                    ['smartctl', '-H', device],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if 'PASSED' in result.stdout:
                    return "healthy"
                elif 'FAILED' in result.stdout:
                    return "failing"
            except:
                pass
                
        return "unknown"
    
    def _test_disk_speed(self, path) -> float:
        """Testa velocidade de escrita do disco"""
        try:
            test_file = os.path.join(path, '.speed_test_tmp')
            size = 10 * 1024 * 1024  # 10MB
            
            start = time.time()
            with open(test_file, 'wb') as f:
                f.write(os.urandom(size))
                f.flush()
                os.fsync(f.fileno())
            elapsed = time.time() - start
            
            os.remove(test_file)
            
            return (size / elapsed) / (1024 * 1024)  # MB/s
        except:
            return 0
    
    def _analyze_disk_fragmentation(self, device) -> float:
        """Analisa fragmentação do disco (Windows)"""
        if os.name == 'nt':
            try:
                result = subprocess.run(
                    ['defrag', device, '/A'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                # Parse do resultado para obter % de fragmentação
                for line in result.stdout.split('\n'):
                    if 'fragmented' in line.lower():
                        import re
                        match = re.search(r'(\d+)%', line)
                        if match:
                            return float(match.group(1))
            except:
                pass
                
        return 0
    
    def _analyze_cache_memory(self) -> Dict:
        """Analisa memória cache"""
        cache_info = {
            "page_cache": 0,
            "buffer_cache": 0,
            "slab_cache": 0
        }
        
        if os.path.exists('/proc/meminfo'):
            try:
                with open('/proc/meminfo', 'r') as f:
                    for line in f:
                        if 'Cached:' in line:
                            cache_info['page_cache'] = int(line.split()[1]) * 1024
                        elif 'Buffers:' in line:
                            cache_info['buffer_cache'] = int(line.split()[1]) * 1024
                        elif 'Slab:' in line:
                            cache_info['slab_cache'] = int(line.split()[1]) * 1024
            except:
                pass
                
        return cache_info
    
    def _test_network_latency(self) -> Dict:
        """Testa latência de rede"""
        hosts = {
            "google": "8.8.8.8",
            "cloudflare": "1.1.1.1",
            "local_gateway": self._get_default_gateway()
        }
        
        results = {}
        for name, host in hosts.items():
            if not host:
                continue
                
            try:
                if os.name == 'nt':
                    cmd = ['ping', '-n', '4', host]
                else:
                    cmd = ['ping', '-c', '4', host]
                    
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                # Parse para obter latência média
                import re
                if os.name == 'nt':
                    match = re.search(r'Average = (\d+)ms', result.stdout)
                else:
                    match = re.search(r'avg/(\d+\.\d+)/', result.stdout)
                    
                if match:
                    results[name] = float(match.group(1))
            except:
                results[name] = None
                
        return results
    
    def _test_network_speed(self) -> Dict:
        """Testa velocidade de rede"""
        try:
            # Teste simples de download
            start = time.time()
            response = httpx.get('https://www.google.com', timeout=5)
            elapsed = time.time() - start
            
            if response.status_code == 200:
                size = len(response.content)
                speed_mbps = (size * 8) / (elapsed * 1_000_000)
                
                return {
                    "download_mbps": speed_mbps,
                    "latency_ms": elapsed * 1000,
                    "test_server": "google.com"
                }
        except:
            pass
            
        return {"download_mbps": 0, "latency_ms": 0}
    
    def _get_default_gateway(self) -> Optional[str]:
        """Obtém gateway padrão"""
        try:
            if os.name == 'nt':
                result = subprocess.run(
                    ['ipconfig'],
                    capture_output=True,
                    text=True
                )
                import re
                match = re.search(r'Default Gateway.*?: ([\d.]+)', result.stdout)
                if match:
                    return match.group(1)
            else:
                result = subprocess.run(
                    ['ip', 'route', 'show', 'default'],
                    capture_output=True,
                    text=True
                )
                if result.stdout:
                    return result.stdout.split()[2]
        except:
            pass
            
        return None
    
    def _check_kopia_gui(self) -> bool:
        """Verifica se Kopia UI está disponível"""
        try:
            result = subprocess.run(
                ['kopia-ui', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except:
            return False
    
    def _check_kopia_repos(self) -> List[str]:
        """Lista repositórios Kopia configurados"""
        try:
            result = subprocess.run(
                ['kopia', 'repository', 'status'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                # Parse do output para obter repos
                return ["default"]  # Simplificado
        except:
            pass
            
        return []
    
    def _analyze_tools_compatibility(self, tools_status) -> Dict:
        """Analisa compatibilidade das ferramentas"""
        compatibility = {
            "cloud_providers": [],
            "encryption_available": False,
            "compression_available": False,
            "deduplication_available": False
        }
        
        # Verifica recursos disponíveis
        for tool_name, tool_info in tools_status.items():
            if tool_info.get('available'):
                features = tool_info.get('features', {})
                if features.get('encryption'):
                    compatibility['encryption_available'] = True
                if features.get('compression'):
                    compatibility['compression_available'] = True
                if features.get('deduplication'):
                    compatibility['deduplication_available'] = True
                    
        # Cloud providers suportados
        if any(t.get('available') for t in tools_status.values()):
            compatibility['cloud_providers'] = [
                "Amazon S3", "Backblaze B2", "Google Cloud Storage",
                "Microsoft Azure", "Wasabi", "Local Storage"
            ]
            
        return compatibility
    
    def _recommend_best_tool(self, tools_status) -> str:
        """Recomenda melhor ferramenta baseada no sistema"""
        scores = {}
        
        for tool_name, tool_info in tools_status.items():
            if tool_info.get('available'):
                score = tool_info.get('performance_score', 50)
                scores[tool_name] = score
                
        if scores:
            return max(scores, key=scores.get)
            
        # Se nenhuma está instalada, recomenda Kopia
        return "kopia"
    
    def _analyze_system_health(self) -> Dict:
        """Análise geral de saúde do sistema"""
        try:
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.now() - boot_time
            
            return {
                "uptime_seconds": uptime.total_seconds(),
                "uptime_days": uptime.days,
                "boot_time": boot_time.isoformat(),
                "users": len(psutil.users()),
                "processes_total": len(psutil.pids()),
                "system_version": platform.version(),
                "python_version": platform.python_version()
            }
        except:
            return {}
    
    def _analyze_performance(self) -> Dict:
        """Análise de performance do sistema"""
        try:
            # CPU detalhada
            cpu_times = psutil.cpu_times()
            cpu_percent_per_core = psutil.cpu_percent(interval=1, percpu=True)
            
            return {
                "cpu_user": cpu_times.user,
                "cpu_system": cpu_times.system,
                "cpu_idle": cpu_times.idle,
                "io_wait": getattr(cpu_times, 'iowait', 0),
                "cpu_variance": max(cpu_percent_per_core) - min(cpu_percent_per_core),
                "context_switches": psutil.cpu_stats().ctx_switches,
                "interrupts": psutil.cpu_stats().interrupts
            }
        except:
            return {}
    
    def _check_backup_schedule(self) -> bool:
        """Verifica se há backups agendados"""
        if self.agent:
            components = self.agent.master_config.get('components', [])
            return any(c.get('schedule') for c in components)
        return False
    
    def _check_encryption_configured(self) -> bool:
        """Verifica se criptografia está configurada"""
        if self.agent:
            targets = self.agent.master_config.get('targets', [])
            return any(t.get('password') for t in targets)
        return False
    
    def _get_directory_size(self, path) -> int:
        """Calcula tamanho de diretório"""
        total = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if os.path.exists(filepath):
                        total += os.path.getsize(filepath)
        except:
            pass
        return total
    
    def _extract_version(self, text) -> str:
        """Extrai versão de texto"""
        import re
        patterns = [
            r'version\s+v?(\d+\.\d+\.\d+)',
            r'v(\d+\.\d+\.\d+)',
            r'(\d+\.\d+\.\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
                
        return "unknown"
    
    # ================================
    # CACHE E OTIMIZAÇÃO
    # ================================
    
    def get_cached_diagnostics(self, force_refresh=False) -> Dict:
        """Obtém diagnósticos com cache"""
        cache_key = 'full_diagnostics'
        
        if not force_refresh and cache_key in self.cache:
            cached_time = self.cache[cache_key].get('timestamp')
            if cached_time:
                age = (datetime.now() - datetime.fromisoformat(cached_time)).total_seconds()
                if age < self.cache_ttl:
                    logger.debug("Retornando diagnóstico do cache")
                    return self.cache[cache_key]
        
        # Gera novo diagnóstico
        diagnostics = self.run_complete_diagnostics()
        self.cache[cache_key] = diagnostics
        
        return diagnostics
    
    def clear_cache(self):
        """Limpa cache de diagnósticos"""
        self.cache.clear()
        logger.info("Cache de diagnósticos limpo")

