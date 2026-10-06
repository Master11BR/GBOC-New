"""
GBOC Server — Instalação em massa do GBOC Agent (tokens de instalação).

Fluxo:
  1. O administrador cria um TOKEN DE INSTALAÇÃO (cliente, validade, limite de usos). O texto do token só é
     mostrado uma vez (o Server guarda apenas o hash).
  2. Em cada máquina, um comando único baixa o script de instalação do Server, que baixa o pacote do Agent,
     instala em modo automático e inscreve o agente:
        powershell -ExecutionPolicy Bypass -Command "iwr -UseBasicParsing '<server>/api/v1/enroll/script?token=<token>' | iex"
     (o mesmo comando serve para GPO de inicialização e Intune).
  3. O agente chama POST /api/v1/enroll com o token e recebe a chave de pareamento e o cliente — o cliente fica
     travado (o agente não consegue trocá-lo). Licença e limite do plano do cliente valem na inscrição.

Rotas públicas (autenticadas pelo token): POST /api/v1/enroll · GET /api/v1/enroll/package · GET /api/v1/enroll/script
Rotas de administração: /api/v1/fleet/install-tokens
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

router = APIRouter(tags=["Instalação em massa"])
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS install_tokens (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        token_hash VARCHAR(64) UNIQUE NOT NULL,
        token_prefix VARCHAR(16),
        tenant_id VARCHAR(100),
        expires_at TIMESTAMP NOT NULL,
        max_uses INTEGER DEFAULT 0,
        uses INTEGER DEFAULT 0,
        created_by TEXT,
        created_at TIMESTAMP DEFAULT LOCALTIMESTAMP,
        last_used_at TIMESTAMP,
        revoked_at TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS agent_enrollments (
        id SERIAL PRIMARY KEY,
        token_id INTEGER,
        agent_id VARCHAR(255),
        hostname TEXT,
        ip_address TEXT,
        tenant_id VARCHAR(100),
        status VARCHAR(20),
        message TEXT,
        created_at TIMESTAMP DEFAULT LOCALTIMESTAMP
    )""",
]
_ready = False
_lock = threading.Lock()
_fails: Dict[str, deque] = defaultdict(deque)
TOKEN_PREFIX = "gbi_"


def _db_exec(sql: str, params: Any = (), fetch: bool = True) -> List[Dict[str, Any]]:
    from modules.reports.report_schedules import _exec
    return _exec(sql, params, fetch)


def ensure_schema() -> None:
    global _ready
    if not _ready:
        with _lock:
            if not _ready:
                for s in SCHEMA:
                    _db_exec(s, fetch=False)
                _ready = True


