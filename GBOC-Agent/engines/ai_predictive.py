# ==============================================================================
# GBOC System v14.7.4 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================
"""
GBOC AI Predictive Suite — modelos estatísticos sobre dados REAIS (Server e Agent).

Arquivo compartilhado e IDÊNTICO em:
  - GBOC-Server/modules/reports/ai_predictive.py
  - GBOC-Agent/engines/ai_predictive.py

Entradas (sempre coletadas do banco/telemetria reais pelo chamador):
  executions: [{"start": datetime|str, "bytes": int, "status": str}]
  disks:      [{"total_gb": float, "used_gb": float}]
  ransomware: {"available": bool, "canaries_total": int, "canaries_compromised": int,
               "incidents_30d": int|None}

Nenhum valor é presumido: quando a amostra é insuficiente, o modelo retorna
status "UNAVAILABLE" com o motivo. A "confiança" é uma métrica real (R² ou tamanho da amostra).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

MIN_DAYS_FOR_REGRESSION = 3
MIN_SAMPLES_FOR_ZSCORE = 5
MIN_SAMPLES_FOR_WINDOW = 5
Z_THRESHOLD = 2.5
EXHAUSTION_WARNING_DAYS = 60

UNAVAILABLE_EXTERNAL = [
    {"name": "FinOps Glacier Tiering Auto-Detection", "type": "Integração externa", "status": "UNAVAILABLE",
     "confidence": "N/A", "detail": "Requer credenciais AWS S3 Lifecycle ou Wasabi Cold Storage configuradas em Configurações > Storage."},
    {"name": "Green Backup / Eficiência Energética", "type": "Telemetria de hardware", "status": "UNAVAILABLE",
     "confidence": "N/A", "detail": "Requer sensor IPMI/ACPI de consumo energético no host."},
]


def _to_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Retorna (slope, r2) por mínimos quadrados."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, 0.0
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return slope, max(0.0, min(1.0, r2))


def capacity_model(executions: list[dict[str, Any]], disks: list[dict[str, Any]], days: int = 30) -> dict[str, Any]:
    cutoff = datetime.now() - timedelta(days=days)
    per_day: dict[datetime, int] = defaultdict(int)
    for e in executions:
        dt = _to_dt(e.get("start"))
        b = int(e.get("bytes") or 0)
        if dt and dt >= cutoff and b > 0:
            per_day[dt.replace(hour=0, minute=0, second=0, microsecond=0)] += b
    total_gb = sum(float(d.get("total_gb") or 0) for d in disks)
    used_gb = sum(float(d.get("used_gb") or 0) for d in disks)
    free_gb = max(0.0, total_gb - used_gb)
    base = {"name": "Predição Linear de Capacidade de Storage", "type": "Regressão linear (volume acumulado/dia)"}

    if len(per_day) < MIN_DAYS_FOR_REGRESSION:
        return {**base, "status": "UNAVAILABLE", "confidence": "N/A", "growth_gb_day": None, "days_to_exhaustion": None,
                "detail": f"Amostra insuficiente: {len(per_day)} dia(s) com volume registrado (mínimo {MIN_DAYS_FOR_REGRESSION})."}
    ordered = sorted(per_day.items())
    t0 = ordered[0][0]
    xs, ys, acc = [], [], 0.0
    for day, b in ordered:
        acc += b / (1024 ** 3)
        xs.append((day - t0).days)
        ys.append(acc)
    slope, r2 = _linear_regression(xs, ys)
    growth = round(max(slope, 0.0), 3)
    if total_gb <= 0:
        return {**base, "status": "OPERACIONAL", "confidence": f"R² {r2:.2f}", "growth_gb_day": growth,
                "days_to_exhaustion": None,
                "detail": f"Crescimento de {growth} GB/dia ({len(per_day)} dias de amostra). Capacidade total não informada — esgotamento não calculado."}
    days_left = int(free_gb / growth) if growth > 0 else None
    status = "OPERACIONAL" if days_left is None or days_left > EXHAUSTION_WARNING_DAYS else "ALERTA"
    if days_left is None:
        detail = f"Sem crescimento líquido detectado; {free_gb:.1f} GB livres."
    else:
        date_txt = (datetime.now() + timedelta(days=days_left)).strftime("%d/%m/%Y")
        detail = f"Crescimento de {growth} GB/dia ({len(per_day)} dias de amostra); {free_gb:.1f} GB livres; esgotamento projetado em ~{days_left} dias ({date_txt})."
    return {**base, "status": status, "confidence": f"R² {r2:.2f}", "growth_gb_day": growth,
            "days_to_exhaustion": days_left, "free_gb": round(free_gb, 1), "detail": detail}


def anomaly_model(executions: list[dict[str, Any]]) -> dict[str, Any]:
    sizes = [int(e.get("bytes") or 0) for e in executions if int(e.get("bytes") or 0) > 0]
    base = {"name": "Detecção de Anomalias de Volume (Z-Score)", "type": f"Desvio estatístico (|Z| > {Z_THRESHOLD})"}
    if len(sizes) < MIN_SAMPLES_FOR_ZSCORE:
        return {**base, "status": "UNAVAILABLE", "confidence": "N/A", "anomalies": None,
                "detail": f"Amostra insuficiente: {len(sizes)} execução(ões) com volume (mínimo {MIN_SAMPLES_FOR_ZSCORE})."}
    avg = sum(sizes) / len(sizes)
    std = math.sqrt(sum((s - avg) ** 2 for s in sizes) / len(sizes))
    anomalies = sum(1 for s in sizes if std > 0 and abs(s - avg) / std > Z_THRESHOLD)
    return {**base, "status": "OPERACIONAL" if anomalies == 0 else "ALERTA", "confidence": f"n={len(sizes)}",
            "anomalies": anomalies,
            "detail": f"{anomalies} execução(ões) com volume atípico entre {len(sizes)} analisadas (média {avg / 1048576:.1f} MB)."}


def ransomware_model(ransomware: dict[str, Any]) -> dict[str, Any]:
    base = {"name": "Exposição a Ransomware", "type": "Canários + incidentes registrados"}
    if not ransomware or not ransomware.get("available"):
        return {**base, "status": "UNAVAILABLE", "confidence": "N/A", "compromised": None,
                "detail": "Dados do Ransomware Guardian indisponíveis."}
    total = int(ransomware.get("canaries_total") or 0)
    comp = int(ransomware.get("canaries_compromised") or 0)
    incidents = ransomware.get("incidents_30d")
    parts = []
    if total:
        parts.append(f"{comp} de {total} canário(s) comprometido(s)")
    if incidents is not None:
        parts.append(f"{incidents} incidente(s) nos últimos 30 dias")
    if not parts:
        return {**base, "status": "UNAVAILABLE", "confidence": "N/A", "compromised": None,
                "detail": "Nenhum canário implantado e nenhum registro de incidentes disponível."}
    alert = comp > 0 or (incidents or 0) > 0
    conf = f"n={total} canários" if total else "registro de incidentes"
    return {**base, "status": "ALERTA" if alert else "OPERACIONAL", "confidence": conf,
            "compromised": comp, "detail": "; ".join(parts) + "."}


def window_model(executions: list[dict[str, Any]]) -> dict[str, Any]:
    base = {"name": "Análise da Janela de Backup", "type": "Densidade de execuções por hora"}
    starts = [(dt, str(e.get("status") or "").lower()) for e in executions if (dt := _to_dt(e.get("start")))]
    if len(starts) < MIN_SAMPLES_FOR_WINDOW:
        return {**base, "status": "UNAVAILABLE", "confidence": "N/A",
                "detail": f"Amostra insuficiente: {len(starts)} execução(ões) (mínimo {MIN_SAMPLES_FOR_WINDOW})."}
    by_hour = Counter(dt.hour for dt, _ in starts)
    fails = Counter(dt.hour for dt, st in starts if st in ("failed", "error"))
    busiest = ", ".join(f"{h:02d}h ({c})" for h, c in by_hour.most_common(3))
    # Taxa de falha só é considerada em horários com amostra mínima (evita alerta por 1 execução isolada)
    worst = [(h, fails[h] / by_hour[h]) for h in by_hour if fails[h] and by_hour[h] >= 3]
    worst.sort(key=lambda x: x[1], reverse=True)
    worst_txt = ("; maior taxa de falha às " + ", ".join(f"{h:02d}h ({r:.0%})" for h, r in worst[:2])) if worst else "; nenhum horário com taxa de falha relevante (mín. 3 execuções/hora)"
    return {**base, "status": "ALERTA" if worst and worst[0][1] >= 0.5 else "OPERACIONAL", "confidence": f"n={len(starts)}",
            "detail": f"Horários mais carregados: {busiest}{worst_txt}."}


def build_predictive_suite(executions: list[dict[str, Any]], disks: list[dict[str, Any]],
                           ransomware: dict[str, Any],
                           capacity_points: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """
    Executa os modelos e calcula um score heurístico transparente (ou None sem dados).
    capacity_points: série própria para o modelo de capacidade (ex.: bytes efetivamente adicionados
    ao repositório ou variação diária do storage); por padrão usa ``executions``.
    """
    cap = capacity_model(capacity_points if capacity_points is not None else executions, disks)
    ano = anomaly_model(executions)
    rw = ransomware_model(ransomware)
    win = window_model(executions)
    models = [cap, ano, rw, win]
    operational = [m for m in models if m["status"] != "UNAVAILABLE"]

    score: int | None = None
    # O score só é calculado quando há dados de execução/capacidade (o modelo de ransomware sozinho não basta)
    if any(m["status"] != "UNAVAILABLE" for m in (cap, ano, win)):
        score = 100
        if ano.get("anomalies"):
            score -= min(30, 10 * ano["anomalies"])
        if cap.get("days_to_exhaustion") is not None and cap["days_to_exhaustion"] <= EXHAUSTION_WARNING_DAYS:
            score -= 25
        if rw.get("status") == "ALERTA":
            score -= 40
        if win.get("status") == "ALERTA":
            score -= 10
        score = max(0, score)

    failed = sum(1 for e in executions if str(e.get("status") or "").lower() in ("failed", "error"))
    return {
        "score": score,
        "models": models + UNAVAILABLE_EXTERNAL,
        "operational_count": len(operational),
        "capacity": cap, "anomaly": ano, "ransomware": rw, "window": win,
        "executions_analyzed": len(executions),
        "failed_executions": failed,
        "score_method": "100 − 10/anomalia (máx. 30) − 25 se esgotamento ≤ 60 dias − 40 se ransomware em alerta − 10 se horário com ≥50% de falhas",
    }
