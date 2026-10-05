"""
GBOC Agent — Janela de manutenção e limite de banda.

  * Janelas de manutenção: períodos (dias da semana + horário, inclusive cruzando a meia-noite) em que
    backups AGENDADOS não iniciam. Execuções manuais continuam permitidas.
  * Limite de banda de upload: valor padrão + regras por dia/horário (ex.: 20 Mbps em horário comercial,
    sem limite à noite). Aplicado no início de cada backup: restic (--limit-upload), Kopia (throttle do
    repositório), Duplicati (--throttle-upload) e motor nativo em nuvem (upload controlado).

Armazenado na tabela settings do agente (categoria 'operation'); pode ser definido localmente ou
pelas políticas centrais do GBOC Server.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("gboc_operation")

KEY_WINDOWS = "maintenance_windows"
KEY_BANDWIDTH = "bandwidth_limits"
KEY_POLICY = "central_policy"
DAYS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_cache: Dict[str, Any] = {"ts": None, "data": None}
_lock = threading.Lock()
recent_skips: deque = deque(maxlen=50)


def _core():
    from shared_core import get_shared_core
    return get_shared_core()


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def validate_windows(windows: Any) -> List[Dict[str, Any]]:
    if windows in (None, ""):
        return []
    if not isinstance(windows, list):
        raise ValueError("Janelas de manutenção devem ser uma lista")
    out = []
    for w in windows[:20]:
        days = sorted({int(d) for d in (w.get("days") or []) if str(d).lstrip("-").isdigit() and 0 <= int(d) <= 6})
        start, end = str(w.get("start") or ""), str(w.get("end") or "")
        if not days or not _HHMM.match(start) or not _HHMM.match(end) or start == end:
            raise ValueError("Janela inválida: informe dias e horários HH:MM (início diferente do fim)")
        out.append({"days": days, "start": start, "end": end, "label": str(w.get("label") or "")[:80]})
    return out


def validate_bandwidth(bw: Any) -> Dict[str, Any]:
    bw = bw or {}
    try:
        default = max(0.0, float(bw.get("default_mbps") or 0))
    except (TypeError, ValueError):
        raise ValueError("Limite padrão inválido")
    rules = []
    for r in (bw.get("rules") or [])[:20]:
        days = sorted({int(d) for d in (r.get("days") or []) if str(d).isdigit() and 0 <= int(d) <= 6})
        start, end = str(r.get("start") or ""), str(r.get("end") or "")
        try:
            mbps = max(0.0, float(r.get("mbps") or 0))
        except (TypeError, ValueError):
            raise ValueError("Limite inválido em uma regra")
        if not days or not _HHMM.match(start) or not _HHMM.match(end) or start == end:
            raise ValueError("Regra de banda inválida: informe dias e horários HH:MM")
        rules.append({"days": days, "start": start, "end": end, "mbps": mbps})
    return {"default_mbps": default, "rules": rules}


def _active(rule: Dict[str, Any], now: datetime) -> bool:
    """Regra/janela ativa agora? Janelas que cruzam a meia-noite valem a partir do dia de início."""
    s, e = _minutes(rule["start"]), _minutes(rule["end"])
    cur = now.hour * 60 + now.minute
    wd = now.weekday()
    if s < e:
        return wd in rule["days"] and s <= cur < e
    # cruza a meia-noite: parte da noite do dia de início ou madrugada do dia seguinte
    prev = (wd - 1) % 7
    return (wd in rule["days"] and cur >= s) or (prev in rule["days"] and cur < e)


def describe(rule: Dict[str, Any]) -> str:
    return f"{', '.join(DAYS_PT[d] for d in rule['days'])} {rule['start']}–{rule['end']}"


def load(force: bool = False) -> Dict[str, Any]:
    with _lock:
        if not force and _cache["data"] is not None and _cache["ts"] and (datetime.now() - _cache["ts"]).total_seconds() < 30:
            return _cache["data"]
    data = {KEY_WINDOWS: [], KEY_BANDWIDTH: {"default_mbps": 0, "rules": []}, KEY_POLICY: None}
    try:
        with _core().get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM settings WHERE key = ANY(%s)", ([KEY_WINDOWS, KEY_BANDWIDTH, KEY_POLICY],))
            for k, v in cur.fetchall():
                try:
                    data[k] = json.loads(v) if isinstance(v, str) else v
                except ValueError:
                    pass
            cur.close()
    except Exception as e:
        logger.debug(f"configurações de operação indisponíveis: {e}")
    with _lock:
        _cache.update(ts=datetime.now(), data=data)
    return data


def save(windows: Any = None, bandwidth: Any = None, policy: Any = "__keep__") -> Dict[str, Any]:
    values = {}
    if windows is not None:
        values[KEY_WINDOWS] = validate_windows(windows)
    if bandwidth is not None:
        values[KEY_BANDWIDTH] = validate_bandwidth(bandwidth)
    if policy != "__keep__":
        values[KEY_POLICY] = policy
    with _core().get_db_connection() as conn:
        cur = conn.cursor()
        for k, v in values.items():
            cur.execute("""INSERT INTO settings (category, key, value, type, description) VALUES ('operation', %s, %s, 'json', %s)
                           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, category = 'operation', updated_at = CURRENT_TIMESTAMP""",
                        (k, json.dumps(v, ensure_ascii=False), {"maintenance_windows": "Janelas de manutenção",
                                                                 "bandwidth_limits": "Limite de banda de upload",
                                                                 "central_policy": "Política central aplicada"}[k]))
        conn.commit()
        cur.close()
    return load(force=True)


def in_maintenance(now: Optional[datetime] = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
    now = now or datetime.now()
    for w in load().get(KEY_WINDOWS) or []:
        try:
            if _active(w, now):
                return True, w
        except Exception:
            continue
    return False, None


def current_upload_mbps(now: Optional[datetime] = None) -> float:
    now = now or datetime.now()
    bw = load().get(KEY_BANDWIDTH) or {}
    for r in bw.get("rules") or []:
        try:
            if _active(r, now):
                return float(r.get("mbps") or 0)
        except Exception:
            continue
    return float(bw.get("default_mbps") or 0)


def mbps_to_kib(mbps: float) -> int:
    """Mbps (megabits/s) → KiB/s (unidade do restic --limit-upload)."""
    return max(1, int(mbps * 1_000_000 / 8 / 1024)) if mbps and mbps > 0 else 0


def _skips_file() -> str:
    import os
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(os.path.join(base, "data"), exist_ok=True)
    return os.path.join(base, "data", "maintenance_skips.json")


def _read_skips() -> List[Dict[str, Any]]:
    try:
        with open(_skips_file(), encoding="utf-8") as f:
            return json.load(f)[:50]
    except Exception:
        return list(recent_skips)


def record_skip(task_id: Any, task_name: str, window: Dict[str, Any]) -> None:
    """Registra o adiamento (arquivo compartilhado: o agendador pode rodar em outro processo/serviço)."""
    item = {"at": datetime.now().isoformat(sep=" ", timespec="seconds"), "task_id": task_id,
            "task_name": task_name, "window": describe(window), "label": window.get("label")}
    prev = _read_skips()
    if prev and prev[0].get("task_id") == task_id and str(prev[0].get("at", ""))[:16] == item["at"][:16]:
        return                                  # mesmo minuto já registrado (mais de um agendador ativo)
    recent_skips.appendleft(item)
    try:
        items = [item] + prev
        with open(_skips_file(), "w", encoding="utf-8") as f:
            json.dump(items[:50], f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"registro de adiamento: {e}")
    logger.info(f"⏸️ [MANUTENÇÃO] Tarefa agendada '{task_name}' não iniciada: janela {describe(window)}")


def status() -> Dict[str, Any]:
    data = load(force=True)
    active, win = in_maintenance()
    mbps = current_upload_mbps()
    nxt = None
    now = datetime.now().replace(second=0, microsecond=0)
    if not active and data.get(KEY_WINDOWS):
        for i in range(1, 7 * 24 * 60 + 1, 5):             # próxima janela (passo de 5 min, até 7 dias)
            t = now + timedelta(minutes=i)
            on, w = in_maintenance(t)
            if on:
                nxt = {"at": t.isoformat(sep=" ", timespec="minutes"), "window": describe(w)}
                break
    return {"maintenance_windows": data.get(KEY_WINDOWS) or [], "bandwidth": data.get(KEY_BANDWIDTH) or {},
            "central_policy": data.get(KEY_POLICY),
            "now": {"in_maintenance": active, "window": describe(win) if win else None, "upload_limit_mbps": mbps},
            "next_window": nxt, "recent_skips": _read_skips()}


class ThrottledReader:
    """Leitor de arquivo que limita a taxa de leitura (usado no upload em nuvem do motor nativo)."""

    def __init__(self, fobj, bytes_per_second: float, chunk: int = 64 * 1024):
        self.f = fobj
        self.rate = float(bytes_per_second)
        self.chunk = chunk
        self.sent = 0
        self.t0 = None

    def __iter__(self):
        import time
        self.t0 = time.monotonic()
        while True:
            data = self.f.read(self.chunk)
            if not data:
                break
            self.sent += len(data)
            expected = self.sent / self.rate
            elapsed = time.monotonic() - self.t0
            if expected > elapsed:
                time.sleep(expected - elapsed)
            yield data
