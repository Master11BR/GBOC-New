"""
GBOC Agent - Controle de rede e de carga durante os backups (aplicado AO VIVO, não só no início).

Fontes de decisão (vale a mais restritiva):
  * Agendado: regras de banda por dia/horário (operation_settings.bandwidth_limits). Cada regra limita
    (mbps) ou PAUSA ("action": "pause"). Um backup que começou de madrugada passa a respeitar o horário de
    pico quando ele chega, e volta ao normal quando ele termina.
  * Automático: dois sinais medidos de verdade -
      1. tráfego de OUTROS programas na placa de rede deste computador (ex.: usuários do Terminal Server);
      2. latência do link de internet (tempo de conexão TCP a hosts externos): sobe quando o link inteiro
         congestiona, inclusive pelo tráfego dos outros computadores da rede.
    Congestionado -> reduz (diminuição multiplicativa); livre -> volta a subir aos poucos; congestionamento
    forte e contínuo -> pausa. A capacidade de upload do link é aprendida (maior upload real medido nos
    últimos 30 dias) ou informada manualmente.
  * Proteção da máquina: CPU / memória / disco críticos -> pausa; altos -> limita. Motores externos rodam
    com prioridade baixa de CPU e de disco.
  * Manual: throttle definido na tela do Hermes (antes ele não tinha efeito nos backups).

Aplicação:
  * motor nativo (nuvem): limitador global compartilhado por todas as conexões (consume) - o limite e a
    pausa valem no meio do envio;
  * restic / Kopia / Duplicati CLI / Borg (processos filhos do Agente): limite no início (já existia) +
    pausa suspendendo o processo e retomando depois;
  * Duplicati Server: pausa com duração (renovada enquanto durar; se o Agente cair, o Duplicati volta
    sozinho em até 10 min).
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("gboc_network")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CAPACITY_FILE = os.path.join(DATA_DIR, "network_capacity.json")
SUSPENDED_FILE = os.path.join(DATA_DIR, "network_governor_suspended.json")
STATE_FILE = os.path.join(DATA_DIR, "network_governor_state.json")
KEY_CONFIG = "network_governor"
TICK_SECONDS = 5
# por prefixo: o WinGet instala o restic como "restic_0.19.1_windows_amd64.exe"
ENGINE_PROCESS_PREFIXES = ("restic", "kopia", "borg", "rclone", "duplicati.commandline", "duplicati-cli")


def is_engine_process_name(name: str) -> bool:
    n = (name or "").lower()
    return n.startswith(ENGINE_PROCESS_PREFIXES) and "kopiaui" not in n and "tray" not in n

DEFAULT_CONFIG: Dict[str, Any] = {
    "mode": "schedule",               # off | schedule | auto | both
    "auto": {
        "busy_pct": 50,               # outros programas usando >= X% do upload do link -> reduz
        "pause_pct": 85,              # >= X% -> pausa
        "latency_extra_ms": 80,       # latência X ms acima da normal -> reduz
        "latency_pause_ms": 400,      # X ms acima da normal (mesmo no mínimo) -> pausa
        "min_mbps": 2.0,              # menor velocidade antes de pausar
        "link_upload_mbps": 0,        # 0 = aprende sozinho
        "probe_hosts": ["1.1.1.1:443", "8.8.8.8:443", "208.67.222.222:443"],
    },
    "resource": {
        "enabled": True,
        "cpu_high": 85, "cpu_critical": 95,
        "ram_high": 88, "ram_critical": 95,
        "disk_high": 90, "disk_critical": 98,     # % de tempo ocupado do disco mais ocupado
        "sustain_seconds": 30,
        "high_limit_mbps": 20.0,
        "low_priority": True,
    },
    "include_duplicati_server": True,
}


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            out[k] = _merge(base[k], v)
        else:
            out[k] = v
    return out


def validate_config(cfg: Any) -> Dict[str, Any]:
    if not isinstance(cfg, dict):
        raise ValueError("Configuração inválida")
    c = _merge(DEFAULT_CONFIG, cfg)
    if c["mode"] not in ("off", "schedule", "auto", "both"):
        raise ValueError("Modo inválido (off, schedule, auto ou both)")
    a, r = c["auto"], c["resource"]
    try:
        for k in ("busy_pct", "pause_pct"):
            a[k] = min(100.0, max(1.0, float(a[k])))
        if a["pause_pct"] <= a["busy_pct"]:
            raise ValueError("O % de pausa deve ser maior que o % de redução")
        for k in ("latency_extra_ms", "latency_pause_ms"):
            a[k] = max(5.0, float(a[k]))
        if a["latency_pause_ms"] <= a["latency_extra_ms"]:
            raise ValueError("A latência de pausa deve ser maior que a de redução")
        a["min_mbps"] = max(0.1, float(a["min_mbps"]))
        a["link_upload_mbps"] = max(0.0, float(a["link_upload_mbps"] or 0))
        hosts = [str(h).strip() for h in (a.get("probe_hosts") or []) if str(h).strip()][:5]
        for h in hosts:
            host, _, port = h.rpartition(":")
            if not host or not port.isdigit():
                raise ValueError(f"Host de medição inválido: {h} (use host:porta)")
        a["probe_hosts"] = hosts or DEFAULT_CONFIG["auto"]["probe_hosts"]
        r["enabled"] = bool(r["enabled"])
        r["low_priority"] = bool(r["low_priority"])
        for k in ("cpu", "ram", "disk"):
            r[f"{k}_high"] = min(100.0, max(10.0, float(r[f"{k}_high"])))
            r[f"{k}_critical"] = min(100.0, max(r[f"{k}_high"] + 1, float(r[f"{k}_critical"])))
        r["sustain_seconds"] = int(min(600, max(10, int(r["sustain_seconds"]))))
        r["high_limit_mbps"] = max(0.5, float(r["high_limit_mbps"]))
    except (TypeError, KeyError) as e:
        raise ValueError(f"Configuração inválida: {e}")
    c["include_duplicati_server"] = bool(c["include_duplicati_server"])
    return c


def _core():
    from shared_core import get_shared_core
    return get_shared_core()


def load_config() -> Dict[str, Any]:
    try:
        with _core().get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key = %s", (KEY_CONFIG,))
            row = cur.fetchone()
            cur.close()
        if row and row[0]:
            return validate_config(json.loads(row[0]) if isinstance(row[0], str) else row[0])
    except Exception as e:
        logger.debug(f"config do controle de rede indisponível: {e}")
    return validate_config({})


def save_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    c = validate_config(cfg)
    with _core().get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""INSERT INTO settings (category, key, value, type, description)
                       VALUES ('operation', %s, %s, 'json', 'Controle de rede e de carga dos backups')
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, category = 'operation',
                       updated_at = CURRENT_TIMESTAMP""", (KEY_CONFIG, json.dumps(c, ensure_ascii=False)))
        conn.commit()
        cur.close()
    governor.reload()
    return c


