# ==============================================================================
# GBOC System v14.8.2 Enterprise Edition
# Module: Virtual Cloud Drive Mount Engine (Z:\ Drive Letter via VFS)
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import time
import shutil
import logging
import subprocess
import psutil
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("gboc_vfs_mount")


class VirtualDriveMountEngine:
    """
    Motor de Montagem de Backup da Nuvem como Drive Local (VFS Virtual Drive).
    Verifica ferramentas nativas do SO (rclone / WinFsp) e partições reais montadas.
    Zero-Mock: 100% de detecção e operações reais.
    """

    def __init__(self):
        self.mounted_drives: Dict[str, Dict[str, Any]] = {}

    def list_mounted_drives(self) -> List[Dict[str, Any]]:
        """
        Retorna a lista de drives virtuais ativamente registrados ou partições montadas.
        """
        active_letters = set()
        try:
            for part in psutil.disk_partitions(all=True):
                active_letters.add(part.device.rstrip('\\').upper())
        except Exception:
            pass

        # Limpar entradas que já foram desmontadas no SO
        surviving = {}
        for letter, info in self.mounted_drives.items():
            clean_letter = letter.rstrip('\\').upper()
            if clean_letter in active_letters:
                surviving[letter] = info
        self.mounted_drives = surviving

        return list(self.mounted_drives.values())

    def mount_virtual_drive(
        self,
        repository_url: str = "",
        drive_letter: str = "Z:"
    ) -> Dict[str, Any]:
        """
        Monta repositório como letra de unidade de rede/virtual via rclone / WinFsp.
        """
        logs = []
        if not repository_url or not repository_url.strip():
            return {
                "success": False,
                "error": "URL do repositório de nuvem não informada.",
                "logs": ["❌ Falha: URL do repositório não informada."]
            }

        drive_letter = drive_letter.strip().upper()
        if not drive_letter.endswith(":"):
            drive_letter += ":"

        logs.append(f"Verificando disponibilidade da letra de unidade '{drive_letter}'...")

        # Verificar se a letra já está em uso por outro disco
        existing_drives = [p.device.rstrip('\\').upper() for p in psutil.disk_partitions(all=True)]
        if drive_letter in existing_drives:
            logs.append(f"❌ Letra de unidade '{drive_letter}' já está em uso por uma partição existente no host.")
            return {
                "success": False,
                "error": f"A unidade '{drive_letter}' já está em uso no sistema operacional.",
                "logs": logs
            }

        rclone_bin = shutil.which("rclone")
        if not rclone_bin:
            logs.append("⚠️ Utilitário 'rclone' com suporte a VFS/WinFsp não localizado no PATH do sistema operacional.")
            logs.append("Para montar repositórios de nuvem como letra de disco local, instale o rclone e o driver WinFsp.")
            return {
                "success": False,
                "error": "Driver VFS/rclone não instalado no host para montagem de sistema de arquivos virtual.",
                "logs": logs
            }

        logs.append(f"Iniciando processo rclone VFS mount para '{repository_url}' em '{drive_letter}'...")
        try:
            # Comando de montagem real via rclone
            cmd = [rclone_bin, "mount", repository_url, drive_letter, "--vfs-cache-mode", "writes"]
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            # So considera montado quando a letra aparece no sistema (ate 20 s)
            mounted = False
            for _ in range(40):
                if proc.poll() is not None:
                    break
                if os.path.exists(drive_letter + "\\"):
                    mounted = True
                    break
                time.sleep(0.5)

            if not mounted:
                if proc.poll() is None:
                    proc.kill()
                _, stderr = proc.communicate(timeout=10)
                err_msg = (stderr.decode('utf-8', errors='ignore').strip() if stderr else "") or \
                          f"A unidade '{drive_letter}' não apareceu em 20 s (verifique o WinFsp e a URL do repositório)."
                logs.append(f"❌ Erro ao montar: {err_msg[-400:]}")
                return {"success": False, "error": err_msg[-400:], "logs": logs}

            logs.append(f"✅ Drive Virtual '{drive_letter}' montado com sucesso via processo PID #{proc.pid}!")
            drive_info = {
                "drive_letter": drive_letter,
                "repository_url": repository_url,
                "status": "MOUNTED",
                "pid": proc.pid,
                "mounted_at": datetime.now().isoformat(),
                "logs": logs
            }
            self.mounted_drives[drive_letter] = drive_info
            self._procs = getattr(self, "_procs", {})
            self._procs[drive_letter] = proc
            return {"success": True, "drive": drive_info}

        except Exception as e:
            logs.append(f"❌ Exceção ao executar montagem: {e}")
            return {"success": False, "error": str(e), "logs": logs}

    def unmount_virtual_drive(self, drive_letter: str = "Z:") -> Dict[str, Any]:
        drive_letter = drive_letter.strip().upper()
        if not drive_letter.endswith(":"):
            drive_letter += ":"

        info = self.mounted_drives.get(drive_letter)
        if not info:
            return {"success": True, "message": f"Drive '{drive_letter}' não estava montado pelo GBOC."}
        # Encerra o processo rclone que mantem a montagem e confere que a letra sumiu
        proc = getattr(self, "_procs", {}).pop(drive_letter, None)
        try:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            elif info.get("pid"):
                p = psutil.Process(int(info["pid"]))
                if "rclone" in (p.name() or "").lower():
                    p.terminate()
                    p.wait(timeout=10)
        except (psutil.NoSuchProcess, ProcessLookupError):
            pass
        except Exception as e:
            return {"success": False, "error": f"Falha ao encerrar o rclone: {e}"}
        for _ in range(20):
            if not os.path.exists(drive_letter + "\\"):
                break
            time.sleep(0.5)
        if os.path.exists(drive_letter + "\\"):
            return {"success": False, "error": f"A unidade '{drive_letter}' continua montada após encerrar o rclone."}
        self.mounted_drives.pop(drive_letter, None)
        return {"success": True, "message": f"Drive Virtual '{drive_letter}' desmontado."}


# Singleton global
virtual_drive_mount_engine = VirtualDriveMountEngine()
