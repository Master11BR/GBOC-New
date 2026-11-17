#!/usr/bin/env python3
"""
GBOC Agent - RAG local (base de conhecimento da IA)

Índice local por Agente em data/ai/gboc_ai.db (SQLite próprio, dentro da área do Agente).
Fontes indexadas (somente dados reais do Agente):
  • solucoes  – casos de falha diagnosticados (ai_cases), com destaque para os validados pelo operador
  • erros     – job_failure_log (falhas de tarefas, retentativas e resolução)
  • execucoes – task_executions (status, duração, volumes, erro, snapshot)
  • logs      – linhas WARNING/ERROR dos logs do Agente (gboc_agent_errors.log, task_errors.log, gboc_agent.log)
  • docs      – documentação Markdown do GBOC (pasta do Agente, docs/ e a raiz do projeto quando existir)

Busca híbrida:
  • BM25 (palavras-chave, sempre disponível, sem dependências)
  • Vetorial (embeddings via Ollama, OpenAI ou Gemini) quando configurada — combinação por RRF.

Configuração em config/global_settings.json → global_settings.ai_llm_config:
  rag_enabled (bool, padrão True)
  rag_embedding_provider: "auto" | "ollama" | "openai" | "gemini" | "none"   (auto = só Ollama local)
  rag_embedding_model: nome do modelo de embedding (padrão por provedor)
  rag_reindex_hours: intervalo da reindexação automática (padrão 6)
  rag_execution_days: dias de execuções indexadas (padrão 90)
"""

from __future__ import annotations

import array
import hashlib
import json
import logging
import math
import re
import sqlite3
import threading
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx

logger = logging.getLogger("GBOC.AIRAG")

SOURCES = ("solucoes", "erros", "execucoes", "logs", "docs")
SOURCE_LABELS = {
    "solucoes": "Soluções e diagnósticos",
    "erros": "Falhas de tarefas",
    "execucoes": "Execuções de backup",
    "logs": "Logs do Agente",
    "docs": "Documentação GBOC",
}

DEFAULT_EMBED_MODELS = {
    "ollama": "nomic-embed-text",
    "openai": "text-embedding-3-small",
    "gemini": "text-embedding-004",
}
_OLLAMA_EMBED_HINTS = ("embed", "bge", "minilm", "e5-", "gte-", "snowflake-arctic-embed", "paraphrase")

CHUNK_CHARS = 900
CHUNK_OVERLAP = 120
MAX_DOC_FILE_BYTES = 2 * 1024 * 1024
LOG_TAIL_BYTES = 3 * 1024 * 1024
EMBED_BATCH = 16

_STOPWORDS = set("""
a o e de da do das dos em no na nos nas um uma uns umas para por com sem ao aos à às que se ou como mais
mas foi ser sao são é esta está este isso esse essa the of and to in for on is it with as at by an be this
from or are was were not que qual quais quando onde porque por que nao não sim
""".split())

_lock = threading.RLock()
_local = threading.local()
_bm25_cache: dict[str, Any] = {"version": -1}
_index_state: dict[str, Any] = {"running": False, "last_run": None, "last_result": None, "last_error": None}
_scheduler_started = False


# ──────────────────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────────────────

def _agent_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_config() -> dict[str, Any]:
    try:
        from engines.ai_diagnostic_engine import ai_diagnostic_engine
        return dict(ai_diagnostic_engine.config)
    except Exception as e:
        logger.debug(f"Config de IA indisponível: {e}")
        return {}


def rag_enabled(cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg if cfg is not None else load_config()
    return cfg.get("rag_enabled", True) is not False


# ──────────────────────────────────────────────────────────────────────────────
# Armazenamento (SQLite local do Agente)
# ──────────────────────────────────────────────────────────────────────────────

def db_path() -> Path:
    try:
        from core.gboc_paths import data_dir
        return data_dir("ai") / "gboc_ai.db"
    except Exception:
        p = _agent_root() / "data" / "ai"
        p.mkdir(parents=True, exist_ok=True)
        return p / "gboc_ai.db"


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(db_path()), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _ensure_schema(conn)
        _local.conn = conn
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            ref TEXT NOT NULL,
            title TEXT,
            content TEXT NOT NULL,
            meta TEXT,
            content_hash TEXT NOT NULL,
            embedding BLOB,
            emb_model TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(source, ref)
        );
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_source ON rag_chunks(source);
        CREATE TABLE IF NOT EXISTS rag_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()


