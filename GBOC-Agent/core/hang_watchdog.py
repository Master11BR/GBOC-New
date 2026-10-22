"""
GBOC - Vigia de travamento do processo (Agente e Servidor).

Um batimento roda no laço assíncrono do FastAPI a cada 1 s. Se o laço parar de bater por mais de
STALL_SECONDS (padrão 10 s) - algo bloqueando o servidor web -, a pilha de TODAS as threads é gravada em
logs/hang_AAAAMMDD_HHMMSS.log (mostra exatamente o código que travou) e o evento é registrado; quando o
laço volta, registra quanto durou. Uma segunda captura é feita se o travamento passar de 60 s.

/api/watchdog/ping (sem login, sem dados sensíveis) responde se o laço está vivo; o serviço GBOCWatchdog
(scripts/gboc_watchdog.ps1) usa essa resposta para reiniciar o serviço quando ele congela de vez.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("gboc_hang_watchdog")

STALL_SECONDS = float(os.getenv("GBOC_HANG_STALL_SECONDS", "10"))
KEEP_DUMPS = 20

_state: Dict[str, Any] = {"app": "", "beat": None, "loop_thread": None, "stalls": 0, "in_stall": False,
                          "stall_started": None, "max_lag": 0.0, "last_stall": None, "dumped_long": False,
                          "logs_dir": None, "data_dir": None, "started_at": None}
_started = False
_lock = threading.Lock()


def _write_dump(reason: str, lag: float) -> Optional[str]:
    logs = _state["logs_dir"]
    try:
        os.makedirs(logs, exist_ok=True)
        path = os.path.join(logs, f"hang_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        frames = sys._current_frames()
        names = {t.ident: t.name for t in threading.enumerate()}
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"GBOC {_state['app']} - {reason}\nLaço sem responder há {lag:.1f} s (PID {os.getpid()})\n")
            f.write(f"Thread do laço: {_state['loop_thread']} ({names.get(_state['loop_thread'], '?')})\n\n")
            loop_tid = _state["loop_thread"]
            order = sorted(frames.items(), key=lambda kv: kv[0] != loop_tid)      # laço primeiro
            for tid, frame in order:
                f.write(f"===== Thread {tid} ({names.get(tid, '?')}){'  <-- LAÇO DO SERVIDOR WEB' if tid == loop_tid else ''}\n")
                f.write("".join(traceback.format_stack(frame)))
                f.write("\n")
        dumps = sorted(p for p in os.listdir(logs) if p.startswith("hang_") and p.endswith(".log"))
        for old in dumps[:-KEEP_DUMPS]:
            try:
                os.remove(os.path.join(logs, old))
            except OSError:
                pass
        return path
    except Exception as e:
        logger.warning(f"[VIGIA] não foi possível gravar a pilha do travamento: {e}")
        return None


def _loop_frame_summary() -> str:
    fr = sys._current_frames().get(_state["loop_thread"])
    if not fr:
        return "?"
    st = traceback.extract_stack(fr)[-3:]
    return " <- ".join(f"{os.path.basename(s.filename)}:{s.lineno} {s.name}" for s in reversed(st))


def _monitor() -> None:
    while True:
        time.sleep(2)
        beat = _state["beat"]
        if beat is None:
            continue
        lag = time.monotonic() - beat
        with _lock:
            _state["max_lag"] = max(_state["max_lag"], lag)
            if lag >= STALL_SECONDS and not _state["in_stall"]:
                _state.update(in_stall=True, stall_started=time.time() - lag, dumped_long=False)
                _state["stalls"] += 1
                where = _loop_frame_summary()
                path = _write_dump("TRAVAMENTO DETECTADO", lag)
                _state["last_stall"] = {"at": datetime.fromtimestamp(_state["stall_started"]).isoformat(sep=" ", timespec="seconds"),
                                        "where": where, "dump": path, "duration_s": None}
                logger.error(f"🧊 [VIGIA] {_state['app']} travado há {lag:.0f} s em {where} (pilha: {path})")
            elif _state["in_stall"] and lag >= 60 and not _state["dumped_long"]:
                _state["dumped_long"] = True
                path = _write_dump("TRAVAMENTO LONGO (60 s+)", lag)
                logger.error(f"🧊 [VIGIA] {_state['app']} continua travado ({lag:.0f} s) em {_loop_frame_summary()} (pilha: {path})")
            elif _state["in_stall"] and lag < 3:
                dur = time.time() - _state["stall_started"]
                _state["in_stall"] = False
                if _state["last_stall"]:
                    _state["last_stall"]["duration_s"] = round(dur, 1)
                logger.warning(f"✅ [VIGIA] {_state['app']} voltou a responder após {dur:.0f} s travado")


async def _heartbeat() -> None:
    _state["loop_thread"] = threading.get_ident()
    last_file = 0.0
    while True:
        _state["beat"] = time.monotonic()
        if _state["data_dir"] and time.monotonic() - last_file >= 5:
            last_file = time.monotonic()
            try:
                with open(os.path.join(_state["data_dir"], "heartbeat.json"), "w", encoding="utf-8") as f:
                    json.dump({"pid": os.getpid(), "at": datetime.now().isoformat(timespec="seconds"),
                               "stalls": _state["stalls"]}, f)
            except OSError:
                pass
        await asyncio.sleep(1)


def start(app_name: str, base_dir: str) -> None:
    """Chamar dentro do lifespan (com o laço rodando)."""
    global _started
    if _started:
        return
    _started = True
    _state.update(app=app_name, logs_dir=os.path.join(base_dir, "logs"), data_dir=os.path.join(base_dir, "data"),
                  started_at=datetime.now().isoformat(sep=" ", timespec="seconds"), beat=time.monotonic())
    asyncio.get_running_loop().create_task(_heartbeat())
    threading.Thread(target=_monitor, name="gboc-hang-watchdog", daemon=True).start()
    logger.info(f"[VIGIA] Vigia de travamento ativo ({app_name}, limite {STALL_SECONDS:g} s)")


def status() -> Dict[str, Any]:
    beat = _state["beat"]
    return {"app": _state["app"], "alive": True, "pid": os.getpid(),
            "loop_lag_s": round(time.monotonic() - beat, 2) if beat else None,
            "stalls": _state["stalls"], "in_stall": _state["in_stall"], "max_lag_s": round(_state["max_lag"], 1),
            "last_stall": _state["last_stall"], "started_at": _state["started_at"]}


def register(app) -> None:
    """Rota /api/watchdog/ping (pública: só diz se está vivo; usada pelo serviço GBOCWatchdog)."""
    async def _ping() -> Dict[str, Any]:
        s = status()
        return {"alive": True, "app": s["app"], "stalls": s["stalls"], "loop_lag_s": s["loop_lag_s"]}
    app.add_api_route("/api/watchdog/ping", _ping, methods=["GET"], include_in_schema=False)
