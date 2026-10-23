#!/usr/bin/env python3
"""
GBOC — Guarda de execuções de backup (tratamento de backup interrompido)

O Agente (API) e o Agendador são processos separados e os dois executam backups. Antes, ao iniciar,
cada processo marcava TODA execução em 'running' como interrompida — inclusive o backup que o outro
processo estava fazendo — e, se um processo morresse sem reiniciar, a execução ficava 'running' para sempre.

Agora cada execução tem DONO e SINAL DE VIDA:
  - owner_host / owner_pid : processo que executa o backup (gravado ao entrar na fila);
  - heartbeat_at           : renovado a cada 30 s por esse processo, independente do motor informar progresso;
  - engine_pid             : processo do motor (restic/kopia/duplicati) em execução.

Uma execução ativa é marcada como 'interrupted' SOMENTE quando:
  1. o processo dono (mesmo computador) não existe mais; ou
  2. está sem sinal de vida há mais de GBOC_EXEC_STALE_SECONDS (padrão 10 min) — processo travado/encerrado;
  3. execução sem dono (versão anterior) cujo início passou desse mesmo limite.
Ao interromper: encerra o motor órfão (que continuaria gravando no repositório), devolve a tarefa para 'idle',
registra o erro e dispara os alertas configurados. A marcação é atômica (WHERE status ativo), então só
um processo age sobre cada execução.

Auto-Retry (opções da tarefa, antes só gravadas): depois de 'failed' ou 'interrupted', se a tarefa tiver
retry_enabled, dispara nova tentativa após retry_delay_minutes, até retry_max_attempts tentativas extras.
A reserva em scheduler_fires ('retry:<execução>') impede que os dois processos disparem a mesma tentativa.
"""
import logging
import os
import socket
import threading
import time
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger("ExecutionGuard")

HEARTBEAT_S = 30
STALE_S = max(60, int(os.environ.get("GBOC_EXEC_STALE_SECONDS", "600") or 600))
LOOP_S = max(5, int(os.environ.get("GBOC_EXEC_GUARD_LOOP_SECONDS", "60") or 60))
ACTIVE = ("running", "preparing", "queued")
_HOST = (socket.gethostname() or "").lower()
_ENGINE_PROCS = ("restic", "kopia", "duplicati", "rclone")


def _as_dt(v) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None) if v.tzinfo is None else v.astimezone().replace(tzinfo=None)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d.astimezone().replace(tzinfo=None) if d.tzinfo else d
    except Exception:
        return None


def _proc(pid) -> Optional[Any]:
    try:
        import psutil
        return psutil.Process(int(pid)) if pid and psutil.pid_exists(int(pid)) else None
    except Exception:
        return None


def _python_alive(pid) -> bool:
    """O dono é um processo Python do GBOC vivo? (PID reaproveitado por outro programa = morto)"""
    p = _proc(pid)
    if p is None:
        return False
    try:
        return "python" in (p.name() or "").lower()
    except Exception:
        return True   # sem permissão para ler o nome: assume vivo (conservador)


