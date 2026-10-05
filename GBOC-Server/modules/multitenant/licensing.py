"""
GBOC Server — Licenciamento por número de agentes.

Licença = token assinado (Ed25519) pelo fornecedor do GBOC:
    base64url(JSON) "." base64url(assinatura)
    JSON: {"product": "GBOC", "id", "customer", "max_agents", "expires" (AAAA-MM-DD), "issued", "features": [...]}

O Server só tem a CHAVE PÚBLICA (license_public_key.pem, gerada por tools/license_tool.py keygen); a chave
privada fica com o fornecedor. Sem chave pública ou sem licença instalada o Server funciona em modo
"avaliação" (sem bloqueio, com aviso). Com licença:
  * agentes NOVOS acima do limite não são aceitos (agentes já cadastrados continuam funcionando);
  * aviso a partir de 30 dias do vencimento; após vencer, 15 dias de carência; depois disso novos agentes
    são bloqueados até renovar.
Os limites por cliente (msp_organizations.max_agents) e organizações suspensas também valem para novos agentes.

Rotas: GET /api/v1/license · PUT /api/v1/license {license_key} · DELETE /api/v1/license
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("gboc_licensing")
router = APIRouter(prefix="/api/v1/license", tags=["Licenciamento"])

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PUBLIC_KEY_FILE = os.path.join(SERVER_DIR, "license_public_key.pem")
WARN_DAYS = 30
GRACE_DAYS = 15


def _db_exec(sql: str, params: Any = (), fetch: bool = True):
    from modules.reports.report_schedules import _exec
    return _exec(sql, params, fetch)


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _public_key():
    if not os.path.isfile(PUBLIC_KEY_FILE):
        return None
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    with open(PUBLIC_KEY_FILE, "rb") as f:
        return load_pem_public_key(f.read())


def decode_license(token: str, public_key=None) -> Dict[str, Any]:
    """Valida a assinatura e retorna o conteúdo. ValueError se inválida."""
    token = (token or "").strip()
    if token.count(".") != 1:
        raise ValueError("Formato de licença inválido")
    body, sig = token.split(".")
    key = public_key if public_key is not None else _public_key()
    if key is None:
        raise ValueError("Chave pública de licença não instalada no Server (license_public_key.pem)")
    try:
        key.verify(_b64d(sig), body.encode("ascii"))
    except Exception:
        raise ValueError("Assinatura da licença inválida")
    data = json.loads(_b64d(body))
    if data.get("product") != "GBOC":
        raise ValueError("Licença de outro produto")
    for k in ("customer", "max_agents", "expires"):
        if k not in data:
            raise ValueError(f"Licença sem o campo {k}")
    date.fromisoformat(str(data["expires"]))
    return data


def _stored_token() -> Optional[str]:
    rows = _db_exec("SELECT value FROM server_settings WHERE category='license' AND key='license_key'")
    return (rows[0]["value"] if rows else None) or None


def _agent_count(exclude: Optional[str] = None, tenant_id: Optional[str] = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM agents WHERE 1=1"
    p = []
    if exclude:
        sql += " AND agent_id <> %s"
        p.append(exclude)
    if tenant_id:
        sql += " AND tenant_id = %s"
        p.append(tenant_id)
    return int(_db_exec(sql, tuple(p))[0]["n"])


def status(today: Optional[date] = None) -> Dict[str, Any]:
    today = today or date.today()
    used = _agent_count()
    tok = _stored_token()
    base = {"used_agents": used, "public_key_installed": os.path.isfile(PUBLIC_KEY_FILE)}
    if not tok:
        return {**base, "state": "none", "message": "Sem licença instalada — modo avaliação (sem limite aplicado).", "enforced": False}
    try:
        lic = decode_license(tok)
    except ValueError as e:
        return {**base, "state": "invalid", "message": f"Licença inválida: {e}", "enforced": False}
    exp = date.fromisoformat(str(lic["expires"]))
    days_left = (exp - today).days
    if days_left < -GRACE_DAYS:
        state, msg = "expired", f"Licença vencida em {exp.strftime('%d/%m/%Y')} — novos agentes bloqueados até a renovação."
    elif days_left < 0:
        state, msg = "grace", (f"Licença vencida em {exp.strftime('%d/%m/%Y')}; carência até "
                               f"{(exp + timedelta(days=GRACE_DAYS)).strftime('%d/%m/%Y')}.")
    elif days_left <= WARN_DAYS:
        state, msg = "expiring", f"Licença vence em {days_left} dia(s) ({exp.strftime('%d/%m/%Y')})."
    else:
        state, msg = "valid", f"Licença válida até {exp.strftime('%d/%m/%Y')}."
    over = used > int(lic["max_agents"])
    if over:
        msg += f" Em uso {used} agentes, acima do limite de {lic['max_agents']}."
    return {**base, "state": state, "message": msg, "enforced": True, "customer": lic.get("customer"), "license_id": lic.get("id"),
            "max_agents": int(lic["max_agents"]), "expires": str(exp), "days_left": days_left, "issued": lic.get("issued"),
            "features": lic.get("features") or [], "over_limit": over}


def can_add_agent(agent_id: Optional[str], tenant_id: Optional[str]) -> Tuple[bool, str]:
    """Regra para um agente NOVO (já cadastrado sempre pode continuar)."""
    if agent_id and _db_exec("SELECT 1 FROM agents WHERE agent_id=%s", (agent_id,)):
        return True, ""
    st = status()
    if st["state"] == "expired":
        return False, st["message"]
    if st["enforced"] and st["state"] in ("valid", "expiring", "grace") and _agent_count(exclude=agent_id) >= st["max_agents"]:
        return False, f"Limite da licença atingido ({st['max_agents']} agentes). Amplie a licença para adicionar agentes."
    if tenant_id:
        org = _db_exec("SELECT name, max_agents, status FROM msp_organizations WHERE org_id=%s", (tenant_id,))
        if not org:
            return False, "Cliente (organização) não encontrado no Server"
        o = org[0]
        if str(o.get("status") or "active").lower() not in ("active", "ativo", "trial"):
            return False, f"Cliente {o['name']} está {o.get('status')} — novos agentes não são aceitos."
        if o.get("max_agents") and _agent_count(exclude=agent_id, tenant_id=tenant_id) >= int(o["max_agents"]):
            return False, f"Cliente {o['name']} atingiu o limite de {o['max_agents']} agente(s) do plano."
    return True, ""


def _require_admin(request: Request) -> None:
    role = (((getattr(request.state, "user", None) or {}).get("role")) or "").lower()
    if role and role not in ("admin", "superadmin", "administrator"):
        raise HTTPException(403, "Somente administradores podem alterar a licença.")


@router.get("")
async def get_license():
    return {"status": "success", "license": await asyncio.to_thread(status)}


@router.put("")
async def put_license(request: Request):
    _require_admin(request)
    b = await request.json() or {}
    tok = str(b.get("license_key") or "").strip()
    try:
        lic = await asyncio.to_thread(decode_license, tok)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await asyncio.to_thread(_db_exec, """INSERT INTO server_settings (category, key, value, type, description)
        VALUES ('license', 'license_key', %s, 'text', 'Licença do GBOC Server') ON CONFLICT (category, key)
        DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP""", (tok,), False)
    logger.warning(f"[LICENÇA] Instalada licença {lic.get('id')} — {lic.get('customer')}, {lic.get('max_agents')} agentes até {lic.get('expires')}")
    return await get_license()


@router.delete("")
async def delete_license(request: Request):
    _require_admin(request)
    await asyncio.to_thread(_db_exec, "DELETE FROM server_settings WHERE category='license' AND key='license_key'", (), False)
    return await get_license()
