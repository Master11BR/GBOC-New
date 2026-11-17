#!/usr/bin/env python3
"""
GBOC Agent - Casos de diagnóstico da IA (memória de soluções)

Cada diagnóstico de falha (LLM ou heurística) vira um "caso" com o erro real e a resposta dada.
O operador valida o caso (resolveu / não resolveu, com observação ou solução corrigida).

Uso:
  • RAG: casos (principalmente os validados) entram na base de conhecimento local → diagnósticos futuros
    passam a citar o que já resolveu antes neste ambiente.
  • Fine-tuning: somente casos reais validados (ou com recuperação comprovada da tarefa) geram o dataset JSONL.

Armazenado no mesmo SQLite local da IA (data/ai/gboc_ai.db).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("GBOC.AICases")
_lock = threading.RLock()
_schema_ok = False

FEEDBACK_VALUES = {"resolved", "not_resolved", ""}


def _conn():
    global _schema_ok
    from engines.ai_rag import get_conn
    conn = get_conn()
    if not _schema_ok:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ai_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                updated_at TEXT,
                origin TEXT,
                task_id INTEGER,
                task_name TEXT,
                execution_id INTEGER,
                engine TEXT,
                error_text TEXT NOT NULL,
                error_hash TEXT,
                cause TEXT,
                solution TEXT,
                recommended_action TEXT,
                analysis TEXT,
                provider TEXT,
                model TEXT,
                is_llm_real INTEGER DEFAULT 0,
                rag_sources TEXT,
                feedback TEXT DEFAULT '',
                operator_note TEXT,
                feedback_by TEXT,
                feedback_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ai_cases_hash ON ai_cases(error_hash);
            CREATE INDEX IF NOT EXISTS idx_ai_cases_feedback ON ai_cases(feedback);
        """)
        conn.commit()
        _schema_ok = True
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _norm_error(text: str) -> str:
    import re
    t = (text or "").lower()
    t = re.sub(r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}(\.\d+)?", "<ts>", t)
    t = re.sub(r"\b[0-9a-f]{12,}\b", "<id>", t)
    t = re.sub(r"\b\d+\b", "<n>", t)
    return " ".join(t.split())[:2000]


