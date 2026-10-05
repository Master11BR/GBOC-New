"""
GBOC Server — Central de falhas (agentes + o próprio servidor), a partir de dados reais.

Antes a tela "Jobs com Falha" lia uma lista em memória alimentada por uma rota que nenhum agente chamava,
e mostrava sempre 0. Agora as falhas vêm do banco:

  Agentes
    * backup        — tarefas cuja execução falhou (agent_task_executions / agent_tasks.last_status /
                      backup_reports de agentes antigos), com falhas seguidas, primeira/última falha,
                      se já se recuperou e as tentativas/escalação informadas pelo agente (agent_job_failures)
    * restore_test  — testes de restauração reprovados (agent_restore_tests)
    * verification  — verificações de integridade com falha (agent_verifications)
    * restore       — restaurações com falha (agent_restore_history)
    * agent_auth    — agente rejeitado pelo servidor (chave de pareamento inválida): ele não sincroniza nada
  Servidor
    * report_schedule / restore_test_schedule — agendamentos do servidor com erro
    * fleet_job      — operações em lote com agentes que falharam
    * notification   — alerta que não pôde ser enviado (SMTP/webhook)
    * server_error   — erros registrados nos logs do próprio servidor
    * server_module  — módulo do servidor que não carregou (a tela correspondente responde "Not Found")

Uma falha "reconhecida" some das ativas até ocorrer uma falha mais nova do mesmo item.
"""
from __future__ import annotations

import json
import zlib
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("gboc.failures")

FAIL_SQL = "(LOWER(COALESCE({c},'')) LIKE 'fail%%' OR LOWER(COALESCE({c},'')) IN ('error','erro','falha','failure','aborted','timeout'))"
OK_SQL = "(LOWER(COALESCE({c},'')) IN ('completed','success','succeeded','ok','passed','done','sent'))"
FAILED_MODULES: Dict[str, str] = {}          # preenchido pelo server_gboc ao carregar os routers
_ready = False
_rej_lock = threading.Lock()
_rej_pending: Dict[Tuple[str, str], Dict[str, Any]] = {}
_rej_last_flush = 0.0


def _exec(sql: str, params: tuple = (), fetch: bool = True) -> List[Dict[str, Any]]:
    from modules.reports.report_schedules import _exec as ex
    return ex(sql, params, fetch)