def _hash(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def _rate_limited(ip: str) -> bool:
    q = _fails[ip]
    now = time.time()
    while q and now - q[0] > 600:
        q.popleft()
    return len(q) >= 20


def _fail(ip: str) -> None:
    _fails[ip].append(time.time())


def _valid_token(token: str, consume: bool = False, agent_id: Optional[str] = None) -> Dict[str, Any]:
    ensure_schema()
    if not token or not token.startswith(TOKEN_PREFIX):
        raise PermissionError("Token de instalação inválido")
    rows = _db_exec("SELECT * FROM install_tokens WHERE token_hash=%s", (_hash(token),))
    if not rows:
        raise PermissionError("Token de instalação inválido")
    t = rows[0]
    if t.get("revoked_at"):
        raise PermissionError("Token de instalação revogado")
    if t["expires_at"] < datetime.now():
        raise PermissionError("Token de instalação expirado")
    if t.get("max_uses") and int(t["uses"] or 0) >= int(t["max_uses"]):
        if not (agent_id and _db_exec("""SELECT 1 FROM agent_enrollments WHERE token_id=%s AND agent_id=%s
                                          AND status='enrolled' LIMIT 1""", (t["id"], agent_id))):
            raise PermissionError("Token de instalação já atingiu o limite de usos")
    return t


def _public_url(request: Request, override: Optional[str] = None) -> str:
    if override:
        return override.rstrip("/")
    rows = _db_exec("SELECT value FROM server_settings WHERE category='general' AND key='public_url'")
    if rows and rows[0]["value"]:
        return rows[0]["value"].rstrip("/")
    return str(request.base_url).rstrip("/")


def bootstrap_script(server_url: str, token: str, skip_tls_check: bool = False) -> str:
    """Script PowerShell autossuficiente: baixa o pacote do Agent, instala e inscreve (ou só inscreve se já instalado)."""
    tls = ("" if not skip_tls_check else
           "add-type 'using System.Net;using System.Security.Cryptography.X509Certificates;public class GbocTrust:ICertificatePolicy{"
           "public bool CheckValidationResult(ServicePoint a,X509Certificate b,WebRequest c,int d){return true;}}'\n"
           "[System.Net.ServicePointManager]::CertificatePolicy = New-Object GbocTrust\n")
    return f"""# GBOC Agent — instalação e inscrição automática no GBOC Server
# Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}. Execute como Administrador (ou via GPO/Intune como SYSTEM).
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# '#Requires' é ignorado quando o script chega por 'iwr | iex': confere aqui
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{
    throw 'Execute o PowerShell como Administrador (ou via GPO/Intune como SYSTEM) para instalar o GBOC Agent.'
}}
$Server = '{server_url}'
$Token = '{token}'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
{tls}$seedDir = 'C:\\ProgramData\\GBOC'
New-Item -ItemType Directory -Force -Path $seedDir | Out-Null
$svc = Get-Service -Name 'GBOCAgent' -ErrorAction SilentlyContinue
if ($svc) {{
    # Agente já instalado: apenas inscreve neste Server (o serviço processa o enroll.json ao reiniciar)
    @{{ server_url = $Server; install_token = $Token }} | ConvertTo-Json | Set-Content -Path "$seedDir\\enroll.json" -Encoding UTF8
    Restart-Service 'GBOCAgent'
    Write-Host 'GBOC Agent já instalado: inscrição agendada no serviço.' -ForegroundColor Green
    exit 0
}}
$work = Join-Path $env:TEMP 'gboc-agent-install'
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $work | Out-Null
Write-Host 'Baixando o pacote do GBOC Agent...' -ForegroundColor Cyan
Invoke-WebRequest -UseBasicParsing -Uri "$Server/api/v1/enroll/package?token=$Token" -OutFile "$work\\agent.zip"
Expand-Archive -Path "$work\\agent.zip" -DestinationPath "$work\\src" -Force
$inst = Get-ChildItem "$work\\src" -Recurse -Filter 'install_agent.ps1' | Where-Object {{ Test-Path (Join-Path $_.DirectoryName 'agent_server.py') }} | Select-Object -First 1
if (-not $inst) {{ throw 'Pacote do Agent inválido (install_agent.ps1 não encontrado).' }}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $inst.FullName -ServerURL $Server -InstallToken $Token -Unattended
if ($LASTEXITCODE -ne 0) {{ throw "Instalador terminou com código $LASTEXITCODE" }}
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
Write-Host 'GBOC Agent instalado e inscrito no Server.' -ForegroundColor Green
"""


# ───────────────────────── rotas públicas (token) ─────────────────────────

@router.post("/api/v1/enroll")
async def enroll(request: Request):
    ip = request.client.host if request.client else "?"
    if _rate_limited(ip):
        raise HTTPException(429, "Muitas tentativas inválidas — aguarde alguns minutos")
    b = await request.json() or {}
    token = str(b.get("token") or "").strip()
    agent_id = str(b.get("agent_id") or "").strip()[:100]
    hostname = str(b.get("hostname") or "").strip()[:255] or agent_id[:12]
    if not agent_id:
        raise HTTPException(400, "agent_id obrigatório")
    try:
        t = await asyncio.to_thread(_valid_token, token, False, agent_id)
    except PermissionError as e:
        _fail(ip)
        raise HTTPException(403, str(e))
    from modules.multitenant.licensing import can_add_agent
    ok, msg = await asyncio.to_thread(can_add_agent, agent_id, t.get("tenant_id"))
    if not ok:
        await asyncio.to_thread(_db_exec, """INSERT INTO agent_enrollments (token_id, agent_id, hostname, ip_address, tenant_id, status, message)
                                             VALUES (%s,%s,%s,%s,%s,'rejected',%s)""", (t["id"], agent_id, hostname, ip, t.get("tenant_id"), msg), False)
        raise HTTPException(403, msg)
    from modules.agents.agent_pairing import get_pairing_key
    key = await asyncio.to_thread(get_pairing_key)
    if not key:
        raise HTTPException(503, "Chave de pareamento não configurada no Server")

    def _register():
        # Mesma máquina repetindo a inscrição com o mesmo token (script executado de novo, nova tentativa) não
        # gasta outro uso. O consumo é atômico: duas máquinas ao mesmo tempo não passam do limite.
        again = _db_exec("""SELECT 1 FROM agent_enrollments WHERE token_id=%s AND agent_id=%s AND status='enrolled' LIMIT 1""",
                         (t["id"], agent_id))
        if not again:
            took = _db_exec("""UPDATE install_tokens SET uses = uses + 1, last_used_at = LOCALTIMESTAMP
                               WHERE id=%s AND revoked_at IS NULL AND (COALESCE(max_uses,0) = 0 OR uses < max_uses)
                               RETURNING id""", (t["id"],))
            if not took:
                raise PermissionError("Token de instalação já atingiu o limite de usos")
        else:
            _db_exec("UPDATE install_tokens SET last_used_at = LOCALTIMESTAMP WHERE id=%s", (t["id"],), False)
        _db_exec("""INSERT INTO agents (agent_id, hostname, ip_address, os_info, status, tenant_id, tenant_locked, last_heartbeat)
                    VALUES (%s, %s, %s, %s, 'offline', %s, %s, NULL)
                    ON CONFLICT (agent_id) DO UPDATE SET hostname=EXCLUDED.hostname,
                        tenant_id=COALESCE(EXCLUDED.tenant_id, agents.tenant_id),
                        tenant_locked=(EXCLUDED.tenant_id IS NOT NULL) OR agents.tenant_locked""",
                 (agent_id, hostname, f"{ip}:9200", str(b.get("os_info") or "")[:255], t.get("tenant_id"), bool(t.get("tenant_id"))), False)
        _db_exec("""INSERT INTO agent_enrollments (token_id, agent_id, hostname, ip_address, tenant_id, status, message)
                    VALUES (%s,%s,%s,%s,%s,'enrolled',NULL)""", (t["id"], agent_id, hostname, ip, t.get("tenant_id")), False)
        org = _db_exec("SELECT name FROM msp_organizations WHERE org_id=%s", (t.get("tenant_id"),)) if t.get("tenant_id") else []
        return org[0]["name"] if org else None
    try:
        tenant_name = await asyncio.to_thread(_register)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return {"status": "success", "pairing_key": key, "tenant_id": t.get("tenant_id"), "tenant_name": tenant_name,
            "server_url": await asyncio.to_thread(_public_url, request)}


@router.get("/api/v1/enroll/package")
async def enroll_package(token: str, request: Request):
    ip = request.client.host if request.client else "?"
    if _rate_limited(ip):
        raise HTTPException(429, "Muitas tentativas inválidas — aguarde alguns minutos")
    try:
        await asyncio.to_thread(_valid_token, token)
    except PermissionError as e:
        _fail(ip)
        raise HTTPException(403, str(e))
    from modules.agents.fleet_ops import UPDATES_DIR, current_package
    pkg = await asyncio.to_thread(current_package)
    if not pkg:
        raise HTTPException(404, "Nenhum pacote do GBOC Agent publicado no Server (Gerenciamento Remoto > Operações em lote)")
    return FileResponse(os.path.join(UPDATES_DIR, f"{pkg['sha256']}.zip"), media_type="application/zip",
                        filename=f"gboc_agent_{pkg.get('version') or 'pacote'}.zip")


@router.get("/api/v1/enroll/script", response_class=PlainTextResponse)
async def enroll_script(token: str, request: Request, insecure: int = 0):
    ip = request.client.host if request.client else "?"
    if _rate_limited(ip):
        raise HTTPException(429, "Muitas tentativas inválidas — aguarde alguns minutos")
    try:
        await asyncio.to_thread(_valid_token, token)
    except PermissionError as e:
        _fail(ip)
        raise HTTPException(403, str(e))
    url = await asyncio.to_thread(_public_url, request)
    return PlainTextResponse(bootstrap_script(url, token, bool(insecure)), media_type="text/plain; charset=utf-8")


# ───────────────────────── administração ─────────────────────────

def _require_admin(request: Request) -> Dict[str, Any]:
    u = getattr(request.state, "user", None) or {}
    role = (u.get("role") or "").lower()
    if role and role not in ("admin", "superadmin", "administrator", "operator"):
        raise HTTPException(403, "Requer perfil admin ou operator.")
    return u


def _ser(r: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: (v.isoformat(sep=" ", timespec="seconds") if hasattr(v, "isoformat") else v) for k, v in r.items() if k != "token_hash"}
    exp = r.get("expires_at")
    out["state"] = ("revogado" if r.get("revoked_at") else "expirado" if exp and exp < datetime.now()
                    else "esgotado" if r.get("max_uses") and r["uses"] >= r["max_uses"] else "ativo")
    return out


@router.get("/api/v1/fleet/install-tokens")
async def list_tokens():
    await asyncio.to_thread(ensure_schema)
    rows = await asyncio.to_thread(_db_exec, """SELECT t.*, o.name AS tenant_name FROM install_tokens t
                                                LEFT JOIN msp_organizations o ON o.org_id = t.tenant_id ORDER BY t.id DESC""")
    enr = await asyncio.to_thread(_db_exec, """SELECT e.*, t.name AS token_name FROM agent_enrollments e
                                               LEFT JOIN install_tokens t ON t.id = e.token_id ORDER BY e.id DESC LIMIT 100""")
    pub = await asyncio.to_thread(_db_exec, "SELECT value FROM server_settings WHERE category='general' AND key='public_url'")
    return {"status": "success", "tokens": [_ser(r) for r in rows],
            "enrollments": [{k: (v.isoformat(sep=" ", timespec="seconds") if hasattr(v, "isoformat") else v) for k, v in e.items()} for e in enr],
            "public_url": (pub[0]["value"] if pub else "") or ""}


@router.post("/api/v1/fleet/install-tokens")
async def create_token(request: Request):
    u = _require_admin(request)
    b = await request.json() or {}
    name = str(b.get("name") or "").strip()[:120] or "Token de instalação"
    tenant = (str(b.get("tenant_id")).strip() or None) if b.get("tenant_id") else None
    try:
        days = max(1, min(365, int(b.get("expires_days") or 7)))
        max_uses = max(0, min(100000, int(b.get("max_uses") or 0)))
    except (TypeError, ValueError):
        raise HTTPException(400, "Validade/limite inválidos")
    await asyncio.to_thread(ensure_schema)
    if tenant and not await asyncio.to_thread(_db_exec, "SELECT 1 FROM msp_organizations WHERE org_id=%s", (tenant,)):
        raise HTTPException(404, "Cliente não encontrado")
    public_url = str(b.get("public_url") or "").strip().rstrip("/")
    if public_url:
        if not public_url.startswith(("http://", "https://")):
            raise HTTPException(400, "A URL do Server deve começar com http:// ou https://")
        await asyncio.to_thread(_db_exec, """INSERT INTO server_settings (category, key, value, type, description)
            VALUES ('general', 'public_url', %s, 'text', 'URL do Server acessada pelos agentes') ON CONFLICT (category, key)
            DO UPDATE SET value = EXCLUDED.value""", (public_url,), False)
    token = TOKEN_PREFIX + secrets.token_urlsafe(24)
    rows = await asyncio.to_thread(_db_exec, """INSERT INTO install_tokens (name, token_hash, token_prefix, tenant_id, expires_at, max_uses, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (name, _hash(token), token[:10], tenant, datetime.now() + timedelta(days=days), max_uses, u.get("username") or "?"))
    url = await asyncio.to_thread(_public_url, request, public_url or None)
    self_signed = bool(b.get("self_signed"))
    if self_signed:
        # Certificado autoassinado: o PowerShell 5.1 recusa o 'iwr' antes mesmo de baixar o script.
        # Sem '$' no comando: colado num PowerShell, o '$true' seria expandido pelo shell externo.
        one_liner = (f"powershell -NoProfile -ExecutionPolicy Bypass -Command \"[Net.ServicePointManager]::SecurityProtocol="
                     f"[Net.SecurityProtocolType]::Tls12; [Net.ServicePointManager]::ServerCertificateValidationCallback={{ 1 -eq 1 }}; "
                     f"iwr -UseBasicParsing '{url}/api/v1/enroll/script?token={token}&insecure=1' | iex\"")
    else:
        one_liner = (f"powershell -NoProfile -ExecutionPolicy Bypass -Command \"iwr -UseBasicParsing "
                     f"'{url}/api/v1/enroll/script?token={token}' | iex\"")
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    warning = ("A URL do Server usa 'localhost' — as outras máquinas não conseguem acessá-la. Informe o nome ou IP "
               "do Server na rede." if host in ("localhost", "127.0.0.1", "::1") else None)
    try:
        await asyncio.to_thread(_db_exec, "INSERT INTO server_auth_audit (user_id, username, action, ip_address, details) VALUES (%s,%s,%s,%s,%s)",
                                (u.get("user_id") or u.get("id"), u.get("username"), "fleet.install_token.create",
                                 request.client.host if request.client else None, f"token={token[:10]}… cliente={tenant} dias={days} usos={max_uses}"), False)
    except Exception:
        pass
    return {"status": "success", "token": token, "record": _ser(rows[0]), "server_url": url, "one_liner": one_liner,
            "script": bootstrap_script(url, token, self_signed), "warning": warning, "manual": f".\\install_agent.ps1 -ServerURL \"{url}\" -InstallToken \"{token}\" -Unattended"}


@router.post("/api/v1/fleet/install-tokens/{token_id}/revoke")
async def revoke_token(token_id: int, request: Request):
    _require_admin(request)
    rows = await asyncio.to_thread(_db_exec, "UPDATE install_tokens SET revoked_at=LOCALTIMESTAMP WHERE id=%s AND revoked_at IS NULL RETURNING *",
                                   (token_id,))
    if not rows:
        raise HTTPException(404, "Token não encontrado ou já revogado")
    return {"status": "success", "record": _ser(rows[0])}