def record_case(error_text: str, result: dict[str, Any], *, origin: str = "diagnostico",
                task_id: Any = None, task_name: str | None = None, execution_id: Any = None,
                engine: str | None = None, rag_sources: list[dict[str, Any]] | None = None) -> int | None:
    """Registra o diagnóstico de uma falha real. Diagnósticos repetidos do mesmo erro em 1h não duplicam."""
    error_text = (error_text or "").strip()
    if not error_text or "teste" == error_text.lower().strip():
        return None
    try:
        from core.log_redact import redact
        error_text = redact(error_text)
    except Exception:
        pass
    eh = hashlib.sha256(_norm_error(error_text).encode()).hexdigest()
    cause = str(result.get("cause") or "")
    solution = str(result.get("solution") or "")
    with _lock:
        conn = _conn()
        since = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
        row = conn.execute(
            "SELECT id FROM ai_cases WHERE error_hash=? AND COALESCE(cause,'')=? AND created_at>=? ORDER BY id DESC LIMIT 1",
            (eh, cause, since),
        ).fetchone()
        if row:
            return int(row[0])
        cur = conn.execute(
            """INSERT INTO ai_cases(created_at, updated_at, origin, task_id, task_name, execution_id, engine, error_text,
                   error_hash, cause, solution, recommended_action, analysis, provider, model, is_llm_real, rag_sources)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), _now(), origin, _int(task_id), task_name, _int(execution_id), engine, error_text[:8000], eh,
             cause[:4000], solution[:6000], str(result.get("recommended_action") or "none"),
             str(result.get("analysis") or "")[:8000], str(result.get("provider") or ""), str(result.get("model") or ""),
             1 if result.get("is_llm_real") else 0, json.dumps(rag_sources or [], ensure_ascii=False)),
        )
        conn.commit()
        case_id = int(cur.lastrowid)
    _reindex_case_async(case_id)
    return case_id


def _int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _row_to_dict(r) -> dict[str, Any]:
    d = dict(r)
    try:
        d["rag_sources"] = json.loads(d.get("rag_sources") or "[]")
    except Exception:
        d["rag_sources"] = []
    d["is_llm_real"] = bool(d.get("is_llm_real"))
    return d


def get_case(case_id: int) -> dict[str, Any] | None:
    r = _conn().execute("SELECT * FROM ai_cases WHERE id=?", (int(case_id),)).fetchone()
    return _row_to_dict(r) if r else None


def list_cases(limit: int = 200, feedback: str | None = None, offset: int = 0) -> list[dict[str, Any]]:
    q = "SELECT * FROM ai_cases"
    params: list[Any] = []
    if feedback == "pending":
        q += " WHERE COALESCE(feedback,'')=''"
    elif feedback in ("resolved", "not_resolved"):
        q += " WHERE feedback=?"
        params.append(feedback)
    q += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [int(limit), int(offset)]
    return [_row_to_dict(r) for r in _conn().execute(q, params).fetchall()]


def counts() -> dict[str, int]:
    out = {"total": 0, "resolved": 0, "not_resolved": 0, "pending": 0}
    for r in _conn().execute("SELECT COALESCE(feedback,'') f, COUNT(*) c FROM ai_cases GROUP BY f").fetchall():
        key = r["f"] or "pending"
        out[key] = out.get(key, 0) + r["c"]
        out["total"] += r["c"]
    return out


def set_feedback(case_id: int, feedback: str, note: str | None = None, solution: str | None = None,
                 cause: str | None = None, user: str | None = None) -> dict[str, Any]:
    feedback = (feedback or "").strip()
    if feedback not in FEEDBACK_VALUES:
        raise ValueError("feedback deve ser 'resolved', 'not_resolved' ou vazio.")
    with _lock:
        conn = _conn()
        if not conn.execute("SELECT 1 FROM ai_cases WHERE id=?", (int(case_id),)).fetchone():
            raise KeyError(f"Caso {case_id} não encontrado.")
        sets = ["feedback=?", "feedback_at=?", "feedback_by=?", "updated_at=?"]
        params: list[Any] = [feedback, _now(), user or "", _now()]
        if note is not None:
            sets.append("operator_note=?")
            params.append(note.strip()[:4000])
        if solution is not None and solution.strip():
            sets.append("solution=?")
            params.append(solution.strip()[:6000])
        if cause is not None and cause.strip():
            sets.append("cause=?")
            params.append(cause.strip()[:4000])
        params.append(int(case_id))
        conn.execute(f"UPDATE ai_cases SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
    _reindex_case_async(int(case_id))
    return get_case(case_id) or {}


def task_recovered_after(case: dict[str, Any]) -> bool | None:
    """Evidência real: a tarefa do caso concluiu com sucesso depois do diagnóstico? (None = sem tarefa associada)."""
    if not case.get("task_id"):
        return None
    try:
        from shared_core import get_shared_core
        with get_shared_core().get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM task_executions WHERE task_id = %s AND status = 'completed' AND started_at >= %s",
                (int(case["task_id"]), str(case.get("created_at") or "")),
            )
            row = cur.fetchone()
            cur.close()
            return bool(row and row[0])
    except Exception as e:
        logger.debug(f"Verificação de recuperação indisponível: {e}")
        return None


def _reindex_case_async(case_id: int) -> None:
    def run():
        try:
            from engines import ai_rag
            case = get_case(case_id)
            if case:
                ai_rag.upsert_document("solucoes", f"case:{case_id}", ai_rag.case_title(case), ai_rag.case_text(case),
                                       {"case_id": case_id, "verified": case.get("feedback") == "resolved",
                                        "task_id": case.get("task_id"), "created_at": case.get("created_at")})
                ai_rag.embed_pending(limit=20)
        except Exception as e:
            logger.debug(f"[RAG] Caso {case_id} não indexado agora: {e}")
    threading.Thread(target=run, name=f"gboc-case-{case_id}", daemon=True).start()


def auto_diagnose_failure(task_id: Any, execution_id: Any, task_name: str | None, engine: str | None,
                          error_text: str) -> None:
    """Diagnóstico automático de falha de tarefa (config ai_llm_config.auto_diagnose_errors), em segundo plano.
    Não repete o diagnóstico do mesmo erro dentro de 6 horas."""
    def run():
        try:
            from engines.ai_diagnostic_engine import ai_diagnostic_engine
            if ai_diagnostic_engine.config.get("auto_diagnose_errors", True) is False:
                return
            eh = hashlib.sha256(_norm_error(error_text).encode()).hexdigest()
            since = (datetime.now() - timedelta(hours=6)).isoformat(timespec="seconds")
            if _conn().execute("SELECT 1 FROM ai_cases WHERE error_hash=? AND created_at>=? LIMIT 1", (eh, since)).fetchone():
                return
            import asyncio
            asyncio.run(ai_diagnostic_engine.analyze_error(
                error_text, record_case=True,
                case_meta={"origin": "falha_automatica", "task_id": task_id, "task_name": task_name,
                           "execution_id": execution_id, "engine": engine}))
        except Exception as e:
            logger.debug(f"Diagnóstico automático não executado: {e}")
    threading.Thread(target=run, name="gboc-auto-diagnose", daemon=True).start()
