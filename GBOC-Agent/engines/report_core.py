"""
GBOC — Motor de Relatórios Reais (compartilhado Server/Agente).

ARQUIVO IDÊNTICO EM:
  GBOC-Server/modules/reports/report_core.py
  GBOC-Agent/engines/report_core.py

Cada relatório é calculado a partir de dados reais fornecidos por uma "fonte de dados"
(adaptador): o Server usa as tabelas sincronizadas de todos os agentes; o Agente usa o seu
próprio banco. Nada é estimado ou inventado: quando um dado não existe, o relatório diz
isso explicitamente em "Observações sobre os dados".

Saídas: dicionário estruturado (JSON), HTML autônomo (gráficos em SVG embutido, pronto para
imprimir/salvar em PDF e abrir sem internet) e CSV.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

REPORT_ENGINE_VERSION = "2.0.0"

# ───────────────────────────── Formatação ─────────────────────────────

def esc(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def fmt_int(n: Any) -> str:
    try:
        return f"{int(round(float(n))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def fmt_pct(v: Any, digits: int = 1) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{digits}f}%".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def fmt_num(v: Any, digits: int = 1) -> str:
    if v is None:
        return "—"
    try:
        s = f"{float(v):,.{digits}f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "—"


def fmt_bytes(n: Any) -> str:
    if n is None:
        return "—"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    neg = n < 0
    n = abs(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or unit == "PB":
            txt = f"{n:.0f} {unit}" if unit == "B" else f"{fmt_num(n, 1 if n < 100 else 0)} {unit}"
            return ("-" if neg else "") + txt
        n /= 1024.0
    return "—"


def fmt_duration(sec: Any) -> str:
    if sec is None:
        return "—"
    try:
        s = int(round(float(sec)))
    except (TypeError, ValueError):
        return "—"
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}min {s:02d}s"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h}h {m:02d}min"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"


def fmt_age_hours(h: Optional[float]) -> str:
    if h is None:
        return "nunca"
    if h < 1:
        return f"{int(h * 60)} min"
    if h < 48:
        return f"{fmt_num(h, 1)} h"
    return f"{fmt_num(h / 24, 1)} dias"


def fmt_dt(v: Any) -> str:
    d = to_dt(v)
    return d.strftime("%d/%m/%Y %H:%M") if d else "—"


def fmt_date(v: Any) -> str:
    d = to_dt(v)
    return d.strftime("%d/%m/%Y") if d else "—"


def to_dt(v: Any) -> Optional[datetime]:
    """Converte para datetime local ingênuo (sem fuso)."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        d = v
    elif isinstance(v, date):
        d = datetime(v.year, v.month, v.day)
    else:
        s = str(v).strip().replace("Z", "+00:00")
        try:
            d = datetime.fromisoformat(s)
        except ValueError:
            for f in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
                try:
                    d = datetime.strptime(s[:26], f)
                    break
                except ValueError:
                    d = None
            if d is None:
                return None
    if d.tzinfo is not None:
        d = d.astimezone().replace(tzinfo=None)
    return d


def to_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


SUCCESS_WORDS = {"success", "completed", "complete", "ok", "done", "finished", "succeeded", "warning", "partial"}
FAIL_WORDS = {"failed", "failure", "error", "aborted", "timeout", "crashed", "fatal", "critical"}
RUNNING_WORDS = {"running", "in_progress", "pending", "queued", "started", "processing"}
CANCEL_WORDS = {"cancelled", "canceled", "stopped", "skipped", "interrupted"}


def norm_status(s: Any) -> str:
    v = str(s or "").strip().lower()
    if v in SUCCESS_WORDS:
        return "success"
    if v in FAIL_WORDS or v.startswith("fail") or v.startswith("err"):
        return "failed"
    if v in RUNNING_WORDS:
        return "running"
    if v in CANCEL_WORDS:
        return "cancelled"
    return "other"


STATUS_LABEL = {"success": "Sucesso", "failed": "Falha", "running": "Em execução", "cancelled": "Cancelada", "other": "Outro"}


def percentile(values: List[float], p: float) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = (len(vals) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return vals[int(k)]
    return vals[f] + (vals[c] - vals[f]) * (k - f)


def linear_slope_per_day(points: List[Tuple[datetime, float]]) -> Optional[float]:
    """Inclinação (unidades/dia) por mínimos quadrados. Exige >= 2 pontos em dias distintos."""
    pts = [(p[0], p[1]) for p in points if p[0] is not None and p[1] is not None]
    if len(pts) < 2:
        return None
    t0 = min(p[0] for p in pts)
    xs = [(p[0] - t0).total_seconds() / 86400.0 for p in pts]
    if max(xs) - min(xs) < 0.5:
        return None
    ys = [p[1] for p in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


# ───────────────────────────── Cron → intervalo esperado ─────────────────────────────

WEEKDAYS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def cron_interval_hours(cron: Optional[str]) -> Optional[float]:
    """Intervalo típico entre execuções a partir de uma expressão cron de 5 campos."""
    if not cron:
        return None
    parts = str(cron).split()
    if len(parts) < 5:
        return None
    minute, hour, dom, mon, dow = parts[:5]

    def count(field: str, lo: int, hi: int) -> Optional[int]:
        if field in ("*", "?"):
            return hi - lo + 1
        if field.startswith("*/"):
            try:
                return max(1, (hi - lo + 1) // int(field[2:]))
            except ValueError:
                return None
        total = 0
        for chunk in field.split(","):
            if "-" in chunk:
                a, _, b = chunk.partition("-")
                b = b.split("/")[0]
                try:
                    total += int(b) - int(a) + 1
                except ValueError:
                    return None
            else:
                total += 1
        return total

    per_day_hours = count(hour, 0, 23) or 1
    per_hour_min = count(minute, 0, 59) or 1
    runs_per_day = per_day_hours * per_hour_min
    if dom not in ("*", "?"):
        days = count(dom, 1, 31) or 1
        return round(24 * 30.4 / days, 1)
    if dow not in ("*", "?"):
        days = count(dow, 0, 6) or 1
        return round(24 * 7 / days, 1) if days < 7 else round(24 / runs_per_day, 2)
    return round(24 / runs_per_day, 2)


def cron_human(cron: Optional[str], enabled: Optional[bool] = True) -> str:
    if not cron:
        return "Manual (sem agendamento)"
    if enabled is False:
        return f"Agendamento desativado ({cron})"
    parts = str(cron).split()
    if len(parts) >= 5:
        minute, hour, dom, mon, dow = parts[:5]
        hh = f"{int(hour):02d}:{int(minute):02d}" if hour.isdigit() and minute.isdigit() else None
        if hh and dom == "*" and dow == "*":
            return f"Diário às {hh}"
        if hh and dom == "*" and dow.isdigit():
            idx = (int(dow) - 1) % 7
            return f"Semanal ({WEEKDAYS_PT[idx]}) às {hh}"
        if hh and dom.isdigit():
            return f"Mensal (dia {dom}) às {hh}"
        if hour.startswith("*/"):
            return f"A cada {hour[2:]} h"
        if hour == "*" and minute.isdigit() and dom == "*" and dow == "*":
            return f"A cada hora (min {int(minute):02d})"
        if minute.startswith("*/") and hour == "*":
            return f"A cada {minute[2:]} min"
    return str(cron)


# ───────────────────────────── Causa raiz de falhas ─────────────────────────────

ERROR_CATEGORIES = [
    ("Permissão / acesso negado", ("permission denied", "access is denied", "acesso negado", "access denied",
                                   "permissão negada", "unauthorizedaccess", "eacces", "operation not permitted"),
     "Executar o serviço do Agente com uma conta que tenha leitura na origem e escrita no destino; revisar ACLs."),
    ("Arquivo em uso / bloqueado", ("being used by another process", "sharing violation", "file is locked", "em uso",
                                     "locked by", "resource busy", "ebusy"),
     "Habilitar VSS/snapshot da origem ou agendar fora do horário de uso; excluir arquivos temporários/abertos."),
    ("Espaço insuficiente", ("no space left", "disk full", "not enough space", "espaço insuficiente", "insufficient space",
                             "quota exceeded", "enospc"),
     "Liberar espaço no destino, ajustar a retenção (prune) ou ampliar o repositório."),
    ("Rede / conectividade", ("timed out", "timeout", "connection refused", "connection reset", "unreachable",
                              "network", "name or service not known", "getaddrinfo", "could not resolve", "econnrefused",
                              "max retries exceeded", "broken pipe", "ssl", "certificate"),
     "Verificar link, DNS, firewall/proxy e disponibilidade do destino; considerar retentativas automáticas."),
    ("Credenciais / autenticação", ("wrong password", "authentication", "unauthorized", "401", "403", "invalid credentials",
                                    "senha", "password", "access key", "signature does not match", "forbidden"),
     "Atualizar a senha do repositório ou as chaves do provedor de nuvem na configuração do repositório."),
    ("Repositório / integridade", ("repository", "repositório", "pack", "corrupt", "checksum", "lock", "unable to open config",
                                   "is not a valid", "index"),
     "Executar verificação/reparo do repositório (check/repair) e remover locks antigos."),
    ("Origem inexistente", ("no such file", "not found", "cannot find", "não encontrado", "does not exist", "enoent",
                            "path not found"),
     "Corrigir os caminhos de origem da tarefa ou remover pastas que deixaram de existir."),
    ("VSS / snapshot do sistema", ("vss", "shadow copy", "volume shadow", "snapshot creation"),
     "Verificar o serviço de Cópias de Sombra do Windows (VSS) e o espaço reservado para snapshots."),
    ("Motor de backup ausente", ("not installed", "executable not found", "command not found", "is not recognized",
                                 "no module named"),
     "Instalar/reparar o motor de backup no Agente ou migrar a tarefa para o Motor Nativo GBOC."),
    ("Cancelada / interrompida", ("cancel", "interrupted", "killed", "terminated", "aborted by user"),
     "Verificar desligamentos/reinicializações do host durante a janela de backup."),
]


def classify_error(msg: Optional[str]) -> Tuple[str, str]:
    m = (msg or "").lower()
    if not m.strip():
        return ("Sem mensagem de erro", "Habilitar logs detalhados do motor para registrar a causa da falha.")
    for name, keys, action in ERROR_CATEGORIES:
        if any(k in m for k in keys):
            return (name, action)
    return ("Outros", "Analisar o log completo da execução no Agente.")


_RE_PATH = re.compile(r"([a-zA-Z]:\\[^\s'\"]*|/[\w.\-/]+)")
_RE_HEX = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
_RE_NUM = re.compile(r"\b\d+\b")
_RE_QUOTE = re.compile(r"(['\"]).*?\1")


def error_pattern(msg: Optional[str]) -> str:
    m = (msg or "").strip().splitlines()[0] if (msg or "").strip() else ""
    m = _RE_QUOTE.sub("'…'", m)
    m = _RE_PATH.sub("<caminho>", m)
    m = _RE_HEX.sub("<id>", m)
    m = _RE_NUM.sub("N", m)
    m = re.sub(r"\s+", " ", m).strip()
    return (m[:140] + "…") if len(m) > 140 else (m or "(sem mensagem)")


# ───────────────────────────── Gráficos SVG ─────────────────────────────
# Paleta categórica validada (ordem fixa) e cores de status reservadas.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
STATUS = {"ok": "#0ca30c", "warn": "#fab219", "serious": "#ec835a", "bad": "#d03b3b", "neutral": "#8a8984"}
INK, INK2, GRID = "#1f1f1d", "#5f5e5a", "#e6e5e0"


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp


def _fmt_axis(v: float, unit: str) -> str:
    if unit == "bytes":
        return fmt_bytes(v)
    if unit == "%":
        return f"{v:.0f}%"
    if unit == "h":
        return f"{fmt_num(v, 0)}h"
    if unit == "s":
        return fmt_duration(v)
    if unit == "d":
        return f"{fmt_num(v, 0)} d"
    if abs(v) >= 1000:
        return fmt_int(v)
    return fmt_num(v, 0 if float(v).is_integer() else 1)


def _fmt_val(v: Optional[float], unit: str) -> str:
    if v is None:
        return "sem dado"
    if unit == "bytes":
        return fmt_bytes(v)
    if unit == "%":
        return fmt_pct(v)
    if unit == "h":
        return fmt_age_hours(v)
    if unit == "s":
        return fmt_duration(v)
    if unit == "B/s":
        return fmt_bytes(v) + "/s"
    if unit == "d":
        return f"{fmt_num(v, 1)} dias"
    return fmt_num(v, 0 if float(v).is_integer() else 1)


def _legend(series: List[Dict[str, Any]], x: float, y: float) -> str:
    out, cx = [], x
    for s in series:
        name = esc(s["name"])
        out.append(f'<rect x="{cx:.1f}" y="{y - 9:.1f}" width="10" height="10" rx="2" fill="{s["color"]}"/>'
                   f'<text x="{cx + 14:.1f}" y="{y:.1f}" font-size="11" fill="{INK2}">{name}</text>')
        cx += 24 + len(s["name"]) * 6.4
    return "".join(out)


def _with_colors(series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for i, s in enumerate(series):
        c = s.get("color") or STATUS.get(s.get("tone", ""), None) or SERIES[i % len(SERIES)]
        out.append({**s, "color": c})
    return out


def svg_empty(title: str, msg: str = "Sem dados no período selecionado") -> str:
    return (f'<svg viewBox="0 0 760 90" class="chart" role="img" aria-label="{esc(title)}">'
            f'<rect x="0" y="0" width="760" height="90" rx="8" fill="#f6f6f3"/>'
            f'<text x="380" y="50" text-anchor="middle" font-size="13" fill="{INK2}">{esc(msg)}</text></svg>')


def svg_bars(labels: List[str], series: List[Dict[str, Any]], unit: str = "", stacked: bool = True,
             height: int = 240, title: str = "") -> str:
    series = _with_colors(series)
    n = len(labels)
    if n == 0 or not series or all(not any(v for v in s["values"] if v) for s in series):
        return svg_empty(title)
    W, H, L, R, T, B = 760, height, 64, 12, 26 if len(series) > 1 else 10, 34
    pw, ph = W - L - R, H - T - B
    if stacked:
        tot = [sum((s["values"][i] or 0) for s in series) for i in range(n)]
    else:
        tot = [max((s["values"][i] or 0) for s in series) for i in range(n)]
    ymax = _nice_max(max(tot) if tot else 1)
    if unit == "" and ymax <= 8:   # contagens pequenas: marcas inteiras no eixo
        ymax = 4.0 if ymax <= 4 else 8.0
    slot = pw / n
    bw = max(2.0, min(34.0, slot * (0.72 if stacked else 0.8)))
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="{esc(title)}">']
    for k in range(5):
        yv = ymax * k / 4
        y = T + ph - ph * k / 4
        out.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W - R}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>'
                   f'<text x="{L - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="{INK2}">{esc(_fmt_axis(yv, unit))}</text>')
    step = max(1, math.ceil(n / 16))
    for i, lab in enumerate(labels):
        cx = L + slot * i + slot / 2
        if stacked:
            base = 0.0
            for s in series:
                v = s["values"][i] or 0
                if v <= 0:
                    continue
                h = ph * v / ymax
                y = T + ph - ph * (base + v) / ymax
                out.append(f'<rect x="{cx - bw / 2:.1f}" y="{y + 1:.1f}" width="{bw:.1f}" height="{max(1.0, h - 2):.1f}" rx="2" fill="{s["color"]}">'
                           f'<title>{esc(lab)} — {esc(s["name"])}: {esc(_fmt_val(v, unit))}</title></rect>')
                base += v
        else:
            m = len(series)
            sub = bw / m
            for j, s in enumerate(series):
                v = s["values"][i] or 0
                h = ph * v / ymax
                x = cx - bw / 2 + j * sub
                out.append(f'<rect x="{x + 1:.1f}" y="{T + ph - h:.1f}" width="{max(1.0, sub - 2):.1f}" height="{max(0.0, h):.1f}" rx="2" fill="{s["color"]}">'
                           f'<title>{esc(lab)} — {esc(s["name"])}: {esc(_fmt_val(v, unit))}</title></rect>')
        if i % step == 0:
            out.append(f'<text x="{cx:.1f}" y="{H - 14}" text-anchor="middle" font-size="10" fill="{INK2}">{esc(lab)}</text>')
    if len(series) > 1:
        out.append(_legend(series, L, 14))
    out.append("</svg>")
    return "".join(out)


def svg_line(labels: List[str], series: List[Dict[str, Any]], unit: str = "", height: int = 230,
             title: str = "", y_max: Optional[float] = None, target: Optional[float] = None, target_label: str = "Meta") -> str:
    series = _with_colors(series)
    n = len(labels)
    vals = [v for s in series for v in s["values"] if v is not None]
    if n == 0 or not vals:
        return svg_empty(title)
    W, H, L, R, T, B = 760, height, 64, 14, 26 if len(series) > 1 else 12, 34
    pw, ph = W - L - R, H - T - B
    ymax = y_max if y_max is not None else _nice_max(max(vals + ([target] if target else [])))
    ymin = 0.0
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="{esc(title)}">']
    for k in range(5):
        yv = ymin + (ymax - ymin) * k / 4
        y = T + ph - ph * k / 4
        out.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W - R}" y2="{y:.1f}" stroke="{GRID}"/>'
                   f'<text x="{L - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="{INK2}">{esc(_fmt_axis(yv, unit))}</text>')

    def xy(i: int, v: float) -> Tuple[float, float]:
        x = L + (pw * i / (n - 1) if n > 1 else pw / 2)
        y = T + ph - ph * (v - ymin) / ((ymax - ymin) or 1)
        return x, y

    if target is not None:
        _, ty = xy(0, target)
        out.append(f'<line x1="{L}" y1="{ty:.1f}" x2="{W - R}" y2="{ty:.1f}" stroke="{STATUS["bad"]}" stroke-dasharray="5 4" stroke-width="1.5"/>'
                   f'<text x="{W - R}" y="{ty - 5:.1f}" text-anchor="end" font-size="10" fill="{STATUS["bad"]}">{esc(target_label)} {esc(_fmt_axis(target, unit))}</text>')
    for s in series:
        pts, seg = [], []
        for i, v in enumerate(s["values"]):
            if v is None:
                if len(seg) > 1:
                    pts.append(seg)
                seg = []
                continue
            seg.append(xy(i, v))
        if seg:
            pts.append(seg)
        for sg in pts:
            if len(sg) > 1:
                d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in sg)
                out.append(f'<path d="{d}" fill="none" stroke="{s["color"]}" stroke-width="2" stroke-linejoin="round"/>')
        for i, v in enumerate(s["values"]):
            if v is None:
                continue
            x, y = xy(i, v)
            r = 3 if n <= 45 else 1.8
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{s["color"]}" stroke="#fff" stroke-width="1">'
                       f'<title>{esc(labels[i])} — {esc(s["name"])}: {esc(_fmt_val(v, unit))}</title></circle>')
    step = max(1, math.ceil(n / 12))
    for i, lab in enumerate(labels):
        if i % step == 0 or i == n - 1:
            x, _ = xy(i, ymin)
            out.append(f'<text x="{x:.1f}" y="{H - 14}" text-anchor="middle" font-size="10" fill="{INK2}">{esc(lab)}</text>')
    if len(series) > 1:
        out.append(_legend(series, L, 14))
    out.append("</svg>")
    return "".join(out)