def _bump_version(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO rag_meta(key, value) VALUES('version', '1') "
        "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)"
    )


def _version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM rag_meta WHERE key='version'").fetchone()
    return int(row[0]) if row else 0


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _redact(text: str) -> str:
    try:
        from core.log_redact import redact
        return redact(text)
    except Exception:
        return text


# ──────────────────────────────────────────────────────────────────────────────
# Texto: normalização, tokenização e chunking
# ──────────────────────────────────────────────────────────────────────────────

def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.\-:]*[a-z0-9]|[a-z0-9]")


def tokenize(text: str) -> list[str]:
    toks = []
    for t in _TOKEN_RE.findall(_fold(text)):
        if t in _STOPWORDS or len(t) < 2:
            continue
        toks.append(t)
        # também indexa partes de termos compostos (ex.: "restic.exe" → "restic", "exe")
        if any(ch in t for ch in ".-_:"):
            toks.extend(p for p in re.split(r"[.\-_:]+", t) if len(p) >= 2 and p not in _STOPWORDS)
    return toks


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = (text or "").strip()
    if len(text) <= size:
        return [text] if text else []
    parts: list[str] = []
    paragraphs = re.split(r"\n\s*\n", text)
    buf = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        while len(para) > size:
            if buf:
                parts.append(buf)
                buf = ""
            cut = para.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            parts.append(para[:cut].strip())
            para = para[max(0, cut - overlap):].strip()
        if len(buf) + len(para) + 2 <= size:
            buf = f"{buf}\n\n{para}" if buf else para
        else:
            if buf:
                parts.append(buf)
            tail = buf[-overlap:] if buf else ""
            buf = f"{tail}\n\n{para}".strip() if tail else para
    if buf:
        parts.append(buf)
    return [p for p in parts if p.strip()]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# Embeddings (opcional)
# ──────────────────────────────────────────────────────────────────────────────

