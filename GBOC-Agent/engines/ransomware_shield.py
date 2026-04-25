#!/usr/bin/env python3
"""
GBOC v11.4 - Ransomware Shield PRO (Módulo Completo e Produção-Ready)

Módulo autônomo de prevenção ransomware em tempo real.
Integração enterprise com API JSON, graceful shutdown, métricas Prometheus.

DESENVOLVIDO PARA: Luiz Arina - GBOC Cyberforensics Suite
DATA: Março 2026
"""

import logging
import threading
import time
import os
import sys
import json
import random
import signal
import atexit
import subprocess
from typing import Dict, Any, List, Optional, Set, Union
from collections import defaultdict, deque
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
import argparse

# ═══════════════════════════════════════════════════════════════════
# DEPENDÊNCIAS OPCIONAIS (Graceful Fallback)
# ═══════════════════════════════════════════════════════════════════

HAS_PSUTIL = False
HAS_WATCHDOG = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    logging.warning("psutil não disponível - funcionalidades limitadas")

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    Observer = None
    FileSystemEventHandler = object
    logging.warning("watchdog não disponível - sem monitoramento FS")

# ═══════════════════════════════════════════════════════════════════
# DATA CLASSES (Type-Safe + JSON Serialização)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ThreatAlert:
    """Alerta de ameaça detectada."""
    threat_id: str
    type: str
    target: str
    description: str
    severity: str  # critical, high, medium
    timestamp: str
    pid: Optional[int] = None
    actions_taken: List[str] = None
    simulation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class ShieldMetrics:
    """Métricas de performance."""
    uptime_seconds: float
    threats_detected: int
    events_processed: int
    processes_killed: int
    cpu_percent: float
    memory_mb: float
    queue_size: int
    simulation_mode: bool

# ═══════════════════════════════════════════════════════════════════
# BANCO DE DADOS DE AMEAÇAS (Completo e Atualizado 2026)
# ═══════════════════════════════════════════════════════════════════

RANSOMWARE_EXTENSIONS_SET: Set[str] = {
    # Clássicos
    '.encrypted', '.enc', '.locked', '.crypt', '.crypto', '.cry',
    '.locky', '.cerber', '.zepto', '.odin', '.thor', '.aesir',
    '.zzzzz', '.micro', '.xxx', '.ttt', '.vvv', '.ecc',
    '.ezz', '.exx', '.abc', '.aaa', '.bbb', '.ccc',
    # WannaCry & variantes
    '.wncry', '.wncryt', '.wcry', '.onion',
    # Dharma/Five Eyes
    '.dharma', '.wallet', '.arena', '.bip', '.gamma', '.monro', '.heets',
    # Outros conhecidos
    '.adobe', '.neitrino', '.crypted', '.globe', '.purge', '.raid10',
    '.petya', '.mira', '.good', '.blocking', '.sage', '.gryphon',
    '.breaking_bad', '.payrms', '.lechiffre', '.cryptolocker',
    # Ransom notes comuns
    '.comrade', '.fantom', '.cbf', '.lol', '.zxz', '.rmd', '.rrk',
    '.rad', '.radamant', '.kraken', '.darkness', '.crrrt', '.frozen',
    # Ativos 2026 (LockBit, Conti, etc.)
    '.lockbit', '.lockbit2', '.conti', '.hive', '.blackmatter', '.avos',
    '.poly', '.sata', '.belah', '.msop', '.reco', '.phobos', '.nemty',
    '.xtbl', '.id', '.acrypt', '.ultra', '.johnycryptor', '.ecovector',
}

RANSOM_NOTES: Set[str] = {
    'readme.txt', '_readme.txt', 'decrypt.txt', 'how_to_recover.txt',
    'files_encrypted.txt', 'recover.txt', 'ransom.html', 'decript.txt',
    'pay.html', 'bitcoin.txt', 'instructions.txt'
}

HONEYPOTS: Set[str] = {
    'very_important_secret.xlsx', 'confidential_passwords.doc',
    '__backup_important.dat', 'critical_data.json', 'database.bak',
    'passwords.txt', 'secrets.key'
}

VSS_KILL_COMMANDS: List[str] = [
    'vssadmin delete shadows', 'wmic shadowcopy delete', 'bcdedit /set',
    'wbadmin delete catalog', 'powershell.exe -c remove-computerfile'
]

CRITICAL_SYSTEM_PROCESSES: Set[str] = {
    'smss.exe', 'csrss.exe', 'wininit.exe', 'services.exe',
    'lsass.exe', 'winlogon.exe', 'dwm.exe'
}

