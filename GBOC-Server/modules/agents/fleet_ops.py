"""
GBOC Server — Operações em lote na frota de agentes e atualização remota do GBOC Agent.

Ações em lote (vários agentes de uma vez, pelo mesmo canal do Gerenciamento Remoto):
  sync, run_tasks (todas ou por nome), pause_schedules, resume_schedules, stop_running,
  test_repositories, restore_test, update_agent.
Cada lote vira um "job" com resultado por agente (histórico em fleet_batch_jobs) e fica na auditoria.

Atualização do agente:
  * o Server publica um pacote ZIP do GBOC Agent — gerado da pasta Agent/GBOC-Agent instalada ao lado
    do Server ou enviado pelo administrador — com SHA-256;
  * o agente baixa o pacote pela rota de sincronização (/api/v1/sync/agent-update/package, chave de
    pareamento), confere o hash, aplica e reinicia o serviço; dados locais não são alterados.

Rotas: /api/v1/fleet/...
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

logger = logging.getLogger("gboc_fleet_ops")
router = APIRouter(tags=["Operações em lote"])

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPDATES_DIR = os.path.join(SERVER_DIR, "data", "agent_updates")
CURRENT_FILE = os.path.join(UPDATES_DIR, "current.json")
EXCLUDE_TOP = {"config", "data", "logs", "repositorios", "tools", "updates", "venv", ".venv", "python", "env", "backups",
               "tests", ".git", ".pytest_cache", "__pycache__"}
EXCLUDE_EXT = {".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3", ".db-shm", ".db-wal", ".tmp", ".key", ".pem", ".env"}
MAX_PACKAGE_BYTES = 400 * 1024 * 1024
ACTIONS = {
    "sync": "Sincronizar agora",
    "run_tasks": "Executar tarefas",
    "pause_schedules": "Pausar agendamentos",
    "resume_schedules": "Retomar agendamentos",
    "stop_running": "Parar execuções em andamento",
    "test_repositories": "Testar repositórios",
    "restore_test": "Teste de restauração",
    "update_agent": "Atualizar o GBOC Agent",
    "apply_policy": "Aplicar política central",
}
WRITE_ROLES = ("admin", "superadmin", "administrator", "operator")
SCHEMA = """CREATE TABLE IF NOT EXISTS fleet_batch_jobs (
    id SERIAL PRIMARY KEY,
    action VARCHAR(40) NOT NULL,
    params JSONB,
    agent_ids JSONB,
    status VARCHAR(15) DEFAULT 'running',
    ok_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    results JSONB DEFAULT '[]'::jsonb,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
    finished_at TIMESTAMP
)"""
_ready = False
_lock = threading.Lock()
_jobs: Dict[int, Dict[str, Any]] = {}


def _db_exec(sql: str, params: Any = (), fetch: bool = True) -> List[Dict[str, Any]]:
    from modules.reports.report_schedules import _exec
    return _exec(sql, params, fetch)


def ensure_schema() -> None:
    global _ready
    if not _ready:
        with _lock:
            if not _ready:
                _db_exec(SCHEMA, fetch=False)
                _ready = True


def _user(request: Request) -> Dict[str, Any]:
    u = getattr(request.state, "user", None) or {}
    return u if isinstance(u, dict) else {}


def _require_write(request: Request) -> None:
    role = (_user(request).get("role") or "").lower()
    if role and role not in WRITE_ROLES:
        raise HTTPException(403, "Seu perfil não pode executar ações remotas (requer admin ou operator).")


def _audit(user: Dict[str, Any], ip: Optional[str], action: str, ok: bool, details: str) -> None:
    try:
        _db_exec("INSERT INTO server_auth_audit (user_id, username, action, ip_address, details) VALUES (%s, %s, %s, %s, %s)",
                 (user.get("id"), user.get("username"), action + ("" if ok else ".fail"), ip, details[:1000]), False)
    except Exception as e:
        logger.debug(f"auditoria: {e}")


# ───────────────────────── pacote de atualização ─────────────────────────

def _ver_tuple(v: Any) -> Tuple[int, ...]:
    out = []
    for p in str(v or "").replace("v", "").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out) or (0,)


def detect_agent_source() -> Optional[Dict[str, Any]]:
    """Pasta do GBOC Agent ao lado do Server (pacote de distribuição: Agent/; código-fonte: GBOC-Agent/)."""
    parent = os.path.dirname(SERVER_DIR)
    for name in ("Agent", "GBOC-Agent"):
        d = os.path.join(parent, name)
        if os.path.isfile(os.path.join(d, "agent_gboc.py")):
            return {"path": d, "version": _read_version(os.path.join(d, "version.py"))}
    return None


def _read_version(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("GBOC_VERSION"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


def _include(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    if parts[0].lower() in EXCLUDE_TOP or parts[0].startswith(".") or "__pycache__" in parts:
        return False
    low = parts[-1].lower()
    return not any(low.endswith(e) for e in EXCLUDE_EXT) and not low.endswith(".gboc_new")


def _validate_zip(path: str) -> Dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        prefix = ""
        if "agent_gboc.py" not in names:
            tops = {n.split("/", 1)[0] for n in names if "/" in n}
            prefix = next((t + "/" for t in tops if f"{t}/agent_gboc.py" in names), "")
            if not prefix:
                raise ValueError("O ZIP não é um pacote do GBOC Agent (agent_gboc.py não encontrado)")
        version, errors, files = None, [], 0
        for n in names:
            if not n.startswith(prefix):
                continue
            rel = n[len(prefix):]
            if rel.startswith("/") or ".." in rel.split("/") or ":" in rel.split("/")[0]:
                raise ValueError(f"Caminho inseguro no pacote: {n}")
            if not _include(rel):
                continue
            files += 1
            if rel.endswith(".py"):
                src = zf.read(n)
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
        return {"files": files, "version": version}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _publish(tmp_zip: str, source: str, user: str) -> Dict[str, Any]:
    info = _validate_zip(tmp_zip)
    sha = _sha256(tmp_zip)
    os.makedirs(UPDATES_DIR, exist_ok=True)
    dst = os.path.join(UPDATES_DIR, f"{sha}.zip")
    shutil.move(tmp_zip, dst)
    meta = {"sha256": sha, "version": info["version"], "files": info["files"], "size": os.path.getsize(dst), "source": source,
            "published_by": user, "published_at": datetime.now().isoformat(sep=" ", timespec="seconds")}
    with open(CURRENT_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    pkgs = sorted((p for p in os.listdir(UPDATES_DIR) if p.endswith(".zip")),
                  key=lambda p: os.path.getmtime(os.path.join(UPDATES_DIR, p)), reverse=True)
    for old in pkgs[3:]:
        try:
            os.remove(os.path.join(UPDATES_DIR, old))
        except OSError:
            pass
    return meta


def build_package_from_source(user: str) -> Dict[str, Any]:
    src = detect_agent_source()
    if not src:
        raise RuntimeError("Pasta do GBOC Agent não encontrada ao lado do Server. Envie o pacote ZIP manualmente.")
    fd, tmp = tempfile.mkstemp(suffix=".zip", prefix="gboc_agent_pkg_")
    os.close(fd)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src["path"]):
            rel_root = os.path.relpath(root, src["path"])
            dirs[:] = [d for d in dirs if _include(d if rel_root == "." else os.path.join(rel_root, d))]
            for fn in files:
                rel = fn if rel_root == "." else os.path.join(rel_root, fn)
                if _include(rel):
                    zf.write(os.path.join(root, fn), rel.replace("\\", "/"))
    try:
        return _publish(tmp, f"Pasta {src['path']}", user)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def current_package() -> Optional[Dict[str, Any]]:
    try:
        with open(CURRENT_FILE, encoding="utf-8") as f:
            meta = json.load(f)
        if os.path.isfile(os.path.join(UPDATES_DIR, f"{meta['sha256']}.zip")):
            return meta
    except Exception:
        pass
    return None


@router.get("/api/v1/sync/agent-update/package")
async def download_package(sha256: str):
    """Download do pacote pelo agente (rota de sincronização: exige a chave de pareamento)."""
    if len(sha256) != 64 or not all(c in "0123456789abcdefABCDEF" for c in sha256):
        raise HTTPException(400, "sha256 inválido")
    path = os.path.join(UPDATES_DIR, f"{sha256.lower()}.zip")
    if not os.path.isfile(path):
        raise HTTPException(404, "Pacote não encontrado no Server")
    return FileResponse(path, media_type="application/zip", filename=f"gboc_agent_{sha256[:12]}.zip")


@router.get("/api/v1/fleet/update/package")
async def package_info():
    src = await asyncio.to_thread(detect_agent_source)
    return {"status": "success", "package": await asyncio.to_thread(current_package), "agent_source": src}


@router.post("/api/v1/fleet/update/package/build")
async def package_build(request: Request):
    _require_write(request)
    u = _user(request)
    try:
        meta = await asyncio.to_thread(build_package_from_source, u.get("username") or "?")
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e))
    _audit(u, request.client.host if request.client else None, "fleet.package.build", True, f"versão={meta.get('version')} sha={meta['sha256'][:16]}")
    return {"status": "success", "package": meta}


@router.post("/api/v1/fleet/update/package/upload")
async def package_upload(request: Request):
    """Corpo = arquivo ZIP (Content-Type application/zip ou octet-stream)."""
    _require_write(request)
    u = _user(request)
    fd, tmp = tempfile.mkstemp(suffix=".zip", prefix="gboc_agent_upload_")
    total = 0
    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                total += len(chunk)
                if total > MAX_PACKAGE_BYTES:
                    raise HTTPException(413, "Pacote maior que 400 MB")
                f.write(chunk)
        if total == 0:
            raise HTTPException(400, "Envie o arquivo ZIP do GBOC Agent no corpo da requisição")
        try:
            meta = await asyncio.to_thread(_publish, tmp, "Envio manual (ZIP)", u.get("username") or "?")
        except zipfile.BadZipFile:
            raise HTTPException(400, "Arquivo não é um ZIP válido")
        except ValueError as e:
            raise HTTPException(400, str(e))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    _audit(u, request.client.host if request.client else None, "fleet.package.upload", True, f"versão={meta.get('version')} sha={meta['sha256'][:16]}")
    return {"status": "success", "package": meta}


# ───────────────────────── frota ─────────────────────────

def _fleet_rows() -> List[Dict[str, Any]]:
    return _db_exec("""SELECT a.agent_id, a.hostname, a.ip_address, a.os_info, a.agent_version, a.status, a.last_heartbeat,
                              a.tenant_id, o.name AS tenant_name
                       FROM agents a LEFT JOIN msp_organizations o ON o.org_id = a.tenant_id ORDER BY a.hostname""")


@router.get("/api/v1/fleet/agents")
async def fleet_agents():
    from modules.agents.remote_mgmt import _manager
    rows = await asyncio.to_thread(_fleet_rows)
    pkg = await asyncio.to_thread(current_package)
    mgr = _manager()
    try:
        thr = float((await asyncio.to_thread(_db_exec, """SELECT value FROM server_settings WHERE key='agent_offline_threshold_minutes'
                                                         LIMIT 1""") or [{"value": 60}])[0]["value"] or 60)
    except Exception:
        thr = 60.0
    now = datetime.now()
    out = []
    for r in rows:
        hb = r.get("last_heartbeat")
        online = bool(hb and (now - hb).total_seconds() <= thr * 60)
        out.append({**{k: (v.isoformat(sep=" ", timespec="seconds") if hasattr(v, "isoformat") else v) for k, v in r.items()},
                    "online": online, "websocket": r["agent_id"] in mgr.active_connections,
                    "outdated": bool(pkg and pkg.get("version") and r.get("agent_version") and
                                     _ver_tuple(r["agent_version"]) < _ver_tuple(pkg["version"]))})
    return {"status": "success", "agents": out, "package": pkg}


async def _call(agent_id: str, method: str, path: str, body: Any = None, timeout: float = 60.0) -> Dict[str, Any]:
    from modules.agents.remote_mgmt import agent_call
    res = await agent_call(agent_id, method, path, body=body, timeout=timeout)
    b = res.get("body")
    if res["status_code"] >= 400:
        msg = b.get("detail") or b.get("message") if isinstance(b, dict) else str(b)[:200]
        if res["status_code"] == 404 and path.startswith("api/agent-ops"):
            msg = "Agente sem suporte a esta ação — atualize o GBOC Agent"
        raise RuntimeError(str(msg or f"HTTP {res['status_code']}")[:400])
    return b if isinstance(b, dict) else {"raw": b}


def _short(msg: Any) -> str:
    """Primeira linha relevante de mensagens de diagnóstico com várias linhas (prioriza FALHA/ERRO)."""
    lines = [ln.strip("- ").strip() for ln in str(msg or "").splitlines() if ln.strip()]
    key = [ln for ln in lines if "FALHA" in ln.upper() or "ERRO" in ln.upper()]
    return (key or lines or ["falhou"])[0][:180]


async def _action(agent_id: str, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if action == "sync":
        await _call(agent_id, "POST", "api/server/sync", {})
        return {"message": "Sincronização solicitada"}
    if action in ("pause_schedules", "resume_schedules"):
        d = await _call(agent_id, "POST", "api/agent-ops/schedules", {"enabled": action == "resume_schedules"})
        names = ", ".join(t["name"] for t in d.get("tasks", [])[:6])
        return {"message": f"{d.get('changed', 0)} tarefa(s) {'retomada(s)' if action == 'resume_schedules' else 'pausada(s)'}"
                           + (f": {names}" if names else "")}
    if action == "run_tasks":
        d = await _call(agent_id, "GET", "api/tasks/")
        flt = str(params.get("name_contains") or "").strip().lower()
        tasks = [t for t in d.get("tasks", []) if t.get("enabled") is not False and (not flt or flt in str(t.get("name", "")).lower())]
        if not tasks:
            return {"message": "Nenhuma tarefa ativa corresponde ao filtro", "skipped": True}
        started = []
        for t in tasks:
            await _call(agent_id, "POST", f"api/tasks/{t['id']}/run", {})
            started.append(t.get("name"))
        return {"message": f"{len(started)} tarefa(s) enviada(s) para execução: {', '.join(started[:6])}"}
    if action == "stop_running":
        d = await _call(agent_id, "GET", "api/tasks/running/detailed")
        ex = d.get("executions") or []
        for x in ex:
            await _call(agent_id, "POST", f"api/tasks/execution/{x.get('id') or x.get('execution_id')}/stop", {})
        return {"message": f"{len(ex)} execução(ões) interrompida(s)" if ex else "Nenhuma execução em andamento"}
    if action == "test_repositories":
        d = await _call(agent_id, "GET", "api/repositories/")
        repos = d.get("repositories") or d.get("repos") or (d.get("raw") if isinstance(d.get("raw"), list) else [])
        okn, bad = 0, []
        for rp in repos:
            try:
                t = await _call(agent_id, "POST", f"api/repositories/{rp.get('id')}/test", {}, timeout=120)
                if t.get("success") is False or str(t.get("status")).lower() in ("error", "failed"):
                    bad.append(f"{rp.get('name')}: {_short(t.get('message') or t.get('error') or 'falhou')}")
                else:
                    okn += 1
            except Exception as e:
                bad.append(f"{rp.get('name')}: {_short(e)}")
        if bad:
            raise RuntimeError(f"{okn} OK, {len(bad)} com problema — " + "; ".join(bad)[:300])
        return {"message": f"{okn} repositório(s) acessível(is)"}
    if action == "restore_test":
        from modules.agents.restore_tests import run_for_agent, _summary_status
        res = await run_for_agent(agent_id, None, int(params.get("sample_size") or 5), int(params.get("max_file_mb") or 100),
                                  f"server:batch:{params.get('_job_id')}")
        st = _summary_status(res["results"])
        txt = "; ".join(f"{r.get('repository_name') or r.get('repository_id')}: {r.get('status')}"
                        + (f" ({r.get('files_ok')}/{r.get('files_tested')})" if r.get("files_tested") is not None else "")
                        for r in res["results"])
        if st != "passed":
            raise RuntimeError(txt[:400])
        return {"message": txt[:400]}
    if action == "apply_policy":
        from modules.agents.policies import _policies, agent_payload
        pol = next((x for x in await asyncio.to_thread(_policies) if x["id"] == int(params.get("policy_id") or 0)), None)
        if not pol:
            raise RuntimeError("Política não encontrada")
        d = await _call(agent_id, "POST", "api/agent-ops/apply-policy", {"policy": agent_payload(pol)}, timeout=600)
        rep = d.get("report") or {}
        parts = [f"{len(rep.get('tasks') or [])} tarefa(s) ajustada(s)"]
        imm = rep.get("immutability") or []
        if imm:
            parts.append("imutável: " + ", ".join(f"{i.get('repository')} {'✔' if i.get('protected') else '✘'}" for i in imm[:5]))
        if rep.get("errors"):
            raise RuntimeError("; ".join(parts + rep["errors"])[:400])
        return {"message": "; ".join(parts) + f" (v{pol.get('version')})"}
    if action == "update_agent":
        pkg = current_package()
        if not pkg:
            raise RuntimeError("Nenhum pacote de atualização publicado no Server")
        d = await _call(agent_id, "POST", "api/agent-ops/update", {"sha256": pkg["sha256"], "restart": True}, timeout=900)
        u = d.get("update") or {}
        return {"message": f"Atualizado {u.get('from_version')} → {u.get('to_version')} ({u.get('files')} arquivos); "
                           f"reinício {u.get('restart')}"}
    raise RuntimeError("Ação desconhecida")


async def _run_job(job_id: int, action: str, agent_ids: List[str], params: Dict[str, Any], user: Dict[str, Any],
                   ip: Optional[str]) -> None:
    from modules.agents.remote_mgmt import _manager
    rows = await asyncio.to_thread(_fleet_rows)
    hosts = {r["agent_id"]: r.get("hostname") for r in rows}
    last_hb = {r["agent_id"]: r.get("last_heartbeat") for r in rows}
    mgr = _manager()
    sem = asyncio.Semaphore(4 if action in ("restore_test", "update_agent") else 8)
    job = _jobs[job_id]
    timeout = {"restore_test": 3 * 3600, "update_agent": 1200}.get(action, 300)

    async def one(aid: str):
        async with sem:
            t0 = time.time()
            item = {"agent_id": aid, "hostname": hosts.get(aid) or aid, "status": "running"}
            job["results"].append(item)
            hb = last_hb.get(aid)
            if aid not in mgr.active_connections and (hb is None or (datetime.now() - hb).total_seconds() > 3 * 3600):
                item.update(status="error", seconds=0.0,
                            message=f"Agente offline (último contato {hb.strftime('%d/%m %H:%M') if hb else 'nunca'}) — ignorado")
                return
            try:
                res = await asyncio.wait_for(_action(aid, action, {**params, "_job_id": job_id}), timeout=timeout)
                item.update(status="skipped" if res.get("skipped") else "ok", message=res.get("message"))
            except asyncio.TimeoutError:
                item.update(status="error", message="Tempo limite excedido")
            except Exception as e:
                item.update(status="error", message=str(e)[:400])
            item["seconds"] = round(time.time() - t0, 1)
            await asyncio.to_thread(_audit, user, ip, f"fleet.{action}", item["status"] != "error",
                                    f"job={job_id} agente={aid} {item.get('message') or ''}")

    await asyncio.gather(*(one(a) for a in agent_ids))
    okc = sum(1 for r in job["results"] if r["status"] in ("ok", "skipped"))
    failc = sum(1 for r in job["results"] if r["status"] == "error")
    job.update(status="done", ok_count=okc, fail_count=failc, finished_at=datetime.now().isoformat(sep=" ", timespec="seconds"))
    await asyncio.to_thread(_db_exec, """UPDATE fleet_batch_jobs SET status='done', ok_count=%s, fail_count=%s, results=%s::jsonb,
                                         finished_at=LOCALTIMESTAMP WHERE id=%s""",
                            (okc, failc, json.dumps(job["results"], ensure_ascii=False), job_id), False)


@router.post("/api/v1/fleet/batch")
async def start_batch(request: Request):
    _require_write(request)
    b = await request.json() or {}
    action = b.get("action")
    if action not in ACTIONS or action == "apply_policy":
        raise HTTPException(400, "Ação inválida")
    params = {k: v for k, v in (b.get("params") or {}).items() if k in ("name_contains", "sample_size", "max_file_mb")}
    return {"status": "started", "job": await start_job(request, action, b.get("agent_ids") or [], params)}


async def start_job(request: Request, action: str, agent_ids: List[str], params: Dict[str, Any]) -> Dict[str, Any]:
    """Cria e dispara um lote (usado pela tela de operações em lote e pela aplicação de políticas)."""
    ids = [str(a) for a in agent_ids if str(a).strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(400, "Selecione ao menos um agente")
    if len(ids) > 500:
        raise HTTPException(400, "Máximo de 500 agentes por lote")
    if action == "update_agent" and not await asyncio.to_thread(current_package):
        raise HTTPException(400, "Publique um pacote de atualização antes (Gerar pacote ou Enviar ZIP).")
    await asyncio.to_thread(ensure_schema)
    u = _user(request)
    rows = await asyncio.to_thread(_db_exec, """INSERT INTO fleet_batch_jobs (action, params, agent_ids, created_by)
                                                VALUES (%s, %s::jsonb, %s::jsonb, %s) RETURNING id, created_at""",
                                   (action, json.dumps(params), json.dumps(ids), u.get("username") or "?"))
    job_id = rows[0]["id"]
    _jobs[job_id] = {"id": job_id, "action": action, "action_label": ACTIONS[action], "params": params, "agent_ids": ids,
                     "status": "running", "results": [], "created_by": u.get("username"),
                     "created_at": rows[0]["created_at"].isoformat(sep=" ", timespec="seconds")}
    if len(_jobs) > 50:
        for k in sorted(_jobs)[:-50]:
            _jobs.pop(k, None)
    asyncio.create_task(_run_job(job_id, action, ids, params, u, request.client.host if request.client else None))
    return _jobs[job_id]


@router.get("/api/v1/fleet/jobs/{job_id}")
async def get_job(job_id: int):
    if job_id in _jobs:
        return {"status": "success", "job": _jobs[job_id]}
    rows = await asyncio.to_thread(_db_exec, "SELECT * FROM fleet_batch_jobs WHERE id=%s", (job_id,))
    if not rows:
        raise HTTPException(404, "Lote não encontrado")
    r = {k: (v.isoformat(sep=" ", timespec="seconds") if hasattr(v, "isoformat") else v) for k, v in rows[0].items()}
    r["action_label"] = ACTIONS.get(r["action"], r["action"])
    return {"status": "success", "job": r}


@router.get("/api/v1/fleet/jobs")
async def list_jobs(limit: int = 20):
    await asyncio.to_thread(ensure_schema)
    rows = await asyncio.to_thread(_db_exec, """SELECT id, action, status, ok_count, fail_count, jsonb_array_length(agent_ids) AS agents,
                                                created_by, created_at, finished_at FROM fleet_batch_jobs ORDER BY id DESC LIMIT %s""",
                                   (max(1, min(limit, 200)),))
    out = []
    for r in rows:
        r = {k: (v.isoformat(sep=" ", timespec="seconds") if hasattr(v, "isoformat") else v) for k, v in r.items()}
        r["action_label"] = ACTIONS.get(r["action"], r["action"])
        if r["id"] in _jobs and _jobs[r["id"]]["status"] == "running":
            r["status"] = "running"
        out.append(r)
    return {"status": "success", "jobs": out, "actions": ACTIONS}
