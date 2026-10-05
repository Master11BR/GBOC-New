"""
GBOC Server — Marca nos relatórios (white-label por cliente).

  * marca padrão ("_default"): a do provedor/MSP — usada em todos os relatórios;
  * marca por cliente (tenant_id de msp_organizations): nome, logotipo, cor, rodapé e contato do cliente,
    com "Relatório preparado por <provedor>"; e a lista de e-mails do cliente para envio automático.

Rotas: GET /api/v1/reports/branding · GET|PUT|DELETE /api/v1/reports/branding/{key}
"""
from __future__ import annotations

import asyncio
import base64
import re
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/v1/reports/branding", tags=["Relatórios - Marca"])
DEFAULT_KEY = "_default"
MAX_LOGO_BYTES = 300 * 1024
SCHEMA = """CREATE TABLE IF NOT EXISTS report_branding (
    scope_key VARCHAR(100) PRIMARY KEY,
    display_name TEXT,
    logo_data TEXT,
    primary_color VARCHAR(7),
    footer_text TEXT,
    contact TEXT,
    client_emails TEXT,
    updated_by TEXT,
    updated_at TIMESTAMP DEFAULT LOCALTIMESTAMP
)"""
_ready = False
_lock = threading.Lock()
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


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


def _company_name() -> str:
    rows = _db_exec("SELECT value FROM server_settings WHERE category='reports' AND key='company_name'")
    return (rows[0]["value"] if rows else "") or ""


