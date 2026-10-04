# GBOC System v14.6.0 Enterprise Edition
# Module: Server RMM & Remote Terminal Router
# Remote Agent Execution Dispatcher, WebSocket/HTTP Proxy & Local Execution Fallback

import os
import sys
import subprocess
import logging
import time
import json
import socket
import platform
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import JSONResponse, Response
import httpx

try:
    from version_control import __version__ as SERVER_VERSION
except Exception:
    SERVER_VERSION = "14.6.0"

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    from database import db_manager
    def get_db(): return db_manager.get_connection()
    def release_db(conn): db_manager.release_connection(conn)
except Exception:
    def get_db(): return None
    def release_db(conn): pass

logger = logging.getLogger("gboc_rmm_server_module")
router = APIRouter(prefix="/api/v1/rmm", tags=["Server RMM & Terminal"])

# Perfis com permissão RMM_EXEC (ver modules/users/users_router.py)
_RMM_EXEC_ROLES = ("admin", "superadmin", "administrator", "operator")
# Cabeçalhos do navegador que nunca devem ser repassados ao Agente (sessão do Server)
_STRIP_PROXY_HEADERS = {"host", "content-length", "cookie", "authorization", "x-gboc-agent-key"}


def _agent_headers() -> Dict[str, str]:
    """Chave de pareamento enviada em toda chamada Server -> Agente."""
    try:
        from modules.agents.agent_pairing import agent_headers
        return agent_headers()
    except Exception:
        return {}


def _require_rmm_exec(request: Request) -> Optional[JSONResponse]:
    user = getattr(request.state, "user", None) or {}
    if (user.get("role") or "").lower() not in _RMM_EXEC_ROLES:
        return JSONResponse({"status": "error", "code": "FORBIDDEN",
                             "message": "Seu perfil não tem permissão para executar ações RMM (requer admin ou operator)."},
                            status_code=403)
    return None


def _agent_unreachable(agent_id: str, conn_info: Dict[str, Any], what: str, extra: Optional[Dict] = None,
                       status_code: int = 503) -> JSONResponse:
    if not conn_info.get("ip"):
        msg = f"Agente '{agent_id}' não encontrado ou sem endereço IP registrado (aguarde o heartbeat)."
        status_code = 404
    else:
        msg = f"Agente '{agent_id}' ({conn_info['ip']}:{conn_info.get('port', 9200)}) está OFFLINE ou inacessível. {what}"
    payload = {"status": "error", "agent_id": agent_id, "message": msg}
    payload.update(extra or {})
    return JSONResponse(payload, status_code=status_code)


def _agent_urls(conn_info: Dict[str, Any], path: str) -> List[str]:
    ip = conn_info.get("ip")
    if not ip:
        return []
    port = conn_info.get("port") or 9200
    return [f"http://{ip}:{port}/{path.lstrip('/')}", f"https://{ip}:{port}/{path.lstrip('/')}"]


def _is_local_agent(agent_id: Optional[str]) -> bool:
    if not agent_id:
        return True
    aid = str(agent_id).lower().strip()
    return aid in ("agente-local", "servidor-central", "server", "local", "localhost", "127.0.0.1")


def _get_agent_connection_info(agent_id: str) -> Dict[str, Any]:
    """Retorna IP, porta e status de conexao WebSocket/DB do agente."""
    if _is_local_agent(agent_id):
        return {"is_local": True}

    ip = None  # sem fallback para 127.0.0.1: Server e Agente podem estar em máquinas diferentes
    port = 9200
    is_ws_connected = False
    status = "unknown"

    try:
        try:
            from server_gboc import manager
        except ImportError:
            from gboc_server import manager
        if agent_id in manager.active_connections:
            is_ws_connected = True
            status = "online"
        agent_info = manager.get_agent_data(agent_id)
        if agent_info:
            ip = agent_info.get("ip_address") or ip
            port = agent_info.get("port") or port
    except Exception:
        pass

    if get_db:
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT ip_address, status FROM agents WHERE agent_id = %s OR hostname = %s LIMIT 1", (agent_id, agent_id))
            row = cur.fetchone()
            if row:
                if isinstance(row, (tuple, list)):
                    ip = row[0] or ip
                    status = row[1] if len(row) > 1 and row[1] else status
                else:
                    ip = row.get("ip_address") or ip
                    status = row.get("status") or status
        except Exception as e:
            logger.warning(f"[SERVER RMM] Erro ao consultar DB para agente '{agent_id}': {e}")
        finally:
            if 'cur' in locals() and cur: cur.close()
            if conn and release_db: release_db(conn)

    # O agente informa "ip:porta" (ex.: 10.0.0.5:9200); antes a URL virava http://10.0.0.5:9200:9200
    try:
        from modules.agents.remote_mgmt import split_host_port
        ip, port = split_host_port(ip, int(port or 9200))
    except Exception:
        pass
    return {
        "is_local": False,
        "ip": ip,
        "port": port,
        "is_ws_connected": is_ws_connected,
        "status": status
    }


