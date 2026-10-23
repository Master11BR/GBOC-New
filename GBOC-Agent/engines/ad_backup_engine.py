# ==============================================================================
# GBOC System v14.8.2 Enterprise Edition
# Module: Active Directory Dedicated Backup & Recovery Engine
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import json
import time
import shutil
import hashlib
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

logger = logging.getLogger("gboc_ad_backup_engine")


class ActiveDirectoryBackupEngine:
    """
    Motor Especializado de Backup e Recuperação do Active Directory Domain Services (AD DS).
    Orquestra VSS NTDS Writer, extração de SYSVOL, Registry Hives, FSMO Roles,
    Diagnóstico DCDiag, Restauração DSRM e Proteção contra USN Rollback.
    """

    def __init__(self):
        self.active_jobs: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        # dentro da pasta do Agente (antes: C:\\GBOC-AD-Backups criada a cada inicializacao) - core/gboc_paths.py
        from core.gboc_paths import data_dir as _gboc_data_dir
        self.base_ad_dir = _gboc_data_dir("ad_backups", create=False)
        try:
            self.base_ad_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _append_log(self, job_id: str, message: str):
        with self.lock:
            if job_id in self.active_jobs:
                self.active_jobs[job_id].setdefault("logs", []).append({
                    "timestamp": datetime.now().isoformat(),
                    "message": message
                })
                if len(self.active_jobs[job_id]["logs"]) > 300:
                    self.active_jobs[job_id]["logs"] = self.active_jobs[job_id]["logs"][-300:]

    def get_ad_topology(self) -> Dict[str, Any]:
        """
        Retorna a topologia completa do Active Directory: Floresta, Domínio, FSMO Roles,
        Controladores de Domínio e Níveis Funcionais.
        """
        topology = {
            "is_ad_installed": False,
            "is_domain_controller": False,
            "forest_name": None,
            "domain_name": os.environ.get("USERDOMAIN", "WORKGROUP"),
            # None = nao se aplica/nao lido (a tela explica o motivo: "nao e DC" ou "nao informado pelo AD")
            "forest_functional_level": None,
            "domain_functional_level": None,
            "fsmo_roles": {
                "schema_master": None,
                "domain_naming_master": None,
                "pdc_emulator": None,
                "rid_master": None,
                "infrastructure_master": None
            },
            "hostname": __import__("socket").gethostname(),
            "domain_controllers": [],
            "global_catalog_servers": [],
            "tombstone_lifetime_days": 180,
            "recycle_bin_enabled": False,
            "timestamp": datetime.now().isoformat()
        }

        if sys.platform == "win32":
            ps_script = """
                $ErrorActionPreference = 'SilentlyContinue'
                Import-Module ActiveDirectory -ErrorAction SilentlyContinue
                
                $cs = Get-CimInstance Win32_ComputerSystem
                $isDc = ($cs.DomainRole -ge 4)
                
                if ($isDc) {
                    $domain = Get-ADDomain -ErrorAction SilentlyContinue
                    $forest = Get-ADForest -ErrorAction SilentlyContinue
                    $dcs = Get-ADDomainController -Filter * -ErrorAction SilentlyContinue
                    $optionalFeatures = Get-ADOptionalFeature -Filter * -ErrorAction SilentlyContinue
                    $rb = ($optionalFeatures | Where-Object { $_.Name -like "*Recycle Bin*" -and $_.EnabledScopes.Count -gt 0 })
                    
                    [PSCustomObject]@{
                        IsDC = $true
                        ForestName = if ($forest) { $forest.Name } else { $cs.Domain }
                        DomainName = if ($domain) { $domain.DNSRoot } else { $cs.Domain }
                        ForestLevel = if ($forest) { $forest.ForestMode.ToString() } else { "Windows2016Forest" }
                        DomainLevel = if ($domain) { $domain.DomainMode.ToString() } else { "Windows2016Domain" }
                        SchemaMaster = if ($forest) { $forest.SchemaMaster } else { $env:COMPUTERNAME }
                        DomainNamingMaster = if ($forest) { $forest.DomainNamingMaster } else { $env:COMPUTERNAME }
                        PDCEmulator = if ($domain) { $domain.PDCEmulator } else { $env:COMPUTERNAME }
                        RIDMaster = if ($domain) { $domain.RIDMaster } else { $env:COMPUTERNAME }
                        InfrastructureMaster = if ($domain) { $domain.InfrastructureMaster } else { $env:COMPUTERNAME }
                        DomainControllers = if ($dcs) { @($dcs | ForEach-Object { [PSCustomObject]@{ Hostname = $_.HostName; IP = $_.IPv4Address; OS = $_.OperatingSystem; IsGC = $_.IsGlobalCatalog; Site = $_.Site } }) } else { @() }
                        RecycleBinEnabled = ($null -ne $rb)
                    } | ConvertTo-Json -Depth 3
                } else {
                    [PSCustomObject]@{
                        IsDC = $false
                        PartOfDomain = [bool]$cs.PartOfDomain
                        ForestName = $cs.Domain
                        DomainName = $cs.Domain
                        Workgroup = $cs.Workgroup
                        DomainRole = [int]$cs.DomainRole
                    } | ConvertTo-Json
                }
            """
            try:
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                    capture_output=True, text=True, timeout=15
                )
                if res.returncode == 0 and res.stdout.strip():
                    raw = json.loads(res.stdout.strip())
                    if not raw.get("IsDC"):
                        # dados reais do Windows (antes: USERDOMAIN, que no login local e o nome da maquina)
                        topology["part_of_domain"] = bool(raw.get("PartOfDomain"))
                        topology["domain_name"] = raw.get("DomainName") if raw.get("PartOfDomain") else None
                        topology["workgroup"] = raw.get("Workgroup") if not raw.get("PartOfDomain") else None
                        topology["forest_name"] = topology["domain_name"]
                        topology["domain_role"] = raw.get("DomainRole")
                    if raw.get("IsDC"):
                        topology["is_ad_installed"] = True
                        topology["is_domain_controller"] = True
                        topology["forest_name"] = raw.get("ForestName")
                        topology["domain_name"] = raw.get("DomainName")
                        topology["forest_functional_level"] = raw.get("ForestLevel", "Windows Server 2016/2019/2022")
                        topology["domain_functional_level"] = raw.get("DomainLevel", "Windows Server 2016/2019/2022")
                        topology["fsmo_roles"] = {
                            "schema_master": raw.get("SchemaMaster"),
                            "domain_naming_master": raw.get("DomainNamingMaster"),
                            "pdc_emulator": raw.get("PDCEmulator"),
                            "rid_master": raw.get("RIDMaster"),
                            "infrastructure_master": raw.get("InfrastructureMaster")
                        }
                        topology["recycle_bin_enabled"] = bool(raw.get("RecycleBinEnabled"))
                        
                        dcs = raw.get("DomainControllers") or []
                        dcs_list = dcs if isinstance(dcs, list) else [dcs]
                        for dc in dcs_list:
                            topology["domain_controllers"].append({
                                "hostname": dc.get("Hostname"),
                                "ip_address": dc.get("IP"),
                                "operating_system": dc.get("OS"),
                                "is_global_catalog": dc.get("IsGC"),
                                "site": dc.get("Site")
                            })
            except Exception as e:
                logger.warning(f"Erro ao consultar topologia do AD: {e}")

        return topology

    def get_ad_health(self) -> Dict[str, Any]:
        """
        Retorna status de replicação entre DCs, saúde de compartilhamento SYSVOL e diagnósticos DCDiag.
        """
        # Nada e presumido saudavel: cada campo so recebe valor depois de verificado
        health = {
            "replication_status": "NAO_VERIFICADO",
            "replication_partners": [],
            "sysvol_shared": None,
            "netlogon_shared": None,
            "dcdiag_summary": None,
            "ntds_vss_writer": None,
            "errors": [],
            "timestamp": datetime.now().isoformat()
        }
        try:
            from engines.disaster_recovery_engine import dr_engine as _dr
            _info = _dr.get_system_dr_info()
            health["is_domain_controller"] = bool(_info.get("is_domain_controller"))
            ntds_w = next((w for w in _info.get("vss_writers", []) if "ntds" in (w.get("name") or "").lower()), None)
            if ntds_w:
                health["ntds_vss_writer"] = "STABLE" if ntds_w.get("state_code") == 1 else (ntds_w.get("state") or f"código {ntds_w.get('state_code')}")
            elif health["is_domain_controller"]:
                health["ntds_vss_writer"] = "NOT_FOUND"
            if not health["is_domain_controller"]:
                health["replication_status"] = "NOT_DC"
                return health
        except Exception:
            pass

        if sys.platform == "win32":
            # 1. Verificar compartilhamentos SYSVOL / NETLOGON
            try:
                net_share = subprocess.run(["net", "share"], capture_output=True, text=True, timeout=8)
                if net_share.returncode == 0:
                    health["sysvol_shared"] = "SYSVOL" in net_share.stdout.upper()
                    health["netlogon_shared"] = "NETLOGON" in net_share.stdout.upper()
                else:
                    health["errors"].append(f"net share (código {net_share.returncode}): {(net_share.stderr or net_share.stdout).strip()[:200]}")
            except Exception as e:
                health["errors"].append(f"net share: {e}")

            # 2. Verificar replicação via repadmin
            try:
                rep_res = subprocess.run(["repadmin", "/replsummary"], capture_output=True, text=True, timeout=12)
                if rep_res.returncode == 0:
                    health["repadmin_output"] = rep_res.stdout.strip()
                    low = rep_res.stdout.lower()
                    import re as _re
                    # linhas 'fails/total' com falhas > 0 ou mensagens de erro
                    failing = [m for m in _re.findall(r"\b(\d+)\s*/\s*\d+\s+\d+\b", rep_res.stdout) if int(m) > 0]
                    health["replication_status"] = "WARNING" if (failing or "error" in low or "erro" in low) else "HEALTHY"
                else:
                    # saida real do repadmin (antes: explicacao fixa inventada)
                    health["repadmin_output"] = (f"repadmin /replsummary retornou código {rep_res.returncode}: "
                                                 f"{(rep_res.stderr or rep_res.stdout).strip()[:600]}")
            except FileNotFoundError:
                health["repadmin_output"] = "repadmin não encontrado neste servidor (instale as ferramentas RSAT de AD DS)."
            except Exception as e:
                health["repadmin_output"] = f"repadmin não executado: {e}"

        return health

    def start_ad_backup(
        self,
        backup_name: Optional[str] = None,
        include_sysvol: bool = True,
        include_registry: bool = True,
        include_dns: bool = True
    ) -> Dict[str, Any]:
        """
        Inicia um backup a quente completo do Active Directory em segundo plano.
        """
        job_id = f"adbackup_{int(time.time())}"
        name = backup_name or f"AD_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        target_dir = str(self.base_ad_dir / name)

        with self.lock:
            self.active_jobs[job_id] = {
                "job_id": job_id,
                "backup_name": name,
                "type": "ad_backup",
                "status": "running",
                "progress": 0,
                "target_dir": target_dir,
                "include_sysvol": include_sysvol,
                "include_registry": include_registry,
                "include_dns": include_dns,
                "total_bytes": 0,
                "bytes_processed": 0,
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "logs": [],
                "error": None
            }

        thread = threading.Thread(
            target=self._ad_backup_worker,
            args=(job_id, target_dir, include_sysvol, include_registry, include_dns),
            daemon=True
        )
        self.active_jobs[job_id]["thread"] = thread
        thread.start()

        return {
            "status": "started",
            "job_id": job_id,
            "target_dir": target_dir,
            "message": f"Backup completo do Active Directory iniciado -> {target_dir}"
        }

    def _ad_backup_worker(
        self,
        job_id: str,
        target_dir: str,
        include_sysvol: bool,
        include_registry: bool,
        include_dns: bool
    ):
        """Backup real do AD: NTDS+SYSVOL via ntdsutil IFM (snapshot VSS), hives conferidos, zonas DNS e SHA-256."""
        from engines.disaster_recovery_engine import dr_engine as _dr
        start_time = time.time()
        captured: List[str] = []
        missing: List[str] = []
        self._append_log(job_id, f"Iniciando backup do Active Directory em: {target_dir}")
        try:
            if sys.platform != "win32":
                raise RuntimeError("Backup do Active Directory disponível apenas no Windows.")
            info = _dr.get_system_dr_info(force_refresh=True)
            if not info.get("is_domain_controller"):
                raise RuntimeError("Este servidor não é controlador de domínio: não há base NTDS para copiar. Nenhum backup foi gerado.")
            os.makedirs(target_dir, exist_ok=True)
            top = self.get_ad_topology()
            self._update_progress(job_id, 5)

            # 1. NTDS (+ SYSVOL) via IFM - reaproveita a rotina verificada do motor de DR (esentutl incluso).
            #    O helper registra mensagens no job do motor de DR: cria um job temporario la e copia depois.
            with _dr.lock:
                _dr.active_jobs[job_id] = {"job_id": job_id, "status": "running", "logs": []}
            try:
                ad_info = _dr._backup_ntds_ifm(job_id, target_dir, captured, missing) if include_sysvol else None
            finally:
                with _dr.lock:
                    _tmp = _dr.active_jobs.pop(job_id, {}) or {}
            for entry in _tmp.get("logs", []):
                self._append_log(job_id, entry.get("message", ""))
            if not include_sysvol:
                ifm_dir = os.path.join(target_dir, "AD_IFM")
                self._append_log(job_id, "Gerando cópia IFM do NTDS (sem SYSVOL) com ntdsutil...")
                try:
                    rc, out = _dr._run_console(["ntdsutil", "activate instance ntds", "ifm", f'create full "{ifm_dir}"', "quit", "quit"], timeout=7200)
                except (OSError, subprocess.TimeoutExpired) as ex:
                    rc, out = -1, str(ex)
                ntds = os.path.join(ifm_dir, "Active Directory", "ntds.dit")
                if rc == 0 and os.path.exists(ntds) and os.path.getsize(ntds) > 0:
                    captured.append("NTDS")
                    self._append_log(job_id, f"✅ NTDS copiado ({_dr._fmt_size(os.path.getsize(ntds))})")
                else:
                    missing.append("NTDS (Active Directory)")
                    self._append_log(job_id, f"❌ Cópia IFM do NTDS falhou (código {rc}): {out[-400:] or 'sem mensagem'}")
                ad_info = {"included": True, "method": "ntdsutil ifm (create full)", "ntdsutil_exit_code": rc}
            self._update_progress(job_id, 60)

            # 2. Hives do registro, cada um conferido
            if include_registry:
                reg_dir = os.path.join(target_dir, "Registry_Hives")
                os.makedirs(reg_dir, exist_ok=True)
                self._append_log(job_id, "Exportando hives do registro (SAM, SECURITY, SYSTEM, SOFTWARE)...")
                for hive in ["SAM", "SECURITY", "SYSTEM", "SOFTWARE"]:
                    hive_path = os.path.join(reg_dir, f"{hive}.hiv")
                    try:
                        rc, out = _dr._run_console(["reg", "save", f"HKLM\\{hive}", hive_path, "/y"], timeout=600)
                    except subprocess.TimeoutExpired:
                        rc, out = -1, "tempo esgotado (600 s)"
                    except OSError as ex:
                        rc, out = -1, f"{ex}. O Windows ou o antivírus/EDR bloqueou o reg.exe."
                    size = os.path.getsize(hive_path) if os.path.exists(hive_path) else 0
                    if rc == 0 and size > 0:
                        captured.append(f"hive {hive}")
                        self._append_log(job_id, f"✅ Hive {hive} salvo ({_dr._fmt_size(size)})")
                    else:
                        missing.append(f"hive {hive}")
                        self._append_log(job_id, f"❌ Hive {hive} NÃO foi salvo (código {rc}): {out[:300] or 'sem mensagem'}")
            self._update_progress(job_id, 75)

            # 3. Zonas DNS integradas ao AD (Export-DnsServerZone grava em %windir%\System32\dns)
            if include_dns:
                dns_dir = os.path.join(target_dir, "DNS_Zones")
                os.makedirs(dns_dir, exist_ok=True)
                self._append_log(job_id, "Exportando zonas DNS integradas ao AD (Export-DnsServerZone)...")
                stamp = datetime.now().strftime("%Y%m%d%H%M%S")
                ps = (
                    "$ErrorActionPreference='Stop'; Import-Module DnsServer; "
                    "$z = Get-DnsServerZone | Where-Object { $_.IsDsIntegrated -and -not $_.IsAutoCreated -and $_.ZoneName -ne 'TrustAnchors' }; "
                    f"foreach ($i in $z) {{ $f = 'gboc_{stamp}_' + ($i.ZoneName -replace '[^\\w.-]','_') + '.dns'; "
                    "Export-DnsServerZone -Name $i.ZoneName -FileName $f; Write-Output \"$($i.ZoneName)|$f\" }"
                )
                try:
                    rc, out = _dr._run_console(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=600)
                except (OSError, subprocess.TimeoutExpired) as ex:
                    rc, out = -1, str(ex)
                dns_src = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "dns")
                zones = 0
                for line in out.splitlines():
                    if "|" not in line:
                        continue
                    zname, fname = line.strip().split("|", 1)
                    src = os.path.join(dns_src, fname)
                    if os.path.exists(src):
                        shutil.move(src, os.path.join(dns_dir, f"{zname}.dns"))
                        zones += 1
                if rc == 0 and zones:
                    captured.append(f"DNS ({zones} zona(s))")
                    self._append_log(job_id, f"✅ {zones} zona(s) DNS exportada(s)")
                elif rc == 0:
                    self._append_log(job_id, "ℹ️ Nenhuma zona DNS integrada ao AD encontrada neste servidor.")
                else:
                    missing.append("zonas DNS")
                    self._append_log(job_id, f"❌ Exportação das zonas DNS falhou (código {rc}): {out[-300:] or 'sem mensagem'}")
            self._update_progress(job_id, 85)

            # 4. Manifesto com SHA-256 real
            self._append_log(job_id, "Calculando SHA-256 dos arquivos capturados...")
            manifest_file = os.path.join(target_dir, "ad_backup_manifest.json")
            files = []
            for root, _d, names in os.walk(target_dir):
                for n in names:
                    p = os.path.join(root, n)
                    if os.path.abspath(p) == os.path.abspath(manifest_file):
                        continue
                    try:
                        files.append({"path": os.path.relpath(p, target_dir), "size_bytes": os.path.getsize(p), "sha256": _dr._sha256(p)})
                    except OSError as ex:
                        files.append({"path": os.path.relpath(p, target_dir), "error": str(ex)})
            manifest = {
                "gboc_version": f"{AGENT_VERSION} Enterprise",
                "backup_type": "ACTIVE_DIRECTORY_IFM",
                "forest": top.get("forest_name"),
                "domain": top.get("domain_name"),
                "fsmo_roles": top.get("fsmo_roles"),
                "active_directory": ad_info,
                "captured": captured,
                "missing": missing,
                "files": files,
                "created_at": datetime.now().isoformat(),
                "duration_seconds": round(time.time() - start_time, 2)
            }
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            self._append_log(job_id, f"Manifesto gerado: {len(files)} arquivo(s) com SHA-256")

            if not any(c == "NTDS" for c in captured):
                raise RuntimeError("A base NTDS não foi copiada; o backup do AD não é utilizável. " + ("Faltaram: " + ", ".join(missing) if missing else ""))
            if missing:
                msg = "Itens não capturados: " + ", ".join(missing)
                self._append_log(job_id, f"⚠️ Backup do AD concluído PARCIALMENTE. {msg}")
                self._finish(job_id, "partial", msg)
            else:
                self._append_log(job_id, f"✅ Backup do Active Directory concluído: {', '.join(captured)}.")
                self._finish(job_id, "completed")
        except Exception as e:
            logger.error(f"Erro no backup do AD {job_id}: {e}", exc_info=True)
            self._append_log(job_id, f"❌ Backup do Active Directory falhou: {e}")
            self._finish(job_id, "failed", str(e))

    def _finish(self, job_id: str, status: str, error: Optional[str] = None):
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

    def start_ad_restore(
        self,
        snapshot_name: str,
        restore_mode: str = "non-authoritative",
        restore_sysvol: bool = True,
        restore_registry: bool = True
    ) -> Dict[str, Any]:
        """
        Inicia a orquestração de restauração do Active Directory (Não-Autoritativa ou DSRM Staging).
        """
        snapshot_dir = self.base_ad_dir / snapshot_name
        if not snapshot_dir.exists():
            raise FileNotFoundError(f"Snapshot '{snapshot_name}' não encontrado.")

        job_id = f"adrestore_{int(time.time())}"

        with self.lock:
            self.active_jobs[job_id] = {
                "job_id": job_id,
                "type": "ad_restore",
                "snapshot_name": snapshot_name,
                "restore_mode": restore_mode,
                "status": "running",
                "progress": 0,
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "logs": [],
                "error": None
            }

        thread = threading.Thread(
            target=self._ad_restore_worker,
            args=(job_id, str(snapshot_dir), restore_mode, restore_sysvol, restore_registry),
            daemon=True
        )
        self.active_jobs[job_id]["thread"] = thread
        thread.start()

        return {
            "status": "started",
            "job_id": job_id,
            "message": f"Restauração do Active Directory ({restore_mode.upper()}) iniciada a partir de '{snapshot_name}'"
        }

    def _ad_restore_worker(
        self,
        job_id: str,
        snapshot_dir: str,
        restore_mode: str,
        restore_sysvol: bool,
        restore_registry: bool
    ):
        """
        Preparacao (staging) verificada da restauracao. A substituicao do NTDS so pode ser feita
        com o DC em DSRM; aqui o backup e conferido de verdade e os passos exatos sao gerados.
        """
        from engines.disaster_recovery_engine import dr_engine as _dr
        self._append_log(job_id, f"Preparando restauração do Active Directory (modo: {restore_mode.upper()})")
        self._append_log(job_id, f"Backup de origem: {snapshot_dir}")
        try:
            manifest_file = os.path.join(snapshot_dir, "ad_backup_manifest.json")
            if not os.path.exists(manifest_file):
                raise RuntimeError("Manifesto ad_backup_manifest.json não encontrado: backup inválido ou incompleto.")
            with open(manifest_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            self._append_log(job_id, f"Manifesto: domínio {meta.get('domain')} (criado em {meta.get('created_at')})")
            self._update_progress(job_id, 10)

            # 1. Conferir SHA-256 de cada arquivo registrado
            files = meta.get("files") or []
            if not files:
                raise RuntimeError("O manifesto não tem a lista de arquivos com SHA-256 (backup gerado por versão antiga, sem cópia real do NTDS). Faça um novo backup.")
            bad = []
            for i, fe in enumerate(files):
                p = os.path.join(snapshot_dir, fe.get("path", ""))
                if not os.path.exists(p):
                    bad.append(f"{fe.get('path')} (ausente)")
                elif fe.get("sha256") and _dr._sha256(p) != fe["sha256"]:
                    bad.append(f"{fe.get('path')} (hash diferente)")
                self._update_progress(job_id, 10 + int(50 * (i + 1) / len(files)))
            if bad:
                raise RuntimeError("Integridade do backup falhou: " + "; ".join(bad[:5]))
            self._append_log(job_id, f"✅ {len(files)} arquivo(s) conferidos por SHA-256")

            # 2. Consistencia ESE do NTDS copiado
            ntds = os.path.join(snapshot_dir, "AD_IFM", "Active Directory", "ntds.dit")
            if not os.path.exists(ntds):
                raise RuntimeError("ntds.dit não encontrado no backup.")
            try:
                rc, out = _dr._run_console(["esentutl", "/mh", ntds], timeout=600)
            except (OSError, subprocess.TimeoutExpired) as ex:
                rc, out = -1, str(ex)
            state = next((l.split(":", 1)[1].strip() for l in out.splitlines() if l.strip().lower().startswith(("state:", "estado:"))), None)
            if rc != 0 or not state or not ("clean" in state.lower() or "limp" in state.lower()):
                raise RuntimeError(f"NTDS do backup não está consistente (esentutl código {rc}, estado: {state or 'não identificado'}).")
            self._append_log(job_id, f"✅ NTDS consistente (esentutl /mh: {state})")
            self._update_progress(job_id, 80)

            # 3. Roteiro exato para o DSRM (substituicao do banco nao e possivel com o AD em execucao)
            ifm = os.path.join(snapshot_dir, "AD_IFM")
            steps = [
                "1. bcdedit /set safeboot dsrepair  e reinicie o DC (modo DSRM).",
                "2. Confirme o caminho atual da base NTDS: reg query HKLM\\SYSTEM\\CurrentControlSet\\Services\\NTDS\\Parameters /v \"DSA Database file\"",
                f"3. Copie \"{os.path.join(ifm, 'Active Directory')}\\*\" para a pasta da base NTDS (ex.: C:\\Windows\\NTDS).",
            ]
            if restore_sysvol:
                steps.append(f"4. Restaure o SYSVOL a partir de \"{os.path.join(ifm, 'SYSVOL')}\" (restauração autoritativa do DFSR se este for o único DC).")
            if restore_mode == "authoritative":
                steps.append("5. ntdsutil \"activate instance ntds\" \"authoritative restore\" \"restore subtree <DN>\" quit quit")
            steps.append("6. bcdedit /deletevalue safeboot  e reinicie em modo normal; valide com dcdiag /v e repadmin /replsummary.")
            script = os.path.join(snapshot_dir, "Restore_Staging", "PASSOS_DSRM.txt")
            os.makedirs(os.path.dirname(script), exist_ok=True)
            with open(script, "w", encoding="utf-8") as f:
                f.write("\n".join(steps) + "\n")
            for s_ in steps:
                self._append_log(job_id, s_)
            self._append_log(job_id, f"✅ Backup verificado e pronto para restauração em DSRM. Roteiro salvo em {script}. Nenhuma alteração foi feita no AD em execução.")
            self._finish(job_id, "completed")
        except Exception as e:
            logger.error(f"Erro na restauração do AD {job_id}: {e}", exc_info=True)
            self._append_log(job_id, f"❌ Restauração não preparada: {e}")
            self._finish(job_id, "failed", str(e))

    def _update_progress(self, job_id: str, progress: int):
        with self.lock:
            if job_id in self.active_jobs:
                self.active_jobs[job_id]["progress"] = progress

    def list_ad_backup_history(self) -> List[Dict[str, Any]]:
        history = []
        if not self.base_ad_dir.exists():
            return history

        for item in sorted(self.base_ad_dir.iterdir(), reverse=True):
            if item.is_dir():
                manifest_file = item / "ad_backup_manifest.json"
                if manifest_file.exists():
                    try:
                        with open(manifest_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            total_size = sum(f.stat().st_size for f in item.glob('**/*') if f.is_file())
                            data["backup_dir"] = str(item)
                            data["backup_name"] = item.name
                            data["size_mb"] = round(total_size / (1024 * 1024), 2)
                            history.append(data)
                    except Exception:
                        pass
        return history

    def delete_ad_snapshot(self, snapshot_name: str) -> bool:
        snapshot_dir = self.base_ad_dir / snapshot_name
        if snapshot_dir.exists() and snapshot_dir.is_dir():
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            return True
        return False

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            job = self.active_jobs.get(job_id)
            if job:
                return {k: v for k, v in job.items() if k != "thread"}
        return None

    def generate_authoritative_restore_script(self, target_ou_dn: str) -> Dict[str, Any]:
        script_content = f"""
# ==============================================================================
# Script de Restauração Autoritativa do Active Directory (NTDSUTIL)
# Objeto Alvo: {target_ou_dn}
# Gerado pelo GBOC Agent v14.8.2 Enterprise
# ==============================================================================

# 1. Reinicie o Controlador de Domínio no modo DSRM (Directory Services Restore Mode)
# 2. Execute a restauração não-autoritativa do System State / NTDS.dit via GBOC Restore
# 3. ANTES de reiniciar em modo normal, execute os comandos abaixo no Prompt de Comando Administrativo:

ntdsutil
authoritative restore
restore subtree "{target_ou_dn}"
quit
quit

# 4. Reinicie o servidor em modo normal. Os números de versão USN dos objetos
# restaurados serão incrementados em 100.000 para sobrepor as réplicas dos outros DCs.
"""
        return {
            "target_ou_dn": target_ou_dn,
            "script": script_content.strip(),
            "instructions": "Execute os comandos no modo DSRM antes de reiniciar o DC para autorizar a sobreposição USN nos parceiros de replicação.",
            "timestamp": datetime.now().isoformat()
        }


# Singleton global
ad_backup_engine = ActiveDirectoryBackupEngine()
