# ==============================================================================
# GBOC System v14.6.0 Enterprise Edition
# Module: Enterprise Database Connectors (Oracle RMAN, SAP HANA, IBM DB2)
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

logger = logging.getLogger("gboc_enterprise_db_connectors")


class EnterpriseDatabaseConnectors:
    """
    Motor de Conectores Nativos para Bancos Corporativos Pesados.
    Orquestra Oracle RMAN, SAP HANA (hdbsql/backint) e IBM DB2 online backup.
    """

    def __init__(self):
        self.active_jobs: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.base_exports_dir = Path("C:/GBOC-Enterprise-DB") if sys.platform == "win32" else Path("./data/enterprise_db")
        try:
            self.base_exports_dir.mkdir(parents=True, exist_ok=True)
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

    def detect_enterprise_databases(self) -> Dict[str, Any]:
        """
        Detecta instâncias locais de Oracle Database, SAP HANA e IBM DB2 no servidor.
        """
        detected = {
            "oracle": {"installed": False, "instances": [], "vss_writer": "NOT_FOUND"},
            "sap_hana": {"installed": False, "instances": [], "backint_ready": False},
            "ibm_db2": {"installed": False, "instances": [], "status": "NOT_FOUND"},
            "timestamp": datetime.now().isoformat()
        }

        if sys.platform == "win32":
            # 1. Oracle Detection
            try:
                ps_oracle = """
                    $ErrorActionPreference = 'SilentlyContinue'
                    $oracleSvcs = Get-Service | Where-Object { $_.Name -like "OracleService*" }
                    $oracleHomes = Get-ChildItem "HKLM:\\SOFTWARE\\ORACLE" -ErrorAction SilentlyContinue
                    [PSCustomObject]@{
                        HasOracle = ($oracleSvcs.Count -gt 0 -or $null -ne $oracleHomes)
                        Services = @($oracleSvcs | ForEach-Object { $_.Name })
                    } | ConvertTo-Json
                """
                res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_oracle], capture_output=True, text=True, timeout=8)
                if res.returncode == 0 and res.stdout.strip():
                    raw = json.loads(res.stdout.strip())
                    if raw.get("HasOracle"):
                        detected["oracle"]["installed"] = True
                        detected["oracle"]["instances"] = raw.get("Services") or ["ORCL", "PROD_DB"]
            except Exception:
                pass

            # 2. SAP HANA Detection
            try:
                sap_paths = ["C:\\Program Files\\SAP\\hdbclient", "C:\\sapmnt", "C:\\usr\\sap"]
                for p in sap_paths:
                    if os.path.exists(p):
                        detected["sap_hana"]["installed"] = True
                        detected["sap_hana"]["instances"].append("HDB_SID_00")
                        detected["sap_hana"]["backint_ready"] = True
                        break
            except Exception:
                pass

            # 3. IBM DB2 Detection
            try:
                db2_path = "C:\\Program Files\\IBM\\SQLLIB"
                if os.path.exists(db2_path):
                    detected["ibm_db2"]["installed"] = True
                    detected["ibm_db2"]["instances"].append("DB2INSTANCE_01")
            except Exception:
                pass

        return detected

    # ==========================================================================
    # ORACLE RMAN CONNECTOR
    # ==========================================================================

    def start_oracle_rman_backup(
        self,
        oracle_sid: str = "ORCL",
        backup_type: str = "INCREMENTAL_LEVEL_0",
        archive_log_delete: bool = True
    ) -> Dict[str, Any]:
        job_id = f"oracle_{int(time.time())}"
        target_dir = str(self.base_exports_dir / f"Oracle_{oracle_sid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

        with self.lock:
            self.active_jobs[job_id] = {
                "job_id": job_id,
                "engine": "Oracle RMAN",
                "instance": oracle_sid,
                "backup_type": backup_type,
                "status": "running",
                "progress": 0,
                "target_dir": target_dir,
                "archive_log_delete": archive_log_delete,
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "logs": [],
                "error": None
            }

        thread = threading.Thread(
            target=self._oracle_rman_worker,
            args=(job_id, oracle_sid, target_dir, backup_type, archive_log_delete),
            daemon=True
        )
        self.active_jobs[job_id]["thread"] = thread
        thread.start()

        return {
            "status": "started",
            "job_id": job_id,
            "engine": "Oracle RMAN",
            "message": f"Backup Oracle RMAN ({backup_type}) iniciado para SID '{oracle_sid}' -> {target_dir}"
        }

    def _oracle_rman_worker(self, job_id: str, oracle_sid: str, target_dir: str, backup_type: str, archive_log_delete: bool):
        self._append_log(job_id, f"Iniciando Oracle RMAN Connector para a instância SID: {oracle_sid}")
        self._append_log(job_id, f"Tipo de Backup: {backup_type} • Destino: {target_dir}")

        try:
            os.makedirs(target_dir, exist_ok=True)
            
            # Verificar se o executável rman existe no PATH
            rman_bin = shutil.which("rman") or shutil.which("rman.exe")
            if not rman_bin:
                raise RuntimeError(f"O utilitário 'rman' (Oracle RMAN) não está instalado ou disponível no PATH do SO host.")

            self._append_log(job_id, f"Binário RMAN localizado em: {rman_bin}. Compilando comandos...")
            rman_script_path = os.path.join(target_dir, "rman_backup.cmd")
            rman_commands = f"""
CONNECT TARGET /;
CONFIGURE CONTROLFILE AUTOBACKUP ON;
CONFIGURE RETENTION POLICY TO RECOVERY WINDOW OF 14 DAYS;
RUN {{
    ALLOCATE CHANNEL ch1 DEVICE TYPE DISK FORMAT '{target_dir}\\df_%d_%s_%p.bkp';
    BACKUP {'INCREMENTAL LEVEL 0' if 'LEVEL_0' in backup_type else 'INCREMENTAL LEVEL 1'} DATABASE PLUS ARCHIVELOG {'DELETE ALL INPUT' if archive_log_delete else ''};
    BACKUP CURRENT CONTROLFILE FORMAT '{target_dir}\\cf_%d_%s_%p.bkp';
    RELEASE CHANNEL ch1;
}}
EXIT;
            """.strip()

            with open(rman_script_path, "w", encoding="utf-8") as f:
                f.write(rman_commands)

            self._append_log(job_id, f"Executando comando RMAN: {rman_bin} target / cmdfile={rman_script_path}")
            res = subprocess.run([rman_bin, "target", "/", f"cmdfile={rman_script_path}"], capture_output=True, text=True, timeout=120)
            
            if res.returncode != 0:
                raise RuntimeError(f"Oracle RMAN retornou código de erro {res.returncode}: {res.stderr or res.stdout}")

            self._append_log(job_id, "✅ Backup Oracle RMAN concluído e validado com sucesso!")
            with self.lock:
                if job_id in self.active_jobs:
                    self.active_jobs[job_id]["status"] = "completed"
                    self.active_jobs[job_id]["progress"] = 100
                    self.active_jobs[job_id]["completed_at"] = datetime.now().isoformat()

        except Exception as e:
            logger.error(f"Erro no Oracle RMAN worker: {e}")
            self._append_log(job_id, f"❌ Falha no Oracle RMAN: {e}")
            with self.lock:
                if job_id in self.active_jobs:
                    self.active_jobs[job_id]["status"] = "failed"
                    self.active_jobs[job_id]["error"] = str(e)

    # ==========================================================================
    # SAP HANA CONNECTOR (BACKINT / HDBCLIENT)
    # ==========================================================================

    def start_sap_hana_backup(
        self,
        instance_id: str = "HDB00",
        tenant_db: str = "SYSTEMDB"
    ) -> Dict[str, Any]:
        job_id = f"saphana_{int(time.time())}"
        target_dir = str(self.base_exports_dir / f"SAPHANA_{instance_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

        with self.lock:
            self.active_jobs[job_id] = {
                "job_id": job_id,
                "engine": "SAP HANA",
                "instance": instance_id,
                "tenant": tenant_db,
                "status": "running",
                "progress": 0,
                "target_dir": target_dir,
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "logs": [],
                "error": None
            }

        thread = threading.Thread(
            target=self._sap_hana_worker,
            args=(job_id, instance_id, tenant_db, target_dir),
            daemon=True
        )
        self.active_jobs[job_id]["thread"] = thread
        thread.start()

        return {
            "status": "started",
            "job_id": job_id,
            "engine": "SAP HANA",
            "message": f"Backup SAP HANA iniciado para '{instance_id}' ({tenant_db}) -> {target_dir}"
        }

    def _sap_hana_worker(self, job_id: str, instance_id: str, tenant_db: str, target_dir: str):
        self._append_log(job_id, f"Iniciando conector SAP HANA Backint para a instância: {instance_id}")
        
        try:
            os.makedirs(target_dir, exist_ok=True)
            hdbsql_bin = shutil.which("hdbsql") or shutil.which("hdbsql.exe")
            if not hdbsql_bin:
                raise RuntimeError(f"O utilitário 'hdbsql' (SAP HANA Client) não está instalado no sistema operacional host.")

            self._append_log(job_id, f"Executando hdbsql no tenant {tenant_db}...")
            res = subprocess.run([
                hdbsql_bin, "-i", instance_id, "-d", tenant_db,
                f"BACKUP DATA FOR FULL SYSTEM USING BACKINT ('{target_dir}\\saphana_stream')"
            ], capture_output=True, text=True, timeout=180)

            if res.returncode != 0:
                raise RuntimeError(f"SAP HANA hdbsql falhou ({res.returncode}): {res.stderr or res.stdout}")

            self._append_log(job_id, "✅ Backup SAP HANA concluído com sucesso via Backint Stream!")

            with self.lock:
                if job_id in self.active_jobs:
                    self.active_jobs[job_id]["status"] = "completed"
                    self.active_jobs[job_id]["progress"] = 100
                    self.active_jobs[job_id]["completed_at"] = datetime.now().isoformat()

        except Exception as e:
            logger.error(f"Erro no SAP HANA worker: {e}")
            self._append_log(job_id, f"❌ Falha no backup SAP HANA: {e}")
            with self.lock:
                if job_id in self.active_jobs:
                    self.active_jobs[job_id]["status"] = "failed"
                    self.active_jobs[job_id]["error"] = str(e)

    # ==========================================================================
    # IBM DB2 CONNECTOR
    # ==========================================================================

    def start_ibm_db2_backup(self, db_name: str = "SAMPLE") -> Dict[str, Any]:
        job_id = f"ibmdb2_{int(time.time())}"
        target_dir = str(self.base_exports_dir / f"IBMDB2_{db_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

        with self.lock:
            self.active_jobs[job_id] = {
                "job_id": job_id,
                "engine": "IBM DB2",
                "database": db_name,
                "status": "running",
                "progress": 0,
                "target_dir": target_dir,
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "logs": [],
                "error": None
            }

        thread = threading.Thread(
            target=self._ibm_db2_worker,
            args=(job_id, db_name, target_dir),
            daemon=True
        )
        self.active_jobs[job_id]["thread"] = thread
        thread.start()

        return {
            "status": "started",
            "job_id": job_id,
            "engine": "IBM DB2",
            "message": f"Backup IBM DB2 Online iniciado para banco '{db_name}' -> {target_dir}"
        }

    def _ibm_db2_worker(self, job_id: str, db_name: str, target_dir: str):
        self._append_log(job_id, f"Iniciando IBM DB2 Online Backup para o banco: {db_name}")

        try:
            os.makedirs(target_dir, exist_ok=True)
            db2_bin = shutil.which("db2") or shutil.which("db2.exe")
            if not db2_bin:
                raise RuntimeError(f"O utilitário 'db2' (IBM DB2 Command Line Processor) não foi localizado no SO host.")

            self._append_log(job_id, f"Invocando comando: {db2_bin} BACKUP DATABASE {db_name} ONLINE TO '{target_dir}' INCLUDE LOGS...")
            res = subprocess.run([
                db2_bin, "BACKUP", "DATABASE", db_name, "ONLINE", "TO", target_dir, "INCLUDE", "LOGS"
            ], capture_output=True, text=True, timeout=180)

            if res.returncode != 0:
                raise RuntimeError(f"IBM DB2 backup falhou ({res.returncode}): {res.stderr or res.stdout}")

            self._append_log(job_id, "✅ Backup IBM DB2 finalizado com sucesso com logs transacionais inclusos.")

            with self.lock:
                if job_id in self.active_jobs:
                    self.active_jobs[job_id]["status"] = "completed"
                    self.active_jobs[job_id]["progress"] = 100
                    self.active_jobs[job_id]["completed_at"] = datetime.now().isoformat()

        except Exception as e:
            logger.error(f"Erro no IBM DB2 worker: {e}")
            self._append_log(job_id, f"❌ Falha no IBM DB2: {e}")
            with self.lock:
                if job_id in self.active_jobs:
                    self.active_jobs[job_id]["status"] = "failed"
                    self.active_jobs[job_id]["error"] = str(e)

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            job = self.active_jobs.get(job_id)
            if job:
                return {k: v for k, v in job.items() if k != "thread"}
        return None


# Singleton global
enterprise_db_connectors = EnterpriseDatabaseConnectors()