def embedding_settings(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve provedor/modelo de embedding. 'auto' usa somente o Ollama local, se houver modelo de embedding."""
    cfg = cfg if cfg is not None else load_config()
    provider = str(cfg.get("rag_embedding_provider") or "auto").strip().lower()
    model = str(cfg.get("rag_embedding_model") or "").strip()
    if provider in ("none", "off", "desativado", ""):
        return {"provider": "none", "model": "", "reason": "Busca vetorial desativada (somente palavras-chave)."}

    from engines import ai_providers as aip

    if provider in ("auto", "ollama"):
        info = aip.list_ollama_models(cfg, timeout=4.0)
        if not info.get("connected"):
            if provider == "ollama":
                return {"provider": "none", "model": model, "reason": f"Ollama inacessível: {info.get('error')}"}
            return {"provider": "none", "model": "", "reason": "Ollama não encontrado — usando busca por palavras-chave."}
        installed = info.get("models") or []
        chosen = ""
        if model:
            chosen = next((m for m in installed if m == model or m.split(":")[0] == model.split(":")[0]), "")
        if not chosen:
            chosen = next((m for m in installed if any(h in m.lower() for h in _OLLAMA_EMBED_HINTS)), "")
        if not chosen:
            want = model or DEFAULT_EMBED_MODELS["ollama"]
            return {"provider": "none", "model": want, "host": info.get("host"),
                    "reason": f"Nenhum modelo de embedding instalado no Ollama. Instale com: ollama pull {want}"}
        return {"provider": "ollama", "model": chosen, "host": info.get("host"), "reason": ""}

    if provider == "openai":
        key = aip.resolve_api_key(cfg, "openai")
        if not key:
            return {"provider": "none", "model": model, "reason": "Chave da OpenAI não configurada."}
        return {"provider": "openai", "model": model or DEFAULT_EMBED_MODELS["openai"], "key": key,
                "base": str(cfg.get("openai_base_url") or "https://api.openai.com/v1").rstrip("/"), "reason": ""}

    if provider == "gemini":
        key = aip.resolve_api_key(cfg, "gemini")
        if not key:
            return {"provider": "none", "model": model, "reason": "Chave do Gemini não configurada."}
        return {"provider": "gemini", "model": model or DEFAULT_EMBED_MODELS["gemini"], "key": key, "reason": ""}

    return {"provider": "none", "model": model, "reason": f"Provedor de embedding '{provider}' não suportado."}


def _embed(settings: dict[str, Any], texts: list[str]) -> list[list[float]]:
    prov = settings.get("provider")
    model = settings.get("model")
    if prov == "ollama":
        from engines import ai_providers as aip
        host = settings["host"]
        opts = aip._http_opts(host)
        resp = httpx.post(f"{host}/api/embed", json={"model": model, "input": texts},
                          timeout=httpx.Timeout(300.0, connect=5.0), **opts)
        if resp.status_code == 404:
            out = []
            for t in texts:  # Ollama antigo: /api/embeddings (um texto por chamada)
                r = httpx.post(f"{host}/api/embeddings", json={"model": model, "prompt": t},
                               timeout=httpx.Timeout(120.0, connect=5.0), **opts)
                r.raise_for_status()
                out.append(r.json().get("embedding") or [])
            return out
        resp.raise_for_status()
        return resp.json().get("embeddings") or []
    if prov == "openai":
        resp = httpx.post(f"{settings['base']}/embeddings", json={"model": model, "input": texts},
                          headers={"Authorization": f"Bearer {settings['key']}"}, timeout=60.0)
        resp.raise_for_status()
        data = sorted(resp.json().get("data") or [], key=lambda d: d.get("index", 0))
        return [d.get("embedding") or [] for d in data]
    if prov == "gemini":
        m = model if model.startswith("models/") else f"models/{model}"
        resp = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/{m}:batchEmbedContents",
            params={"key": settings["key"]},
            json={"requests": [{"model": m, "content": {"parts": [{"text": t}]}} for t in texts]},
            timeout=60.0,
        )
        resp.raise_for_status()
        return [e.get("values") or [] for e in resp.json().get("embeddings") or []]
    return []


def _to_blob(vec: list[float]) -> bytes:
    return array.array("f", vec).tobytes()


def _from_blob(blob: bytes | None) -> array.array | None:
    if not blob:
        return None
    a = array.array("f")
    a.frombytes(blob)
    return a


def _norm(v) -> float:
    return math.sqrt(sum(x * x for x in v)) or 1.0


def embed_pending(settings: dict[str, Any] | None = None, limit: int = 4000,
                  progress: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Gera embeddings dos trechos ainda sem vetor (ou com vetor de outro modelo)."""
    settings = settings or embedding_settings()
    if settings.get("provider") == "none":
        return {"embedded": 0, "skipped_reason": settings.get("reason")}
    emb_id = f"{settings['provider']}:{settings['model']}"
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, content FROM rag_chunks WHERE emb_model IS NULL OR emb_model != ? ORDER BY id DESC LIMIT ?",
        (emb_id, limit),
    ).fetchall()
    done = 0
    for i in range(0, len(rows), EMBED_BATCH):
        batch = rows[i:i + EMBED_BATCH]
        texts = [f"{r['title'] or ''}\n{r['content']}"[:4000] for r in batch]
        try:
            vecs = _embed(settings, texts)
        except Exception as e:
            logger.warning(f"[RAG] Falha ao gerar embeddings ({emb_id}): {e}")
            return {"embedded": done, "error": f"{e.__class__.__name__}: {e}", "model": emb_id}
        with _lock:
            for r, v in zip(batch, vecs):
                if v:
                    conn.execute("UPDATE rag_chunks SET embedding=?, emb_model=? WHERE id=?", (_to_blob(v), emb_id, r["id"]))
                    done += 1
            conn.commit()
        if progress:
            progress(done)
    return {"embedded": done, "model": emb_id}


# ──────────────────────────────────────────────────────────────────────────────
# Gravação de documentos
# ──────────────────────────────────────────────────────────────────────────────

