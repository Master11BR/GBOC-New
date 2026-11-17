# -*- coding: utf-8 -*-
"""
GBOC System v15.0.0 Enterprise — Python-to-Go Core Bridge (Server Mirror)
=========================================================================
Expõe a mesma interface `GoCoreBridge` / `go_bridge` no `GBOC-Server`
para telemetria concorrente, sincronização de assets e diagnóstico de arquitetura.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("gboc.server.go_bridge")

GO_CORE_VERSION = "15.0.0"


class GoCoreBridge:
    """Ponte de execução e fallback para o motor nativo `gboc-core` em Go."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        if workspace_root is None:
            here = Path(__file__).resolve()
            self.workspace_root = here.parent.parent
        else:
            self.workspace_root = Path(workspace_root).resolve()

        self.go_core_dir = self.workspace_root / "go-core"
        self.binary_path = self._discover_binary()

    def _discover_binary(self) -> Path | None:
        exe_name = "gboc-core.exe" if os.name == "nt" else "gboc-core"
        candidates = [
            self.go_core_dir / "bin" / exe_name,
            self.go_core_dir / exe_name,
            self.workspace_root / "bin" / exe_name,
            Path(__file__).resolve().parent / exe_name,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate

        which_bin = shutil.which(exe_name)
        if which_bin:
            return Path(which_bin)
        return None

    def is_native_binary_available(self) -> bool:
        return self.binary_path is not None and self.binary_path.is_file()

    def has_go_source(self) -> bool:
        return (self.go_core_dir / "cmd" / "gboc-core" / "main.go").is_file()

    def get_architecture_info(self) -> dict[str, Any]:
        return {
            "engine": "gboc-go-core",
            "version": GO_CORE_VERSION,
            "native_binary_compiled": self.is_native_binary_available(),
            "binary_path": str(self.binary_path) if self.binary_path else None,
            "go_source_present": self.has_go_source(),
            "go_module": "github.com/master11br/gboc-go-core",
            "capabilities": [
                "chunker.sha256_worker_pool",
                "chunker.verify_local_repo",
                "telemetry.watchdog_probe",
                "telemetry.hermes_udp_mesh",
                "syncer.universal_css_sync",
            ],
            "os": platform.system().lower(),
            "arch": platform.machine().lower(),
        }

    def _invoke_binary(self, args: list[str], timeout: float = 60.0) -> dict[str, Any] | None:
        if not self.is_native_binary_available() or self.binary_path is None:
            return None
        try:
            proc = subprocess.run(
                [str(self.binary_path), *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return json.loads(proc.stdout.strip())
        except Exception as exc:
            logger.debug("Falha ao invocar binário gboc-core (%s): %s", args, exc)
        return None


go_bridge = GoCoreBridge()

