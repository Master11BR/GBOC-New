#!/usr/bin/env python3
"""
GBOC Agent - Capacidades do ambiente para os recursos de IA

Cada recurso tem uma chave de ativação (config/global_settings.json → ai_llm_config) e um estado REAL,
verificado no host do Agente:
  • active       – ativado e funcionando completo
  • partial      – ativado, mas só parte funciona neste ambiente (o que funciona fica ligado; o resto é informado)
  • unavailable  – ativado, mas o ambiente não permite (motivo e o que fazer são informados)
  • disabled     – desligado pelo administrador

Recursos:
  rag            – base de conhecimento local (palavras-chave sempre; semântica depende de embedding)
  diagnosis      – diagnóstico/Copilot com LLM (sem LLM: heurística + soluções validadas do RAG)
  auto_diagnose  – diagnóstico automático das falhas de tarefas
  mcp            – servidor MCP
  finetune       – dataset (sempre) · importação no Ollama · treino local (GPU NVIDIA + CUDA + Unsloth)
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("GBOC.AICapabilities")

MIN_VRAM_GB_TRAIN = 8.0
MIN_FREE_DISK_GB_TRAIN = 20.0
MIN_RAM_GB_LOCAL_LLM = 8.0
_CACHE_TTL = 90.0
_cache: dict[str, Any] = {"ts": 0.0, "data": None}
_lock = threading.Lock()
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _agent_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _cfg() -> dict[str, Any]:
    try:
        from engines.ai_diagnostic_engine import ai_diagnostic_engine
        return dict(ai_diagnostic_engine.config)
    except Exception:
        return {}


def _flag(cfg: dict[str, Any], key: str, default: bool) -> bool:
    v = cfg.get(key, default)
    return v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "sim", "on", "yes")


# ──────────────────────────────────────────────────────────────────────────────
# Detecção de hardware / software (somente leitura, sem instalar nada)
# ──────────────────────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW)
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", "não encontrado"
    except subprocess.TimeoutExpired:
        return 124, "", f"tempo limite ({timeout}s)"
    except Exception as e:
        return 1, "", str(e)


def detect_nvidia_gpus() -> dict[str, Any]:
    exe = shutil.which("nvidia-smi")
    if not exe and os.name == "nt":
        cand = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"
        exe = str(cand) if cand.is_file() else None
        if not exe:
            sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
            exe = str(sys32) if sys32.is_file() else None
    if not exe:
        return {"available": False, "gpus": [], "reason": "Driver NVIDIA (nvidia-smi) não encontrado."}
    rc, out, err = _run([exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"])
    if rc != 0:
        return {"available": False, "gpus": [], "reason": f"nvidia-smi falhou: {(err or out).strip()[:200]}"}
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            try:
                vram = round(float(parts[1]) / 1024, 1)
            except ValueError:
                vram = None
            gpus.append({"name": parts[0], "vram_gb": vram, "driver": parts[2]})
    return {"available": bool(gpus), "gpus": gpus, "reason": "" if gpus else "Nenhuma GPU NVIDIA listada pelo driver."}


def detect_other_gpus() -> list[str]:
    """Placas de vídeo não NVIDIA (para explicar por que o treino não é possível)."""
    names: list[str] = []
    if os.name == "nt":
        ps = shutil.which("powershell.exe") or shutil.which("powershell")
        if ps:
            rc, out, _ = _run([ps, "-NoProfile", "-NonInteractive", "-Command",
                               "(Get-CimInstance Win32_VideoController).Name | ConvertTo-Json -Compress"], 20)
            if rc == 0 and out.strip():
                try:
                    data = json.loads(out)
                    names = [data] if isinstance(data, str) else [str(x) for x in data or []]
                except ValueError:
                    pass
    else:
        rc, out, _ = _run(["lspci"], 10)
        if rc == 0:
            names = [ln.split(":", 2)[-1].strip() for ln in out.splitlines() if "VGA" in ln or "3D controller" in ln]
    return [n for n in names if n and "nvidia" not in n.lower()]


def detect_training_stack() -> dict[str, Any]:
    """Verifica no Python do Agente (em processo separado) torch+CUDA e Unsloth/TRL — sem carregar nada no Agente."""
    probe = (
        "import json,importlib.util as u;r={'torch':bool(u.find_spec('torch')),'unsloth':bool(u.find_spec('unsloth')),"
        "'trl':bool(u.find_spec('trl')),'datasets':bool(u.find_spec('datasets')),'cuda':False,'cuda_version':None}\n"
        "if r['torch']:\n"
        " import torch;r['cuda']=bool(torch.cuda.is_available());r['cuda_version']=getattr(torch.version,'cuda',None)\n"
        "print(json.dumps(r))"
    )
    rc, out, err = _run([sys.executable, "-c", probe], timeout=90)
    try:
        data = json.loads(out.strip().splitlines()[-1]) if rc == 0 and out.strip() else {}
    except (ValueError, IndexError):
        data = {}
    if not data:
        data = {"torch": False, "unsloth": False, "trl": False, "datasets": False, "cuda": False,
                "error": (err or out).strip()[:300] or "Verificação do Python falhou."}
    data["python"] = sys.executable
    data["python_version"] = platform.python_version()
    return data


def detect_ollama(cfg: dict[str, Any]) -> dict[str, Any]:
    try:
        from engines import ai_providers as aip
        import httpx
        info = aip.list_ollama_models(cfg, timeout=4.0)
        if not info.get("connected"):
            return {"connected": False, "reason": info.get("error") or "Ollama não respondeu."}
        version = ""
        try:
            r = httpx.get(f"{info['host']}/api/version", timeout=4.0, **aip._http_opts(info["host"]))
            version = (r.json() or {}).get("version", "") if r.status_code == 200 else ""
        except Exception:
            pass
        models = info.get("models") or []
        hints = ("embed", "bge", "minilm", "e5-", "gte-", "arctic-embed", "paraphrase")
        return {"connected": True, "host": info["host"], "version": version, "models": models,
                "embedding_models": [m for m in models if any(h in m.lower() for h in hints)],
                "chat_models": [m for m in models if not any(h in m.lower() for h in hints)]}
    except Exception as e:
        return {"connected": False, "reason": f"{e.__class__.__name__}: {e}"}


def _version_tuple(v: str) -> tuple[int, ...]:
    out = []
    for p in (v or "0").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def detect_host() -> dict[str, Any]:
    info: dict[str, Any] = {"os": f"{platform.system()} {platform.release()}", "cpu_cores": os.cpu_count()}
    try:
        import psutil
        info["ram_gb"] = round(psutil.virtual_memory().total / 1024 ** 3, 1)
        du = psutil.disk_usage(str(_agent_root()))
        info["disk_free_gb"] = round(du.free / 1024 ** 3, 1)
    except Exception as e:
        info["error"] = str(e)
    return info


# ──────────────────────────────────────────────────────────────────────────────
# Avaliação por recurso
# ──────────────────────────────────────────────────────────────────────────────

def _feature(key: str, label: str, requested: bool, state: str, message: str,
             works: list[str] | None = None, missing: list[str] | None = None, impossible: bool = False) -> dict[str, Any]:
    if not requested:
        state = "disabled"
    return {"key": key, "label": label, "requested": requested, "state": state, "message": message,
            "works": works or [], "missing": missing or [], "impossible": impossible}


def evaluate(force: bool = False) -> dict[str, Any]:
    with _lock:
        if not force and _cache["data"] and time.time() - _cache["ts"] < _CACHE_TTL:
            return _cache["data"]
    cfg = _cfg()
    host = detect_host()
    ollama = detect_ollama(cfg)
    gpu = detect_nvidia_gpus()
    features = []

    # ── RAG ──
    from engines import ai_rag
    rag_req = _flag(cfg, "rag_enabled", True)
    db_ok, db_err = True, ""
    try:
        ai_rag.get_conn().execute("SELECT 1")
    except Exception as e:
        db_ok, db_err = False, str(e)
    emb = ai_rag.embedding_settings(cfg)
    if not db_ok:
        features.append(_feature("rag", "Base de conhecimento (RAG)", rag_req, "unavailable",
                                 f"Não foi possível abrir o índice local ({db_err}). Verifique permissão de escrita na pasta data\\ai do Agente.",
                                 missing=["Escrita em data\\ai"]))
    elif emb.get("provider") != "none":
        features.append(_feature("rag", "Base de conhecimento (RAG)", rag_req, "active",
                                 f"Busca por palavras-chave + busca semântica ({emb['provider']} · {emb['model']}).",
                                 works=["Palavras-chave", "Semântica"]))
    else:
        features.append(_feature("rag", "Base de conhecimento (RAG)", rag_req, "partial",
                                 "Busca por palavras-chave ativa. Busca semântica indisponível: " + (emb.get("reason") or ""),
                                 works=["Palavras-chave"], missing=["Modelo de embedding (ex.: ollama pull nomic-embed-text)"]))

    # ── Diagnóstico / Copilot ──
    from engines import ai_providers as aip
    provider = aip.normalize_provider(cfg.get("provider"))
    llm_ok, llm_msg = False, ""
    if provider == "ollama":
        if ollama.get("connected") and ollama.get("chat_models"):
            llm_ok = True
            llm_msg = f"Ollama em {ollama['host']} com {len(ollama['chat_models'])} modelo(s)."
            if (host.get("ram_gb") or 0) < MIN_RAM_GB_LOCAL_LLM and not gpu["available"]:
                llm_msg += f" Atenção: {host.get('ram_gb')} GB de RAM e sem GPU — respostas locais podem ser lentas."
        elif ollama.get("connected"):
            llm_msg = "Ollama ativo, mas sem modelo de conversa instalado (ex.: ollama pull qwen2.5:3b)."
        else:
            llm_msg = f"Ollama inacessível: {ollama.get('reason')}"
    else:
        llm_ok = bool(aip.resolve_api_key(cfg, provider))
        llm_msg = f"{aip.provider_label(provider)} configurado." if llm_ok else f"Chave de API de {aip.provider_label(provider)} não configurada."
    features.append(_feature(
        "diagnosis", "Diagnóstico e Copilot com IA", True, "active" if llm_ok else "partial",
        llm_msg if llm_ok else llm_msg + " Funcionando com heurística + soluções já validadas da base local.",
        works=["LLM", "Heurística", "RAG"] if llm_ok else ["Heurística", "RAG"],
        missing=[] if llm_ok else ["Provedor de IA acessível"]))

    # ── Diagnóstico automático ──
    ad_req = _flag(cfg, "auto_diagnose_errors", True)
    features.append(_feature("auto_diagnose", "Diagnóstico automático de falhas", ad_req, "active" if llm_ok else "partial",
                             "Cada falha nova de tarefa vira um caso diagnosticado." +
                             ("" if llm_ok else " Sem LLM acessível, os casos usam a heurística local."),
                             works=["Casos automáticos"]))

    # ── MCP ──
    mcp_req = _flag(cfg, "mcp_enabled", True)
    try:
        from engines import mcp_server
        active_tokens = sum(1 for t in mcp_server.list_tokens() if not t["revoked"])
        features.append(_feature("mcp", "Servidor MCP", mcp_req, "active" if active_tokens else "partial",
                                 f"Endpoint /api/mcp ativo com {active_tokens} token(s)." if active_tokens
                                 else "Endpoint /api/mcp ativo. Gere um token para conectar um cliente de IA.",
                                 works=["Endpoint"], missing=[] if active_tokens else ["Token de cliente"]))
    except Exception as e:
        features.append(_feature("mcp", "Servidor MCP", mcp_req, "unavailable", f"Falha ao carregar o servidor MCP: {e}"))

    # ── Fine-tuning ──
    ft_local_req = _flag(cfg, "finetune_local_enabled", False)
    works = ["Gerar dataset"]
    missing: list[str] = []
    train_info: dict[str, Any] = {"gpu": gpu}
    ollama_import_ok = bool(ollama.get("connected")) and _version_tuple(ollama.get("version", "0")) >= (0, 5, 0)
    if ollama_import_ok:
        works.append("Importar no Ollama")
    else:
        missing.append("Ollama 0.5+ acessível para importar o modelo" if ollama.get("connected")
                       else "Ollama acessível para importar o modelo")

    impossible_train = False
    local_ok = False
    if ft_local_req:
        stack = detect_training_stack()
        train_info["stack"] = stack
        best_vram = max([g.get("vram_gb") or 0 for g in gpu.get("gpus", [])] or [0])
        if not gpu["available"]:
            others = detect_other_gpus()
            train_info["other_gpus"] = others
            impossible_train = True
            missing.append("GPU NVIDIA com CUDA" + (f" (placa(s) encontrada(s): {', '.join(others)} — não suportada(s) pelo treino)" if others else ""))
        elif best_vram < MIN_VRAM_GB_TRAIN:
            impossible_train = True
            missing.append(f"GPU com {MIN_VRAM_GB_TRAIN:.0f} GB+ de VRAM (maior encontrada: {best_vram} GB)")
        else:
            if not stack.get("torch") or not stack.get("cuda"):
                missing.append("PyTorch com CUDA no Python do Agente")
            for pkg in ("unsloth", "trl", "datasets"):
                if not stack.get(pkg):
                    missing.append(f"Pacote Python '{pkg}'")
            if (host.get("disk_free_gb") or 0) < MIN_FREE_DISK_GB_TRAIN:
                missing.append(f"{MIN_FREE_DISK_GB_TRAIN:.0f} GB livres em disco (livre: {host.get('disk_free_gb')} GB)")
            local_ok = not any(m.startswith(("PyTorch", "Pacote", f"{MIN_FREE_DISK_GB_TRAIN:.0f} GB")) for m in missing)
        if local_ok:
            works.append("Treino local na GPU")

    if not ft_local_req:
        msg = ("Dataset" + (" e importação no Ollama" if ollama_import_ok else "") +
               " disponíveis. Treino local desligado: treine numa máquina com GPU (scripts\\finetune) ou ative o treino local.")
        state = "active" if ollama_import_ok else "partial"
    elif local_ok:
        state, msg = ("active" if ollama_import_ok else "partial"), "Treino local disponível nesta máquina (GPU NVIDIA detectada)."
    elif impossible_train:
        state = "partial"
        msg = ("Treino local IMPOSSÍVEL neste servidor: sem GPU NVIDIA adequada. Continua disponível: gerar dataset"
               + (" e importar no Ollama" if ollama_import_ok else "") + "; treine em outra máquina com GPU.")
    else:
        state = "partial"
        msg = "GPU adequada encontrada, mas faltam componentes para o treino local (veja abaixo). O restante segue ativo."
    features.append(_feature("finetune", "Fine-tuning do diagnóstico", True, state, msg, works=works, missing=missing,
                             impossible=impossible_train))

    data = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "host": host, "ollama": ollama, "training": train_info,
            "features": features, "local_training_available": local_ok}
    with _lock:
        _cache.update(ts=time.time(), data=data)
    return data


def feature_state(key: str) -> dict[str, Any] | None:
    return next((f for f in evaluate()["features"] if f["key"] == key), None)
