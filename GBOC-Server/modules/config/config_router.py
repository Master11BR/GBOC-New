# GBOC System v14.0.0 Enterprise Edition
# Module: Server Settings Router

import logging
import os
import json
import time
import urllib.request
from typing import Dict, Any
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("gboc_config_module")
router = APIRouter(prefix="/api/v1/server/config", tags=["Configurações"])

_EXCHANGE_RATE_CACHE = {"rate": 5.50, "timestamp": 0}
_REPORTS_CONFIG_CACHE = {
    "cloud_storage_cost_usd_per_tb": 7.99,
    "auto_currency_conversion": True,
    "target_currency": "BRL"
}


def get_usd_to_brl_rate() -> float:
    """Obtém a taxa de câmbio comercial do dia USD -> BRL em tempo real com fallback automático."""
    now = time.time()
    if now - _EXCHANGE_RATE_CACHE["timestamp"] < 3600 and _EXCHANGE_RATE_CACHE["rate"] > 0:
        return _EXCHANGE_RATE_CACHE["rate"]

    try:
        req = urllib.request.Request(
            "https://economia.awesomeapi.com.br/json/last/USD-BRL",
            headers={"User-Agent": "GBOC-System/14.0.0"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                rate = float(payload.get("USDBRL", {}).get("bid", 5.50))
                if rate > 0:
                    _EXCHANGE_RATE_CACHE["rate"] = rate
                    _EXCHANGE_RATE_CACHE["timestamp"] = now
                    return rate
    except Exception as err:
        logger.warning(f"Falha ao obter câmbio USD-BRL em tempo real (fallback 5.50): {err}")

    return _EXCHANGE_RATE_CACHE.get("rate", 5.50)


def get_reports_config() -> Dict[str, Any]:
    """Retorna as configurações do módulo de relatórios."""
    return _REPORTS_CONFIG_CACHE


@router.get("")
async def get_server_settings():
    """Retorna as configurações globais do GBOC Server, incluindo a aba Relatórios."""
    rate = get_usd_to_brl_rate()
    usd_per_tb = _REPORTS_CONFIG_CACHE["cloud_storage_cost_usd_per_tb"]
    brl_per_tb = round(usd_per_tb * rate, 2)

    return JSONResponse({
        "status": "success",
        "settings": {
            "server_title": "GBOC Operations Center v14.0.0 Enterprise",
            "http_port": int(os.getenv("SERVER_PORT", "8000")),
            "ai_provider": os.getenv("GBOC_AI_PROVIDER", "ollama"),
            "ai_model": os.getenv("GBOC_AI_MODEL", "llama3"),
            "tls_enabled": True,
            "reports": {
                "cloud_storage_cost_usd_per_tb": usd_per_tb,
                "cloud_storage_cost_brl_per_tb": brl_per_tb,
                "current_exchange_rate_usd_brl": rate,
                "auto_currency_conversion": _REPORTS_CONFIG_CACHE["auto_currency_conversion"],
                "target_currency": _REPORTS_CONFIG_CACHE["target_currency"]
            }
        }
    })


@router.post("")
@router.put("")
async def update_server_settings(request: Request):
    """Atualiza configurações globais do servidor e módulo de relatórios."""
    try:
        data = await request.json()
        if "reports" in data:
            rep_cfg = data["reports"]
            if "cloud_storage_cost_usd_per_tb" in rep_cfg:
                _REPORTS_CONFIG_CACHE["cloud_storage_cost_usd_per_tb"] = float(rep_cfg["cloud_storage_cost_usd_per_tb"])
            if "auto_currency_conversion" in rep_cfg:
                _REPORTS_CONFIG_CACHE["auto_currency_conversion"] = bool(rep_cfg["auto_currency_conversion"])

        rate = get_usd_to_brl_rate()
        usd_per_tb = _REPORTS_CONFIG_CACHE["cloud_storage_cost_usd_per_tb"]
        brl_per_tb = round(usd_per_tb * rate, 2)

        return JSONResponse({
            "status": "success",
            "message": "Configurações salvas com sucesso",
            "reports": {
                "cloud_storage_cost_usd_per_tb": usd_per_tb,
                "cloud_storage_cost_brl_per_tb": brl_per_tb,
                "current_exchange_rate_usd_brl": rate,
                "auto_currency_conversion": _REPORTS_CONFIG_CACHE["auto_currency_conversion"]
            }
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