class ExecutionGuard:
    def __init__(self, task_manager):
        self.tm = task_manager
        self.core = task_manager.core
        self._owned = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._schema_ok = self._ensure_schema()

    # ── esquema ────────────────────────────────────────────────────────────────
    def _ensure_schema(self) -> bool:
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""SELECT column_name FROM information_schema.columns
                               WHERE table_name = 'task_executions' AND table_schema = current_schema()""")
                have = {r[0] for r in cur.fetchall()}
                need = [(c, t) for c, t in (("owner_host", "TEXT"), ("owner_pid", "INTEGER"),
                                            ("heartbeat_at", "TIMESTAMP"), ("engine_pid", "INTEGER")) if c not in have]
                # ALTER só quando falta coluna: pede trava exclusiva e o outro processo pode estar no meio de um backup
                for col, typ in need:
                    cur.execute(f"ALTER TABLE task_executions ADD COLUMN IF NOT EXISTS {col} {typ}")
                conn.commit()
            return True
        except Exception as e:
            logger.warning(f"[GUARD] Colunas de dono/sinal de vida indisponíveis: {e}")
            return False

    # ── dono + sinal de vida ───────────────────────────────────────────────────
    def own(self, execution_id) -> None:
        if not execution_id:
            return
        with self._lock:
            self._owned.add(int(execution_id))
        self._beat([int(execution_id)])

    def release(self, execution_id) -> None:
        with self._lock:
            self._owned.discard(int(execution_id or 0))

    def _beat(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids or not self._schema_ok:
            return
        cur_id = getattr(self.tm, "_current_execution_id", None)
        cur_proc = getattr(self.tm, "_current_process", None)
        eng_pid = None
        try:
            if cur_proc is not None and cur_proc.poll() is None:
                eng_pid = cur_proc.pid
        except Exception:
            eng_pid = None
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE task_executions SET owner_host = %s, owner_pid = %s, heartbeat_at = %s
                    WHERE id = ANY(%s) AND status IN ('running', 'preparing', 'queued')
                """, (_HOST, os.getpid(), datetime.now(), ids))
                if eng_pid and cur_id in ids:
                    cur.execute("UPDATE task_executions SET engine_pid = %s WHERE id = %s", (eng_pid, cur_id))
                conn.commit()
        except Exception as e:
            logger.debug(f"[GUARD] sinal de vida não gravado: {e}")

    # ── interrupção ───────────────────────────────────────────────────────────
    def _dead_reason(self, row: Dict[str, Any], now: datetime) -> Optional[str]:
        owner_pid, owner_host = row.get("owner_pid"), (row.get("owner_host") or "").lower()
        if owner_pid and owner_host == _HOST and int(owner_pid) != os.getpid() and not _python_alive(owner_pid):
            return f"Backup interrompido: o processo do GBOC que o executava (PID {owner_pid}) foi encerrado"
        hb = _as_dt(row.get("heartbeat_at"))
        ref = hb or _as_dt(row.get("started_at"))
        if ref is None:
            return None
        age = (now - ref).total_seconds()
        if age <= STALE_S:
            return None
        if hb is None:
            return (f"Backup interrompido: execução sem sinal de vida desde o início "
                    f"({int(age // 60)} min) — processo encerrado ou versão anterior do GBOC")
        return f"Backup interrompido: sem sinal de vida há {int(age // 60)} min (processo travado ou encerrado)"

    def _kill_orphan_engine(self, row: Dict[str, Any]) -> Optional[str]:
        """Motor (restic/kopia/duplicati) que ficou rodando sem o GBOC continuaria gravando no repositório
        e disputaria a trava com a próxima tentativa."""
        if (row.get("owner_host") or "").lower() not in ("", _HOST):
            return None
        p = _proc(row.get("engine_pid"))
        if p is None:
            return None
        try:
            name = (p.name() or "").lower()
            if not name.startswith(_ENGINE_PROCS):
                return None
            for ch in p.children(recursive=True):
                try:
                    ch.kill()
                except Exception:
                    pass
            p.kill()
            return f"{name} (PID {p.pid}) encerrado"
        except Exception as e:
            return f"não foi possível encerrar o motor órfão: {e}"

    def reap(self, startup: bool = False) -> int:
        """Marca como interrompidas as execuções ativas sem dono vivo. Retorna quantas marcou."""
        if not self._schema_ok:
            return 0
        now = datetime.now()
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT te.id, te.task_id, te.status, te.started_at, te.owner_host, te.owner_pid,
                           te.heartbeat_at, te.engine_pid, t.name, COALESCE(t.engine, '')
                    FROM task_executions te LEFT JOIN tasks t ON t.id = te.task_id
                    WHERE te.status IN ('running', 'preparing', 'queued')
                """)
                cols = ["id", "task_id", "status", "started_at", "owner_host", "owner_pid",
                        "heartbeat_at", "engine_pid", "task_name", "engine"]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception as e:
            logger.debug(f"[GUARD] verificação de execuções indisponível: {e}")
            return 0
        with self._lock:
            mine = set(self._owned)
        done = 0
        for row in rows:
            if int(row["id"]) in mine:
                continue
            reason = self._dead_reason(row, now)
            if not reason:
                continue
            killed = self._kill_orphan_engine(row)
            msg = reason + (f"; motor órfão {killed}" if killed else "")
            if self._mark_interrupted(row, msg, now):
                done += 1
        if done:
            logger.warning(f"[GUARD] {done} execução(ões) interrompida(s) tratada(s)"
                           f"{' na inicialização' if startup else ''}")
        return done

    def _mark_interrupted(self, row: Dict[str, Any], msg: str, now: datetime) -> bool:
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE task_executions SET status = 'interrupted', error_message = %s, completed_at = %s
                    WHERE id = %s AND status IN ('running', 'preparing', 'queued')
                """, (msg, now.isoformat(), row["id"]))
                if not (cur.rowcount or 0):
                    conn.rollback()
                    return False          # outro processo já tratou (ou o backup terminou agora)
                cur.execute("""
                    UPDATE tasks SET status = 'idle', last_status = 'interrupted', last_run = %s
                    WHERE id = %s AND NOT EXISTS (
                        SELECT 1 FROM task_executions WHERE task_id = %s AND id <> %s
                          AND status IN ('running', 'preparing', 'queued'))
                """, (now.isoformat(), row["task_id"], row["task_id"], row["id"]))
                conn.commit()
        except Exception as e:
            logger.error(f"[GUARD] falha ao marcar execução {row.get('id')} como interrompida: {e}")
            return False
        logger.warning(f"[GUARD] Execução {row['id']} (tarefa {row.get('task_name') or row['task_id']}): {msg}")
        try:   # erro na tela de tarefas + alertas/notificações configurados
            self.tm._register_task_error(row["task_id"], row["id"], row.get("task_name") or f"Task {row['task_id']}",
                                         (row.get("engine") or "unknown"), msg)
        except Exception as e:
            logger.debug(f"[GUARD] alerta de interrupção não enviado: {e}")
        return True

    # ── Auto-Retry ────────────────────────────────────────────────────────────
    def retry_pass(self) -> int:
        now = datetime.now()
        try:
            with self.core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, name, COALESCE(retry_max_attempts, 3), COALESCE(retry_delay_minutes, 5)
                    FROM tasks
                    WHERE retry_enabled = TRUE AND COALESCE(enabled, TRUE) = TRUE
                """)
                tasks = cur.fetchall()
                plans = []
                for task_id, name, max_att, delay_min in tasks:
                    cur.execute("""SELECT id, status, completed_at FROM task_executions
                                   WHERE task_id = %s ORDER BY id DESC LIMIT %s""", (task_id, int(max_att) + 2))
                    ex = cur.fetchall()
                    if not ex or ex[0][1] not in ("failed", "interrupted"):
                        continue
                    if any(s in ACTIVE for _, s, _ in ex):
                        continue
                    fails = 0
                    for _, s, _ in ex:
                        if s in ("failed", "interrupted"):
                            fails += 1
                        else:
                            break
                    if fails > int(max_att):          # 1ª falha + N tentativas extras esgotadas
                        continue
                    done_at = _as_dt(ex[0][2])
                    if done_at and (now - done_at).total_seconds() < int(delay_min) * 60:
                        continue
                    plans.append((task_id, name, ex[0][0], fails, int(max_att)))
                fired = []
                for task_id, name, last_exec, fails, max_att in plans:
                    try:
                        cur.execute("""CREATE TABLE IF NOT EXISTS scheduler_fires (
                                         task_id TEXT NOT NULL, slot TEXT NOT NULL,
                                         fired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (task_id, slot))""")
                        cur.execute("INSERT INTO scheduler_fires (task_id, slot) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                                    (str(task_id), f"retry:{last_exec}"))
                        if (cur.rowcount or 0) > 0:
                            fired.append((task_id, name, fails, max_att))
                        conn.commit()
                    except Exception:
                        conn.rollback()
        except Exception as e:
            logger.debug(f"[GUARD] auto-retry indisponível: {e}")
            return 0
        for task_id, name, fails, max_att in fired:
            res = self.tm.trigger_task(task_id)
            logger.warning(f"[AUTO-RETRY] Tarefa {name}: nova tentativa {fails}/{max_att} "
                           f"após falha/interrupção -> {res.get('status')} (exec {res.get('execution_id')})")
        return len(fired)

    # ── laço ──────────────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="gboc-exec-guard", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        last_check = 0.0
        while not self._stop.wait(HEARTBEAT_S if LOOP_S >= HEARTBEAT_S else LOOP_S):
            with self._lock:
                ids = list(self._owned)
            self._beat(ids)
            if time.time() - last_check >= LOOP_S:
                last_check = time.time()
                try:
                    self.reap()
                    self.retry_pass()
                except Exception as e:
                    logger.debug(f"[GUARD] ciclo: {e}")
