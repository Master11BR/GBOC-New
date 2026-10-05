"""
GBOC Server — Testes de restauração agendados (evidência de recuperabilidade).

O Server agenda e dispara, pelo canal do Gerenciamento Remoto (WebSocket do agente ou HTTP
direto), o teste de restauração do agente: restaura uma amostra real do snapshot mais recente,
confere tamanho/SHA-256 e devolve a evidência. O resultado fica em agent_restore_tests
(também chega pelo inventário) e alimenta os relatórios REP-09 (Restaurações e Testes) e
REP-10 (Prontidão para DR).

Rotas (/api/v1/restore-tests):
  GET    ""                       resultados (filtros: days, agent_id)
  GET    /{agent_id}/{ext_id}     detalhe com a lista de arquivos conferidos
  POST   /run                     executa agora {agent_id, repository_id?} (em segundo plano)
  GET|POST /schedules, PUT|DELETE /schedules/{id}, POST /schedules/{id}/run
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("gboc_restore_tests")
router = APIRouter(prefix="/api/v1/restore-tests", tags=["Testes de restauração"])

SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS agent_restore_tests (
        id SERIAL PRIMARY KEY,
        agent_id VARCHAR(255) NOT NULL,
        ext_id INTEGER NOT NULL,
        repository_id TEXT,
        repository_name TEXT,
        engine TEXT,
        task_name TEXT,
        snapshot_id TEXT,
        snapshot_time TEXT,
        status VARCHAR(20),
        files_tested INTEGER,
        files_ok INTEGER,
        files_hash_verified INTEGER,
        bytes_restored BIGINT,
        duration_seconds DOUBLE PRECISION,
        error_message TEXT,
        evidence_hash TEXT,
        details JSONB,
        triggered_by TEXT,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        synced_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
        UNIQUE (agent_id, ext_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_agent_restore_tests_started ON agent_restore_tests(started_at DESC)",
    """CREATE TABLE IF NOT EXISTS restore_test_schedules (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        repository_id TEXT,
        frequency VARCHAR(10) NOT NULL DEFAULT 'weekly',
        hour SMALLINT NOT NULL DEFAULT 2,
        minute SMALLINT NOT NULL DEFAULT 0,
        weekday SMALLINT DEFAULT 6,
        day_of_month SMALLINT DEFAULT 1,
        sample_size INTEGER NOT NULL DEFAULT 5,
        max_file_mb INTEGER NOT NULL DEFAULT 100,
        enabled BOOLEAN DEFAULT TRUE,
        created_by TEXT,
        created_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
        last_run_at TIMESTAMP,
        last_status TEXT,
        last_error TEXT
    )""",
]
_ready = False
_lock = threading.Lock()
_running: Dict[str, float] = {}
_last_runs: Dict[str, Dict[str, Any]] = {}  # último resultado por agente (inclui erros de comunicação)           # agent_id → início (evita testes simultâneos no mesmo agente)
_loop: Optional[asyncio.AbstractEventLoop] = None


def _db_exec(sql: str, params: Any = (), fetch: bool = True) -> List[Dict[str, Any]]:
    from modules.reports.report_schedules import _exec as rexec
    return rexec(sql, params, fetch)


def ensure_schema() -> None:
    global _ready
    if _ready:
        return
    with _lock:
        if not _ready:
            for sql in SCHEMA_SQL:
                _db_exec(sql, fetch=False)
            _ready = True


def _ts(v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    return str(v).replace("T", " ")[:26]


def store_results(conn, agent_id: str, tests: List[Dict[str, Any]]) -> int:
    """Grava/atualiza resultados vindos do agente (resposta direta ou inventário). Usa a conexão recebida."""
    from psycopg2.extras import execute_values
    rows = []
    for t in tests or []:
        try:
            ext = int(t.get("id") if t.get("id") is not None else t.get("ext_id"))
        except (TypeError, ValueError):
            continue
        rows.append((agent_id, ext, str(t.get("repository_id") or ""), t.get("repository_name"), t.get("engine"), t.get("task_name"),
                     t.get("snapshot_id"), t.get("snapshot_time"), t.get("status"), t.get("files_tested"), t.get("files_ok"),
                     t.get("files_hash_verified"), t.get("bytes_restored"), t.get("duration_seconds"),
                     (t.get("error_message") or None) and str(t.get("error_message"))[:2000], t.get("evidence_hash"),
                     json.dumps(t.get("details") or [], ensure_ascii=False, default=str), t.get("triggered_by"),
                     _ts(t.get("started_at")) or _ts(t.get("completed_at")) or datetime.now().isoformat(sep=" "),
                     _ts(t.get("completed_at"))))
    if not rows:
        return 0
    cur = conn.cursor()
    execute_values(cur, """
        INSERT INTO agent_restore_tests (agent_id, ext_id, repository_id, repository_name, engine, task_name, snapshot_id,
            snapshot_time, status, files_tested, files_ok, files_hash_verified, bytes_restored, duration_seconds, error_message,
            evidence_hash, details, triggered_by, started_at, completed_at)
        VALUES %s ON CONFLICT (agent_id, ext_id) DO UPDATE SET status=EXCLUDED.status, snapshot_id=EXCLUDED.snapshot_id,
            snapshot_time=EXCLUDED.snapshot_time, files_tested=EXCLUDED.files_tested, files_ok=EXCLUDED.files_ok,
            files_hash_verified=EXCLUDED.files_hash_verified, bytes_restored=EXCLUDED.bytes_restored,
            duration_seconds=EXCLUDED.duration_seconds, error_message=EXCLUDED.error_message, evidence_hash=EXCLUDED.evidence_hash,
            details=EXCLUDED.details, completed_at=EXCLUDED.completed_at, started_at=EXCLUDED.started_at,
            synced_at=LOCALTIMESTAMP
    """, rows, template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)")
    cur.close()
    return len(rows)


def _store_one(agent_id: str, test: Dict[str, Any]) -> None:
    from database import db_manager
    conn = db_manager.get_connection()
    try:
        store_results(conn, agent_id, [test])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db_manager.release_connection(conn)


def _agent_repos(agent_id: str) -> List[Dict[str, Any]]:
    return _db_exec("""SELECT repo_id, name, engine FROM agent_repositories WHERE agent_id=%s AND removed_at IS NULL
                       AND COALESCE(status,'active') IN ('active','ready') ORDER BY repo_id""", (agent_id,))


async def run_for_agent(agent_id: str, repository_id: Optional[str] = None, sample_size: int = 5, max_file_mb: int = 100,
                        triggered_by: str = "server:manual") -> Dict[str, Any]:
    """Executa o teste no agente (um ou todos os repositórios). Retorna o resumo por repositório."""
    from modules.agents.remote_mgmt import agent_call
    if agent_id in _running and time.time() - _running[agent_id] < 3 * 3600:
        raise RuntimeError("Já existe um teste de restauração em andamento neste agente")
    _running[agent_id] = time.time()
    try:
        await asyncio.to_thread(ensure_schema)
        repos = [{"repo_id": repository_id}] if repository_id else await asyncio.to_thread(_agent_repos, agent_id)
        if not repos:
            raise RuntimeError("Nenhum repositório conhecido deste agente (aguarde a sincronização do inventário)")
        out = []
        for rp in repos:
            res = await agent_call(agent_id, "POST", "api/agent-ops/restore-test",
                                   body={"repository_id": rp["repo_id"], "sample_size": sample_size, "max_file_mb": max_file_mb,
                                         "triggered_by": triggered_by}, timeout=1800.0)
            body = res.get("body") if isinstance(res.get("body"), dict) else {}
            if res["status_code"] == 404:
                out.append({"repository_id": rp["repo_id"], "status": "error", "comm": True,
                            "message": "Agente sem suporte a teste de restauração — atualize o GBOC Agent"})
                continue
            if res["status_code"] >= 400:
                out.append({"repository_id": rp["repo_id"], "status": "error", "comm": True,
                            "message": body.get("detail") or body.get("message") or f"HTTP {res['status_code']}"})
                continue
            test = body.get("test") or {}
            await asyncio.to_thread(_store_one, agent_id, test)
            out.append({"repository_id": rp["repo_id"], "repository_name": test.get("repository_name"),
                        "status": test.get("status"), "files_ok": test.get("files_ok"), "files_tested": test.get("files_tested"),
                        "message": test.get("error_message")})
        for r in out:
            if r.get("status") == "error":
                logger.warning(f"[TESTE-RESTORE] {agent_id} repositório {r.get('repository_id')}: {r.get('message')}")
        _last_runs[agent_id] = {"at": datetime.now().isoformat(sep=" ", timespec="seconds"), "results": out}
        return {"agent_id": agent_id, "results": out}
    finally:
        _running.pop(agent_id, None)


def _summary_status(results: List[Dict[str, Any]]) -> str:
    st = {r.get("status") for r in results}
    if st <= {"passed"}:
        return "passed"
    if "passed" in st or "partial" in st:
        return "partial"
    if st <= {"error"}:
        return "error"
    return "failed"


async def _run_schedule(s: Dict[str, Any]) -> Dict[str, Any]:
    try:
        res = await run_for_agent(s["agent_id"], s.get("repository_id") or None, int(s.get("sample_size") or 5),
                                  int(s.get("max_file_mb") or 100), f"server:schedule:{s['id']}")
        status = _summary_status(res["results"])
        msgs = "; ".join(f"{r.get('repository_name') or r.get('repository_id')}: {r.get('message')}" for r in res["results"]
                         if r.get("message"))
        await asyncio.to_thread(_db_exec, """UPDATE restore_test_schedules SET last_run_at=LOCALTIMESTAMP, last_status=%s,
                                              last_error=%s WHERE id=%s""", (status, msgs[:1000] or None, s["id"]), False)
        _notify_failure(s, status, res["results"])
        return {"status": status, **res}
    except Exception as e:
        await asyncio.to_thread(_db_exec, """UPDATE restore_test_schedules SET last_run_at=LOCALTIMESTAMP, last_status='error',
                                              last_error=%s WHERE id=%s""", (str(e)[:1000], s["id"]), False)
        _notify_failure(s, "error", [{"message": str(e)}])
        return {"status": "error", "message": str(e)}


def _notify_failure(s: Dict[str, Any], status: str, results: List[Dict[str, Any]]) -> None:
    """Teste reprovado gera alerta proativo (e-mail/Teams), se o módulo de alertas estiver ativo."""
    if status == "passed":
        try:
            from modules.alerts.proactive_alerts import resolve_external
            resolve_external("restore_test_failed", f"{s['agent_id']}:{s['id']}")
        except Exception as e:
            logger.debug(f"encerramento do alerta de teste de restauração: {e}")
        return
    try:
        from modules.alerts.proactive_alerts import raise_external_alert
        label = {"passed": "aprovado", "partial": "parcial", "failed": "reprovado", "error": "não executado"}
        detail = "; ".join(f"{r.get('repository_name') or r.get('repository_id') or 'agente'}: "
                           f"{label.get(r.get('status'), r.get('status') or 'erro')}"
                           + (f" — {r.get('message')}" if r.get("message") else "") for r in results)[:600]
        raise_external_alert("restore_test_failed", f"{s['agent_id']}:{s['id']}", s["agent_id"], "critical",
                             f"Teste de restauração {('reprovado' if status != 'error' else 'não executado')}: {s.get('name')}",
                             detail)
    except Exception as e:
        logger.debug(f"alerta de teste de restauração: {e}")


def _due(s: Dict[str, Any], now: datetime) -> bool:
    from modules.reports.report_schedules import next_run
    prev = next_run(s, after=now - timedelta(days=32))
    while True:
        nxt = next_run(s, after=prev)
        if nxt > now:
            break
        prev = nxt
    created = s.get("created_at") or now
    last = s.get("last_run_at")
    return prev <= now and prev >= created and (now - prev) < timedelta(hours=6) and (last is None or last < prev)


async def scheduler_loop() -> None:
    await asyncio.sleep(90)
    while True:
        try:
            await asyncio.to_thread(ensure_schema)
            now = datetime.now()
            rows = await asyncio.to_thread(_db_exec, "SELECT * FROM restore_test_schedules WHERE enabled = TRUE")
            for s in rows:
                if _due(s, now) and s["agent_id"] not in _running:
                    asyncio.create_task(_run_schedule(s))
        except Exception as e:
            logger.warning(f"[TESTE-RESTORE] Verificação de agendamentos falhou: {e}")
        await asyncio.sleep(60)


def start_scheduler() -> None:
    """Chamado no lifespan do Server (event loop ativo)."""
    global _loop
    _loop = asyncio.get_event_loop()
    _loop.create_task(scheduler_loop())


def _serialize(s: Dict[str, Any]) -> Dict[str, Any]:
    from modules.reports.report_schedules import _describe, next_run
    out = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in s.items()}
    out["description"] = _describe(s)
    out["next_run_at"] = next_run(s).isoformat() if s.get("enabled") else None
    return out


def _validate(body: Dict[str, Any]) -> Dict[str, Any]:
    from modules.reports.report_schedules import FREQS
    agent_id = str(body.get("agent_id") or "").strip()
    if not agent_id:
        raise HTTPException(400, "Selecione o agente.")
    freq = body.get("frequency") or "weekly"
    if freq not in FREQS:
        raise HTTPException(400, "Frequência inválida (daily, weekly ou monthly).")
    try:
        hour, minute = int(body.get("hour", 2)), int(body.get("minute", 0))
        sample, maxmb = int(body.get("sample_size", 5)), int(body.get("max_file_mb", 100))
    except (TypeError, ValueError):
        raise HTTPException(400, "Valores inválidos.")
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 1 <= sample <= 50 and 1 <= maxmb <= 5000):
        raise HTTPException(400, "Horário, amostra (1–50) ou tamanho máximo (1–5000 MB) fora do intervalo.")
    return {"name": (body.get("name") or f"Teste de restauração — {agent_id}")[:200], "agent_id": agent_id,
            "repository_id": (str(body.get("repository_id")) if body.get("repository_id") not in (None, "") else None),
            "frequency": freq, "hour": hour, "minute": minute, "weekday": int(body.get("weekday") or 0) % 7,
            "day_of_month": max(1, min(28, int(body.get("day_of_month") or 1))), "sample_size": sample, "max_file_mb": maxmb,
            "enabled": bool(body.get("enabled", True))}


def _user(request: Request) -> str:
    u = getattr(request.state, "user", None) or {}
    return (u.get("username") if isinstance(u, dict) else None) or "?"


def _require_operator(request: Request) -> None:
    role = (((getattr(request.state, "user", None) or {}).get("role")) or "").lower()
    if role and role not in ("admin", "superadmin", "administrator", "operator"):
        raise HTTPException(403, "Seu perfil não pode executar testes de restauração (requer admin ou operator).")


@router.get("")
async def list_results(days: int = 90, agent_id: Optional[str] = None, limit: int = 300):
    await asyncio.to_thread(ensure_schema)
    params: List[Any] = [datetime.now() - timedelta(days=max(1, min(days, 730)))]
    cl = ""
    if agent_id:
        cl = " AND t.agent_id = %s"
        params.append(agent_id)
    params.append(max(1, min(limit, 2000)))
    rows = await asyncio.to_thread(_db_exec, f"""
        SELECT t.agent_id, a.hostname, t.ext_id, t.repository_id, t.repository_name, t.engine, t.task_name, t.snapshot_id,
               t.snapshot_time, t.status, t.files_tested, t.files_ok, t.files_hash_verified, t.bytes_restored, t.duration_seconds,
               t.error_message, t.evidence_hash, t.triggered_by, t.started_at, t.completed_at
        FROM agent_restore_tests t LEFT JOIN agents a ON a.agent_id = t.agent_id
        WHERE t.started_at >= %s {cl} ORDER BY t.started_at DESC LIMIT %s""", tuple(params))
    out = [{k: (v.isoformat(sep=" ") if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in rows]
    return {"status": "success", "tests": out, "running": sorted(_running),
            "last_runs": {k: v for k, v in _last_runs.items() if not agent_id or k == agent_id}}


@router.get("/schedules")
async def list_schedules():
    await asyncio.to_thread(ensure_schema)
    rows = await asyncio.to_thread(_db_exec, """SELECT s.*, a.hostname FROM restore_test_schedules s
                                                LEFT JOIN agents a ON a.agent_id = s.agent_id ORDER BY s.id""")
    return {"status": "success", "schedules": [_serialize(r) for r in rows]}


@router.post("/schedules")
async def create_schedule(request: Request):
    _require_operator(request)
    v = _validate(await request.json() or {})
    await asyncio.to_thread(ensure_schema)
    rows = await asyncio.to_thread(_db_exec, """
        INSERT INTO restore_test_schedules (name, agent_id, repository_id, frequency, hour, minute, weekday, day_of_month,
            sample_size, max_file_mb, enabled, created_by)
        VALUES (%(name)s, %(agent_id)s, %(repository_id)s, %(frequency)s, %(hour)s, %(minute)s, %(weekday)s, %(day_of_month)s,
            %(sample_size)s, %(max_file_mb)s, %(enabled)s, %(created_by)s) RETURNING *""", {**v, "created_by": _user(request)})
    return {"status": "success", "schedule": _serialize(rows[0])}


@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, request: Request):
    _require_operator(request)
    v = _validate(await request.json() or {})
    rows = await asyncio.to_thread(_db_exec, """
        UPDATE restore_test_schedules SET name=%(name)s, agent_id=%(agent_id)s, repository_id=%(repository_id)s,
            frequency=%(frequency)s, hour=%(hour)s, minute=%(minute)s, weekday=%(weekday)s, day_of_month=%(day_of_month)s,
            sample_size=%(sample_size)s, max_file_mb=%(max_file_mb)s, enabled=%(enabled)s WHERE id=%(id)s RETURNING *""",
        {**v, "id": schedule_id})
    if not rows:
        raise HTTPException(404, "Agendamento não encontrado.")
    return {"status": "success", "schedule": _serialize(rows[0])}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int, request: Request):
    _require_operator(request)
    await asyncio.to_thread(_db_exec, "DELETE FROM restore_test_schedules WHERE id=%s", (schedule_id,), False)
    return {"status": "success"}


@router.post("/schedules/{schedule_id}/run")
async def run_schedule_now(schedule_id: int, request: Request):
    _require_operator(request)
    rows = await asyncio.to_thread(_db_exec, "SELECT * FROM restore_test_schedules WHERE id=%s", (schedule_id,))
    if not rows:
        raise HTTPException(404, "Agendamento não encontrado.")
    if rows[0]["agent_id"] in _running:
        raise HTTPException(409, "Já existe um teste em andamento neste agente.")
    asyncio.create_task(_run_schedule(rows[0]))
    return {"status": "started", "message": "Teste iniciado no agente. O resultado aparece na lista ao terminar."}


@router.post("/run")
async def run_now(request: Request):
    _require_operator(request)
    b = await request.json() or {}
    agent_id = str(b.get("agent_id") or "").strip()
    if not agent_id:
        raise HTTPException(400, "Informe o agente.")
    if agent_id in _running:
        raise HTTPException(409, "Já existe um teste em andamento neste agente.")
    who = _user(request)

    async def _go():
        try:
            res = await run_for_agent(agent_id, b.get("repository_id") or None, int(b.get("sample_size") or 5),
                                      int(b.get("max_file_mb") or 100), f"server:manual:{who}")
            st = _summary_status(res["results"])
            if st != "passed":
                _notify_failure({"agent_id": agent_id, "id": "manual", "name": "execução manual"}, st, res["results"])
        except Exception as e:
            logger.warning(f"[TESTE-RESTORE] {agent_id}: {e}")
    asyncio.create_task(_go())
    return {"status": "started", "message": "Teste iniciado no agente. O resultado aparece na lista ao terminar."}


@router.get("/{agent_id}/{ext_id}")
async def get_detail(agent_id: str, ext_id: int):
    rows = await asyncio.to_thread(_db_exec, """SELECT t.*, a.hostname FROM agent_restore_tests t LEFT JOIN agents a
                                                ON a.agent_id = t.agent_id WHERE t.agent_id=%s AND t.ext_id=%s""", (agent_id, ext_id))
    if not rows:
        raise HTTPException(404, "Teste não encontrado.")
    r = {k: (v.isoformat(sep=" ") if hasattr(v, "isoformat") else v) for k, v in rows[0].items()}
    return {"status": "success", "test": r}