def svg_hbar(labels: List[str], values: List[Optional[float]], unit: str = "", tones: Optional[List[str]] = None,
             title: str = "", max_items: int = 15, target: Optional[float] = None, target_label: str = "Meta") -> str:
    items = [(l, v, (tones[i] if tones else None)) for i, (l, v) in enumerate(zip(labels, values)) if v is not None][:max_items]
    if not items:
        return svg_empty(title)
    W, row = 760, 24
    H = 16 + row * len(items) + 18
    L, R = 230, 90
    pw = W - L - R
    vmax = _nice_max(max([v for _, v, _ in items] + ([target] if target else [])) or 1)
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="{esc(title)}">']
    for i, (lab, v, tone) in enumerate(items):
        y = 10 + i * row
        w = pw * (v or 0) / vmax
        color = STATUS.get(tone or "", None) or SERIES[0]
        short = lab if len(lab) <= 34 else lab[:33] + "…"
        out.append(f'<text x="{L - 8}" y="{y + 14}" text-anchor="end" font-size="11" fill="{INK}">{esc(short)}</text>'
                   f'<rect x="{L}" y="{y + 3}" width="{max(2.0, w):.1f}" height="{row - 8}" rx="3" fill="{color}">'
                   f'<title>{esc(lab)}: {esc(_fmt_val(v, unit))}</title></rect>'
                   f'<text x="{L + max(2.0, w) + 6:.1f}" y="{y + 14}" font-size="11" fill="{INK2}">{esc(_fmt_val(v, unit))}</text>')
    if target is not None:
        tx = L + pw * target / vmax
        out.append(f'<line x1="{tx:.1f}" y1="6" x2="{tx:.1f}" y2="{H - 14}" stroke="{STATUS["bad"]}" stroke-dasharray="4 3" stroke-width="1.5"/>'
                   f'<text x="{tx:.1f}" y="{H - 3}" text-anchor="middle" font-size="10" fill="{STATUS["bad"]}">{esc(target_label)} {esc(_fmt_axis(target, unit))}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_donut(labels: List[str], values: List[float], colors: Optional[List[str]] = None, title: str = "",
              center_label: str = "") -> str:
    data = [(l, float(v or 0), (colors[i] if colors else SERIES[i % len(SERIES)])) for i, (l, v) in enumerate(zip(labels, values)) if (v or 0) > 0]
    total = sum(v for _, v, _ in data)
    if not data or total <= 0:
        return svg_empty(title)
    W, H, cx, cy, r, rin = 760, 210, 120, 105, 88, 56
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="{esc(title)}">']
    ang = -math.pi / 2
    for lab, v, col in data:
        frac = v / total
        a2 = ang + 2 * math.pi * frac
        if frac >= 0.9999:
            out.append(f'<circle cx="{cx}" cy="{cy}" r="{(r + rin) / 2}" fill="none" stroke="{col}" stroke-width="{r - rin}">'
                       f'<title>{esc(lab)}: {fmt_num(v, 0)} (100%)</title></circle>')
        else:
            large = 1 if frac > 0.5 else 0
            x1, y1 = cx + r * math.cos(ang), cy + r * math.sin(ang)
            x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
            x3, y3 = cx + rin * math.cos(a2), cy + rin * math.sin(a2)
            x4, y4 = cx + rin * math.cos(ang), cy + rin * math.sin(ang)
            out.append(f'<path d="M{x1:.1f},{y1:.1f} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f} L{x3:.1f},{y3:.1f} '
                       f'A{rin},{rin} 0 {large} 0 {x4:.1f},{y4:.1f} Z" fill="{col}" stroke="#fff" stroke-width="2">'
                       f'<title>{esc(lab)}: {fmt_num(v, 0)} ({fmt_pct(frac * 100)})</title></path>')
        ang = a2
    out.append(f'<text x="{cx}" y="{cy + 2}" text-anchor="middle" font-size="20" font-weight="700" fill="{INK}">{esc(fmt_int(total))}</text>'
               f'<text x="{cx}" y="{cy + 19}" text-anchor="middle" font-size="10" fill="{INK2}">{esc(center_label)}</text>')
    for i, (lab, v, col) in enumerate(data[:9]):
        y = 30 + i * 19
        out.append(f'<rect x="260" y="{y - 10}" width="11" height="11" rx="2" fill="{col}"/>'
                   f'<text x="278" y="{y}" font-size="12" fill="{INK}">{esc(lab)}</text>'
                   f'<text x="740" y="{y}" text-anchor="end" font-size="12" fill="{INK2}">{esc(fmt_int(v))} · {esc(fmt_pct(v / total * 100))}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_heatmap(row_labels: List[str], col_labels: List[str], matrix: List[List[float]], unit: str = "",
                title: str = "") -> str:
    vmax = max((v for r in matrix for v in r), default=0)
    if not matrix or vmax <= 0:
        return svg_empty(title)
    ramp = ["#f3f6fb", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
    W, L, T = 760, 48, 18
    cw = (W - L - 8) / len(col_labels)
    ch = 22
    H = T + ch * len(row_labels) + 22
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="{esc(title)}">']
    for j, cl in enumerate(col_labels):
        if j % 2 == 0:
            out.append(f'<text x="{L + cw * j + cw / 2:.1f}" y="12" text-anchor="middle" font-size="9" fill="{INK2}">{esc(cl)}</text>')
    for i, rl in enumerate(row_labels):
        y = T + i * ch
        out.append(f'<text x="{L - 6}" y="{y + 15}" text-anchor="end" font-size="11" fill="{INK}">{esc(rl)}</text>')
        for j, v in enumerate(matrix[i]):
            idx = 0 if v <= 0 else min(len(ramp) - 1, 1 + int((v / vmax) * (len(ramp) - 2) + 0.5))
            out.append(f'<rect x="{L + cw * j + 1:.1f}" y="{y + 1}" width="{cw - 2:.1f}" height="{ch - 2}" rx="2" fill="{ramp[idx]}">'
                       f'<title>{esc(rl)} {esc(col_labels[j])}: {esc(_fmt_val(v, unit))}</title></rect>')
    out.append(f'<text x="{L}" y="{H - 5}" font-size="10" fill="{INK2}">Menos</text>')
    for k, c in enumerate(ramp):
        out.append(f'<rect x="{L + 40 + k * 16}" y="{H - 14}" width="14" height="10" rx="2" fill="{c}"/>')
    out.append(f'<text x="{L + 40 + len(ramp) * 16 + 4}" y="{H - 5}" font-size="10" fill="{INK2}">Mais</text></svg>')
    return "".join(out)


# ───────────────────────────── Contexto do relatório ─────────────────────────────

def cell(text: Any, tone: Optional[str] = None) -> Dict[str, Any]:
    return {"v": "" if text is None else str(text), "tone": tone}


def cell_text(c: Any) -> str:
    return c.get("v", "") if isinstance(c, dict) else ("" if c is None else str(c))


class ReportContext:
    """Carrega (uma única vez) os conjuntos de dados usados pelos relatórios."""

    def __init__(self, source: Any, days: int = 30, agent_ids: Optional[List[str]] = None,
                 tenant_id: Optional[str] = None):
        self.source = source
        self.days = max(1, min(int(days or 30), 730))
        self.end = datetime.now().replace(microsecond=0)
        self.start = (self.end - timedelta(days=self.days)).replace(hour=0, minute=0, second=0)
        self.tenant_id = tenant_id or None
        self.info = dict(source.info() or {})
        self.settings = dict(self.info.get("settings") or {})
        self._agent_filter = [a for a in (agent_ids or []) if a]
        self._cache: Dict[str, Any] = {}

    # ── carga preguiçosa ──
    def _get(self, key: str, loader: Callable[[], Any]) -> Any:
        if key not in self._cache:
            try:
                self._cache[key] = loader()
            except Exception as exc:  # fonte indisponível → lista vazia + observação
                self._cache[key] = []
                self.notes_errors.append(f"Dados de '{key}' indisponíveis: {exc}")
        return self._cache[key]

    @property
    def notes_errors(self) -> List[str]:
        return self._cache.setdefault("__errors__", [])

    @property
    def agent_ids(self) -> Optional[List[str]]:
        if "__agent_ids__" in self._cache:
            return self._cache["__agent_ids__"]
        ids = list(self._agent_filter)
        if self.tenant_id:
            tenant_agents = [a["agent_id"] for a in self.all_agents if (a.get("tenant_id") or "") == self.tenant_id]
            ids = [i for i in ids if i in tenant_agents] if ids else tenant_agents
            if not ids:
                ids = ["__none__"]
        self._cache["__agent_ids__"] = ids or None
        return self._cache["__agent_ids__"]

    def _flt(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ids = self.agent_ids
        if not ids:
            return rows
        s = set(ids)
        return [r for r in rows if r.get("agent_id") in s]

    @property
    def all_agents(self) -> List[Dict[str, Any]]:
        return self._get("all_agents", lambda: self.source.agents())

    @property
    def agents(self) -> List[Dict[str, Any]]:
        return self._flt(self.all_agents)

    def host(self, agent_id: Any) -> str:
        m = self._cache.get("__hosts__")
        if m is None:
            cnt = Counter((a.get("hostname") or "").lower() for a in self.all_agents)
            m = {}
            for a in self.all_agents:
                hn = a.get("hostname") or a.get("agent_id")
                if cnt[(a.get("hostname") or "").lower()] > 1:   # mesmo hostname em agentes diferentes
                    hn = f"{hn} ({str(a.get('agent_id'))[:8]})"
                m[a.get("agent_id")] = hn
            self._cache["__hosts__"] = m
        return m.get(agent_id) or str(agent_id or "—")

    @property
    def tasks(self) -> List[Dict[str, Any]]:
        return self._get("tasks", lambda: self._flt(self.source.tasks(agent_ids=self.agent_ids)))

    @property
    def active_tasks(self) -> List[Dict[str, Any]]:
        return [t for t in self.tasks if not t.get("removed") and t.get("enabled") is not False]

    @property
    def repos(self) -> List[Dict[str, Any]]:
        return self._get("repos", lambda: [r for r in self._flt(self.source.repositories(agent_ids=self.agent_ids)) if not r.get("removed")])

    @property
    def repo_history(self) -> List[Dict[str, Any]]:
        return self._get("repo_history", lambda: self._flt(self.source.repo_size_history(self.start, agent_ids=self.agent_ids)))

    @property
    def runs(self) -> List[Dict[str, Any]]:
        def load():
            rows = self._flt(self.source.runs(self.start, self.end, agent_ids=self.agent_ids))
            out = []
            for r in rows:
                st = to_dt(r.get("started_at")) or to_dt(r.get("completed_at"))
                if not st:
                    continue
                r = dict(r)
                r["started_at"] = st
                r["completed_at"] = to_dt(r.get("completed_at"))
                r["status"] = norm_status(r.get("raw_status") or r.get("status"))
                dur = to_float(r.get("duration_s"))
                if dur is None and r["completed_at"]:
                    dur = max(0.0, (r["completed_at"] - st).total_seconds())
                r["duration_s"] = dur
                for k in ("bytes", "bytes_added", "files", "files_new", "files_changed", "speed_bps"):
                    r[k] = to_float(r.get(k))
                if (not r.get("speed_bps")) and r.get("bytes") and dur:
                    r["speed_bps"] = r["bytes"] / dur if dur > 0 else None
                r["task_label"] = r.get("task_name") or (f"Tarefa {r.get('task_id')}" if r.get("task_id") is not None else "—")
                out.append(r)
            out.sort(key=lambda x: x["started_at"])
            return out
        return self._get("runs", load)

    @property
    def restores(self):
        return self._get("restores", lambda: self._flt(self.source.restores(self.start, self.end, agent_ids=self.agent_ids)))

    @property
    def verifications(self):
        return self._get("verifications", lambda: self._flt(self.source.verifications(self.start, self.end, agent_ids=self.agent_ids)))

    @property
    def job_failures(self):
        return self._get("job_failures", lambda: self._flt(self.source.job_failures(self.start, self.end, agent_ids=self.agent_ids)))

    @property
    def volumes(self):
        return self._get("volumes", lambda: self._flt(self.source.volumes(agent_ids=self.agent_ids)))

    @property
    def replication(self):
        return self._get("replication", lambda: self._flt(self.source.replication(agent_ids=self.agent_ids)))

    @property
    def metrics(self):
        return self._get("metrics", lambda: self._flt(self.source.metrics(self.start, self.end, agent_ids=self.agent_ids)))

    @property
    def events(self):
        return self._get("events", lambda: self._flt(self.source.events(self.start, self.end, agent_ids=self.agent_ids)))

    @property
    def log_errors(self):
        return self._get("log_errors", lambda: self._flt(self.source.log_error_summary(self.start, self.end, agent_ids=self.agent_ids)))

    @property
    def log_errors_daily(self):
        return self._get("log_errors_daily", lambda: self.source.log_error_daily(self.start, self.end, agent_ids=self.agent_ids))

    @property
    def security(self) -> Dict[str, List[Dict[str, Any]]]:
        def load():
            d = self.source.security(self.start, self.end, agent_ids=self.agent_ids) or {}
            return {"incidents": self._flt(d.get("incidents") or []), "events": self._flt(d.get("events") or [])}
        v = self._get("security", load)
        return v if isinstance(v, dict) else {"incidents": [], "events": []}

    @property
    def audit(self):
        return self._get("audit", lambda: self.source.audit(self.start, self.end))

    @property
    def tenants(self):
        return self._get("tenants", lambda: self.source.tenants())

    @property
    def inventory_status(self) -> Dict[str, Any]:
        v = self._get("inventory_status", lambda: self.source.inventory_status())
        return v if isinstance(v, dict) else {}

    # ── utilidades de período ──
    @property
    def day_list(self) -> List[date]:
        d0, d1 = self.start.date(), self.end.date()
        return [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]

    @property
    def day_labels(self) -> List[str]:
        return [d.strftime("%d/%m") for d in self.day_list]

    def setting(self, key: str, default: Any) -> Any:
        v = self.settings.get(key)
        if v in (None, ""):
            return default
        try:
            return type(default)(v) if not isinstance(default, bool) else str(v).lower() in ("1", "true", "sim", "yes")
        except (TypeError, ValueError):
            return default

    @property
    def rpo_hours(self) -> float:
        return float(self.setting("rpo_target_hours", 24.0))

    @property
    def success_goal(self) -> float:
        return float(self.setting("success_rate_goal", 95.0))

    # ── derivações reutilizadas ──
    def task_key(self, row: Dict[str, Any]) -> Tuple[Any, Any]:
        return (row.get("agent_id"), row.get("task_id"))

    @property
    def runs_by_task(self) -> Dict[Tuple[Any, Any], List[Dict[str, Any]]]:
        if "__rbt__" not in self._cache:
            m: Dict[Tuple[Any, Any], List[Dict[str, Any]]] = defaultdict(list)
            for r in self.runs:
                m[self.task_key(r)].append(r)
            self._cache["__rbt__"] = m
        return self._cache["__rbt__"]

    def last_success(self, task: Dict[str, Any]) -> Optional[datetime]:
        runs = self.runs_by_task.get(self.task_key(task), [])
        ok = [r["started_at"] for r in runs if r["status"] == "success"]
        best = max(ok) if ok else None
        lr = to_dt(task.get("last_run"))
        if lr and norm_status(task.get("last_status")) == "success" and (best is None or lr > best):
            best = lr
        return best

    def last_run(self, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        runs = self.runs_by_task.get(self.task_key(task), [])
        return runs[-1] if runs else None

    def failure_streak(self, task: Dict[str, Any]) -> int:
        n = 0
        for r in reversed(self.runs_by_task.get(self.task_key(task), [])):
            if r["status"] == "failed":
                n += 1
            elif r["status"] == "success":
                break
        return n

    def agent_status(self, a: Dict[str, Any]) -> str:
        st = str(a.get("status") or "").lower()
        hb = to_dt(a.get("last_heartbeat"))
        thr = float(self.setting("agent_offline_threshold_minutes", 60.0))
        if hb is not None:
            return "online" if (self.end - hb).total_seconds() <= thr * 60 else "offline"
        return "online" if st == "online" else "offline"


def _rate(ok: int, total: int) -> Optional[float]:
    return (ok / total * 100.0) if total else None


def _tone_rate(rate: Optional[float], goal: float) -> str:
    if rate is None:
        return "neutral"
    rate = round(rate, 1)
    if rate >= goal:
        return "ok"
    if rate >= goal - 10:
        return "warn"
    return "bad"


def _daily_counts(ctx: ReportContext, rows: Iterable[Dict[str, Any]], key: str = "started_at",
                  value: Optional[Callable[[Dict[str, Any]], float]] = None) -> List[float]:
    idx = {d: i for i, d in enumerate(ctx.day_list)}
    out = [0.0] * len(idx)
    for r in rows:
        d = to_dt(r.get(key))
        if d and d.date() in idx:
            out[idx[d.date()]] += (value(r) if value else 1) or 0
    return out


def _kpi(label: str, value: str, sub: str = "", tone: str = "neutral") -> Dict[str, str]:
    return {"label": label, "value": value, "sub": sub, "tone": tone}


def _chart(title: str, svg: str, data: Optional[Dict[str, Any]] = None, wide: bool = True) -> Dict[str, Any]:
    return {"title": title, "svg": svg, "data": data or {}, "wide": wide}


def _table(title: str, columns: List[str], rows: List[List[Any]], note: str = "", empty: str = "Nenhum registro no período.",
           max_rows: int = 1000) -> Dict[str, Any]:
    total = len(rows)
    shown = rows[:max_rows]
    if total > max_rows:
        note = (note + " " if note else "") + f"Exibindo {fmt_int(max_rows)} de {fmt_int(total)} linhas (o CSV contém todas)."
    return {"title": title, "columns": columns, "rows": shown, "all_rows": rows if total > max_rows else None,
            "note": note, "empty": empty}


def _coverage_notes(ctx: ReportContext) -> List[str]:
    notes = list(ctx.notes_errors)
    if ctx.info.get("product") == "server":
        inv = ctx.inventory_status
        missing = [ctx.host(a["agent_id"]) for a in ctx.agents if a["agent_id"] not in inv]
        stale = [ctx.host(k) for k, v in inv.items() if to_dt(v) and (ctx.end - to_dt(v)).total_seconds() > 86400
                 and (not ctx.agent_ids or k in ctx.agent_ids)]
        if missing:
            notes.append(f"{len(missing)} agente(s) ainda não enviaram o inventário detalhado (Agente 14.7.7+): "
                         + ", ".join(missing[:8]) + ("…" if len(missing) > 8 else "") + ".")
        if stale:
            notes.append(f"Inventário desatualizado há mais de 24 h: {', '.join(stale[:8])}.")
    return notes


# ───────────────────────────── Relatórios ─────────────────────────────

def task_rpo_target(ctx: "ReportContext", expected_h: Optional[float]) -> float:
    """RPO efetivo da tarefa: o alvo global (padrão 24 h) ou, para tarefas com intervalo maior
    (ex.: semanal), o próprio intervalo agendado com 25% de tolerância."""
    base = ctx.rpo_hours
    if expected_h and expected_h * 1.25 + 1 > base:
        return expected_h * 1.25 + 1
    return base


def _task_rpo_rows(ctx: ReportContext) -> List[Dict[str, Any]]:
    """Situação de RPO de cada tarefa ativa."""
    out = []
    for t in ctx.active_tasks:
        ls = ctx.last_success(t)
        age = (ctx.end - ls).total_seconds() / 3600 if ls else None
        expected = cron_interval_hours(t.get("schedule_cron")) if t.get("schedule_enabled") is not False else None
        target = task_rpo_target(ctx, expected)
        if age is None:
            status, tone = "Nunca concluída com sucesso", "bad"
        elif age > target:
            status, tone = "RPO violado", "bad"
        elif age > target * 0.75:
            status, tone = "Em risco", "warn"
        else:
            status, tone = "Dentro do RPO", "ok"
        late = bool(expected and age is not None and age > expected * 1.5 + 1)
        out.append({"task": t, "last_success": ls, "age_h": age, "expected_h": expected, "target_h": target, "status": status,
                    "tone": tone, "late_vs_schedule": late, "streak": ctx.failure_streak(t)})
    return out


def rep_operational_summary(ctx: ReportContext) -> Dict[str, Any]:
    runs = ctx.runs
    done = [r for r in runs if r["status"] in ("success", "failed")]
    ok = sum(1 for r in done if r["status"] == "success")
    fail = len(done) - ok
    rate = _rate(ok, len(done))
    processed = sum(r["bytes"] or 0 for r in runs if r["status"] == "success")
    added = sum(r["bytes_added"] or 0 for r in runs if r["status"] == "success")
    rpo = _task_rpo_rows(ctx)
    in_rpo = sum(1 for x in rpo if x["tone"] in ("ok", "warn"))
    agents = ctx.agents
    online = sum(1 for a in agents if ctx.agent_status(a) == "online")

    kpis = [
        _kpi("Taxa de sucesso", fmt_pct(rate), f"meta {fmt_pct(ctx.success_goal, 0)}", _tone_rate(rate, ctx.success_goal)),
        _kpi("Execuções concluídas", fmt_int(len(done)), f"{fmt_int(ok)} sucesso · {fmt_int(fail)} falha"),
        _kpi("Tarefas dentro do RPO", f"{fmt_int(in_rpo)}/{fmt_int(len(rpo))}", f"RPO alvo {fmt_num(ctx.rpo_hours, 0)} h",
             _tone_rate(_rate(in_rpo, len(rpo)), 100.0) if rpo else "neutral"),
        _kpi("Dados protegidos (lidos)", fmt_bytes(processed), f"{fmt_bytes(added)} de dados novos"),
        _kpi("Agentes online", f"{fmt_int(online)}/{fmt_int(len(agents))}", "", "ok" if online == len(agents) else "warn"),
    ]
    succ = _daily_counts(ctx, [r for r in runs if r["status"] == "success"])
    fl = _daily_counts(ctx, [r for r in runs if r["status"] == "failed"])
    daily_rate = [(_rate(int(s), int(s + f))) for s, f in zip(succ, fl)]
    charts = [
        _chart("Execuções por dia", svg_bars(ctx.day_labels, [{"name": "Sucesso", "values": succ, "tone": "ok"},
                                                               {"name": "Falha", "values": fl, "tone": "bad"}],
                                              title="Execuções por dia"),
               {"labels": ctx.day_labels, "success": succ, "failed": fl}),
        _chart("Taxa de sucesso diária", svg_line(ctx.day_labels, [{"name": "Taxa de sucesso", "values": daily_rate}], unit="%",
                                                  y_max=100, target=ctx.success_goal, title="Taxa de sucesso diária"),
               {"labels": ctx.day_labels, "rate": daily_rate}),
    ]
    by_agent: Dict[Any, Dict[str, Any]] = {}
    for a in agents:
        by_agent[a["agent_id"]] = {"ok": 0, "fail": 0, "bytes": 0.0, "last_ok": None}
    for r in runs:
        b = by_agent.setdefault(r.get("agent_id"), {"ok": 0, "fail": 0, "bytes": 0.0, "last_ok": None})
        if r["status"] == "success":
            b["ok"] += 1
            b["bytes"] += r["bytes"] or 0
            b["last_ok"] = max(filter(None, [b["last_ok"], r["started_at"]]))
        elif r["status"] == "failed":
            b["fail"] += 1
    rows = []
    for aid, b in sorted(by_agent.items(), key=lambda kv: ctx.host(kv[0]).lower()):
        a = next((x for x in agents if x["agent_id"] == aid), {})
        tot = b["ok"] + b["fail"]
        r_ = _rate(b["ok"], tot)
        age = (ctx.end - b["last_ok"]).total_seconds() / 3600 if b["last_ok"] else None
        st = ctx.agent_status(a) if a else "—"
        rows.append([ctx.host(aid), cell("Online" if st == "online" else "Offline", "ok" if st == "online" else "bad"),
                     fmt_int(tot), cell(fmt_pct(r_), _tone_rate(r_, ctx.success_goal)), fmt_int(b["fail"]),
                     fmt_bytes(b["bytes"]), fmt_dt(b["last_ok"]),
                     cell(fmt_age_hours(age), "bad" if age is None or age > ctx.rpo_hours else "ok")])
    tables = [_table("Desempenho por agente", ["Agente", "Status", "Execuções", "Sucesso", "Falhas", "Volume lido",
                                               "Último sucesso", "Idade do último backup"], rows)]

    findings, recs = [], []
    if rate is not None:
        if round(rate, 1) >= ctx.success_goal:
            findings.append({"tone": "ok", "text": f"Taxa de sucesso de {fmt_pct(rate)} atende à meta de {fmt_pct(ctx.success_goal, 0)}."})
        else:
            findings.append({"tone": "bad", "text": f"Taxa de sucesso de {fmt_pct(rate)} está abaixo da meta de {fmt_pct(ctx.success_goal, 0)} ({fmt_int(fail)} falhas)."})
            recs.append("Priorizar as causas listadas no relatório REP-04 (Falhas e Causa Raiz).")
        half = ctx.start + (ctx.end - ctx.start) / 2
        a1 = [r for r in done if r["started_at"] < half]
        a2 = [r for r in done if r["started_at"] >= half]
        r1, r2 = _rate(sum(1 for r in a1 if r["status"] == "success"), len(a1)), _rate(sum(1 for r in a2 if r["status"] == "success"), len(a2))
        if r1 is not None and r2 is not None and abs(r2 - r1) >= 2:
            findings.append({"tone": "ok" if r2 > r1 else "warn",
                             "text": f"Tendência: a taxa de sucesso {'melhorou' if r2 > r1 else 'piorou'} de {fmt_pct(r1)} para {fmt_pct(r2)} entre a primeira e a segunda metade do período."})
    else:
        findings.append({"tone": "warn", "text": "Nenhuma execução concluída no período selecionado."})
    silent = [ctx.host(aid) for aid, b in by_agent.items() if b["ok"] + b["fail"] == 0]
    if silent:
        findings.append({"tone": "warn", "text": f"{len(silent)} agente(s) sem nenhuma execução no período: {', '.join(silent[:10])}."})
        recs.append("Verificar se os agentes sem execuções possuem tarefas agendadas e se o serviço está ativo (REP-05).")
    viol = [x for x in rpo if x["tone"] == "bad"]
    if viol:
        findings.append({"tone": "bad", "text": f"{len(viol)} tarefa(s) fora do RPO de {fmt_num(ctx.rpo_hours, 0)} h (detalhes no REP-02)."})
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": recs}


def rep_rpo_compliance(ctx: ReportContext) -> Dict[str, Any]:
    rpo = _task_rpo_rows(ctx)
    target = ctx.rpo_hours
    counts = Counter(x["status"] for x in rpo)
    within = counts.get("Dentro do RPO", 0) + counts.get("Em risco", 0)
    worst = max((x["age_h"] for x in rpo if x["age_h"] is not None), default=None)
    kpis = [
        _kpi("Conformidade de RPO", fmt_pct(_rate(within, len(rpo))), f"alvo {fmt_num(target, 0)} h",
             _tone_rate(_rate(within, len(rpo)), 100.0) if rpo else "neutral"),
        _kpi("Tarefas monitoradas", fmt_int(len(rpo))),
        _kpi("RPO violado", fmt_int(counts.get("RPO violado", 0)), "", "bad" if counts.get("RPO violado") else "ok"),
        _kpi("Nunca concluídas", fmt_int(counts.get("Nunca concluída com sucesso", 0)), "",
             "bad" if counts.get("Nunca concluída com sucesso") else "ok"),
        _kpi("Maior atraso", fmt_age_hours(worst), "desde o último sucesso", "bad" if worst and worst > target else "neutral"),
    ]
    # conformidade diária: tarefa conforme se teve sucesso nas 'target' horas que antecedem o fim do dia
    succ_by_task = {k: [r["started_at"] for r in v if r["status"] == "success"] for k, v in ctx.runs_by_task.items()}
    daily = []
    keys = [ctx.task_key(x["task"]) for x in rpo]
    tgts = [x["target_h"] for x in rpo]
    for d in ctx.day_list:
        de = datetime(d.year, d.month, d.day, 23, 59, 59)
        if de > ctx.end:
            de = ctx.end
        if not keys:
            daily.append(None)
            continue
        okc = sum(1 for k, tg in zip(keys, tgts) if any(de - timedelta(hours=tg) < s <= de for s in succ_by_task.get(k, [])))
        daily.append(okc / len(keys) * 100)
    order = sorted(rpo, key=lambda x: (-(x["age_h"] if x["age_h"] is not None else 1e9)))
    charts = [
        _chart("Conformidade diária de RPO (% das tarefas com backup válido)",
               svg_line(ctx.day_labels, [{"name": "Conformidade", "values": daily}], unit="%", y_max=100, target=100, target_label="Ideal"),
               {"labels": ctx.day_labels, "compliance": daily}),
        _chart("Idade do último backup bem-sucedido (maiores atrasos)",
               svg_hbar([f'{ctx.host(x["task"]["agent_id"])} · {x["task"].get("name")}' for x in order],
                        [x["age_h"] if x["age_h"] is not None else None for x in order], unit="h",
                        tones=[x["tone"] for x in order], target=target, target_label="RPO"),
               {}),
        _chart("Situação das tarefas", svg_donut(list(counts.keys()), list(counts.values()),
                                                 [STATUS[{"Dentro do RPO": "ok", "Em risco": "warn"}.get(k, "bad")] for k in counts.keys()],
                                                 center_label="tarefas"), dict(counts), wide=False),
    ]
    rows = []
    for x in order:
        t = x["task"]
        rows.append([ctx.host(t.get("agent_id")), t.get("name"), cron_human(t.get("schedule_cron"), t.get("schedule_enabled")),
                     fmt_age_hours(x["expected_h"]) if x["expected_h"] else "—", fmt_age_hours(x["target_h"]), fmt_dt(x["last_success"]),
                     fmt_age_hours(x["age_h"]), fmt_int(x["streak"]) if x["streak"] else "0", cell(x["status"], x["tone"]),
                     cell("Atrasada" if x["late_vs_schedule"] else "No prazo", "warn" if x["late_vs_schedule"] else "ok")
                     if x["expected_h"] else "—"])
    tables = [_table("RPO por tarefa", ["Agente", "Tarefa", "Agendamento", "Intervalo esperado", "RPO alvo", "Último sucesso",
                                        "Idade", "Falhas seguidas", "RPO", "Agenda"], rows,
                     note=f"RPO alvo global: {fmt_num(target, 0)} h (Configurações > Relatórios). Tarefas com agendamento mais espaçado "
                          "(ex.: semanal) usam o próprio intervalo + 25% de tolerância.")]
    findings, recs = [], []
    if not rpo:
        findings.append({"tone": "warn", "text": "Nenhuma tarefa ativa encontrada para avaliar o RPO."})
    else:
        findings.append({"tone": _tone_rate(_rate(within, len(rpo)), 100.0),
                         "text": f"{fmt_int(within)} de {fmt_int(len(rpo))} tarefas possuem backup válido dentro de {fmt_num(target, 0)} h."})
        never = [x for x in rpo if x["age_h"] is None]
        if never:
            findings.append({"tone": "bad", "text": f"{len(never)} tarefa(s) nunca concluíram um backup com sucesso: "
                             + ", ".join(f'{ctx.host(x["task"]["agent_id"])}/{x["task"].get("name")}' for x in never[:6]) + "."})
            recs.append("Executar manualmente as tarefas que nunca concluíram e validar origem, destino e credenciais.")
        late = [x for x in rpo if x["late_vs_schedule"]]
        if late:
            findings.append({"tone": "warn", "text": f"{len(late)} tarefa(s) estão atrasadas em relação ao próprio agendamento."})
            recs.append("Conferir se o agendador do Agente está ativo e se a janela de backup é suficiente (REP-16).")
        streaky = [x for x in rpo if x["streak"] >= 3]
        if streaky:
            findings.append({"tone": "bad", "text": f"{len(streaky)} tarefa(s) com 3 ou mais falhas consecutivas."})
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": recs}


def rep_execution_history(ctx: ReportContext) -> Dict[str, Any]:
    runs = list(reversed(ctx.runs))
    done = [r for r in runs if r["status"] in ("success", "failed")]
    durs = [r["duration_s"] for r in done if r["duration_s"] is not None]
    speeds = [r["speed_bps"] for r in runs if r["status"] == "success" and r.get("speed_bps")]
    kpis = [
        _kpi("Execuções", fmt_int(len(runs)), f"{fmt_int(sum(1 for r in runs if r['status'] == 'running'))} em execução"),
        _kpi("Sucesso", fmt_int(sum(1 for r in runs if r["status"] == "success")), "", "ok"),
        _kpi("Falhas", fmt_int(sum(1 for r in runs if r["status"] == "failed")), "",
             "bad" if any(r["status"] == "failed" for r in runs) else "ok"),
        _kpi("Duração mediana", fmt_duration(percentile(durs, 0.5)), f"P95 {fmt_duration(percentile(durs, 0.95))}"),
        _kpi("Velocidade mediana", (fmt_bytes(percentile(speeds, 0.5)) + "/s") if speeds else "—"),
    ]
    series = []
    for st, tone in (("success", "ok"), ("failed", "bad"), ("cancelled", "neutral"), ("running", "warn")):
        vals = _daily_counts(ctx, [r for r in runs if r["status"] == st])
        if any(vals):
            series.append({"name": STATUS_LABEL[st], "values": vals, "tone": tone})
    charts = [_chart("Execuções por dia e situação", svg_bars(ctx.day_labels, series), {"labels": ctx.day_labels})]
    rows = [[fmt_dt(r["started_at"]), ctx.host(r.get("agent_id")), r["task_label"], r.get("repository_name") or "—",
             cell(STATUS_LABEL.get(r["status"], r["status"]), {"success": "ok", "failed": "bad", "running": "warn"}.get(r["status"])),
             fmt_duration(r["duration_s"]), fmt_bytes(r["bytes"]), fmt_bytes(r["bytes_added"]),
             fmt_int(r["files"]) if r["files"] is not None else "—",
             (fmt_bytes(r["speed_bps"]) + "/s") if r.get("speed_bps") else "—",
             (str(r.get("error") or "")[:160])] for r in runs]
    tables = [_table("Execuções (mais recentes primeiro)", ["Início", "Agente", "Tarefa", "Repositório", "Status", "Duração",
                                                             "Lido", "Novos dados", "Arquivos", "Velocidade", "Erro"], rows, max_rows=1500)]
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": [], "recommendations": []}


def rep_failures_rca(ctx: ReportContext) -> Dict[str, Any]:
    runs = ctx.runs
    fails = [r for r in runs if r["status"] == "failed"]
    cats: Dict[str, Dict[str, Any]] = {}
    pats: Dict[str, Dict[str, Any]] = {}
    for r in fails:
        cat, action = classify_error(r.get("error"))
        c = cats.setdefault(cat, {"n": 0, "agents": set(), "tasks": set(), "first": r["started_at"], "last": r["started_at"], "action": action})
        c["n"] += 1
        c["agents"].add(r.get("agent_id"))
        c["tasks"].add(ctx.task_key(r))
        c["first"] = min(c["first"], r["started_at"])
        c["last"] = max(c["last"], r["started_at"])
        p = error_pattern(r.get("error"))
        pp = pats.setdefault(p, {"n": 0, "cat": cat, "example": r, "agents": set()})
        pp["n"] += 1
        pp["agents"].add(r.get("agent_id"))
        if r["started_at"] > pp["example"]["started_at"]:
            pp["example"] = r
    # MTTR: do início de uma sequência de falhas até o próximo sucesso da mesma tarefa
    repairs = []
    for k, rs in ctx.runs_by_task.items():
        open_at = None
        for r in rs:
            if r["status"] == "failed" and open_at is None:
                open_at = r["started_at"]
            elif r["status"] == "success" and open_at is not None:
                repairs.append((r["started_at"] - open_at).total_seconds())
                open_at = None
    pending = [f for f in ctx.job_failures if not f.get("resolved_at")]
    tasks_aff = {ctx.task_key(r) for r in fails}
    agents_aff = {r.get("agent_id") for r in fails}
    kpis = [
        _kpi("Falhas no período", fmt_int(len(fails)), "", "bad" if fails else "ok"),
        _kpi("Tarefas afetadas", fmt_int(len(tasks_aff))),
        _kpi("Agentes afetados", fmt_int(len(agents_aff))),
        _kpi("Tempo médio de recuperação", fmt_duration(statistics.mean(repairs)) if repairs else "—", "falha → próximo sucesso"),
        _kpi("Falhas pendentes", fmt_int(len(pending)), "sem resolução registrada", "bad" if pending else "ok"),
    ]
    cat_sorted = sorted(cats.items(), key=lambda kv: -kv[1]["n"])
    charts = [
        _chart("Falhas por causa", svg_hbar([k for k, _ in cat_sorted], [v["n"] for _, v in cat_sorted], tones=["bad"] * len(cat_sorted)),
               {"labels": [k for k, _ in cat_sorted], "values": [v["n"] for _, v in cat_sorted]}),
        _chart("Falhas por dia", svg_bars(ctx.day_labels, [{"name": "Falhas", "values": _daily_counts(ctx, fails), "tone": "bad"}]),
               {"labels": ctx.day_labels}),
    ]
    rows_c = [[k, fmt_int(v["n"]), fmt_pct(v["n"] / len(fails) * 100) if fails else "—", fmt_int(len(v["agents"])),
               fmt_int(len(v["tasks"])), fmt_dt(v["first"]), fmt_dt(v["last"]), v["action"]] for k, v in cat_sorted]
    rows_p = [[p, v["cat"], fmt_int(v["n"]), fmt_int(len(v["agents"])),
               f'{ctx.host(v["example"].get("agent_id"))} / {v["example"]["task_label"]}', fmt_dt(v["example"]["started_at"])]
              for p, v in sorted(pats.items(), key=lambda kv: -kv[1]["n"])[:40]]
    rows_pending = [[ctx.host(f.get("agent_id")), f.get("task_name") or f.get("task_id"), (f.get("failure_reason") or "")[:200],
                     f"{fmt_int(f.get('retry_count') or 0)}/{fmt_int(f.get('max_retries') or 0)}", fmt_dt(f.get("first_failed_at")),
                     cell("Sim" if f.get("escalated") else "Não", "bad" if f.get("escalated") else None)] for f in pending]
    tables = [
        _table("Causas de falha", ["Causa", "Falhas", "% do total", "Agentes", "Tarefas", "Primeira", "Última", "Ação recomendada"], rows_c),
        _table("Mensagens de erro mais frequentes (agrupadas)", ["Padrão", "Causa", "Ocorrências", "Agentes", "Exemplo", "Última"], rows_p),
        _table("Falhas pendentes no Agente (fila de retentativas)", ["Agente", "Tarefa", "Motivo", "Tentativas", "Desde", "Escalada"], rows_pending,
               empty="Nenhuma falha pendente."),
    ]
    findings, recs = [], []
    if not fails:
        findings.append({"tone": "ok", "text": "Nenhuma falha de backup registrada no período."})
    else:
        top, tv = cat_sorted[0]
        findings.append({"tone": "bad", "text": f"A principal causa é '{top}', responsável por {fmt_pct(tv['n'] / len(fails) * 100)} das falhas ({fmt_int(tv['n'])})."})
        for k, v in cat_sorted[:3]:
            recs.append(f"{k}: {v['action']}")
        if repairs:
            findings.append({"tone": "neutral", "text": f"Em média, uma tarefa leva {fmt_duration(statistics.mean(repairs))} para voltar a ter sucesso após falhar."})
        no_msg = cats.get("Sem mensagem de erro")
        if no_msg:
            findings.append({"tone": "warn", "text": f"{fmt_int(no_msg['n'])} falha(s) sem mensagem de erro registrada."})
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": recs}


def _norm_path(p: str) -> str:
    p = str(p or "").strip().replace("\\", "/").rstrip("/").lower()
    return p or "/"


def rep_coverage_gaps(ctx: ReportContext) -> Dict[str, Any]:
    agents = ctx.agents
    tasks = [t for t in ctx.tasks if not t.get("removed")]
    tasks_by_agent: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for t in tasks:
        tasks_by_agent[t.get("agent_id")].append(t)
    gaps: List[List[Any]] = []

    def gap(sev: str, kind: str, agent: Any, obj: str, detail: str, action: str):
        gaps.append([cell({"bad": "Crítico", "warn": "Atenção"}[sev], sev), kind, ctx.host(agent), obj, detail, action])

    for a in agents:
        aid = a["agent_id"]
        if ctx.agent_status(a) != "online":
            hb = to_dt(a.get("last_heartbeat"))
            gap("bad", "Agente offline", aid, a.get("hostname") or aid,
                f"Sem comunicação desde {fmt_dt(hb)}" if hb else "Nunca enviou heartbeat",
                "Verificar o serviço do GBOC Agent e a conectividade com o Server.")
        if not [t for t in tasks_by_agent.get(aid, []) if t.get("enabled") is not False]:
            gap("bad", "Agente sem tarefa ativa", aid, a.get("hostname") or aid, "Nenhuma tarefa de backup habilitada",
                "Criar ao menos uma tarefa de backup para este host.")
    for t in tasks:
        aid = t.get("agent_id")
        name = t.get("name") or f"Tarefa {t.get('task_id')}"
        if t.get("enabled") is False:
            gap("warn", "Tarefa desabilitada", aid, name, "A tarefa existe mas está desabilitada", "Reabilitar ou remover a tarefa.")
            continue
        if not t.get("schedule_cron") or t.get("schedule_enabled") is False:
            gap("warn", "Tarefa sem agendamento", aid, name, "Executa apenas manualmente", "Definir um agendamento coerente com o RPO.")
        if not t.get("source_paths") and t.get("source_paths") is not None:
            gap("warn", "Tarefa sem origem", aid, name, "Nenhum caminho de origem configurado", "Configurar as pastas/volumes de origem.")
        runs = ctx.runs_by_task.get(ctx.task_key(t), [])
        if not runs and not to_dt(t.get("last_run")):
            gap("bad", "Tarefa nunca executada", aid, name, "Nenhuma execução registrada", "Executar a tarefa manualmente e validar.")
        elif runs and not any(r["status"] == "success" for r in runs):
            gap("bad", "Sem sucesso no período", aid, name, f"{fmt_int(len(runs))} execução(ões), nenhuma com sucesso",
                "Corrigir a causa da falha (REP-04).")
    # Volumes do host não incluídos em nenhuma origem
    vol_by_agent: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for v in ctx.volumes:
        vol_by_agent[v.get("agent_id")].append(v)
    for aid, vols in vol_by_agent.items():
        srcs = [_norm_path(p) for t in tasks_by_agent.get(aid, []) if t.get("enabled") is not False for p in (t.get("source_paths") or [])]
        if not srcs:
            continue
        for v in vols:
            mp = _norm_path(v.get("mountpoint"))
            if (v.get("used_bytes") or 0) < 1024 ** 3:
                continue
            covered = any(s == mp or s.startswith(mp + "/") or (mp == "/" and s.startswith("/")) or
                          (len(mp) == 2 and mp.endswith(":") and s.startswith(mp)) for s in srcs)
            if not covered:
                gap("warn", "Volume sem backup", aid, v.get("mountpoint"),
                    f"{fmt_bytes(v.get('used_bytes'))} em uso e nenhuma tarefa inclui este volume",
                    "Avaliar se o volume contém dados de negócio e incluí-lo em uma tarefa.")
    protected = sum(1 for a in agents if ctx.agent_status(a) == "online" and
                    any(t.get("enabled") is not False and any(r["status"] == "success" for r in ctx.runs_by_task.get(ctx.task_key(t), []))
                        for t in tasks_by_agent.get(a["agent_id"], [])))
    kinds = Counter(cell_text(g[1]) for g in gaps)
    kpis = [
        _kpi("Agentes protegidos", f"{fmt_int(protected)}/{fmt_int(len(agents))}", "online, com tarefa e backup com sucesso",
             _tone_rate(_rate(protected, len(agents)), 100.0) if agents else "neutral"),
        _kpi("Tarefas cadastradas", fmt_int(len(tasks)), f"{fmt_int(sum(1 for t in tasks if t.get('enabled') is not False))} ativas"),
        _kpi("Lacunas críticas", fmt_int(sum(1 for g in gaps if g[0]["tone"] == "bad")), "", "bad" if any(g[0]["tone"] == "bad" for g in gaps) else "ok"),
        _kpi("Pontos de atenção", fmt_int(sum(1 for g in gaps if g[0]["tone"] == "warn")), "", "warn" if gaps else "ok"),
    ]
    charts = [_chart("Lacunas por tipo", svg_hbar(list(kinds.keys()), list(kinds.values()), tones=["warn"] * len(kinds)), dict(kinds))] if kinds else []
    gaps.sort(key=lambda g: (0 if g[0]["tone"] == "bad" else 1, g[1], g[2]))
    tables = [_table("Lacunas de proteção encontradas", ["Severidade", "Tipo", "Agente", "Objeto", "Detalhe", "Ação recomendada"], gaps,
                     empty="Nenhuma lacuna encontrada — todos os agentes possuem tarefas ativas com backup bem-sucedido.")]
    findings = [{"tone": "ok" if not gaps else ("bad" if any(g[0]["tone"] == "bad" for g in gaps) else "warn"),
                 "text": "Cobertura completa." if not gaps else f"{len(gaps)} lacuna(s) de proteção identificada(s)."}]
    recs = sorted({cell_text(g[5]) for g in gaps if g[0]["tone"] == "bad"})[:6]
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": recs}


def _repo_growth(ctx: ReportContext) -> List[Dict[str, Any]]:
    hist: Dict[Tuple[Any, Any], List[Tuple[datetime, float]]] = defaultdict(list)
    for h in ctx.repo_history:
        d = to_dt(h.get("recorded_at"))
        v = to_float(h.get("size_bytes"))
        if d and v is not None:
            hist[(h.get("agent_id"), h.get("repo_id"))].append((d, v))
    added_by_repo: Dict[Tuple[Any, str], float] = defaultdict(float)
    for r in ctx.runs:
        if r["status"] == "success" and r.get("repository_name"):
            added_by_repo[(r.get("agent_id"), r["repository_name"])] += r.get("bytes_added") or 0
    out = []
    for rp in ctx.repos:
        key = (rp.get("agent_id"), rp.get("repo_id"))
        pts = sorted(hist.get(key, []))
        slope = linear_slope_per_day(pts)
        method = "série histórica de tamanho"
        if slope is None:
            add = added_by_repo.get((rp.get("agent_id"), rp.get("name")), 0)
            slope = add / ctx.days if add else None
            method = "dados novos das execuções" if add else "sem histórico"
        size = to_float(rp.get("size_bytes"))
        free = to_float(rp.get("free_bytes"))
        cap = to_float(rp.get("capacity_bytes"))
        days_full = (free / slope) if (slope and slope > 0 and free is not None) else None
        used_pct = ((cap - free) / cap * 100) if (cap and free is not None) else None
        if days_full is not None and days_full < 30:
            tone, st = "bad", "Esgota em menos de 30 dias"
        elif used_pct is not None and used_pct >= 90:
            tone, st = "bad", "Disco acima de 90%"
        elif (days_full is not None and days_full < 90) or (used_pct is not None and used_pct >= 80):
            tone, st = "warn", "Atenção"
        elif size is None:
            tone, st = "neutral", "Sem medição de tamanho"
        else:
            tone, st = "ok", "Saudável"
        out.append({"repo": rp, "size": size, "free": free, "cap": cap, "slope": slope, "method": method,
                    "days_full": days_full, "used_pct": used_pct, "tone": tone, "status": st})
    return out


def rep_capacity_forecast(ctx: ReportContext) -> Dict[str, Any]:
    g = _repo_growth(ctx)
    total = sum(x["size"] or 0 for x in g)
    growth_day = sum(x["slope"] or 0 for x in g if x["slope"] and x["slope"] > 0)
    risky = [x for x in g if x["tone"] == "bad"]
    vols = [v for v in ctx.volumes if (to_float(v.get("total_bytes")) or 0) >= 1024 ** 3]
    vol_rows, vol_crit = [], 0
    for v in sorted(vols, key=lambda v: -((v.get("used_bytes") or 0) / (v.get("total_bytes") or 1))):
        tot = to_float(v.get("total_bytes")) or 0
        pct = ((to_float(v.get("used_bytes")) or 0) / tot * 100) if tot else None
        tone = "bad" if pct is not None and pct >= 90 else "warn" if pct is not None and pct >= 80 else "ok"
        vol_crit += 1 if tone == "bad" else 0
        vol_rows.append([ctx.host(v.get("agent_id")), v.get("mountpoint"), v.get("fstype") or "—", fmt_bytes(tot),
                         fmt_bytes(v.get("used_bytes")), fmt_bytes(v.get("free_bytes")), cell(fmt_pct(pct), tone)])
    kpis = [
        _kpi("Armazenamento ocupado", fmt_bytes(total), f"{fmt_int(len(g))} repositório(s)"),
        _kpi("Crescimento estimado", f"{fmt_bytes(growth_day * 30)}/mês" if growth_day else "—", "tendência do período"),
        _kpi("Repositórios em risco", fmt_int(len(risky)), "esgotamento < 30 dias ou disco > 90%", "bad" if risky else "ok"),
        _kpi("Volumes críticos", fmt_int(vol_crit), "acima de 90% de uso nos hosts", "bad" if vol_crit else "ok"),
    ]
    # Série total por dia (último valor conhecido de cada repositório, propagado)
    by_repo: Dict[Tuple[Any, Any], List[Tuple[datetime, float]]] = defaultdict(list)
    for h in ctx.repo_history:
        d, v = to_dt(h.get("recorded_at")), to_float(h.get("size_bytes"))
        if d and v is not None:
            by_repo[(h.get("agent_id"), h.get("repo_id"))].append((d, v))
    series_total = []
    for d in ctx.day_list:
        de = datetime(d.year, d.month, d.day, 23, 59, 59)
        s, any_ = 0.0, False
        for pts in by_repo.values():
            prev = [v for (t, v) in pts if t <= de]
            if prev:
                s += prev[-1]
                any_ = True
        series_total.append(s if any_ else None)
    charts = [
        _chart("Armazenamento total ocupado por dia", svg_line(ctx.day_labels, [{"name": "Total", "values": series_total}], unit="bytes"),
               {"labels": ctx.day_labels, "total": series_total}),
    ]
    with_days = sorted([x for x in g if x["days_full"] is not None], key=lambda x: x["days_full"])
    if with_days:
        charts.append(_chart("Dias até o esgotamento do destino", svg_hbar(
            [f'{ctx.host(x["repo"].get("agent_id"))} · {x["repo"].get("name")}' for x in with_days],
            [x["days_full"] for x in with_days], unit="d", tones=[x["tone"] for x in with_days], target=30, target_label="Limite")))
    rows = []
    for x in sorted(g, key=lambda x: ({"bad": 0, "warn": 1, "neutral": 2, "ok": 3}[x["tone"]], -(x["size"] or 0))):
        rp = x["repo"]
        base = {"série histórica de tamanho": "histórico", "dados novos das execuções": "execuções"}.get(x["method"])
        rows.append([ctx.host(rp.get("agent_id")), rp.get("name"), f'{rp.get("engine") or "—"} · {rp.get("type") or "local"}',
                     rp.get("target") or rp.get("path") or "—", fmt_bytes(x["size"]),
                     fmt_int(rp.get("snapshot_count")) if rp.get("snapshot_count") is not None else "—",
                     ((fmt_bytes(x["slope"]) + "/dia") + (f" ({base})" if base else "")) if x["slope"] else "—", fmt_bytes(x["free"]),
                     fmt_pct(x["used_pct"]), fmt_age_hours(x["days_full"] * 24) if x["days_full"] is not None else "—",
                     cell(x["status"], x["tone"])])
    tables = [
        _table("Repositórios: ocupação e previsão", ["Agente", "Repositório", "Motor · tipo", "Destino", "Tamanho", "Snapshots",
                                                      "Crescimento", "Livre no destino", "Uso do disco", "Esgota em", "Situação"], rows,
               note="Crescimento calculado pela série histórica de tamanho; sem histórico, pelos dados novos das execuções do período.",
               empty="Nenhum repositório sincronizado."),
        _table("Volumes dos hosts", ["Agente", "Volume", "Sistema de arquivos", "Total", "Usado", "Livre", "Uso"], vol_rows,
               empty="Volumes ainda não informados pelos agentes."),
    ]
    findings, recs = [], []
    for x in risky[:6]:
        findings.append({"tone": "bad", "text": f'{ctx.host(x["repo"].get("agent_id"))} / {x["repo"].get("name")}: {x["status"].lower()}'
                         + (f' (≈ {fmt_num(x["days_full"], 0)} dias)' if x["days_full"] is not None else "") + "."})
    if risky:
        recs.append("Ampliar o destino, mover dados antigos para um repositório de arquivamento ou reduzir a retenção dos repositórios em risco.")
    if vol_crit:
        recs.append("Liberar espaço nos volumes acima de 90%: snapshots VSS antigos, logs e temporários impactam backups e o próprio sistema.")
    no_size = [x for x in g if x["size"] is None]
    if no_size:
        findings.append({"tone": "warn", "text": f"{len(no_size)} repositório(s) ainda sem medição de tamanho (o Agente mede periodicamente)."})
    if not findings:
        findings.append({"tone": "ok", "text": "Nenhum destino de backup com risco de esgotamento identificado."})
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": recs}


def rep_throughput(ctx: ReportContext) -> Dict[str, Any]:
    ok_runs = [r for r in ctx.runs if r["status"] == "success"]
    processed = sum(r["bytes"] or 0 for r in ok_runs)
    added = sum(r["bytes_added"] or 0 for r in ok_runs)
    speeds = [r["speed_bps"] for r in ok_runs if r.get("speed_bps")]
    durs = [r["duration_s"] for r in ok_runs if r["duration_s"] is not None]
    kpis = [
        _kpi("Dados lidos", fmt_bytes(processed), f"{fmt_int(len(ok_runs))} execuções com sucesso"),
        _kpi("Dados novos enviados", fmt_bytes(added), "após deduplicação/incremental"),
        _kpi("Taxa de mudança", fmt_pct(added / processed * 100) if processed else "—", "novos ÷ lidos"),
        _kpi("Velocidade mediana", (fmt_bytes(percentile(speeds, 0.5)) + "/s") if speeds else "—"),
        _kpi("Duração mediana", fmt_duration(percentile(durs, 0.5)), f"P95 {fmt_duration(percentile(durs, 0.95))}"),
    ]
    d_proc = _daily_counts(ctx, ok_runs, value=lambda r: r["bytes"] or 0)
    d_add = _daily_counts(ctx, ok_runs, value=lambda r: r["bytes_added"] or 0)
    sp_by_day: Dict[date, List[float]] = defaultdict(list)
    for r in ok_runs:
        if r.get("speed_bps"):
            sp_by_day[r["started_at"].date()].append(r["speed_bps"])
    d_speed = [percentile(sp_by_day.get(d, []), 0.5) for d in ctx.day_list]
    charts = [
        _chart("Volume por dia", svg_bars(ctx.day_labels, [{"name": "Lido", "values": d_proc}, {"name": "Novos dados", "values": d_add}],
                                          unit="bytes", stacked=False), {"labels": ctx.day_labels, "processed": d_proc, "added": d_add}),
        _chart("Velocidade mediana por dia", svg_line(ctx.day_labels, [{"name": "Velocidade", "values": d_speed}], unit="bytes"),
               {"labels": ctx.day_labels, "speed": d_speed}),
    ]
    rows = []
    for k, rs in ctx.runs_by_task.items():
        ok = [r for r in rs if r["status"] == "success"]
        if not ok:
            continue
        dd = [r["duration_s"] for r in ok if r["duration_s"] is not None]
        med = percentile(dd, 0.5)
        last = ok[-1]["duration_s"]
        trend_tone = "warn" if (med and last and last > med * 2) else None
        rows.append((sum(r["bytes"] or 0 for r in ok), [
            ctx.host(k[0]), ok[-1]["task_label"], fmt_int(len(ok)), fmt_duration(med), fmt_duration(percentile(dd, 0.95)),
            cell(fmt_duration(last), trend_tone), (fmt_bytes(percentile([r["speed_bps"] for r in ok if r.get("speed_bps")], 0.5)) + "/s")
            if any(r.get("speed_bps") for r in ok) else "—",
            fmt_bytes(sum(r["bytes"] or 0 for r in ok)), fmt_bytes(sum(r["bytes_added"] or 0 for r in ok))]))
    rows.sort(key=lambda x: -x[0])
    tables = [_table("Desempenho por tarefa", ["Agente", "Tarefa", "Execuções", "Duração mediana", "Duração P95", "Última duração",
                                               "Velocidade mediana", "Total lido", "Total novos"], [r for _, r in rows],
                     note="Última duração destacada quando passa do dobro da mediana da tarefa.")]
    findings = []
    slow = [r for _, r in rows if isinstance(r[5], dict) and r[5].get("tone") == "warn"]
    if slow:
        findings.append({"tone": "warn", "text": f"{len(slow)} tarefa(s) tiveram a última execução com mais do dobro da duração mediana."})
    if processed and added / processed > 0.3:
        findings.append({"tone": "warn", "text": f"Taxa de mudança alta ({fmt_pct(added / processed * 100)}): verificar crescimento real de dados ou alterações em massa."})
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings,
            "recommendations": ["Tarefas com duração crescente podem precisar de janela maior, exclusões de arquivos temporários ou motor mais eficiente."] if slow else []}


def _ver_tuple(v: Any) -> Tuple[int, ...]:
    nums = re.findall(r"\d+", str(v or ""))
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def rep_fleet_inventory(ctx: ReportContext) -> Dict[str, Any]:
    agents = ctx.agents
    ref = ctx.info.get("recommended_agent_version") or ctx.info.get("server_version")
    tasks_by: Counter = Counter(t.get("agent_id") for t in ctx.tasks if not t.get("removed"))
    repos_by: Counter = Counter(r.get("agent_id") for r in ctx.repos)
    online = [a for a in agents if ctx.agent_status(a) == "online"]
    outdated = [a for a in agents if ref and a.get("agent_version") and _ver_tuple(a.get("agent_version")) < _ver_tuple(ref)]
    versions = Counter(a.get("agent_version") or "desconhecida" for a in agents)
    oss = Counter((a.get("os_info") or "desconhecido").split(" (")[0][:40] for a in agents)
    kpis = [
        _kpi("Agentes", fmt_int(len(agents))),
        _kpi("Online", fmt_int(len(online)), "", "ok" if len(online) == len(agents) else "warn"),
        _kpi("Versões em uso", fmt_int(len(versions))),
        _kpi("Desatualizados", fmt_int(len(outdated)), f"referência {ref or '—'}", "warn" if outdated else "ok"),
    ]
    charts = [
        _chart("Versões do Agente", svg_donut(list(versions.keys()), list(versions.values()), center_label="agentes"), dict(versions), wide=False),
        _chart("Sistemas operacionais", svg_donut(list(oss.keys()), list(oss.values()), center_label="agentes"), dict(oss), wide=False),
    ]
    rows = []
    for a in sorted(agents, key=lambda a: (a.get("hostname") or "").lower()):
        st = ctx.agent_status(a)
        inv = ctx.inventory_status.get(a["agent_id"])
        rows.append([ctx.host(a["agent_id"]), a.get("ip_address") or "—", a.get("os_info") or "—",
                     cell(a.get("agent_version") or "—", "warn" if a in outdated else None), a.get("tenant_id") or "—",
                     cell("Online" if st == "online" else "Offline", "ok" if st == "online" else "bad"), fmt_dt(a.get("last_heartbeat")),
                     fmt_pct(to_float(a.get("cpu_usage"))), fmt_pct(to_float(a.get("ram_usage"))), fmt_pct(to_float(a.get("disk_usage"))),
                     fmt_int(tasks_by.get(a["agent_id"], 0)), fmt_int(repos_by.get(a["agent_id"], 0)), fmt_dt(inv) if inv else "—",
                     fmt_date(a.get("registered_at"))])
    tables = [_table("Inventário de agentes", ["Host", "IP", "Sistema", "Versão", "Cliente", "Status", "Último contato", "CPU", "RAM",
                                               "Disco", "Tarefas", "Repositórios", "Inventário", "Registrado em"], rows)]
    findings, recs = [], []
    if outdated:
        findings.append({"tone": "warn", "text": f"{len(outdated)} agente(s) com versão anterior a {ref}."})
        recs.append("Atualizar os agentes desatualizados para receber correções e o inventário completo (relatórios e gerenciamento remoto).")
    off = [a for a in agents if a not in online]
    if off:
        findings.append({"tone": "bad", "text": f"{len(off)} agente(s) offline: {', '.join((a.get('hostname') or a['agent_id']) for a in off[:8])}."})
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": recs}


def rep_restores_tests(ctx: ReportContext) -> Dict[str, Any]:
    rs = ctx.restores
    vs = ctx.verifications
    ok = [r for r in rs if norm_status(r.get("status")) == "success"]
    durs = [to_float(r.get("duration_seconds")) for r in ok if to_float(r.get("duration_seconds")) is not None]
    vok = [v for v in vs if norm_status(v.get("status")) == "success" or str(v.get("status") or "").lower() in ("passed", "healthy", "valid")]
    vfail = [v for v in vs if v not in vok]
    kpis = [
        _kpi("Restaurações", fmt_int(len(rs)), f"{fmt_int(len(ok))} com sucesso"),
        _kpi("Sucesso nas restaurações", fmt_pct(_rate(len(ok), len(rs))), "", _tone_rate(_rate(len(ok), len(rs)), 95.0) if rs else "neutral"),
        _kpi("Volume restaurado", fmt_bytes(sum(to_float(r.get("bytes_restored")) or 0 for r in ok))),
        _kpi("Tempo médio de restauração", fmt_duration(statistics.mean(durs)) if durs else "—", "RTO observado"),
        _kpi("Verificações", fmt_int(len(vs)), f"{fmt_int(len(vfail))} com problema", "bad" if vfail else ("ok" if vs else "neutral")),
    ]
    charts = [_chart("Restaurações por dia", svg_bars(ctx.day_labels, [
        {"name": "Sucesso", "values": _daily_counts(ctx, ok, "created_at"), "tone": "ok"},
        {"name": "Falha", "values": _daily_counts(ctx, [r for r in rs if r not in ok], "created_at"), "tone": "bad"}]), {})]
    rows_r = [[fmt_dt(r.get("created_at")), ctx.host(r.get("agent_id")), r.get("repository_name") or "—", r.get("snapshot_id") or "—",
               r.get("target_path") or "—", cell(STATUS_LABEL.get(norm_status(r.get("status")), r.get("status")),
                                                  "ok" if r in ok else "bad"),
               f"{fmt_int(r.get('files_restored'))}/{fmt_int(r.get('total_files'))}", fmt_bytes(r.get("bytes_restored")),
               fmt_duration(r.get("duration_seconds")), (r.get("error_message") or "")[:160]]
              for r in sorted(rs, key=lambda r: to_dt(r.get("created_at")) or datetime.min, reverse=True)]
    rows_v = [[fmt_dt(v.get("finished_at") or v.get("started_at")), ctx.host(v.get("agent_id")),
               {"integrity": "Integridade do repositório", "surebackup": "SureBackup (boot/aplicação)"}.get(v.get("kind"), v.get("kind")),
               v.get("subject") or "—", cell(v.get("status") or "—", "ok" if v in vok else "bad"),
               fmt_int(v.get("errors_found")) if v.get("errors_found") is not None else "—", (v.get("summary") or "")[:160]]
              for v in sorted(vs, key=lambda v: to_dt(v.get("finished_at") or v.get("started_at")) or datetime.min, reverse=True)]
    verified = {(v.get("agent_id"), v.get("subject")) for v in vs if v.get("kind") == "integrity"}
    never = [rp for rp in ctx.repos if (rp.get("agent_id"), rp.get("name")) not in verified]
    rows_n = [[ctx.host(rp.get("agent_id")), rp.get("name"), rp.get("engine") or "—", fmt_bytes(rp.get("size_bytes"))] for rp in never]
    tables = [
        _table("Restaurações realizadas", ["Data", "Agente", "Repositório", "Snapshot", "Destino", "Status", "Arquivos", "Volume", "Duração", "Erro"], rows_r),
        _table("Verificações de integridade e testes de recuperação", ["Data", "Agente", "Tipo", "Objeto", "Resultado", "Erros", "Resumo"], rows_v),
        _table("Repositórios sem verificação de integridade no período", ["Agente", "Repositório", "Motor", "Tamanho"], rows_n,
               empty="Todos os repositórios foram verificados no período."),
    ]
    findings, recs = [], []
    if not rs and not vs:
        findings.append({"tone": "warn", "text": "Nenhuma restauração ou teste de recuperação registrado no período: a recuperação não foi comprovada."})
        recs.append("Agendar testes periódicos de restauração (ex.: mensal) para comprovar o RTO e a integridade dos backups.")
    if never:
        findings.append({"tone": "warn", "text": f"{len(never)} repositório(s) sem verificação de integridade no período."})
        recs.append("Agendar a verificação de integridade dos repositórios ao menos uma vez por mês.")
    if vfail:
        findings.append({"tone": "bad", "text": f"{len(vfail)} verificação(ões) encontraram problemas."})
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": recs}


def rep_dr_readiness(ctx: ReportContext) -> Dict[str, Any]:
    rpo = _task_rpo_rows(ctx)
    rpo_by_agent: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for x in rpo:
        rpo_by_agent[x["task"].get("agent_id")].append(x)
    offsite_agents = {r.get("agent_id") for r in ctx.repos if (r.get("type") or "local").lower() not in ("local", "")}
    offsite_agents |= {p.get("agent_id") for p in ctx.replication if p.get("enabled") is not False}
    tested = {r.get("agent_id") for r in ctx.restores if norm_status(r.get("status")) == "success"}
    tested |= {v.get("agent_id") for v in ctx.verifications}
    pending = {f.get("agent_id") for f in ctx.job_failures if not f.get("resolved_at")}
    recent_ok = defaultdict(lambda: None)
    for r in ctx.runs:
        if r["status"] == "success":
            recent_ok[r.get("agent_id")] = r["started_at"]
    crit = ["Backup com sucesso nas últimas 24 h", "Todas as tarefas dentro do RPO", "Cópia fora do host (nuvem/replicação)",
            "Recuperação testada no período", "Sem falhas pendentes", "Agente online"]
    rows, scores = [], []
    for a in sorted(ctx.agents, key=lambda a: ctx.host(a["agent_id"]).lower()):
        aid = a["agent_id"]
        lst = recent_ok[aid]
        checks = [
            bool(lst and (ctx.end - lst).total_seconds() <= 86400),
            bool(rpo_by_agent.get(aid)) and all(x["tone"] in ("ok", "warn") for x in rpo_by_agent.get(aid, [])),
            aid in offsite_agents,
            aid in tested,
            aid not in pending,
            ctx.agent_status(a) == "online",
        ]
        score = sum(checks) / len(checks) * 100
        scores.append((ctx.host(aid), round(score)))
        tone = "ok" if score >= 83 else "warn" if score >= 50 else "bad"
        rows.append([ctx.host(aid)] + [cell("✔" if c else "✘", "ok" if c else "bad") for c in checks] + [cell(f"{score:.0f}/100", tone)])
    avg = statistics.mean([s for _, s in scores]) if scores else None
    ready = sum(1 for _, s in scores if s >= 83)
    kpis = [
        _kpi("Prontidão média", f"{avg:.0f}/100" if avg is not None else "—", "", "ok" if avg and avg >= 83 else "warn" if avg and avg >= 50 else "bad"),
        _kpi("Agentes prontos", f"{fmt_int(ready)}/{fmt_int(len(scores))}", "≥ 5 de 6 critérios"),
        _kpi("Sem cópia externa", fmt_int(sum(1 for a in ctx.agents if a['agent_id'] not in offsite_agents)), "regra 3-2-1",
             "warn" if any(a['agent_id'] not in offsite_agents for a in ctx.agents) else "ok"),
        _kpi("Sem teste de recuperação", fmt_int(sum(1 for a in ctx.agents if a['agent_id'] not in tested)), "no período"),
    ]
    order = sorted(scores, key=lambda x: x[1])
    charts = [_chart("Pontuação de prontidão por agente", svg_hbar([n for n, _ in order], [s for _, s in order],
                     tones=["ok" if s >= 83 else "warn" if s >= 50 else "bad" for _, s in order], max_items=25))]
    tables = [_table("Critérios de prontidão para recuperação de desastres", ["Agente"] + crit + ["Pontuação"], rows)]
    findings, recs = [], []
    for i, label in enumerate(crit):
        miss = [r[0] for r in rows if r[1 + i]["v"] == "✘"]
        if miss:
            findings.append({"tone": "bad" if i in (0, 1, 5) else "warn", "text": f"{label}: não atendido em {len(miss)} agente(s)."})
    if any(a["agent_id"] not in offsite_agents for a in ctx.agents):
        recs.append("Configurar uma cópia fora do host (repositório em nuvem ou política de replicação) para cumprir a regra 3-2-1.")
    if any(a["agent_id"] not in tested for a in ctx.agents):
        recs.append("Realizar e registrar testes de restauração/verificação para comprovar a recuperabilidade.")
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": recs}


def rep_security(ctx: ReportContext) -> Dict[str, Any]:
    sec = ctx.security
    inc, evs = sec["incidents"], sec["events"]
    open_inc = [i for i in inc if not i.get("resolved_at") and str(i.get("status") or "").lower() not in ("resolved", "closed", "false_positive")]
    mttr = [(to_dt(i.get("resolved_at")) - to_dt(i.get("detected_at"))).total_seconds() for i in inc
            if to_dt(i.get("resolved_at")) and to_dt(i.get("detected_at"))]
    types = Counter(e.get("type") or "evento" for e in evs)
    kpis = [
        _kpi("Incidentes", fmt_int(len(inc)), "", "bad" if inc else "ok"),
        _kpi("Incidentes em aberto", fmt_int(len(open_inc)), "", "bad" if open_inc else "ok"),
        _kpi("Tempo médio de resposta", fmt_duration(statistics.mean(mttr)) if mttr else "—", "detecção → resolução"),
        _kpi("Eventos de segurança", fmt_int(len(evs))),
        _kpi("Agentes com eventos", fmt_int(len({e.get("agent_id") for e in evs} | {i.get("agent_id") for i in inc}))),
    ]
    charts = [_chart("Eventos de segurança por dia", svg_bars(ctx.day_labels, [{"name": "Eventos", "values": _daily_counts(ctx, evs, "ts"), "tone": "serious"},
                                                                          {"name": "Incidentes", "values": _daily_counts(ctx, inc, "detected_at"), "tone": "bad"}]))]
    if types:
        charts.append(_chart("Eventos por tipo", svg_hbar(list(types.keys()), list(types.values()), tones=["serious"] * len(types))))
    rows_i = [[fmt_dt(i.get("detected_at")), ctx.host(i.get("agent_id")), i.get("external_id") or i.get("id") or "—",
               cell(i.get("status") or "—", "bad" if i in open_inc else "ok"), fmt_dt(i.get("resolved_at")), (i.get("summary") or "")[:200]]
              for i in sorted(inc, key=lambda i: to_dt(i.get("detected_at")) or datetime.min, reverse=True)]
    rows_e = [[fmt_dt(e.get("ts")), ctx.host(e.get("agent_id")), e.get("type") or "—", (e.get("message") or "")[:220]]
              for e in sorted(evs, key=lambda e: to_dt(e.get("ts")) or datetime.min, reverse=True)]
    tables = [_table("Incidentes", ["Detectado", "Agente", "Identificador", "Status", "Resolvido", "Resumo"], rows_i, empty="Nenhum incidente registrado."),
              _table("Eventos de segurança", ["Data", "Agente", "Tipo", "Mensagem"], rows_e, empty="Nenhum evento de segurança registrado.")]
    findings = [{"tone": "bad", "text": f"{len(open_inc)} incidente(s) de segurança ainda em aberto."}] if open_inc else \
               [{"tone": "ok", "text": "Nenhum incidente de segurança em aberto."}]
    recs = ["Isolar o host afetado, validar os snapshots anteriores ao evento e restaurar de um ponto limpo."] if open_inc else []
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": recs}


def rep_access_audit(ctx: ReportContext) -> Dict[str, Any]:
    au = ctx.audit
    logins = [a for a in au if "login" in str(a.get("action") or "").lower()]
    fails = [a for a in logins if a.get("ok") is False]
    oks = [a for a in logins if a.get("ok") is not False]
    by_ip_fail = Counter(a.get("ip") or "—" for a in fails)
    by_user = defaultdict(lambda: {"ok": 0, "fail": 0, "last": None, "ips": set()})
    for a in logins:
        u = by_user[a.get("username") or "—"]
        u["ok" if a.get("ok") is not False else "fail"] += 1
        u["ips"].add(a.get("ip") or "—")
        d = to_dt(a.get("ts"))
        if d and (u["last"] is None or d > u["last"]):
            u["last"] = d
    kpis = [
        _kpi("Logins bem-sucedidos", fmt_int(len(oks))),
        _kpi("Tentativas com falha", fmt_int(len(fails)), "", "bad" if len(fails) >= 10 else "warn" if fails else "ok"),
        _kpi("Usuários distintos", fmt_int(len(by_user))),
        _kpi("IPs de origem", fmt_int(len({a.get("ip") for a in logins}))),
        _kpi("Ações registradas", fmt_int(len(au))),
    ]
    charts = [_chart("Acessos por dia", svg_bars(ctx.day_labels, [{"name": "Sucesso", "values": _daily_counts(ctx, oks, "ts"), "tone": "ok"},
                                                                   {"name": "Falha", "values": _daily_counts(ctx, fails, "ts"), "tone": "bad"}]))]
    rows_u = [[u, fmt_int(v["ok"]), cell(fmt_int(v["fail"]), "bad" if v["fail"] >= 5 else None), fmt_int(len(v["ips"])), fmt_dt(v["last"])]
              for u, v in sorted(by_user.items(), key=lambda kv: -(kv[1]["ok"] + kv[1]["fail"]))]
    rows_ip = [[ip, cell(fmt_int(n), "bad" if n >= 5 else "warn")] for ip, n in by_ip_fail.most_common(30)]
    rows_a = [[fmt_dt(a.get("ts")), a.get("username") or "—", a.get("action") or "—", a.get("ip") or "—",
               cell("OK" if a.get("ok") is not False else "Falha", "ok" if a.get("ok") is not False else "bad"), (a.get("details") or "")[:160]]
              for a in sorted(au, key=lambda a: to_dt(a.get("ts")) or datetime.min, reverse=True)]
    tables = [_table("Acessos por usuário", ["Usuário", "Logins", "Falhas", "IPs", "Último acesso"], rows_u),
              _table("IPs com tentativas de login malsucedidas", ["IP", "Falhas"], rows_ip, empty="Nenhuma falha de login."),
              _table("Trilha de auditoria", ["Data", "Usuário", "Ação", "IP", "Resultado", "Detalhes"], rows_a, max_rows=1500)]
    findings, recs = [], []
    sus = [ip for ip, n in by_ip_fail.items() if n >= 5]
    if sus:
        findings.append({"tone": "bad", "text": f"{len(sus)} IP(s) com 5 ou mais falhas de login: {', '.join(sus[:6])}."})
        recs.append("Bloquear os IPs suspeitos no firewall e revisar a política de senhas/2FA dos administradores.")
    if not au:
        findings.append({"tone": "warn", "text": "Nenhum registro de auditoria no período."})
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": recs}


def rep_tenant_billing(ctx: ReportContext) -> Dict[str, Any]:
    if ctx.info.get("product") != "server":
        return {"kpis": [], "charts": [], "tables": [], "findings": [{"tone": "neutral", "text": "Relatório disponível no GBOC Server (visão multi-cliente)."}], "recommendations": []}
    names = {t.get("tenant_id"): t for t in ctx.tenants}
    price_agent = ctx.setting("price_per_agent", 0.0)
    price_tb = ctx.setting("price_per_tb", 0.0)
    currency = ctx.setting("currency", "BRL")
    size_by_agent: Dict[Any, float] = defaultdict(float)
    for r in ctx.repos:
        size_by_agent[r.get("agent_id")] += to_float(r.get("size_bytes")) or 0
    data: Dict[Any, Dict[str, Any]] = {}
    for a in ctx.agents:
        tid = a.get("tenant_id") or "__none__"
        d = data.setdefault(tid, {"agents": 0, "online": 0, "tasks": 0, "size": 0.0, "read": 0.0, "added": 0.0, "ok": 0, "fail": 0})
        d["agents"] += 1
        d["online"] += 1 if ctx.agent_status(a) == "online" else 0
        d["size"] += size_by_agent.get(a["agent_id"], 0)
        d["tasks"] += sum(1 for t in ctx.active_tasks if t.get("agent_id") == a["agent_id"])
    tenant_of = {a["agent_id"]: (a.get("tenant_id") or "__none__") for a in ctx.agents}
    for r in ctx.runs:
        d = data.get(tenant_of.get(r.get("agent_id")))
        if not d:
            continue
        if r["status"] == "success":
            d["ok"] += 1
            d["read"] += r["bytes"] or 0
            d["added"] += r["bytes_added"] or 0
        elif r["status"] == "failed":
            d["fail"] += 1
    billed = price_agent > 0 or price_tb > 0
    rows, total_val = [], 0.0
    for tid, d in sorted(data.items(), key=lambda kv: -kv[1]["size"]):
        t = names.get(tid) or {}
        tb = d["size"] / 1024 ** 4
        val = d["agents"] * price_agent + tb * price_tb
        total_val += val
        rate = _rate(d["ok"], d["ok"] + d["fail"])
        rows.append([t.get("name") or ("Sem cliente atribuído" if tid == "__none__" else tid), t.get("plan") or "—",
                     f"{fmt_int(d['agents'])}" + (f"/{fmt_int(t.get('max_agents'))}" if t.get("max_agents") else ""),
                     fmt_int(d["online"]), fmt_int(d["tasks"]), fmt_bytes(d["size"]), fmt_bytes(d["read"]), fmt_bytes(d["added"]),
                     cell(fmt_pct(rate), _tone_rate(rate, ctx.success_goal)),
                     (f"{currency} {fmt_num(val, 2)}" if billed else "—")])
    kpis = [
        _kpi("Clientes", fmt_int(len([k for k in data if k != "__none__"]))),
        _kpi("Agentes faturáveis", fmt_int(sum(d["agents"] for d in data.values()))),
        _kpi("Armazenamento protegido", fmt_bytes(sum(d["size"] for d in data.values()))),
        _kpi("Valor estimado do período", f"{currency} {fmt_num(total_val, 2)}" if billed else "Preços não configurados",
             "agentes × preço + TB × preço" if billed else "Configurações > Relatórios"),
    ]
    order = sorted(data.items(), key=lambda kv: -kv[1]["size"])
    charts = [_chart("Armazenamento por cliente", svg_hbar([(names.get(k) or {}).get("name") or ("Sem cliente" if k == "__none__" else k) for k, _ in order],
                                                           [v["size"] for _, v in order], unit="bytes"))]
    tables = [_table("Consumo por cliente", ["Cliente", "Plano", "Agentes", "Online", "Tarefas", "Armazenado", "Lido no período",
                                             "Novos dados", "Sucesso", "Valor estimado"], rows,
                     note=("Preços: " + f"{currency} {fmt_num(price_agent, 2)} por agente, {currency} {fmt_num(price_tb, 2)} por TB armazenado.") if billed
                     else "Defina preço por agente e por TB em Configurações > Relatórios para calcular o faturamento.")]
    findings = []
    over = [r for r in rows if "/" in r[2] and int(r[2].split("/")[0].replace(".", "")) > int(r[2].split("/")[1].replace(".", ""))]
    if over:
        findings.append({"tone": "warn", "text": f"{len(over)} cliente(s) acima do limite de agentes do plano."})
    if "__none__" in data:
        findings.append({"tone": "warn", "text": f"{data['__none__']['agents']} agente(s) sem cliente atribuído (não entram no faturamento por cliente)."})
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": []}


def rep_cloud_cost(ctx: ReportContext) -> Dict[str, Any]:
    usd_tb = ctx.setting("cloud_storage_cost_usd_per_tb", 0.0)
    fx = ctx.setting("usd_brl_rate", 0.0)
    growth = {(x["repo"].get("agent_id"), x["repo"].get("repo_id")): x for x in _repo_growth(ctx)}
    cloud = [r for r in ctx.repos if (r.get("type") or "local").lower() not in ("local", "")]
    rows, tot_tb, tot_usd, tot_12 = [], 0.0, 0.0, 0.0
    for r in sorted(cloud, key=lambda r: -(to_float(r.get("size_bytes")) or 0)):
        size = to_float(r.get("size_bytes"))
        tb = (size or 0) / 1024 ** 4
        g = growth.get((r.get("agent_id"), r.get("repo_id")), {})
        slope = g.get("slope") or 0
        tb12 = ((size or 0) + max(0, slope) * 365) / 1024 ** 4
        usd = tb * usd_tb
        tot_tb += tb
        tot_usd += usd
        tot_12 += tb12 * usd_tb
        rows.append([ctx.host(r.get("agent_id")), r.get("name"), r.get("provider") or r.get("type"), r.get("target") or "—",
                     fmt_bytes(size), (fmt_bytes(slope * 30) + "/mês") if slope else "—",
                     f"US$ {fmt_num(usd, 2)}" if usd_tb else "—", f"R$ {fmt_num(usd * fx, 2)}" if (usd_tb and fx) else "—",
                     f"US$ {fmt_num(tb12 * usd_tb, 2)}" if usd_tb else "—"])
    kpis = [
        _kpi("Repositórios em nuvem", fmt_int(len(cloud)), f"{fmt_int(len(ctx.repos) - len(cloud))} locais"),
        _kpi("Armazenado em nuvem", fmt_bytes(tot_tb * 1024 ** 4)),
        _kpi("Custo mensal estimado", f"US$ {fmt_num(tot_usd, 2)}" if usd_tb else "Tarifa não configurada",
             f"≈ R$ {fmt_num(tot_usd * fx, 2)}" if (usd_tb and fx) else ""),
        _kpi("Custo mensal em 12 meses", f"US$ {fmt_num(tot_12, 2)}" if usd_tb else "—", "mantida a tendência de crescimento"),
    ]
    charts = [_chart("Armazenamento em nuvem por repositório", svg_hbar([f'{ctx.host(r.get("agent_id"))} · {r.get("name")}' for r in cloud],
                                                                       [to_float(r.get("size_bytes")) for r in cloud], unit="bytes"))] if cloud else []
    tables = [_table("Custo por repositório em nuvem", ["Agente", "Repositório", "Provedor", "Bucket/destino", "Tamanho", "Crescimento",
                                                        "Custo/mês (USD)", "Custo/mês (BRL)", "Custo/mês em 12 meses"], rows,
                     note=(f"Tarifa: US$ {fmt_num(usd_tb, 2)}/TB/mês" + (f"; câmbio R$ {fmt_num(fx, 2)}" if fx else "") + ". Não inclui egress/requisições.")
                     if usd_tb else "Configure a tarifa US$/TB em Configurações > Relatórios.",
                     empty="Nenhum repositório em nuvem cadastrado.")]
    findings = [] if cloud else [{"tone": "warn", "text": "Nenhum repositório em nuvem: os backups não possuem cópia externa em nuvem."}]
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": []}


def rep_resources(ctx: ReportContext) -> Dict[str, Any]:
    ms = ctx.metrics
    by_agent: Dict[Any, Dict[str, List[float]]] = defaultdict(lambda: {"cpu": [], "ram": [], "disk": []})
    by_day: Dict[date, Dict[str, List[float]]] = defaultdict(lambda: {"cpu": [], "ram": [], "disk": []})
    for m in ms:
        d = to_dt(m.get("ts"))
        for k in ("cpu", "ram", "disk"):
            v = to_float(m.get(k))
            if v is not None:
                by_agent[m.get("agent_id")][k].append(v)
                if d:
                    by_day[d.date()][k].append(v)
    rows = []
    for aid, v in sorted(by_agent.items(), key=lambda kv: -(max(kv[1]["disk"]) if kv[1]["disk"] else 0)):
        def st(k):
            return (statistics.mean(v[k]) if v[k] else None, max(v[k]) if v[k] else None, percentile(v[k], 0.95))
        c, r, d = st("cpu"), st("ram"), st("disk")
        rows.append([ctx.host(aid), fmt_pct(c[0]), cell(fmt_pct(c[2]), "warn" if c[2] and c[2] > 85 else None),
                     fmt_pct(r[0]), cell(fmt_pct(r[2]), "warn" if r[2] and r[2] > 90 else None),
                     cell(fmt_pct(d[1]), "bad" if d[1] and d[1] >= 90 else "warn" if d[1] and d[1] >= 80 else None),
                     fmt_int(len(v["cpu"]))])
    labels = ctx.day_labels
    cpu = [statistics.mean(by_day[d]["cpu"]) if by_day[d]["cpu"] else None for d in ctx.day_list]
    ram = [statistics.mean(by_day[d]["ram"]) if by_day[d]["ram"] else None for d in ctx.day_list]
    disk = [statistics.mean(by_day[d]["disk"]) if by_day[d]["disk"] else None for d in ctx.day_list]
    hot = [r[0] for r in rows if isinstance(r[5], dict) and r[5].get("tone") == "bad"]
    kpis = [
        _kpi("Agentes com métricas", fmt_int(len(by_agent))),
        _kpi("CPU média da frota", fmt_pct(statistics.mean([x for x in cpu if x is not None]) if any(x is not None for x in cpu) else None)),
        _kpi("RAM média da frota", fmt_pct(statistics.mean([x for x in ram if x is not None]) if any(x is not None for x in ram) else None)),
        _kpi("Hosts com disco ≥ 90%", fmt_int(len(hot)), "", "bad" if hot else "ok"),
    ]
    charts = [_chart("Utilização média da frota por dia", svg_line(labels, [{"name": "CPU", "values": cpu}, {"name": "RAM", "values": ram},
                                                                          {"name": "Disco do sistema", "values": disk}], unit="%", y_max=100),
                     {"labels": labels, "cpu": cpu, "ram": ram, "disk": disk})]
    tables = [_table("Utilização por agente", ["Agente", "CPU média", "CPU P95", "RAM média", "RAM P95", "Disco (máx.)", "Amostras"], rows,
                     empty="Sem métricas no período (enviadas pelo heartbeat dos agentes).")]
    findings = [{"tone": "bad", "text": f"Disco do sistema acima de 90% em: {', '.join(hot[:8])}."}] if hot else []
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings,
            "recommendations": ["Liberar espaço nos hosts com disco crítico; pouco espaço impede snapshots VSS e logs."] if hot else []}


def rep_backup_window(ctx: ReportContext) -> Dict[str, Any]:
    runs = [r for r in ctx.runs if r["status"] in ("success", "failed")]
    matrix = [[0.0] * 24 for _ in range(7)]
    by_hour = defaultdict(lambda: {"n": 0, "fail": 0, "bytes": 0.0, "dur": []})
    for r in runs:
        s = r["started_at"]
        matrix[s.weekday()][s.hour] += 1
        h = by_hour[s.hour]
        h["n"] += 1
        h["fail"] += 1 if r["status"] == "failed" else 0
        h["bytes"] += r["bytes"] or 0
        if r["duration_s"] is not None:
            h["dur"].append(r["duration_s"])
    # concorrência máxima (intervalos sobrepostos)
    evs = []
    for r in runs:
        end = r["completed_at"] or (r["started_at"] + timedelta(seconds=r["duration_s"] or 0))
        evs.append((r["started_at"], 1))
        evs.append((max(end, r["started_at"]), -1))
    evs.sort(key=lambda e: (e[0], e[1]))
    cur = peak = 0
    peak_at = None
    for t, dlt in evs:
        cur += dlt
        if cur > peak:
            peak, peak_at = cur, t
    business = sum(1 for r in runs if r["started_at"].weekday() < 5 and 8 <= r["started_at"].hour < 18)
    busiest = max(by_hour.items(), key=lambda kv: kv[1]["n"])[0] if by_hour else None
    kpis = [
        _kpi("Pico de concorrência", fmt_int(peak), f"em {fmt_dt(peak_at)}" if peak_at else ""),
        _kpi("Hora mais carregada", f"{busiest:02d}h" if busiest is not None else "—"),
        _kpi("Em horário comercial", fmt_pct(_rate(business, len(runs))), "seg–sex 08h–18h", "warn" if runs and business / len(runs) > 0.3 else "ok"),
        _kpi("Execuções analisadas", fmt_int(len(runs))),
    ]
    charts = [_chart("Início das execuções por dia da semana e hora", svg_heatmap(WEEKDAYS_PT, [f"{h:02d}" for h in range(24)], matrix),
                     {"matrix": matrix})]
    rows = [[f"{h:02d}:00–{h:02d}:59", fmt_int(v["n"]), cell(fmt_pct(_rate(v["fail"], v["n"])), "bad" if v["fail"] and v["fail"] / v["n"] > 0.2 else None),
             fmt_bytes(v["bytes"]), fmt_duration(percentile(v["dur"], 0.5))] for h, v in sorted(by_hour.items())]
    tables = [_table("Carga por faixa horária", ["Faixa", "Execuções", "Taxa de falha", "Volume lido", "Duração mediana"], rows)]
    findings = []
    if runs and business / len(runs) > 0.3:
        findings.append({"tone": "warn", "text": f"{fmt_pct(business / len(runs) * 100)} das execuções começam em horário comercial e podem afetar usuários."})
    bad_hours = [h for h, v in by_hour.items() if v["n"] >= 5 and v["fail"] / v["n"] > 0.2]
    if bad_hours:
        findings.append({"tone": "warn", "text": "Faixas com taxa de falha acima de 20%: " + ", ".join(f"{h:02d}h" for h in sorted(bad_hours)) + "."})
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings,
            "recommendations": ["Redistribuir os agendamentos para fora do horário comercial e das faixas com mais falhas."] if findings else []}


