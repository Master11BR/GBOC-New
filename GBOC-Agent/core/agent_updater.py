"""
GBOC Agent — Atualização remota do próprio agente (pacote publicado pelo GBOC Server).

Fluxo: o Server pede a atualização → o agente baixa o pacote do Server (rota de sincronização,
autenticada pela chave de pareamento; funciona com o agente atrás de NAT) → confere o SHA-256 →
valida o ZIP (caminhos seguros e sintaxe de todos os .py) → guarda cópia dos arquivos que serão
substituídos → grava os novos → reinicia o serviço (o NSSM reinicia o processo automaticamente).

Dados locais nunca são tocados: config/, data/, logs/, repositorios/, tools/, updates/ e ambientes Python.
Se algo der errado é possível voltar à cópia anterior (rollback).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gboc_agent_updater")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPDATES_DIR = os.path.join(AGENT_DIR, "updates")
STATE_FILE = os.path.join(UPDATES_DIR, "last_update.json")
PROTECTED_TOP = {"config", "data", "logs", "repositorios", "tools", "updates", "venv", ".venv", "python", "env",
                 "__pycache__", ".git", "backups"}
PROTECTED_EXT = {".db", ".sqlite", ".sqlite3", ".log", ".pyc", ".pyo", ".key", ".pem", ".env"}
MAX_PACKAGE_BYTES = 400 * 1024 * 1024
_lock = threading.Lock()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def current_version() -> str:
    try:
        from version import GBOC_VERSION
        return GBOC_VERSION
    except Exception:
        return "?"


def running_as_service() -> bool:
    """True quando o processo é filho do NSSM (serviço 'GBOC Backup Agent')."""
    try:
        import psutil
        p = psutil.Process(os.getpid()).parent()
        for _ in range(3):
            if p is None:
                break
            if "nssm" in (p.name() or "").lower():
                return True
            p = p.parent()
    except Exception:
        pass
    return os.environ.get("GBOC_AGENT_SERVICE") == "1"


def _members(zf: zipfile.ZipFile) -> List[tuple]:
    """(nome no zip, caminho relativo no agente) — remove a pasta raiz comum (GBOC-Agent/ ou Agent/)."""
    names = [n for n in zf.namelist() if not n.endswith("/")]
    if not names:
        raise ValueError("Pacote vazio")
    prefix = ""
    if "agent_gboc.py" not in names:
        tops = {n.split("/", 1)[0] for n in names if "/" in n}
        for t in tops:
            if f"{t}/agent_gboc.py" in names:
                prefix = t + "/"
                break
        if not prefix:
            raise ValueError("Pacote não é do GBOC Agent (agent_gboc.py não encontrado)")
    out = []
    for n in names:
        if prefix and not n.startswith(prefix):
            continue
        rel = n[len(prefix):].replace("\\", "/")
        parts = [p for p in rel.split("/") if p]
        if not parts or any(p == ".." for p in parts) or rel.startswith("/") or ":" in parts[0]:
            raise ValueError(f"Caminho inseguro no pacote: {n}")
        if parts[0].lower() in PROTECTED_TOP or parts[0].startswith(".") or "__pycache__" in parts:
            continue
        if os.path.splitext(parts[-1])[1].lower() in PROTECTED_EXT:
            continue
        out.append((n, os.path.join(*parts)))
    return out


def inspect_package(path: str) -> Dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        members = _members(zf)
        version = None
        errors = []
        for name, rel in members:
            if rel.endswith(".py"):
                src = zf.read(name)
                try:
                    compile(src, rel, "exec")
                except SyntaxError as e:
                    errors.append(f"{rel}: linha {e.lineno}: {e.msg}")
                if rel == "version.py":
                    for line in src.decode("utf-8", "replace").splitlines():
                        if line.strip().startswith("GBOC_VERSION"):
                            version = line.split("=", 1)[1].strip().strip("\"'")
    if errors:
        raise ValueError("Pacote com erros de sintaxe: " + "; ".join(errors[:5]))
    return {"files": len(members), "version": version}


def apply_package(path: str, expected_sha256: str, restart: bool = True) -> Dict[str, Any]:
    if not _lock.acquire(blocking=False):
        raise RuntimeError("Já existe uma atualização em andamento")
    try:
        digest = _sha256_file(path)
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            raise ValueError("SHA-256 do pacote não confere — download corrompido ou adulterado")
        info = inspect_package(path)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = os.path.join(UPDATES_DIR, f"backup_{current_version()}_{stamp}")
        os.makedirs(backup, exist_ok=True)
        written = 0
        with zipfile.ZipFile(path) as zf:
            members = _members(zf)
            for _name, rel in members:                         # 1) cópia de segurança dos atuais
                cur = os.path.join(AGENT_DIR, rel)
                if os.path.isfile(cur):
                    dst = os.path.join(backup, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(cur, dst)
            for name, rel in members:                          # 2) grava os novos (arquivo temporário + troca)
                dst = os.path.join(AGENT_DIR, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                tmp = dst + ".gboc_new"
                with zf.open(name) as src, open(tmp, "wb") as out:
                    shutil.copyfileobj(src, out)
                os.replace(tmp, dst)
                written += 1
        state = {"from_version": current_version(), "to_version": info.get("version"), "sha256": digest,
                 "applied_at": datetime.now().isoformat(sep=" ", timespec="seconds"), "files": written, "backup": backup,
                 "status": "applied"}
        os.makedirs(UPDATES_DIR, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        service = running_as_service()
        state["restart"] = "automático (serviço)" if (service and restart) else "manual — reinicie o serviço do agente"
        if service and restart:
            schedule_restart()
        logger.warning(f"[UPDATE] Agente atualizado {state['from_version']} → {state['to_version']} ({written} arquivos)")
        return state
    finally:
        _lock.release()


def schedule_restart(delay: float = 4.0) -> None:
    """Encerra o processo após a resposta ser enviada; o NSSM sobe o agente com o código novo."""
    def _bye():
        time.sleep(delay)
        logger.warning("[UPDATE] Reiniciando o agente para carregar a nova versão...")
        os._exit(0)
    threading.Thread(target=_bye, name="gboc-update-restart", daemon=True).start()


def download_and_apply(sha256: str, restart: bool = True) -> Dict[str, Any]:
    from core.server_client import central_client
    if not central_client.server_url:
        raise RuntimeError("Agente não está configurado com um GBOC Server")
    os.makedirs(UPDATES_DIR, exist_ok=True)
    dst = os.path.join(UPDATES_DIR, f"package_{sha256[:16]}.zip")
    url = f"{central_client.server_url.rstrip('/')}/api/v1/sync/agent-update/package"
    with central_client._session.get(url, params={"sha256": sha256}, stream=True, timeout=(15, 600)) as r:
        if r.status_code != 200:
            raise RuntimeError(f"Server recusou o download do pacote (HTTP {r.status_code})")
        total = 0
        with open(dst, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                total += len(chunk)
                if total > MAX_PACKAGE_BYTES:
                    raise RuntimeError("Pacote maior que o limite permitido")
                f.write(chunk)
    try:
        return apply_package(dst, sha256, restart=restart)
    finally:
        try:
            os.remove(dst)
        except OSError:
            pass


def list_backups() -> List[Dict[str, Any]]:
    if not os.path.isdir(UPDATES_DIR):
        return []
    out = []
    for d in sorted(os.listdir(UPDATES_DIR), reverse=True):
        full = os.path.join(UPDATES_DIR, d)
        if d.startswith("backup_") and os.path.isdir(full):
            out.append({"name": d, "created_at": datetime.fromtimestamp(os.path.getmtime(full)).isoformat(sep=" ", timespec="seconds")})
    return out


def rollback(name: Optional[str] = None, restart: bool = True) -> Dict[str, Any]:
    backups = list_backups()
    if not backups:
        raise RuntimeError("Nenhuma cópia anterior disponível")
    chosen = name or backups[0]["name"]
    src = os.path.join(UPDATES_DIR, os.path.basename(chosen))
    if not os.path.isdir(src):
        raise ValueError("Cópia não encontrada")
    restored = 0
    for root, _dirs, files in os.walk(src):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, src)
            dst = os.path.join(AGENT_DIR, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(full, dst)
            restored += 1
    state = {"status": "rolled_back", "backup": chosen, "files": restored,
             "applied_at": datetime.now().isoformat(sep=" ", timespec="seconds")}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    if restart and running_as_service():
        schedule_restart()
        state["restart"] = "automático (serviço)"
    else:
        state["restart"] = "manual — reinicie o serviço do agente"
    return state


def status() -> Dict[str, Any]:
    last = None
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            last = json.load(f)
    except Exception:
        pass
    return {"version": current_version(), "running_as_service": running_as_service(), "last_update": last,
            "backups": list_backups()[:10]}
