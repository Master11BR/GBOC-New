# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Module: Hermes Self-Healing Engine — VSS Repair, Disk Guard, Service Watchdog
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================
"""
Hermes Self-Healing Engine — Pilar 2: Auto-Cura Autônoma

70% das falhas de backup no mercado são causadas por:
  1. VSS Writers travados no Windows (estado Failed ou Waiting for completion)
  2. Falta de espaço em disco temporário durante snapshot
  3. Serviços de sistema parados (vss, swprv, schedule, lanmanworkstation)
  4. Jobs de backup presos em loop sem auto-retry inteligente

Este engine monitora e repara todos esses cenários automaticamente,
sem intervenção humana e sem reiniciar o servidor host.
"""

import os
import subprocess
import logging
import threading
import time
import shutil
import glob
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("hermes_self_heal_engine")

# Configurações
DISK_WARN_THRESHOLD = float(os.getenv("HERMES_DISK_WARN_THRESHOLD", "90.0"))   # % — aviso
DISK_CRITICAL_THRESHOLD = float(os.getenv("HERMES_DISK_CRIT_THRESHOLD", "95.0"))  # % — purge
WATCHDOG_INTERVAL_SECONDS = int(os.getenv("HERMES_WATCHDOG_INTERVAL", "120"))  # 2 min