def rep_events_logs(ctx: ReportContext) -> Dict[str, Any]:
    evs = ctx.events
    errs = ctx.log_errors
    daily = ctx.log_errors_daily or []
    sev = Counter(e.get("severity") or "info" for e in evs)
    types = Counter(e.get("type") or "evento" for e in evs)
    err_total = sum(int(e.get("count") or 0) for e in errs)
    by_agent = Counter()
    for e in errs:
        by_agent[e.get("agent_id")] += int(e.get("count") or 0)
    kpis = [
        _kpi("Eventos do sistema", fmt_int(len(evs))),
        _kpi("Eventos críticos/erro", fmt_int(sev.get("critical", 0) + sev.get("error", 0)), "", "bad" if (sev.get("critical") or sev.get("error")) else "ok"),
        _kpi("Erros nos logs dos agentes", fmt_int(err_total)),
        _kpi("Agentes com erros em log", fmt_int(len(by_agent))),
    ]
    idx = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(ctx.day_list)}
    err_series = [0.0] * len(idx)
    for d in daily:
        k = str(d.get("day"))[:10]
        if k in idx:
            err_series[idx[k]] = float(d.get("count") or 0)
    charts = [_chart("Erros e avisos nos logs por dia", svg_bars(ctx.day_labels, [{"name": "Erros", "values": err_series, "tone": "bad"}])),
              _chart("Eventos por tipo", svg_hbar(list(types.keys()), list(types.values()))) if types else None]
    charts = [c for c in charts if c]
    rows_src = [[ctx.host(e.get("agent_id")), e.get("source") or "—", e.get("level") or "—", fmt_int(e.get("count")), fmt_dt(e.get("last")),
                 (e.get("sample") or "")[:200]] for e in sorted(errs, key=lambda e: -int(e.get("count") or 0))[:100]]
    rows_ev = [[fmt_dt(e.get("ts")), ctx.host(e.get("agent_id")) if e.get("agent_id") else (e.get("agent") or "—"), e.get("type") or "—",
                cell(e.get("severity") or "info", {"critical": "bad", "error": "bad", "warning": "warn"}.get(str(e.get("severity")).lower())),
                (e.get("message") or "")[:220]] for e in sorted(evs, key=lambda e: to_dt(e.get("ts")) or datetime.min, reverse=True)]
    tables = [_table("Origens de erro mais frequentes nos logs", ["Agente", "Origem", "Nível", "Ocorrências", "Última", "Exemplo"], rows_src,
                     empty="Nenhum erro nos logs sincronizados no período."),
              _table("Eventos e alertas", ["Data", "Agente", "Tipo", "Severidade", "Mensagem"], rows_ev, max_rows=1000)]
    findings = []
    if by_agent:
        top_a, n = by_agent.most_common(1)[0]
        findings.append({"tone": "warn", "text": f"{ctx.host(top_a)} concentra {fmt_pct(n / err_total * 100)} dos erros de log ({fmt_int(n)})."})
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": []}


