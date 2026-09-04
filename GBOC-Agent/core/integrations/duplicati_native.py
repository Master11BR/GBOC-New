#!/usr/bin/env python3
"""
Integração nativa inicial com Duplicati (módulo isolado).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from engines.engine_paths import get_engine_path

logger = logging.getLogger("DuplicatiNative")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_FILE = os.path.join(DATA_DIR, "duplicati_native_config.json")


@dataclass
class DuplicatiConfig:
    base_url: str = "http://localhost:8200"
    username: str = ""
    password: str = ""
    verify_tls: bool = False
    timeout_seconds: int = 8


class DuplicatiNativeService:
    def __init__(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        self._session = requests.Session()
        self._xsrf_token: Optional[str] = None
        self._authenticated: bool = False

    # ──────────────────────────────────────────────
    # Config
    # ──────────────────────────────────────────────

    def load_config(self) -> DuplicatiConfig:
        if not os.path.exists(CONFIG_FILE):
            return DuplicatiConfig()
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return DuplicatiConfig(
                base_url=str(raw.get("base_url", "http://localhost:8200")).rstrip("/"),
                username=str(raw.get("username", "")),
                password=str(raw.get("password", "")),
                verify_tls=bool(raw.get("verify_tls", False)),
                timeout_seconds=int(raw.get("timeout_seconds", 8)),
            )
        except Exception as e:
            logger.warning(f"Falha ao carregar config do Duplicati: {e}")
            return DuplicatiConfig()

    def save_config(self, payload: Dict[str, Any]) -> DuplicatiConfig:
        current = self.load_config()
        next_cfg = DuplicatiConfig(
            base_url=str(payload.get("base_url", current.base_url)).rstrip("/"),
            username=str(payload.get("username", current.username)),
            password=str(payload.get("password", current.password)),
            verify_tls=bool(payload.get("verify_tls", current.verify_tls)),
            timeout_seconds=max(2, int(payload.get("timeout_seconds", current.timeout_seconds))),
        )
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "base_url": next_cfg.base_url,
                "username": next_cfg.username,
                "password": next_cfg.password,
                "verify_tls": next_cfg.verify_tls,
                "timeout_seconds": next_cfg.timeout_seconds,
            }, f, ensure_ascii=False, indent=2)
        # Invalidar sessão ao salvar nova config
        self._authenticated = False
        self._xsrf_token = None
        self._session = requests.Session()
        return next_cfg

    # ──────────────────────────────────────────────
    # Autenticação por sessão + XSRF (Duplicati v2.x)
    # ──────────────────────────────────────────────

    def _login(self, cfg: DuplicatiConfig) -> bool:
        """
        Realiza login na API do Duplicati.
        Suporta dois fluxos:
          - v2.3+ (Kestrel/JWT): POST /api/v1/auth/login → {"AccessToken": "<jwt>"}
          - v2.x legado: GET / → xsrf-token → POST /login.cgi
        Sem senha configurada, tenta acesso direto (Duplicati sem senha).
        """
        try:
            # ── 1. Tentar ler XSRF token da página inicial ──────────────────────
            home = self._session.get(
                cfg.base_url + "/",
                timeout=cfg.timeout_seconds,
                verify=cfg.verify_tls,
                allow_redirects=True,
            )
            xsrf = (
                home.cookies.get("xsrf-token")
                or home.cookies.get("XSRF-TOKEN")
                or home.headers.get("X-XSRF-Token", "")
            )
            if xsrf:
                self._xsrf_token = xsrf
                self._session.headers.update({"X-XSRF-Token": xsrf})

            if cfg.password:
                self._session.headers.update({"X-Duplicati-Password": cfg.password})

            # ── 2. Fluxo v2.3+: JWT via /api/v1/auth/login ──────────────────────
            login_url_jwt = cfg.base_url + "/api/v1/auth/login"
            resp_jwt = self._session.post(
                login_url_jwt,
                json={"Password": cfg.password, "password": cfg.password},
                timeout=cfg.timeout_seconds,
                verify=cfg.verify_tls,
            )
            if resp_jwt.status_code == 200:
                try:
                    token = resp_jwt.json().get("AccessToken", "")
                    if token:
                        self._session.headers.update({"Authorization": f"Bearer {token}"})
                        self._xsrf_token = token
                        self._authenticated = True
                        logger.info("✅ Autenticado no Duplicati v2.3+ via JWT")
                        return True
                except Exception:
                    pass

            # ── 3. Fluxo v2.x legado: POST /login.cgi ou /api/v1/login ──────────────
            if cfg.password:
                for login_path in ["/login.cgi", "/api/v1/login"]:
                    login_url = cfg.base_url + login_path
                    resp = self._session.post(
                        login_url,
                        data={"Password": cfg.password, "password": cfg.password},
                        headers={"X-XSRF-Token": self._xsrf_token or ""},
                        timeout=cfg.timeout_seconds,
                        verify=cfg.verify_tls,
                    )
                    if resp.status_code in (200, 302, 303):
                        new_xsrf = (
                            resp.cookies.get("xsrf-token")
                            or resp.cookies.get("XSRF-TOKEN")
                            or resp.headers.get("X-XSRF-Token", "")
                        )
                        if new_xsrf:
                            self._xsrf_token = new_xsrf
                            self._session.headers.update({"X-XSRF-Token": new_xsrf})
                        self._authenticated = True
                        logger.info(f"✅ Autenticado no Duplicati via {login_path}")
                        return True

            # Se a checagem básica no /api/v1/serverstate passar, a conexão está OK
            chk = self._session.get(f"{cfg.base_url}/api/v1/serverstate", timeout=cfg.timeout_seconds, verify=cfg.verify_tls, params={"password": cfg.password} if cfg.password else None)
            if chk.status_code == 200:
                self._authenticated = True
                logger.info("✅ Conexão Duplicati estabelecida com sucesso")
                return True

            logger.warning("Falha no login Duplicati com as credenciais fornecidas.")
            return False

        except Exception as e:
            logger.warning(f"Erro no login Duplicati: {e}")
            return False

    def _ensure_authenticated(self, cfg: DuplicatiConfig) -> bool:
        """Garante que a sessão está autenticada; refaz login se necessário."""
        if self._authenticated:
            return True
        return self._login(cfg)

    def _api_get(self, cfg: DuplicatiConfig, path: str) -> requests.Response:
        """GET autenticado com retry de login se receber 401/403."""
        self._ensure_authenticated(cfg)
        url = f"{cfg.base_url}/{path.lstrip('/')}"
        resp = self._session.get(
            url,
            timeout=cfg.timeout_seconds,
            verify=cfg.verify_tls,
        )
        if resp.status_code in (401, 403):
            # Sessão expirada — refaz login
            self._authenticated = False
            self._xsrf_token = None
            if self._login(cfg):
                resp = self._session.get(url, timeout=cfg.timeout_seconds, verify=cfg.verify_tls)
        return resp

    def _api_put(self, cfg: DuplicatiConfig, path: str, json_body: Any = None) -> requests.Response:
        """PUT autenticado com retry de login se receber 401/403."""
        self._ensure_authenticated(cfg)
        url = f"{cfg.base_url}/{path.lstrip('/')}"
        headers = {"X-XSRF-Token": self._xsrf_token or ""}
        resp = self._session.put(
            url,
            json=json_body,
            headers=headers,
            timeout=cfg.timeout_seconds,
            verify=cfg.verify_tls,
        )
        if resp.status_code in (401, 403):
            self._authenticated = False
            self._xsrf_token = None
            if self._login(cfg):
                headers = {"X-XSRF-Token": self._xsrf_token or ""}
                resp = self._session.put(url, json=json_body, headers=headers,
                                         timeout=cfg.timeout_seconds, verify=cfg.verify_tls)
        return resp

    def _api_post(self, cfg: DuplicatiConfig, path: str, json_body: Any = None, data: Any = None) -> requests.Response:
        """POST autenticado com retry de login se receber 401/403."""
        self._ensure_authenticated(cfg)
        url = f"{cfg.base_url}/{path.lstrip('/')}"
        headers = {"X-XSRF-Token": self._xsrf_token or ""}
        resp = self._session.post(
            url,
            json=json_body,
            data=data,
            headers=headers,
            timeout=cfg.timeout_seconds,
            verify=cfg.verify_tls,
        )
        if resp.status_code in (401, 403):
            self._authenticated = False
            self._xsrf_token = None
            if self._login(cfg):
                headers = {"X-XSRF-Token": self._xsrf_token or ""}
                resp = self._session.post(url, json=json_body, data=data, headers=headers,
                                          timeout=cfg.timeout_seconds, verify=cfg.verify_tls)
        return resp

    # ──────────────────────────────────────────────
    # Métodos públicos existentes (interface preservada)
    # ──────────────────────────────────────────────

    def _build_url(self, cfg: DuplicatiConfig, path: str) -> str:
        return f"{cfg.base_url}/{path.lstrip('/')}"

    def _mask(self, value: str) -> str:
        if not value:
            return ""
        if len(value) <= 2:
            return "*" * len(value)
        return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"

    def get_config_summary(self) -> Dict[str, Any]:
        cfg = self.load_config()
        return {
            "base_url": cfg.base_url,
            "username": cfg.username,
            "password_masked": self._mask(cfg.password),
            "verify_tls": cfg.verify_tls,
            "timeout_seconds": cfg.timeout_seconds,
            "config_file": CONFIG_FILE,
            "authenticated": self._authenticated,
        }

    def detect_local_installation(self) -> Dict[str, Any]:
        path = get_engine_path("duplicati")
        return {
            "detected": bool(path),
            "path": path,
        }

    def discover_endpoints(self) -> List[str]:
        candidates = [
            "http://localhost:8200",
            "http://127.0.0.1:8200",
            "http://localhost:8300",
            "http://127.0.0.1:8300",
        ]
        found: List[str] = []
        for base in candidates:
            try:
                response = self._session.get(f"{base}/", timeout=2)
                if response.status_code < 500:
                    found.append(base)
            except Exception:
                continue
        return found

    def probe(self) -> Dict[str, Any]:
        cfg = self.load_config()

        # 1. Testar conectividade HTTP básica no servidor Duplicati
        server_reachable = False
        try:
            r = self._session.get(f"{cfg.base_url}/", timeout=cfg.timeout_seconds, verify=cfg.verify_tls)
            if r.status_code < 500:
                server_reachable = True
        except Exception:
            pass

        probe_paths = [
            "api/v1/serverstate",
            "api/v1/systeminfo",
            "api/v1/backups",
        ]
        results = []
        ok = False
        auth_required = False

        for path in probe_paths:
            try:
                resp = self._api_get(cfg, path)
                status = resp.status_code
                results.append({"url": self._build_url(cfg, path), "status": status})
                if status == 200:
                    ok = True
                elif status == 401:
                    auth_required = True
            except Exception as e:
                results.append({"url": self._build_url(cfg, path), "status": "error", "error": str(e)})

        install = self.detect_local_installation()
        if ok:
            status_msg = "✅ Conectado e autenticado no Duplicati!"
        elif server_reachable or auth_required:
            status_msg = "🟢 Instância do Duplicati detectada e rodando! (Configure a senha de acesso web se exigida)."
        else:
            status_msg = "❌ Servidor Duplicati não foi localizado no endereço especificado."

        return {
            "ok": ok or server_reachable or auth_required,
            "message": status_msg,
            "base_url": cfg.base_url,
            "authenticated": self._authenticated,
            "auth_required": auth_required,
            "installation": install,
            "probes": results,
            "discovered": self.discover_endpoints(),
        }

    def _read_duplicati_server_db(self) -> List[Dict[str, Any]]:
        """Lê os backups e todas as métricas detalhadas do arquivo SQLite local do Duplicati."""
        import sqlite3
        db_paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\Duplicati\Duplicati-server.sqlite"),
            os.path.expandvars(r"%APPDATA%\Duplicati\Duplicati-server.sqlite"),
            r"C:\ProgramData\Duplicati\Duplicati-server.sqlite",
            "/var/lib/duplicati/Duplicati-server.sqlite",
            os.path.expanduser("~/.config/Duplicati/Duplicati-server.sqlite"),
        ]

        def fix_iso_date(raw_val: Any) -> Optional[str]:
            if not raw_val:
                return None
            s = str(raw_val).strip()
            if len(s) == 16 and s[8] == 'T' and s[15] == 'Z':
                return f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}Z"
            return s

        for path in db_paths:
            if os.path.isfile(path):
                try:
                    conn = sqlite3.connect(path)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute("SELECT ID, Name, Description, TargetURL FROM Backup")
                    rows = cur.fetchall()
                    backups = []

                    for row in rows:
                        b_id = str(row["ID"])
                        name = row["Name"] or f"Backup #{b_id}"
                        desc = row["Description"] or ""
                        target_url = str(row["TargetURL"] or "")

                        dest_label = "Destino Remoto"
                        if "wasabi" in target_url.lower():
                            dest_label = "Wasabi S3"
                        elif "s3.amazonaws" in target_url.lower():
                            dest_label = "Amazon S3"
                        elif "b2" in target_url.lower():
                            dest_label = "Backblaze B2"
                        elif "azure" in target_url.lower():
                            dest_label = "Azure Blob"
                        elif "file://" in target_url.lower() or ":" in target_url:
                            dest_label = "Disco Local / Pasta"

                        metadata = {}
                        try:
                            cur.execute("SELECT Name, Value FROM Metadata WHERE BackupID = ?", (b_id,))
                            for m in cur.fetchall():
                                metadata[m["Name"]] = m["Value"]
                        except Exception:
                            pass

                        schedule_info = {}
                        try:
                            cur.execute("SELECT Time, Repeat, LastRun FROM Schedule WHERE Tags LIKE ?", (f"%ID={b_id}%",))
                            sch = cur.fetchone()
                            if sch:
                                schedule_info = {
                                    "repeat": sch["Repeat"] or "Manual",
                                    "next_run_ts": sch["Time"],
                                    "last_run_ts": sch["LastRun"]
                                }
                        except Exception:
                            pass

                        last_backup_date = fix_iso_date(metadata.get("LastBackupDate"))
                        last_result = metadata.get("LastBackupResult", "OK")
                        source_size = metadata.get("SourceFilesSize", "0")
                        target_size = metadata.get("TargetFilesSize", "0")
                        versions_count = metadata.get("BackupListCount", "0")
                        duration = metadata.get("LastBackupDuration", "")

                        metadata["LastBackupDate"] = last_backup_date
                        metadata["LastBackupStarted"] = fix_iso_date(metadata.get("LastBackupStarted"))
                        metadata["LastBackupFinished"] = fix_iso_date(metadata.get("LastBackupFinished"))
                        metadata["TargetURL"] = target_url

                        backups.append({
                            "id": b_id,
                            "name": name,
                            "description": desc,
                            "target_label": dest_label,
                            "last_run": last_backup_date,
                            "last_status": last_result,
                            "source_size": source_size,
                            "target_size": target_size,
                            "versions_count": versions_count,
                            "duration": duration,
                            "schedule": schedule_info,
                            "source": "sqlite_database",
                            "Backup": {
                                "ID": b_id,
                                "Name": name,
                                "Description": desc,
                                "TargetURL": target_url,
                                "Metadata": metadata
                            }
                        })
                    conn.close()
                    if backups:
                        logger.info(f"✅ {len(backups)} backup(s) enriquecido(s) do SQLite do Duplicati ({path})")
                        return backups
                except Exception as e:
                    logger.warning(f"Erro ao ler banco do Duplicati em {path}: {e}")

        return []

    def list_backups(self) -> Dict[str, Any]:
        cfg = self.load_config()
        paths = ["api/v1/backups", "api/v1/backup"]
        last_error: Optional[str] = None
        for path in paths:
            try:
                resp = self._api_get(cfg, path)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict):
                        for key in ("Backups", "backups", "Items", "items"):
                            if key in data and isinstance(data[key], list):
                                return {"status": "success", "items": data[key], "source": self._build_url(cfg, path)}
                        return {"status": "success", "items": [data], "source": self._build_url(cfg, path)}
                    if isinstance(data, list):
                        return {"status": "success", "items": data, "source": self._build_url(cfg, path)}
            except Exception as e:
                last_error = str(e)

        # Fallback: tentar ler diretamente do SQLite local do Duplicati
        db_items = self._read_duplicati_server_db()
        if db_items:
            return {
                "status": "success",
                "items": db_items,
                "source": "sqlite_local_db"
            }

        return {
            "status": "error",
            "message": "Não foi possível listar backups no Duplicati",
            "error": last_error or "Nenhum backup encontrado no servidor HTTP nem no banco SQLite",
            "items": [],
        }

    def list_filesets(self, backup_id: str) -> List[Dict[str, Any]]:
        """Lista os filesets (snapshots / pontos no tempo) reais de um backup do Duplicati."""
        cfg = self.load_config()

        # 1. Tentar via API HTTP do Duplicati
        try:
            resp = self._api_get(cfg, f"api/v1/backup/{backup_id}/filesets")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    snapshots = []
                    for idx, fs in enumerate(data):
                        ver = str(fs.get("Version", idx))
                        ts = fs.get("Time") or fs.get("Timestamp")
                        filecount = fs.get("FileCount", 0)
                        size = fs.get("FileSizes", 0)
                        size_str = f"{round(size/1024/1024, 2)} MB" if size else ""
                        snapshots.append({
                            "id": f"v{ver}",
                            "full_id": f"v{ver}",
                            "short_id": f"v{ver}",
                            "version": ver,
                            "time": str(ts),
                            "hostname": "Duplicati",
                            "username": "Duplicati",
                            "paths": [f"{filecount} arquivos {size_str}".strip()],
                            "engine": "duplicati"
                        })
                    if snapshots:
                        return snapshots
        except Exception as e:
            logger.warning(f"Erro ao obter filesets via HTTP: {e}")

        # 2. Fallback via SQLite local do backup (DBPath)
        try:
            import sqlite3
            from datetime import datetime
            db_items = self._read_duplicati_server_db()
            db_path = ""
            for item in db_items:
                b = item.get("Backup", {})
                if str(b.get("ID")) == str(backup_id) or str(item.get("id")) == str(backup_id):
                    db_path = b.get("DBPath") or item.get("DBPath", "")
                    break

            if db_path and os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT ID, Timestamp, OperationID FROM Fileset ORDER BY Timestamp DESC")
                rows = cur.fetchall()
                snapshots = []
                for idx, r in enumerate(rows):
                    ver = str(idx)
                    ts = r["Timestamp"]
                    if isinstance(ts, (int, float)):
                        ts_str = datetime.fromtimestamp(ts).isoformat()
                    else:
                        ts_str = str(ts)
                    snapshots.append({
                        "id": f"v{ver}",
                        "full_id": f"v{ver}",
                        "short_id": f"v{ver}",
                        "version": ver,
                        "time": ts_str,
                        "hostname": "Duplicati Native",
                        "username": "Duplicati",
                        "paths": ["Backup Completo Duplicati"],
                        "engine": "duplicati"
                    })
                conn.close()
                if snapshots:
                    return snapshots
        except Exception as e:
            logger.warning(f"Erro ao ler filesets do SQLite do backup: {e}")

        return []

    # ──────────────────────────────────────────────
    # Controle de Jobs (run / stop / progress)
    # ──────────────────────────────────────────────

    def run_backup(self, backup_id: str) -> Dict[str, Any]:
        """Inicia um job de backup manualmente."""
        cfg = self.load_config()
        try:
            resp = self._api_post(cfg, f"api/v1/backup/{backup_id}/run")
            if resp.status_code == 200:
                return {"status": "success", "message": f"Backup {backup_id} iniciado"}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def stop_backup(self, backup_id: str, abort: bool = False) -> Dict[str, Any]:
        """Para ou aborta um job de backup em execução."""
        cfg = self.load_config()
        action = "abort" if abort else "stop"
        try:
            resp = self._api_post(cfg, f"api/v1/backup/{backup_id}/{action}")
            if resp.status_code == 200:
                return {"status": "success", "message": f"Backup {backup_id} {action}"}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_progress(self) -> Dict[str, Any]:
        """Retorna o estado de progresso atual do Duplicati."""
        cfg = self.load_config()
        try:
            resp = self._api_get(cfg, "api/v1/progressstate")
            if resp.status_code == 200:
                return {"status": "success", "progress": resp.json()}
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_server_state(self) -> Dict[str, Any]:
        """Retorna o estado atual do servidor Duplicati (programed, running, paused...)."""
        cfg = self.load_config()
        try:
            resp = self._api_get(cfg, "api/v1/serverstate")
            if resp.status_code == 200:
                return {"status": "success", "state": resp.json()}
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_backup_log(self, backup_id: str, page_size: int = 20) -> Dict[str, Any]:
        """Retorna o log de execuções de um job específico."""
        cfg = self.load_config()
        try:
            resp = self._api_get(cfg, f"api/v1/backup/{backup_id}/log?pagesize={page_size}")
            if resp.status_code == 200:
                return {"status": "success", "log": resp.json()}
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def pause_server(self) -> Dict[str, Any]:
        """Pausa o agendador do Duplicati."""
        cfg = self.load_config()
        try:
            resp = self._api_post(cfg, "api/v1/serverstate/pause")
            return {"status": "success" if resp.status_code == 200 else "error",
                    "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def resume_server(self) -> Dict[str, Any]:
        """Retoma o agendador do Duplicati."""
        cfg = self.load_config()
        try:
            resp = self._api_post(cfg, "api/v1/serverstate/resume")
            return {"status": "success" if resp.status_code == 200 else "error",
                    "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ──────────────────────────────────────────────
    # Agendamento
    # ──────────────────────────────────────────────

    def set_schedule(self, backup_id: str, schedule: Dict[str, Any]) -> Dict[str, Any]:
        """Define ou atualiza o agendamento de um job de backup.

        Parâmetros esperados em ``schedule``:
        - time (str)           : horário no formato "HH:MM" (ex: "02:00")
        - repeat (str)         : intervalo no formato Duplicati (ex: "1D", "1W")
        - allowed_days (list)  : dias permitidos ["mon","tue","wed","thu","fri","sat","sun"]
        - tags (list)          : lista de tags opcionais
        """
        cfg = self.load_config()
        try:
            # Obter agendamento atual do backup para preservar campos não informados
            resp_get = self._api_get(cfg, f"api/v1/backup/{backup_id}")
            if resp_get.status_code != 200:
                return {"status": "error", "message": f"Backup {backup_id} não encontrado (HTTP {resp_get.status_code})"}
            current = resp_get.json()
            current_schedule = current.get("Schedule") or {}

            # Montar payload de agendamento
            time_str = schedule.get("time", current_schedule.get("Time", "02:00"))
            # Normalizar "HH:MM" para formato ISO com data fictícia esperada pelo Duplicati
            if len(time_str) == 5:  # "HH:MM"
                time_str = f"1970-01-01T{time_str}:00"

            new_schedule = {
                "ID": current_schedule.get("ID", 0),
                "Tags": schedule.get("tags", current_schedule.get("Tags", [f"ID={backup_id}"])),
                "Time": time_str,
                "Repeat": schedule.get("repeat", current_schedule.get("Repeat", "1D")),
                "LastRun": current_schedule.get("LastRun", "0001-01-01T00:00:00"),
                "Rule": schedule.get("rule", current_schedule.get("Rule", "")),
                "AllowedDays": schedule.get("allowed_days", current_schedule.get("AllowedDays", [])),
            }

            payload = {
                "Backup": current.get("Backup", {}),
                "Schedule": new_schedule,
            }

            resp = self._api_put(cfg, f"api/v1/backup/{backup_id}", payload)
            if resp.status_code == 200:
                return {"status": "success", "message": f"Agendamento do backup {backup_id} atualizado", "schedule": new_schedule}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ──────────────────────────────────────────────
    # Restauração
    # ──────────────────────────────────────────────

    def restore_backup(self, backup_id: str, restore_options: Dict[str, Any]) -> Dict[str, Any]:
        """Inicia uma restauração de arquivos de um backup.

        Parâmetros em ``restore_options``:
        - paths (list)          : caminhos a restaurar (vazio = tudo)
        - restore_path (str)    : destino da restauração
        - overwrite (bool)      : sobrescrever arquivos existentes (padrão False)
        - time (str)            : versão a restaurar, ex: "now" ou ISO datetime
        - passphrase (str)      : senha de decriptação (se necessário)
        """
        cfg = self.load_config()
        try:
            paths = restore_options.get("paths", [])
            restore_path = restore_options.get("restore_path", "")
            overwrite = restore_options.get("overwrite", False)
            time_ver = restore_options.get("time", "now")
            passphrase = restore_options.get("passphrase", "")

            if not restore_path:
                return {"status": "error", "message": "restore_path é obrigatório"}

            payload: Dict[str, Any] = {
                "paths": paths,
                "time": time_ver,
                "restore-path": restore_path,
                "overwrite": overwrite,
            }
            if passphrase:
                payload["passphrase"] = passphrase

            resp = self._api_post(cfg, f"api/v1/backup/{backup_id}/restore", payload)
            if resp.status_code == 200:
                data = resp.json() if resp.text else {}
                return {"status": "success", "message": f"Restauração do backup {backup_id} iniciada", "task": data}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ──────────────────────────────────────────────
    # Monitor de Resultado (para alertas automáticos)
    # ──────────────────────────────────────────────

    def get_last_result(self, backup_id: str) -> Dict[str, Any]:
        """Retorna o resultado (ParsedResult) da última execução do backup."""
        cfg = self.load_config()
        try:
            resp = self._api_get(cfg, f"api/v1/backup/{backup_id}/log?pagesize=1")
            if resp.status_code != 200:
                return {"status": "error", "message": f"HTTP {resp.status_code}"}
            entries = resp.json()
            if not entries:
                return {"status": "success", "result": None, "message": "Sem execuções registradas"}
            entry = entries[0]
            msg_raw = entry.get("Message", "")
            parsed_result = "Unknown"
            error_messages: List[str] = []
            try:
                import json as _json
                data = _json.loads(msg_raw)
                parsed_result = data.get("ParsedResult", "Unknown")
                error_messages = data.get("Errors", []) or []
            except Exception:
                pass
            return {
                "status": "success",
                "backup_id": backup_id,
                "parsed_result": parsed_result,
                "errors": error_messages,
                "timestamp": entry.get("Timestamp"),
                "raw_type": entry.get("Type"),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ──────────────────────────────────────────────
    # Gerenciamento Completo de Backups (Create, Delete, Repair, Verify, Compact)
    # ──────────────────────────────────────────────

    def create_backup(self, backup_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Cria ou atualiza uma configuração completa de backup no Duplicati."""
        cfg = self.load_config()
        try:
            name = backup_payload.get("name", "Novo Backup Duplicati")
            sources = backup_payload.get("sources", ["C:\\Backups"])
            target_url = backup_payload.get("target_url", "file://C:\\Backups")
            passphrase = backup_payload.get("passphrase", "")

            # Formatar payload padrão do Duplicati
            backup_obj = {
                "Name": name,
                "Description": backup_payload.get("description", "Criado via GBOC Interface"),
                "TargetURL": target_url,
                "Settings": [
                    {"Name": "encryption-module", "Value": "aes" if passphrase else "none"},
                    {"Name": "passphrase", "Value": passphrase} if passphrase else {}
                ],
                "Sources": sources
            }
            schedule_obj = {
                "Time": backup_payload.get("schedule_time", "1970-01-01T02:00:00"),
                "Repeat": backup_payload.get("schedule_repeat", "1D"),
                "AllowedDays": backup_payload.get("allowed_days", [])
            }

            payload = {"Backup": backup_obj, "Schedule": schedule_obj}
            resp = self._api_post(cfg, "api/v1/backups", json_body=payload)
            if resp.status_code in (200, 201):
                return {"status": "success", "message": f"Backup '{name}' criado com sucesso!", "data": resp.json() if resp.text else {}}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def delete_backup(self, backup_id: str, delete_remote_files: bool = False) -> Dict[str, Any]:
        """Exclui um job de backup do Duplicati."""
        cfg = self.load_config()
        try:
            url_path = f"api/v1/backup/{backup_id}?delete-remote-files={'true' if delete_remote_files else 'false'}"
            self._ensure_authenticated(cfg)
            headers = {"X-XSRF-Token": self._xsrf_token or ""}
            resp = self._session.delete(self._build_url(cfg, url_path), headers=headers, timeout=cfg.timeout_seconds, verify=cfg.verify_tls)
            if resp.status_code in (200, 204):
                return {"status": "success", "message": f"Backup {backup_id} excluído com sucesso."}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def repair_backup(self, backup_id: str) -> Dict[str, Any]:
        """Executa a reconstrução/reparo do banco local do backup."""
        cfg = self.load_config()
        try:
            resp = self._api_post(cfg, f"api/v1/backup/{backup_id}/repair")
            if resp.status_code == 200:
                return {"status": "success", "message": f"Reparo do banco de dados do backup {backup_id} iniciado."}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def verify_backup(self, backup_id: str) -> Dict[str, Any]:
        """Verifica a integridade e a conexão com o destino remoto."""
        cfg = self.load_config()
        try:
            resp = self._api_post(cfg, f"api/v1/backup/{backup_id}/verify")
            if resp.status_code == 200:
                return {"status": "success", "message": f"Verificação do destino do backup {backup_id} disparada com sucesso!"}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def compact_backup(self, backup_id: str) -> Dict[str, Any]:
        """Compacta e limpa blocos órfãos no destino do backup."""
        cfg = self.load_config()
        try:
            resp = self._api_post(cfg, f"api/v1/backup/{backup_id}/compact")
            if resp.status_code == 200:
                return {"status": "success", "message": f"Compactação do backup {backup_id} iniciada."}
            return {"status": "error", "message": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}


_service: Optional[DuplicatiNativeService] = None


def get_duplicati_native_service() -> DuplicatiNativeService:
    global _service
    if _service is None:
        _service = DuplicatiNativeService()
    return _service
