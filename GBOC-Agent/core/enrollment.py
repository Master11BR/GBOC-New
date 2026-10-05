"""
GBOC Agent — Inscrição automática no GBOC Server (instalação em massa).

O instalador (ou GPO/Intune) informa a URL do Server e um TOKEN DE INSTALAÇÃO gerado no Server.
O agente troca o token pela chave de pareamento e pelo cliente (tenant) definidos no Server, grava a
configuração central e passa a se comunicar sozinho — sem digitar a chave em cada máquina.

Formas de uso:
  * linha de comando (usada pelo script de instalação):
      python -m core.enrollment --server https://gboc.empresa.com.br:8000 --token gbi_xxx
  * arquivo de semente: C:\\ProgramData\\GBOC\\enroll.json  {"server_url": "...", "install_token": "..."}
    processado na inicialização do serviço (o token é removido do arquivo depois do uso).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import socket
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("gboc_enrollment")


def config_dir() -> Path:
    d = Path("C:/ProgramData/GBOC") if os.name == "nt" else Path.home() / ".gboc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def agent_id() -> str:
    """Mesmo identificador usado pelo cliente do servidor central (arquivo agent_id)."""
    f = config_dir() / "agent_id"
    if f.exists():
        v = f.read_text().strip()
        if v:
            return v
    v = str(uuid.uuid4())
    f.write_text(v)
    return v


def request_enrollment(server_url: str, token: str, timeout: int = 30) -> Dict[str, Any]:
    import requests
    url = server_url.rstrip("/") + "/api/v1/enroll"
    payload = {"token": token, "agent_id": agent_id(), "hostname": socket.gethostname(),
               "os_info": f"{platform.system()} {platform.release()}"}
    r = requests.post(url, json=payload, timeout=timeout, verify=False)
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code != 200:
        raise RuntimeError(data.get("detail") or data.get("message") or f"Server respondeu HTTP {r.status_code}")
    if not data.get("pairing_key"):
        raise RuntimeError("Resposta do Server sem chave de pareamento")
    return data


def save_config(server_url: str, pairing_key: str, tenant_id: Optional[str]) -> None:
    from core.server_config import config_manager
    config_manager.update({"server_url": server_url.rstrip("/"), "api_key": pairing_key, "tenant_id": tenant_id,
                           "enabled": True, "configured_at": datetime.now().isoformat(), "enrolled": True})


def enroll(server_url: str, token: str, apply_live: bool = False) -> Dict[str, Any]:
    if not server_url.startswith(("http://", "https://")):
        raise ValueError("A URL do Server deve começar com http:// ou https://")
    data = request_enrollment(server_url, token)
    url = (data.get("server_url") or server_url).rstrip("/")
    save_config(url, data["pairing_key"], data.get("tenant_id"))
    if apply_live:                          # serviço já rodando: aplica sem reiniciar
        try:
            from core.server_client import central_client
            central_client.configure_server(url, data["pairing_key"], data.get("tenant_id"))
        except Exception as e:
            logger.warning(f"[INSCRIÇÃO] Configuração salva; aplicação imediata falhou ({e}) — vale no próximo início")
    logger.info(f"[INSCRIÇÃO] Agente {agent_id()} inscrito em {url} (cliente: {data.get('tenant_name') or data.get('tenant_id') or '—'})")
    return {"server_url": url, "tenant_id": data.get("tenant_id"), "tenant_name": data.get("tenant_name"), "agent_id": agent_id()}


def process_seed_file() -> Optional[Dict[str, Any]]:
    """Processa C:\\ProgramData\\GBOC\\enroll.json (GPO/Intune). Retorna o resultado ou None."""
    f = config_dir() / "enroll.json"
    if not f.exists():
        return None
    try:
        seed = json.loads(f.read_text(encoding="utf-8-sig"))
    except Exception as e:
        logger.warning(f"[INSCRIÇÃO] enroll.json inválido: {e}")
        return None
    if not seed.get("server_url") or not seed.get("install_token"):
        return None
    try:
        res = enroll(seed["server_url"], seed["install_token"], apply_live=True)
        seed.pop("install_token", None)
        seed.update(enrolled_at=datetime.now().isoformat(), result=res)
        f.with_name("enroll.done.json").write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
        f.unlink()
        return res
    except Exception as e:
        seed["last_error"] = str(e)[:300]
        seed["last_attempt"] = datetime.now().isoformat()
        try:
            f.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        logger.warning(f"[INSCRIÇÃO] Falha ao inscrever no Server: {e}")
        return None


def seed_loop(interval: int = 300, max_hours: int = 72) -> None:
    """Processa o enroll.json e, se o Server estiver inacessível, tenta novamente a cada 5 minutos."""
    import time
    deadline = time.time() + max_hours * 3600
    while time.time() < deadline:
        if not (config_dir() / "enroll.json").exists():
            return
        if process_seed_file():
            return
        time.sleep(interval)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Inscreve este GBOC Agent no GBOC Server com um token de instalação")
    p.add_argument("--server", required=True, help="URL do GBOC Server, ex.: https://gboc.empresa.com.br:8000")
    p.add_argument("--token", required=True, help="Token de instalação gerado no Server")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:
        pass
    try:
        res = enroll(a.server, a.token)
        print(json.dumps({"status": "success", **res}, ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
