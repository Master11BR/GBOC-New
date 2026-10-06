"""
GBOC Agent — regra única do estado da ligação Agente → Servidor Central.

Usada pelo indicador do topbar (todas as telas), pela Visão Geral e pela API /api/server/status, para que
nenhuma tela mostre "Online" enquanto outra mostra "Offline" para a mesma coisa.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

LEGACY_DEFAULT_KEY = "gboc-local-server-key"


def compute_link_state(*, server_url: Optional[str], api_key: Optional[str], server_auth: str,
                       last_heartbeat: Optional[datetime], hb_fail_at: Optional[datetime],
                       websocket_connected: bool, started_at: Optional[datetime],
                       heartbeat_minutes: Any = 2, key_label: str = "", now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now()
    try:
        interval = max(1, int(heartbeat_minutes or 2))
    except (TypeError, ValueError):
        interval = 2
    limit = max(5, 3 * interval) * 60
    if not server_url or not api_key or api_key == LEGACY_DEFAULT_KEY:
        return {"state": "not_configured", "connected": False,
                "detail": "Servidor Central não configurado (Configurações > Servidor Central)"}
    if server_auth == "rejected":
        return {"state": "key_rejected", "connected": False,
                "detail": f"O Server recusou a chave de pareamento {key_label}".strip()}
    hb = last_heartbeat
    if hb_fail_at and (not hb or hb_fail_at > hb) and not websocket_connected:
        return {"state": "no_contact", "connected": False,
                "detail": f"O Server ({server_url}) não respondeu ao último heartbeat ({hb_fail_at.strftime('%d/%m %H:%M:%S')})"}
    if (hb and (now - hb).total_seconds() <= limit) or websocket_connected:
        return {"state": "connected", "connected": True,
                "detail": f"Último heartbeat aceito: {hb.strftime('%d/%m %H:%M:%S') if hb else '—'}"
                          f"{' · canal em tempo real ativo' if websocket_connected else ''}"}
    if not hb and started_at and (now - started_at).total_seconds() <= limit:
        return {"state": "starting", "connected": False, "detail": "Aguardando o primeiro heartbeat"}
    return {"state": "no_contact", "connected": False,
            "detail": f"Sem resposta do Server ({server_url}) desde {hb.strftime('%d/%m %H:%M') if hb else 'o início do serviço'}"}