class HermesSelfHealEngine:
    """
    Engine de auto-cura autônoma do Hermes.
    Executa em background monitorando e reparando o ambiente do GBOC Agent.
    """

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._heal_log: List[Dict[str, Any]] = []
        self._max_log = 500

    # ------------------------------------------------------------------
    # Watchdog Loop
    # ------------------------------------------------------------------

    def start_watchdog(self) -> None:
        """Inicia o loop de watchdog em background."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._watchdog_loop,
            name="hermes-self-heal-watchdog",
            daemon=True
        )
        self._thread.start()
        logger.info("[HERMES HEAL] Watchdog de auto-cura iniciado")

    def stop_watchdog(self) -> None:
        """Para o loop de watchdog."""
        self._running = False
        logger.info("[HERMES HEAL] Watchdog de auto-cura encerrado")

    def _watchdog_loop(self) -> None:
        """Loop principal do watchdog (executa a cada WATCHDOG_INTERVAL_SECONDS)."""
        while self._running:
            try:
                self._run_vss_health_check()
                self._run_disk_guard()
                self._run_service_watchdog()
            except Exception as e:
                logger.error(f"[HERMES HEAL] Erro no ciclo de watchdog: {e}")
            time.sleep(WATCHDOG_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    # VSS Writers Auto-Repair
    # ------------------------------------------------------------------

    def repair_vss_writers(self) -> Dict[str, Any]:
        """
        Detecta e repara VSS Writers problemáticos sem reiniciar o servidor.

        Fluxo:
          1. Executa 'vssadmin list writers' para obter estado atual
          2. Identifica writers em estado Failed/Waiting for completion
          3. Para o serviço VSS, re-registra as DLLs críticas
          4. Reinicia VSS e verifica novamente
        """
        result = {
            "action": "vss_repair",
            "timestamp": datetime.now().isoformat(),
            "failed_writers_before": [],
            "failed_writers_after": [],
            "steps_executed": [],
            "success": False,
            "error": None
        }

        try:
            # Passo 1: Listar VSS Writers
            writers_before = self._get_vss_writers_status()
            failed_before = [w for w in writers_before if w.get("state") in ("Failed", "Waiting for completion", "Unknown error")]
            result["failed_writers_before"] = failed_before

            if not failed_before:
                result["success"] = True
                result["message"] = "Nenhum VSS Writer problemático detectado"
                self._log_heal_event("vss_check", "OK", "Nenhum VSS Writer problemático")
                return result

            logger.warning(f"[HERMES HEAL] {len(failed_before)} VSS Writer(s) com problema detectado(s)")

            # Passo 2: Parar serviço VSS
            self._run_command(["net", "stop", "vss", "/y"], result["steps_executed"], "Parando VSS")

            # Passo 3: Re-registrar DLLs críticas do VSS
            vss_dlls = [
                "ole32.dll", "vss_ps.dll", "vssapi.dll",
                "cryptsvc.dll", "msxml2.dll", "msxml3.dll", "msxml4.dll",
            ]
            for dll in vss_dlls:
                self._run_command(["regsvr32", "/s", dll], result["steps_executed"], f"Re-registro {dll}", ignore_error=True)

            # Passo 4: Reiniciar serviço VSS
            self._run_command(["net", "start", "vss"], result["steps_executed"], "Iniciando VSS")

            # Passo 5: Verificar estado após reparo
            writers_after = self._get_vss_writers_status()
            failed_after = [w for w in writers_after if w.get("state") in ("Failed", "Waiting for completion", "Unknown error")]
            result["failed_writers_after"] = failed_after
            result["success"] = len(failed_after) < len(failed_before)

            msg = f"VSS reparado: {len(failed_before)} falhos → {len(failed_after)} falhos"
            self._log_heal_event("vss_repair", "SUCCESS" if result["success"] else "PARTIAL", msg)
            logger.info(f"[HERMES HEAL] {msg}")

        except Exception as e:
            result["error"] = str(e)
            self._log_heal_event("vss_repair", "ERROR", str(e))
            logger.error(f"[HERMES HEAL] Erro no reparo de VSS: {e}")

        return result

    def _get_vss_writers_status(self) -> List[Dict[str, str]]:
        """Obtém o status real dos VSS Writers do sistema."""
        writers = []
        try:
            proc = subprocess.run(
                ["vssadmin", "list", "writers"],
                capture_output=True, text=True, timeout=30,
                creationflags=0x08000000  # CREATE_NO_WINDOW
            )
            current_writer: Dict[str, str] = {}
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.startswith("Writer name:"):
                    if current_writer:
                        writers.append(current_writer)
                    current_writer = {"name": line.replace("Writer name:", "").strip().strip("'")}
                elif line.startswith("State:") and current_writer:
                    state_part = line.replace("State:", "").strip()
                    # Formato: "[1] Stable" → extrai "Stable"
                    current_writer["state"] = state_part.split("]")[-1].strip() if "]" in state_part else state_part
                elif line.startswith("Last error:") and current_writer:
                    current_writer["last_error"] = line.replace("Last error:", "").strip()
            if current_writer:
                writers.append(current_writer)
        except FileNotFoundError:
            logger.debug("[HERMES HEAL] vssadmin não disponível (provavelmente não-Windows)")
        except Exception as e:
            logger.warning(f"[HERMES HEAL] Erro ao listar VSS Writers: {e}")
        return writers

    def _run_vss_health_check(self) -> None:
        """Verifica VSS Writers e repara automaticamente se houver falhas."""
        writers = self._get_vss_writers_status()
        failed = [w for w in writers if w.get("state") in ("Failed", "Waiting for completion")]
        if failed:
            logger.warning(f"[HERMES HEAL] VSS Writers com falha detectados — iniciando reparo automático")
            self.repair_vss_writers()

    # ------------------------------------------------------------------
    # Disk Space Pre-Guard
    # ------------------------------------------------------------------

    def run_disk_guard(self, target_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Monitora o espaço em disco e expurga arquivos temporários seguros
        quando o uso atingir o limiar crítico.

        Arquivos expurgados (somente temp e cache, nunca backups):
          - *.tmp na pasta Windows Temp
          - Caches do Restic/GBOC em data/cache/
          - Logs de debug rotacionados (*.log.1, *.log.2, ...)
        """
        result = {
            "action": "disk_guard",
            "timestamp": datetime.now().isoformat(),
            "drives_checked": [],
            "purge_executed": False,
            "bytes_freed": 0,
            "success": True,
            "error": None
        }

        try:
            # Se nenhum path especificado, verificar disco do sistema
            check_path = target_path or (os.environ.get("SystemDrive", "C:") + "\\")

            total, used, free = shutil.disk_usage(check_path)
            used_pct = (used / total) * 100 if total > 0 else 0

            drive_info = {
                "path": check_path,
                "total_gb": round(total / 1024**3, 2),
                "used_gb": round(used / 1024**3, 2),
                "free_gb": round(free / 1024**3, 2),
                "used_pct": round(used_pct, 1)
            }
            result["drives_checked"].append(drive_info)

            if used_pct >= DISK_CRITICAL_THRESHOLD:
                logger.warning(f"[HERMES HEAL] Disco crítico: {used_pct:.1f}% usado — iniciando expurgo de cache")
                bytes_freed = self._purge_temp_cache()
                result["purge_executed"] = True
                result["bytes_freed"] = bytes_freed
                self._log_heal_event("disk_guard_purge", "SUCCESS",
                                     f"Disco {used_pct:.1f}% — liberados {bytes_freed/1024/1024:.1f} MB")
            elif used_pct >= DISK_WARN_THRESHOLD:
                logger.info(f"[HERMES HEAL] Disco em aviso: {used_pct:.1f}% (limite crítico: {DISK_CRITICAL_THRESHOLD}%)")
                self._log_heal_event("disk_guard_warn", "WARN", f"Disco {used_pct:.1f}% — acima do limiar de aviso")

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            logger.error(f"[HERMES HEAL] Erro no disk guard: {e}")

        return result

    def _purge_temp_cache(self) -> int:
        """Remove arquivos temporários e de cache com segurança. Retorna bytes liberados."""
        bytes_freed = 0
        purge_patterns = []

        # Windows Temp
        win_temp = os.environ.get("TEMP") or os.environ.get("TMP") or "C:\\Windows\\Temp"
        if os.path.isdir(win_temp):
            purge_patterns.extend(glob.glob(os.path.join(win_temp, "*.tmp")))
            purge_patterns.extend(glob.glob(os.path.join(win_temp, "gboc_*")))

        # GBOC Agent cache
        agent_cache = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")
        if os.path.isdir(agent_cache):
            purge_patterns.extend(glob.glob(os.path.join(agent_cache, "*.cache")))

        # Logs rotacionados antigos
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
        if os.path.isdir(logs_dir):
            for ext in ["*.log.1", "*.log.2", "*.log.3", "*.log.4", "*.log.5"]:
                purge_patterns.extend(glob.glob(os.path.join(logs_dir, ext)))

        for filepath in purge_patterns:
            try:
                size = os.path.getsize(filepath)
                os.remove(filepath)
                bytes_freed += size
                logger.debug(f"[HERMES HEAL] Removido: {filepath} ({size} bytes)")
            except Exception:
                pass

        return bytes_freed

    def _run_disk_guard(self) -> None:
        """Executado pelo watchdog a cada ciclo."""
        self.run_disk_guard()

    # ------------------------------------------------------------------
    # Service Watchdog
    # ------------------------------------------------------------------

    def check_and_restart_services(self, service_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Verifica e reinicia serviços críticos do Windows se estiverem parados.

        Serviços monitorados por padrão:
          - vss (Volume Shadow Copy)
          - swprv (Microsoft Software Shadow Copy Provider)
          - schedule (Task Scheduler)
          - lanmanworkstation (Workstation)
        """
        watched_services = service_names or ["vss", "swprv", "schedule", "lanmanworkstation"]
        result = {
            "action": "service_watchdog",
            "timestamp": datetime.now().isoformat(),
            "services_checked": [],
            "services_restarted": [],
            "success": True
        }

        for svc in watched_services:
            svc_result = self._check_service(svc)
            result["services_checked"].append(svc_result)

            if svc_result.get("state") == "stopped":
                logger.warning(f"[HERMES HEAL] Serviço '{svc}' parado — reiniciando automaticamente")
                restart_ok = self._restart_service(svc)
                if restart_ok:
                    result["services_restarted"].append(svc)
                    self._log_heal_event("service_restart", "SUCCESS", f"Serviço '{svc}' reiniciado")
                else:
                    result["success"] = False
                    self._log_heal_event("service_restart", "FAILED", f"Falha ao reiniciar '{svc}'")

        return result

    def _check_service(self, service_name: str) -> Dict[str, str]:
        """Verifica o estado real de um serviço Windows via sc query."""
        try:
            proc = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True, text=True, timeout=10,
                creationflags=0x08000000
            )
            state = "unknown"
            for line in proc.stdout.splitlines():
                if "STATE" in line.upper():
                    parts = line.split()
                    if len(parts) >= 4:
                        state_text = parts[-1].lower()
                        if "running" in state_text:
                            state = "running"
                        elif "stopped" in state_text:
                            state = "stopped"
                        elif "pending" in state_text:
                            state = "pending"
                    break
            return {"service": service_name, "state": state}
        except FileNotFoundError:
            return {"service": service_name, "state": "unavailable", "note": "sc.exe not found"}
        except Exception as e:
            return {"service": service_name, "state": "error", "error": str(e)}

    def _restart_service(self, service_name: str) -> bool:
        """Tenta reiniciar um serviço Windows."""
        try:
            subprocess.run(
                ["net", "start", service_name],
                capture_output=True, timeout=30,
                creationflags=0x08000000
            )
            time.sleep(2)
            status = self._check_service(service_name)
            return status.get("state") == "running"
        except Exception as e:
            logger.error(f"[HERMES HEAL] Erro ao reiniciar serviço '{service_name}': {e}")
            return False

    def _run_service_watchdog(self) -> None:
        """Executado pelo watchdog a cada ciclo."""
        self.check_and_restart_services()

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def _run_command(self, cmd: List[str], steps_log: List[str], description: str, ignore_error: bool = False) -> bool:
        """Executa um comando do sistema e registra o resultado."""
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                creationflags=0x08000000
            )
            success = proc.returncode == 0
            step_entry = f"{'✓' if success else '✗'} {description} (exit={proc.returncode})"
            steps_log.append(step_entry)
            logger.debug(f"[HERMES HEAL] {step_entry}")
            return success
        except FileNotFoundError:
            steps_log.append(f"⚠ {description} — comando não encontrado (possivelmente não-Windows)")
            return ignore_error
        except Exception as e:
            steps_log.append(f"✗ {description} — {e}")
            if not ignore_error:
                logger.warning(f"[HERMES HEAL] Erro ao executar '{' '.join(cmd)}': {e}")
            return False

    def _log_heal_event(self, action: str, status: str, message: str) -> None:
        """Adiciona um evento ao log interno de auto-cura."""
        with self._lock:
            self._heal_log.append({
                "timestamp": datetime.now().isoformat(),
                "action": action,
                "status": status,
                "message": message
            })
            # Manter apenas os últimos N eventos
            if len(self._heal_log) > self._max_log:
                self._heal_log = self._heal_log[-self._max_log:]

    def get_heal_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retorna os últimos eventos de auto-cura registrados."""
        with self._lock:
            return list(reversed(self._heal_log[-limit:]))

    def get_status(self) -> Dict[str, Any]:
        """Retorna o status atual do engine de auto-cura."""
        vss_writers = self._get_vss_writers_status()
        failed_vss = [w for w in vss_writers if w.get("state") in ("Failed", "Waiting for completion")]

        try:
            sys_drive = os.environ.get("SystemDrive", "C:") + "\\"
            total, used, free = shutil.disk_usage(sys_drive)
            disk_pct = round((used / total) * 100, 1) if total > 0 else 0
        except Exception:
            disk_pct = 0

        return {
            "watchdog_running": self._running,
            "watchdog_interval_seconds": WATCHDOG_INTERVAL_SECONDS,
            "disk_warn_threshold_pct": DISK_WARN_THRESHOLD,
            "disk_critical_threshold_pct": DISK_CRITICAL_THRESHOLD,
            "current_disk_used_pct": disk_pct,
            "vss_writers_total": len(vss_writers),
            "vss_writers_failed": len(failed_vss),
            "heal_events_logged": len(self._heal_log),
            "last_heal_events": self.get_heal_log(limit=5)
        }


# Instância global singleton
hermes_self_heal_engine = HermesSelfHealEngine()