def upsert_document(source: str, ref: str, title: str, content: str, meta: dict[str, Any] | None = None) -> list[str]:
    """Grava um documento (dividido em trechos). Retorna os refs gravados. Conteúdo idêntico não é regravado."""
    content = _redact((content or "").strip())
    if not content:
        return []
    pieces = chunk_text(content)
    refs = []
    conn = get_conn()
    meta_json = json.dumps(meta or {}, ensure_ascii=False, default=str)
    with _lock:
        for idx, piece in enumerate(pieces):
            cref = ref if len(pieces) == 1 else f"{ref}#{idx}"
            h = _hash(f"{title}\n{piece}")
            row = conn.execute("SELECT id, content_hash FROM rag_chunks WHERE source=? AND ref=?", (source, cref)).fetchone()
            if row and row["content_hash"] == h:
                if row and meta:
                    conn.execute("UPDATE rag_chunks SET meta=? WHERE id=?", (meta_json, row["id"]))
            elif row:
                conn.execute(
                    "UPDATE rag_chunks SET title=?, content=?, meta=?, content_hash=?, embedding=NULL, emb_model=NULL, updated_at=? WHERE id=?",
                    (title, piece, meta_json, h, _now(), row["id"]),
                )
                _bump_version(conn)
            else:
                conn.execute(
                    "INSERT INTO rag_chunks(source, ref, title, content, meta, content_hash, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (source, cref, title, piece, meta_json, h, _now(), _now()),
                )
                _bump_version(conn)
            refs.append(cref)
        # remove trechos excedentes de uma versão anterior maior do mesmo documento
        if len(pieces) > 1 or conn.execute(
                "SELECT 1 FROM rag_chunks WHERE source=? AND ref LIKE ? LIMIT 1", (source, f"{ref}#%")).fetchone():
            keep = set(refs)
            for r in conn.execute("SELECT id, ref FROM rag_chunks WHERE source=? AND (ref=? OR ref LIKE ?)",
                                  (source, ref, f"{ref}#%")).fetchall():
                if r["ref"] not in keep:
                    conn.execute("DELETE FROM rag_chunks WHERE id=?", (r["id"],))
                    _bump_version(conn)
        conn.commit()
    return refs


def prune_source(source: str, keep_refs: Iterable[str], ref_prefix: str | None = None) -> int:
    """Remove do índice os documentos de uma fonte que não existem mais na origem."""
    keep = set(keep_refs)
    conn = get_conn()
    removed = 0
    with _lock:
        q = "SELECT id, ref FROM rag_chunks WHERE source=?"
        params: tuple = (source,)
        if ref_prefix:
            q += " AND ref LIKE ?"
            params = (source, f"{ref_prefix}%")
        for r in conn.execute(q, params).fetchall():
            if r["ref"] not in keep:
                conn.execute("DELETE FROM rag_chunks WHERE id=?", (r["id"],))
                removed += 1
        if removed:
            _bump_version(conn)
        conn.commit()
    return removed


# ──────────────────────────────────────────────────────────────────────────────
# Indexadores (dados reais do Agente)
# ──────────────────────────────────────────────────────────────────────────────

def _shared_rows(sql: str, params: tuple = ()) -> list[tuple]:
    from shared_core import get_shared_core
    with get_shared_core().get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            return list(cur.fetchall() or [])
        finally:
            try:
                cur.close()
            except Exception:
                pass


