"""
GBOC — métricas de CPU sem bloquear requisições (arquivo idêntico no Agente e no Server).

Problema: várias rotas chamavam psutil.cpu_percent(interval=1) / (interval=0.5) — isso DORME 0,5–1,5 s.
Dentro de rotas assíncronas, o servidor inteiro parava durante esse tempo; /api/system/info (chamado em toda
troca de tela pelo cabeçalho) dormia 1,5 s a cada chamada. Além disso platform.processor() no Windows consulta
o WMI a cada chamada (lento).

Solução: uma thread amostra a CPU a cada 1 s; psutil.cpu_percent(...) passa a devolver a última amostra
imediatamente (mesma média de 1 s, sem esperar). platform.processor() é calculado uma única vez.
Process.cpu_percent (por processo) não é alterado.
"""
from __future__ import annotations

import functools
import logging
import os
import platform
import threading
import time

logger = logging.getLogger("gboc.fast_metrics")

_state = {"total": 0.0, "percpu": [], "ts": 0.0}
_installed = False


def _sampler(orig) -> None:
    while True:
        try:
            per = orig(interval=1.0, percpu=True)          # 1 s de amostra, fora das requisições
            _state["percpu"] = per
            _state["total"] = round(sum(per) / len(per), 1) if per else 0.0
            _state["ts"] = time.monotonic()
        except Exception:
            time.sleep(5)


def install() -> bool:
    """Idempotente. GBOC_FAST_METRICS=0 desativa."""
    global _installed
    if _installed or os.getenv("GBOC_FAST_METRICS", "1") == "0":
        return False
    try:
        import psutil
    except Exception:
        return False
    orig = psutil.cpu_percent

    def cpu_percent(interval=None, percpu=False):
        # Sem amostra ainda (primeiro segundo após iniciar): mede rápido sem dormir
        if not _state["ts"]:
            return orig(interval=None, percpu=percpu)
        return list(_state["percpu"]) if percpu else _state["total"]

    cpu_percent.__doc__ = orig.__doc__
    psutil.cpu_percent = cpu_percent
    threading.Thread(target=_sampler, args=(orig,), name="gboc-cpu-sampler", daemon=True).start()
    platform.processor = functools.lru_cache(maxsize=1)(platform.processor)
    _installed = True
    logger.info("Métricas de CPU em segundo plano ativas (rotas não esperam mais pela amostragem)")
    return True
