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
            # ── Fluxo v2.3+: JWT via /api/v1/auth/login ──────────────────────
            login_url_jwt = cfg.base_url + "/api/v1/auth/login"
            resp_jwt = self._session.post(
                login_url_jwt,
                json={"Password": cfg.password},
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

            # ── Fluxo legado: sessão/XSRF via /login.cgi ──────────────────────
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

            if not cfg.password:
                self._authenticated = True
                return True

            login_url = cfg.base_url + "/login.cgi"
            payload = {"Password": cfg.password}
            resp = self._session.post(
                login_url,
                data=payload,
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
                logger.info("✅ Autenticado no Duplicati via sessão/XSRF (legado)")
                return True

            logger.warning(f"Falha no login Duplicati: HTTP {resp.status_code}")
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
        probe_paths = [
            "api/v1/serverstate",
            "api/v1/systeminfo",
            "api/v1/backups",
            "api/v1/backup",
        ]
        results = []
        ok = False
        for path in probe_paths:
            try:
                resp = self._api_get(cfg, path)
                status = resp.status_code
                results.append({"url": self._build_url(cfg, path), "status": status})
                if status == 200:
                    ok = True
            except Exception as e:
                results.append({"url": self._build_url(cfg, path), "status": "error", "error": str(e)})
        install = self.detect_local_installation()
        return {
            "ok": ok,
            "base_url": cfg.base_url,
            "authenticated": self._authenticated,
            "installation": install,
            "probes": results,
            "discovered": self.discover_endpoints(),
        }

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
                    return {"status": "success", "items": [], "source": self._build_url(cfg, path)}
                last_error = f"HTTP {resp.status_code} em {self._build_url(cfg, path)}"
            except Exception as e:
                last_error = str(e)
        return {
            "status": "error",
            "message": "Não foi possível listar backups no Duplicati",
            "error": last_error,
            "items": [],
        }

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


_service: Optional[DuplicatiNativeService] = None


def get_duplicati_native_service() -> DuplicatiNativeService:
    global _service
    if _service is None:
        _service = DuplicatiNativeService()
    return _service