def rep_task_scorecard(ctx: ReportContext) -> Dict[str, Any]:
    rpo = {ctx.task_key(x["task"]): x for x in _task_rpo_rows(ctx)}
    rows, scored = [], []
    for t in ctx.active_tasks:
        k = ctx.task_key(t)
        rs = [r for r in ctx.runs_by_task.get(k, []) if r["status"] in ("success", "failed")]
        ok = [r for r in rs if r["status"] == "success"]
        rate = _rate(len(ok), len(rs))
        x = rpo.get(k, {})
        dd = [r["duration_s"] for r in ok if r["duration_s"]]
        cv = (statistics.pstdev(dd) / statistics.mean(dd)) if len(dd) >= 3 and statistics.mean(dd) > 0 else 0
        streak = x.get("streak", 0)
        s_rate = (rate or 0) / 100
        s_rpo = {"ok": 1.0, "warn": 0.7}.get(x.get("tone"), 0.0)
        s_stab = max(0.0, 1 - min(1.0, cv) * 0.5 - min(streak, 5) * 0.1)
        score = round((s_rate * 0.5 + s_rpo * 0.3 + s_stab * 0.2) * 100) if rs else 0
        grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 65 else "D" if score >= 50 else "E"
        tone = {"A": "ok", "B": "ok", "C": "warn", "D": "serious", "E": "bad"}[grade]
        scored.append((f"{ctx.host(t.get('agent_id'))} · {t.get('name')}", score, tone))
        rows.append((score, [ctx.host(t.get("agent_id")), t.get("name"), t.get("engine") or "—", t.get("repository_name") or "—",
                             fmt_int(len(rs)), cell(fmt_pct(rate), _tone_rate(rate, ctx.success_goal)),
                             cell(x.get("status", "—"), x.get("tone")), fmt_int(streak), fmt_pct(cv * 100, 0) if dd else "—",
                             cell(f"{score} ({grade})", tone)]))
    rows.sort(key=lambda r: r[0])
    grades = Counter(cell_text(r[1][9]).split("(")[-1].rstrip(")") for r in rows)
    kpis = [
        _kpi("Tarefas avaliadas", fmt_int(len(rows))),
        _kpi("Pontuação média", f"{statistics.mean([r[0] for r in rows]):.0f}/100" if rows else "—"),
        _kpi("Notas A/B", fmt_int(grades.get("A", 0) + grades.get("B", 0)), "", "ok"),
        _kpi("Notas D/E", fmt_int(grades.get("D", 0) + grades.get("E", 0)), "exigem ação", "bad" if grades.get("D") or grades.get("E") else "ok"),
    ]
    order = sorted(scored, key=lambda x: x[1])[:20]
    charts = [_chart("Tarefas com menor pontuação", svg_hbar([n for n, _, _ in order], [s for _, s, _ in order], tones=[t for _, _, t in order]))]
    tables = [_table("Scorecard de qualidade por tarefa", ["Agente", "Tarefa", "Motor", "Repositório", "Execuções", "Sucesso", "RPO",
                                                           "Falhas seguidas", "Variação de duração", "Pontuação"], [r for _, r in rows],
                     note="Pontuação = 50% taxa de sucesso + 30% conformidade de RPO + 20% estabilidade (variação de duração e falhas seguidas).")]
    findings = [{"tone": "bad", "text": f"{grades.get('D', 0) + grades.get('E', 0)} tarefa(s) com nota D ou E."}] if (grades.get("D") or grades.get("E")) else []
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings, "recommendations": []}


