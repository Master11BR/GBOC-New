# ==============================================================================
# GBOC System v14.8.1 Enterprise Edition
# Module: Flagship Reports Engine v2.0 (Server)
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# ==============================================================================

import os
import io
import csv
import json
import logging
import hashlib
import re
import html as html_lib
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

try:
    from version_control import __version__ as SERVER_VERSION
except Exception:
    SERVER_VERSION = "14.8.1"

def _clean_task_name(raw_name: str) -> str:
    """Remove sufixos técnicos gerados automaticamente de nomes de tasks."""
    if not raw_name:
        return "Sem Nome"
    import re
    cleaned = re.sub(r'_[A-Z0-9]{16,}$', '', str(raw_name))
    cleaned = cleaned.replace('_', ' ').strip()
    return cleaned or str(raw_name)

# Catálogo Oficial dos 8 Relatórios Flagship (Schema v4.0.0)
FLAGSHIPS_CATALOG_8 = [
    {
        "id": "REP-F1",
        "code": "REP-F1",
        "name": "Protection Scorecard",
        "category": "Executive Flagship",
        "substitutes": ["REP-01", "REP-02", "REP-07", "REP-14", "REP-16", "REP-24", "REP-30"],
        "target_audience": "CISO, Diretor de TI, MSP Account Manager",
        "objective": "Visão consolidada de proteção, SLA e disponibilidade do ecossistema em menos de 10 segundos.",
        "score_title": "PROTECTION SCORE",
        "icon": "fa-shield-halved"
    },
    {
        "id": "REP-F2",
        "code": "REP-F2",
        "name": "Operational Performance",
        "category": "Operations Flagship",
        "substitutes": ["REP-04", "REP-08", "REP-11", "REP-15", "REP-17", "REP-19", "REP-20", "REP-21", "REP-22", "REP-25", "REP-28"],
        "target_audience": "NOC, Engenharia, Administrador de Backup",
        "objective": "Telemetria de execuções com dados individuais reais por tarefa, comparativo entre motores e causa raiz.",
        "score_title": "OPERATIONAL HEALTH SCORE",
        "icon": "fa-gauge-high"
    },
    {
        "id": "REP-F3",
        "code": "REP-F3",
        "name": "Storage Intelligence",
        "category": "Storage Flagship",
        "substitutes": ["REP-03", "REP-05", "REP-09", "REP-17", "REP-23", "REP-26", "REP-31"],
        "target_audience": "Administrador de Infraestrutura, FinOps",
        "objective": "Saúde do armazenamento, projeção preditiva por regressão linear e taxa de deduplicação real por repositório.",
        "score_title": "STORAGE HEALTH & CAPACIDADE",
        "icon": "fa-hard-drive"
    },
    {
        "id": "REP-F4",
        "code": "REP-F4",
        "name": "Security & Resilience",
        "category": "Security Flagship",
        "substitutes": ["REP-06", "REP-12", "REP-13", "REP-18", "REP-27", "REP-32", "REP-37"],
        "target_audience": "CISO, SOC, Analista de Segurança",
        "objective": "Linha do tempo unificada de eventos de integridade, canários digitais ativos, WORM lock e auditoria.",
        "score_title": "THREAT SCORE & RESILIENCE",
        "icon": "fa-biohazard"
    },
    {
        "id": "REP-F5",
        "code": "REP-F5",
        "name": "Compliance & Governance",
        "category": "Governance Flagship",
        "substitutes": ["REP-02", "REP-10", "REP-24", "REP-27", "REP-29", "REP-33"],
        "target_audience": "DPO, Auditor de TI, Compliance Officer",
        "objective": "Auditoria de SLA RPO/RTO em minutos, políticas de retenção/poda, conformidade LGPD/GDPR e inventário de pontos.",
        "score_title": "COMPLIANCE & GOVERNANCE SCORE",
        "icon": "fa-scale-balanced"
    },
    {
        "id": "REP-F6",
        "code": "REP-F6",
        "name": "AI Predictive Suite",
        "category": "AI Flagship",
        "substitutes": ["REP-31 a REP-50"],
        "target_audience": "Planejamento Estratégico, Engenharia de DR, Diretoria de TI",
        "objective": "Inteligência preditiva executiva baseada em modelos estatísticos e séries temporais sobre dados reais.",
        "score_title": "AI PREDICTIVE SCORE",
        "icon": "fa-brain"
    },
    {
        "id": "REP-F7",
        "code": "REP-F7",
        "name": "FinOps & Total Cost of Ownership",
        "category": "FinOps Flagship",
        "substitutes": ["REP-10", "REP-33", "REP-35", "REP-41", "REP-50"],
        "target_audience": "CFO, Gerente de TI, FinOps, MSP Account Manager",
        "objective": "TCO detalhado com conversão USD->BRL do Banco Central, oportunidades de economia e faturamento multi-tenant.",
        "score_title": "FINOPS TCO & ROI SCORE",
        "icon": "fa-sack-dollar"
    },
    {
        "id": "REP-F8",
        "code": "REP-F8",
        "name": "Disaster Recovery Readiness",
        "category": "DR Flagship",
        "substitutes": ["REP-18", "REP-29", "REP-34", "REP-46", "REP-47", "REP-49"],
        "target_audience": "CTO, Arquiteto de DR, Gestor de Continuidade de Negócios",
        "objective": "Matriz de prontidão para desastres, gaps de RTO/RPO reais vs meta, ordem de boot e simulação de contingência.",
        "score_title": "DR READINESS SCORE",
        "icon": "fa-fire-extinguisher"
    }
]