# ═══════════════════════════════════════════════════════════════════
# CONFIG MANAGER (Arquivo + ENV + Defaults)
# ═══════════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    'monitored_paths': [
        str(Path.home() / 'Desktop'),
        str(Path.home() / 'Documents'),
        str(Path.home() / 'Downloads'),
    ],
    'burst_threshold': 25,
    'burst_window_seconds': 6,
    'entropy_threshold': 7.8,
    'max_entropy_queue': 50,
    'cooldown_seconds': 30,
    'simulation_mode': False,
    'auto_kill_process': True,
    'vss_guard_enabled': True,
    'enabled': True,
    'auto_isolate_network': False,
    'log_level': 'INFO',
    'log_json': False,
}

class Config:
    def __init__(self):
        self._config = DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        """Carrega config: arquivo > ENV > default."""
        # 1. Arquivo
        config_file = os.getenv('GBOC_SHIELD_CONFIG', 'shield_config.json')
        if os.path.exists(config_file):
            try:
                with open(config_file) as f:
                    file_config = json.load(f)
                    self._config.update(file_config)
            except Exception as e:
                logging.error(f"Erro carregando {config_file}: {e}")

        # 2. ENV overrides
        env_overrides = {
            'simulation_mode': os.getenv('SHIELD_SIM', 'false').lower() == 'true',
            'auto_kill_process': os.getenv('SHIELD_KILL', 'true').lower() == 'true',
        }
        self._config.update(env_overrides)

    def __getitem__(self, key):
        return self._config[key]

    def get(self, key, default=None):
        return self._config.get(key, default)

    def update(self, updates: Dict[str, Any]):
        self._config.update(updates)

# ═══════════════════════════════════════════════════════════════════
# LOGGER ESTRUTURADO JSON
# ═══════════════════════════════════════════════════════════════════

def setup_logging(config: Config):
    """Retorna logger dedicado do Shield SEM alterar o root logger do GBOC."""
    logger = logging.getLogger('GBOC.Shield')
    logger.setLevel(getattr(logging, config['log_level'], logging.INFO))
    # Não adiciona handlers — herda do root logger configurado pelo agent_server
    return logger

# ═══════════════════════════════════════════════════════════════════
# EVENT HANDLER OTIMIZADO
# ═══════════════════════════════════════════════════════════════════

class RansomwareEventHandler(FileSystemEventHandler):
    def __init__(self, shield):
        self.shield = shield
        self.events_per_dir = defaultdict(lambda: deque(maxlen=1000))
        self.threat_cooldown = {}

    def on_any_event(self, event):
        """Handler universal para todos eventos FS."""
        if event.is_directory:
            return
            
        self.shield.stats['events_processed'] += 1
        filepath = event.src_path
        event_type = event.event_type
        
        self._analyze_file(filepath, event_type)

    def _analyze_file(self, filepath: str, event_type: str):
        """Análise completa de ameaça."""
        try:
            path = Path(filepath)
            ext = path.suffix.lower()
            name = path.name.lower()
            parent = str(path.parent)
            
            # 1. EXTENSÃO RANSOMWARE (1ms)
            if ext in RANSOMWARE_EXTENSIONS_SET:
                self._raise_alert('ransomware_extension', filepath, f"Ext: {ext}")
                return

            # 2. RANSOM NOTE (ultra-confiável)
            if any(note in name for note in RANSOM_NOTES):
                self._raise_alert('ransom_note', filepath, f"Note: {name}")
                return

            # 3. HONEYPOT ATINGIDO (máxima prioridade)
            if name in HONEYPOTS:
                self._raise_alert('honeypot_hit', filepath, f"Honeypot: {name}", 'critical')
                return

            # 4. BURST DETECTION
            self._check_io_burst(parent)

            # 5. ENTROPIA SAMPLING (0.5% arquivos >1MB)
            if (random.random() < 0.005 and 
                event_type in ('created', 'modified') and 
                path.stat().st_size > 1_000_000):
                self.shield._queue_entropy_check(filepath)

        except Exception as e:
            logging.debug(f"Análise FS falhou: {e}")

    def _check_io_burst(self, parent_dir: str):
        now = time.time()
        events = self.events_per_dir[parent_dir]
        events.append(now)
        
        window = self.shield.config['burst_window_seconds']
        burst_count = sum(1 for t in events if now - t < window)
        
        if burst_count >= self.shield.config['burst_threshold']:
            self._raise_alert('io_burst', parent_dir, f"{burst_count} ops/{window}s", 'critical')
            events.clear()

    def _raise_alert(self, threat_type: str, target: str, desc: str, severity: str = 'high'):
        """Levanta alerta com cooldown."""
        now = time.time()
        cooldown_key = f"{threat_type}:{target}"
        
        if now - self.threat_cooldown.get(cooldown_key, 0) < self.shield.config['cooldown_seconds']:
            return
            
        self.threat_cooldown[cooldown_key] = now
        
        alert = ThreatAlert(
            threat_id=f"{threat_type}_{int(now*1000)}",
            type=threat_type,
            target=target,
            description=desc,
            severity=severity,
            timestamp=datetime.now().isoformat()
        )
        
        self.shield.handle_threat(alert)