def rep_anomalies(ctx: ReportContext) -> Dict[str, Any]:
    found = []
    for k, rs in ctx.runs_by_task.items():
        ok = [r for r in rs if r["status"] == "success"]
        if len(ok) < 4:
            continue
        for metric, label, unit in (("bytes_added", "Dados novos", "bytes"), ("bytes", "Dados lidos", "bytes"), ("duration_s", "Duração", "s")):
            vals = [r[metric] for r in ok if r.get(metric) is not None]
            if len(vals) < 4:
                continue
            for i, r in enumerate(ok):
                v = r.get(metric)
                if v is None:
                    continue
                base = [x[metric] for x in ok[max(0, i - 10):i] if x.get(metric) is not None]
                if len(base) < 3:
                    continue
                med = statistics.median(base)
                floor = 50 * 1024 ** 2 if unit == "bytes" else 60
                if med >= floor and v > med * 3:
                    found.append((r, label, "aumento", v, med, v / med, unit))
                elif med >= floor and v < med * 0.1:
                    found.append((r, label, "queda", v, med, v / med if med else 0, unit))
            if metric == "bytes_added":
                break  # se há dados novos, não repete a análise em "lidos"
    found.sort(key=lambda x: x[0]["started_at"], reverse=True)
    expl = {("Dados novos", "aumento"): "Alteração em massa de arquivos (possível criptografia por ransomware) ou entrada de novos dados.",
            ("Dados lidos", "aumento"): "Origem cresceu ou exclusões deixaram de ser aplicadas.",
            ("Duração", "aumento"): "Lentidão no destino/rede ou crescimento da origem.",
            ("Dados novos", "queda"): "Possível origem vazia/inacessível ou exclusão indevida.",
            ("Dados lidos", "queda"): "Possível pasta removida ou caminho de origem alterado.",
            ("Duração", "queda"): "Execução interrompida cedo ou origem vazia."}
    rows = [[fmt_dt(r["started_at"]), ctx.host(r.get("agent_id")), r["task_label"], label,
             cell(kind.capitalize(), "bad" if kind == "aumento" and label == "Dados novos" else "warn"),
             _fmt_val(v, unit), _fmt_val(med, unit), f"{fmt_num(ratio, 1)}×", expl.get((label, kind), "")]
            for r, label, kind, v, med, ratio, unit in found]
    kpis = [
        _kpi("Anomalias detectadas", fmt_int(len(found)), "", "warn" if found else "ok"),
        _kpi("Picos de dados novos", fmt_int(sum(1 for f in found if f[1] == "Dados novos" and f[2] == "aumento")), "≥ 3× a mediana recente",
             "bad" if any(f[1] == "Dados novos" and f[2] == "aumento" for f in found) else "ok"),
        _kpi("Quedas bruscas", fmt_int(sum(1 for f in found if f[2] == "queda")), "≤ 10% da mediana recente"),
        _kpi("Tarefas analisadas", fmt_int(sum(1 for rs in ctx.runs_by_task.values() if sum(1 for r in rs if r['status'] == 'success') >= 4))),
    ]
    charts = [_chart("Anomalias por dia", svg_bars(ctx.day_labels, [{"name": "Aumentos", "values": _daily_counts(ctx, [f[0] for f in found if f[2] == "aumento"]), "tone": "serious"},
                                                                    {"name": "Quedas", "values": _daily_counts(ctx, [f[0] for f in found if f[2] == "queda"]), "tone": "warn"}]))]
    tables = [_table("Execuções fora do padrão da própria tarefa", ["Data", "Agente", "Tarefa", "Métrica", "Tipo", "Valor", "Mediana recente",
                                                                     "Variação", "Possível causa"], rows,
                     empty="Nenhuma execução fora do padrão (são necessárias ao menos 4 execuções com sucesso por tarefa).",
                     note="Comparação com a mediana das 10 execuções bem-sucedidas anteriores da mesma tarefa.")]
    findings = []
    spikes = [f for f in found if f[1] == "Dados novos" and f[2] == "aumento"]
    if spikes:
        findings.append({"tone": "bad", "text": f"{len(spikes)} pico(s) de dados novos: confirme com o responsável se houve carga legítima; caso contrário, investigue ransomware."})
    return {"kpis": kpis, "charts": charts, "tables": tables, "findings": findings,
            "recommendations": ["Para picos não explicados: comparar snapshots, verificar extensões de arquivo alteradas e eventos do Ransomware Shield (REP-11)."] if spikes else []}


