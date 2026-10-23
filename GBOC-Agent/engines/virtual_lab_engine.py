# ==============================================================================
# GBOC System v14.8.2 Enterprise Edition
# Module: Isolated Virtual Lab & Anti-Collision Network Sandbox
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import time
import logging
import subprocess
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger("gboc_virtual_lab")


class VirtualLabSandboxEngine:
    """
    Motor de Virtual Lab Isolado com Proteção Anti-Colisão de Rede e Validação SureRestore.
    Zero-Mock: Ciclo de vida real de sandbox com Hyper-V, verificação de heartbeat e teardown.
    """

    def __init__(self):
        # dentro da pasta do Agente (antes: relativo ao diretorio atual do processo)
        from core.gboc_paths import data_dir as _gboc_data_dir
        self.sandbox_dir = _gboc_data_dir("dr_sandbox", create=False)
        try:
            self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def run_isolated_boot_verification(
        self,
        snapshot_id: str,
        vm_name: Optional[str] = None,
        disk_path: Optional[str] = None,
        timeout_seconds: int = 120
    ) -> Dict[str, Any]:
        start_time = time.time()
        lab_id = f"vlab_{int(time.time())}"
        import re as _re
        # Nome e caminhos entram em scripts PowerShell: nome restrito e caminhos sem aspas
        name = _re.sub(r"[^\w.-]", "_", vm_name or f"GBOC-Sandbox-{str(snapshot_id)[:8]}")[:64]
        if disk_path and ("'" in disk_path or "`" in disk_path or "$" in disk_path):
            return {"success": False, "status": "Inconclusivo", "lab_id": lab_id,
                    "error": "Caminho do VHDX contém caracteres não permitidos (', `, $).",
                    "logs": [f"❌ Caminho inválido: {disk_path}"]}

        logs = [f"Iniciando verificação de Virtual Lab Isolado para o Snapshot #{snapshot_id}"]

        if sys.platform != "win32":
            logs.append("❌ Virtual Lab isolado com Hyper-V requer ambiente Windows Server / Windows 11 com Hyper-V.")
            return {
                "success": False,
                "status": "Inconclusivo",
                "lab_id": lab_id,
                "error": "Ambiente Windows Hyper-V não detectado.",
                "logs": logs
            }

        # 1. Verificar se o Hyper-V está ativo no host
        ps_check = "Get-Command New-VM -ErrorAction SilentlyContinue"
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_check],
            capture_output=True, text=True, timeout=10
        )
        if not res.stdout.strip():
            logs.append("❌ Módulo Hyper-V (New-VM / New-VMSwitch) não está disponível no sistema operacional host.")
            return {
                "success": False,
                "status": "Inconclusivo",
                "lab_id": lab_id,
                "error": "Hyper-V não instalado ou desabilitado no host. A validação de boot requer Hyper-V.",
                "logs": logs
            }

        # 2. Configurar switch privado isolado real (Zero-Collision)
        logs.append("Configurando switch virtual privado isolado 'GBOC-Isolated-Lab'...")
        ps_net = """
            $ErrorActionPreference = 'Stop'
            if (!(Get-VMSwitch -Name 'GBOC-Isolated-Lab' -ErrorAction SilentlyContinue)) {
                New-VMSwitch -Name 'GBOC-Isolated-Lab' -SwitchType Private -Notes 'GBOC Isolated Sandbox Network' | Out-Null
            }
            if (Get-VMSwitch -Name 'GBOC-Isolated-Lab' -ErrorAction SilentlyContinue) {
                Write-Output "SWITCH_READY"
            }
        """
        switch_ready = False
        try:
            net_res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_net],
                capture_output=True, text=True, timeout=20
            )
            if "SWITCH_READY" in net_res.stdout:
                switch_ready = True
                logs.append("✅ Switch virtual privado 'GBOC-Isolated-Lab' ativo (100% isolado da produção).")
            else:
                logs.append("⚠️ Aviso: Falha ao confirmar switch virtual privado Hyper-V.")
        except Exception as e:
            logs.append(f"Aviso de rede Hyper-V: {e}")

        # 3. Validar disco virtual a ser conectado
        resolved_disk = None
        if disk_path and os.path.exists(disk_path):
            resolved_disk = disk_path
        else:
            # Buscar VHDX de recuperação nos diretórios de exportação
            from core.gboc_paths import data_dir as _gboc_data_dir
            # pasta atual do DR + a antiga (exportacoes feitas por versoes anteriores)
            # So aceita imagem que corresponda ao snapshot pedido (antes: qualquer .vhdx, e o resultado
            # era atribuido ao snapshot errado)
            candidates = list(_gboc_data_dir("dr_exports", create=False).glob("*.vhdx")) + list(Path("C:/GBOC-DR").glob("*.vhdx"))
            sid = str(snapshot_id or "").lower()
            matches = [c for c in candidates if sid and sid in c.name.lower()]
            if len(matches) == 1:
                resolved_disk = str(matches[0])
            elif len(matches) > 1:
                logs.append(f"⚠️ Mais de uma imagem corresponde ao snapshot {snapshot_id}: informe o caminho do VHDX.")

        if not resolved_disk or not os.path.exists(resolved_disk):
            logs.append(f"⚠️ Disco virtual de recuperação para snapshot {snapshot_id} não localizado em disco.")
            logs.append("ℹ️ Nenhuma validação de boot foi executada: gere/exporte o VHDX de recuperação e repita o teste.")
            duration = round(time.time() - start_time, 2)
            return {
                "success": False,
                "status": "Inconclusivo",
                "error": "VHDX de recuperação não encontrado — boot não validado.",
                "lab_id": lab_id,
                "snapshot_id": snapshot_id,
                "vm_name": name,
                "hyperv_switch": "GBOC-Isolated-Lab",
                "duration_seconds": duration,
                "evidence": {
                    "hyperv_available": True,
                    "switch_isolated": switch_ready,
                    "disk_attached": False,
                    "reason": "VHDX de recuperação não encontrado para boot dinâmico."
                },
                "timestamp": datetime.now().isoformat(),
                "logs": logs
            }

        # 4. Criar camada diferencial (Copy-on-Write) para não modificar a imagem original
        diff_vhdx = str(self.sandbox_dir / f"{name}_diff.vhdx")
        logs.append(f"Criando disco diferencial CoW isolado: {os.path.basename(diff_vhdx)}...")
        ps_diff = f"""
            $ErrorActionPreference = 'Stop'
            New-VHD -ParentPath '{resolved_disk}' -Path '{diff_vhdx}' -Differencing -Force | Out-Null
            Write-Output "DIFF_VHDX_READY"
        """
        diff_ok = False
        try:
            diff_res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_diff],
                capture_output=True, text=True, timeout=60
            )
            diff_ok = "DIFF_VHDX_READY" in (diff_res.stdout or "") and os.path.exists(diff_vhdx)
            diff_err = (diff_res.stderr or diff_res.stdout or "").strip()[:300]
        except Exception as ex_diff:
            diff_err = str(ex_diff)
        if not diff_ok:
            # Nunca dar boot na imagem original: isso alteraria o proprio backup
            logs.append(f"❌ Disco diferencial não criado ({diff_err or 'sem mensagem'}); teste cancelado para não alterar a imagem do backup.")
            return {
                "success": False, "status": "Inconclusivo", "lab_id": lab_id, "snapshot_id": snapshot_id,
                "vm_name": name, "error": "Falha ao criar o disco diferencial (CoW).",
                "duration_seconds": round(time.time() - start_time, 2),
                "timestamp": datetime.now().isoformat(), "logs": logs
            }

        # 5. Provisionar VM temporária no Hyper-V
        logs.append(f"Criando Máquina Virtual de teste '{name}' (Geração 2 / UEFI, Switch: GBOC-Isolated-Lab)...")
        ps_vm = f"""
            $ErrorActionPreference = 'Stop'
            # Remover VM se já existir com o mesmo nome
            if (Get-VM -Name '{name}' -ErrorAction SilentlyContinue) {{
                Stop-VM -Name '{name}' -TurnOff -Force -ErrorAction SilentlyContinue | Out-Null
                Remove-VM -Name '{name}' -Force -ErrorAction SilentlyContinue | Out-Null
            }}
            $vm = New-VM -Name '{name}' -MemoryStartupBytes 2GB -VHDPath '{diff_vhdx}' -SwitchName 'GBOC-Isolated-Lab' -Generation 2 -ErrorAction SilentlyContinue
            if ($vm) {{
                Set-VM -Name '{name}' -AutomaticCheckpointsEnabled $false | Out-Null
                Start-VM -Name '{name}' -ErrorAction SilentlyContinue | Out-Null
                Write-Output "VM_STARTED"
            }}
        """
        vm_started = False
        try:
            vm_res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_vm],
                capture_output=True, text=True, timeout=30
            )
            if "VM_STARTED" in vm_res.stdout:
                vm_started = True
                logs.append(f"✅ VM de Sandbox '{name}' iniciada com sucesso na sandbox isolada.")
            else:
                logs.append("⚠️ Falha ao instanciar VM de teste no Hyper-V.")
        except Exception as ex_vm:
            logs.append(f"Erro ao criar VM no Hyper-V: {ex_vm}")

        # 6. Monitorar Heartbeat / Boot
        heartbeat_detected = False
        if vm_started:
            logs.append("Aguardando pulso de boot (WMI / Integration Components)...")
            check_ps = f"""
                $hb = Get-VMIntegrationService -VMName '{name}' -Name 'Heartbeat' -ErrorAction SilentlyContinue
                if ($hb -and $hb.PrimaryStatusDescription -eq 'OK') {{
                    Write-Output "HEARTBEAT_OK"
                }}
            """
            for _ in range(6):
                time.sleep(2)
                try:
                    hb_res = subprocess.run(
                        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", check_ps],
                        capture_output=True, text=True, timeout=10
                    )
                    if "HEARTBEAT_OK" in hb_res.stdout:
                        heartbeat_detected = True
                        logs.append("🟢 Heartbeat do Guest SO recebido com sucesso!")
                        break
                except Exception:
                    pass

        # 7. Teardown Seguro da Sandbox
        if vm_started:
            logs.append("Encerrando e desprovisionando VM de teste temporária...")
            ps_cleanup = f"""
                Stop-VM -Name '{name}' -TurnOff -Force -ErrorAction SilentlyContinue | Out-Null
                Remove-VM -Name '{name}' -Force -ErrorAction SilentlyContinue | Out-Null
            """
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cleanup],
                    capture_output=True, text=True, timeout=20
                )
                logs.append("✅ VM de teste removida da infraestrutura com sucesso.")
            except Exception:
                pass

        if os.path.exists(diff_vhdx) and diff_vhdx != resolved_disk:
            try:
                os.remove(diff_vhdx)
                logs.append("✅ Camada temporária CoW liberada.")
            except Exception:
                pass

        duration = round(time.time() - start_time, 2)
        status = "Aprovado" if (vm_started and heartbeat_detected) else ("Reprovado" if vm_started else "Inconclusivo")

        return {
            "success": status == "Aprovado",
            "status": status,
            "lab_id": lab_id,
            "snapshot_id": snapshot_id,
            "vm_name": name,
            "hyperv_switch": "GBOC-Isolated-Lab",
            "boot_heartbeat": heartbeat_detected,
            "duration_seconds": duration,
            "timestamp": datetime.now().isoformat(),
            "logs": logs
        }


# Singleton global
virtual_lab_engine = VirtualLabSandboxEngine()
