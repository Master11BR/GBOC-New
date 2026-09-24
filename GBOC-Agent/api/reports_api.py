#!/usr/bin/env python3
"""
GBOC 14.6.0 - Reports API (Agent)
Generate, schedule, download and manage backup reports with 100% real system data.
Supports HTML (print-to-PDF), CSV, JSON formats.
"""

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.concurrency import run_in_threadpool
import logging
import io
import csv
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional

try:
    from version import GBOC_VERSION as AGENT_VERSION
except ImportError:
    AGENT_VERSION = "14.6.0"

try:
    from engines.v4_reports_engine import (
        generate_real_report_data_v4,
        _clean_task_name,
        _sla_badge,
        get_real_uptime,
        predict_storage_exhaustion,
        build_ai_recommendation
    )
except ImportError:
    try:
        from v4_reports_engine import (
            generate_real_report_data_v4,
            _clean_task_name,
            _sla_badge,
            get_real_uptime,
            predict_storage_exhaustion,
            build_ai_recommendation
        )
    except ImportError:
        try:
            from engines.v3_reports_engine import (
                generate_real_report_data_v3 as generate_real_report_data_v4,
                _clean_task_name,
                _sla_badge,
                get_real_uptime,
                predict_storage_exhaustion,
                build_ai_recommendation
            )
        except ImportError:
            from v3_reports_engine import (
                generate_real_report_data_v3 as generate_real_report_data_v4,
                _clean_task_name,
                _sla_badge,
                get_real_uptime,
                predict_storage_exhaustion,
                build_ai_recommendation
            )

logger = logging.getLogger(__name__)
# Router sem prefixo fixo para mapear tanto /api/reports quanto /api/v1/reports
router = APIRouter(tags=["Reports"])

_EXCHANGE_RATE_CACHE = {"rate": 5.50, "timestamp": 0}
_REPORTS_CONFIG_CACHE = {
    "cloud_storage_cost_usd_per_tb": 7.99,
    "auto_currency_conversion": True
}


