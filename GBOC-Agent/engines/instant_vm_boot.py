# ==============================================================================
# GBOC System v14.8.2 Enterprise Edition
# Module: Instant VM Boot & Loopback Virtual Disk Mounting Engine
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import json
import time
import logging
import threading
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger("gboc_instant_vm_boot")


def _hv_boot_vm(name: str, vhd_path: str, parent_path: str, memory_mb: int, cpu_cores: int, timeout: int = 180) -> Dict[str, Any]:
    """
    Cria disco diferencial + VM Geracao 2 no Hyper-V local e confirma o estado 'Running'.
    Tudo com $ErrorActionPreference='Stop' e caminhos via variavel de ambiente.
    Retorna {"ok": bool, "stage": str, "message": str, "state": str|None}.
    """
    import json as _json
    if sys.platform != "win32":
        return {"ok": False, "stage": "platform", "message": "Hyper-V disponível apenas no Windows.", "state": None}
    ps = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$r = [ordered]@{ ok = $false; stage = 'hyperv'; message = ''; state = $null }
try {
    if (-not (Get-Command New-VM -ErrorAction SilentlyContinue)) { throw 'Hyper-V (módulo PowerShell Hyper-V) não está instalado neste servidor.' }
    $r.stage = 'disk'
    New-VHD -Path $env:GBOC_VHD -ParentPath $env:GBOC_PARENT -Differencing | Out-Null
    $r.stage = 'vm'
    $sw = (Get-VMSwitch | Select-Object -First 1).Name
    $p = @{ Name = $env:GBOC_VM; MemoryStartupBytes = [int64]$env:GBOC_MEM * 1MB; VHDPath = $env:GBOC_VHD; Generation = 2 }
    if ($sw) { $p.SwitchName = $sw }
    New-VM @p | Out-Null
    Set-VMProcessor -VMName $env:GBOC_VM -Count ([int]$env:GBOC_CPU)
    $r.stage = 'start'
    Start-VM -Name $env:GBOC_VM
    $r.state = (Get-VM -Name $env:GBOC_VM).State.ToString()
    $r.ok = ($r.state -eq 'Running')
    if (-not $r.ok) { $r.message = "VM criada, mas o estado é $($r.state)." }
} catch {
    $r.message = $_.Exception.Message
}
$r | ConvertTo-Json -Compress
"""
    env = dict(os.environ, GBOC_VM=name, GBOC_VHD=vhd_path, GBOC_PARENT=parent_path,
               GBOC_MEM=str(int(memory_mb)), GBOC_CPU=str(int(cpu_cores)))
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
    except Exception as e:
        return {"ok": False, "stage": "powershell", "message": str(e), "state": None}
    for line in reversed((res.stdout or "").splitlines()):
        if line.strip().startswith("{"):
            try:
                return _json.loads(line.strip())
            except ValueError:
                break
    return {"ok": False, "stage": "powershell", "message": (res.stderr or res.stdout or "").strip()[:400] or f"código {res.returncode}", "state": None}


def _hv_cleanup(name: str, vhd_path: str):
    """Remove VM e disco diferencial criados por _hv_boot_vm (nunca toca no disco pai)."""
    if sys.platform != "win32":
        return
    ps = r"""
$ErrorActionPreference = 'SilentlyContinue'
if (Get-Command Get-VM -ErrorAction SilentlyContinue) {
    if (Get-VM -Name $env:GBOC_VM) { Stop-VM -Name $env:GBOC_VM -TurnOff -Force; Remove-VM -Name $env:GBOC_VM -Force }
}
"""
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, timeout=60, env=dict(os.environ, GBOC_VM=name))
    except Exception:
        pass
    try:
        if vhd_path and os.path.exists(vhd_path):
            os.remove(vhd_path)
    except OSError:
        pass


class InstantVmBootEngine:
    """
    Motor de Inicialização Instantânea de Máquinas Virtuais (Instant VM Boot / RTO < 30s).
    Monta VHDX com camada diferencial Copy-on-Write (CoW) permitindo que o Hyper-V
    ou Proxmox inicialize a VM diretamente do storage de backup em segundos.
    """

    def __init__(self):
        self.running_instances: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()

    def start_instant_vm(
        self,
        source_vhdx_path: str,
        vm_name: Optional[str] = None,
        memory_mb: int = 4096,
        cpu_cores: int = 2,
        hypervisor: str = "Hyper-V"
    ) -> Dict[str, Any]:
        """
        Dispara a inicialização instantânea de uma VM a partir do arquivo VHDX de backup.
        """
        if not os.path.exists(source_vhdx_path):
            raise FileNotFoundError(f"Arquivo VHDX '{source_vhdx_path}' não encontrado.")

        start_ts = time.time()
        instance_id = f"ivm_{int(time.time())}"
        name = vm_name or f"GBOC-InstantVM-{instance_id[-6:]}"
        
        diff_vhdx_dir = os.path.join(os.path.dirname(source_vhdx_path), "Instant_VM_Diffs")
        os.makedirs(diff_vhdx_dir, exist_ok=True)
        diff_vhdx_path = os.path.join(diff_vhdx_dir, f"{name}_diff.vhdx")

        logs = []
        logs.append(f"Criando camada diferencial Copy-on-Write (CoW) para '{os.path.basename(source_vhdx_path)}'...")

        boot = _hv_boot_vm(name, diff_vhdx_path, source_vhdx_path, memory_mb, cpu_cores)
        if not boot.get("ok"):
            _hv_cleanup(name, diff_vhdx_path)
            raise RuntimeError(f"Instant VM não iniciada (etapa '{boot.get('stage')}'): {boot.get('message')}")
        logs.append(f"✅ Disco diferencial criado: {diff_vhdx_path}")
        logs.append(f"✅ VM '{name}' em execução no Hyper-V (estado: {boot.get('state')}).")

        elapsed_boot = max(0.1, round(time.time() - start_ts, 2))

        instance_data = {
            "instance_id": instance_id,
            "vm_name": name,
            "source_vhdx": source_vhdx_path,
            "diff_vhdx": diff_vhdx_path,
            "memory_mb": memory_mb,
            "cpu_cores": cpu_cores,
            "hypervisor": hypervisor,
            "status": "RUNNING",
            "boot_time_seconds": elapsed_boot,
            "started_at": datetime.now().isoformat(),
            "logs": logs
        }

        with self.lock:
            self.running_instances[instance_id] = instance_data

        return instance_data

    def list_instant_vms(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.running_instances.values())

    def stop_instant_vm(self, instance_id: str) -> bool:
        with self.lock:
            inst = self.running_instances.get(instance_id)
            if not inst:
                return False

            _hv_cleanup(inst.get("vm_name"), inst.get("diff_vhdx"))
            inst["status"] = "STOPPED"
            inst["stopped_at"] = datetime.now().isoformat()
            self.running_instances.pop(instance_id, None)
            return True


# Singleton global
instant_vm_boot_engine = InstantVmBootEngine()
