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

        return next_cfg

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
            url = self._build_url(cfg, path)
            try:
                resp = self._session.get(
                    url,
                    timeout=cfg.timeout_seconds,
                    verify=cfg.verify_tls,
                    auth=(cfg.username, cfg.password) if cfg.username else None,
                )
                status = resp.status_code
                results.append({"url": url, "status": status})
                if status in (200, 401, 403):
                    ok = True
            except Exception as e:
                results.append({"url": url, "status": "error", "error": str(e)})

        install = self.detect_local_installation()

        return {
            "ok": ok,
            "base_url": cfg.base_url,
            "installation": install,
            "probes": results,
            "discovered": self.discover_endpoints(),
        }

    def list_backups(self) -> Dict[str, Any]:
        cfg = self.load_config()
        paths = ["api/v1/backups", "api/v1/backup"]

        last_error: Optional[str] = None
        for path in paths:
            url = self._build_url(cfg, path)
            try:
                resp = self._session.get(
                    url,
                    timeout=cfg.timeout_seconds,
                    verify=cfg.verify_tls,
                    auth=(cfg.username, cfg.password) if cfg.username else None,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict):
                        for key in ("Backups", "backups", "Items", "items"):
                            if key in data and isinstance(data[key], list):
                                return {"status": "success", "items": data[key], "source": url}
                        return {"status": "success", "items": [data], "source": url}
                    if isinstance(data, list):
                        return {"status": "success", "items": data, "source": url}
                    return {"status": "success", "items": [], "source": url}

                last_error = f"HTTP {resp.status_code} em {url}"
            except Exception as e:
                last_error = str(e)

        return {
            "status": "error",
            "message": "Não foi possível listar backups no Duplicati",
            "error": last_error,
            "items": [],
        }


_service: Optional[DuplicatiNativeService] = None


def get_duplicati_native_service() -> DuplicatiNativeService:
    global _service
    if _service is None:
        _service = DuplicatiNativeService()
    return _service
