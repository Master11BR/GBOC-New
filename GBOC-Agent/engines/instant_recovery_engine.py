# ==============================================================================
# GBOC System v14.8.2 Enterprise Edition
# Module: Instant Recovery Datastore & NFS/SMB Local Exporter Engine
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import json
import time
import socket
import logging
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("gboc_instant_recovery")


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


class InstantRecoveryDatastoreEngine:
    """
    Motor de Recuperação Instantânea Local (Instant VM Recovery / RTO < 60s).
    Permite expor repositórios de backup descompactados como Datastore SMB/NFS temporário
    diretamente para o Hyper-V ou VMware ESXi, combinando camada Copy-on-Write (CoW).
    Zero-Mock: Executa operações reais de compartilhamento de rede e provisionamento de VM.
    """

    def __init__(self):
        self.active_datastores: Dict[str, Dict[str, Any]] = {}
        self.active_vms: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.hostname = socket.gethostname()

    def start_datastore_share(
        self,
        share_name: str,
        folder_path: str,
        read_only: bool = True,
        protocol: str = "SMB"
    ) -> Dict[str, Any]:
        """
        Cria um compartilhamento de Datastore local (SMB no Windows ou NFS)
        para permitir que o Hypervisor acesse os arquivos de backup diretamente sem cópia.
        """
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Pasta do repositório '{folder_path}' não encontrada.")

        clean_share_name = "".join(c for c in share_name if c.isalnum() or c in ("-", "_"))
        unc_path = f"\\\\{self.hostname}\\{clean_share_name}"

        if sys.platform == "win32":
            # 'Everyone' e localizado ('Todos' no pt-BR): resolve pelo SID universal S-1-1-0
            perm = "-ReadAccess $everyone" if read_only else "-FullAccess $everyone"
            ps_cmd = f"""
                [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
                $ErrorActionPreference = 'Stop'
                $everyone = (New-Object System.Security.Principal.SecurityIdentifier('S-1-1-0')).Translate([System.Security.Principal.NTAccount]).Value
                $existing = Get-SmbShare -Name '{clean_share_name}' -ErrorAction SilentlyContinue
                if ($existing) {{
                    [PSCustomObject]@{{ Status = 'already_exists'; Path = $existing.Path }} | ConvertTo-Json
                }} else {{
                    New-SmbShare -Name '{clean_share_name}' -Path $env:GBOC_DS_PATH {perm} -Description 'GBOC Instant Recovery Datastore' | Out-Null
                    [PSCustomObject]@{{ Status = 'created'; Path = $env:GBOC_DS_PATH }} | ConvertTo-Json
                }}
            """
            try:
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                    env=dict(os.environ, GBOC_DS_PATH=str(folder_path))
                )
            except Exception as e:
                raise RuntimeError(f"Falha ao executar New-SmbShare: {e}")
            if res.returncode != 0:
                raise RuntimeError(f"Compartilhamento SMB não criado: {(res.stderr or res.stdout or '').strip()[:300] or 'código ' + str(res.returncode)}")
        else:
            raise RuntimeError("Datastore SMB disponível apenas no Windows.")

        datastore_info = {
            "share_name": clean_share_name,
            "folder_path": folder_path,
            "unc_path": unc_path,
            "protocol": protocol,
            "read_only": read_only,
            "created_at": datetime.now().isoformat(),
            "status": "ACTIVE"
        }

        with self.lock:
            self.active_datastores[clean_share_name] = datastore_info

        return {
            "status": "success",
            "message": f"Datastore '{clean_share_name}' exportado com sucesso via {protocol}.",
            "datastore": datastore_info
        }

    def stop_datastore_share(self, share_name: str) -> Dict[str, Any]:
        """Remove o compartilhamento de Datastore do sistema."""
        clean_share_name = "".join(c for c in share_name if c.isalnum() or c in ("-", "_"))

        if sys.platform == "win32":
            ps_cmd = f"Remove-SmbShare -Name '{clean_share_name}' -Force -ErrorAction SilentlyContinue"
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                    capture_output=True, text=True, timeout=10
                )
            except Exception as e:
                logger.warning(f"[InstantRecovery] Aviso ao remover SMB Share: {e}")

        with self.lock:
            if clean_share_name in self.active_datastores:
                self.active_datastores[clean_share_name]["status"] = "STOPPED"
                del self.active_datastores[clean_share_name]

        return {
            "status": "success",
            "message": f"Datastore '{clean_share_name}' desativado e removido."
        }

    def start_instant_vm_recovery(
        self,
        backup_image_path: str,
        vm_name: Optional[str] = None,
        memory_mb: int = 4096,
        cpu_cores: int = 2,
        hypervisor: str = "Hyper-V"
    ) -> Dict[str, Any]:
        """
        Executa o fluxo completo de Instant VM Recovery:
        1. Cria Datastore SMB local apontando para a pasta da imagem.
        2. Cria camada de escrita CoW (VHDX diferencial) para proteger a imagem base.
        3. Registra e dispara a VM no Hyper-V local ou exporta conexão para VMware.
        4. Calcula o tempo real de boot (RTO medido).
        """
        if not os.path.exists(backup_image_path):
            raise FileNotFoundError(f"Imagem de backup '{backup_image_path}' não encontrada.")

        start_time = time.time()
        parent_folder = os.path.dirname(backup_image_path)
        img_name = Path(backup_image_path).stem
        vm_id = f"ir_{int(start_time)}"
        resolved_vm_name = vm_name or f"GBOC-Instant-{img_name[:12]}"

        # 1. Exportar Datastore SMB
        share_res = self.start_datastore_share(
            share_name=f"GBOC_IR_{vm_id[-6:]}",
            folder_path=parent_folder,
            read_only=True
        )
        datastore = share_res.get("datastore", {})

        # 2. Criar disco diferencial CoW
        diff_dir = os.path.join(parent_folder, "Instant_VM_Diffs")
        os.makedirs(diff_dir, exist_ok=True)
        diff_vhdx_path = os.path.join(diff_dir, f"{resolved_vm_name}_cow.vhdx")

        logs = [
            f"Datastore de recuperação instantânea provisionado: {datastore.get('unc_path')}",
            f"Criando camada diferencial Copy-on-Write (CoW) em: {diff_vhdx_path}"
        ]

        boot = _hv_boot_vm(resolved_vm_name, diff_vhdx_path, backup_image_path, memory_mb, cpu_cores)
        if not boot.get("ok"):
            _hv_cleanup(resolved_vm_name, diff_vhdx_path)
            share_unc = datastore.get("unc_path")
            if share_unc:
                self.stop_datastore_share(share_unc.split("\\")[-1])
            raise RuntimeError(f"Instant VM Recovery falhou (etapa '{boot.get('stage')}'): {boot.get('message')}")
        logs.append("✅ Disco diferencial CoW criado.")
        logs.append(f"✅ VM '{resolved_vm_name}' em execução no Hyper-V a partir do storage de backup (estado: {boot.get('state')}).")

        rto_seconds = max(0.2, round(time.time() - start_time, 2))

        vm_record = {
            "vm_id": vm_id,
            "vm_name": resolved_vm_name,
            "backup_image": backup_image_path,
            "diff_vhdx": diff_vhdx_path,
            "datastore_share": datastore.get("unc_path"),
            "memory_mb": memory_mb,
            "cpu_cores": cpu_cores,
            "hypervisor": hypervisor,
            "rto_boot_seconds": rto_seconds,
            "status": "RUNNING",
            "started_at": datetime.now().isoformat(),
            "logs": logs
        }

        with self.lock:
            self.active_vms[vm_id] = vm_record

        return {
            "status": "success",
            "message": f"VM iniciada em {rto_seconds}s (tempo medido até o Hyper-V reportar 'Running'; o boot do sistema convidado não é verificado aqui).",
            "vm": vm_record
        }

    def list_active_vms(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.active_vms.values())

    def stop_instant_vm_recovery(self, vm_id: str) -> Dict[str, Any]:
        """Desliga a VM instantânea, remove o disco diferencial e fecha o Datastore temporário."""
        with self.lock:
            vm = self.active_vms.get(vm_id)
            if not vm:
                return {"status": "error", "message": f"VM instantânea {vm_id} não encontrada."}

        vm_name = vm.get("vm_name")
        _hv_cleanup(vm_name, vm.get("diff_vhdx"))

        # Desalocar Datastore SMB se houver
        share_unc = vm.get("datastore_share")
        if share_unc:
            share_name = share_unc.split("\\")[-1]
            self.stop_datastore_share(share_name)

        with self.lock:
            vm["status"] = "STOPPED"
            del self.active_vms[vm_id]

        return {
            "status": "success",
            "message": f"VM instantânea '{vm_name}' finalizada e recursos desalocados com segurança."
        }


# Singleton global
instant_recovery_engine = InstantRecoveryDatastoreEngine()