def _safe(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        return _exec(sql, params)
    except Exception as e:
        logger.debug(f"[FALHAS] consulta ignorada: {e}")
        return []


def ensure_schema() -> None:
    global _ready
    if _ready:
        return
    _exec("""CREATE TABLE IF NOT EXISTS failure_acks (
                 key TEXT PRIMARY KEY, acked_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP, acked_by TEXT, note TEXT)""", fetch=False)
    _exec("""CREATE TABLE IF NOT EXISTS agent_auth_rejections (
                 agent_id VARCHAR(100) NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '', path TEXT, count INTEGER NOT NULL DEFAULT 0,
                 first_seen TIMESTAMP, last_seen TIMESTAMP, PRIMARY KEY (agent_id, ip))""", fetch=False)
    _ready = True


# ───────────────────────── agentes rejeitados (chamado pelo auth_guard) ─────────────────────────

def note_rejection(agent_id: Optional[str], ip: Optional[str], path: str) -> None:
    """Registra (em lote, no máx. 1 gravação a cada 30 s) que um agente foi rejeitado por chave inválida."""
    global _rej_last_flush
    k = ((agent_id or "")[:100], ip or "")
    now = datetime.now()
    with _rej_lock:
        e = _rej_pending.setdefault(k, {"count": 0, "first": now, "path": path})
        e["count"] += 1
        e["last"], e["path"] = now, path
        if time.monotonic() - _rej_last_flush < 30:
            return
        _rej_last_flush = time.monotonic()
        batch = dict(_rej_pending)
        _rej_pending.clear()
    threading.Thread(target=_flush_rejections, args=(batch,), daemon=True).start()


def _flush_rejections(batch: Dict[Tuple[str, str], Dict[str, Any]]) -> None:
    try:
        ensure_schema()
        for (aid, ip), e in batch.items():
            _exec("""INSERT INTO agent_auth_rejections (agent_id, ip, path, count, first_seen, last_seen) VALUES (%s, %s, %s, %s, %s, %s)
                     ON CONFLICT (agent_id, ip) DO UPDATE SET count = agent_auth_rejections.count + EXCLUDED.count,
                         last_seen = EXCLUDED.last_seen, path = EXCLUDED.path,
                         first_seen = CASE WHEN agent_auth_rejections.last_seen < EXCLUDED.first_seen - INTERVAL '1 hour'
                                           THEN EXCLUDED.first_seen ELSE agent_auth_rejections.first_seen END""",
                  (aid, ip, e["path"], e["count"], e["first"], e["last"]), fetch=False)
    except Exception as ex:
        logger.debug(f"[FALHAS] rejeições não gravadas: {ex}")


# ───────────────────────── coleta ─────────────────────────

def _iso(v: Any) -> Optional[str]:
    return v.isoformat(sep=" ", timespec="seconds") if isinstance(v, datetime) else (str(v) if v else None)


def _agents(tenant_id: Optional[str]) -> Dict[str, Dict[str, Any]]:
    rows = _safe("SELECT agent_id, hostname, tenant_id, last_heartbeat FROM agents")
    return {r["agent_id"]: r for r in rows if not tenant_id or r.get("tenant_id") == tenant_id}


def _backup_failures(start: datetime, end: datetime, agent_ids: List[str]) -> List[Dict[str, Any]]:
    f, ok = FAIL_SQL.format(c="status"), OK_SQL.format(c="status")
    rows = _safe(f"""
        WITH keys AS (
            SELECT agent_id, task_id FROM agent_task_executions
             WHERE started_at >= %s AND started_at <= %s AND {f} AND agent_id = ANY(%s)
            UNION
            SELECT agent_id, task_id FROM agent_tasks
             WHERE {FAIL_SQL.format(c='last_status')} AND removed_at IS NULL AND agent_id = ANY(%s)
        ), last_ok AS (
            SELECT e.agent_id, e.task_id, MAX(e.started_at) AS t FROM agent_task_executions e JOIN keys k USING (agent_id, task_id)
             WHERE {ok.replace('status', 'e.status')} GROUP BY 1, 2
        ), agg AS (
            SELECT e.agent_id, e.task_id,
                   COUNT(*) FILTER (WHERE {f.replace('status', 'e.status')} AND e.started_at >= %s AND e.started_at <= %s) AS fails,
                   COUNT(*) FILTER (WHERE e.started_at >= %s AND e.started_at <= %s) AS runs,
                   COUNT(*) FILTER (WHERE {f.replace('status', 'e.status')} AND e.started_at > COALESCE(lo.t, '-infinity'::timestamp)) AS streak,
                   MIN(e.started_at) FILTER (WHERE {f.replace('status', 'e.status')} AND e.started_at > COALESCE(lo.t, '-infinity'::timestamp)) AS streak_start,
                   MAX(e.started_at) FILTER (WHERE {f.replace('status', 'e.status')}) AS last_fail,
                   lo.t AS last_ok
              FROM agent_task_executions e JOIN keys k USING (agent_id, task_id) LEFT JOIN last_ok lo USING (agent_id, task_id)
             GROUP BY e.agent_id, e.task_id, lo.t
        ), lastrun AS (
            SELECT DISTINCT ON (e.agent_id, e.task_id) e.agent_id, e.task_id, e.status, e.started_at, e.error_message, e.task_name, e.repository_name
              FROM agent_task_executions e JOIN keys k USING (agent_id, task_id)
             WHERE {f.replace('status', 'e.status')}
             ORDER BY e.agent_id, e.task_id, e.started_at DESC
        )
        SELECT k.agent_id, k.task_id, a.fails, a.runs, a.streak, a.streak_start, a.last_fail, a.last_ok,
               lr.error_message, COALESCE(lr.task_name, t.name) AS task_name, COALESCE(lr.repository_name, t.repository_name) AS repository_name,
               t.last_status, t.last_run, t.schedule_enabled, t.enabled
          FROM keys k LEFT JOIN agg a USING (agent_id, task_id) LEFT JOIN lastrun lr USING (agent_id, task_id)
          LEFT JOIN agent_tasks t ON t.agent_id = k.agent_id AND t.task_id = k.task_id""",
                 (start, end, agent_ids, agent_ids, start, end, start, end))
    jf = {(r["agent_id"], str(r["task_id"])): r for r in _safe(
        """SELECT DISTINCT ON (agent_id, task_id) agent_id, task_id, task_name, failure_reason, retry_count, max_retries, status, escalated,
                  first_failed_at, last_retried_at, resolved_at
             FROM agent_job_failures WHERE agent_id = ANY(%s) ORDER BY agent_id, task_id, COALESCE(last_retried_at, first_failed_at) DESC""",
        (agent_ids,))}
    out = []
    seen = set()
    for r in rows:
        key = (r["agent_id"], str(r["task_id"]))
        seen.add(key)
        j = jf.get(key) or {}
        last_fail = r.get("last_fail") or (r.get("last_run") if str(r.get("last_status") or "").lower().startswith("fail") else None)
        active = bool(r.get("streak")) or (not r.get("last_ok") and last_fail) or \
            (str(r.get("last_status") or "").lower().startswith("fail") and not r.get("runs"))
        out.append({"key": f"backup:{key[0]}:{key[1]}", "origin": "agent", "kind": "backup", "agent_id": r["agent_id"],
                    "title": r.get("task_name") or f"Tarefa {r['task_id']}", "subtitle": r.get("repository_name"),
                    "reason": r.get("error_message") or j.get("failure_reason") or "Execução com falha (sem mensagem do motor)",
                    "failures": int(r.get("fails") or 0), "consecutive": int(r.get("streak") or 0),
                    "first_failed_at": r.get("streak_start") or j.get("first_failed_at") or last_fail, "last_failed_at": last_fail,
                    "recovered_at": None if active else r.get("last_ok"), "active": bool(active),
                    "retry_count": j.get("retry_count"), "max_retries": j.get("max_retries"), "escalated": bool(j.get("escalated")),
                    "schedule_paused": r.get("schedule_enabled") is False})
    # falhas informadas pelo módulo de alertas do agente sem execução sincronizada
    for key, j in jf.items():
        if key in seen or (str(j.get("status") or "").lower() == "resolved") or j.get("resolved_at"):
            continue
        t = j.get("last_retried_at") or j.get("first_failed_at")
        if t and (t < start - timedelta(days=30)):
            continue
        out.append({"key": f"backup:{key[0]}:{key[1]}", "origin": "agent", "kind": "backup", "agent_id": key[0],
                    "title": j.get("task_name") or f"Tarefa {key[1]}", "reason": j.get("failure_reason"),
                    "failures": max(1, int(j.get("retry_count") or 0)), "consecutive": max(1, int(j.get("retry_count") or 0)),
                    "first_failed_at": j.get("first_failed_at"), "last_failed_at": t, "active": True,
                    "retry_count": j.get("retry_count"), "max_retries": j.get("max_retries"), "escalated": bool(j.get("escalated"))})
    # agentes antigos (somente /backups/report)
    for r in _safe(f"""SELECT agent_id, COALESCE(NULLIF(source_path,''), backup_type, 'Backup') AS name, COUNT(*) AS fails,
                              MIN(start_time) AS first, MAX(start_time) AS last, (ARRAY_AGG(error_message ORDER BY start_time DESC))[1] AS err
                         FROM backup_reports b
                        WHERE start_time >= %s AND start_time <= %s AND {FAIL_SQL.format(c='status')} AND agent_id = ANY(%s)
                          AND NOT EXISTS (SELECT 1 FROM agent_task_executions x WHERE x.agent_id = b.agent_id)
                        GROUP BY 1, 2""", (start, end, agent_ids)):
        out.append({"key": f"legacy:{r['agent_id']}:{r['name']}", "origin": "agent", "kind": "backup", "agent_id": r["agent_id"],
                    "title": r["name"], "reason": r.get("err") or "Backup com falha", "failures": int(r["fails"]),
                    "consecutive": None, "first_failed_at": r["first"], "last_failed_at": r["last"], "active": True})
    return out


def _other_agent_failures(start: datetime, end: datetime, agent_ids: List[str]) -> List[Dict[str, Any]]:
    out = []
    for r in _safe(f"""SELECT agent_id, repository_name, COUNT(*) AS fails, MIN(started_at) AS first, MAX(started_at) AS last,
                              (ARRAY_AGG(COALESCE(error_message, '') ORDER BY started_at DESC))[1] AS err,
                              (ARRAY_AGG(status ORDER BY started_at DESC))[1] AS last_status,
                              MAX(started_at) FILTER (WHERE status = 'passed') AS last_ok
                         FROM agent_restore_tests WHERE started_at >= %s AND started_at <= %s AND agent_id = ANY(%s)
                         GROUP BY 1, 2 HAVING COUNT(*) FILTER (WHERE status IN ('failed', 'partial', 'error')) > 0""",
                   (start, end, agent_ids)):
        active = r["last_status"] in ("failed", "partial", "error")
        out.append({"key": f"restore_test:{r['agent_id']}:{r['repository_name']}", "origin": "agent", "kind": "restore_test",
                    "agent_id": r["agent_id"], "title": f"Teste de restauração — {r['repository_name'] or 'repositório'}",
                    "reason": r["err"] or ("Teste parcial: nem todos os arquivos conferiram" if r["last_status"] == "partial" else "Teste reprovado"),
                    "failures": int(r["fails"]), "first_failed_at": r["first"], "last_failed_at": r["last"], "active": active,
                    "recovered_at": None if active else r.get("last_ok")})
    for r in _safe(f"""SELECT agent_id, kind, subject, COUNT(*) AS fails, MIN(started_at) AS first, MAX(started_at) AS last,
                              (ARRAY_AGG(COALESCE(summary, '') ORDER BY started_at DESC))[1] AS err,
                              (ARRAY_AGG(status ORDER BY started_at DESC))[1] AS last_status
                         FROM agent_verifications WHERE started_at >= %s AND started_at <= %s AND agent_id = ANY(%s)
                         GROUP BY 1, 2, 3 HAVING COUNT(*) FILTER (WHERE {FAIL_SQL.format(c='status')} OR status = 'partial') > 0""",
                   (start, end, agent_ids)):
        active = str(r["last_status"] or "").lower() in ("failed", "partial", "error")
        out.append({"key": f"verification:{r['agent_id']}:{r['kind']}:{r['subject']}", "origin": "agent", "kind": "verification",
                    "agent_id": r["agent_id"], "title": f"Verificação ({r['kind'] or 'integridade'}) — {r['subject'] or ''}".strip(" —"),
                    "reason": r["err"] or "Verificação com erros", "failures": int(r["fails"]), "first_failed_at": r["first"],
                    "last_failed_at": r["last"], "active": active})
    for r in _safe(f"""SELECT agent_id, repository_name, COUNT(*) AS fails, MIN(created_at) AS first, MAX(created_at) AS last,
                              (ARRAY_AGG(COALESCE(error_message, '') ORDER BY created_at DESC))[1] AS err
                         FROM agent_restore_history WHERE created_at >= %s AND created_at <= %s AND agent_id = ANY(%s)
                          AND {FAIL_SQL.format(c='status')} GROUP BY 1, 2""", (start, end, agent_ids)):
        out.append({"key": f"restore:{r['agent_id']}:{r['repository_name']}", "origin": "agent", "kind": "restore",
                    "agent_id": r["agent_id"], "title": f"Restauração — {r['repository_name'] or 'repositório'}",
                    "reason": r["err"] or "Restauração com falha", "failures": int(r["fails"]), "first_failed_at": r["first"],
                    "last_failed_at": r["last"], "active": r["last"] >= datetime.now() - timedelta(days=1)})
    return out


def _auth_failures(agents: Dict[str, Dict[str, Any]], tenant_id: Optional[str]) -> List[Dict[str, Any]]:
    out = []
    for r in _safe("SELECT agent_id, ip, path, count, first_seen, last_seen FROM agent_auth_rejections WHERE last_seen >= %s",
                   (datetime.now() - timedelta(days=7),)):
        aid = r["agent_id"] or None
        if tenant_id and aid not in agents:
            continue
        active = r["last_seen"] >= datetime.now() - timedelta(minutes=15)
        out.append({"key": f"agent_auth:{r['agent_id']}:{r['ip']}", "origin": "agent", "kind": "agent_auth", "agent_id": aid,
                    "title": "Agente rejeitado pelo servidor (chave de pareamento)",
                    "subtitle": f"origem {r['ip']}" + ("" if aid else " · agente sem ID"),
                    "reason": "Chave de pareamento ausente ou inválida: o agente não consegue enviar heartbeat, tarefas, execuções nem logs. "
                              "Copie a chave em Configurações > Pareamento do Server para Configurações > Servidor Central no Agente.",
                    "failures": int(r["count"] or 0), "first_failed_at": r["first_seen"], "last_failed_at": r["last_seen"],
                    "active": active, "recovered_at": None if active else r["last_seen"]})
    return out


def _server_failures(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    out = []
    for name, err in FAILED_MODULES.items():
        out.append({"key": f"server_module:{name}", "origin": "server", "kind": "server_module", "agent_id": None,
                    "title": f"Módulo do servidor não carregado: {name}",
                    "reason": f"{err}. As telas que usam este módulo respondem 'Not Found'. Corrija e reinicie o serviço do Server.",
                    "failures": 1, "first_failed_at": None, "last_failed_at": None, "active": True})
    for r in _safe(f"""SELECT id, name, report_code, last_run_at, last_status, last_error, enabled FROM report_schedules
                        WHERE last_status IS NOT NULL AND NOT {OK_SQL.format(c='last_status')}"""):
        out.append({"key": f"report_schedule:{r['id']}", "origin": "server", "kind": "report_schedule", "agent_id": None,
                    "title": f"Envio agendado de relatório — {r['name'] or r['report_code']}",
                    "reason": r.get("last_error") or f"Status: {r['last_status']}", "failures": 1,
                    "first_failed_at": r["last_run_at"], "last_failed_at": r["last_run_at"], "active": bool(r.get("enabled", True))})
    for r in _safe(f"""SELECT id, name, agent_id, last_run_at, last_status, last_error, enabled FROM restore_test_schedules
                        WHERE last_status IS NOT NULL AND NOT {OK_SQL.format(c='last_status')} AND last_status NOT IN ('running', 'started')"""):
        out.append({"key": f"restore_test_schedule:{r['id']}", "origin": "server", "kind": "restore_test_schedule", "agent_id": r.get("agent_id"),
                    "title": f"Agendamento de teste de restauração — {r['name'] or r['id']}",
                    "reason": r.get("last_error") or f"Status: {r['last_status']}", "failures": 1,
                    "first_failed_at": r["last_run_at"], "last_failed_at": r["last_run_at"], "active": bool(r.get("enabled", True))})
    for r in _safe("""SELECT id, action, status, ok_count, fail_count, results, created_by, created_at, finished_at FROM fleet_batch_jobs
                       WHERE created_at >= %s AND created_at <= %s AND (COALESCE(fail_count, 0) > 0 OR LOWER(COALESCE(status, '')) IN ('failed', 'error'))""",
                   (start, end)):
        res = r.get("results") or {}
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except ValueError:
                res = {}
        lst = res if isinstance(res, list) else ([dict(v, agent_id=k) for k, v in res.items() if isinstance(v, dict)] if isinstance(res, dict) else [])
        errs = [f"{v.get('hostname') or v.get('agent_id')}: {v.get('message') or v.get('error')}" for v in lst
                if isinstance(v, dict) and (str(v.get('status')).lower() in ('error', 'failed') or v.get('ok') is False)][:5]
        out.append({"key": f"fleet_job:{r['id']}", "origin": "server", "kind": "fleet_job", "agent_id": None,
                    "title": f"Operação em lote — {r['action']} ({r['fail_count'] or 0} falha(s), {r['ok_count'] or 0} ok)",
                    "reason": "; ".join(errs) or f"Status: {r['status']}", "failures": int(r["fail_count"] or 1),
                    "first_failed_at": r["created_at"], "last_failed_at": r.get("finished_at") or r["created_at"],
                    "active": (r.get("finished_at") or r["created_at"]) >= datetime.now() - timedelta(hours=24)})
    # alertas que não puderam ser enviados — agrupados pelo erro do canal (um item por causa)
    for r in _safe("""SELECT last_notify_error AS err, COUNT(*) AS n, MIN(COALESCE(last_notified_at, first_seen)) AS first,
                             MAX(COALESCE(last_notified_at, last_seen)) AS last, (ARRAY_AGG(title ORDER BY last_seen DESC))[1:3] AS titles
                        FROM proactive_alert_events
                       WHERE status = 'open' AND last_notify_error IS NOT NULL AND last_notify_error <> ''
                       GROUP BY last_notify_error"""):
        out.append({"key": f"notification:{zlib.crc32(str(r['err']).encode())}", "origin": "server", "kind": "notification", "agent_id": None,
                    "title": f"Alertas não enviados ({r['n']} alerta(s) aberto(s))",
                    "subtitle": "; ".join(r.get("titles") or [])[:200],
                    "reason": f"{r['err']} — configure os canais em Alertas e Falhas > Alertas proativos > Regras e canais.",
                    "failures": int(r["n"]), "first_failed_at": r["first"], "last_failed_at": r["last"], "active": True})
    for r in _safe("""SELECT source, COUNT(*) AS n, MIN(timestamp) AS first, MAX(timestamp) AS last,
                             (ARRAY_AGG(LEFT(message, 400) ORDER BY timestamp DESC))[1] AS msg
                        FROM agent_logs WHERE agent_id IS NULL AND timestamp >= %s AND timestamp <= %s
                         AND (level ILIKE 'err%%' OR level ILIKE 'crit%%' OR level ILIKE 'fatal%%')
                       GROUP BY source ORDER BY MAX(timestamp) DESC LIMIT 50""", (start, end)):
        out.append({"key": f"server_error:{r['source']}", "origin": "server", "kind": "server_error", "agent_id": None,
                    "title": f"Erro no servidor — {str(r['source'] or '').replace('server.', '')}", "reason": r["msg"],
                    "failures": int(r["n"]), "first_failed_at": r["first"], "last_failed_at": r["last"],
                    "active": r["last"] >= datetime.now() - timedelta(hours=24)})
    return out


KIND_LABEL = {"backup": "Backup", "restore_test": "Teste de restauração", "verification": "Verificação", "restore": "Restauração",
              "agent_auth": "Conexão do agente", "report_schedule": "Relatório agendado", "restore_test_schedule": "Agendamento de teste",
              "fleet_job": "Operação em lote", "notification": "Notificação", "server_error": "Erro do servidor",
              "server_module": "Módulo do servidor"}


def collect(days: int = 30, start: Optional[str] = None, end: Optional[str] = None, agent_id: Optional[str] = None,
            tenant_id: Optional[str] = None, origin: Optional[str] = None, include_inactive: bool = True) -> Dict[str, Any]:
    ensure_schema()
    now = datetime.now()
    if start or end:
        t0 = datetime.strptime(start[:10], "%Y-%m-%d") if start else now - timedelta(days=days)
        t1 = (datetime.strptime(end[:10], "%Y-%m-%d") + timedelta(days=1) - timedelta(seconds=1)) if end else now
    else:
        t0 = now - timedelta(days=days) if days else datetime(1970, 1, 1)
        t1 = now
    agents = _agents(tenant_id)
    ids = [a for a in agents if not agent_id or agent_id == a]
    items: List[Dict[str, Any]] = []
    if origin in (None, "", "agent") and agent_id != "__server__":
        items += _backup_failures(t0, t1, ids) + _other_agent_failures(t0, t1, ids) + _auth_failures(agents, tenant_id)
        if agent_id:
            items = [i for i in items if i.get("agent_id") == agent_id]
    if origin in (None, "", "server") and not tenant_id and (not agent_id or agent_id == "__server__"):
        items += _server_failures(t0, t1)
    acks = {r["key"]: r for r in _safe("SELECT key, acked_at, acked_by, note FROM failure_acks")}
    for it in items:
        a = agents.get(it.get("agent_id")) or {}
        it["hostname"] = a.get("hostname") or (it.get("agent_id") or "Servidor central")
        it["kind_label"] = KIND_LABEL.get(it["kind"], it["kind"])
        ack = acks.get(it["key"])
        if ack and it.get("active") and (not it.get("last_failed_at") or ack["acked_at"] >= it["last_failed_at"]):
            it["active"] = False
            it["acknowledged"] = {"at": _iso(ack["acked_at"]), "by": ack.get("acked_by"), "note": ack.get("note")}
        it["status"] = "active" if it.get("active") else ("acknowledged" if it.get("acknowledged") else "recovered")
        for k in ("first_failed_at", "last_failed_at", "recovered_at"):
            it[k] = _iso(it.get(k))
    items = sorted(items, key=lambda i: str(i.get("last_failed_at") or ""), reverse=True)     # mais recente primeiro
    items = sorted(items, key=lambda i: 0 if i.get("active") else 1)                          # ativas no topo
    if not include_inactive:
        items = [i for i in items if i.get("active")]
    active = [i for i in items if i.get("active")]
    with_fail = [i for i in items if i["origin"] == "agent" and i["kind"] in ("backup", "restore_test")]
    recovered = [i for i in with_fail if i["status"] == "recovered"]
    esc = sum(1 for i in items if i.get("escalated"))
    esc += sum(int(r["n"] or 0) for r in _safe("""SELECT COUNT(*) AS n FROM proactive_alert_events
                                                    WHERE notify_count > 0 AND first_seen >= %s""", (t0,)))
    return {"period": {"start": _iso(t0), "end": _iso(t1)},
            "kpis": {"active": len(active), "active_agent": sum(1 for i in active if i["origin"] == "agent"),
                     "active_server": sum(1 for i in active if i["origin"] == "server"),
                     "agents_affected": len({i.get("agent_id") for i in active if i["origin"] == "agent" and i.get("agent_id")}),
                     "escalations": esc, "total": len(items),
                     "recovery_rate": round(len(recovered) / len(with_fail) * 100, 1) if with_fail else None},
            "failures": items}


def history(days: int = 30, agent_id: Optional[str] = None, tenant_id: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    """Execuções com falha (backup e teste de restauração), da mais recente para a mais antiga."""
    agents = _agents(tenant_id)
    ids = [a for a in agents if not agent_id or agent_id == a]
    t0 = datetime.now() - timedelta(days=days) if days else datetime(1970, 1, 1)
    rows = _safe(f"""SELECT 'backup' AS kind, e.agent_id, COALESCE(e.task_name, t.name) AS title, e.started_at AS at, e.error_message AS reason,
                            e.duration_seconds AS duration
                       FROM agent_task_executions e LEFT JOIN agent_tasks t ON t.agent_id = e.agent_id AND t.task_id = e.task_id
                      WHERE e.started_at >= %s AND {FAIL_SQL.format(c='e.status')} AND e.agent_id = ANY(%s)
                     UNION ALL
                     SELECT 'restore_test', agent_id, 'Teste de restauração — ' || COALESCE(repository_name, ''), started_at, error_message, duration_seconds
                       FROM agent_restore_tests WHERE started_at >= %s AND status IN ('failed', 'partial') AND agent_id = ANY(%s)
                     ORDER BY at DESC LIMIT %s""", (t0, ids, t0, ids, limit))
    for r in rows:
        r["hostname"] = (agents.get(r["agent_id"]) or {}).get("hostname") or r["agent_id"]
        r["kind_label"] = KIND_LABEL.get(r["kind"], r["kind"])
        r["at"] = _iso(r["at"])
    return rows


def acknowledge(key: str, user: Optional[str], note: Optional[str] = None) -> None:
    ensure_schema()
    _exec("""INSERT INTO failure_acks (key, acked_at, acked_by, note) VALUES (%s, LOCALTIMESTAMP, %s, %s)
             ON CONFLICT (key) DO UPDATE SET acked_at = LOCALTIMESTAMP, acked_by = EXCLUDED.acked_by, note = EXCLUDED.note""",
          (key, user, note), fetch=False)


def unacknowledge(key: str) -> None:
    ensure_schema()
    _exec("DELETE FROM failure_acks WHERE key = %s", (key,), fetch=False)
