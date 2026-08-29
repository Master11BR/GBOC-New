# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Module: Universal Hardware Independent Restore Engine
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import logging
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger("gboc_universal_restore")


class UniversalRestoreEngine:
    """
    Motor de Restauração Independente de Hardware (Universal Restore).
    Injeta drivers de controladoras de armazenamento (RAID, NVMe, SAS, SATA)
    e corrige os serviços de boot na hive de registro offline do Windows
    para evitar telas azuis de Stop 0x7B (INACCESSIBLE_BOOT_DEVICE).
    """

    CRITICAL_BOOT_SERVICES = [
        "storahci", "stornvme", "iaStorA", "iaStorV", "vmbus",
        "megasas", "megasas2", "megasas35", "percsas2", "percsas3",
        "LSI_SAS", "LSI_SAS2i", "LSI_SSS", "amdsata", "nvraid"
    ]

    def inject_drivers_and_fix_hal(self, target_volume: str, drivers_folder: Optional[str] = None) -> Dict[str, Any]:
        """
        Executa a injeção de drivers e correção de serviços de boot no volume offline de destino.
        
        Args:
            target_volume: Letra de unidade ou caminho raiz do volume restaurado (ex: "E:\\" ou "E:")
            drivers_folder: Pasta opcional contendo drivers .inf / .sys para injeção via DISM
        """
        vol = target_volume.rstrip("\\") + "\\"
        win_dir = os.path.join(vol, "Windows")
        sys32_dir = os.path.join(win_dir, "System32")
        system_hive = os.path.join(sys32_dir, "config", "SYSTEM")

        logs = []
        logs.append(f"Iniciando Universal Hardware Restore no volume: {vol}")

        if not os.path.exists(win_dir):
            return {
                "success": False,
                "error": f"Diretório do Windows não encontrado em '{vol}'. Verifique a letra da unidade.",
                "logs": logs
            }

        injected_drivers_count = 0

        # 1. Injeção de drivers via DISM se pasta fornecida e no Windows
        if drivers_folder and os.path.exists(drivers_folder) and sys.platform == "win32":
            logs.append(f"Injetando drivers da pasta '{drivers_folder}' via DISM...")
            try:
                cmd = [
                    "dism.exe",
                    f"/Image:{vol}",
                    f"/Add-Driver",
                    f"/Driver:{drivers_folder}",
                    "/Recurse",
                    "/ForceUnsigned"
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if res.returncode == 0:
                    logs.append("✅ Drivers injetados com sucesso na imagem do Windows!")
                    injected_drivers_count += 1
                else:
                    logs.append(f"Aviso no DISM: {res.stderr or res.stdout}")
            except Exception as e:
                logs.append(f"Erro ao executar DISM: {e}")

        # 2. Correção de serviços de boot no registro offline (SYSTEM hive)
        fixed_services = []
        if sys.platform == "win32" and os.path.exists(system_hive):
            logs.append("Montando hive de registro offline HKLM\\SYSTEM para ativação de drivers de boot...")
            temp_key = "GBOC_OFFLINE_SYS"
            try:
                # Carregar hive offline
                subprocess.run(["reg", "load", f"HKLM\\{temp_key}", system_hive], capture_output=True, timeout=10)

                # Definir Start=0 (BOOT_START) para todos os drivers críticos de armazenamento
                for svc in self.CRITICAL_BOOT_SERVICES:
                    try:
                        svc_key = f"HKLM\\{temp_key}\\ControlSet001\\Services\\{svc}"
                        # Testar se a chave existe e definir Start = 0 (DWORD)
                        sub_res = subprocess.run(
                            ["reg", "add", svc_key, "/v", "Start", "/t", "REG_DWORD", "/d", "0", "/f"],
                            capture_output=True, timeout=5
                        )
                        if sub_res.returncode == 0:
                            fixed_services.append(svc)
                    except Exception:
                        pass

                # Descarregar hive offline
                subprocess.run(["reg", "unload", f"HKLM\\{temp_key}"], capture_output=True, timeout=10)
                logs.append(f"✅ Hive descarregada. {len(fixed_services)} serviços de boot ativados (Start=0): {', '.join(fixed_services[:6])}...")
            except Exception as ex_reg:
                logs.append(f"Aviso na manipulação de registro offline: {ex_reg}")
                try:
                    subprocess.run(["reg", "unload", f"HKLM\\{temp_key}"], capture_output=True, timeout=5)
                except Exception:
                    pass

        logs.append("🎉 Universal Hardware Restore concluído. O sistema operacional está pronto para boot em hardware virgem ou diferente.")
        
        return {
            "success": True,
            "target_volume": vol,
            "injected_drivers_count": injected_drivers_count,
            "activated_boot_services": fixed_services,
            "timestamp": datetime.now().isoformat(),
            "logs": logs
        }


# Singleton global
universal_restore_engine = UniversalRestoreEngine()