# ═══════════════════════════════════════════════════════════════════
# VSS GUARD (Proteção Shadow Copies)
# ═══════════════════════════════════════════════════════════════════

class VSSGuard(threading.Thread):
    def __init__(self, shield):
        super().__init__(daemon=True, name='VSSGuard')
        self.shield = shield
        self._stop = threading.Event()

    def run(self):
        while not self._stop.wait(timeout=1.2):
            if HAS_PSUTIL:
                self._scan_processes()

    def _scan_processes(self):
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                info = proc.info  # dict, NÃO callable
                cmdline = info.get('cmdline') or []
                cmd_str = ' '.join(cmdline).lower()

                for kill_cmd in VSS_KILL_COMMANDS:
                    if kill_cmd.lower() in cmd_str:
                        pid = info['pid']
                        name = info.get('name', 'unknown')
                        
                        alert = ThreatAlert(
                            threat_id=f"vss_{int(time.time()*1000)}",
                            type='vss_attack',
                            target=cmd_str[:100],
                            description=f"VSS delete attempt: {name}",
                            severity='critical',
                            pid=pid,
                            timestamp=datetime.now().isoformat()
                        )
                        
                        self.shield.handle_threat(alert)
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def stop(self):
        self._stop.set()

# ═══════════════════════════════════════════════════════════════════
# PROCESS KILLER SEGURA
# ═══════════════════════════════════════════════════════════════════

class ProcessKiller:
    @staticmethod
    def kill_by_pid(shield, pid: int) -> Dict[str, Any]:
        """Mata processo com verificações de segurança."""
        if shield.config['simulation_mode']:
            return {'killed': False, 'method': 'SIMULATION', 'pid': pid}
        
        result = {'pid': pid, 'killed': False, 'error': None}
        
        if not HAS_PSUTIL:
            result['error'] = 'psutil não disponível'
            return result
        
        try:
            proc = psutil.Process(pid)
            proc_name = proc.name().lower()
            
            # NUNCA matar processos críticos
            if proc_name in CRITICAL_SYSTEM_PROCESSES:
                result['error'] = f'Processo crítico protegido: {proc_name}'
                return result
            
            proc.kill()
            result['killed'] = True
            result['method'] = 'psutil.kill'
            result['name'] = proc_name
            
        except psutil.NoSuchProcess:
            result['error'] = 'Processo não encontrado'
        except psutil.AccessDenied:
            # Fallback taskkill
            try:
                subprocess.run(['taskkill', '/F', '/PID', str(pid)], 
                             capture_output=True, timeout=5)
                result['killed'] = True
                result['method'] = 'taskkill'
            except:
                result['error'] = 'Acesso negado'
        
        return result

# ═══════════════════════════════════════════════════════════════════
# MOTOR PRINCIPAL DO SHIELD
# ═══════════════════════════════════════════════════════════════════

