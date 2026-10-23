# ==============================================================================
# GBOC System v14.8.2 Enterprise Edition
# Module: Disaster Recovery, P2V & Boot Media Engine
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import json
import time
import shutil
import logging
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from version_control import __version__ as AGENT_VERSION
except Exception:
    AGENT_VERSION = "14.8.2"

logger = logging.getLogger("gboc_dr_engine")


class DisasterRecoveryEngine:
    """
    Motor Enterprise de Disaster Recovery, Clonagem P2V e Mídia de Boot.
    Fornece rotinas reais de VSS, System State, Active Directory, conversão VHDX e WinPE.
    """

    def __init__(self):
        self.active_jobs: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        # dentro da pasta do Agente (antes: C:\\GBOC-... criada a cada inicializacao) - core/gboc_paths.py
        from core.gboc_paths import data_dir as _gboc_data_dir
        self.dr_exports_dir = _gboc_data_dir("dr_exports", create=False)
        try:
            self.dr_exports_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Thread-safe TTL Caches para evitar travamento da UI
        self._cache_ttl = 30.0  # 30 segundos
        self._disks_cache: Optional[List[Dict[str, Any]]] = None
        self._disks_cache_time = 0.0
        self._sys_info_cache: Optional[Dict[str, Any]] = None
        self._sys_info_cache_time = 0.0
        self._readiness_cache: Optional[Dict[str, Any]] = None
        self._readiness_cache_time = 0.0

    def _append_log(self, job_id: str, message: str):
        with self.lock:
            if job_id in self.active_jobs:
                self.active_jobs[job_id].setdefault("logs", []).append({
                    "timestamp": datetime.now().isoformat(),
                    "message": message
                })
                if len(self.active_jobs[job_id]["logs"]) > 300:
                    self.active_jobs[job_id]["logs"] = self.active_jobs[job_id]["logs"][-300:]

    # ------------------------------------------------------------------
    # Utilitarios reais (sem simulacao): execucao, status e verificacao
    # ------------------------------------------------------------------
    @staticmethod
    def _console_encoding() -> str:
        """Ferramentas de console do Windows (reg, ntdsutil, dism) escrevem na pagina OEM (ex.: cp850)."""
        if sys.platform == "win32":
            try:
                import ctypes
                return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
            except Exception:
                pass
        return "utf-8"

    def _run_console(self, cmd: List[str], timeout: int):
        """Executa a ferramenta e devolve (codigo_de_saida, saida_decodificada)."""
        res = subprocess.run(cmd, capture_output=True, timeout=timeout)
        enc = self._console_encoding()
        out = (res.stdout or b"").decode(enc, errors="replace")
        err = (res.stderr or b"").decode(enc, errors="replace")
        return res.returncode, (out + ("\n" + err if err.strip() else "")).strip()

    @staticmethod
    def _is_admin() -> bool:
        if sys.platform != "win32":
            return hasattr(os, "geteuid") and os.geteuid() == 0
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    @staticmethod
    def _fmt_size(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024 or unit == "TB":
                return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
            n /= 1024.0
        return f"{n:.1f} TB"

    @staticmethod
    def _sha256(path: str, chunk: int = 4 * 1024 * 1024) -> str:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(chunk), b""):
                h.update(block)
        return h.hexdigest()

    def _set_progress(self, job_id: str, pct: int):
        with self.lock:
            if job_id in self.active_jobs:
                self.active_jobs[job_id]["progress"] = pct

    def _is_cancelled(self, job_id: str) -> bool:
        with self.lock:
            return self.active_jobs.get(job_id, {}).get("status") == "cancelled"

    def _finish_job(self, job_id: str, status: str, error: Optional[str] = None):
        """Fecha o job com o status real; nunca sobrescreve um cancelamento do operador."""
        with self.lock:
            job = self.active_jobs.get(job_id)
            if not job or job.get("status") == "cancelled":
                return
            job["status"] = status
            if status in ("completed", "partial"):
                job["progress"] = 100
            job["completed_at"] = datetime.now().isoformat()
            if error:
                job["error"] = error

    def get_physical_disks(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Retorna informações 100% reais sobre os discos físicos e partições do sistema.
        Utiliza cache TTL de 30s e uma única consulta em lote PowerShell para máxima velocidade.
        """
        now = time.time()
        with self.lock:
            if not force_refresh and self._disks_cache is not None and (now - self._disks_cache_time) < self._cache_ttl:
                return self._disks_cache

        disks = []
        if sys.platform == "win32":
            # Consulta única em lote para todos os discos e partições de uma vez só
            ps_batch_cmd = (
                "$ErrorActionPreference = 'SilentlyContinue'; "
                "$dList = @(Get-Disk | Select-Object Number, FriendlyName, SerialNumber, Size, PartitionStyle, BusType, OperationalStatus); "
                "$pList = @(Get-Partition | Select-Object DiskNumber, PartitionNumber, DriveLetter, Size, Type); "
                "[PSCustomObject]@{ Disks = $dList; Partitions = $pList } | ConvertTo-Json -Depth 3"
            )
            try:
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_batch_cmd],
                    capture_output=True, text=True, timeout=12
                )
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout.strip())
                    raw_disks = data.get("Disks", [])
                    raw_parts = data.get("Partitions", [])
                    
                    if isinstance(raw_disks, dict):
                        raw_disks = [raw_disks]
                    if isinstance(raw_parts, dict):
                        raw_parts = [raw_parts]

                    for item in raw_disks:
                        num = item.get("Number", 0)
                        size_bytes = item.get("Size") or 0
                        size_gb = round(size_bytes / (1024 ** 3), 2)

                        # Filtrar partições pertencentes a este disco físico
                        partitions = []
                        drive_letters = []
                        for p in raw_parts:
                            if p.get("DiskNumber") == num:
                                letter = p.get("DriveLetter")
                                if letter:
                                    drive_letters.append(f"{letter}:")
                                partitions.append({
                                    "partition_number": p.get("PartitionNumber"),
                                    "drive_letter": f"{letter}:" if letter else None,
                                    "size_gb": round((p.get("Size") or 0) / (1024 ** 3), 2),
                                    "type": p.get("Type")
                                })

                        is_system = any(dl.upper() == "C:" for dl in drive_letters) or num == 0
                        disks.append({
                            "disk_number": num,
                            "name": item.get("FriendlyName") or f"Disk #{num}",
                            "serial": item.get("SerialNumber", "N/A"),
                            "size_bytes": size_bytes,
                            "size_gb": size_gb,
                            "partition_style": item.get("PartitionStyle", "GPT"),
                            "bus_type": item.get("BusType", "SATA/NVMe"),
                            "status": item.get("OperationalStatus", "Online"),
                            "drive_letters": drive_letters,
                            "partitions": partitions,
                            "is_system_disk": is_system
                        })
            except Exception as e:
                logger.error(f"Erro ao listar discos físicos via PowerShell: {e}")

        # Fallback de discos se PowerShell falhar ou em Linux
        if not disks:
            try:
                import psutil
                for part in psutil.disk_partitions(all=False):
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        "disk_number": 0,
                        "name": f"Volume {part.device} ({part.mountpoint})",
                        "serial": "N/A",
                        "size_bytes": usage.total,
                        "size_gb": round(usage.total / (1024 ** 3), 2),
                        "partition_style": "GPT/MBR",
                        "bus_type": part.fstype,
                        "status": "Online",
                        "drive_letters": [part.mountpoint],
                        "partitions": [],
                        "is_system_disk": part.mountpoint.upper().startswith("C:") or part.mountpoint == "/"
                    })
            except Exception:
                pass

        with self.lock:
            self._disks_cache = disks
            self._disks_cache_time = time.time()

        return disks

    def get_system_dr_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Retorna diagnóstico em tempo real do sistema para Disaster Recovery,
        incluindo detecção de Active Directory e integridade dos VSS Writers.
        Utiliza cache TTL de 30s e validação de registro NTDS para máxima agilidade.
        """
        now = time.time()
        with self.lock:
            if not force_refresh and self._sys_info_cache is not None and (now - self._sys_info_cache_time) < self._cache_ttl:
                return self._sys_info_cache

        info = {
            "os_name": sys.platform,
            "is_windows": sys.platform == "win32",
            "is_domain_controller": False,
            "domain_name": None,
            "ad_roles": [],
            "vss_writers": [],
            "vss_healthy": True,
            "vss_writer_count": 0,
            "system_root": os.environ.get("SystemRoot", "C:\\Windows"),
            "hostname": os.environ.get("COMPUTERNAME", "LOCALHOST"),
            "timestamp": datetime.now().isoformat()
        }

        if sys.platform == "win32":
            # 1. Verificar se é Active Directory Domain Controller via winreg nativo (sub-milissegundo)
            try:
                import winreg
                # A chave Services\NTDS existe tambem em servidores que NAO sao DC (ex.: so 'RID Values').
                # Controlador de dominio de verdade tem o banco NTDS configurado em Parameters\'DSA Database file'.
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\NTDS\Parameters") as k:
                        dsa_db, _t = winreg.QueryValueEx(k, "DSA Database file")
                        if dsa_db:
                            info["is_domain_controller"] = True
                            info["ntds_database"] = dsa_db
                            info["ad_roles"].append("Active Directory Domain Services (AD DS)")
                except (FileNotFoundError, OSError):
                    info["is_domain_controller"] = False

                domain = os.environ.get("USERDNSDOMAIN") or os.environ.get("USERDOMAIN")
                info["domain_name"] = domain
            except Exception as e:
                logger.debug(f"Erro ao verificar Domain Controller: {e}")

            # 2. Verificar VSS Writers
            try:
                # Saida localizada (ex.: pt-BR 'Nome do gravador', 'Estado: [1] Estavel', 'Ultimo erro: Sem erros')
                # e na pagina OEM: le em bytes e usa o codigo numerico do estado ([1] = estavel).
                import re as _re
                vss_rc, vss_out = self._run_console(["vssadmin", "list", "writers"], timeout=20)
                if vss_rc == 0 and vss_out:
                    writers = []
                    current_writer = {}
                    for line in vss_out.splitlines():
                        line_str = line.strip()
                        low = line_str.lower()
                        if low.startswith(("writer name:", "nome do gravador:")):
                            if current_writer and "name" in current_writer:
                                writers.append(current_writer)
                            current_writer = {"name": line_str.split(":", 1)[1].strip("' ")}
                        elif current_writer and low.startswith(("state:", "estado:")):
                            current_writer["state"] = line_str.split(":", 1)[1].strip()
                            m = _re.search(r"\[(\d+)\]", line_str)
                            current_writer["state_code"] = int(m.group(1)) if m else None
                        elif current_writer and _re.match(r"^(last error|.ltimo erro):", low):
                            current_writer["last_error"] = line_str.split(":", 1)[1].strip()
                    if current_writer and "name" in current_writer:
                        writers.append(current_writer)

                    ok_errors = ("no error", "sem erros", "sem erro")
                    info["vss_writers"] = writers
                    info["vss_writer_count"] = len(writers)
                    # [1] estavel e [5] aguardando conclusao (normal apos backup) sem erro = saudavel; [6+] = falha
                    unhealthy = [w for w in writers if (w.get("state_code") or 0) >= 6 or w.get("state_code") is None
                                 or w.get("last_error", "no error").strip().lower() not in ok_errors]
                    info["vss_healthy"] = len(unhealthy) == 0
                    if not info["vss_healthy"]:
                        info["unhealthy_writers"] = unhealthy
            except Exception as e:
                logger.warning(f"Erro ao consultar vssadmin list writers: {e}")

        with self.lock:
            self._sys_info_cache = info
            self._sys_info_cache_time = time.time()

        return info

    def calculate_dr_readiness(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Calcula o Disaster Recovery Readiness Score (0-100%) com checklist de conformidade.
        Aproveita os dados em cache de system_info e physical_disks para execução instantânea.
        """
        now = time.time()
        with self.lock:
            if not force_refresh and self._readiness_cache is not None and (now - self._readiness_cache_time) < self._cache_ttl:
                return self._readiness_cache

        sys_info = self.get_system_dr_info(force_refresh=force_refresh)
        disks = self.get_physical_disks(force_refresh=force_refresh)
        
        checks = []
        score = 100

        # Check 1: VSS Writers
        if sys_info.get("vss_healthy"):
            checks.append({"name": "VSS Subsystem & ShadowCopy Writers", "status": "PASSED", "weight": 25, "detail": f"{sys_info.get('vss_writer_count', 0)} writers operando em estado estável."})
        else:
            score -= 25
            checks.append({"name": "VSS Subsystem & ShadowCopy Writers", "status": "WARNING", "weight": 25, "detail": "Um ou mais VSS writers reportaram falha ou timeout."})

        # Check 2: Disco de Sistema
        sys_disks = [d for d in disks if d.get("is_system_disk")]
        if sys_disks:
            checks.append({"name": "Estrutura de Particionamento e Disco de Boot", "status": "PASSED", "weight": 25, "detail": f"Disco de sistema identificado: {sys_disks[0]['name']} ({sys_disks[0]['partition_style']})."})
        else:
            score -= 20
            checks.append({"name": "Estrutura de Particionamento e Disco de Boot", "status": "WARNING", "weight": 25, "detail": "Não foi possível confirmar o layout de partição de boot."})

        # Check 3: Active Directory / System State Ready
        if sys_info.get("is_domain_controller"):
            checks.append({"name": "Active Directory Domain Controller State", "status": "INFO", "weight": 25, "detail": f"Controlador de Domínio detectado: {sys_info.get('domain_name')}. Backup NTDS habilitado."})
        else:
            checks.append({"name": "Servidor Membro / Standalone", "status": "PASSED", "weight": 25, "detail": "Servidor em topologia padrão. System State Registry & BCD prontos."})

        # Check 4: Espaço para Imagens e Snapshots
        free_gb = 0
        try:
            import psutil
            free_gb = round(psutil.disk_usage("C:\\").free / (1024 ** 3), 1)
        except Exception:
            pass
        if free_gb > 15:
            checks.append({"name": "Espaço Livre para VSS & Imagens", "status": "PASSED", "weight": 25, "detail": f"{free_gb} GB livres no volume primário para shadow copies."})
        else:
            score -= 15
            checks.append({"name": "Espaço Livre para VSS & Imagens", "status": "WARNING", "weight": 25, "detail": f"Apenas {free_gb} GB livres. Risco de estouro de storage durante VSS."})

        score = max(0, min(100, score))
        res = {
            "score": score,
            "status": "EXCELLENT" if score >= 85 else ("GOOD" if score >= 70 else "NEEDS_ATTENTION"),
            "checks": checks,
            "estimated_rto": "15 - 30 minutos (Restauração Instantânea VHDX)",
            "estimated_rpo": "Último snapshot consistente",
            "timestamp": datetime.now().isoformat()
        }

        with self.lock:
            self._readiness_cache = res
            self._readiness_cache_time = time.time()

        return res

    # ==========================================================================
    # WORKER: CLONAGEM P2V (PHYSICAL-TO-VIRTUAL) VHDX
    # ==========================================================================

    def start_p2v_conversion(self, disk_number: int, target_path: str, format_type: str = "VHDX", is_dynamic: bool = True) -> Dict[str, Any]:
        job_id = f"p2v_{int(time.time())}"
        
        target = Path(target_path)
        if not target.suffix.lower() in [".vhdx", ".vhd"]:
            target = target.with_suffix(".vhdx" if format_type.upper() == "VHDX" else ".vhd")

        with self.lock:
            self.active_jobs[job_id] = {
                "job_id": job_id,
                "type": "p2v_clone",
                "status": "running",
                "progress": 0,
                "disk_number": disk_number,
                "target_path": str(target),
                "format_type": format_type,
                "is_dynamic": is_dynamic,
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "bytes_processed": 0,
                "total_bytes": 0,
                "speed_mbps": 0.0,
                "logs": [],
                "error": None
            }

        thread = threading.Thread(
            target=self._p2v_worker,
            args=(job_id, disk_number, str(target), is_dynamic),
            daemon=True
        )
        self.active_jobs[job_id]["thread"] = thread
        thread.start()

        return {
            "status": "started",
            "job_id": job_id,
            "message": f"Clonagem P2V iniciada para o disco físico #{disk_number} -> {target}"
        }

    def _find_disk2vhd(self) -> Optional[str]:
        """Localiza o Sysinternals Disk2vhd (PATH ou pasta tools do Agente)."""
        names = ("disk2vhd64.exe", "disk2vhd.exe")
        for n in names:
            p = shutil.which(n)
            if p:
                return p
        bases = [Path(__file__).resolve().parent.parent / "tools"]
        try:
            from core.gboc_paths import data_dir as _gboc_data_dir
            bases.insert(0, _gboc_data_dir("tools", create=False))
        except Exception:
            pass
        for base in bases:
            for n in names:
                c = Path(base) / n
                if c.exists():
                    return str(c)
        return None

    def _p2v_worker(self, job_id: str, disk_number: int, target_path: str, is_dynamic: bool):
        start_time = time.time()
        self._append_log(job_id, f"Iniciando conversão P2V do disco físico #{disk_number}")
        self._append_log(job_id, f"Destino da imagem virtual: {target_path}")
        try:
            if sys.platform != "win32":
                raise RuntimeError("Conversão P2V disponível apenas no Windows.")
            if not self._is_admin():
                raise RuntimeError("O Agente precisa de privilégio administrativo para ler o disco físico. Nenhum dado foi copiado.")
            tool = self._find_disk2vhd()
            if not tool:
                raise RuntimeError(
                    "Nenhum dado foi copiado: a conversão P2V usa o Sysinternals Disk2vhd (disk2vhd64.exe), "
                    "que não foi encontrado. Coloque o disk2vhd64.exe na pasta 'tools' do Agente ou no PATH e tente novamente."
                )
            if os.path.exists(target_path):
                raise RuntimeError("O arquivo de destino já existe; escolha outro nome para não sobrescrever uma imagem existente.")

            # Volumes (com letra) do disco escolhido e espaco realmente ocupado
            ps = (
                f"Get-Partition -DiskNumber {int(disk_number)} -ErrorAction Stop | Where-Object DriveLetter | "
                "ForEach-Object { $v = Get-Volume -DriveLetter $_.DriveLetter; \"$($_.DriveLetter)|$($v.Size - $v.SizeRemaining)\" }"
            )
            rc, out = self._run_console(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=60)
            letters, used_bytes = [], 0
            for line in out.splitlines():
                parts = line.strip().split("|")
                if len(parts) == 2 and len(parts[0]) == 1 and parts[0].isalpha():
                    letters.append(parts[0].upper() + ":")
                    try:
                        used_bytes += int(parts[1])
                    except ValueError:
                        pass
            if rc != 0 or not letters:
                raise RuntimeError(f"Não foi possível identificar volumes com letra no disco #{disk_number}: {out[:300] or 'sem saída'}")

            target_dir = os.path.dirname(target_path)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
            with self.lock:
                if job_id in self.active_jobs:
                    self.active_jobs[job_id]["total_bytes"] = used_bytes

            # Aceite da EULA pelo mecanismo padrao da Sysinternals (evita janela bloqueando o servico)
            try:
                import winreg
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Sysinternals\Disk2Vhd") as k:
                    winreg.SetValueEx(k, "EulaAccepted", 0, winreg.REG_DWORD, 1)
            except Exception:
                pass

            if not is_dynamic:
                self._append_log(job_id, "ℹ️ O Disk2vhd sempre gera disco de tamanho dinâmico; a opção 'fixo' não se aplica.")
            self._append_log(job_id, f"Copiando {', '.join(letters)} ({self._fmt_size(used_bytes)} em uso) com Disk2vhd (snapshot VSS)...")
            proc = subprocess.Popen([tool, *letters, target_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            last_size, last_log = 0, 0.0
            while proc.poll() is None:
                if self._is_cancelled(job_id):
                    proc.kill()
                    proc.wait(timeout=30)
                    try:
                        if os.path.exists(target_path):
                            os.remove(target_path)
                    except OSError:
                        pass
                    self._append_log(job_id, "🛑 Conversão cancelada; o arquivo parcial foi removido.")
                    return
                size = os.path.getsize(target_path) if os.path.exists(target_path) else 0
                elapsed = max(0.1, time.time() - start_time)
                if size == 0 and elapsed > 120:
                    proc.kill()
                    raise RuntimeError("O Disk2vhd não começou a gravar a imagem em 120 s (possível erro de parâmetros ou bloqueio). Nenhum dado foi copiado.")
                pct = min(99, int(size * 100 / used_bytes)) if used_bytes else 0
                with self.lock:
                    if job_id in self.active_jobs:
                        self.active_jobs[job_id]["progress"] = pct
                        self.active_jobs[job_id]["bytes_processed"] = size
                        self.active_jobs[job_id]["speed_mbps"] = round(size / (1024 * 1024) / elapsed, 1)
                if size != last_size and time.time() - last_log > 30:
                    self._append_log(job_id, f"Gravado: {self._fmt_size(size)} de ~{self._fmt_size(used_bytes)} ({pct}%)")
                    last_log = time.time()
                last_size = size
                time.sleep(2)

            enc = self._console_encoding()
            so, se = proc.communicate()
            msg = ((so or b"").decode(enc, errors="replace") + (se or b"").decode(enc, errors="replace")).strip()
            size = os.path.getsize(target_path) if os.path.exists(target_path) else 0
            if proc.returncode != 0 or size == 0:
                raise RuntimeError(f"Disk2vhd terminou com código {proc.returncode} e {size} bytes gravados: {msg[:400] or 'sem mensagem'}")

            disks = self.get_physical_disks()
            disk_info = next((d for d in disks if d["disk_number"] == disk_number), {})
            vm_meta_path = Path(target_path).with_suffix(".vmconfig.json")
            vm_config = {
                "vm_name": f"P2V-Clone-Disk{disk_number}-{int(time.time())}",
                "virtual_disk": os.path.basename(target_path),
                "virtual_disk_bytes": size,
                "volumes": letters,
                "generation": 2 if disk_info.get("partition_style") == "GPT" else 1,
                "firmware": "UEFI" if disk_info.get("partition_style") == "GPT" else "BIOS",
                "tool": "Sysinternals Disk2vhd",
                "created_at": datetime.now().isoformat()
            }
            with open(vm_meta_path, "w", encoding="utf-8") as f:
                json.dump(vm_config, f, indent=2)
            with self.lock:
                if job_id in self.active_jobs:
                    self.active_jobs[job_id]["bytes_processed"] = size
            self._append_log(job_id, f"✅ Imagem gerada: {os.path.basename(target_path)} ({self._fmt_size(size)}) em {round(time.time() - start_time)} s")
            self._append_log(job_id, f"Perfil de VM salvo em {vm_meta_path.name}. Teste o boot da imagem antes de considerá-la pronta para recuperação.")
            self._finish_job(job_id, "completed")
        except Exception as e:
            logger.error(f"Erro no worker P2V {job_id}: {e}", exc_info=True)
            self._append_log(job_id, f"❌ Conversão P2V falhou: {e}")
            self._finish_job(job_id, "failed", str(e))

    # ==========================================================================
    # WORKER: BACKUP A QUENTE DE SERVIDOR & ACTIVE DIRECTORY (SYSTEM STATE)
    # ==========================================================================

    def start_system_state_backup(self, target_folder: Optional[str] = None, include_ad: bool = True) -> Dict[str, Any]:
        job_id = f"sysstate_{int(time.time())}"
        target = target_folder or str(self.dr_exports_dir / f"SystemState_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

        with self.lock:
            self.active_jobs[job_id] = {
                "job_id": job_id,
                "type": "system_state_backup",
                "status": "running",
                "progress": 0,
                "target_folder": target,
                "include_ad": include_ad,
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "logs": [],
                "error": None
            }

        thread = threading.Thread(
            target=self._system_state_worker,
            args=(job_id, target, include_ad),
            daemon=True
        )
        self.active_jobs[job_id]["thread"] = thread
        thread.start()

        return {
            "status": "started",
            "job_id": job_id,
            "message": f"Backup a quente do System State e Active Directory iniciado -> {target}"
        }

    def _system_state_worker(self, job_id: str, target_folder: str, include_ad: bool):
        self._append_log(job_id, "Iniciando backup do System State (registro, BCD e, em controlador de domínio, NTDS/SYSVOL)")
        self._append_log(job_id, f"Diretório de destino: {target_folder}")
        captured: List[str] = []
        missing: List[str] = []
        try:
            if sys.platform != "win32":
                raise RuntimeError("Backup de System State disponível apenas no Windows.")
            os.makedirs(target_folder, exist_ok=True)
            sys_info = self.get_system_dr_info(force_refresh=True)

            if not self._is_admin():
                self._append_log(job_id, "⚠️ O Agente não está com privilégio administrativo: hives protegidos e o NTDS não poderão ser copiados.")

            n_writers = sys_info.get("vss_writer_count", 0)
            if n_writers:
                bad = sys_info.get("unhealthy_writers") or []
                if bad:
                    names = ", ".join(f"{w.get('name')} ({w.get('state', '?')})" for w in bad[:5])
                    self._append_log(job_id, f"⚠️ VSS writers com problema: {names}")
                else:
                    self._append_log(job_id, f"VSS: {n_writers} writer(s) estáveis.")
            else:
                self._append_log(job_id, "⚠️ Não foi possível consultar os VSS writers (vssadmin list writers).")
            self._set_progress(job_id, 10)

            # 1. Hives do registro - cada um conferido (codigo de saida + arquivo nao vazio)
            reg_dir = os.path.join(target_folder, "Registry_Hives")
            os.makedirs(reg_dir, exist_ok=True)
            self._append_log(job_id, "Exportando hives do registro (SAM, SECURITY, SYSTEM, SOFTWARE)...")
            for idx, hive in enumerate(["SAM", "SECURITY", "SYSTEM", "SOFTWARE"]):
                if self._is_cancelled(job_id):
                    return
                hive_path = os.path.join(reg_dir, f"{hive}.hiv")
                try:
                    rc, out = self._run_console(["reg", "save", f"HKLM\\{hive}", hive_path, "/y"], timeout=600)
                except subprocess.TimeoutExpired:
                    rc, out = -1, "tempo esgotado (600 s)"
                except OSError as ex:
                    rc, out = -1, (f"{ex}. O Windows ou o antivírus/EDR bloqueou a execução do reg.exe "
                                   "(a proteção contra extração de credenciais costuma bloquear a cópia de SAM/SECURITY).")
                size = os.path.getsize(hive_path) if os.path.exists(hive_path) else 0
                if rc == 0 and size > 0:
                    captured.append(f"hive {hive}")
                    self._append_log(job_id, f"✅ Hive {hive} salvo ({self._fmt_size(size)})")
                else:
                    missing.append(f"hive {hive}")
                    self._append_log(job_id, f"❌ Hive {hive} NÃO foi salvo (código {rc}, {size} bytes): {out[:300] or 'sem mensagem'}")
                    if os.path.exists(hive_path) and size == 0:
                        try:
                            os.remove(hive_path)
                        except OSError:
                            pass
                self._set_progress(job_id, 10 + (idx + 1) * 8)

            # 2. Banco de configuracao de boot (BCD)
            bcd_path = os.path.join(target_folder, "BCD_export")
            try:
                rc, out = self._run_console(["bcdedit", "/export", bcd_path], timeout=120)
            except (OSError, subprocess.TimeoutExpired) as ex:
                rc, out = -1, str(ex)
            size = os.path.getsize(bcd_path) if os.path.exists(bcd_path) else 0
            if rc == 0 and size > 0:
                captured.append("BCD")
                self._append_log(job_id, f"✅ BCD exportado ({self._fmt_size(size)})")
            else:
                missing.append("BCD")
                self._append_log(job_id, f"❌ BCD NÃO foi exportado (código {rc}): {out[:300] or 'sem mensagem'}")
            self._set_progress(job_id, 50)

            # 3. Active Directory (somente em controlador de dominio)
            ad_info: Dict[str, Any] = {"included": False}
            if sys_info.get("is_domain_controller"):
                if include_ad:
                    ad_info = self._backup_ntds_ifm(job_id, target_folder, captured, missing)
                else:
                    self._append_log(job_id, "ℹ️ Controlador de domínio detectado, mas a opção de incluir o Active Directory está desmarcada.")
            elif include_ad:
                self._append_log(job_id, "ℹ️ Este servidor não é controlador de domínio: não há base NTDS para copiar.")
            if self._is_cancelled(job_id):
                return
            self._set_progress(job_id, 85)

            # 4. Manifesto com SHA-256 real de cada arquivo capturado
            self._append_log(job_id, "Calculando SHA-256 dos arquivos capturados...")
            manifest_file = os.path.join(target_folder, "dr_manifest.json")
            files = []
            for root, _dirs, names in os.walk(target_folder):
                for n in names:
                    p = os.path.join(root, n)
                    if os.path.abspath(p) == os.path.abspath(manifest_file):
                        continue
                    rel = os.path.relpath(p, target_folder)
                    try:
                        files.append({"path": rel, "size_bytes": os.path.getsize(p), "sha256": self._sha256(p)})
                    except OSError as ex:
                        files.append({"path": rel, "error": str(ex)})
            manifest = {
                "gboc_version": f"{AGENT_VERSION} Enterprise",
                "backup_type": "SYSTEM_STATE_EXPORT",
                "hostname": sys_info.get("hostname"),
                "domain": sys_info.get("domain_name"),
                "is_domain_controller": sys_info.get("is_domain_controller"),
                "vss_writers_checked": n_writers,
                "vss_healthy": sys_info.get("vss_healthy"),
                "captured": captured,
                "missing": missing,
                "active_directory": ad_info,
                "files": files,
                "wbadmin_available": shutil.which("wbadmin") is not None,
                "created_at": datetime.now().isoformat()
            }
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            self._append_log(job_id, f"Manifesto gerado: dr_manifest.json ({len(files)} arquivo(s) com SHA-256)")

            if not captured:
                raise RuntimeError("Nenhum item do System State foi capturado. " + ("Faltaram: " + ", ".join(missing) if missing else ""))
            if missing:
                msg = "Itens não capturados: " + ", ".join(missing)
                self._append_log(job_id, f"⚠️ Backup do System State concluído PARCIALMENTE. {msg}")
                self._finish_job(job_id, "partial", msg)
            else:
                self._append_log(job_id, f"✅ Backup do System State concluído: {len(captured)} item(ns) capturado(s) e registrados no manifesto.")
                self._finish_job(job_id, "completed")

        except Exception as e:
            logger.error(f"Erro no backup de System State {job_id}: {e}", exc_info=True)
            self._append_log(job_id, f"❌ Falha no backup do System State: {e}")
            self._finish_job(job_id, "failed", str(e))

    def _backup_ntds_ifm(self, job_id: str, target_folder: str, captured: List[str], missing: List[str]) -> Dict[str, Any]:
        """Copia NTDS + SYSVOL com ntdsutil IFM (usa snapshot VSS) e confere a consistencia ESE com esentutl."""
        info: Dict[str, Any] = {"included": True, "method": "ntdsutil ifm (create sysvol full)"}
        ifm_dir = os.path.join(target_folder, "AD_IFM")
        self._append_log(job_id, "Controlador de domínio: gerando cópia IFM do NTDS e do SYSVOL com ntdsutil (snapshot VSS)...")
        try:
            rc, out = self._run_console(
                ["ntdsutil", "activate instance ntds", "ifm", f'create sysvol full "{ifm_dir}"', "quit", "quit"],
                timeout=7200
            )
        except subprocess.TimeoutExpired:
            rc, out = -1, "tempo esgotado (2 h)"
        except OSError as ex:
            rc, out = -1, f"{ex} (execução do ntdsutil bloqueada)"
        info["ntdsutil_exit_code"] = rc
        ntds = os.path.join(ifm_dir, "Active Directory", "ntds.dit")
        size = os.path.getsize(ntds) if os.path.exists(ntds) else 0
        if rc != 0 or size == 0:
            missing.append("NTDS (Active Directory)")
            tail = " | ".join(l.strip() for l in out.splitlines()[-6:] if l.strip())
            self._append_log(job_id, f"❌ Cópia IFM do NTDS falhou (código {rc}): {tail[:400] or 'sem mensagem'}")
            info["ok"] = False
            return info
        captured.append("NTDS")
        self._append_log(job_id, f"✅ NTDS copiado ({self._fmt_size(size)})")
        if os.path.isdir(os.path.join(ifm_dir, "SYSVOL")):
            captured.append("SYSVOL")
            self._append_log(job_id, "✅ SYSVOL copiado")
        else:
            missing.append("SYSVOL")
            self._append_log(job_id, "❌ SYSVOL não foi encontrado na cópia IFM")

        try:
            rc2, out2 = self._run_console(["esentutl", "/mh", ntds], timeout=600)
        except (OSError, subprocess.TimeoutExpired) as ex:
            rc2, out2 = -1, str(ex)
        state = None
        for line in out2.splitlines():
            s = line.strip()
            if s.lower().startswith(("state:", "estado:")):
                state = s.split(":", 1)[1].strip()
                break
        info["ese_state"] = state
        if rc2 == 0 and state and ("clean" in state.lower() or "limp" in state.lower()):
            info["ok"] = True
            self._append_log(job_id, f"✅ Consistência ESE do NTDS verificada (esentutl /mh: {state})")
        else:
            info["ok"] = False
            missing.append("verificação de consistência do NTDS")
            self._append_log(job_id, f"⚠️ Consistência do NTDS não confirmada (esentutl código {rc2}, estado: {state or 'não identificado'})")
        return info

    # ==========================================================================
    # WORKER: MÍDIA DE BOOT & EXTRAÇÃO DE DRIVERS (WINPE / ISO)
    # ==========================================================================

    def start_boot_media_build(self, media_type: str = "winpe", embed_drivers: bool = True) -> Dict[str, Any]:
        job_id = f"bootmedia_{int(time.time())}"
        target_iso = str(self.dr_exports_dir / f"GBOC_Recovery_Environment_{datetime.now().strftime('%Y%m%d')}.iso")

        with self.lock:
            self.active_jobs[job_id] = {
                "job_id": job_id,
                "type": "boot_media_build",
                "status": "running",
                "progress": 0,
                "media_type": media_type,
                "embed_drivers": embed_drivers,
                "target_iso": target_iso,
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "logs": [],
                "error": None
            }

        thread = threading.Thread(
            target=self._boot_media_worker,
            args=(job_id, target_iso, media_type, embed_drivers),
            daemon=True
        )
        self.active_jobs[job_id]["thread"] = thread
        thread.start()

        return {
            "status": "started",
            "job_id": job_id,
            "message": f"Construção da mídia de boot inicializada ({media_type.upper()})"
        }

    @staticmethod
    def _find_adk():
        """Retorna (DandISetEnv.bat ou None, complemento WinPE instalado?)."""
        base = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "Assessment and Deployment Kit"
        env_bat = base / "Deployment Tools" / "DandISetEnv.bat"
        winpe = base / "Windows Preinstallation Environment" / "amd64"
        return (str(env_bat) if env_bat.exists() else None), winpe.exists()

    def _boot_media_worker(self, job_id: str, target_iso: str, media_type: str, embed_drivers: bool):
        self._append_log(job_id, f"Iniciando construção da mídia de recuperação ({media_type.upper()})")
        try:
            if sys.platform != "win32":
                raise RuntimeError("Construção de mídia WinPE disponível apenas no Windows.")
            staging_dir = str(self.dr_exports_dir / "WinPE_Recovery_Staging")
            drivers_dir = os.path.join(staging_dir, "Drivers")
            os.makedirs(drivers_dir, exist_ok=True)

            # 1. Exportacao real dos drivers de terceiros instalados no host
            driver_count = 0
            drivers_failed = False
            if embed_drivers:
                self._append_log(job_id, "Exportando drivers de terceiros instalados no host (Export-WindowsDriver)...")
                ps = f"Export-WindowsDriver -Online -Destination '{drivers_dir}' | Out-Null"
                try:
                    rc, out = self._run_console(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=1800)
                except (OSError, subprocess.TimeoutExpired) as ex:
                    rc, out = -1, str(ex)
                driver_count = len(list(Path(drivers_dir).rglob("*.inf")))
                if rc == 0:
                    self._append_log(job_id, f"✅ {driver_count} driver(s) exportado(s) para {drivers_dir}")
                else:
                    drivers_failed = True
                    self._append_log(job_id, f"❌ Exportação de drivers falhou (código {rc}): {out[:300] or 'sem mensagem'}")
            self._set_progress(job_id, 30)
            if self._is_cancelled(job_id):
                return

            # 2. ISO bootavel real: precisa do Windows ADK + complemento WinPE
            dandi, has_winpe = self._find_adk()
            if not dandi or not has_winpe:
                what = "o Windows ADK" if not dandi else "o complemento WinPE do Windows ADK"
                msg = f"ISO não gerada: {what} não está instalado neste servidor."
                if driver_count:
                    msg += f" Os drivers exportados estão em {drivers_dir}."
                self._append_log(job_id, f"⚠️ {msg}")
                self._finish_job(job_id, "partial" if driver_count else "failed", msg)
                return

            work_dir = os.path.join(staging_dir, "WinPE_amd64")
            mount_dir = os.path.join(work_dir, "mount")
            subprocess.run(["dism", "/Cleanup-Mountpoints"], capture_output=True, timeout=300)
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)
            startnet = os.path.join(staging_dir, "startnet.cmd")
            with open(startnet, "w", encoding="ascii") as f:
                f.write("@echo off\r\nwpeinit\r\necho GBOC Recovery Environment (WinPE)\r\n")

            bat_lines = [
                "@echo off",
                f'call "{dandi}"',
                f'call copype amd64 "{work_dir}" || exit /b 10',
                f'dism /Mount-Image /ImageFile:"{work_dir}\\media\\sources\\boot.wim" /Index:1 /MountDir:"{mount_dir}" || exit /b 11',
            ]
            if embed_drivers and driver_count:
                bat_lines.append(f'dism /Image:"{mount_dir}" /Add-Driver /Driver:"{drivers_dir}" /Recurse /ForceUnsigned || set GBOC_DRV_ERR=1')
            bat_lines += [
                f'copy /y "{startnet}" "{mount_dir}\\Windows\\System32\\startnet.cmd" >nul',
                f'dism /Unmount-Image /MountDir:"{mount_dir}" /Commit || (dism /Unmount-Image /MountDir:"{mount_dir}" /Discard & exit /b 12)',
                f'call MakeWinPEMedia /ISO /F "{work_dir}" "{target_iso}" || exit /b 13',
                "if defined GBOC_DRV_ERR exit /b 2",
                "exit /b 0",
            ]
            bat = os.path.join(staging_dir, "build_winpe.cmd")
            with open(bat, "w", encoding="mbcs" if sys.platform == "win32" else "utf-8") as f:
                f.write("\r\n".join(bat_lines) + "\r\n")

            self._append_log(job_id, "Gerando WinPE com o Windows ADK (copype, DISM e MakeWinPEMedia)...")
            self._set_progress(job_id, 45)
            try:
                rc, out = self._run_console(["cmd", "/c", bat], timeout=3600)
            except subprocess.TimeoutExpired:
                rc, out = -1, "tempo esgotado (1 h)"
                subprocess.run(["dism", "/Unmount-Image", f"/MountDir:{mount_dir}", "/Discard"], capture_output=True, timeout=600)
            iso_size = os.path.getsize(target_iso) if os.path.exists(target_iso) else 0
            steps = {10: "copype", 11: "montagem do boot.wim", 12: "gravação do boot.wim", 13: "MakeWinPEMedia"}

            manifest_pe = {
                "environment": "WinPE (Windows ADK)",
                "iso": target_iso if iso_size else None,
                "iso_bytes": iso_size,
                "iso_sha256": self._sha256(target_iso) if iso_size else None,
                "drivers_exported": driver_count,
                "drivers_injected": bool(embed_drivers and driver_count and rc == 0),
                "build_exit_code": rc,
                "created_at": datetime.now().isoformat()
            }
            with open(os.path.join(staging_dir, "winpe_manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest_pe, f, indent=2, ensure_ascii=False)

            if rc in (0, 2) and iso_size > 0:
                shutil.rmtree(work_dir, ignore_errors=True)
                self._append_log(job_id, f"✅ ISO WinPE gerada: {target_iso} ({self._fmt_size(iso_size)})")
                problems = []
                if rc == 2:
                    problems.append("parte dos drivers não foi injetada no WinPE")
                if drivers_failed:
                    problems.append("a exportação de drivers falhou")
                if problems:
                    msg = "ISO gerada, mas " + " e ".join(problems) + "."
                    self._append_log(job_id, f"⚠️ {msg}")
                    self._finish_job(job_id, "partial", msg)
                else:
                    self._finish_job(job_id, "completed")
            else:
                tail = " | ".join(l.strip() for l in out.splitlines()[-6:] if l.strip())
                raise RuntimeError(f"Falha na etapa '{steps.get(rc, 'build')}' (código {rc}): {tail[:400] or 'sem mensagem'}")

        except Exception as e:
            logger.error(f"Erro na construção da mídia de boot {job_id}: {e}", exc_info=True)
            self._append_log(job_id, f"❌ Mídia de boot não gerada: {e}")
            self._finish_job(job_id, "failed", str(e))

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            job = self.active_jobs.get(job_id)
            if job:
                return {k: v for k, v in job.items() if k != "thread"}
        return None

    def cancel_job(self, job_id: str) -> bool:
        with self.lock:
            job = self.active_jobs.get(job_id)
            if job and job.get("status") == "running":
                job["status"] = "cancelled"
                self._append_log(job_id, "Operação cancelada pelo operador.")
                return True
        return False


# Singleton global
dr_engine = DisasterRecoveryEngine()