def _fmt_bytes(n: Any) -> str:
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        return str(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or u == "TB":
            return f"{v:.1f} {u}" if u != "B" else f"{int(v)} B"
        v /= 1024
    return str(n)


def index_solucoes() -> dict[str, Any]:
    from engines import ai_cases
    keep = []
    n = 0
    for case in ai_cases.list_cases(limit=5000):
        keep += upsert_document("solucoes", f"case:{case['id']}", case_title(case), case_text(case),
                                {"case_id": case["id"], "verified": case.get("feedback") == "resolved",
                                 "task_id": case.get("task_id"), "created_at": case.get("created_at")})
        n += 1
    removed = prune_source("solucoes", keep, "case:")
    return {"documents": n, "removed": removed}


def case_title(case: dict[str, Any]) -> str:
    status = {"resolved": "✔ Solução validada", "not_resolved": "✖ Não resolveu"}.get(case.get("feedback") or "", "Diagnóstico")
    task = f" — tarefa '{case['task_name']}'" if case.get("task_name") else ""
    return f"{status}{task}"


def case_text(case: dict[str, Any]) -> str:
    lines = [f"Erro: {case.get('error_text') or ''}"]
    if case.get("cause"):
        lines.append(f"Causa: {case['cause']}")
    if case.get("solution"):
        lines.append(f"Solução: {case['solution']}")
    if case.get("operator_note"):
        lines.append(f"Observação do operador: {case['operator_note']}")
    fb = case.get("feedback")
    if fb == "resolved":
        lines.append("Resultado: o operador confirmou que esta solução resolveu o problema.")
    elif fb == "not_resolved":
        lines.append("Resultado: o operador informou que esta solução NÃO resolveu o problema.")
    if case.get("engine"):
        lines.append(f"Motor: {case['engine']}")
    lines.append(f"Origem do diagnóstico: {case.get('provider') or 'desconhecida'}; data: {case.get('created_at')}")
    return "\n".join(lines)


def index_erros() -> dict[str, Any]:
    try:
        rows = _shared_rows(
            "SELECT id, task_id, task_name, execution_id, failure_reason, retry_count, status, "
            "first_failed_at, last_retried_at, resolved_at FROM job_failure_log ORDER BY id DESC LIMIT 3000"
        )
    except Exception as e:
        return {"documents": 0, "error": f"job_failure_log indisponível: {e}"}
    keep = []
    for r in rows:
        (fid, task_id, task_name, exec_id, reason, retries, status, first_at, last_at, resolved_at) = r
        resolved = bool(resolved_at) or str(status or "").lower() == "resolved"
        text = (
            f"Falha na tarefa '{task_name}' (id {task_id}, execução {exec_id}).\n"
            f"Motivo: {reason or ''}\n"
            f"Retentativas: {retries}; status: {status}; primeira falha: {first_at}; última tentativa: {last_at}; "
            f"{'resolvida em ' + str(resolved_at) if resolved else 'ainda não resolvida'}."
        )
        keep += upsert_document("erros", f"jfl:{fid}", f"Falha — {task_name}", text,
                                {"task_id": task_id, "resolved": resolved, "date": str(first_at)})
    removed = prune_source("erros", keep, "jfl:")
    return {"documents": len(rows), "removed": removed}


def index_execucoes(days: int = 90) -> dict[str, Any]:
    since = datetime.fromtimestamp(time.time() - days * 86400).isoformat(timespec="seconds")
    try:
        rows = _shared_rows(
            "SELECT e.id, e.task_id, t.name, e.status, e.started_at, e.completed_at, e.files_processed, "
            "e.bytes_processed, e.error_message, e.snapshot_id "
            "FROM task_executions e LEFT JOIN tasks t ON t.id = e.task_id "
            "WHERE e.started_at >= %s ORDER BY e.id DESC LIMIT 6000",
            (since,),
        )
    except Exception as e:
        return {"documents": 0, "error": f"task_executions indisponível: {e}"}
    keep = []
    for r in rows:
        (eid, task_id, name, status, started, completed, files, bytes_, err, snap) = r
        dur = ""
        try:
            if started and completed:
                s = started if isinstance(started, datetime) else datetime.fromisoformat(str(started))
                c = completed if isinstance(completed, datetime) else datetime.fromisoformat(str(completed))
                secs = int((c - s).total_seconds())
                dur = f"{secs // 3600}h{(secs % 3600) // 60:02d}m{secs % 60:02d}s"
        except Exception:
            pass
        text = (
            f"Execução {eid} da tarefa '{name or task_id}' (id {task_id}): status {status}.\n"
            f"Início {started}; fim {completed}{'; duração ' + dur if dur else ''}.\n"
            f"Arquivos: {files or 0}; volume: {_fmt_bytes(bytes_)}; snapshot: {snap or '-'}."
        )
        if err:
            text += f"\nErro: {err}"
        keep += upsert_document("execucoes", f"exec:{eid}", f"Execução {eid} — {name or task_id} ({status})", text,
                                {"task_id": task_id, "status": status, "date": str(started)})
    removed = prune_source("execucoes", keep, "exec:")
    return {"documents": len(rows), "removed": removed, "days": days}


_LOG_LEVEL_RE = re.compile(r"\b(ERROR|CRITICAL|WARNING|ERRO|FALHA|Traceback)\b|❌|⚠️|💥")


def index_logs() -> dict[str, Any]:
    logs_dir = _agent_root() / "logs"
    files = [logs_dir / "gboc_agent_errors.log", logs_dir / "task_errors.log", logs_dir / "gboc_agent.log"]
    keep = []
    total = 0
    for f in files:
        if not f.is_file():
            continue
        try:
            size = f.stat().st_size
            with open(f, "rb") as fh:
                if size > LOG_TAIL_BYTES:
                    fh.seek(size - LOG_TAIL_BYTES)
                raw = fh.read().decode("utf-8", "replace")
        except OSError as e:
            logger.debug(f"[RAG] Log {f} indisponível: {e}")
            continue
        lines = raw.splitlines()
        if size > LOG_TAIL_BYTES and lines:
            lines = lines[1:]  # primeira linha pode estar cortada
        if f.name == "gboc_agent.log":
            lines = [ln for ln in lines if _LOG_LEVEL_RE.search(ln)]
        # agrupa em blocos de ~25 linhas, deduplicando linhas repetidas consecutivas
        block: list[str] = []
        blocks: list[list[str]] = []
        last = None
        for ln in lines:
            key = re.sub(r"^\S+ \S+ ", "", ln)[:200]
            if key == last:
                continue
            last = key
            block.append(ln[:600])
            if len(block) >= 25:
                blocks.append(block)
                block = []
        if block:
            blocks.append(block)
        for b in blocks:
            text = "\n".join(b)
            ref = f"log:{f.name}:{_hash(text)[:16]}"
            first_ts = b[0][:19]
            keep += upsert_document("logs", ref, f"{f.name} — {first_ts}", text, {"file": f.name, "date": first_ts})
            total += 1
    removed = prune_source("logs", keep, "log:")
    return {"documents": total, "removed": removed}


def _doc_files() -> list[Path]:
    root = _agent_root()
    cands: list[Path] = []
    cands += sorted(root.glob("*.md"))
    docs = root / "docs"
    if docs.is_dir():
        cands += sorted(docs.rglob("*.md"))
    modules = root / "modules"
    if modules.is_dir():
        cands += sorted(modules.rglob("*.md"))
    # Layout de desenvolvimento/instalação completa: .md da raiz do projeto GBOC
    parent = root.parent
    if (parent / "GBOC-Agent").is_dir():
        cands += sorted(parent.glob("*.md"))
    seen, out = set(), []
    for p in cands:
        try:
            rp = p.resolve()
            if rp in seen or not p.is_file() or p.stat().st_size > MAX_DOC_FILE_BYTES:
                continue
            seen.add(rp)
            out.append(p)
        except OSError:
            continue
    return out


def index_docs() -> dict[str, Any]:
    keep = []
    files = _doc_files()
    root = _agent_root().parent
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(p.resolve().relative_to(root.resolve()))
        except ValueError:
            rel = p.name
        # divide por seções de título para trechos com contexto
        sections = re.split(r"(?m)^(?=#{1,3} )", text)
        for i, sec in enumerate(sections):
            sec = sec.strip()
            if len(sec) < 40:
                continue
            heading = sec.splitlines()[0].lstrip("# ").strip()[:120]
            keep += upsert_document("docs", f"doc:{rel}:{i}", f"{rel} — {heading}", sec, {"file": rel})
    removed = prune_source("docs", keep, "doc:")
    return {"documents": len(files), "removed": removed}


INDEXERS: dict[str, Callable[[], dict[str, Any]]] = {
    "solucoes": index_solucoes,
    "erros": index_erros,
    "execucoes": lambda: index_execucoes(int(load_config().get("rag_execution_days") or 90)),
    "logs": index_logs,
    "docs": index_docs,
}


def reindex(sources: Iterable[str] | None = None, embed: bool = True) -> dict[str, Any]:
    """Indexação incremental (só regrava o que mudou). Pode ser chamada a qualquer momento."""
    wanted = [s for s in (sources or SOURCES) if s in INDEXERS]
    if not _index_state_lock.acquire(blocking=False):
        return {"status": "busy", "message": "Indexação já em andamento."}
    _index_state.update(running=True, last_error=None, started_at=_now(), phase="indexando")
    t0 = time.monotonic()
    result: dict[str, Any] = {"sources": {}}
    try:
        for s in wanted:
            _index_state["phase"] = f"indexando {SOURCE_LABELS.get(s, s)}"
            try:
                result["sources"][s] = INDEXERS[s]()
            except Exception as e:
                logger.warning(f"[RAG] Falha ao indexar '{s}': {e}", exc_info=True)
                result["sources"][s] = {"error": f"{e.__class__.__name__}: {e}"}
        if embed:
            _index_state["phase"] = "gerando embeddings"
            result["embeddings"] = embed_pending(progress=lambda n: _index_state.update(phase=f"gerando embeddings ({n})"))
        result["status"] = "success"
        result["duration_seconds"] = round(time.monotonic() - t0, 1)
        _index_state["last_result"] = result
        return result
    except Exception as e:
        _index_state["last_error"] = str(e)
        raise
    finally:
        _index_state.update(running=False, last_run=_now(), phase="")
        _index_state_lock.release()


_index_state_lock = threading.Lock()


def reindex_async(sources: Iterable[str] | None = None) -> bool:
    if _index_state["running"]:
        return False
    threading.Thread(target=lambda: _safe_reindex(sources), name="gboc-rag-index", daemon=True).start()
    return True


def _safe_reindex(sources=None):
    try:
        reindex(sources)
    except Exception as e:
        logger.warning(f"[RAG] Reindexação falhou: {e}")


def start_scheduler() -> None:
    """Reindexação automática em segundo plano (primeira após 3 min do start, depois a cada N horas)."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    def loop():
        time.sleep(180)
        while True:
            cfg = load_config()
            if rag_enabled(cfg):
                _safe_reindex()
            hours = cfg.get("rag_reindex_hours") or 6
            try:
                hours = max(0.5, float(hours))
            except (TypeError, ValueError):
                hours = 6.0
            time.sleep(hours * 3600)

    threading.Thread(target=loop, name="gboc-rag-scheduler", daemon=True).start()
    logger.info("[RAG] Agendador de indexação da base de conhecimento iniciado.")


# ──────────────────────────────────────────────────────────────────────────────
# Busca
# ──────────────────────────────────────────────────────────────────────────────

def _load_bm25(conn: sqlite3.Connection) -> dict[str, Any]:
    ver = _version(conn)
    if _bm25_cache.get("version") == ver:
        return _bm25_cache
    rows = conn.execute("SELECT id, source, title, content FROM rag_chunks").fetchall()
    docs, df = {}, Counter()
    total_len = 0
    for r in rows:
        toks = tokenize(f"{r['title'] or ''} {r['content']}")
        tf = Counter(toks)
        docs[r["id"]] = (r["source"], tf, len(toks))
        df.update(tf.keys())
        total_len += len(toks)
    _bm25_cache.clear()
    _bm25_cache.update(version=ver, docs=docs, df=df, n=len(docs), avgdl=(total_len / len(docs)) if docs else 1.0)
    return _bm25_cache


def _bm25_search(conn, query: str, sources: set[str], top: int) -> list[tuple[int, float]]:
    idx = _load_bm25(conn)
    q = tokenize(query)
    if not q or not idx["n"]:
        return []
    k1, b = 1.4, 0.75
    n, avgdl, df = idx["n"], idx["avgdl"], idx["df"]
    idf = {t: math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5)) for t in set(q) if df.get(t)}
    if not idf:
        return []
    scores = []
    for did, (src, tf, dl) in idx["docs"].items():
        if sources and src not in sources:
            continue
        s = 0.0
        for t, w in idf.items():
            f = tf.get(t)
            if f:
                s += w * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        if s > 0:
            scores.append((did, s))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top]


def _vector_search(conn, query: str, sources: set[str], top: int, settings: dict[str, Any]) -> tuple[list[tuple[int, float]], str]:
    if settings.get("provider") == "none":
        return [], settings.get("reason", "")
    emb_id = f"{settings['provider']}:{settings['model']}"
    try:
        qv = _embed(settings, [query[:4000]])
        qv = qv[0] if qv else []
    except Exception as e:
        return [], f"Falha no embedding da pergunta: {e}"
    if not qv:
        return [], "Embedding vazio."
    qn = _norm(qv)
    rows = conn.execute("SELECT id, source, embedding FROM rag_chunks WHERE emb_model=?", (emb_id,)).fetchall()
    try:
        import numpy as np  # opcional: acelera quando disponível
        ids, mats = [], []
        for r in rows:
            if sources and r["source"] not in sources:
                continue
            ids.append(r["id"])
            mats.append(np.frombuffer(r["embedding"], dtype=np.float32))
        if not ids:
            return [], ""
        m = np.vstack(mats)
        q = np.asarray(qv, dtype=np.float32)
        sims = (m @ q) / ((np.linalg.norm(m, axis=1) * qn) + 1e-9)
        order = np.argsort(-sims)[:top]
        return [(ids[i], float(sims[i])) for i in order], ""
    except ImportError:
        pass
    scored = []
    for r in rows:
        if sources and r["source"] not in sources:
            continue
        v = _from_blob(r["embedding"])
        if v is None or len(v) != len(qv):
            continue
        dot = sum(a * b for a, b in zip(v, qv))
        scored.append((r["id"], dot / (_norm(v) * qn)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top], ""


def search(query: str, k: int = 6, sources: Iterable[str] | None = None, use_vectors: bool = True) -> dict[str, Any]:
    """Busca híbrida (BM25 + vetorial com RRF). Retorna trechos reais do índice com a origem."""
    query = (query or "").strip()
    if not query:
        return {"results": [], "mode": "none"}
    conn = get_conn()
    src = {s for s in (sources or []) if s in SOURCES}
    pool = max(k * 5, 30)
    t0 = time.monotonic()
    lex = _bm25_search(conn, query, src, pool)
    vec, vec_note = ([], "")
    if use_vectors:
        vec, vec_note = _vector_search(conn, query, src, pool, embedding_settings())
    fused: dict[int, float] = {}
    for rank, (did, _) in enumerate(lex):
        fused[did] = fused.get(did, 0.0) + 1.0 / (60 + rank)
    for rank, (did, sim) in enumerate(vec):
        if sim < 0.2:
            continue
        fused[did] = fused.get(did, 0.0) + 1.0 / (60 + rank)
    # soluções validadas pelo operador têm prioridade
    ids = list(fused.keys())
    if not ids:
        return {"results": [], "mode": "hybrid" if vec else "keywords", "vector_note": vec_note,
                "duration_ms": int((time.monotonic() - t0) * 1000)}
    placeholders = ",".join("?" * len(ids))
    rows = {r["id"]: r for r in conn.execute(
        f"SELECT id, source, ref, title, content, meta, updated_at FROM rag_chunks WHERE id IN ({placeholders})", ids).fetchall()}
    lex_map, vec_map = dict(lex), dict(vec)
    results = []
    for did, score in fused.items():
        r = rows.get(did)
        if not r:
            continue
        meta = json.loads(r["meta"] or "{}")
        if r["source"] == "solucoes" and meta.get("verified"):
            score *= 1.5
        results.append({
            "id": did, "source": r["source"], "source_label": SOURCE_LABELS.get(r["source"], r["source"]),
            "ref": r["ref"], "title": r["title"], "content": r["content"], "meta": meta,
            "score": round(score, 5), "bm25": round(lex_map.get(did, 0.0), 3),
            "similarity": round(vec_map[did], 3) if did in vec_map else None, "updated_at": r["updated_at"],
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return {"results": results[:k], "mode": "hybrid" if vec else "keywords", "vector_note": vec_note,
            "duration_ms": int((time.monotonic() - t0) * 1000)}


def build_context(query: str, k: int = 5, sources: Iterable[str] | None = None,
                  max_chars: int = 5000) -> tuple[str, list[dict[str, Any]]]:
    """Texto pronto para o prompt + lista de fontes usadas. Vazio quando o RAG está desativado/sem resultados."""
    if not rag_enabled():
        return "", []
    try:
        res = search(query, k=k, sources=sources)
    except Exception as e:
        logger.debug(f"[RAG] Busca indisponível: {e}")
        return "", []
    parts, used, total = [], [], 0
    for i, r in enumerate(res["results"], 1):
        block = f"[{i}] ({r['source_label']}) {r['title']}\n{r['content']}"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
        used.append({"n": i, "source": r["source"], "source_label": r["source_label"], "title": r["title"],
                     "ref": r["ref"], "score": r["score"], "verified": bool(r["meta"].get("verified")),
                     "excerpt": r["content"][:400]})
    return "\n\n".join(parts), used


# ──────────────────────────────────────────────────────────────────────────────
# Estado
# ──────────────────────────────────────────────────────────────────────────────

def stats() -> dict[str, Any]:
    conn = get_conn()
    by_source = {s: {"label": SOURCE_LABELS[s], "chunks": 0, "embedded": 0} for s in SOURCES}
    for r in conn.execute("SELECT source, COUNT(*) c, SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) e "
                          "FROM rag_chunks GROUP BY source").fetchall():
        by_source.setdefault(r["source"], {"label": r["source"], "chunks": 0, "embedded": 0})
        by_source[r["source"]].update(chunks=r["c"], embedded=r["e"] or 0)
    try:
        size = db_path().stat().st_size
    except OSError:
        size = 0
    emb = embedding_settings()
    return {
        "enabled": rag_enabled(),
        "db_path": str(db_path()),
        "db_size_bytes": size,
        "total_chunks": sum(v["chunks"] for v in by_source.values()),
        "total_embedded": sum(v["embedded"] for v in by_source.values()),
        "sources": by_source,
        "embedding": {k: v for k, v in emb.items() if k != "key"},
        "indexer": {k: v for k, v in _index_state.items()},
    }