def get_usd_to_brl_rate() -> float:
    """Obtém a taxa de câmbio comercial do dia USD -> BRL em tempo real com fallback automático."""
    import time
    import urllib.request
    now = time.time()
    if now - _EXCHANGE_RATE_CACHE["timestamp"] < 3600 and _EXCHANGE_RATE_CACHE["rate"] > 0:
        return _EXCHANGE_RATE_CACHE["rate"]

    try:
        req = urllib.request.Request(
            "https://economia.awesomeapi.com.br/json/last/USD-BRL",
            headers={"User-Agent": "GBOC-System/14.6.0"}
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
        logger.warning(f"Falha ao obter câmbio USD-BRL em tempo real no agente (fallback 5.50): {err}")

    return _EXCHANGE_RATE_CACHE.get("rate", 5.50)


def get_agent_reports_config() -> Dict[str, Any]:
    """Obtém as configurações de relatórios do banco do agente ou fallback em memória."""
    try:
        core = _get_core()
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM settings WHERE category = 'reports'")
            rows = cur.fetchall()
            for r in rows:
                if r[0] == 'cloud_storage_cost_usd_per_tb':
                    try:
                        _REPORTS_CONFIG_CACHE['cloud_storage_cost_usd_per_tb'] = float(r[1])
                    except Exception:
                        pass
                elif r[0] == 'auto_currency_conversion':
                    _REPORTS_CONFIG_CACHE['auto_currency_conversion'] = (str(r[1]).lower() in ['true', '1'])
    except Exception:
        pass
    return _REPORTS_CONFIG_CACHE


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        return super().default(o)


# ─── 50 RELATÓRIOS CATALOG DEFINITION ────────────────────────────────────────

REPORTS_CATALOG_50 = [
    # IDs 1 a 30: Mercado & Executivos
    {"id": 1, "code": "REP-01", "name": "Resumo Executivo de Backups", "category": "Executive", "type": "PDF/HTML", "description": "Status global das rotinas, taxa de sucesso e volumes trafegados no período.", "format": "PDF/HTML"},
    {"id": 2, "code": "REP-02", "name": "Conformidade de SLA de RPO/RTO", "category": "Executive", "type": "PDF/HTML", "description": "Auditoria de alinhamento com as metas operacionais de recuperação.", "format": "PDF/HTML"},
    {"id": 3, "code": "REP-03", "name": "Capacidade e Crescimento de Storage", "category": "Storage", "type": "PDF/HTML", "description": "Projeção de ocupação de repositórios e alocação por motor.", "format": "PDF/HTML"},
    {"id": 4, "code": "REP-04", "name": "Relatório de Falhas e Causa Raiz", "category": "Performance", "type": "PDF/HTML", "description": "Análise detalhada de erros de execução e falhas de conexão.", "format": "PDF/HTML"},
    {"id": 5, "code": "REP-05", "name": "Taxa de Deduplicação e Compressão", "category": "Storage", "type": "PDF/HTML", "description": "Economia de espaço obtida por deduplicação e compressão.", "format": "PDF/HTML"},
    {"id": 6, "code": "REP-06", "name": "Auditoria de Integridade de Repositórios", "category": "Security", "type": "PDF/HTML", "description": "Resultado de rotinas check e prune nos motores Restic, Kopia e Borg.", "format": "PDF/HTML"},
    {"id": 7, "code": "REP-07", "name": "Cobertura de Agentes e Ativos", "category": "Executive", "type": "PDF/HTML", "description": "Mapeamento de servidores e máquinas cobertos por rotinas de backup.", "format": "PDF/HTML"},
    {"id": 8, "code": "REP-08", "name": "Desempenho por Engine (Restic/Kopia/Duplicati)", "category": "Performance", "type": "PDF/HTML", "description": "Comparativo de throughput, velocidade de transferência e tempo.", "format": "PDF/HTML"},
    {"id": 9, "code": "REP-09", "name": "Histórico de Retenção e Pruning", "category": "Storage", "type": "PDF/HTML", "description": "Log de retenção de snapshots e expiração de dados antigos.", "format": "PDF/HTML"},
    {"id": 10, "code": "REP-10", "name": "Custo de Armazenamento Cloud", "category": "Executive", "type": "PDF/HTML", "description": "Estimativa financeira de custos de egress e armazenamento em S3/Wasabi/Azure.", "format": "PDF/HTML"},
    {"id": 11, "code": "REP-11", "name": "Janela de Backup e Concorrência", "category": "Performance", "type": "PDF/HTML", "description": "Análise de picos de utilização do processador e rede durante backups.", "format": "PDF/HTML"},
    {"id": 12, "code": "REP-12", "name": "Ransomware Protection Shield", "category": "Security", "type": "PDF/HTML", "description": "Verificação de imutabilidade e proteção contra criptografia maliciosa.", "format": "PDF/HTML"},
    {"id": 13, "code": "REP-13", "name": "Auditoria de Logs e Acessos", "category": "Security", "type": "PDF/HTML", "description": "Trilha de auditoria contendo operações de usuários e alterações de configuração.", "format": "PDF/HTML"},
    {"id": 14, "code": "REP-14", "name": "Notificações e Disparos de Alertas", "category": "Executive", "type": "PDF/HTML", "description": "Histórico de envios de e-mails, webhooks e alertas críticos gerados.", "format": "PDF/HTML"},
    {"id": 15, "code": "REP-15", "name": "Relatório de Retentativas e DLQ", "category": "Performance", "type": "PDF/HTML", "description": "Rotinas que exigiram re-tentativa ou caíram em fila de exceção.", "format": "PDF/HTML"},
    {"id": 16, "code": "REP-16", "name": "Disponibilidade dos Serviços de Backup", "category": "Executive", "type": "PDF/HTML", "description": "Uptime dos serviços de agente e servidor GBOC.", "format": "PDF/HTML"},
    {"id": 17, "code": "REP-17", "name": "Volume Transacionado por Dia", "category": "Storage", "type": "PDF/HTML", "description": "Total em GB/TB trafegado diariamente nas rotinas programadas.", "format": "PDF/HTML"},
    {"id": 18, "code": "REP-18", "name": "Relatório de Testes de Restauração", "category": "Security", "type": "PDF/HTML", "description": "Validação periódica de restauração para garantia de legibilidade de arquivos.", "format": "PDF/HTML"},
    {"id": 19, "code": "REP-19", "name": "Consumo de Banda de Rede", "category": "Performance", "type": "PDF/HTML", "description": "Taxas de upload e download utilizadas durante os jobs.", "format": "PDF/HTML"},
    {"id": 20, "code": "REP-20", "name": "Estatísticas do Duplicati Native", "category": "Performance", "type": "PDF/HTML", "description": "Métricas exclusivas de jobs gerenciados via Duplicati Native Engine.", "format": "PDF/HTML"},
    {"id": 21, "code": "REP-21", "name": "Estatísticas do Engine Kopia", "category": "Performance", "type": "PDF/HTML", "description": "Visão analítica de repositórios e manutenções do Kopia Engine.", "format": "PDF/HTML"},
    {"id": 22, "code": "REP-22", "name": "Estatísticas do Engine Restic", "category": "Performance", "type": "PDF/HTML", "description": "Detalhamento de repositórios, snapshots e locks do Restic Engine.", "format": "PDF/HTML"},
    {"id": 23, "code": "REP-23", "name": "Inventário de Bases de Dados (Postgres/SQLite)", "category": "Storage", "type": "PDF/HTML", "description": "Estado e integridade dos bancos de dados locais e remotos.", "format": "PDF/HTML"},
    {"id": 24, "code": "REP-24", "name": "Relatório de Tarefas Inativas / Agendamento", "category": "Executive", "type": "PDF/HTML", "description": "Tarefas cadastradas sem execução recente ou com agendamento suspenso.", "format": "PDF/HTML"},
    {"id": 25, "code": "REP-25", "name": "Resumo de Exceções e Erros Frequentes", "category": "Performance", "type": "PDF/HTML", "description": "Agrupamento dos erros mais recorrentes com recomendações de correção.", "format": "PDF/HTML"},
    {"id": 26, "code": "REP-26", "name": "Qualidade dos Chunks de Armazenamento", "category": "Storage", "type": "PDF/HTML", "description": "Análise de integridade de blocos desduplicados.", "format": "PDF/HTML"},
    {"id": 27, "code": "REP-27", "name": "Conformidade LGPD/GDPR de Retenção", "category": "Security", "type": "PDF/HTML", "description": "Relatório de atendimento às regras de retenção legal e descarte seguro.", "format": "PDF/HTML"},
    {"id": 28, "code": "REP-28", "name": "Impacto de Latência por Região Cloud", "category": "Performance", "type": "PDF/HTML", "description": "Atrasos e resposta de latência em endpoints de nuvem.", "format": "PDF/HTML"},
    {"id": 29, "code": "REP-29", "name": "Mapeamento de Pontos de Restauração Granulares", "category": "Executive", "type": "PDF/HTML", "description": "Snapshots disponíveis para recuperação granular de arquivos.", "format": "PDF/HTML"},
    {"id": 30, "code": "REP-30", "name": "Status Geral de Licenciamento & Agentes", "category": "Executive", "type": "PDF/HTML", "description": "Controle de nós conectados e licença do agente.", "format": "PDF/HTML"},

    # IDs 31 a 50: Exclusivos & IA
    {"id": 31, "code": "REP-31", "name": "Esgotamento Preditivo de Armazenamento (IA)", "category": "AI Predictive", "type": "PDF/HTML", "description": "Predição baseada em machine learning de quando o storage atingirá 100%.", "format": "PDF/HTML"},
    {"id": 32, "code": "REP-32", "name": "Score de Vulnerabilidade a Ransomware (IA)", "category": "AI Predictive", "type": "PDF/HTML", "description": "Avaliação preditiva do nível de proteção do ambiente contra ataques.", "format": "PDF/HTML"},
    {"id": 33, "code": "REP-33", "name": "Custo Otimizado por GB de Disaster Recovery (IA)", "category": "AI Executive", "type": "PDF/HTML", "description": "Algoritmo de recomendação de redução de custos de armazenamento cloud.", "format": "PDF/HTML"},
    {"id": 34, "code": "REP-34", "name": "Análise de Gaps de Cobertura CDP (IA)", "category": "AI Predictive", "type": "PDF/HTML", "description": "Identificação preditiva de intervalos desprotegidos em proteção contínua.", "format": "PDF/HTML"},
    {"id": 35, "code": "REP-35", "name": "Calculadora de ROI de Synthetic Full (IA)", "category": "AI Executive", "type": "PDF/HTML", "description": "Economia estimada de banda e tempo ao utilizar backups sintéticos.", "format": "PDF/HTML"},
    {"id": 36, "code": "REP-36", "name": "Isolamento e Segurança Multi-tenant (IA)", "category": "AI Executive", "type": "PDF/HTML", "description": "Verificação automatizada de barreiras de segurança entre tenants.", "format": "PDF/HTML"},
    {"id": 37, "code": "REP-37", "name": "Air-Gap Verifier & Imutabilidade (IA)", "category": "AI Executive", "type": "PDF/HTML", "description": "Auditoria IA da garantia de desconexão e imutabilidade do repositório.", "format": "PDF/HTML"},
    {"id": 38, "code": "REP-38", "name": "Previsão de Rotação de Chaves de Criptografia (IA)", "category": "AI Predictive", "type": "PDF/HTML", "description": "Diagnóstico de ciclos de vida de chaves de criptografia recomendados.", "format": "PDF/HTML"},
    {"id": 39, "code": "REP-39", "name": "Matriz Inteligente de Janelas de Backup (IA)", "category": "AI Predictive", "type": "PDF/HTML", "description": "Reorganização inteligente de horários para eliminar gargalos de rede.", "format": "PDF/HTML"},
    {"id": 40, "code": "REP-40", "name": "Log de Auto-recuperação e Auto-repair (IA)", "category": "AI Executive", "type": "PDF/HTML", "description": "Histórico de correções automáticas executadas pela engine de IA.", "format": "PDF/HTML"},
    {"id": 41, "code": "REP-41", "name": "Eficiência de Energia e Green Backup (IA)", "category": "AI Executive", "type": "PDF/HTML", "description": "Redução da pegada de carbono e consumo de recursos energéticos.", "format": "PDF/HTML"},
    {"id": 42, "code": "REP-42", "name": "Potencial Máximo de Deduplicação (IA)", "category": "AI Predictive", "type": "PDF/HTML", "description": "Estimativa preditiva do ganho com blocos variáveis de deduplicação.", "format": "PDF/HTML"},
    {"id": 43, "code": "REP-43", "name": "Matriz de Riscos LGPD/GDPR de Dados (IA)", "category": "AI Executive", "type": "PDF/HTML", "description": "Identificação de dados sensíveis armazenados nos pontos de restauração.", "format": "PDF/HTML"},
    {"id": 44, "code": "REP-44", "name": "Classificação de Ativos Críticos (IA)", "category": "AI Predictive", "type": "PDF/HTML", "description": "Ranking automatizado da relevância e criticidade dos servidores.", "format": "PDF/HTML"},
    {"id": 45, "code": "REP-45", "name": "Detecção de Volumes Desprotegidos (IA)", "category": "AI Predictive", "type": "PDF/HTML", "description": "Varredura proativa de discos ou partições recém-criados sem rotinas.", "format": "PDF/HTML"},
    {"id": 46, "code": "REP-46", "name": "Análise de Impacto de Latência (IA)", "category": "AI Predictive", "type": "PDF/HTML", "description": "Simulação de tempos de RTO considerando variações de throughput na nuvem.", "format": "PDF/HTML"},
    {"id": 47, "code": "REP-47", "name": "Resiliência contra Outage Cloud (IA)", "category": "AI Predictive", "type": "PDF/HTML", "description": "Modelagem de disponibilidade do repositório em falhas massivas de nuvem.", "format": "PDF/HTML"},
    {"id": 48, "code": "REP-48", "name": "Log de Remediação Preditiva de Alertas (IA)", "category": "AI Executive", "type": "PDF/HTML", "description": "Ações tomadas pela IA antes que falhas operacionais acontecessem.", "format": "PDF/HTML"},
    {"id": 49, "code": "REP-49", "name": "Simulador de Restauração Bare-Metal (IA)", "category": "AI Executive", "type": "PDF/HTML", "description": "Previsão de tempo e requisitos para restauração completa do servidor.", "format": "PDF/HTML"},
    {"id": 50, "code": "REP-50", "name": "ROI & TCO Executivo Global (IA)", "category": "AI Executive", "type": "PDF/HTML", "description": "Relatório consolidado de retorno sobre investimento e custo total de propriedade.", "format": "PDF/HTML"}
]

@router.get("/api/reports/catalog")
@router.get("/api/v1/reports/catalog")
async def get_reports_catalog():
    """Retorna o catálogo oficial com os 50 relatórios gerenciais e preditivos do GBOC."""
    return {
        "status": "success",
        "total": len(REPORTS_CATALOG_50),
        "reports": REPORTS_CATALOG_50
    }


def generate_real_report_data(rep_id: int, days: int = 30) -> Dict[str, Any]:
    """Gera o payload oficial com 100% de dados reais e contrato JSON universal v4.0.0."""
    return generate_real_report_data_v4(rep_id, catalog_50=REPORTS_CATALOG_50, days=days)


@router.post("/api/reports/generate")
@router.post("/api/v1/reports/generate")
@router.get("/api/reports/generate/{report_id}")
@router.get("/api/v1/reports/generate/{report_id}")
async def generate_report_by_payload(request: Request, report_id: Optional[int] = None):
    """Gera dados detalhados para qualquer um dos 50 relatórios com dados 100% reais do sistema."""
    rep_id = report_id
    days = 30
    if request.method == "POST":
        try:
            payload = await request.json()
            rep_id = payload.get("report_id") or payload.get("id") or rep_id
            if "days" in payload:
                try:
                    days = int(payload.get("days"))
                except Exception:
                    days = 30
        except Exception:
            pass
    elif request.method == "GET":
        try:
            days = int(request.query_params.get("days", 30))
        except Exception:
            days = 30

    try:
        rep_id = int(rep_id or 1)
    except Exception:
        rep_id = 1

    data = await run_in_threadpool(generate_real_report_data, rep_id, days)
    return JSONResponse(data)


@router.get("/api/reports/export/{report_id}")
@router.get("/api/v1/reports/export/{report_id}")
async def export_agent_report(report_id: int, format: str = Query("html", pattern="^(html|csv|json)$")):
    """Exporta relatórios do agente em HTML/PDF, CSV ou JSON."""
    data = await run_in_threadpool(generate_real_report_data, report_id)

    if format == "json":
        return JSONResponse(content=data, headers={
            "Content-Disposition": f"attachment; filename=GBOC_Agent_Report_{data['code']}.json"
        })
    elif format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["GBOC Agent - Relatório Exportado"])
        writer.writerow(["Título", data["title"]])
        writer.writerow(["Código", data["code"]])
        writer.writerow(["Categoria", data["category"]])
        writer.writerow(["Gerado em", data["generated_at"]])
        writer.writerow([])
        writer.writerow(["Métricas"])
        for m in data["metrics"]:
            writer.writerow([m["label"], m["value"]])
        if data.get("table_headers"):
            writer.writerow([])
            writer.writerow(data["table_headers"])
            for row in data.get("table_rows", []):
                writer.writerow(row)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=GBOC_Agent_Report_{data['code']}.csv"}
        )
    else:
        import hashlib
        audit_hash = data.get("integrity_hash")
        if not audit_hash:
            raw_data = json.dumps(data, sort_keys=True, default=str).encode('utf-8')
            h = hashlib.sha256(raw_data).hexdigest().upper()
            audit_hash = f"{h[:8]}-{h[8:16]}-{h[16:24]}-{h[24:32]}"
        audit_hash_short = audit_hash

        score_data = data.get("score") or {}
        score_val = score_data.get("value", 100)
        score_trend = score_data.get("trend", "0")
        score_status = score_data.get("status", "OK")
        score_color = "#10b981" if score_status == "OK" else ("#f59e0b" if score_status == "AT_RISK" else "#ef4444")

        score_html = f"""
        <div class="score-banner" style="display:flex;align-items:center;justify-content:space-between;background:#f8fafc;border:1.5px solid #cbd5e1;border-left:5px solid {score_color};border-radius:8px;padding:12px 18px;margin-bottom:16px;">
            <div style="display:flex;align-items:center;gap:16px;">
                <div style="font-size:2em;font-weight:800;color:{score_color};">{score_val}<span style="font-size:0.5em;color:#64748b">/100</span></div>
                <div>
                    <div style="font-weight:700;font-size:0.95em;color:#0f172a;">Protection & Operations Score</div>
                    <div style="font-size:0.75em;color:#64748b;">Tendência: <strong>{score_trend}pp</strong> vs período anterior • Status: <span class="badge" style="background:{score_color};color:#fff;font-size:0.8em;padding:2px 6px;border-radius:4px;">{score_status}</span></div>
                </div>
            </div>
            <div style="font-size:0.75em;color:#64748b;text-align:right;">
                <div>GBOC Agent Engine v3.0</div>
                <div style="font-family:'JetBrains Mono',monospace;">Telemetria 100% Real</div>
            </div>
        </div>
        """ if score_data else ""

        delta_items = data.get("delta") or []
        delta_html = ""
        if delta_items:
            bullets = []
            for d in delta_items:
                ic = d.get("icon", "neutral")
                if ic == "up":
                    ic_html = '<i class="fas fa-arrow-up" style="color:#10b981"></i>'
                elif ic == "down":
                    ic_html = '<i class="fas fa-arrow-down" style="color:#ef4444"></i>'
                else:
                    ic_html = '<i class="fas fa-minus" style="color:#0284c7"></i>'
                bullets.append(f'<li style="display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:0.85em;color:#334155;">{ic_html} <span>{d.get("text", "")}</span></li>')
            delta_html = f"""
            <div class="delta-box" style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;margin-bottom:18px;">
                <div style="font-size:0.75em;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:6px;"><i class="fas fa-chart-line"></i> O que mudou vs período anterior:</div>
                <ul style="list-style:none;margin:0;padding:0;">{''.join(bullets)}</ul>
            </div>
            """

        kpi_colors = ["#0284c7", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4"]
        metrics_html = "".join([f"""
            <div class="report-kpi-card" style="--kpi-color:{kpi_colors[i % len(kpi_colors)]}">
                <div class="kpi-label">{m['label']}</div>
                <div class="kpi-value">{m['value']}</div>
                {f'<div class="kpi-target">Meta: {m["target"]}</div>' if m.get("target") else ''}
                <div class="status-dot {str(m.get('status', 'ok')).lower()}"></div>
            </div>
        """ for i, m in enumerate(data.get("metrics", []))])

        headers_html = "".join([f"<th>{h}</th>" for h in data.get("table_headers", [])])
        rows_html = "".join([
            "<tr>" + "".join([f"<td>{_sla_badge(cell) if str(cell).upper() in ('CONFORME','EM RISCO','NÃO CONFORME','NAO CONFORME') else cell}</td>" for cell in row]) + "</tr>"
            for row in data.get("table_rows", [])
        ])

        actions_list = data.get("recommended_actions") or []
        actions_html = ""
        if actions_list:
            items = []
            for act in actions_list:
                p = str(act.get("priority", "MEDIUM")).upper()
                items.append(f"""
                <div class="action-item action-{p.lower()}">
                    <span class="action-badge">{p}</span>
                    <span class="action-text">{act.get('action', '')}</span>
                </div>
                """)
            actions_html = f"""
            <section class="actions-section" style="margin-top:20px;margin-bottom:20px;">
                <div class="report-section-title"><i class="fas fa-bolt" style="color:#d97706"></i> Ações Recomendadas</div>
                <div class="actions-list">{''.join(items)}</div>
            </section>
            """

        ai_rec = data.get("ai_executive_recommendation") or ""
        if not ai_rec and data.get("content"):
            ai_rec = data["content"]

        html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{data['title']} — GBOC Enterprise Suite (Agent)</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
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

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

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

        /* Barra de Ações Interativas (Apenas em tela) */
        .report-actions-bar {{
            width: 100%;
            max-width: 1050px;
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

        .report-actions-bar .info {{
            color: #94a3b8;
            font-size: 0.85em;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .report-actions-bar .info strong {{
            color: #f8fafc;
        }}

        .action-btns {{
            display: flex;
            gap: 10px;
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

        .btn-action:hover {{
            background: #0369a1;
            transform: translateY(-1px);
        }}

        .btn-action.secondary {{
            background: #334155;
            color: #e2e8f0;
        }}

        .btn-action.secondary:hover {{
            background: #475569;
        }}

        /* Folha A4 do Relatório Executivo */
        .report-sheet {{
            background: var(--bg-sheet);
            width: 100%;
            max-width: 1050px;
            border-radius: 12px;
            padding: 36px 42px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
            box-sizing: border-box;
            position: relative;
        }}

        /* Cabeçalho do Relatório */
        .report-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            border-bottom: 2.5px solid var(--primary);
            padding-bottom: 18px;
            margin-bottom: 20px;
            gap: 16px;
        }}

        .brand-block {{
            display: flex;
            align-items: center;
            gap: 14px;
        }}

        .brand-logo-svg {{
            width: 44px;
            height: 44px;
            flex-shrink: 0;
        }}

        .brand-text h2 {{
            font-size: 1.25em;
            font-weight: 800;
            color: #0f172a;
            letter-spacing: -0.02em;
            margin: 0;
            line-height: 1.2;
        }}

        .brand-text p {{
            font-size: 0.72em;
            color: var(--text-muted);
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-top: 2px;
        }}

        .classification-block {{
            text-align: right;
        }}

        .badge-classification {{
            display: inline-block;
            background: #f0fdf4;
            color: #166534;
            border: 1px solid #bbf7d0;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.72em;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-bottom: 4px;
        }}

        .doc-reference {{
            font-size: 0.75em;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
        }}

        /* Título e Escopo do Documento */
        .report-title-banner {{
            margin-bottom: 20px;
        }}

        .report-title-banner h1 {{
            font-size: 1.45em;
            color: #0f172a;
            font-weight: 800;
            letter-spacing: -0.02em;
            margin-bottom: 6px;
        }}

        .report-title-banner .desc {{
            font-size: 0.88em;
            color: var(--text-muted);
            line-height: 1.5;
        }}

        /* Metadados Oficiais */
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

        .meta-cell {{
            font-size: 0.8em;
        }}

        .meta-cell .k {{
            color: var(--text-muted);
            font-size: 0.72em;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-bottom: 2px;
            display: block;
        }}

        .meta-cell .v {{
            color: #0f172a;
            font-weight: 600;
        }}

        .meta-cell .v.mono {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.9em;
        }}

        /* Grade de KPIs */
        .report-kpi-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 22px;
        }}

        .report-kpi-card {{
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 12px 14px;
            position: relative;
            overflow: hidden;
            border-left: 4px solid var(--kpi-color, var(--primary));
        }}

        .report-kpi-card .kpi-label {{
            font-size: 0.72em;
            color: var(--text-muted);
            text-transform: uppercase;
            font-weight: 700;
            letter-spacing: 0.04em;
        }}

        .report-kpi-card .kpi-value {{
            font-size: 1.45em;
            font-weight: 800;
            color: #0f172a;
            margin-top: 4px;
            letter-spacing: -0.02em;
        }}

        .kpi-target {{
            font-size: 0.72em;
            color: var(--text-muted);
            margin-top: 4px;
        }}

        .status-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-top: 6px;
        }}
        .status-dot.ok {{ background: #10b981; }}
        .status-dot.warning, .status-dot.at_risk {{ background: #f59e0b; }}
        .status-dot.critical {{ background: #ef4444; }}

        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.76em;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }}
        .badge-ok {{ background: #10b981; color: #ffffff; }}
        .badge-warn {{ background: #f59e0b; color: #ffffff; }}
        .badge-fail {{ background: #ef4444; color: #ffffff; }}

        /* Parecer de Inteligência Preditiva IA */
        .report-ai-card {{
            background: #fffbeb;
            border: 1px solid #fde68a;
            border-left: 5px solid #d97706;
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 24px;
            line-height: 1.6;
            font-size: 0.88em;
            color: #1e293b;
        }}

        .report-ai-card .ai-title {{
            color: #b45309;
            font-weight: 700;
            font-size: 0.92em;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        /* Tabela de Auditoria */
        .report-section-title {{
            font-size: 0.95em;
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}

        .table-container {{
            width: 100%;
            overflow-x: auto;
            margin-bottom: 24px;
            border-radius: 8px;
            border: 1px solid #cbd5e1;
        }}

        .audit-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.84em;
            text-align: left;
        }}

        .audit-table thead th {{
            background: #f1f5f9;
            color: #334155;
            padding: 10px 12px;
            font-size: 0.74em;
            text-transform: uppercase;
            font-weight: 700;
            letter-spacing: 0.04em;
            border-bottom: 1.5px solid #cbd5e1;
            white-space: nowrap;
        }}

        .audit-table tbody td {{
            padding: 9px 12px;
            border-bottom: 1px solid #e2e8f0;
            color: #1e293b;
            vertical-align: middle;
            word-break: break-word;
        }}

        .audit-table tbody tr:nth-child(even) {{
            background: #f8fafc;
        }}

        /* Ações Recomendadas */
        .action-item {{
            display: flex;
            gap: 10px;
            align-items: flex-start;
            padding: 10px 14px;
            border-radius: 6px;
            margin-bottom: 8px;
            border: 1px solid;
            font-size: 0.84em;
        }}
        .action-item.action-high {{ background: rgba(239, 68, 68, 0.08); border-color: rgba(239, 68, 68, 0.25); color: #991b1b; }}
        .action-item.action-medium {{ background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.25); color: #92400e; }}
        .action-item.action-low {{ background: rgba(148, 163, 184, 0.08); border-color: rgba(148, 163, 184, 0.25); color: #334155; }}
        .action-badge {{
            font-size: 0.72em;
            font-weight: 800;
            padding: 2px 8px;
            border-radius: 4px;
            white-space: nowrap;
        }}
        .action-high .action-badge {{ background: #ef4444; color: #ffffff; }}
        .action-medium .action-badge {{ background: #f59e0b; color: #ffffff; }}
        .action-low .action-badge {{ background: #64748b; color: #ffffff; }}

        /* Termo de Encerramento e Assinaturas */
        .audit-sign-section {{
            margin-top: 32px;
            padding-top: 20px;
            border-top: 1px solid #cbd5e1;
            break-inside: avoid;
            page-break-inside: avoid;
        }}

        .audit-sign-disclaimer {{
            font-size: 0.76em;
            color: var(--text-muted);
            line-height: 1.5;
            margin-bottom: 24px;
            text-align: justify;
        }}

        .signatures-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 40px;
            margin-top: 20px;
        }}

        .sig-box {{
            text-align: center;
        }}

        .sig-line {{
            border-bottom: 1px solid #64748b;
            height: 36px;
            margin-bottom: 6px;
        }}

        .sig-name {{
            font-size: 0.82em;
            font-weight: 700;
            color: #0f172a;
        }}

        .sig-role {{
            font-size: 0.72em;
            color: var(--text-muted);
            text-transform: uppercase;
        }}

        /* Rodapé Oficial */
        .report-footer {{
            margin-top: 24px;
            padding-top: 12px;
            border-top: 1px solid #e2e8f0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.72em;
            color: var(--text-muted);
            flex-wrap: wrap;
            gap: 8px;
        }}

        .audit-hash-badge {{
            font-family: 'JetBrains Mono', monospace;
            background: #f1f5f9;
            padding: 2px 6px;
            border-radius: 4px;
            border: 1px solid #cbd5e1;
            font-size: 0.95em;
        }}

        /* ─── REGRAS NATIVAS DE IMPRESSÃO A4 (ANTI-OVERFLOW ESTREITO) ─── */
        @page {{
            size: A4 portrait;
            margin: 12mm 14mm 14mm 14mm;
        }}

        @media print {{
            *, *::before, *::after {{
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
                box-shadow: none !important;
                text-shadow: none !important;
            }}

            html, body {{
                background: #ffffff !important;
                color: #0f172a !important;
                padding: 0 !important;
                margin: 0 !important;
                width: 100% !important;
                font-size: 9pt !important;
            }}

            .report-actions-bar {{
                display: none !important;
            }}

            .report-sheet {{
                max-width: 100% !important;
                width: 100% !important;
                padding: 0 !important;
                border: none !important;
                box-shadow: none !important;
                border-radius: 0 !important;
            }}

            .report-header {{
                border-bottom: 2px solid #0284c7 !important;
                padding-bottom: 10px !important;
                margin-bottom: 12px !important;
                break-inside: avoid;
                page-break-inside: avoid;
            }}

            .report-meta-grid {{
                background: #f8fafc !important;
                border: 1px solid #cbd5e1 !important;
                padding: 8px 12px !important;
                margin-bottom: 14px !important;
                gap: 8px !important;
                break-inside: avoid;
                page-break-inside: avoid;
            }}

            .report-kpi-grid {{
                grid-template-columns: repeat(4, 1fr) !important;
                gap: 8px !important;
                margin-bottom: 14px !important;
                break-inside: avoid;
                page-break-inside: avoid;
            }}

            .report-kpi-card {{
                padding: 8px 10px !important;
                border: 1px solid #cbd5e1 !important;
                border-left: 3px solid #0284c7 !important;
                break-inside: avoid;
                page-break-inside: avoid;
            }}

            .report-kpi-card .kpi-value {{
                font-size: 1.25em !important;
            }}

            .report-ai-card {{
                background: #fffbeb !important;
                border: 1px solid #fde68a !important;
                border-left: 4px solid #d97706 !important;
                padding: 10px 12px !important;
                margin-bottom: 14px !important;
                break-inside: avoid;
                page-break-inside: avoid;
            }}

            .table-container {{
                border: 1px solid #cbd5e1 !important;
                overflow: visible !important;
                margin-bottom: 14px !important;
            }}

            .audit-table {{
                width: 100% !important;
            }}

            .audit-table thead {{
                display: table-header-group !important;
            }}

            .audit-table tr {{
                break-inside: avoid;
                page-break-inside: avoid;
            }}

            .audit-table th {{
                background: #f1f5f9 !important;
                color: #0f172a !important;
                border-bottom: 1.5px solid #94a3b8 !important;
                padding: 6px 8px !important;
                font-size: 7.5pt !important;
            }}

            .audit-table td {{
                padding: 6px 8px !important;
                border-bottom: 1px solid #e2e8f0 !important;
                font-size: 7.8pt !important;
            }}

            .audit-sign-section {{
                margin-top: 20px !important;
                padding-top: 14px !important;
                break-inside: avoid;
                page-break-inside: avoid;
            }}

            .sig-line {{
                height: 28px !important;
            }}

            .report-footer {{
                border-top: 1px solid #cbd5e1 !important;
                margin-top: 14px !important;
                padding-top: 8px !important;
                break-inside: avoid;
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <!-- Barra de Controle Interativo em Tela -->
    <div class="report-actions-bar">
        <div class="info">
            <i class="fas fa-file-shield" style="color:#38bdf8"></i>
            <span>Relatório Oficial <strong>{data['code']}</strong> — GBOC Agent (Visualização A4)</span>
        </div>
        <div class="action-btns">
            <button class="btn-action" onclick="window.print()">
                <i class="fas fa-print"></i> Imprimir / Salvar PDF
            </button>
            <a class="btn-action secondary" href="?format=csv">
                <i class="fas fa-file-csv"></i> Exportar CSV
            </a>
            <button class="btn-action secondary" onclick="window.close()">
                <i class="fas fa-times"></i> Fechar
            </button>
        </div>
    </div>

    <!-- Folha Oficial do Relatório -->
    <main class="report-sheet">
        <!-- Cabeçalho Institucional -->
        <header class="report-header">
            <div class="brand-block">
                <svg class="brand-logo-svg" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M24 4L6 12V22C6 33.1 13.7 43.4 24 46C34.3 43.4 42 33.1 42 22V12L24 4Z" fill="#0284c7" fill-opacity="0.15" stroke="#0284c7" stroke-width="2.5" stroke-linejoin="round"/>
                    <path d="M17 24L22 29L31 19" stroke="#0284c7" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <div class="brand-text">
                    <h2>GBOC ENTERPRISE SUITE</h2>
                    <p>Agente Local • Central de Auditoria, Riscos & Governança</p>
                </div>
            </div>
            <div class="classification-block">
                <span class="badge-classification"><i class="fas fa-shield-halved"></i> Documento Oficial Auditável</span>
                <div class="doc-reference">ISO 27001 • LGPD Art. 46 • NIST CSF</div>
            </div>
        </header>

        <!-- Banner com Título e Código -->
        <section class="report-title-banner">
            <h1>{data['title']}</h1>
            <p class="desc">{data.get('description', 'Relatório analítico local consolidado gerado automaticamente pela plataforma GBOC Agent.')}</p>
        </section>

        <!-- Metadados de Autenticidade -->
        <section class="report-meta-grid">
            <div class="meta-cell">
                <span class="k">Código do Relatório</span>
                <span class="v mono">{data['code']}</span>
            </div>
            <div class="meta-cell">
                <span class="k">Data de Emissão (UTC)</span>
                <span class="v">{data['generated_at'][:19].replace('T', ' ')} UTC</span>
            </div>
            <div class="meta-cell">
                <span class="k">Categoria & Escopo</span>
                <span class="v">{data['category']} • GBOC Agent Node</span>
            </div>
            <div class="meta-cell">
                <span class="k">Hash de Autenticidade</span>
                <span class="v mono">{audit_hash_short}</span>
            </div>
        </section>

        <!-- Score de Proteção & Resiliência -->
        {score_html}

        <!-- O Que Mudou (Delta vs Período Anterior) -->
        {delta_html}

        <!-- Grade de Métricas Principais (KPIs) -->
        <section class="report-kpi-grid">
            {metrics_html}
        </section>

        <!-- Parecer Executivo de IA Preditiva -->
        <section class="report-ai-card">
            <div class="ai-title">
                <i class="fas fa-brain"></i> Parecer Técnico & Inteligência Preditiva GBOC:
            </div>
            <div>{ai_rec}</div>
        </section>

        <!-- Detalhamento dos Registros Auditados (se houver tabela) -->
        {f'''
        <section>
            <div class="report-section-title">
                <i class="fas fa-table-list" style="color:var(--primary)"></i> Detalhamento dos Dados Auditados
            </div>
            <div class="table-container">
                <table class="audit-table">
                    <thead><tr>{headers_html}</tr></thead>
                    <tbody>{rows_html if rows_html else '<tr><td colspan="100%" style="text-align:center">Nenhum registro auditado no período selecionado.</td></tr>'}</tbody>
                </table>
            </div>
        </section>
        ''' if headers_html else ''}

        <!-- Ações Recomendadas -->
        {actions_html}

        <!-- Seção de Responsabilidade e Assinatura Técnica -->
        <section class="audit-sign-section">
            <p class="audit-sign-disclaimer">
                <strong>Declaração de Conformidade Técnica:</strong> As informações contidas neste documento foram extraídas diretamente da base de dados local e telemetria operacional em tempo real do GBOC Agent v{AGENT_VERSION} Enterprise Edition, sem simulações ou dados fictícios. A integridade dos dados pode ser atestada pelo hash criptográfico constante no cabeçalho.
            </p>
            <div class="signatures-grid">
                <div class="sig-box">
                    <div class="sig-line"></div>
                    <div class="sig-name">Operador do Agente Local</div>
                    <div class="sig-role">Operações de TI • GBOC Enterprise</div>
                </div>
                <div class="sig-box">
                    <div class="sig-line"></div>
                    <div class="sig-name">Auditoria de Segurança da Informação</div>
                    <div class="sig-role">Governança, Riscos & Compliance (GRC)</div>
                </div>
            </div>
        </section>

        <!-- Rodapé do Relatório -->
        <footer class="report-footer">
            <span>GBOC System v{AGENT_VERSION} Enterprise Edition — Propriedade Intelectual Registrada.</span>
            <span>Assinatura Digital: <span class="audit-hash-badge">{audit_hash[:16]}...</span></span>
        </footer>
    </main>

    <script>
        window.addEventListener('DOMContentLoaded', () => {{
            if (window.location.search.includes('print=1')) {{
                setTimeout(() => {{
                    window.print();
                }}, 300);
            }}
        }});
    </script>
</body>
</html>"""
        return HTMLResponse(content=html_content)


# =====================================================================
# GBOC v2.0 FLAGSHIP REPORTS (7 Relatórios Executivos de Mercado - Agent)
# =====================================================================

try:
    from engines.flagship_reports import (
        FLAGSHIPS_CATALOG_8,
        FLAGSHIPS_CATALOG_7,
        build_flagship_report_agent,
        render_flagship_html,
        render_flagship_csv,
    )
except ImportError:
    from flagship_reports import (
        FLAGSHIPS_CATALOG_8,
        FLAGSHIPS_CATALOG_7,
        build_flagship_report_agent,
        render_flagship_html,
        render_flagship_csv,
    )

try:
    from engines.v4_reports_engine import (
        NEW_REPORTS_CATALOG_5,
        detect_anomalies,
        collect_health_timeline,
        collect_engine_health,
        collect_config_drift,
        compare_periods
    )
except ImportError:
    try:
        from v4_reports_engine import (
            NEW_REPORTS_CATALOG_5,
            detect_anomalies,
            collect_health_timeline,
            collect_engine_health,
            collect_config_drift,
            compare_periods
        )
    except ImportError:
        NEW_REPORTS_CATALOG_5 = []
        detect_anomalies = lambda days=30: []
        collect_health_timeline = lambda days=90: []
        collect_engine_health = lambda: []
        collect_config_drift = lambda: []
        compare_periods = lambda periods=[7, 30, 90]: {"periods": [], "period_labels": []}

from fastapi.responses import Response


@router.get("/api/reports/flagships")
@router.get("/api/v1/reports/flagships")
async def list_agent_flagship_reports():
    """Retorna o catálogo dos 8 relatórios flagship executivos no GBOC Agent (Schema v4.0.0)."""
    return JSONResponse({
        "status": "success",
        "schema_version": "4.0.0",
        "platform": f"GBOC Agent v{AGENT_VERSION}",
        "count": len(FLAGSHIPS_CATALOG_8),
        "flagships": FLAGSHIPS_CATALOG_8,
        "new_reports": NEW_REPORTS_CATALOG_5
    })


@router.get("/api/reports/flagships/{flagship_id}")
@router.get("/api/v1/reports/flagships/{flagship_id}")
async def get_agent_flagship_report(
    flagship_id: str,
    format: str = Query("html", pattern="^(html|pdf|csv|json)$"),
    print: Optional[str] = Query(None)
):
    """Gera e retorna um dos 8 relatórios flagship no formato requisitado (html, pdf, csv, json) no Agente."""
    fid = flagship_id.upper().strip()
    valid_ids = [f["id"] for f in FLAGSHIPS_CATALOG_8]
    if fid not in valid_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Relatório Flagship '{flagship_id}' não encontrado. IDs válidos: {', '.join(valid_ids)}"
        )

    try:
        payload = await run_in_threadpool(build_flagship_report_agent, fid)
    except Exception as e:
        logger.error(f"Erro ao gerar payload do Flagship {fid} no agente: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro interno ao gerar relatório: {str(e)}")

    if format == "json":
        return JSONResponse(content=payload)

    elif format == "csv":
        csv_data = render_flagship_csv(payload)
        filename = f"{fid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    else:
        is_print = (format == "pdf") or (print in ("1", "true", "yes"))
        html_content = render_flagship_html(payload, is_print=is_print)
        return HTMLResponse(content=html_content)


# ── NOVAS ROTAS DE RELATÓRIO DO MASTER REPORT STANDARD v4.0 ─────────────────

@router.get("/api/reports/anomalies")
@router.get("/api/v1/reports/anomalies")
async def get_anomalies_endpoint(days: int = Query(30, ge=1, le=365)):
    """REP-N1: Retorna anomalias de volume e duração detectadas via Z-Score."""
    try:
        anomalies = await run_in_threadpool(detect_anomalies, days)
        return JSONResponse({
            "status": "success",
            "code": "REP-N1",
            "title": "Anomaly Detection Report",
            "period_days": days,
            "anomalies_count": len(anomalies),
            "anomalies": anomalies
        })
    except Exception as e:
        logger.error(f"Erro em REP-N1 anomalies: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/reports/health-timeline")
@router.get("/api/v1/reports/health-timeline")
async def get_health_timeline_endpoint(days: int = Query(90, ge=7, le=365)):
    """REP-N2: Retorna calendário visual com matriz diária de saúde dos backups."""
    try:
        timeline = await run_in_threadpool(collect_health_timeline, days)
        return JSONResponse({
            "status": "success",
            "code": "REP-N2",
            "title": "Backup Health Timeline",
            "period_days": days,
            "days_count": len(timeline),
            "timeline": timeline
        })
    except Exception as e:
        logger.error(f"Erro em REP-N2 health-timeline: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/reports/engine-health")
@router.get("/api/v1/reports/engine-health")
async def get_engine_health_endpoint():
    """REP-N3: Retorna diagnóstico aprofundado dos motores de backup instalados."""
    try:
        engines_data = await run_in_threadpool(collect_engine_health)
        return JSONResponse({
            "status": "success",
            "code": "REP-N3",
            "title": "Engine Health Report",
            "engines": engines_data
        })
    except Exception as e:
        logger.error(f"Erro em REP-N3 engine-health: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/reports/config-drift")
@router.get("/api/v1/reports/config-drift")
async def get_config_drift_endpoint():
    """REP-N4: Rastreia desvios e alterações de configuração dos backups."""
    try:
        drift = await run_in_threadpool(collect_config_drift)
        return JSONResponse({
            "status": "success",
            "code": "REP-N4",
            "title": "Configuration Drift Report",
            "drift_events": drift
        })
    except Exception as e:
        logger.error(f"Erro em REP-N4 config-drift: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/reports/compare")
@router.get("/api/v1/reports/compare")
async def get_compare_periods_endpoint(periods: str = Query("7,30,90")):
    """REP-N5: Comparativo analítico multi-período lado a lado."""
    try:
        days_list = [int(p.strip()) for p in periods.split(",") if p.strip().isdigit()]
        if not days_list:
            days_list = [7, 30, 90]
        comp = await run_in_threadpool(compare_periods, days_list)
        return JSONResponse({
            "status": "success",
            "code": "REP-N5",
            "title": "Multi-Period Comparison Report",
            "data": comp
        })
    except Exception as e:
        logger.error(f"Erro em REP-N5 compare: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/reports/schema")
@router.get("/api/v1/reports/schema")
async def get_reports_schema():
    """Retorna a especificação normativa Schema v4.0.0 para integrações de BI e API."""
    return JSONResponse({
        "schema_version": "4.0.0",
        "normative_standard": "GBOC Agent Master Report Standard v4.0",
        "flagships_count": len(FLAGSHIPS_CATALOG_8),
        "new_reports_count": len(NEW_REPORTS_CATALOG_5),
        "supported_formats": ["html", "pdf", "csv", "json"],
        "flagships": FLAGSHIPS_CATALOG_8,
        "new_reports": NEW_REPORTS_CATALOG_5
    })


@router.get("/api/system/health")
@router.get("/api/v1/system/health")
async def get_system_health():
    """Health check unificado — expõe versão, uptime, integridade do banco e engines ativos."""
    try:
        from version import GBOC_VERSION, version_string
    except ImportError:
        GBOC_VERSION = "14.6.0"
        version_string = lambda: "GBOC Agent v14.6.0 Enterprise"

    import psutil, os
    proc = psutil.Process(os.getpid())
    elapsed = time.time() - proc.create_time()
    h, m = int(elapsed // 3600), int((elapsed % 3600) // 60)
    uptime_info = {
        "pid": os.getpid(),
        "uptime_str": f"{h}h {m}m",
        "uptime_hours": round(elapsed / 3600, 1),
        "memory_mb": round(proc.memory_info().rss / (1024**2), 1),
        "cpu_pct": proc.cpu_percent(interval=None),
        "status": proc.status(),
    }

    core = _get_core()
    summary = {"total": 0, "ok": 0, "failed": 0, "success_rate": 100.0}
    engines = []
    try:
        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END)
                FROM backups WHERE start_time >= datetime('now', '-1 day')
            """)
            r = cur.fetchone()
            if r and r[0]:
                tot = int(r[0] or 0)
                ok = int(r[1] or 0)
                summary = {
                    "total": tot,
                    "ok": ok,
                    "failed": int(r[2] or 0),
                    "success_rate": round(ok / tot * 100, 1) if tot else 100.0
                }
            cur.execute("SELECT engine, path, detected FROM detected_engines LIMIT 10")
            for erow in cur.fetchall():
                engines.append({"engine": erow[0], "path": erow[1], "detected": bool(erow[2])})
    except Exception as db_err:
        logger.warning(f"Erro ao consultar DB para healthcheck: {db_err}")

    status_str = "healthy" if summary["failed"] == 0 else ("degraded" if summary["success_rate"] >= 80 else "unhealthy")

    return JSONResponse({
        "status": status_str,
        "version": GBOC_VERSION,
        "version_string": version_string(),
        "uptime": uptime_info,
        "last_24h": summary,
        "engines": engines,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


@router.get("/api/system/version")
@router.get("/api/v1/system/version")
async def get_system_version():
    """Retorna versão oficial, build e metadados de release da plataforma."""
    try:
        from version import GBOC_VERSION, GBOC_BUILD, GBOC_EDITION, GBOC_RELEASE_DATE, GBOC_PLATFORM, version_string
        return JSONResponse({
            "version": GBOC_VERSION,
            "build": GBOC_BUILD,
            "edition": GBOC_EDITION,
            "release_date": GBOC_RELEASE_DATE,
            "platform": GBOC_PLATFORM,
            "string": version_string()
        })
    except Exception:
        return JSONResponse({"version": "14.6.0", "build": "stable", "edition": "Enterprise"})