def get_branding(tenant_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Marca efetiva para o relatório: cliente (se houver) sobre a padrão. None = visual GBOC padrão."""
    ensure_schema()
    rows = {r["scope_key"]: r for r in _db_exec("SELECT * FROM report_branding WHERE scope_key = ANY(%s)",
                                                ([DEFAULT_KEY] + ([tenant_id] if tenant_id else []),))}
    base = dict(rows.get(DEFAULT_KEY) or {})
    provider = base.get("display_name") or _company_name()
    if tenant_id and tenant_id in rows:
        t = rows[tenant_id]
        out = {"display_name": t.get("display_name"), "logo_data": t.get("logo_data") or None,
               "primary_color": t.get("primary_color") or base.get("primary_color"),
               "footer_text": t.get("footer_text") or base.get("footer_text"), "contact": t.get("contact") or base.get("contact"),
               "provider_name": provider, "client_emails": t.get("client_emails") or ""}
        if not out["display_name"]:
            org = _db_exec("SELECT name FROM msp_organizations WHERE org_id=%s", (tenant_id,))
            out["display_name"] = org[0]["name"] if org else tenant_id
        return out
    if base:
        return {"display_name": base.get("display_name") or provider, "logo_data": base.get("logo_data"),
                "primary_color": base.get("primary_color"), "footer_text": base.get("footer_text"), "contact": base.get("contact"),
                "provider_name": "", "client_emails": ""}
    return None


def client_emails(tenant_id: Optional[str]) -> List[str]:
    if not tenant_id:
        return []
    ensure_schema()
    rows = _db_exec("SELECT client_emails FROM report_branding WHERE scope_key=%s", (tenant_id,))
    raw = (rows[0]["client_emails"] if rows else "") or ""
    return [e.strip() for e in raw.replace(";", ",").split(",") if _EMAIL_RE.match(e.strip())]


def _ser(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v.isoformat(sep=" ", timespec="seconds") if hasattr(v, "isoformat") else v) for k, v in r.items()}


@router.get("")
async def list_branding():
    await asyncio.to_thread(ensure_schema)
    rows = await asyncio.to_thread(_db_exec, "SELECT * FROM report_branding ORDER BY scope_key")
    tenants = await asyncio.to_thread(_db_exec, """SELECT o.org_id, o.name, COUNT(a.agent_id) AS agents FROM msp_organizations o
                                                   LEFT JOIN agents a ON a.tenant_id = o.org_id GROUP BY o.org_id, o.name ORDER BY o.name""")
    return {"status": "success", "branding": [_ser(r) for r in rows], "tenants": tenants, "company_name": await asyncio.to_thread(_company_name)}


@router.get("/{key}")
async def read_branding(key: str):
    await asyncio.to_thread(ensure_schema)
    rows = await asyncio.to_thread(_db_exec, "SELECT * FROM report_branding WHERE scope_key=%s", (key,))
    return {"status": "success", "branding": _ser(rows[0]) if rows else None,
            "effective": await asyncio.to_thread(get_branding, None if key == DEFAULT_KEY else key)}


def _validate(key: str, b: Dict[str, Any]) -> Dict[str, Any]:
    from modules.reports import report_core as rc
    color = str(b.get("primary_color") or "").strip()
    if color and not re.match(r"^#[0-9a-fA-F]{6}$", color):
        raise HTTPException(400, "Cor inválida (use o formato #RRGGBB).")
    logo = str(b.get("logo_data") or "").strip()
    if logo:
        if not rc._LOGO_RE.match(logo):
            raise HTTPException(400, "Logotipo inválido: envie PNG, JPG, GIF, WEBP ou SVG.")
        try:
            raw = base64.b64decode(logo.split(",", 1)[1], validate=False)
        except Exception:
            raise HTTPException(400, "Logotipo corrompido.")
        if len(raw) > MAX_LOGO_BYTES:
            raise HTTPException(400, "Logotipo acima de 300 KB — reduza a imagem.")
    emails = [e.strip() for e in str(b.get("client_emails") or "").replace(";", ",").split(",") if e.strip()]
    bad = [e for e in emails if not _EMAIL_RE.match(e)]
    if bad:
        raise HTTPException(400, f"E-mail inválido: {bad[0]}")
    return {"display_name": str(b.get("display_name") or "").strip()[:120] or None, "logo_data": logo or None,
            "primary_color": color or None, "footer_text": str(b.get("footer_text") or "").strip()[:400] or None,
            "contact": str(b.get("contact") or "").strip()[:200] or None,
            "client_emails": ", ".join(emails) if key != DEFAULT_KEY else None}


@router.put("/{key}")
async def save_branding(key: str, request: Request):
    role = (((getattr(request.state, "user", None) or {}).get("role")) or "").lower()
    if role and role not in ("admin", "superadmin", "administrator", "operator"):
        raise HTTPException(403, "Requer perfil admin ou operator.")
    await asyncio.to_thread(ensure_schema)
    if key != DEFAULT_KEY:
        org = await asyncio.to_thread(_db_exec, "SELECT 1 FROM msp_organizations WHERE org_id=%s", (key,))
        if not org:
            raise HTTPException(404, "Cliente (organização) não encontrado.")
    v = _validate(key, await request.json() or {})
    user = ((getattr(request.state, "user", None) or {}).get("username")) or "?"
    rows = await asyncio.to_thread(_db_exec, """
        INSERT INTO report_branding (scope_key, display_name, logo_data, primary_color, footer_text, contact, client_emails, updated_by, updated_at)
        VALUES (%(k)s, %(display_name)s, %(logo_data)s, %(primary_color)s, %(footer_text)s, %(contact)s, %(client_emails)s, %(u)s, LOCALTIMESTAMP)
        ON CONFLICT (scope_key) DO UPDATE SET display_name=EXCLUDED.display_name, logo_data=EXCLUDED.logo_data,
            primary_color=EXCLUDED.primary_color, footer_text=EXCLUDED.footer_text, contact=EXCLUDED.contact,
            client_emails=EXCLUDED.client_emails, updated_by=EXCLUDED.updated_by, updated_at=LOCALTIMESTAMP
        RETURNING *""", {**v, "k": key, "u": user})
    return {"status": "success", "branding": _ser(rows[0])}


@router.delete("/{key}")
async def delete_branding(key: str, request: Request):
    role = (((getattr(request.state, "user", None) or {}).get("role")) or "").lower()
    if role and role not in ("admin", "superadmin", "administrator", "operator"):
        raise HTTPException(403, "Requer perfil admin ou operator.")
    await asyncio.to_thread(_db_exec, "DELETE FROM report_branding WHERE scope_key=%s", (key,), False)
    return {"status": "success"}
