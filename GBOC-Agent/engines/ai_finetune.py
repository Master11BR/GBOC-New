#!/usr/bin/env python3
"""
GBOC Agent - Fine-tuning do modelo de diagnóstico

Fluxo (sem dados simulados):
  1. Dataset: gerado somente a partir de casos REAIS do Agente (engines/ai_cases.py):
       • "verified"            → casos que o operador marcou como "resolveu" (padrão, maior qualidade)
       • "verified_recovered"  → + casos sem avaliação cuja tarefa voltou a concluir com sucesso depois do diagnóstico
     Formato: JSONL de conversas (system/user/assistant), compatível com Unsloth, Axolotl, TRL, OpenAI e Ollama.
  2. Treino: fora do Agente, numa máquina com GPU (scripts/finetune/train_lora_gboc.py — LoRA com Unsloth),
     que gera um .gguf (modelo completo) ou um adapter LoRA .gguf.
  3. Importação: o Agente envia o arquivo para o Ollama (API /api/blobs + /api/create) e, opcionalmente,
     passa a usar o modelo treinado no diagnóstico.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("GBOC.AIFinetune")

MIN_RECOMMENDED_EXAMPLES = 30
_import_state: dict[str, Any] = {"running": False, "phase": "", "last_result": None, "last_error": None}
_import_lock = threading.Lock()


def finetune_dir() -> Path:
    try:
        from core.gboc_paths import data_dir
        return data_dir("ai", "finetune")
    except Exception:
        p = Path(__file__).resolve().parent.parent / "data" / "ai" / "finetune"
        p.mkdir(parents=True, exist_ok=True)
        return p


def _system_prompt() -> str:
    from engines.ai_diagnostic_engine import DIAGNOSTIC_SYSTEM_PROMPT
    return DIAGNOSTIC_SYSTEM_PROMPT


def _eligible_cases(mode: str) -> list[dict[str, Any]]:
    from engines import ai_cases
    out = []
    for c in ai_cases.list_cases(limit=100000):
        if not (c.get("solution") or c.get("cause")):
            continue
        fb = c.get("feedback") or ""
        if fb == "resolved":
            c["_evidence"] = "validado pelo operador"
            out.append(c)
        elif mode == "verified_recovered" and fb == "":
            if ai_cases.task_recovered_after(c):
                c["_evidence"] = "tarefa voltou a concluir após o diagnóstico"
                out.append(c)
    return out


def summary() -> dict[str, Any]:
    from engines import ai_cases
    verified = _eligible_cases("verified")
    with_recovered = _eligible_cases("verified_recovered")
    actions: dict[str, int] = {}
    for c in verified:
        actions[c.get("recommended_action") or "none"] = actions.get(c.get("recommended_action") or "none", 0) + 1
    return {
        "cases": ai_cases.counts(),
        "eligible_verified": len(verified),
        "eligible_verified_recovered": len(with_recovered),
        "min_recommended": MIN_RECOMMENDED_EXAMPLES,
        "actions": actions,
        "datasets": list_datasets(),
        "import": dict(_import_state),
        "train": train_state(),
    }


def _example(case: dict[str, Any], system: str) -> dict[str, Any]:
    user = f"ERRO REGISTRADO:\n{case['error_text']}"
    if case.get("engine"):
        user += f"\n\nMOTOR: {case['engine']}"
    analysis = case.get("analysis") or ""
    if case.get("operator_note"):
        analysis = (analysis + f"\n\nObservação do operador: {case['operator_note']}").strip()
    answer = {
        "cause": case.get("cause") or "",
        "solution": case.get("solution") or "",
        "recommended_action": case.get("recommended_action") or "none",
        "analysis": analysis,
    }
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
    ]}


def build_dataset(mode: str = "verified", val_ratio: float = 0.1, seed: int = 42) -> dict[str, Any]:
    mode = mode if mode in ("verified", "verified_recovered") else "verified"
    cases = _eligible_cases(mode)
    if not cases:
        raise ValueError(
            "Nenhum caso elegível ainda. Valide diagnósticos na tela de IA (botão 'Resolveu') "
            "para gerar exemplos reais de treino.")
    system = _system_prompt()
    # remove duplicados exatos de erro+solução
    seen, examples = set(), []
    for c in cases:
        key = hashlib.sha256(f"{c['error_text']}|{c.get('solution')}".encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        examples.append((c, _example(c, system)))
    rnd = random.Random(seed)
    rnd.shuffle(examples)
    n_val = int(len(examples) * val_ratio) if len(examples) >= 20 else 0
    val, train = examples[:n_val], examples[n_val:]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"gboc_diag_{ts}"
    d = finetune_dir()
    train_path = d / f"{base}.train.jsonl"
    with open(train_path, "w", encoding="utf-8") as fh:
        for _, ex in train:
            fh.write(json.dumps(ex, ensure_ascii=False) + "\n")
    val_path = None
    if val:
        val_path = d / f"{base}.val.jsonl"
        with open(val_path, "w", encoding="utf-8") as fh:
            for _, ex in val:
                fh.write(json.dumps(ex, ensure_ascii=False) + "\n")
    manifest = {
        "name": base, "created_at": datetime.now().isoformat(timespec="seconds"), "mode": mode,
        "train_examples": len(train), "val_examples": len(val),
        "case_ids": [c["id"] for c, _ in examples],
        "evidence": {e: sum(1 for c, _ in examples if c.get("_evidence") == e) for e in {c.get("_evidence") for c, _ in examples}},
        "system_prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
        "format": "chat-messages-jsonl",
        "below_recommended": len(examples) < MIN_RECOMMENDED_EXAMPLES,
    }
    (d / f"{base}.manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest | {"files": [p.name for p in (train_path, val_path) if p]}


def list_datasets() -> list[dict[str, Any]]:
    out = []
    for m in sorted(finetune_dir().glob("*.manifest.json"), reverse=True):
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
        except Exception:
            continue
        files = [p.name for p in finetune_dir().glob(f"{data.get('name')}.*.jsonl")]
        out.append({**{k: data.get(k) for k in ("name", "created_at", "mode", "train_examples", "val_examples",
                                                 "below_recommended")}, "files": sorted(files)})
    return out


def dataset_file(filename: str) -> Path:
    if not re.fullmatch(r"gboc_diag_\d{8}_\d{6}\.(train|val)\.jsonl", filename or ""):
        raise ValueError("Nome de arquivo de dataset inválido.")
    p = finetune_dir() / filename
    if not p.is_file():
        raise FileNotFoundError(filename)
    return p


# ──────────────────────────────────────────────────────────────────────────────
# Importação no Ollama
# ──────────────────────────────────────────────────────────────────────────────

def _ollama_host() -> str:
    from engines import ai_providers as aip
    from engines.ai_diagnostic_engine import ai_diagnostic_engine
    info = aip.list_ollama_models(ai_diagnostic_engine.config, timeout=5.0)
    if not info.get("connected"):
        raise RuntimeError(f"Ollama inacessível: {info.get('error')}")
    return info["host"]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _upload_blob(host: str, path: Path, digest: str, opts: dict[str, Any]) -> None:
    head = httpx.head(f"{host}/api/blobs/sha256:{digest}", timeout=30.0, **opts)
    if head.status_code == 200:
        return
    size = path.stat().st_size
    sent = {"n": 0}

    def gen():
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
                sent["n"] += len(chunk)
                _import_state["phase"] = f"enviando arquivo ao Ollama ({sent['n'] * 100 // max(size, 1)}%)"
                yield chunk

    resp = httpx.post(f"{host}/api/blobs/sha256:{digest}", content=gen(),
                      timeout=httpx.Timeout(None, connect=15.0), **opts)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Ollama recusou o arquivo (HTTP {resp.status_code}): {resp.text[:300]}")


def import_to_ollama(model_name: str, file_path: str, kind: str = "gguf", base_model: str | None = None,
                     set_default: bool = False) -> dict[str, Any]:
    from engines import ai_providers as aip
    model_name = (model_name or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._\-/]{1,80}(:[a-z0-9._\-]{1,40})?", model_name):
        raise ValueError("Nome do modelo inválido (use letras minúsculas, números, '-', '_', '.', ex.: gboc-diag:v1).")
    path = Path(str(file_path or "").strip().strip('"'))
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado no host do Agente: {path}")
    if path.suffix.lower() not in (".gguf", ".safetensors"):
        raise ValueError("Envie um arquivo .gguf (modelo completo ou adapter LoRA) ou .safetensors (adapter).")
    if kind == "adapter" and not (base_model or "").strip():
        raise ValueError("Para adapter LoRA informe o modelo base instalado no Ollama (ex.: qwen2.5:3b).")

    host = _ollama_host()
    opts = aip._http_opts(host)
    _import_state["phase"] = "calculando hash do arquivo"
    digest = _sha256_file(path)
    _upload_blob(host, path, digest, opts)
    _import_state["phase"] = "criando o modelo no Ollama"
    body: dict[str, Any] = {
        "model": model_name,
        "system": _system_prompt(),
        "parameters": {"temperature": 0.2},
        "stream": False,
    }
    fname = path.name
    if kind == "adapter":
        body["from"] = base_model.strip()
        body["adapters"] = {fname: f"sha256:{digest}"}
    else:
        body["files"] = {fname: f"sha256:{digest}"}
    resp = httpx.post(f"{host}/api/create", json=body, timeout=httpx.Timeout(3600.0, connect=15.0), **opts)
    if resp.status_code != 200:
        hint = " (atualize o Ollama para 0.5 ou superior)" if resp.status_code in (400, 404) else ""
        raise RuntimeError(f"Ollama não criou o modelo (HTTP {resp.status_code}){hint}: {resp.text[:400]}")
    result = {"model": model_name, "host": host, "kind": kind, "file": str(path), "digest": digest,
              "ollama_response": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:300]}
    if set_default:
        from engines.ai_diagnostic_engine import ai_diagnostic_engine
        ai_diagnostic_engine.save_config({"ollama_model": model_name})
        result["set_default"] = True
    return result


def import_async(**kwargs) -> bool:
    if not _import_lock.acquire(blocking=False):
        return False

    def run():
        _import_state.update(running=True, phase="iniciando", last_error=None, started_at=time.time())
        try:
            _import_state["last_result"] = import_to_ollama(**kwargs)
            _import_state["phase"] = "concluído"
        except Exception as e:
            logger.warning(f"[FINETUNE] Importação no Ollama falhou: {e}")
            _import_state["last_error"] = f"{e.__class__.__name__}: {e}"
            _import_state["phase"] = "falhou"
        finally:
            _import_state["running"] = False
            _import_lock.release()

    threading.Thread(target=run, name="gboc-ollama-import", daemon=True).start()
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Treino local (opcional) — somente quando o ambiente tem GPU NVIDIA + CUDA + Unsloth
# ──────────────────────────────────────────────────────────────────────────────

_train_state: dict[str, Any] = {"running": False, "phase": "", "run_dir": None, "pid": None,
                                "last_result": None, "last_error": None}
_train_lock = threading.Lock()


def train_state(log_lines: int = 40) -> dict[str, Any]:
    st = dict(_train_state)
    if st.get("run_dir"):
        log = Path(st["run_dir"]) / "train.log"
        if log.is_file():
            try:
                st["log_tail"] = log.read_text(encoding="utf-8", errors="replace").splitlines()[-log_lines:]
            except OSError:
                pass
    return st


def train_local(dataset_name: str, base_model: str | None = None, epochs: float = 3.0, export_gguf: bool = True) -> dict[str, Any]:
    """Inicia o treino LoRA nesta máquina. Recusa com motivo claro se o ambiente não atende."""
    from engines import ai_capabilities
    from engines.ai_diagnostic_engine import ai_diagnostic_engine
    if ai_diagnostic_engine.config.get("finetune_local_enabled", False) is not True:
        raise PermissionError("Treino local está desativado. Ative em 'Capacidades do ambiente' na tela de IA.")
    caps = ai_capabilities.evaluate(force=True)
    if not caps.get("local_training_available"):
        ft = next((f for f in caps["features"] if f["key"] == "finetune"), {})
        raise RuntimeError("Este ambiente não atende ao treino local: " + "; ".join(ft.get("missing") or ["requisitos ausentes"]))
    if not re.fullmatch(r"gboc_diag_\d{8}_\d{6}", dataset_name or ""):
        raise ValueError("Dataset inválido.")
    train = finetune_dir() / f"{dataset_name}.train.jsonl"
    if not train.is_file():
        raise FileNotFoundError(f"Dataset não encontrado: {train.name}")
    val = finetune_dir() / f"{dataset_name}.val.jsonl"
    script = Path(__file__).resolve().parent.parent / "scripts" / "finetune" / "train_lora_gboc.py"
    if not script.is_file():
        raise FileNotFoundError(f"Script de treino não encontrado: {script}")
    if not _train_lock.acquire(blocking=False):
        raise RuntimeError("Já existe um treino em andamento.")
    import subprocess
    import sys
    run_dir = finetune_dir() / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(script), "--train", str(train), "--out", str(run_dir), "--epochs", str(float(epochs))]
    if val.is_file():
        cmd += ["--val", str(val)]
    if base_model:
        cmd += ["--base", base_model.strip()]
    if export_gguf:
        cmd.append("--export-gguf")

    def run():
        _train_state.update(running=True, phase="treinando", run_dir=str(run_dir), last_error=None, last_result=None,
                            started_at=time.time())
        try:
            with open(run_dir / "train.log", "w", encoding="utf-8") as log:
                proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(run_dir),
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                _train_state["pid"] = proc.pid
                rc = proc.wait()
            ggufs = sorted(str(p) for p in (run_dir / "gguf").glob("*.gguf")) if (run_dir / "gguf").is_dir() else []
            if rc == 0:
                _train_state["last_result"] = {"run_dir": str(run_dir), "adapter": str(run_dir / "adapter"), "gguf": ggufs}
                _train_state["phase"] = "concluído"
            else:
                _train_state["last_error"] = f"O treino terminou com código {rc}. Veja o log da execução."
                _train_state["phase"] = "falhou"
        except Exception as e:
            _train_state["last_error"] = f"{e.__class__.__name__}: {e}"
            _train_state["phase"] = "falhou"
        finally:
            _train_state.update(running=False, pid=None)
            _train_lock.release()

    threading.Thread(target=run, name="gboc-train-local", daemon=True).start()
    return {"status": "started", "run_dir": str(run_dir)}