def _run_local_server_command(cmd: str, shell: str = "powershell", cwd: str = None, timeout: int = 30) -> Dict[str, Any]:
    """Executa o comando localmente na maquina do Servidor Central."""
    start_time = time.time()
    try:
        if not cmd:
            return {"status": "error", "message": "Comando vazio"}

        cwd = cwd or os.getcwd()
        if not os.path.exists(cwd):
            cwd = os.getcwd()

        if shell == "cmd":
            shell_cmd = ["cmd.exe", "/c", cmd]
        elif shell == "python":
            shell_cmd = [sys.executable, "-c", cmd]
        elif shell in ("bash", "sh"):
            shell_cmd = ["bash", "-c", cmd]
        else:
            shell_cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd] if os.name == 'nt' else ["bash", "-c", cmd]

        res = subprocess.run(shell_cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        duration = round(time.time() - start_time, 3)

        stdout = (res.stdout or "").strip()
        stderr = (res.stderr or "").strip()
        output = stdout if stdout else (stderr if stderr else "Comando executado localmente no Servidor sem retorno de texto.")

        return {
            "status": "success",
            "execution_type": "local_server",
            "command": cmd,
            "shell": shell,
            "stdout": stdout,
            "stderr": stderr,
            "output": output,
            "exit_code": res.returncode,
            "duration_seconds": duration,
            "hostname": socket.gethostname(),
            "timestamp": datetime.now().isoformat()
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Timeout de {timeout}s excedido no servidor", "exit_code": 124}
    except Exception as e:
        return {"status": "error", "message": str(e), "exit_code": 1}


# --- EXECUCAO DE COMANDOS RMM ---

@router.post("/execute")
@router.post("/terminal/exec")
async def rmm_execute_command(request: Request):
    """Encaminha comandos para execucao no Agente remoto ou executa localmente no Servidor."""
    denied = _require_rmm_exec(request)
    if denied:
        return denied
    try:
        body = await request.json()
        agent_id = body.get("agent_id") or body.get("agent")
        cmd = (body.get("command") or body.get("cmd") or "").strip()
        shell = (body.get("shell") or ("powershell" if os.name == "nt" else "bash")).lower()
        timeout = min(int(body.get("timeout") or 30), 120)

        if not cmd:
            return JSONResponse({"status": "error", "message": "Comando vazio"}, status_code=400)

        # 1. Se for comando no Servidor Host Local
        if _is_local_agent(agent_id):
            logger.info(f"[SERVER RMM] Executando comando no Servidor Central Host")
            local_res = _run_local_server_command(cmd, shell=shell, cwd=body.get("cwd"), timeout=timeout)
            local_res["agent_id"] = "servidor-central"
            return JSONResponse(local_res)

        # 2. Se for agente remoto
        conn_info = _get_agent_connection_info(agent_id)
        agent_ip = conn_info.get("ip")
        agent_port = conn_info.get("port", 9200)
        if not agent_ip:
            return _agent_unreachable(agent_id, conn_info, "")

        for target_url in _agent_urls(conn_info, "api/v1/rmm/execute"):
            try:
                async with httpx.AsyncClient(timeout=float(timeout + 5), verify=False) as client:
                    resp = await client.post(target_url, json=body, headers=_agent_headers())
                    if resp.status_code == 401:
                        return JSONResponse({"status": "error", "agent_id": agent_id, "code": "AGENT_KEY_REJECTED",
                                             "message": "O Agente recusou a chave de pareamento. Configure a chave do Server no Agente."},
                                            status_code=502)
                    if resp.status_code == 200:
                        res_data = resp.json()
                        res_data["execution_type"] = f"remote_agent_{agent_id}"
                        logger.info(f"[SERVER RMM] Comando executado com sucesso no Agente {agent_id} via {target_url}")
                        return JSONResponse(res_data)
            except Exception as proxy_err:
                logger.warning(f"[SERVER RMM] Falha ao comunicar com agente remoto {agent_id} em {target_url}: {proxy_err}")

        # Se nao conseguiu conectar ao agente remoto, RETORNAR ERRO DE AGENTE OFFLINE (Sem farsa local!)
        logger.warning(f"[SERVER RMM] Agente remoto '{agent_id}' esta OFFLINE ou inacessivel. Cancelando execucao.")
        return JSONResponse({
            "status": "error",
            "agent_id": agent_id,
            "execution_type": "offline_error",
            "message": f"Agente '{agent_id}' esta OFFLINE ou inacessivel no momento. O terminal remoto nao pode executar comandos enquanto o agente estiver desconectado.",
            "output": f"[ERRO DE CONEXAO RMM]: O agente '{agent_id}' ({agent_ip}:{agent_port}) esta OFFLINE. Nenhuma acao foi executada."
        }, status_code=503)

    except Exception as e:
        logger.error(f"[SERVER RMM] Erro no rmm_execute_command: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# --- GERENCIADOR DE PROCESSOS ---

@router.get("/processes")
@router.get("/proxy/{agent_id}/processes")
async def rmm_get_processes(agent_id: Optional[str] = None):
    """Retorna lista de processos ativos (do Agente remoto ou do Servidor local)."""
    if not _is_local_agent(agent_id):
        conn_info = _get_agent_connection_info(agent_id)
        for url in _agent_urls(conn_info, "api/v1/rmm/processes"):
            try:
                async with httpx.AsyncClient(timeout=6.0, verify=False) as client:
                    resp = await client.get(url, headers=_agent_headers())
                    if resp.status_code == 200:
                        return JSONResponse(resp.json())
            except Exception:
                pass
        return _agent_unreachable(agent_id, conn_info, "Impossível listar processos.", {"processes": []})

    # Processos locais do Servidor Central
    procs = []
    if PSUTIL_AVAILABLE:
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'username']):
            try:
                info = p.info
                procs.append({
                    "pid": info['pid'],
                    "name": info['name'] or 'process',
                    "cpu": round(info['cpu_percent'] or 0, 1),
                    "memory": round(info['memory_percent'] or 0, 1),
                    "user": info['username'] or 'SYSTEM'
                })
            except Exception:
                continue
    procs.sort(key=lambda x: (x['memory'], x['cpu']), reverse=True)
    return JSONResponse({"status": "success", "execution_type": "local_server", "total": len(procs), "processes": procs[:100]})


@router.post("/process/kill")
async def rmm_kill_process(request: Request):
    """Encerra um processo pelo PID."""
    denied = _require_rmm_exec(request)
    if denied:
        return denied
    try:
        body = await request.json()
        agent_id = body.get("agent_id")
        pid = int(body.get("pid", 0))

        if not _is_local_agent(agent_id):
            conn_info = _get_agent_connection_info(agent_id)
            for url in _agent_urls(conn_info, "api/v1/rmm/process/kill"):
                try:
                    async with httpx.AsyncClient(timeout=6.0, verify=False) as client:
                        resp = await client.post(url, json=body, headers=_agent_headers())
                        if resp.status_code == 200:
                            return JSONResponse(resp.json())
                except Exception:
                    pass
            return _agent_unreachable(agent_id, conn_info, f"Não foi possível encerrar o processo PID {pid}.")

        # Local Kill no Servidor
        if PSUTIL_AVAILABLE and pid > 0:
            p = psutil.Process(pid)
            p_name = p.name()
            p.terminate()
            return JSONResponse({"status": "success", "message": f"Processo '{p_name}' (PID {pid}) encerrado no Servidor."})
        elif pid > 0:
            cmd = ["taskkill", "/F", "/PID", str(pid)] if os.name == 'nt' else ["kill", "-9", str(pid)]
            subprocess.run(cmd, capture_output=True)
            return JSONResponse({"status": "success", "message": f"Processo PID {pid} encerrado no Servidor."})

        return JSONResponse({"status": "error", "message": "PID invalido"}, status_code=400)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# --- GERENCIADOR DE SERVICOS ---

@router.get("/services")
async def rmm_get_services(agent_id: Optional[str] = None):
    """Retorna lista de servicos."""
    if not _is_local_agent(agent_id):
        conn_info = _get_agent_connection_info(agent_id)
        for url in _agent_urls(conn_info, "api/v1/rmm/services"):
            try:
                async with httpx.AsyncClient(timeout=6.0, verify=False) as client:
                    resp = await client.get(url, headers=_agent_headers())
                    if resp.status_code == 200:
                        return JSONResponse(resp.json())
            except Exception:
                pass
        return _agent_unreachable(agent_id, conn_info, "Impossível listar serviços.", {"services": []})

    services = []
    if os.name == 'nt' and PSUTIL_AVAILABLE:
        for s in psutil.win_service_iter():
            try:
                s_info = s.as_dict()
                services.append({
                    "name": s_info.get("name"),
                    "display_name": s_info.get("display_name") or s_info.get("name"),
                    "status": s_info.get("status"),
                    "start_type": s_info.get("start_type"),
                    "pid": s_info.get("pid")
                })
            except Exception:
                continue
    return JSONResponse({"status": "success", "execution_type": "local_server", "total": len(services), "services": services[:100]})


# --- ESPELHO REMOTO ---

@router.get("/mirror")
@router.get("/mirror/{agent_id}")
async def rmm_get_mirror(agent_id: Optional[str] = None):
    """Retorna o Espelho Remoto Completo do Agente ou Servidor."""
    if not _is_local_agent(agent_id):
        conn_info = _get_agent_connection_info(agent_id)
        for url in _agent_urls(conn_info, "api/v1/rmm/mirror"):
            try:
                async with httpx.AsyncClient(timeout=6.0, verify=False) as client:
                    resp = await client.get(url, headers=_agent_headers())
                    if resp.status_code == 200:
                        return JSONResponse(resp.json())
            except Exception as proxy_err:
                logger.warning(f"[SERVER RMM] Espelho do agente {agent_id} inacessivel ({url}): {proxy_err}")
        return _agent_unreachable(agent_id, conn_info, "")

    # Mirror Snapshot do Servidor Central
    hostname = socket.gethostname()
    os_info = f"{platform.system()} {platform.release()} ({platform.architecture()[0]})"
    cpu = psutil.cpu_percent(interval=0.2) if PSUTIL_AVAILABLE else None
    mem = psutil.virtual_memory() if PSUTIL_AVAILABLE else None
    try:
        host_ip = socket.gethostbyname(hostname)
    except Exception:
        host_ip = None

    return JSONResponse({
        "status": "success",
        "mirror": {
            "agent_id": agent_id or "servidor-central",
            "hostname": hostname,
            "ip_address": host_ip,
            "version": f"GBOC Server {SERVER_VERSION} Enterprise",
            "system_telemetry": {
                "hostname": hostname,
                "os_info": os_info,
                "cpu_percent": cpu,
                "memory": {
                    "total_gb": round(mem.total / (1024**3), 2) if mem else None,
                    "used_gb": round(mem.used / (1024**3), 2) if mem else None,
                    "percent": mem.percent if mem else None
                }
            },
            "mirror_timestamp": datetime.now().isoformat()
        }
    })


# --- ROUTE DE PROXY COMPATIVEL ---

@router.api_route("/proxy/{agent_id}/{subpath:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def rmm_proxy_agent(agent_id: str, subpath: str, request: Request):
    """Proxy HTTP/REST para redirecionar chamadas RMM diretamente ao Agente."""
    body = await request.body()
    if request.method != "GET":
        denied = _require_rmm_exec(request)
        if denied:
            return denied

    if not _is_local_agent(agent_id):
        conn_info = _get_agent_connection_info(agent_id)
        clean_subpath = subpath if subpath.startswith("api/") else f"api/v1/{subpath.lstrip('/')}"
        fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in _STRIP_PROXY_HEADERS}
        fwd_headers.update(_agent_headers())

        # Agente conectado por WebSocket: usa o canal do próprio agente (funciona atrás de NAT/firewall)
        if conn_info.get("is_ws_connected"):
            try:
                from modules.agents.remote_mgmt import agent_call
                body_json = json.loads(body.decode("utf-8")) if body else None
                res = await agent_call(agent_id, request.method, clean_subpath, query=dict(request.query_params), body=body_json)
                if res["status_code"] < 500 or res.get("channel"):
                    b = res["body"]
                    if isinstance(b, (dict, list)):
                        return JSONResponse(b, status_code=res["status_code"])
                    return Response(content=str(b or ""), status_code=res["status_code"], media_type=res.get("content_type") or "text/plain")
            except Exception as e:
                logger.warning(f"[SERVER RMM] Canal WebSocket falhou para {agent_id}: {e}")

        for target_url in _agent_urls(conn_info, clean_subpath):
            try:
                async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
                    resp = await client.request(
                        method=request.method,
                        url=target_url,
                        params=dict(request.query_params),
                        headers=fwd_headers,
                        content=body
                    )
                    if resp.status_code < 500:
                        hop = {"content-length", "content-encoding", "transfer-encoding", "connection", "set-cookie"}
                        return Response(content=resp.content, status_code=resp.status_code,
                                        headers={k: v for k, v in resp.headers.items() if k.lower() not in hop})
            except Exception as e:
                logger.warning(f"[SERVER RMM] Falha proxy para agente {agent_id} ({target_url}): {e}")

        return _agent_unreachable(agent_id, conn_info, "", status_code=502)

    # Execucao local no Servidor Central
    if "command" in subpath or "execute" in subpath:
        body_data = {}
        try:
            body_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            pass
        cmd = body_data.get("command", "")
        shell = body_data.get("shell", "powershell")
        res = _run_local_server_command(cmd, shell=shell)
        res["agent_id"] = "servidor-central"
        return JSONResponse(res)

    elif "processes" in subpath:
        return await rmm_get_processes(agent_id="servidor-central")

    elif "isolation" in subpath:
        return JSONResponse({"status": "unavailable", "message": "Isolamento de rede não é executado no host do Servidor Central; selecione um agente."},
                            status_code=501)

    return JSONResponse({"status": "error", "message": f"Agente '{agent_id}' offline ou inacessivel."}, status_code=502)