def rep_retention(ctx: ReportContext) -> Dict[str, Any]:
    tasks = ctx.active_tasks
    no_ret = [t for t in tasks if not t.get("retention")]
    snaps_hist: Dict[Tuple[Any, Any], List[Tuple[datetime, float]]] = defaultdict(list)
    for h in ctx.repo_history:
        d, v = to_dt(h.get("recorded_at")), to_float(h.get("snapshot_count"))
        if d and v is not None:
            snaps_hist[(h.get("agent_id"), h.get("repo_id"))].append((d, v))
    rows_r = []
    for rp in ctx.repos:
        pts = sorted(snaps_hist.get((rp.get("agent_id"), rp.get("repo_id")), []))
        slope = linear_slope_per_day(pts)
        first = pts[0][1] if pts else None
        rows_r.append([ctx.host(rp.get("agent_id")), rp.get("name"), rp.get("engine") or "—",
                       fmt_int(rp.get("snapshot_count")) if rp.get("snapshot_count") is not None else "—",
                       fmt_int(first) if first is not None else "—",
                       cell((f"+{fmt_num(slope * 30, 0)}/mês" if slope and slope > 0 else (f"{fmt_num(slope * 30, 0)}/mês" if slope else "estável")),
                            "warn" if slope and slope * 30 > 60 else None), fmt_bytes(rp.get("size_bytes"))])
    rows_t = [[ctx.host(t.get("agent_id")), t.get("name"), t.get("repository_name") or "—",
               cell(t.get("retention") or "Sem política", None if t.get("retention") else "warn"), cron_human(t.get("schedule_cron"), t.get("schedule_enabled"))]
              for t in sorted(tasks, key=lambda t: (bool(t.get("retention")), ctx.host(t.get("agent_id"))))]
    kpis = [
        _kpi("Tarefas ativas", fmt_int(len(tasks))),
        _kpi("Sem política de retenção", fmt_int(len(no_ret)), "crescimento ilimitado", "warn" if no_ret else "ok"),
        _kpi("Snapshots armazenados", fmt_int(sum(int(to_float(r.get("snapshot_count")) or 0) for r in ctx.repos))),
        _kpi("Repositórios", fmt_int(len(ctx.repos))),
    ]
    tables = [_table("Política de retenção por tarefa", ["Agente", "Tarefa", "Repositório", "Retenção (d/s/m/a)", "Agendamento"], rows_t),
              _table("Snapshots por repositório", ["Agente", "Repositório", "Motor", "Snapshots atuais", "No início do período", "Tendência", "Tamanho"], rows_r)]
    findings = [{"tone": "warn", "text": f"{len(no_ret)} tarefa(s) sem política de retenção: os snapshots se acumulam indefinidamente."}] if no_ret else []
    return {"kpis": kpis, "charts": [], "tables": tables, "findings": findings,
            "recommendations": ["Definir retenção (ex.: 7 diários, 4 semanais, 12 mensais) nas tarefas sem política."] if no_ret else []}