FLAGSHIPS_CATALOG_7 = FLAGSHIPS_CATALOG_8


def _default_db_getter():
    try:
        from modules.reports.reports_router import _get_server_db
        return _get_server_db()
    except Exception:
        try:
            from database import db_manager
            return db_manager.get_connection(), db_manager
        except Exception:
            return None, None

def _default_get_usd_rate():
    try:
        from modules.reports.reports_router import get_usd_to_brl_rate
        return get_usd_to_brl_rate()
    except Exception:
        return 5.50

def _default_get_reports_cfg():
    try:
        from modules.reports.reports_router import get_reports_config
        return get_reports_config()
    except Exception:
        return {"cloud_storage_cost_usd_per_tb": 7.99}


def _build_server_f6_ai(report: Dict[str, Any], db_getter) -> None:
    """REP-F6 AI Predictive Suite (Server) — modelos estatísticos sobre dados reais do PostgreSQL."""
    from modules.reports.ai_predictive import build_predictive_suite

    executions: List[Dict[str, Any]] = []
    growth_points: List[Dict[str, Any]] = []
    ransomware: Dict[str, Any] = {"available": False}
    conn, db_mgr = None, None
    try:
        conn, db_mgr = db_getter()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT started_at, COALESCE(bytes_processed, 0), status
                FROM agent_task_executions
                WHERE started_at >= LOCALTIMESTAMP - INTERVAL '30 days'
                ORDER BY started_at
            """)
            executions = [{"start": r[0], "bytes": int(r[1] or 0), "status": r[2]} for r in cur.fetchall()]
            # Crescimento real do storage: variação diária do tamanho somado dos repositórios
            cur.execute("""
                SELECT d, SUM(sz) FROM (
                    SELECT DISTINCT ON (repository_id, recorded_at::date)
                           recorded_at::date AS d, size_bytes AS sz
                    FROM storage_usage_history
                    WHERE recorded_at >= NOW() - INTERVAL '30 days'
                    ORDER BY repository_id, recorded_at::date, recorded_at DESC
                ) t GROUP BY d ORDER BY d
            """)
            rows = cur.fetchall()
            prev = None
            for d, total in rows:
                if prev is not None and total is not None:
                    growth_points.append({"start": datetime.combine(d, datetime.min.time()), "bytes": max(0, int(total) - int(prev)), "status": "completed"})
                prev = total
            cur.execute("SELECT COUNT(*) FROM ransomware_central_incidents WHERE COALESCE(detected_at, created_at) >= LOCALTIMESTAMP - INTERVAL '30 days'")
            ransomware = {"available": True, "canaries_total": 0, "canaries_compromised": 0, "incidents_30d": int(cur.fetchone()[0])}
            cur.close()
    except Exception as err:
        logger.warning(f"REP-F6: falha ao coletar dados reais: {err}")
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
    finally:
        if db_mgr and conn:
            db_mgr.release_connection(conn)

    suite = build_predictive_suite(executions, [], ransomware, capacity_points=growth_points or None)
    cap, ano = suite["capacity"], suite["anomaly"]
    score = suite["score"]

    report["score_value"] = score if score is not None else "N/D"
    report["score_delta"] = f"{suite['operational_count']} de 4 modelos com dados"
    report["score_status"] = "N/D" if score is None else ("OK" if score >= 85 else "ATENÇÃO" if score >= 70 else "CRÍTICO")
    report["score_composition"] = [
        {"label": m["name"], "value": m["status"], "weight": m["confidence"],
         "bar_pct": 100 if m["status"] == "OPERACIONAL" else 50 if m["status"] == "ALERTA" else 0}
        for m in suite["models"][:4]
    ]
    report["delta"] = [
        {"type": "neutral" if m["status"] == "OPERACIONAL" else "deterioration",
         "icon": "→" if m["status"] == "OPERACIONAL" else "↓",
         "class": "delta-neutral" if m["status"] == "OPERACIONAL" else "delta-down",
         "text": f"{m['name']}: {m['detail']}"}
        for m in suite["models"][:4]
    ]
    report["kpi_cards"] = [
        {"label": "AI Predictive Score", "value": f"{score} / 100" if score is not None else "Indisponível",
         "target": "Alvo: ≥ 85", "status": "SEM DADOS" if score is None else ("CONFORME" if score >= 85 else "ATENÇÃO")},
        {"label": "Modelos com Dados", "value": f"{suite['operational_count']} de 4", "target": "Meta: 4",
         "status": "CONFORME" if suite["operational_count"] == 4 else "ATENÇÃO"},
        {"label": "Crescimento de Storage",
         "value": f"{cap['growth_gb_day']} GB/dia" if cap.get("growth_gb_day") is not None else "Indisponível",
         "target": "Tendência", "status": "SEM DADOS" if cap["status"] == "UNAVAILABLE" else "CONFORME"},
        {"label": "Anomalias Detectadas", "value": str(ano["anomalies"]) if ano.get("anomalies") is not None else "Indisponível",
         "target": "Alvo: Zero", "status": "SEM DADOS" if ano.get("anomalies") is None else ("CONFORME" if ano["anomalies"] == 0 else "ATENÇÃO")},
    ]
    report["sections"].append({
        "title": "Modelos de Inteligência Artificial & Estatística Preditiva",
        "narrative": (f"Modelos aplicados a <strong>{suite['executions_analyzed']} execuções reais</strong> sincronizadas pelos agentes "
                      f"nos últimos 30 dias ({suite['failed_executions']} com falha). Modelos sem amostra suficiente são exibidos como UNAVAILABLE."),
        "table_headers": ["Modelo", "Metodologia", "Status", "Confiança / Amostra", "Diagnóstico & Projeção"],
        "table_rows": [[m["name"], m["type"], m["status"], m["confidence"], m["detail"]] for m in suite["models"]],
        "ai_inline": f"Score heurístico: {suite['score_method']}.",
    })
    actions = []
    if cap["status"] == "ALERTA":
        actions.append({"priority": "ALTA", "action": "Expandir o storage ou revisar a retenção: esgotamento projetado em menos de 60 dias.", "owner": "Engenharia de Backup", "deadline": "7 dias"})
    if ano.get("anomalies"):
        actions.append({"priority": "ALTA", "action": "Investigar execuções com volume atípico (possível alteração em massa de arquivos).", "owner": "Segurança / NOC", "deadline": "24 horas"})
    if suite["ransomware"]["status"] == "ALERTA":
        actions.append({"priority": "CRÍTICA", "action": "Tratar os incidentes de ransomware registrados nos últimos 30 dias.", "owner": "SOC", "deadline": "Imediato"})
    missing = [m["name"] for m in suite["models"][:4] if m["status"] == "UNAVAILABLE"]
    if missing:
        actions.append({"priority": "MÉDIA", "action": "Acumular histórico para habilitar: " + ", ".join(missing) + ".", "owner": "Administrador de Backup", "deadline": "30 dias"})
    report["recommended_actions"] = actions


# ─── BUILDER GERAL PARA OS 7 FLAGSHIPS (SERVER) ──────────────────────────────
def build_flagship_report_server(
    flagship_id: str,
    db_getter=None,
    get_usd_rate=None,
    get_reports_cfg=None
) -> Dict[str, Any]:
    """
    Compila o relatório Flagship com dados reais do PostgreSQL do Servidor Central
    (dados sincronizados pelos agentes — o servidor pode estar em outra máquina).
    Indicadores sem amostra são exibidos como N/D / SEM DADOS.
    """
    from modules.reports import flagship_server_builders as fb

    if db_getter is None:
        db_getter = _default_db_getter
    if get_reports_cfg is None:
        get_reports_cfg = _default_get_reports_cfg

    flagship_meta = next((f for f in FLAGSHIPS_CATALOG_8 if f["id"].upper() == flagship_id.upper()), FLAGSHIPS_CATALOG_8[0])
    code = flagship_meta["code"]

    if get_usd_rate is not None:
        usd_info = {"rate": float(get_usd_rate()), "live": True, "source": "provedor de cotação informado"}
    else:
        try:
            from modules.config.config_router import get_usd_to_brl_rate_info
            usd_info = get_usd_to_brl_rate_info()
        except Exception:
            usd_info = {"rate": _default_get_usd_rate(), "live": False, "source": "valor de referência"}
    reports_cfg = get_reports_cfg() or {}
    cost_per_tb = reports_cfg.get("cloud_storage_cost_usd_per_tb")

    now = datetime.now()
    period_start = (now - timedelta(days=fb.PERIOD_DAYS)).strftime("%Y-%m-%d")
    period_end = now.strftime("%Y-%m-%d")
    report: Dict[str, Any] = {
        "report_id": code,
        "report_name": flagship_meta["name"],
        "category": flagship_meta["category"],
        "platform": f"GBOC Server v{SERVER_VERSION}",
        "schema_version": "4.1.0",
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "period_start": period_start,
        "period_end": period_end,
        "period_label": f"Últimos {fb.PERIOD_DAYS} dias ({period_start} a {period_end})",
        "target_audience": flagship_meta["target_audience"],
        "objective": flagship_meta["objective"],
        "score_title": flagship_meta["score_title"],
        "score_value": "N/D",
        "score_delta": "",
        "score_status": "N/D",
        "score_composition": [],
        "delta": [],
        "kpi_cards": [],
        "sections": [],
        "recommended_actions": [],
        "methodology": ("Indicadores calculados exclusivamente a partir do PostgreSQL do Servidor Central "
                        "(execuções, tarefas, repositórios e status de segurança sincronizados pelos agentes). "
                        "Indicadores sem amostra suficiente são exibidos como N/D, sem valores presumidos."),
    }

    if code == "REP-F6":
        _build_server_f6_ai(report, db_getter)
    else:
        data = fb.collect_server_report_data(db_getter)
        if code == "REP-F1":
            fb.build_f1(report, data)
        elif code == "REP-F2":
            fb.build_f2(report, data)
        elif code == "REP-F3":
            fb.build_f3(report, data, usd_info, cost_per_tb)
        elif code == "REP-F4":
            fb.build_f4(report, data)
        elif code == "REP-F5":
            fb.build_f5(report, data)
        elif code == "REP-F7":
            fb.build_f7(report, data, usd_info, cost_per_tb)
        else:
            fb.build_f8(report, data)

    hash_seed = json.dumps(report, sort_keys=True, default=str)
    report["integrity_hash"] = hashlib.sha256(hash_seed.encode("utf-8")).hexdigest().upper()
    return report


# ─── RENDERIZADOR HTML / A4 OFICIAL v2.0 ─────────────────────────────────────
def render_flagship_html(report_data: Dict[str, Any], is_print: bool = False) -> str:
    """Gera o documento HTML interativo e pronto para impressão estrita A4 / PDF institucional."""
    audit_hash = report_data.get("integrity_hash", "00000000000000000000000000000000")
    audit_hash_short = f"{audit_hash[:8]}-{audit_hash[8:16]}-{audit_hash[16:24]}-{audit_hash[24:32]}"

    score_val = report_data.get("score_value", 85)
    score_status = report_data.get("score_status", "OK")
    score_color = "#10b981" if score_status == "OK" else ("#f59e0b" if score_status in ["ATENÇÃO", "EM RISCO"] else ("#64748b" if score_status == "N/D" else "#ef4444"))
    status_bg = "#ecfdf5" if score_status == "OK" else ("#fffbeb" if score_status in ["ATENÇÃO", "EM RISCO"] else "#fef2f2")
    status_border = "#a7f3d0" if score_status == "OK" else ("#fde68a" if score_status in ["ATENÇÃO", "EM RISCO"] else "#fecaca")

    # Composição do score
    from html import escape as _esc
    comp_html = ""
    for c in report_data.get("score_composition", []):
        pct = c.get("bar_pct", 80)
        comp_html += f"""
        <div class="score-comp-row">
            <span class="comp-label">{_esc(str(c['label']))} <strong>{_esc(str(c['value']))}</strong></span>
            <div class="comp-bar-bg"><div class="comp-bar-fill" style="width:{pct}%;background:{score_color}"></div></div>
            <span class="comp-weight">peso {_esc(str(c['weight']))}</span>
        </div>
        """

    # Delta bullets (O que mudou)
    delta_html = ""
    for d in report_data.get("delta", []):
        delta_html += f"""
        <div class="delta-item {d['class']}">
            <span class="delta-icon">{d['icon']}</span>
            <span class="delta-text">{_esc(str(d['text']))}</span>
        </div>
        """

    # KPI Cards com Benchmark
    kpis_html = ""
    kpi_colors = ["#0284c7", "#10b981", "#f59e0b", "#8b5cf6", "#06b6d4"]
    for i, k in enumerate(report_data.get("kpi_cards", [])):
        col = kpi_colors[i % len(kpi_colors)]
        st = k.get("status", "CONFORME")
        st_badge_cls = "badge-kpi-ok" if st == "CONFORME" else ("badge-kpi-warn" if st in ["ATENÇÃO", "EM RISCO", "SEM DADOS"] else "badge-kpi-danger")
        kpis_html += f"""
        <div class="flagship-kpi-card" style="--card-border-top:{col}">
            <div class="kpi-top">
                <span class="kpi-label">{_esc(str(k['label']))}</span>
                <span class="kpi-badge {st_badge_cls}">{st}</span>
            </div>
            <div class="kpi-value">{_esc(str(k['value']))}</div>
            <div class="kpi-target">{_esc(str(k['target']))}</div>
        </div>
        """

    # Seções analíticas
    sections_html = ""
    for s in report_data.get("sections", []):
        headers_th = "".join([f"<th>{_esc(str(h))}</th>" for h in s.get("table_headers", [])])
        rows_td = ""
        for row in s.get("table_rows", []):
            cells = ""
            for c in row:
                c_str = _esc(str(c))
                if c_str in ["COMPLIANT", "CONFORME", "OK", "SUCCESS", "ATIVO", "OPERACIONAL"]:
                    cells += f'<td><span class="status-pill pill-green">{c_str}</span></td>'
                elif c_str in ["EM RISCO", "ATENÇÃO", "WARNING", "ALERTA", "INATIVO"]:
                    cells += f'<td><span class="status-pill pill-yellow">{c_str}</span></td>'
                elif c_str in ["NON_COMPLIANT", "NÃO CONFORME", "CRÍTICO", "FAILED", "CRITICAL", "OFFLINE"]:
                    cells += f'<td><span class="status-pill pill-red">{c_str}</span></td>'
                else:
                    cells += f'<td>{c_str}</td>'
            rows_td += f"<tr>{cells}</tr>"

        sections_html += f"""
        <div class="analytic-section">
            <h3 class="section-title"><i class="fas fa-chart-column"></i> {s['title']}</h3>
            <div class="section-lead-narrative"><i class="fas fa-quote-left"></i> {s['narrative']}</div>
            <div class="table-container">
                <table class="flagship-table">
                    <thead><tr>{headers_th}</tr></thead>
                    <tbody>{rows_td}</tbody>
                </table>
            </div>
            <div class="ai-inline-box">
                <div class="ai-inline-header"><i class="fas fa-brain"></i> Análise automática (dados reais)</div>
                <div class="ai-inline-body">{s['ai_inline']}</div>
            </div>
        </div>
        """

    # Ações recomendadas
    actions_html = ""
    for a in report_data.get("recommended_actions", []):
        prio = a.get("priority", "MÉDIA")
        prio_cls = "prio-high" if prio == "ALTA" else ("prio-med" if prio == "MÉDIA" else "prio-low")
        actions_html += f"""
        <div class="action-card {prio_cls}">
            <div class="action-prio-badge">[{prio}]</div>
            <div class="action-content">
                <div class="action-desc">{_esc(str(a['action']))}</div>
                <div class="action-meta">
                    <span><i class="fas fa-user-shield"></i> Responsável sugerido: <strong>{_esc(str(a['owner']))}</strong></span>
                    <span><i class="fas fa-clock"></i> Prazo estimado: <strong>{_esc(str(a['deadline']))}</strong></span>
                </div>
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{report_data['report_name']} ({report_data['report_id']}) — GBOC Enterprise Suite</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/vendor/fontawesome/css/all.min.css">
    <style>
        :root {{
            --primary: #0284c7;
            --primary-dark: #0369a1;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --bg-page: #0b1120;
            --bg-sheet: #ffffff;
            --border-color: #cbd5e1;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: var(--bg-page);
            color: var(--text-main);
            padding: 24px 16px;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-height: 100vh;
        }}
        .report-actions-bar {{
            width: 100%;
            max-width: 1080px;
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 12px 20px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }}
        .btn-action {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #0284c7;
            color: #ffffff;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 0.84em;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s;
        }}
        .btn-action:hover {{ background: #0369a1; transform: translateY(-1px); }}
        .btn-action.secondary {{ background: #334155; color: #e2e8f0; }}
        .btn-action.secondary:hover {{ background: #475569; }}

        .report-sheet {{
            background: var(--bg-sheet);
            width: 100%;
            max-width: 1080px;
            border-radius: 12px;
            padding: 38px 44px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.35);
            box-sizing: border-box;
            position: relative;
        }}
        .report-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            border-bottom: 2.5px solid var(--primary);
            padding-bottom: 18px;
            margin-bottom: 20px;
            gap: 16px;
        }}
        .brand-block {{ display: flex; align-items: center; gap: 14px; }}
        .brand-text h2 {{ font-size: 1.25em; font-weight: 800; color: #0f172a; }}
        .brand-text p {{ font-size: 0.72em; color: var(--text-muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }}
        .badge-classification {{
            display: inline-block;
            background: #f0fdf4;
            color: #166534;
            border: 1px solid #bbf7d0;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.72em;
            font-weight: 700;
            text-transform: uppercase;
        }}
        .report-title-banner h1 {{ font-size: 1.5em; color: #0f172a; font-weight: 800; margin-bottom: 4px; }}
        .report-title-banner .desc {{ font-size: 0.88em; color: var(--text-muted); line-height: 1.4; }}

        /* Meta grid */
        .report-meta-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 20px;
        }}
        .meta-item .label {{ font-size: 0.68em; text-transform: uppercase; color: var(--text-muted); font-weight: 700; }}
        .meta-item .val {{ font-size: 0.84em; font-weight: 700; color: #1e293b; margin-top: 2px; }}

        /* SCORE PRINCIPAL */
        .score-spotlight-card {{
            background: {status_bg};
            border: 1.5px solid {status_border};
            border-radius: 10px;
            padding: 20px 24px;
            margin-bottom: 22px;
            display: grid;
            grid-template-columns: 260px 1fr;
            gap: 24px;
            align-items: center;
        }}
        .score-display-box {{
            text-align: center;
            border-right: 1.5px solid {status_border};
            padding-right: 20px;
        }}
        .score-title-sub {{ font-size: 0.75em; text-transform: uppercase; font-weight: 800; color: var(--text-muted); letter-spacing: 0.05em; }}
        .score-number {{ font-size: 3.2em; font-weight: 900; color: {score_color}; line-height: 1.1; margin: 4px 0; }}
        .score-number small {{ font-size: 0.45em; color: var(--text-muted); font-weight: 700; }}
        .score-delta-tag {{ display: inline-block; font-size: 0.78em; font-weight: 700; color: #1e293b; background: rgba(255,255,255,0.8); padding: 2px 8px; border-radius: 4px; }}

        .score-comp-row {{ display: grid; grid-template-columns: 180px 1fr 80px; align-items: center; gap: 12px; margin-bottom: 6px; font-size: 0.8em; }}
        .comp-label strong {{ color: #0f172a; margin-left: 4px; }}
        .comp-bar-bg {{ background: #e2e8f0; height: 8px; border-radius: 4px; overflow: hidden; }}
        .comp-bar-fill {{ height: 100%; border-radius: 4px; }}
        .comp-weight {{ font-size: 0.85em; color: var(--text-muted); text-align: right; }}

        /* DELTA */
        .delta-box {{
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 22px;
        }}
        .delta-header {{ font-size: 0.82em; font-weight: 800; text-transform: uppercase; color: #0f172a; margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }}
        .delta-item {{ display: flex; align-items: flex-start; gap: 10px; font-size: 0.84em; line-height: 1.45; margin-bottom: 6px; }}
        .delta-item:last-child {{ margin-bottom: 0; }}
        .delta-icon {{ font-weight: 900; width: 18px; text-align: center; font-size: 1.1em; }}
        .delta-up .delta-icon {{ color: #10b981; }}
        .delta-down .delta-icon {{ color: #ef4444; }}
        .delta-neutral .delta-icon {{ color: #0284c7; }}

        /* KPI CARDS */
        .kpis-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin-bottom: 24px;
        }}
        .flagship-kpi-card {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-top: 3.5px solid var(--card-border-top, #0284c7);
            border-radius: 8px;
            padding: 12px 14px;
        }}
        .kpi-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }}
        .kpi-label {{ font-size: 0.72em; text-transform: uppercase; font-weight: 700; color: var(--text-muted); }}
        .badge-kpi-ok {{ font-size: 0.65em; font-weight: 700; background: #ecfdf5; color: #166534; padding: 1px 6px; border-radius: 4px; }}
        .badge-kpi-warn {{ font-size: 0.65em; font-weight: 700; background: #fffbeb; color: #b45309; padding: 1px 6px; border-radius: 4px; }}
        .badge-kpi-danger {{ font-size: 0.65em; font-weight: 700; background: #fef2f2; color: #b91c1c; padding: 1px 6px; border-radius: 4px; }}
        .kpi-value {{ font-size: 1.35em; font-weight: 800; color: #0f172a; margin-bottom: 2px; }}
        .kpi-target {{ font-size: 0.72em; color: #64748b; font-family: 'JetBrains Mono', monospace; }}

        /* SEÇÃO ANALÍTICA */
        .analytic-section {{ margin-bottom: 26px; }}
        .section-title {{ font-size: 1.05em; font-weight: 800; color: #0f172a; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }}
        .section-lead-narrative {{
            background: #f1f5f9;
            border-left: 3.5px solid var(--primary);
            padding: 10px 14px;
            font-size: 0.86em;
            color: #334155;
            line-height: 1.5;
            margin-bottom: 12px;
            border-radius: 0 6px 6px 0;
        }}
        .table-container {{
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            overflow-x: auto;
            margin-bottom: 12px;
        }}
        .flagship-table {{ width: 100%; border-collapse: collapse; font-size: 0.82em; }}
        .flagship-table th {{
            background: #f8fafc;
            color: #334155;
            font-weight: 700;
            padding: 9px 12px;
            text-align: left;
            border-bottom: 1.5px solid #cbd5e1;
            white-space: nowrap;
        }}
        .flagship-table td {{
            padding: 8px 12px;
            border-bottom: 1px solid #e2e8f0;
            color: #1e293b;
            vertical-align: middle;
        }}
        .flagship-table tbody tr:nth-child(even) {{ background: #fcfdfe; }}

        .status-pill {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 0.75em; text-transform: uppercase; }}
        .pill-green {{ background: #ecfdf5; color: #166534; }}
        .pill-yellow {{ background: #fffbeb; color: #b45309; }}
        .pill-red {{ background: #fef2f2; color: #b91c1c; }}

        .ai-inline-box {{
            background: #f0fdf4;
            border: 1px solid #bbf7d0;
            border-radius: 6px;
            padding: 10px 14px;
            font-size: 0.82em;
            color: #166534;
            line-height: 1.45;
        }}
        .ai-inline-header {{ font-weight: 800; text-transform: uppercase; margin-bottom: 4px; font-size: 0.76em; display: flex; align-items: center; gap: 6px; }}

        /* AÇÕES RECOMENDADAS */
        .actions-section {{ margin-top: 26px; margin-bottom: 26px; }}
        .action-card {{
            display: flex;
            align-items: flex-start;
            gap: 12px;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 8px;
            background: #ffffff;
        }}
        .action-card.prio-high {{ border-left: 4.5px solid #ef4444; background: #fffafb; }}
        .action-card.prio-med {{ border-left: 4.5px solid #f59e0b; background: #fffdfa; }}
        .action-card.prio-low {{ border-left: 4.5px solid #0284c7; background: #f8fafc; }}
        .action-prio-badge {{ font-weight: 800; font-size: 0.85em; }}
        .prio-high .action-prio-badge {{ color: #ef4444; }}
        .prio-med .action-prio-badge {{ color: #f59e0b; }}
        .prio-low .action-prio-badge {{ color: #0284c7; }}
        .action-desc {{ font-size: 0.86em; font-weight: 600; color: #0f172a; margin-bottom: 4px; }}
        .action-meta {{ font-size: 0.76em; color: var(--text-muted); display: flex; gap: 16px; }}
        .action-meta strong {{ color: #334155; }}

        /* ASSINATURAS E RODAPÉ */
        .audit-sign-section {{
            margin-top: 28px;
            padding-top: 18px;
            border-top: 1px solid #cbd5e1;
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        .audit-sign-disclaimer {{ font-size: 0.76em; color: var(--text-muted); line-height: 1.45; margin-bottom: 18px; text-align: justify; }}
        .signatures-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 36px; margin-top: 18px; }}
        .sig-box {{ text-align: center; }}
        .sig-line {{ height: 38px; border-bottom: 1.5px solid #64748b; margin-bottom: 6px; }}
        .sig-name {{ font-weight: 700; font-size: 0.84em; color: #0f172a; }}
        .sig-role {{ font-size: 0.74em; color: var(--text-muted); }}

        .report-footer {{
            margin-top: 26px;
            padding-top: 14px;
            border-top: 1px solid #e2e8f0;
            display: flex;
            justify-content: space-between;
            font-size: 0.72em;
            color: var(--text-muted);
        }}
        .audit-hash-badge {{ font-family: 'JetBrains Mono', monospace; font-weight: 600; color: #0284c7; }}

        /* ESTILOS DE IMPRESSÃO A4 */
        @media print {{
            @page {{
                size: A4 portrait;
                margin: 10mm 12mm 12mm 12mm;
            }}
            body {{
                background-color: #ffffff !important;
                padding: 0 !important;
                color: #0f172a !important;
            }}
            .report-actions-bar {{ display: none !important; }}
            .report-sheet {{
                max-width: 100% !important;
                padding: 0 !important;
                box-shadow: none !important;
                border-radius: 0 !important;
            }}
            .table-container {{ overflow: visible !important; border: 1px solid #cbd5e1 !important; }}
            .flagship-table tr {{ break-inside: avoid; page-break-inside: avoid; }}
            .flagship-table thead {{ display: table-header-group !important; }}
            .analytic-section, .score-spotlight-card, .delta-box, .audit-sign-section {{
                break-inside: avoid;
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <aside class="report-actions-bar">
        <div class="info">
            <i class="fas fa-file-shield" style="color:#38bdf8;font-size:1.2em"></i>
            <span>Visualizador Corporativo <strong>{report_data['report_id']}</strong> • v14.8.1</span>
        </div>
        <div class="action-btns">
            <button onclick="window.print()" class="btn-action"><i class="fas fa-print"></i> Imprimir / Gerar PDF (A4)</button>
            <a href="?format=csv" class="btn-action secondary"><i class="fas fa-file-csv"></i> Exportar CSV</a>
            <a href="?format=json" class="btn-action secondary"><i class="fas fa-code"></i> API JSON</a>
        </div>
    </aside>

    <main class="report-sheet">
        <header class="report-header">
            <div class="brand-block">
                <svg width="42" height="42" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect width="48" height="48" rx="10" fill="#0284C7"/>
                    <path d="M24 10L36 16V25C36 32.5 30.9 39.5 24 41C17.1 39.5 12 32.5 12 25V16L24 10Z" stroke="white" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M20 24L23 27L29 21" stroke="#38BDF8" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <div class="brand-text">
                    <h2>GBOC OPERATIONS CENTER</h2>
                    <p>Enterprise Backup, RMM & Disaster Recovery</p>
                </div>
            </div>
            <div style="text-align:right">
                <span class="badge-classification">DOCUMENTO OFICIAL AUDITADO</span>
                <div style="font-size:0.75em;color:var(--text-muted);font-family:'JetBrains Mono',monospace;margin-top:4px">REF: {report_data['report_id']} • {report_data['platform']}</div>
            </div>
        </header>

        <section class="report-title-banner">
            <h1>{report_data['report_name']}</h1>
            <p class="desc">{report_data['objective']}</p>
        </section>

        <section class="report-meta-grid">
            <div class="meta-item">
                <div class="label">Código Oficial</div>
                <div class="val">{report_data['report_id']}</div>
            </div>
            <div class="meta-item">
                <div class="label">Período Auditado</div>
                <div class="val">{report_data['period_label']}</div>
            </div>
            <div class="meta-item">
                <div class="label">Data de Emissão</div>
                <div class="val">{report_data['generated_at']}</div>
            </div>
            <div class="meta-item">
                <div class="label">Público-Alvo</div>
                <div class="val">{report_data['target_audience']}</div>
            </div>
        </section>

        <!-- SCORE PRINCIPAL COM DESTAQUE VISUAL -->
        <section class="score-spotlight-card">
            <div class="score-display-box">
                <div class="score-title-sub">{report_data['score_title']}</div>
                <div class="score-number">{score_val} <small>/ 100</small></div>
                <div class="score-delta-tag">{report_data['score_delta']}</div>
            </div>
            <div class="score-composition-box">
                {comp_html}
            </div>
        </section>

        <!-- DELTA: O QUE MUDOU NESTE PERÍODO -->
        <section class="delta-box">
            <div class="delta-header"><i class="fas fa-arrow-trend-up" style="color:var(--primary)"></i> O que mudou neste período (Análise Comparativa)</div>
            {delta_html}
        </section>

        <!-- KPI CARDS HORIZONTAIS COM BENCHMARK -->
        <section class="kpis-row">
            {kpis_html}
        </section>

        <!-- CORPO ANALÍTICO -->
        {sections_html}

        <!-- AÇÕES RECOMENDADAS OBRIGATÓRIAS -->
        <section class="actions-section">
            <h3 class="section-title"><i class="fas fa-list-check" style="color:var(--primary)"></i> Ações Recomendadas com Priorização (IA & Engenharia)</h3>
            {actions_html}
        </section>

        <!-- RESPONSABILIDADE TÉCNICA E ASSINATURAS -->
        <section class="audit-sign-section">
            <p class="audit-sign-disclaimer">
                <strong>Declaração de Integridade dos Dados:</strong> {report_data['methodology']} A autenticidade matemática deste relatório pode ser comprovada através do cálculo de soma criptográfica do documento gerado contra a chave SHA-256 informada.
            </p>
            <div class="signatures-grid">
                <div class="sig-box">
                    <div class="sig-line"></div>
                    <div class="sig-name">Engenharia de Infraestrutura & Backup</div>
                    <div class="sig-role">Operações de TI • GBOC Enterprise</div>
                </div>
                <div class="sig-box">
                    <div class="sig-line"></div>
                    <div class="sig-name">Auditoria de Segurança & Riscos</div>
                    <div class="sig-role">Governança, Riscos & Compliance (GRC)</div>
                </div>
            </div>
        </section>

        <footer class="report-footer">
            <span>GBOC System v{SERVER_VERSION} Enterprise Edition — Schema v2.0.0.</span>
            <span>Hash SHA-256: <span class="audit-hash-badge">{audit_hash_short}</span></span>
        </footer>
    </main>

    <script>
        window.addEventListener('DOMContentLoaded', () => {{
            if (window.location.search.includes('print=1')) {{
                setTimeout(() => {{ window.print(); }}, 300);
            }}
        }});
    </script>
</body>
</html>
"""
    return html


# ─── RENDERIZADOR CSV PARA OS 7 FLAGSHIPS ─────────────────────────────────────
def render_flagship_csv(report_data: Dict[str, Any]) -> str:
    """Exporta o relatório Flagship v2.0 em formato tabular CSV estruturado."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["GBOC System v14.8.1 Enterprise - Relatório Flagship Executivo"])
    writer.writerow(["Código", report_data.get("report_id")])
    writer.writerow(["Nome", report_data.get("report_name")])
    writer.writerow(["Categoria", report_data.get("category")])
    writer.writerow(["Período", report_data.get("period_label")])
    writer.writerow(["Gerado em", report_data.get("generated_at")])
    writer.writerow(["Score", f"{report_data.get('score_value')}/100", report_data.get("score_delta")])
    writer.writerow([])

    writer.writerow(["--- DELTA: O QUE MUDOU ---"])
    for d in report_data.get("delta", []):
        writer.writerow([d.get("type"), d.get("text")])
    writer.writerow([])

    writer.writerow(["--- KPI CARDS ---"])
    writer.writerow(["Métrica", "Valor", "Meta / Benchmark", "Status"])
    for k in report_data.get("kpi_cards", []):
        writer.writerow([k.get("label"), k.get("value"), k.get("target"), k.get("status")])
    writer.writerow([])

    for s in report_data.get("sections", []):
        writer.writerow([f"--- SEÇÃO: {s.get('title')} ---"])
        writer.writerow(["Narrativa", re.sub(r"<[^>]+>", "", str(s.get("narrative") or ""))])
        if s.get("table_headers"):
            writer.writerow(s.get("table_headers"))
            for r in s.get("table_rows", []):
                writer.writerow(r)
        writer.writerow(["Análise", html_lib.unescape(re.sub(r"<[^>]+>", "", str(s.get("ai_inline") or "")))])
        writer.writerow([])

    writer.writerow(["--- AÇÕES RECOMENDADAS ---"])
    writer.writerow(["Prioridade", "Ação", "Responsável", "Prazo"])
    for a in report_data.get("recommended_actions", []):
        writer.writerow([a.get("priority"), a.get("action"), a.get("owner"), a.get("deadline")])

    writer.writerow([])
    writer.writerow(["Hash Integridade SHA-256", report_data.get("integrity_hash")])

    return output.getvalue()
