# ==============================================================================
# GBOC System v14.8.2 Enterprise Edition
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

        errors: List[str] = []
        injected_drivers_count = 0

        def _run(cmd, timeout):
            res = subprocess.run(cmd, capture_output=True, timeout=timeout)
            try:
                import ctypes
                enc = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
            except Exception:
                enc = "utf-8"
            out = ((res.stdout or b"") + b"\n" + (res.stderr or b"")).decode(enc, errors="replace").strip()
            return res.returncode, out

        # 1. Injecao de drivers via DISM (resultado conferido)
        if drivers_folder:
            if not os.path.isdir(drivers_folder):
                errors.append(f"pasta de drivers '{drivers_folder}' não encontrada")
                logs.append(f"❌ Pasta de drivers '{drivers_folder}' não encontrada.")
            elif sys.platform == "win32":
                n_inf = len(list(Path(drivers_folder).rglob("*.inf")))
                logs.append(f"Injetando {n_inf} driver(s) (.inf) da pasta '{drivers_folder}' via DISM...")
                try:
                    rc, out = _run(["dism.exe", f"/Image:{vol}", "/Add-Driver", f"/Driver:{drivers_folder}", "/Recurse", "/ForceUnsigned"], 1800)
                except Exception as e:
                    rc, out = -1, str(e)
                if rc == 0:
                    injected_drivers_count = n_inf
                    logs.append(f"✅ DISM concluiu a injeção de {n_inf} driver(s).")
                else:
                    errors.append(f"DISM terminou com código {rc}")
                    logs.append(f"❌ DISM terminou com código {rc}: {out[-400:]}")

        # 2. Servicos de boot na hive SYSTEM offline (somente servicos que EXISTEM na imagem)
        fixed_services: List[str] = []
        failed_services: List[str] = []
        if sys.platform == "win32":
            if not os.path.exists(system_hive):
                errors.append("hive SYSTEM offline não encontrada")
                logs.append(f"❌ Hive SYSTEM offline não encontrada em {system_hive}.")
            else:
                temp_key = "GBOC_OFFLINE_SYS"
                logs.append("Montando hive de registro offline HKLM\\SYSTEM...")
                rc, out = _run(["reg", "load", f"HKLM\\{temp_key}", system_hive], 60)
                if rc != 0:
                    errors.append("não foi possível montar a hive SYSTEM offline")
                    logs.append(f"❌ reg load falhou (código {rc}): {out[:300]}")
                else:
                    try:
                        control_set = "ControlSet001"
                        rcq, outq = _run(["reg", "query", f"HKLM\\{temp_key}\\Select", "/v", "Current"], 30)
                        import re as _re
                        m = _re.search(r"0x([0-9a-fA-F]+)", outq) if rcq == 0 else None
                        if m:
                            control_set = f"ControlSet{int(m.group(1), 16):03d}"
                        for svc in self.CRITICAL_BOOT_SERVICES:
                            svc_key = f"HKLM\\{temp_key}\\{control_set}\\Services\\{svc}"
                            if _run(["reg", "query", svc_key], 15)[0] != 0:
                                continue  # driver nao existe nesta imagem: nao criar chave orfa
                            if _run(["reg", "add", svc_key, "/v", "Start", "/t", "REG_DWORD", "/d", "0", "/f"], 15)[0] == 0:
                                fixed_services.append(svc)
                            else:
                                failed_services.append(svc)
                    finally:
                        rcu, outu = _run(["reg", "unload", f"HKLM\\{temp_key}"], 60)
                        if rcu != 0:
                            errors.append("a hive SYSTEM offline não foi descarregada")
                            logs.append(f"❌ reg unload falhou (código {rcu}): {outu[:300]}. Descarregue manualmente: reg unload HKLM\\{temp_key}")
                    logs.append(f"Control set: {control_set}. Serviços de boot ativados (Start=0): {', '.join(fixed_services) or 'nenhum encontrado na imagem'}")
                    if failed_services:
                        errors.append(f"falha ao ativar {', '.join(failed_services)}")
                        logs.append(f"❌ Falha ao ativar: {', '.join(failed_services)}")
                    if not fixed_services and not failed_services:
                        logs.append("⚠️ Nenhum dos drivers de armazenamento conhecidos existe nesta imagem; injete os drivers da controladora pela pasta de drivers.")

        success = not errors
        if success:
            logs.append("✅ Universal Restore aplicado. Teste o boot no hardware de destino.")
        else:
            logs.append("❌ Universal Restore terminou com problemas: " + "; ".join(errors))

        return {
            "success": success,
            "error": "; ".join(errors) or None,
            "target_volume": vol,
            "injected_drivers_count": injected_drivers_count,
            "activated_boot_services": fixed_services,
            "timestamp": datetime.now().isoformat(),
            "logs": logs
        }


# Singleton global
universal_restore_engine = UniversalRestoreEngine()