# ───────────────────────────── Catálogo ─────────────────────────────

CATALOG: List[Dict[str, Any]] = [
    {"id": 1, "code": "REP-01", "name": "Resumo Operacional de Backups", "category": "Operação", "builder": rep_operational_summary,
     "description": "Taxa de sucesso, execuções por dia, volume protegido e situação de cada agente no período.", "audience": "Gestor de TI"},
    {"id": 2, "code": "REP-02", "name": "Conformidade de RPO (SLA)", "category": "SLA", "builder": rep_rpo_compliance,
     "description": "Idade do último backup válido por tarefa, violações de RPO e conformidade diária.", "audience": "Gestor / Cliente"},
    {"id": 3, "code": "REP-03", "name": "Histórico Detalhado de Execuções", "category": "Operação", "builder": rep_execution_history,
     "description": "Todas as execuções com duração, volume lido, dados novos, velocidade e erro.", "audience": "Operação"},
    {"id": 4, "code": "REP-04", "name": "Falhas e Análise de Causa Raiz", "category": "Operação", "builder": rep_failures_rca,
     "description": "Falhas agrupadas por causa e por mensagem, tempo médio de recuperação e fila de retentativas.", "audience": "Operação"},
    {"id": 5, "code": "REP-05", "name": "Cobertura e Lacunas de Proteção", "category": "Risco", "builder": rep_coverage_gaps,
     "description": "Agentes sem tarefa, offline, tarefas sem agendamento/sucesso e volumes sem backup.", "audience": "Gestor de TI"},
    {"id": 6, "code": "REP-06", "name": "Capacidade e Previsão de Armazenamento", "category": "Capacidade", "builder": rep_capacity_forecast,
     "description": "Ocupação dos repositórios, crescimento, dias até esgotar e volumes críticos dos hosts.", "audience": "Infraestrutura"},
    {"id": 7, "code": "REP-07", "name": "Volume Transferido e Desempenho", "category": "Desempenho", "builder": rep_throughput,
     "description": "Dados lidos e novos por dia, taxa de mudança, velocidade e duração por tarefa.", "audience": "Infraestrutura"},
    {"id": 8, "code": "REP-08", "name": "Inventário da Frota de Agentes", "category": "Inventário", "builder": rep_fleet_inventory,
     "description": "Agentes, versões, sistemas, recursos, tarefas e repositórios de cada host.", "audience": "Operação"},
    {"id": 9, "code": "REP-09", "name": "Restaurações e Testes de Recuperação", "category": "Recuperação", "builder": rep_restores_tests,
     "description": "Restaurações realizadas, RTO observado, verificações de integridade e SureBackup.", "audience": "Auditoria / Cliente"},
    {"id": 10, "code": "REP-10", "name": "Prontidão para Recuperação de Desastres", "category": "Risco", "builder": rep_dr_readiness,
     "description": "Pontuação por agente: backup recente, RPO, cópia externa (3-2-1), testes e pendências.", "audience": "Diretoria / Cliente"},
    {"id": 11, "code": "REP-11", "name": "Segurança e Ransomware", "category": "Segurança", "builder": rep_security,
     "description": "Incidentes, tempo de resposta e eventos do Ransomware Shield por agente.", "audience": "Segurança"},
    {"id": 12, "code": "REP-12", "name": "Auditoria de Acessos", "category": "Segurança", "builder": rep_access_audit,
     "description": "Logins, falhas por usuário e IP e trilha de ações administrativas.", "audience": "Auditoria"},
    {"id": 13, "code": "REP-13", "name": "Consumo por Cliente e Faturamento", "category": "Comercial", "builder": rep_tenant_billing,
     "description": "Agentes, armazenamento e volume por cliente (MSP), com valor estimado pelos preços configurados.", "audience": "Comercial / MSP",
     "products": ["server"]},
    {"id": 14, "code": "REP-14", "name": "Custo de Armazenamento em Nuvem", "category": "Comercial", "builder": rep_cloud_cost,
     "description": "Tamanho real dos repositórios em nuvem e custo mensal atual e projetado.", "audience": "Financeiro"},
    {"id": 15, "code": "REP-15", "name": "Utilização de Recursos dos Agentes", "category": "Desempenho", "builder": rep_resources,
     "description": "CPU, memória e disco dos hosts (média, P95 e máximo).", "audience": "Infraestrutura"},
    {"id": 16, "code": "REP-16", "name": "Janela de Backup e Concorrência", "category": "Desempenho", "builder": rep_backup_window,
     "description": "Mapa de calor dia × hora, pico de execuções simultâneas e carga em horário comercial.", "audience": "Infraestrutura"},
    {"id": 17, "code": "REP-17", "name": "Eventos, Alertas e Erros de Log", "category": "Operação", "builder": rep_events_logs,
     "description": "Eventos do sistema e principais origens de erro nos logs dos agentes.", "audience": "Operação"},
    {"id": 18, "code": "REP-18", "name": "Scorecard de Qualidade por Tarefa", "category": "SLA", "builder": rep_task_scorecard,
     "description": "Nota A–E por tarefa combinando sucesso, RPO e estabilidade.", "audience": "Gestor de TI"},
    {"id": 19, "code": "REP-19", "name": "Anomalias de Volume e Duração", "category": "Segurança", "builder": rep_anomalies,
     "description": "Execuções muito acima ou abaixo do padrão da tarefa (possível ransomware ou origem perdida).", "audience": "Segurança"},
    {"id": 20, "code": "REP-20", "name": "Retenção e Snapshots", "category": "Capacidade", "builder": rep_retention,
     "description": "Política de retenção por tarefa e evolução da quantidade de snapshots.", "audience": "Infraestrutura"},
]