class RansomwareShield:
    """Motor completo de prevenção ransomware."""
    
    _instance: Optional['RansomwareShield'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_init_done'):
            return
        
        self.config = Config()
        self.logger = setup_logging(self.config)
        self._init_done = True
        
        # Estado
        self.running = False
        self.stats = defaultdict(int)
        self.threat_history: deque[ThreatAlert] = deque(maxlen=200)
        self.entropy_queue: deque[str] = deque(maxlen=self.config['max_entropy_queue'])
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        
        # Components
        self.observer: Optional[Observer] = None
        self.handler: Optional[RansomwareEventHandler] = None
        self.vss_guard: Optional[VSSGuard] = None
        self.entropy_thread: Optional[threading.Thread] = None
        
        # Graceful shutdown (signal só funciona na main thread)
        try:
            signal.signal(signal.SIGINT, self._shutdown)
            signal.signal(signal.SIGTERM, self._shutdown)
        except (ValueError, OSError):
            pass  # Não estamos na main thread — OK, agent_server gerencia shutdown
        atexit.register(self.stop)

        self.logger.info("GBOC Ransomware Shield v11.4 inicializado")

    def start(self) -> ShieldMetrics:
        """Inicia proteção completa."""
        with self._lock:
            if self.running:
                return self.get_metrics()

            self.running = True
            self._stop_event.clear()  # Reset para permitir re-start
            self.stats['start_time'] = time.time()
            
            # Filesystem watcher
            if HAS_WATCHDOG:
                self.handler = RansomwareEventHandler(self)
                self.observer = Observer()
                for path in self.config['monitored_paths']:
                    if os.path.exists(path):
                        self.observer.schedule(self.handler, path, recursive=True)
                self.observer.start()
            
            # VSS Guard
            if self.config['vss_guard_enabled']:
                self.vss_guard = VSSGuard(self)
                self.vss_guard.start()
            
            # Entropy worker
            self.entropy_thread = threading.Thread(
                target=self._entropy_worker, daemon=True
            )
            self.entropy_thread.start()
            
            self.logger.critical("🔒 RANSOMWARE SHIELD ATIVO - Proteção completa")
            return self.get_metrics()

    def stop(self):
        """Shutdown gracioso."""
        with self._lock:
            self._stop_event.set()
            self.running = False
            
            if self.observer:
                self.observer.stop()
                self.observer.join(timeout=3)
            
            if self.vss_guard:
                self.vss_guard.stop()
                self.vss_guard.join(timeout=3)
        
        self.logger.info("🔓 Ransomware Shield parado")

    def _shutdown(self, signum=None, frame=None):
        self.logger.info(f"Sinal {signum} - shutdown gracioso")
        self.stop()

    def handle_threat(self, alert: ThreatAlert):
        """Processa ameaça detectada."""
        self.threat_history.append(alert)
        self.stats['threats_detected'] += 1

        self.logger.critical(
            f"🚨 {alert.type.upper()}: {alert.description} | target={alert.target}",
            extra={'threat_id': alert.threat_id, 'pid': alert.pid}
        )

        # Resposta automática: matar processo
        if alert.pid and self.config['auto_kill_process']:
            kill_result = ProcessKiller.kill_by_pid(self, alert.pid)
            if kill_result['killed']:
                self.stats['processes_killed'] += 1
                alert.actions_taken = [f"Processo {alert.pid} morto via {kill_result.get('method', '?')}"]

        # Registrar no banco de dados como alerta
        self._record_alert_db(alert)

        # Para ameaças critical, acionar Guardian (cadeia completa de resposta)
        if alert.severity == 'critical':
            self._trigger_guardian(alert)

    def _record_alert_db(self, alert: ThreatAlert):
        """Registra ameaça no banco como alerta do sistema."""
        try:
            from engines.ransomware_detector import _execute
            _execute("""
                INSERT INTO alerts (type, severity, title, message, source, timestamp, details)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
            """, (
                'ransomware_shield',
                alert.severity,
                f"Shield: {alert.type} — {alert.target[:80]}",
                alert.description,
                'ransomware_shield',
                json.dumps(alert.to_dict(), default=str),
            ))
        except Exception as e:
            self.logger.error(f"Falha ao registrar ameaça no DB: {e}")

    def _trigger_guardian(self, alert: ThreatAlert):
        """Aciona Guardian para resposta completa (snapshot, lock, notificações)."""
        try:
            from engines.ransomware_guardian import get_guardian
            guardian = get_guardian()
            guardian_threat = {
                'threat_detected': True,
                'source': 'ransomware_shield',
                'type': alert.type,
                'description': alert.description,
                'target': alert.target,
                'compromised': 1,
                'missing': 0,
                'total': 0,
                'details': [alert.to_dict()],
                'detected_at': alert.timestamp,
            }
            guardian._handle_threat(guardian_threat)
            self.logger.info(f"Guardian acionado para {alert.threat_id}")
        except Exception as e:
            self.logger.error(f"Falha ao acionar Guardian: {e}")

    def _queue_entropy_check(self, filepath: str):
        """Fila arquivos para análise de entropia."""
        if len(self.entropy_queue) < self.config['max_entropy_queue']:
            self.entropy_queue.append(filepath)

    def _entropy_worker(self):
        """Worker de análise de entropia (sampling)."""
        while self.running and not self._stop_event.wait(timeout=0.8):
            if self.entropy_queue:
                filepath = self.entropy_queue.popleft()
                try:
                    entropy = self._calculate_entropy(filepath)
                    if entropy > self.config['entropy_threshold']:
                        alert = ThreatAlert(
                            threat_id=f"entropy_{int(time.time()*1000)}",
                            type='high_entropy',
                            target=filepath,
                            description=f"Entropia {entropy:.2f}",
                            severity='high',
                            timestamp=datetime.now().isoformat()
                        )
                        self.handle_threat(alert)
                except Exception:
                    pass

    def _calculate_entropy(self, filepath: str) -> float:
        """Calcula entropia Shannon otimizada (0-8 bits/byte)."""
        import math
        try:
            stat = os.stat(filepath)
            if stat.st_size < 10_000:
                return 0.0

            size = min(100_000, stat.st_size)  # Max 100KB
            with open(filepath, 'rb') as f:
                data = f.read(size)

            if not data:
                return 0.0

            length = len(data)
            freq = [0] * 256
            for byte in data:
                freq[byte] += 1

            entropy = 0.0
            for count in freq:
                if count > 0:
                    p = count / length
                    entropy -= p * math.log2(p)

            return round(entropy, 4)
        except Exception:
            return 0.0

    def get_metrics(self) -> ShieldMetrics:
        """Métricas completas."""
        uptime = time.time() - self.stats['start_time'] if self.stats['start_time'] else 0
        
        cpu = 0.0
        memory = 0.0
        try:
            if HAS_PSUTIL:
                cpu = psutil.cpu_percent(interval=None)
                memory = psutil.Process().memory_info().rss / 1024**2
        except:
            pass
        
        return ShieldMetrics(
            uptime_seconds=uptime,
            threats_detected=self.stats['threats_detected'],
            events_processed=self.stats['events_processed'],
            processes_killed=self.stats['processes_killed'],
            cpu_percent=cpu,
            memory_mb=memory,
            queue_size=len(self.entropy_queue),
            simulation_mode=self.config['simulation_mode']
        )

    def get_recent_threats(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Últimas ameaças."""
        return [alert.to_dict() for alert in list(self.threat_history)[-limit:]]

    def add_monitored_path(self, path: str) -> bool:
        """Adiciona path em runtime."""
        if HAS_WATCHDOG and self.observer and os.path.exists(path):
            self.observer.schedule(self.handler, path, recursive=True)
            if path not in self.config['monitored_paths']:
                self.config['monitored_paths'].append(path)
            return True
        return False

# ═══════════════════════════════════════════════════════════════════
# CLI INTERFACE
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="GBOC Ransomware Shield")
    parser.add_argument('--start', action='store_true', help='Iniciar shield')
    parser.add_argument('--stop', action='store_true', help='Parar shield')
    parser.add_argument('--status', action='store_true', help='Status atual')
    parser.add_argument('--config', help='Arquivo de config JSON')
    parser.add_argument('--sim', action='store_true', help='Modo simulação')
    parser.add_argument('--add-path', help='Adicionar path ao monitoramento')
    
    args = parser.parse_args()
    
    shield = RansomwareShield()
    
    if args.config:
        config = json.load(open(args.config))
        shield.config.update(config)
    
    if args.sim:
        shield.config['simulation_mode'] = True
    
    if args.start:
        metrics = shield.start()
        print(json.dumps(asdict(metrics), indent=2))
        try:
            while True:
                time.sleep(30)
                print(".", end='', flush=True)
        except KeyboardInterrupt:
            shield.stop()
    
    elif args.status:
        print(json.dumps(asdict(shield.get_metrics()), indent=2))
        print(json.dumps(shield.get_recent_threats(5), indent=2))
    
    elif args.add_path:
        success = shield.add_monitored_path(args.add_path)
        print(f"Path adicionado: {success}")
    
    else:
        parser.print_help()

# ═══════════════════════════════════════════════════════════════════
# COMPATIBILIDADE COM API (get_shield singleton)
# ═══════════════════════════════════════════════════════════════════

def get_shield(config: Dict[str, Any] = None) -> RansomwareShield:
    """Retorna instância singleton do Shield. Compatível com ransomware_api.py."""
    shield = RansomwareShield()
    if config:
        shield.config.update(config)
    return shield


if __name__ == "__main__":
    main()