class _Sustain:
    """Condição verdadeira há pelo menos N segundos."""

    def __init__(self):
        self.since: Optional[float] = None

    def update(self, cond: bool, now: float) -> float:
        if cond:
            if self.since is None:
                self.since = now
            return now - self.since
        self.since = None
        return 0.0


class NetworkGovernor:
    def __init__(self):
        self._lock = threading.RLock()
        self._bucket_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cfg: Dict[str, Any] = validate_config({})
        self._cfg_ts = 0.0
        # decisão vigente
        self.action = "normal"              # normal | limit | pause
        self.limit_bps = 0.0                # 0 = sem limite
        self.reasons: List[str] = []
        self.since = time.time()
        # limitador global (token bucket)
        self._tokens = 0.0
        self._tb_last = time.monotonic()
        self.own_bytes = 0                  # bytes enviados pelo motor nativo (consume)
        self.paused_seconds = 0.0
        # medições
        self._last_nic: Optional[Tuple[float, int, int]] = None
        self._last_own: Tuple[float, int] = (time.monotonic(), 0)
        self._last_ext: Dict[int, int] = {}
        self._rtt_hist: deque = deque(maxlen=360)       # ~30 min de amostras
        self._tx_hist: deque = deque(maxlen=3)          # suavização de 15 s
        self.signals: Dict[str, Any] = {}
        self._capacity = self._load_capacity()
        # automático (AIMD)
        self._auto_rate_bps = 0.0
        self._auto_action = "normal"
        self._auto_busy = _Sustain()
        self._auto_severe = _Sustain()
        self._auto_clear = _Sustain()
        # recursos
        self._res_crit = _Sustain()
        self._res_high = _Sustain()
        self._res_clear = _Sustain()
        self._res_action = "normal"
        self._res_reason = ""
        self._last_disk: Optional[Tuple[float, Dict[str, int]]] = None
        # aplicação
        self._suspended: Dict[int, str] = {}
        self._prioritized: set = set()
        self._dup_paused_until = 0.0
        self.events: deque = deque(maxlen=100)
        self.manual_pause_until = 0.0           # pausa manual pela tela (expira sozinha)

    # ───────────────────────── ciclo ─────────────────────────

    def ensure_started(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._resume_leftovers()
            self._thread = threading.Thread(target=self._loop, name="gboc-network-governor", daemon=True)
            self._thread.start()

    def reload(self) -> None:
        self._cfg_ts = 0.0

    def _config(self) -> Dict[str, Any]:
        if time.monotonic() - self._cfg_ts > 30:
            self._cfg = load_config()
            self._cfg_ts = time.monotonic()
        return self._cfg

    def _loop(self) -> None:
        try:
            import psutil
            psutil.cpu_percent(None)        # primeira leitura de CPU serve de base
        except Exception:
            pass
        while True:
            try:
                self.tick()
            except Exception as e:
                logger.warning(f"[REDE] ciclo do controle de rede: {e}", exc_info=True)
            time.sleep(TICK_SECONDS)

    def tick(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        with self._lock:                     # laço do controle e início de backup podem chamar juntos
            return self._tick(now)

    def _tick(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        cfg = self._config()
        now = now or datetime.now()
        mono = time.monotonic()
        decisions: List[Tuple[str, float, str]] = []      # (action, bps, motivo)

        if cfg["mode"] in ("schedule", "both"):
            sched = self._schedule_decision(now)
            if sched:
                decisions.append(sched)
        manual = self._manual_decision()
        if manual:
            decisions.append(manual)
        if cfg["mode"] in ("auto", "both"):
            d = self._auto_decision(cfg["auto"], mono)
            if d:
                decisions.append(d)
        else:
            self._measure_nic(mono)                       # mantém o aprendizado da capacidade
        if cfg["resource"]["enabled"]:
            d = self._resource_decision(cfg["resource"], mono)
            if d:
                decisions.append(d)

        action, bps, reasons = "normal", 0.0, []
        pauses = [d for d in decisions if d[0] == "pause"]
        limits = [d for d in decisions if d[0] == "limit" and d[1] > 0]
        if pauses:
            action, reasons = "pause", [d[2] for d in pauses]
        elif limits:
            best = min(limits, key=lambda d: d[1])
            action, bps, reasons = "limit", best[1], [d[2] for d in limits]
        self._set_state(action, bps, reasons)
        self._apply(cfg)
        self._save_state()
        return self.status()

    # ───────────────────────── fontes ─────────────────────────

    def _schedule_decision(self, now: datetime) -> Optional[Tuple[str, float, str]]:
        try:
            from engines import operation_settings as ops
            act, mbps, rule = ops.current_schedule_action(now)
        except Exception:
            return None
        if act == "pause":
            return ("pause", 0.0, f"Agendado: pausa em {ops.describe(rule)}")
        if act == "limit" and mbps > 0:
            where = ops.describe(rule) if rule else "limite padrão"
            return ("limit", mbps * 1_000_000 / 8, f"Agendado: {mbps:g} Mbps ({where})")
        return None

    def _manual_decision(self) -> Optional[Tuple[str, float, str]]:
        if self.manual_pause_until and time.time() < self.manual_pause_until:
            ate = datetime.fromtimestamp(self.manual_pause_until).strftime("%H:%M")
            return ("pause", 0.0, f"Manual: pausado até {ate}")
        self.manual_pause_until = 0.0
        try:
            from engines.hermes_bandwidth_engine import hermes_bandwidth_engine as h
            m = h._manual_override
        except Exception:
            return None
        if m is None or float(m) <= 0:
            return None
        return ("limit", float(m) * 1_000_000 / 8, f"Manual (Hermes): {float(m):g} Mbps")

    def _engine_processes(self) -> List[Any]:
        try:
            import psutil
            out = []
            for p in psutil.Process().children(recursive=True):
                try:
                    if is_engine_process_name(p.name()):
                        out.append(p)
                except Exception:
                    continue
            return out
        except Exception:
            return []

    def _duplicati_server_processes(self) -> List[Any]:
        try:
            import psutil
            return [p for p in psutil.process_iter(["name"])
                    if (p.info.get("name") or "").lower() in ("duplicati.server.exe", "duplicati.gui.trayicon.exe")]
        except Exception:
            return []

    def _measure_nic(self, mono: float) -> Optional[Dict[str, float]]:
        """Taxas (bytes/s) de envio/recebimento da placa e do próprio GBOC desde a última medição."""
        try:
            import psutil
            per = psutil.net_io_counters(pernic=True)
        except Exception:
            return None
        tx = sum(c.bytes_sent for n, c in per.items() if "loopback" not in n.lower() and n.lower() != "lo")
        rx = sum(c.bytes_recv for n, c in per.items() if "loopback" not in n.lower() and n.lower() != "lo")
        prev, self._last_nic = self._last_nic, (mono, tx, rx)
        own_prev_t, own_prev = self._last_own
        self._last_own = (mono, self.own_bytes)
        if not prev or mono - prev[0] < 1:
            return None
        dt = mono - prev[0]
        tx_rate = max(0, tx - prev[1]) / dt
        rx_rate = max(0, rx - prev[2]) / dt
        own_rate = max(0, self.own_bytes - own_prev) / max(0.5, mono - own_prev_t)
        # motores externos e Duplicati Server: E/S do processo (no Windows inclui a rede); limitado ao total
        ext = 0
        seen = {}
        procs = self._engine_processes()
        if self._config().get("include_duplicati_server"):
            procs += self._duplicati_server_processes()
        for p in procs:
            try:
                io = p.io_counters()
                val = int(getattr(io, "write_bytes", 0)) + int(getattr(io, "other_bytes", 0))
                seen[p.pid] = val
                if p.pid in self._last_ext:
                    ext += max(0, val - self._last_ext[p.pid])
            except Exception:
                continue
        self._last_ext = seen
        own_rate = min(tx_rate, own_rate + ext / dt)
        self._tx_hist.append(tx_rate)
        self._learn_capacity(sum(self._tx_hist) / len(self._tx_hist))
        return {"tx": tx_rate, "rx": rx_rate, "own": own_rate, "other_tx": max(0.0, tx_rate - own_rate)}

    def _probe_rtt(self, hosts: List[str]) -> Optional[float]:
        best = None
        for h in hosts[:3]:
            host, _, port = h.rpartition(":")
            t0 = time.perf_counter()
            try:
                with socket.create_connection((host, int(port)), timeout=2.5):
                    ms = (time.perf_counter() - t0) * 1000
                best = ms if best is None else min(best, ms)
            except OSError:
                continue
            if best is not None and best < 300:
                break
        return best

    def _auto_decision(self, a: Dict[str, Any], mono: float) -> Optional[Tuple[str, float, str]]:
        nic = self._measure_nic(mono)
        rtt = self._probe_rtt(a["probe_hosts"])
        if rtt is not None:
            self._rtt_hist.append(rtt)
        base = min(self._rtt_hist) if self._rtt_hist else None
        cap_mbps = a["link_upload_mbps"] or self.capacity_mbps()
        cap_bps = max(125_000.0, cap_mbps * 1_000_000 / 8)
        other_pct = (nic["other_tx"] / cap_bps * 100) if nic else 0.0
        lat_extra = (rtt - base) if (rtt is not None and base is not None) else 0.0
        self.signals.update({
            "link_upload_mbps": round(cap_mbps, 2), "link_learned": not a["link_upload_mbps"],
            "nic_upload_mbps": round(nic["tx"] * 8 / 1e6, 2) if nic else None,
            "gboc_upload_mbps": round(nic["own"] * 8 / 1e6, 2) if nic else None,
            "others_upload_mbps": round(nic["other_tx"] * 8 / 1e6, 2) if nic else None,
            "others_upload_pct": round(other_pct, 1),
            "latency_ms": round(rtt, 1) if rtt is not None else None,
            "latency_base_ms": round(base, 1) if base is not None else None,
            "latency_extra_ms": round(lat_extra, 1),
        })
        severe = other_pct >= a["pause_pct"] or (lat_extra >= a["latency_pause_ms"] and rtt is not None)
        busy = severe or other_pct >= a["busy_pct"] or (lat_extra >= a["latency_extra_ms"] and rtt is not None)
        sev_for = self._auto_severe.update(severe, mono)
        busy_for = self._auto_busy.update(busy, mono)
        clear_for = self._auto_clear.update(not busy, mono)
        min_bps = a["min_mbps"] * 1_000_000 / 8
        why = (f"outros programas em {other_pct:.0f}% do upload" if other_pct >= a["busy_pct"]
               else f"latência +{lat_extra:.0f} ms")

        if self._auto_action == "pause":
            if clear_for >= 30:
                self._auto_action, self._auto_rate_bps = "limit", max(min_bps, cap_bps * 0.25)
                self._auto_clear.since = mono                             # primeiro aumento só em 20 s
        elif sev_for >= 15 and (self._auto_action != "limit" or self._auto_rate_bps <= min_bps * 1.01 or other_pct >= a["pause_pct"]):
            self._auto_action = "pause"
        elif busy_for >= TICK_SECONDS:
            start = self._auto_rate_bps or max(min_bps, (nic["own"] if nic and nic["own"] > 0 else cap_bps * 0.5))
            self._auto_rate_bps = max(min_bps, start * 0.7)              # diminuição multiplicativa
            self._auto_action = "limit"
        elif self._auto_action == "limit" and clear_for >= 20:
            self._auto_rate_bps *= 1.25                                    # sobe aos poucos
            self._auto_clear.since = mono                                  # próximo aumento em 20 s
            if self._auto_rate_bps >= cap_bps:
                self._auto_action, self._auto_rate_bps = "normal", 0.0

        if self._auto_action == "pause":
            return ("pause", 0.0, f"Automático: rede congestionada ({why})")
        if self._auto_action == "limit":
            return ("limit", self._auto_rate_bps,
                    f"Automático: {self._auto_rate_bps * 8 / 1e6:.1f} Mbps ({why if busy else 'voltando ao normal'})")
        return None

    def _disk_busy_pct(self, mono: float) -> Optional[float]:
        try:
            import psutil
            per = psutil.disk_io_counters(perdisk=True)
        except Exception:
            return None
        cur = {k: int(v.read_time) + int(v.write_time) for k, v in per.items()}
        prev, self._last_disk = self._last_disk, (mono, cur)
        if not prev:
            return None
        dt_ms = (mono - prev[0]) * 1000
        if dt_ms <= 0:
            return None
        return max([min(100.0, (cur[k] - prev[1].get(k, cur[k])) / dt_ms * 100) for k in cur] or [0.0])

    def _resource_decision(self, r: Dict[str, Any], mono: float) -> Optional[Tuple[str, float, str]]:
        try:
            import psutil
            cpu = psutil.cpu_percent(None)
            ram = psutil.virtual_memory().percent
        except Exception:
            return None
        disk = self._disk_busy_pct(mono)
        self.signals.update({"cpu_pct": round(cpu, 1), "ram_pct": round(ram, 1),
                             "disk_busy_pct": round(disk, 1) if disk is not None else None})
        crit = [n for n, v, lim in (("CPU", cpu, r["cpu_critical"]), ("memória", ram, r["ram_critical"]),
                                    ("disco", disk, r["disk_critical"])) if v is not None and v >= lim]
        high = [n for n, v, lim in (("CPU", cpu, r["cpu_high"]), ("memória", ram, r["ram_high"]),
                                    ("disco", disk, r["disk_high"])) if v is not None and v >= lim]
        crit_for = self._res_crit.update(bool(crit), mono)
        high_for = self._res_high.update(bool(high), mono)
        clear_for = self._res_clear.update(not high, mono)
        sustain = r["sustain_seconds"]
        if crit_for >= sustain:
            self._res_action = "pause"
            self._res_reason = f"Máquina sobrecarregada: {', '.join(crit)} crítico(s)"
        elif high_for >= sustain and self._res_action != "pause":
            self._res_action = "limit"
            self._res_reason = f"Máquina carregada: {', '.join(high)} alto(s)"
        elif self._res_action != "normal" and clear_for >= sustain:
            self._res_action = "normal"
        if self._res_action == "pause":
            return ("pause", 0.0, self._res_reason)
        if self._res_action == "limit":
            return ("limit", r["high_limit_mbps"] * 1_000_000 / 8, self._res_reason)
        return None

    # ───────────────────────── capacidade do link ─────────────────────────

    def _load_capacity(self) -> Dict[str, float]:
        try:
            with open(CAPACITY_FILE, encoding="utf-8") as f:
                return {k: float(v) for k, v in json.load(f).get("daily_max_bps", {}).items()}
        except Exception:
            return {}

    def _learn_capacity(self, bps: float) -> None:
        day = datetime.now().strftime("%Y-%m-%d")
        if bps <= self._capacity.get(day, 0):
            return
        self._capacity[day] = bps
        cut = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        self._capacity = {d: v for d, v in self._capacity.items() if d >= cut}
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(CAPACITY_FILE, "w", encoding="utf-8") as f:
                json.dump({"daily_max_bps": self._capacity, "updated_at": datetime.now().isoformat(timespec="seconds")}, f)
        except Exception:
            pass

    def capacity_mbps(self) -> float:
        return max(self._capacity.values()) * 8 / 1e6 if self._capacity else 0.0

    # ───────────────────────── estado e aplicação ─────────────────────────

    def _set_state(self, action: str, bps: float, reasons: List[str]) -> None:
        changed = action != self.action or (action == "limit" and abs(bps - self.limit_bps) > max(1.0, self.limit_bps * 0.05))
        with self._bucket_lock:
            self.action, self.limit_bps, self.reasons = action, bps, reasons
        if changed:
            self.since = time.time()
            txt = {"normal": "Velocidade normal", "pause": "Backups PAUSADOS",
                   "limit": f"Upload limitado a {bps * 8 / 1e6:.1f} Mbps"}[action]
            msg = f"{txt}" + (f" - {'; '.join(reasons)}" if reasons else "")
            self.events.appendleft({"at": datetime.now().isoformat(sep=" ", timespec="seconds"), "action": action,
                                    "limit_mbps": round(bps * 8 / 1e6, 2), "message": msg})
            logger.info(f"📶 [REDE] {msg}")

    def _apply(self, cfg: Dict[str, Any]) -> None:
        procs = self._engine_processes()
        low = cfg["resource"]["enabled"] and cfg["resource"]["low_priority"]
        for p in procs:
            if low and p.pid not in self._prioritized:
                self._lower_priority(p)
                self._prioritized.add(p.pid)
            if self.action == "pause" and p.pid not in self._suspended:
                try:
                    p.suspend()
                    self._suspended[p.pid] = p.name()
                    logger.info(f"⏸️ [REDE] {p.name()} (PID {p.pid}) pausado")
                except Exception as e:
                    logger.warning(f"[REDE] não foi possível pausar {p.pid}: {e}")
        if self.action != "pause" and self._suspended:
            self._resume_all()
        self._prioritized &= {p.pid for p in procs}
        self._save_suspended()
        if cfg.get("include_duplicati_server"):
            self._apply_duplicati()

    @staticmethod
    def _lower_priority(p) -> None:
        try:
            import psutil
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS") else 10)
            if hasattr(psutil, "IOPRIO_LOW"):
                p.ionice(psutil.IOPRIO_LOW)
        except Exception:
            pass

    def _resume_all(self) -> None:
        try:
            import psutil
        except Exception:
            return
        for pid, name in list(self._suspended.items()):
            try:
                psutil.Process(pid).resume()
                logger.info(f"▶️ [REDE] {name} (PID {pid}) retomado")
            except Exception:
                pass
            self._suspended.pop(pid, None)

    def _save_suspended(self) -> None:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(SUSPENDED_FILE, "w", encoding="utf-8") as f:
                json.dump(self._suspended, f)
        except Exception:
            pass

    def _resume_leftovers(self) -> None:
        """Processos que ficaram pausados quando o Agente parou (ex.: serviço reiniciado no meio da pausa)."""
        try:
            import psutil
            with open(SUSPENDED_FILE, encoding="utf-8") as f:
                left = json.load(f)
        except Exception:
            return
        for pid, name in (left or {}).items():
            try:
                p = psutil.Process(int(pid))
                if p.name() == name:
                    p.resume()
                    logger.info(f"▶️ [REDE] {name} (PID {pid}) retomado (pausa anterior ao reinício)")
            except Exception:
                pass
        self._save_suspended()

    def _apply_duplicati(self) -> None:
        if not self._duplicati_server_processes():
            return
        now = time.time()
        try:
            from core.integrations.duplicati_native import get_duplicati_native_service
            svc = get_duplicati_native_service()
            cfg = svc.load_config()
            if self.action == "pause":
                if now >= self._dup_paused_until - 120:          # renova antes de expirar
                    r = svc._api_post(cfg, "api/v1/serverstate/pause?duration=10m")
                    if r.status_code == 200:
                        if not self._dup_paused_until:
                            logger.info("⏸️ [REDE] Duplicati Server pausado (renovado a cada 8 min; expira sozinho)")
                        self._dup_paused_until = now + 600
            elif self._dup_paused_until:
                svc._api_post(cfg, "api/v1/serverstate/resume")
                self._dup_paused_until = 0.0
                logger.info("▶️ [REDE] Duplicati Server retomado")
        except Exception as e:
            logger.debug(f"[REDE] Duplicati Server: {e}")

    # ───────────────────────── limitador do motor nativo ─────────────────────────

    def consume(self, nbytes: int, on_nic: bool = True) -> None:
        """Chamado antes de cada envio do motor nativo. Bloqueia enquanto pausado; limita a taxa global
        (todas as conexões juntas) ao limite vigente - que pode mudar no meio do envio."""
        self.ensure_started()
        t_pause = None
        while self.action == "pause":
            t_pause = t_pause or time.monotonic()
            time.sleep(1)
        if t_pause:
            self.paused_seconds += time.monotonic() - t_pause
        with self._bucket_lock:
            if on_nic:                      # destino neste computador não passa pela placa de rede
                self.own_bytes += nbytes
            rate = self.limit_bps if self.action == "limit" else 0.0
            if rate <= 0:
                self._tokens, self._tb_last = 0.0, time.monotonic()
                return
            now = time.monotonic()
            self._tokens = min(rate * 0.5, self._tokens + (now - self._tb_last) * rate)   # rajada máx. 0,5 s
            self._tb_last = now
            self._tokens -= nbytes
        while True:
            with self._bucket_lock:
                if self.action == "pause":
                    debt = None
                else:
                    rate = self.limit_bps if self.action == "limit" else 0.0
                    if rate <= 0:
                        self._tokens = 0.0
                        return
                    now = time.monotonic()
                    self._tokens = min(rate * 0.5, self._tokens + (now - self._tb_last) * rate)
                    self._tb_last = now
                    if self._tokens >= 0:
                        return
                    debt = -self._tokens / rate
            if debt is None:
                time.sleep(1)               # pausou no meio da espera
                continue
            time.sleep(min(1.0, debt))       # reavalia a cada 1 s (o limite pode mudar)

    # ───────────────────────── status ─────────────────────────

    def pause_manual(self, minutes: float) -> Dict[str, Any]:
        minutes = max(1.0, min(24 * 60.0, float(minutes)))
        self.manual_pause_until = time.time() + minutes * 60
        self.ensure_started()
        return self.tick()

    def resume_manual(self) -> Dict[str, Any]:
        self.manual_pause_until = 0.0
        self.ensure_started()
        return self.tick()

    def start_limit_mbps(self) -> float:
        """Limite para o início de um motor externo (restic/Kopia/Duplicati CLI recebem o limite na linha de
        comando). Reavalia agora; pausa vira 0 aqui porque o processo é suspenso logo depois de iniciar."""
        self.ensure_started()
        try:
            self.tick()
        except Exception as e:
            logger.debug(f"[REDE] avaliação no início do backup: {e}")
        return round(self.limit_bps * 8 / 1e6, 3) if self.action == "limit" else 0.0

    def status(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "limit_mbps": round(self.limit_bps * 8 / 1e6, 2) if self.action == "limit" else None,
            "reasons": list(self.reasons),
            "since": datetime.fromtimestamp(self.since).isoformat(sep=" ", timespec="seconds"),
            "signals": dict(self.signals),
            "link_capacity_learned_mbps": round(self.capacity_mbps(), 2),
            "suspended_processes": [{"pid": k, "name": v} for k, v in self._suspended.items()],
            "duplicati_server_paused": bool(self._dup_paused_until),
            "native_bytes_sent": self.own_bytes,
            "native_paused_seconds": round(self.paused_seconds, 1),
            "events": list(self.events)[:30],
            "manual_pause_until": datetime.fromtimestamp(self.manual_pause_until).isoformat(sep=" ", timespec="seconds")
            if self.manual_pause_until else None,
            "running": bool(self._thread and self._thread.is_alive()),
        }

    def _save_state(self) -> None:
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({**self.status(), "pid": os.getpid(), "updated_at": datetime.now().isoformat(timespec="seconds")},
                          f, ensure_ascii=False)
        except Exception:
            pass


governor = NetworkGovernor()


def consume(nbytes: int, on_nic: bool = True) -> None:
    governor.consume(nbytes, on_nic)