_BY_ID = {c["id"]: c for c in CATALOG}
_BY_CODE = {c["code"].upper(): c for c in CATALOG}


def catalog(product: str = "server") -> List[Dict[str, Any]]:
    return [{k: v for k, v in c.items() if k != "builder"} for c in CATALOG if product in c.get("products", ["server", "agent"])]


def find_report(ref: Any) -> Optional[Dict[str, Any]]:
    if ref is None:
        return None
    s = str(ref).strip().upper()
    if s.isdigit():
        return _BY_ID.get(int(s))
    if s.startswith("REP") and not s.startswith("REP-"):
        s = "REP-" + s[3:].lstrip("-_")
    return _BY_CODE.get(s)


def build_report(source: Any, ref: Any, days: int = 30, agent_ids: Optional[List[str]] = None,
                 tenant_id: Optional[str] = None) -> Dict[str, Any]:
    spec = find_report(ref)
    if not spec:
        raise KeyError(f"Relatório '{ref}' não encontrado")
    ctx = ReportContext(source, days=days, agent_ids=agent_ids, tenant_id=tenant_id)
    body = spec["builder"](ctx)
    scope = "Todos os agentes"
    if ctx.agent_ids and ctx.agent_ids != ["__none__"]:
        scope = ", ".join(ctx.host(a) for a in ctx.agent_ids[:6]) + ("…" if len(ctx.agent_ids) > 6 else "")
    if tenant_id:
        tn = next((t.get("name") for t in ctx.tenants if t.get("tenant_id") == tenant_id), tenant_id)
        scope = f"Cliente {tn}" + ("" if scope == "Todos os agentes" else f" · {scope}")
    if ctx.info.get("product") == "agent":
        scope = f"Agente {ctx.info.get('hostname') or ''}".strip()
    notes = _coverage_notes(ctx) + list(body.get("notes") or [])
    rep = {
        "id": spec["id"], "code": spec["code"], "title": spec["name"], "category": spec["category"],
        "description": spec["description"], "audience": spec.get("audience"),
        "period": {"start": ctx.start.isoformat(), "end": ctx.end.isoformat(), "days": ctx.days},
        "scope": scope, "product": ctx.info.get("product"), "organization": ctx.info.get("organization") or "",
        "generated_at": datetime.now().isoformat(timespec="seconds"), "engine_version": REPORT_ENGINE_VERSION,
        "platform": ctx.info.get("platform") or "GBOC",
        "kpis": body.get("kpis", []), "charts": body.get("charts", []), "tables": body.get("tables", []),
        "findings": body.get("findings", []), "recommendations": body.get("recommendations", []), "notes": notes,
    }
    raw = f"{rep['code']}|{rep['generated_at']}|{rep['scope']}|{sum(len(t['rows']) for t in rep['tables'])}"
    h = hashlib.sha256(raw.encode()).hexdigest().upper()
    rep["integrity"] = f"{h[:8]}-{h[8:16]}-{h[16:24]}-{h[24:32]}"
    return rep


def report_json(rep: Dict[str, Any], include_svg: bool = False) -> Dict[str, Any]:
    out = dict(rep)
    out["charts"] = [{k: v for k, v in c.items() if include_svg or k != "svg"} for c in rep.get("charts", [])]
    out["tables"] = [{**{k: v for k, v in t.items() if k not in ("all_rows",)},
                      "rows": [[cell_text(c) for c in r] for r in (t.get("all_rows") or t["rows"])]} for t in rep.get("tables", [])]
    return out


def legacy_payload(rep: Dict[str, Any]) -> Dict[str, Any]:
    """Formato antigo de /generate (title, metrics, table_headers/rows, ai_executive_recommendation)."""
    t0 = rep["tables"][0] if rep.get("tables") else {"columns": [], "rows": []}
    rec = " ".join(f["text"] for f in rep.get("findings", [])[:4])
    if rep.get("recommendations"):
        rec += " Recomendações: " + " ".join(rep["recommendations"][:3])
    return {
        "status": "success", "report_id": rep["id"], "code": rep["code"], "title": rep["title"], "category": rep["category"],
        "description": rep["description"], "generated_at": rep["generated_at"], "period": rep["period"], "scope": rep["scope"],
        "metrics": [{"label": k["label"], "value": k["value"], "sub": k.get("sub"), "tone": k.get("tone")} for k in rep.get("kpis", [])],
        "table_headers": t0["columns"], "table_rows": [[cell_text(c) for c in r] for r in t0["rows"][:200]],
        "findings": rep.get("findings", []), "recommendations": rep.get("recommendations", []), "notes": rep.get("notes", []),
        "ai_executive_recommendation": esc(rec or "Sem observações relevantes no período."),
        "data_source": "Dados reais sincronizados (sem estimativas)", "engine_version": rep.get("engine_version"),
    }


def render_csv(rep: Dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([f"{rep['platform']} — {rep['code']} {rep['title']}"])
    w.writerow(["Período", f"{fmt_dt(rep['period']['start'])} a {fmt_dt(rep['period']['end'])}", "Escopo", rep["scope"]])
    w.writerow(["Gerado em", fmt_dt(rep["generated_at"]), "Código de integridade", rep.get("integrity")])
    w.writerow([])
    w.writerow(["Indicador", "Valor", "Detalhe"])
    for k in rep.get("kpis", []):
        w.writerow([k["label"], k["value"], k.get("sub", "")])
    for f in rep.get("findings", []):
        w.writerow(["Constatação", f["text"]])
    for r in rep.get("recommendations", []):
        w.writerow(["Recomendação", r])
    for t in rep.get("tables", []):
        w.writerow([])
        w.writerow([t["title"]])
        w.writerow(t["columns"])
        for row in (t.get("all_rows") or t["rows"]):
            w.writerow([cell_text(c) for c in row])
    for n in rep.get("notes", []):
        w.writerow(["Observação", n])
    return buf.getvalue()


_TONE_CSS = {"ok": "#0a7a0a", "warn": "#9a6400", "serious": "#b4521f", "bad": "#b42323", "neutral": "#5f5e5a"}
_TONE_BG = {"ok": "#e8f6e8", "warn": "#fff4d6", "serious": "#fde9df", "bad": "#fbe5e5", "neutral": "#f0efec"}
_TONE_ICON = {"ok": "✔", "warn": "▲", "serious": "▲", "bad": "✖", "neutral": "•"}


def _cell_html(c: Any) -> str:
    if isinstance(c, dict):
        tone = c.get("tone")
        if tone:
            return (f'<span class="pill" style="color:{_TONE_CSS.get(tone, INK)};background:{_TONE_BG.get(tone, "#f0efec")}">'
                    f'{esc(c.get("v"))}</span>')
        return esc(c.get("v"))
    return esc(c)


def render_html(rep: Dict[str, Any], embedded: bool = False) -> str:
    kpis = "".join(
        f'<div class="kpi" style="border-top-color:{_TONE_CSS.get(k.get("tone"), "#2a78d6") if k.get("tone") not in (None, "neutral") else "#2a78d6"}">'
        f'<div class="kl">{esc(k["label"])}</div><div class="kv">{esc(k["value"])}</div>'
        f'<div class="ks">{(_TONE_ICON.get(k.get("tone"), "") + " ") if (k.get("tone") not in (None, "neutral") and k.get("sub")) else ""}{esc(k.get("sub", ""))}</div></div>'
        for k in rep.get("kpis", []))
    findings = "".join(
        f'<li style="border-left-color:{_TONE_CSS.get(f["tone"], INK2)};background:{_TONE_BG.get(f["tone"], "#f6f6f3")}">'
        f'<b style="color:{_TONE_CSS.get(f["tone"], INK2)}">{_TONE_ICON.get(f["tone"], "•")}</b> {esc(f["text"])}</li>'
        for f in rep.get("findings", []))
    recs = "".join(f"<li>{esc(r)}</li>" for r in rep.get("recommendations", []))
    charts = "".join(f'<figure class="{"wide" if c.get("wide", True) else "half"}"><figcaption>{esc(c["title"])}</figcaption>{c["svg"]}</figure>'
                     for c in rep.get("charts", []) if c and c.get("svg"))
    tables = []
    for t in rep.get("tables", []):
        head = "".join(f"<th>{esc(c)}</th>" for c in t["columns"])
        if t["rows"]:
            body = "".join("<tr>" + "".join(f"<td>{_cell_html(c)}</td>" for c in r) + "</tr>" for r in t["rows"])
        else:
            body = f'<tr><td colspan="{len(t["columns"])}" class="empty">{esc(t.get("empty"))}</td></tr>'
        note = f'<p class="note">{esc(t["note"])}</p>' if t.get("note") else ""
        tables.append(f'<section class="tbl"><h3>{esc(t["title"])}</h3><div class="tw"><table><thead><tr>{head}</tr></thead>'
                      f'<tbody>{body}</tbody></table></div>{note}</section>')
    notes = "".join(f"<li>{esc(n)}</li>" for n in rep.get("notes", []))
    period = f"{fmt_dt(rep['period']['start'])} a {fmt_dt(rep['period']['end'])} ({rep['period']['days']} dias)"
    org = esc(rep.get("organization") or "")
    toolbar = "" if embedded else (
        '<div class="toolbar no-print"><button onclick="window.print()">Imprimir / Salvar PDF</button></div>')
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(rep['code'])} — {esc(rep['title'])}</title>
<style>
@page {{ size: A4; margin: 14mm 12mm 16mm; @bottom-right {{ content: "Página " counter(page) " de " counter(pages); font-size: 9px; color: #777; }} }}
:root {{ --ink:{INK}; --ink2:{INK2}; --line:#e2e1dc; --brand:#2a78d6; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:#f4f4f1; color:var(--ink); font:13px/1.45 "Segoe UI", Inter, Roboto, Arial, sans-serif; }}
.page {{ max-width: 1080px; margin: 0 auto; background:#fff; padding: 28px 34px 40px; }}
header {{ display:flex; justify-content:space-between; gap:16px; border-bottom:3px solid var(--brand); padding-bottom:14px; margin-bottom:18px; }}
.brand {{ font-weight:800; font-size:20px; letter-spacing:.5px; color:var(--brand); }}
.brand small {{ display:block; font-weight:600; font-size:11px; color:var(--ink2); letter-spacing:0; }}
h1 {{ margin:6px 0 2px; font-size:22px; }}
.meta {{ color:var(--ink2); font-size:12px; text-align:right; line-height:1.6; }}
.desc {{ color:var(--ink2); margin:0 0 16px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin-bottom:18px; }}
.kpi {{ border:1px solid var(--line); border-top:4px solid var(--brand); border-radius:8px; padding:10px 12px; break-inside:avoid; }}
.kl {{ font-size:11px; text-transform:uppercase; letter-spacing:.4px; color:var(--ink2); }}
.kv {{ font-size:22px; font-weight:750; margin:2px 0; }}
.ks {{ font-size:11px; color:var(--ink2); }}
h2 {{ font-size:15px; margin:22px 0 8px; padding-bottom:4px; border-bottom:1px solid var(--line); }}
h3 {{ font-size:13.5px; margin:16px 0 6px; }}
ul.find {{ list-style:none; padding:0; margin:0; }}
ul.find li {{ border-left:4px solid; padding:7px 10px; margin-bottom:6px; border-radius:4px; break-inside:avoid; }}
ol.recs li {{ margin-bottom:4px; }}
.charts {{ display:flex; flex-wrap:wrap; gap:12px; }}
figure {{ margin:0; border:1px solid var(--line); border-radius:8px; padding:10px 12px 6px; break-inside:avoid; }}
figure.wide {{ flex:1 1 100%; }} figure.half {{ flex:1 1 calc(50% - 6px); min-width:320px; }}
figcaption {{ font-weight:650; font-size:12.5px; margin-bottom:4px; }}
svg.chart {{ width:100%; height:auto; display:block; font-family:inherit; }}
.tw {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:11.5px; }}
th {{ text-align:left; background:#f3f3ef; color:var(--ink2); font-weight:650; padding:6px 7px; border-bottom:1px solid var(--line); vertical-align:bottom; }}
td {{ padding:5px 7px; border-bottom:1px solid #efeee9; vertical-align:top; overflow-wrap:anywhere; }}
td:first-child {{ white-space:nowrap; font-weight:550; }}
tr:nth-child(even) td {{ background:#fafaf7; }}
thead {{ display:table-header-group; }} tr {{ break-inside:avoid; }}
td.empty {{ text-align:center; color:var(--ink2); padding:14px; }}
.pill {{ display:inline-block; padding:1px 7px; border-radius:10px; font-weight:600; font-size:11px; white-space:nowrap; }}
.note {{ font-size:11px; color:var(--ink2); margin:4px 0 0; }}
.notes {{ font-size:11.5px; color:var(--ink2); }}
footer {{ margin-top:26px; border-top:1px solid var(--line); padding-top:10px; font-size:10.5px; color:var(--ink2); display:flex; justify-content:space-between; gap:10px; flex-wrap:wrap; }}
.toolbar {{ position:sticky; top:0; text-align:right; padding:8px; background:#f4f4f1; }}
.toolbar button {{ background:var(--brand); color:#fff; border:0; border-radius:6px; padding:8px 14px; font-weight:600; cursor:pointer; }}
@media print {{ table {{ font-size:9.5px; }} th, td {{ padding:3px 4px; }} th {{ white-space:normal; }} body {{ background:#fff; }} .page {{ padding:0; max-width:none; }} .no-print {{ display:none; }} h2 {{ break-after:avoid; }} }}
</style></head>
<body>{toolbar}<div class="page">
<header><div><div class="brand">GBOC<small>{esc(rep.get('platform') or '')}{(' · ' + org) if (org and org.lower() not in (rep.get('platform') or '').lower()) else ''}</small></div>
<h1>{esc(rep['title'])}</h1><div style="color:var(--ink2);font-size:12px">{esc(rep['code'])} · {esc(rep['category'])}{(' · Público: ' + esc(rep['audience'])) if rep.get('audience') else ''}</div></div>
<div class="meta"><div><b>Período:</b> {esc(period)}</div><div><b>Escopo:</b> {esc(rep['scope'])}</div><div><b>Emitido em:</b> {esc(fmt_dt(rep['generated_at']))}</div></div></header>
<p class="desc">{esc(rep['description'])}</p>
<div class="kpis">{kpis}</div>
{('<h2>Principais constatações</h2><ul class="find">' + findings + '</ul>') if findings else ''}
{('<h2>Recomendações</h2><ol class="recs">' + recs + '</ol>') if recs else ''}
{('<h2>Gráficos</h2><div class="charts">' + charts + '</div>') if charts else ''}
{('<h2>Detalhamento</h2>' + ''.join(tables)) if tables else ''}
{('<h2>Observações sobre os dados</h2><ul class="notes">' + notes + '</ul>') if notes else ''}
<footer><span>Relatório gerado a partir de dados reais sincronizados pelos agentes GBOC — nenhum valor estimado sem indicação.</span>
<span>Integridade: {esc(rep.get('integrity'))} · Motor de relatórios {esc(rep.get('engine_version'))}</span></footer>
</div></body></html>"""
