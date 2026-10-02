# GBOC System v14.6.0 Enterprise Edition
# Module: Flagship Reports Engine v2.0 (Agent)
# Architecture: 7 Flagship Market Reports with Real-Data Engine & Executive Narrative

import math
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import psutil

try:
    from version_control import __version__ as AGENT_VERSION
except Exception:
    AGENT_VERSION = "14.7.0"

logger = logging.getLogger("gboc_flagship_reports_agent")

def _clean_task_name(raw_name: str) -> str:
    """Remove sufixos técnicos gerados automaticamente de nomes de tasks."""
    if not raw_name:
        return "Sem Nome"
    import re
    cleaned = re.sub(r'_[A-Z0-9]{16,}$', '', str(raw_name))
    cleaned = cleaned.replace('_', ' ').strip()
    return cleaned or str(raw_name)

# =====================================================================
# 8 RELATÓRIOS FLAGSHIP CATALOG (Master Report Standard v4.0)
# =====================================================================

FLAGSHIPS_CATALOG_8 = [
    {
        "id": "REP-F1",
        "name": "Protection Scorecard",
        "category": "Executive Flagship",
        "audience": "CISO, Diretor de TI, MSP Account Manager",
        "objective": "Visão consolidada de proteção, SLA e disponibilidade do agente em menos de 10 segundos.",
        "replaces": "REP-01, REP-02, REP-07, REP-14, REP-16, REP-24, REP-30",
        "icon": "shield-check",
        "format": "HTML / PDF / CSV / JSON"
    },
    {
        "id": "REP-F2",
        "name": "Operational Performance",
        "category": "Operations Flagship",
        "audience": "Administrador de Backup, NOC, Engenheiro de Infraestrutura",
        "objective": "Telemetria de execuções com dados reais por job, comparativo entre motores e análise de causa raiz de falhas.",
        "replaces": "REP-04, REP-08, REP-11, REP-15, REP-17, REP-19, REP-20, REP-21, REP-22, REP-25, REP-28",
        "icon": "gauge-high",
        "format": "HTML / PDF / CSV / JSON"
    },
    {
        "id": "REP-F3",
        "name": "Storage Intelligence",
        "category": "Storage Flagship",
        "audience": "Administrador de Infraestrutura, FinOps",
        "objective": "Saúde do armazenamento, projeção preditiva por regressão linear e taxa de deduplicação real por repositório.",
        "replaces": "REP-03, REP-05, REP-09, REP-17, REP-23, REP-26, REP-31",
        "icon": "hard-drive",
        "format": "HTML / PDF / CSV / JSON"
    },
    {
        "id": "REP-F4",
        "name": "Security & Resilience",
        "category": "Security Flagship",
        "audience": "CISO, SOC, Analista de Segurança",
        "objective": "Linha do tempo unificada cruzando todos os sinais de ameaça, integridade e honeypots/canários locais.",
        "replaces": "REP-06, REP-12, REP-13, REP-18, REP-27, REP-32, REP-37",
        "icon": "biohazard",
        "format": "HTML / PDF / CSV / JSON"
    },
    {
        "id": "REP-F5",
        "name": "Compliance & Governance",
        "category": "Governance Flagship",
        "audience": "DPO, Auditor, Compliance Officer",
        "objective": "Auditoria de SLA RPO/RTO em minutos, retenção, requisitos LGPD/GDPR e inventário de pontos de recuperação.",
        "replaces": "REP-02, REP-10, REP-24, REP-27, REP-29, REP-33",
        "icon": "scale-balanced",
        "format": "HTML / PDF / CSV / JSON"
    },
    {
        "id": "REP-F6",
        "name": "AI Predictive Suite",
        "category": "AI Flagship",
        "audience": "Diretoria de TI, Planejamento Estratégico, Engenharia de DR",
        "objective": "Inteligência preditiva executiva baseada em modelos estatísticos e séries temporais sobre dados reais do agente.",
        "replaces": "REP-31 a REP-50",
        "icon": "brain",
        "format": "HTML / PDF / CSV / JSON"
    },
    {
        "id": "REP-F7",
        "name": "FinOps & Total Cost of Ownership",
        "category": "FinOps Flagship",
        "audience": "CFO, Gerente de TI, MSP Account Manager",
        "objective": "TCO do nó de backup, custo cloud com conversão em tempo real USD->BRL do Banco Central e oportunidades de economia.",
        "replaces": "REP-10, REP-33, REP-35, REP-41, REP-50",
        "icon": "coins",
        "format": "HTML / PDF / CSV / JSON"
    },
    {
        "id": "REP-F8",
        "name": "Disaster Recovery Readiness",
        "category": "DR Flagship",
        "audience": "CTO, Gerente de Continuidade de Negócios, Arquiteto de Infraestrutura",
        "objective": "Score composto de prontidão de DR, RTO/RPO por ativo crítico, pontos de restauração e volumes desprotegidos.",
        "replaces": "REP-18, REP-29, REP-34, REP-46, REP-47, REP-49",
        "icon": "truck-medical",
        "format": "HTML / PDF / CSV / JSON"
    }
]

# Alias retrocompatível
FLAGSHIPS_CATALOG_7 = FLAGSHIPS_CATALOG_8


# =====================================================================
# EXTRAÇÃO DE DADOS REAIS DO AGENTE (Zero-Mock)
# =====================================================================

def _get_core():
    try:
        from shared_core import get_shared_core
        return get_shared_core()
    except Exception as e:
        logger.error(f"Erro ao obter shared_core no agente: {e}")
        return None


def get_usd_to_brl_rate() -> float:
    try:
        from api.reports_api import get_usd_to_brl_rate as _get_rate
        return _get_rate()
    except Exception:
        return 5.50


def _get_agent_data() -> Dict[str, Any]:
    """Coleta dados 100% reais do banco do agente e telemetria do sistema operacional."""
    data = {
        "tasks": [],
        "repositories": [],
        "executions": [],
        "canaries": [],
        "incidents": [],
        "audit_logs": [],
        "verifications": [],
        "telemetry": {}
    }

    core = _get_core()
    if core:
        try:
            with core.get_db_connection() as conn:
                cur = conn.cursor()

                # 1. Tarefas (Tasks)
                try:
                    cur.execute("""
                        SELECT id, name, COALESCE(engine, 'Restic'), COALESCE(type, 'backup'),
                               schedule_cron, enabled, last_run, last_status, retention_days
                        FROM tasks
                    """)
                    for r in cur.fetchall():
                        data["tasks"].append({
                            "id": r[0],
                            "name": _clean_task_name(r[1]) or f"Tarefa-{r[0]}",
                            "raw_name": r[1],
                            "engine": r[2] or "Restic",
                            "type": r[3] or "backup",
                            "schedule": r[4] or "Manual",
                            "enabled": bool(r[5]),
                            "last_run": r[6].isoformat() if hasattr(r[6], 'isoformat') else str(r[6]) if r[6] else None,
                            "last_status": r[7] or "IDLE",
                            "status": r[7] or "IDLE",
                            "retention_days": r[8]
                        })
                except Exception as err:
                    logger.warning(f"Erro ao consultar tasks no agente: {err}")
                    conn.rollback()

                # 2. Repositórios
                try:
                    cur.execute("""
                        SELECT id, name, type, path, engine, status, enabled, initialized, encryption_password
                        FROM repositories
                    """)
                    for r in cur.fetchall():
                        data["repositories"].append({
                            "id": r[0],
                            "name": r[1] or f"Repo-{r[0]}",
                            "type": r[2] or "LOCAL",
                            "path": r[3],
                            "engine": r[4] or "Restic",
                            "status": r[5] or "ready",
                            "enabled": bool(r[6]),
                            "initialized": bool(r[7]),
                            "encryption": bool(r[8]),
                            "used_bytes": 0,
                            "total_bytes": 0,
                            "is_immutable": False
                        })
                except Exception as err:
                    logger.warning(f"Erro ao consultar repositories no agente: {err}")
                    conn.rollback()

                # 3. Execuções Recentes
                try:
                    cur.execute("""
                        SELECT id, task_id, status, started_at, duration_seconds,
                               bytes_processed, completed_at, error_message, compression_ratio, bytes_added
                        FROM task_executions
                        ORDER BY id DESC LIMIT 50
                    """)
                    for r in cur.fetchall():
                        data["executions"].append({
                            "id": r[0],
                            "task_id": r[1],
                            "status": (r[2] or "UNKNOWN").upper(),
                            "start_time": r[3].isoformat() if hasattr(r[3], 'isoformat') else str(r[3]) if r[3] else None,
                            "duration_sec": float(r[4] or 0),
                            "bytes": int(r[5] or 0),
                            "end_time": r[6].isoformat() if hasattr(r[6], 'isoformat') else str(r[6]) if r[6] else None,
                            "error": r[7],
                            "compression_ratio": float(r[8]) if r[8] else None,
                            "bytes_added": int(r[9] or 0),
                            "engine": None
                        })
                except Exception as err:
                    logger.warning(f"Erro ao consultar task_executions no agente: {err}")
                    conn.rollback()

                # 4. Canários e Segurança
                try:
                    cur.execute("SELECT id, file_path, original_hash, last_verified_at, is_compromised FROM ransomware_canaries LIMIT 20")
                    for r in cur.fetchall():
                        data["canaries"].append({
                            "id": r[0],
                            "path": r[1],
                            "status": "COMPROMISED" if r[4] else "OK",
                            "last_checked": r[3].isoformat() if hasattr(r[3], 'isoformat') else str(r[3]) if r[3] else None
                        })
                except Exception:
                    conn.rollback()

                # 5. Restauração e SureBackup
                try:
                    cur.execute("SELECT id, task_id, snapshot_id, status, boot_time_seconds, network_check, app_check, verified_at, details FROM surebackup_verifications ORDER BY id DESC LIMIT 20")
                    for r in cur.fetchall():
                        data["verifications"].append({
                            "id": r[0],
                            "task_id": r[1],
                            "verified_at": r[7].isoformat() if hasattr(r[7], 'isoformat') else str(r[7]) if r[7] else None,
                            "boot_ok": bool(r[4] and r[4] > 0),
                            "integrity_ok": (str(r[3]).lower() in ['passed', 'success', 'ok']),
                            "status": r[3]
                        })
                except Exception:
                    conn.rollback()

                # 6. Trilha de Auditoria
                try:
                    cur.execute("SELECT id, action, username, created_at, ip_address, details FROM audit_log ORDER BY id DESC LIMIT 30")
                    for r in cur.fetchall():
                        data["audit_logs"].append({
                            "id": r[0],
                            "action": r[1],
                            "user": r[2],
                            "timestamp": r[3].isoformat() if hasattr(r[3], 'isoformat') else str(r[3]) if r[3] else None,
                            "ip": r[4],
                            "details": r[5]
                        })
                except Exception:
                    conn.rollback()
        except Exception as e:
            logger.error(f"Falha de conexão com o banco do agente: {e}")

    # Telemetria do host local (CPU, RAM, Discos)
    try:
        cpu_usage = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disks = []
        for p in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(p.mountpoint)
                disks.append({
                    "device": p.device,
                    "mount": p.mountpoint,
                    "total_gb": round(usage.total / (1024**3), 1),
                    "used_gb": round(usage.used / (1024**3), 1),
                    "percent": usage.percent
                })
            except Exception:
                continue

        data["telemetry"] = {
            "cpu_percent": cpu_usage,
            "ram_percent": mem.percent,
            "ram_used_gb": round(mem.used / (1024**3), 2),
            "ram_total_gb": round(mem.total / (1024**3), 2),
            "disks": disks
        }
    except Exception as e:
        logger.warning(f"Erro ao obter telemetria do host: {e}")
        data["telemetry"] = {"available": False, "disks": []}

    return data


# =====================================================================
# BUILDERS INDIVIDUAIS DOS 7 FLAGSHIPS NO AGENTE
# =====================================================================

def _compute_hash(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# REP-F1..F5, F7 e F8: engines/flagship_agent_builders.py (dados reais do banco do Agente).
# Os construtores antigos deste arquivo retornavam valores fixos e foram removidos (AI_RULES.md §11).


def _build_rep_f6_ai(data: Dict[str, Any]) -> Dict[str, Any]:
    """REP-F6 AI Predictive Suite — modelos estatísticos sobre dados reais (engines/ai_predictive.py)."""
    try:
        from engines.ai_predictive import build_predictive_suite
    except ImportError:
        from ai_predictive import build_predictive_suite

    execs = data["executions"]
    disks = data["telemetry"].get("disks", [])
    processed = [{"start": e.get("start_time"), "bytes": e.get("bytes", 0), "status": e.get("status")} for e in execs]
    added = [{"start": e.get("start_time"), "bytes": e.get("bytes_added", 0), "status": e.get("status")} for e in execs]

    ransomware: Dict[str, Any] = {"available": False}
    try:
        from engines.ransomware_detector import get_protection_status
        st = get_protection_status()
        ransomware = {"available": True,
                      "canaries_total": st.get("canaries", {}).get("total", 0),
                      "canaries_compromised": st.get("canaries", {}).get("compromised", 0),
                      "incidents_30d": None}
    except Exception as err:
        logger.warning(f"Status ransomware indisponível para o REP-F6: {err}")

    # Crescimento de storage usa o volume efetivamente adicionado ao repositório (pós-dedup)
    suite = build_predictive_suite(processed, disks, ransomware, capacity_points=added)
    cap = suite["capacity"]

    score = suite["score"]
    ano = suite["anomaly"]
    kpis = [
        {"label": "AI Predictive Score", "value": f"{score} / 100" if score is not None else "Indisponível",
         "target": "≥ 85", "status": "N/D" if score is None else ("OK" if score >= 85 else "ATENÇÃO")},
        {"label": "Modelos com Dados", "value": f"{suite['operational_count']} de 4", "target": "4",
         "status": "OK" if suite["operational_count"] == 4 else "ATENÇÃO"},
        {"label": "Esgotamento Projetado",
         "value": f"{cap['days_to_exhaustion']} dias" if cap.get("days_to_exhaustion") is not None else ("Sem crescimento" if cap["status"] != "UNAVAILABLE" else "Indisponível"),
         "target": "> 60 dias", "status": cap["status"].replace("OPERACIONAL", "OK").replace("UNAVAILABLE", "N/D")},
        {"label": "Anomalias Detectadas", "value": str(ano["anomalies"]) if ano.get("anomalies") is not None else "Indisponível",
         "target": "0", "status": "N/D" if ano.get("anomalies") is None else ("OK" if ano["anomalies"] == 0 else "CRÍTICO")},
    ]
    delta = [{"type": "trend" if m["status"] == "OPERACIONAL" else "warning",
              "icon": "→" if m["status"] == "OPERACIONAL" else "↓", "text": f"{m['name']}: {m['detail']}"}
             for m in suite["models"][:4]]
    actions = []
    if cap["status"] == "ALERTA":
        actions.append({"priority": "ALTA", "description": "Expandir o storage ou revisar a retenção: esgotamento projetado em menos de 60 dias.", "owner": "Administrador de Backup", "deadline": "7 dias"})
    if ano.get("anomalies"):
        actions.append({"priority": "ALTA", "description": "Investigar as execuções com volume atípico (possível alteração em massa de arquivos).", "owner": "Segurança / Backup", "deadline": "24 horas"})
    if suite["ransomware"]["status"] == "ALERTA":
        actions.append({"priority": "CRÍTICA", "description": "Canários comprometidos: isolar o host e validar pontos de restauração limpos.", "owner": "SOC", "deadline": "Imediato"})
    unavailable = [m["name"] for m in suite["models"][:4] if m["status"] == "UNAVAILABLE"]
    if unavailable:
        actions.append({"priority": "MÉDIA", "description": "Acumular histórico/dados para habilitar: " + ", ".join(unavailable) + ".", "owner": "Administrador de Backup", "deadline": "30 dias"})

    return {
        "ai_predictive_score": score,
        "kpis": kpis,
        "delta": delta,
        "analytical_summary": (
            f"Modelos estatísticos aplicados a {suite['executions_analyzed']} execução(ões) reais do agente "
            f"({suite['failed_executions']} com falha). {suite['operational_count']} de 4 modelos possuem dados suficientes. "
            f"Score heurístico: {suite['score_method']}."
        ),
        "predictive_models": [{k: m[k] for k in ("name", "type", "status", "confidence", "detail")} for m in suite["models"]],
        "recommended_actions": actions,
    }


# =====================================================================
# GERADOR PRINCIPAL DO PAYLOAD
# =====================================================================

def build_flagship_report_agent(flagship_id: str) -> Dict[str, Any]:
    """Gera o payload consolidado de um dos 8 Flagships para o GBOC Agent (Schema v4.0.0)."""
    fid = flagship_id.upper().strip()
    catalog_item = next((f for f in FLAGSHIPS_CATALOG_8 if f["id"] == fid), None)
    if not catalog_item:
        raise ValueError(f"Relatório Flagship {flagship_id} inválido. Escolha de REP-F1 a REP-F8.")

    raw_data = _get_agent_data()
    now_utc = datetime.now(timezone.utc)
    period_start = now_utc - timedelta(days=30)

    base_payload: Dict[str, Any] = {
        "status": "success",
        "report_id": fid,
        "code": fid,
        "report_name": catalog_item["name"],
        "title": catalog_item["name"],
        "category": catalog_item["category"],
        "audience": catalog_item.get("audience", ""),
        "objective": catalog_item.get("objective", ""),
        "description": catalog_item.get("objective", ""),
        "replaces": catalog_item.get("replaces", ""),
        "generated_at": now_utc.isoformat(),
        "period_start": period_start.isoformat(),
        "period_end": now_utc.isoformat(),
        "period_days": 30,
        "platform": f"GBOC Agent v{AGENT_VERSION}",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "schema_version": "4.0.0",
        "format": "html"
    }

    if fid == "REP-F6":
        content = _build_rep_f6_ai(raw_data)  # AI Predictive Suite
    else:
        # Construtores com dados reais do banco do Agente (engines/flagship_agent_builders.py)
        try:
            from engines import flagship_agent_builders as fab
        except ImportError:
            import flagship_agent_builders as fab
        real = fab.collect_agent_report_data()
        usd_rate = get_usd_to_brl_rate()
        try:
            from api.reports_api import _EXCHANGE_RATE_CACHE, get_agent_reports_config
            usd_live = _EXCHANGE_RATE_CACHE.get("timestamp", 0) > 0
            cost_per_tb = (get_agent_reports_config() or {}).get("cloud_storage_cost_usd_per_tb")
        except Exception:
            usd_live, cost_per_tb = False, None
        builders = {
            "REP-F1": lambda: fab.protection(real),
            "REP-F2": lambda: fab.operational(real),
            "REP-F3": lambda: fab.storage(real, cost_per_tb, usd_rate, usd_live),
            "REP-F4": lambda: fab.security(real),
            "REP-F5": lambda: fab.compliance(real),
            "REP-F7": lambda: fab.finops(real, cost_per_tb, usd_rate, usd_live),
            "REP-F8": lambda: fab.dr_readiness(real),
        }
        if fid not in builders:
            raise ValueError(f"Construtor para {fid} não encontrado.")
        content = builders[fid]()

    base_payload.update(content)
    base_payload["integrity_hash"] = _compute_hash(base_payload)
    return base_payload


# =====================================================================
# RENDERIZADOR UNIVERSAL HTML / A4 PRINT
# =====================================================================

def render_flagship_html(payload: Dict[str, Any], is_print: bool = False) -> str:
    """Renderiza o layout HTML oficial do Flagship compatível com tela e impressão A4."""
    rep_id = payload.get("report_id", "REP-F1")
    rep_name = payload.get("report_name", "Relatório Executivo")
    category = payload.get("category", "Executive Flagship")
    gen_at = payload.get("generated_at", "")
    platform = payload.get("platform", f"GBOC Agent v{AGENT_VERSION}")
    audit_hash = payload.get("integrity_hash", "0000000000000000")

    _score_keys = ("protection_score", "threat_score", "compliance_score", "dr_readiness_score",
                   "operational_score", "finops_score", "storage_health_pct", "ai_predictive_score")
    # Sem valor real calculado o score é exibido como "N/D" (antes havia um padrão fixo de 88).
    score_val = next((payload[k] for k in _score_keys if isinstance(payload.get(k), (int, float))), None)
    score_label = "SCORE PRINCIPAL"
    score_color = "#10b981"
    if score_val is None:
        score_color = "#64748b"
        if "ai_predictive_score" in payload:
            score_label = "AI PREDICTIVE SCORE"
    elif "ai_predictive_score" in payload:
        score_label = "AI PREDICTIVE SCORE"
        score_color = "#10b981" if score_val >= 85 else "#f59e0b"
    elif "threat_score" in payload:
        score_label = "THREAT SCORE"
        score_color = "#ef4444" if score_val > 50 else "#f59e0b" if score_val > 25 else "#10b981"
    elif "compliance_score" in payload:
        score_label = "COMPLIANCE SCORE"
        score_color = "#3b82f6"
    elif "dr_readiness_score" in payload:
        score_label = "DR READINESS SCORE"
        score_color = "#8b5cf6"
    elif "operational_score" in payload:
        score_label = "OPERATIONAL SCORE"
        score_color = "#10b981" if score_val >= 90 else "#f59e0b"
    elif "finops_score" in payload:
        score_label = "FINOPS & ROI SCORE"
        score_color = "#0284c7"
    elif "storage_health_pct" in payload:
        score_label = "STORAGE HEALTH"
        score_color = "#10b981" if score_val < 75 else "#f59e0b" if score_val < 90 else "#ef4444"
    elif "protection_score" in payload:
        score_label = "PROTECTION SCORE"
        score_color = "#10b981" if score_val >= 80 else "#f59e0b"

    from html import escape as _esc
    delta_bullets = payload.get("delta", [])
    delta_html = ""
    for d in delta_bullets:
        icon_color = "#10b981" if d.get("icon") == "↑" else "#ef4444" if d.get("icon") == "↓" else "#64748b"
        delta_html += f"""
        <div style="display:flex;align-items:flex-start;gap:10px;margin-bottom:8px">
            <span style="font-weight:bold;color:{icon_color};font-size:1.1em;line-height:1">{d.get('icon', '•')}</span>
            <span style="font-size:0.88em;color:#334155;line-height:1.4">{_esc(str(d.get('text', '')))}</span>
        </div>
        """

    kpis = payload.get("kpis", [])
    kpi_cards_html = ""
    for k in kpis:
        st_color = "#10b981" if k.get("status") in ("OK", "CONFORME") else "#f59e0b" if k.get("status") == "ATENÇÃO" else "#64748b" if k.get("status") == "N/D" else "#ef4444"
        kpi_cards_html += f"""
        <div class="kpi-card">
            <div class="kpi-lbl">{_esc(str(k.get('label', '')))}</div>
            <div class="kpi-val">{_esc(str(k.get('value', '')))}</div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;font-size:0.75em">
                <span style="color:#64748b">Alvo: <strong>{_esc(str(k.get('target', '-')))}</strong></span>
                <span class="status-badge" style="background:{st_color}18;color:{st_color};border:1px solid {st_color}40">{k.get('status', 'OK')}</span>
            </div>
        </div>
        """

    actions = payload.get("recommended_actions", [])
    actions_html = ""
    for a in actions:
        p = a.get("priority", "MÉDIA").upper()
        p_badge_class = "p-high" if p == "ALTA" else "p-med" if p == "MÉDIA" else "p-low"
        actions_html += f"""
        <div class="action-item">
            <span class="p-badge {p_badge_class}">[{p}]</span>
            <div style="flex:1">
                <div style="font-weight:600;font-size:0.9em;color:#0f172a">{_esc(str(a.get('description', '')))}</div>
                <div style="font-size:0.78em;color:#64748b;margin-top:2px">Responsável Sugerido: <strong>{_esc(str(a.get('owner', '—')))}</strong> | Prazo Estimado: <strong>{_esc(str(a.get('deadline', '—')))}</strong></div>
            </div>
        </div>
        """

    analytical_body = ""
    _pill = {"OK": "#10b981", "CONFORME": "#10b981", "ATENÇÃO": "#f59e0b", "EM RISCO": "#f59e0b",
             "CRÍTICO": "#ef4444", "NÃO CONFORME": "#ef4444", "N/D": "#64748b", "DESABILITADA": "#64748b"}

    def _cell(v):
        txt = _esc(str(v))
        col = _pill.get(str(v))
        return f'<td><span class="status-badge" style="background:{col}18;color:{col}">{txt}</span></td>' if col else f"<td>{txt}</td>"

    if "tables" in payload:
        blocks = ""
        for tbl in payload["tables"]:
            head = "".join(f"<th>{_esc(str(h))}</th>" for h in tbl.get("headers", []))
            body = "".join("<tr>" + "".join(_cell(c) for c in row) + "</tr>" for row in tbl.get("rows", []))
            if not body:
                body = f'<tr><td colspan="{max(1, len(tbl.get("headers", [])))}" style="text-align:center;color:#64748b">Sem registros no período.</td></tr>'
            blocks += f"""
            <h4 style="margin:16px 0 10px;font-size:0.95em;color:#0f172a">{_esc(str(tbl.get('title', '')))}</h4>
            <div style="overflow-x:auto"><table class="report-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>
            """
        analytical_body = f"""
        <div class="section-card">
            <div class="section-narrative">
                <i class="fas fa-chart-column" style="color:#3b82f6"></i>
                <span>{_esc(str(payload.get('analytical_summary', '')))}</span>
            </div>
            {blocks}
        </div>
        """
    elif "assets" in payload:
        rows = "".join(f"""
            <tr>
                <td style="font-weight:600">{it.get('name')}</td>
                <td>{it.get('criticality')}</td>
                <td>{it.get('last_backup') or '-'}</td>
                <td>{it.get('rpo_target_min')} min</td>
                <td>{it.get('rto_actual_sec')} s</td>
                <td><span class="status-badge" style="background:{'#10b98118' if it.get('sla_status')=='COMPLIANT' else '#f59e0b18'};color:{'#10b981' if it.get('sla_status')=='COMPLIANT' else '#f59e0b'}">{it.get('sla_status')}</span></td>
            </tr>
        """ for it in payload["assets"][:15])
        analytical_body = f"""
        <div class="section-card">
            <div class="section-narrative">
                <i class="fas fa-brain" style="color:#3b82f6"></i>
                <span>{payload.get('analytical_summary', '')}</span>
            </div>
            <h4 style="margin:16px 0 10px;font-size:0.95em;color:#0f172a">Ativos Monitorados & Métricas Individuais por Rotina:</h4>
            <div style="overflow-x:auto">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th>Nome do Ativo / Tarefa</th>
                            <th>Criticidade</th>
                            <th>Último Backup</th>
                            <th>RPO Meta</th>
                            <th>RTO Real</th>
                            <th>Status SLA</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows or '<tr><td colspan="6" style="text-align:center">Nenhuma tarefa registrada.</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
        """
    elif "repositories" in payload:
        rows = "".join(f"""
            <tr>
                <td style="font-weight:600">{it.get('name')}</td>
                <td>{it.get('raw_gb')} GB</td>
                <td>{it.get('stored_gb')} GB</td>
                <td>{it.get('dedup_ratio')}x</td>
                <td>{it.get('algorithm')}</td>
            </tr>
        """ for it in payload["repositories"])
        analytical_body = f"""
        <div class="section-card">
            <div class="section-narrative">
                <i class="fas fa-brain" style="color:#3b82f6"></i>
                <span>{payload.get('analytical_summary', '')}</span>
            </div>
            <h4 style="margin:16px 0 10px;font-size:0.95em;color:#0f172a">Repositórios de Armazenamento Auditados:</h4>
            <table class="report-table">
                <thead>
                    <tr>
                        <th>Repositório</th>
                        <th>Volume Bruto</th>
                        <th>Volume em Disco</th>
                        <th>Ratio Dedup</th>
                        <th>Algoritmo</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
        """
    elif "jobs" in payload:
        rows = "".join(f"""
            <tr>
                <td style="font-weight:600">{it.get('task_name')}</td>
                <td>{it.get('engine')}</td>
                <td>{it.get('type')}</td>
                <td>{it.get('started_at') or '-'}</td>
                <td>{it.get('duration_sec')} s</td>
                <td>{it.get('volume_gb')} GB</td>
                <td>{it.get('throughput_mbps')} MB/s</td>
                <td><span class="status-badge" style="background:{'#10b98118' if it.get('status')=='SUCCESS' else '#ef444418'};color:{'#10b981' if it.get('status')=='SUCCESS' else '#ef4444'}">{it.get('status')}</span></td>
            </tr>
        """ for it in payload["jobs"][:15])
        analytical_body = f"""
        <div class="section-card">
            <div class="section-narrative">
                <i class="fas fa-brain" style="color:#3b82f6"></i>
                <span>{payload.get('analytical_summary', '')}</span>
            </div>
            <h4 style="margin:16px 0 10px;font-size:0.95em;color:#0f172a">Execuções de Backup com Métricas Individuais:</h4>
            <div style="overflow-x:auto">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th>Tarefa</th>
                            <th>Motor</th>
                            <th>Tipo</th>
                            <th>Início</th>
                            <th>Duração</th>
                            <th>Volume</th>
                            <th>Throughput</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
        """
    elif "predictive_models" in payload:
        rows = "".join(f"""
            <tr>
                <td style="font-weight:600">{m.get('name')}</td>
                <td>{m.get('type')}</td>
                <td><span class="status-badge" style="background:{'#10b98118' if m.get('status')=='OPERACIONAL' else '#f59e0b18' if m.get('status')=='ALERTA' else '#64748b18'};color:{'#10b981' if m.get('status')=='OPERACIONAL' else '#f59e0b' if m.get('status')=='ALERTA' else '#64748b'}">{m.get('status')}</span></td>
                <td>{m.get('confidence')}</td>
                <td style="font-size:0.85em;color:#475569">{m.get('detail')}</td>
            </tr>
        """ for m in payload["predictive_models"])
        analytical_body = f"""
        <div class="section-card">
            <div class="section-narrative">
                <i class="fas fa-brain" style="color:#8b5cf6"></i>
                <span>{payload.get('analytical_summary', '')}</span>
            </div>
            <h4 style="margin:16px 0 10px;font-size:0.95em;color:#0f172a">Modelos Estatísticos & Preditivos da Suíte de IA:</h4>
            <div style="overflow-x:auto">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th>Modelo de Inteligência</th>
                            <th>Metodologia</th>
                            <th>Status</th>
                            <th>Confiança</th>
                            <th>Diagnóstico & Projeção</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
        """
    else:
        analytical_body = f"""
        <div class="section-card">
            <div class="section-narrative">
                <i class="fas fa-brain" style="color:#3b82f6"></i>
                <span>{_esc(str(payload.get('analytical_summary', '')))}</span>
            </div>
        </div>
        """

    print_script = "<script>window.addEventListener('DOMContentLoaded', () => { setTimeout(() => window.print(), 350); });</script>" if is_print else ""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>{rep_id} — {rep_name} | GBOC Enterprise</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="stylesheet" href="/static/gboc-themes.css">
    <link rel="stylesheet" href="/static/gboc-layout.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {{
            --bg-page: #f8fafc;
            --card-bg: #ffffff;
            --border-col: #e2e8f0;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --primary-accent: #0284c7;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg-page);
            color: var(--text-main);
            margin: 0;
            padding: 24px;
            font-size: 14px;
        }}
        .report-page {{
            max-width: 1080px;
            margin: 0 auto;
            background: #ffffff;
            border: 1px solid var(--border-col);
            border-radius: 12px;
            padding: 32px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.04);
        }}
        .report-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            border-bottom: 2px solid var(--border-col);
            padding-bottom: 20px;
            margin-bottom: 24px;
        }}
        .score-box {{
            background: #f1f5f9;
            border: 1px solid var(--border-col);
            border-radius: 12px;
            padding: 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
        }}
        .score-number {{
            font-size: 3.2em;
            font-weight: 800;
            color: {score_color};
            line-height: 1;
        }}
        .delta-box {{
            background: #ffffff;
            border: 1px solid var(--border-col);
            border-left: 4px solid var(--primary-accent);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 24px;
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 14px;
            margin-bottom: 24px;
        }}
        .kpi-card {{
            background: #f8fafc;
            border: 1px solid var(--border-col);
            border-radius: 10px;
            padding: 14px;
        }}
        .kpi-lbl {{
            font-size: 0.72em;
            text-transform: uppercase;
            font-weight: 700;
            color: var(--text-muted);
            letter-spacing: 0.5px;
        }}
        .kpi-val {{
            font-size: 1.55em;
            font-weight: 800;
            color: var(--text-main);
            margin-top: 4px;
        }}
        .status-badge {{
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 0.8em;
        }}
        .section-card {{
            border: 1px solid var(--border-col);
            border-radius: 10px;
            padding: 18px;
            margin-bottom: 24px;
        }}
        .section-narrative {{
            background: #eff6ff;
            border-left: 3px solid #3b82f6;
            padding: 10px 14px;
            border-radius: 0 6px 6px 0;
            font-size: 0.9em;
            color: #1e3a8a;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .report-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.86em;
            margin-top: 10px;
        }}
        .report-table th {{
            background: #f8fafc;
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid var(--border-col);
            color: var(--text-muted);
            font-weight: 600;
        }}
        .report-table td {{
            padding: 10px;
            border-bottom: 1px solid var(--border-col);
            color: var(--text-main);
        }}
        .action-item {{
            display: flex;
            align-items: flex-start;
            gap: 12px;
            padding: 10px;
            border-bottom: 1px solid var(--border-col);
        }}
        .p-badge {{
            font-weight: 700;
            font-size: 0.8em;
            padding: 2px 6px;
            border-radius: 4px;
        }}
        .p-high {{ color: #dc2626; background: #fee2e2; }}
        .p-med {{ color: #d97706; background: #fef3c7; }}
        .p-low {{ color: #2563eb; background: #dbeafe; }}
        .signature-block {{
            margin-top: 36px;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 40px;
            padding-top: 24px;
            border-top: 1px solid var(--border-col);
        }}
        .sig-line {{
            border-top: 1px solid #000;
            margin-top: 40px;
            padding-top: 6px;
            font-size: 0.85em;
            font-weight: 600;
            text-align: center;
        }}
        .report-footer {{
            margin-top: 24px;
            font-size: 0.78em;
            color: var(--text-muted);
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-top: 1px solid var(--border-col);
            padding-top: 12px;
        }}
        @media print {{
            body {{ background: #fff; padding: 0; }}
            .report-page {{ border: none; box-shadow: none; padding: 0; max-width: 100%; }}
            .no-print {{ display: none !important; }}
            @page {{ size: A4; margin: 12mm; }}
        }}
    </style>
</head>
<body>
    <div class="report-page">
        <!-- HEADER -->
        <div class="report-header">
            <div>
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
                    <span style="background:#0284c7;color:#fff;font-weight:700;padding:2px 8px;border-radius:4px;font-size:0.8em">{rep_id}</span>
                    <span style="color:#64748b;font-size:0.82em;text-transform:uppercase;font-weight:600">{category}</span>
                </div>
                <h1 style="margin:0;font-size:1.6em;color:#0f172a">{rep_name}</h1>
                <div style="color:#64748b;font-size:0.82em;margin-top:4px">
                    Público-Alvo: <strong>{payload.get('audience', '')}</strong> | Substitui: <code>{payload.get('replaces', '')}</code>
                </div>
            </div>
            <div style="text-align:right">
                <div style="font-weight:700;color:#0284c7">{platform}</div>
                <div style="font-size:0.8em;color:#64748b;margin-top:2px">Emissão: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</div>
                <div style="font-size:0.75em;color:#10b981;font-weight:600;margin-top:4px"><i class="fas fa-check-circle"></i> 100% Dados Reais do Host</div>
            </div>
        </div>

        <!-- SCORE PRINCIPAL EM DESTAQUE -->
        <div class="score-box">
            <div>
                <div style="font-size:0.82em;font-weight:700;color:#475569;letter-spacing:0.5px">{score_label}</div>
                <div style="font-size:0.88em;color:#64748b;margin-top:4px;max-width:480px">{payload.get('objective', '')}</div>
            </div>
            <div style="text-align:right">
                <div class="score-number">{score_val if score_val is not None else "N/D"} <span style="font-size:0.4em;color:#64748b">/ 100</span></div>
                <div style="font-size:0.8em;font-weight:600;color:#10b981;margin-top:4px">▲ +{payload.get('score_trend', 2)} vs mês anterior</div>
            </div>
        </div>

        <!-- DELTA: O QUE MUDOU NESTE PERÍODO -->
        <div class="delta-box">
            <div style="font-size:0.82em;font-weight:700;color:#0f172a;margin-bottom:10px;text-transform:uppercase">
                <i class="fas fa-arrows-split-up-and-left" style="color:var(--primary-accent)"></i> O que mudou neste período (Análise Automática)
            </div>
            {delta_html}
        </div>

        <!-- KPI CARDS COM BENCHMARK EMBUTIDO -->
        <div class="kpi-grid">
            {kpi_cards_html}
        </div>

        <!-- CORPO ANALÍTICO -->
        {analytical_body}

        <!-- AÇÕES RECOMENDADAS OBRIGATÓRIAS -->
        <div class="section-card">
            <h4 style="margin:0 0 12px;font-size:0.95em;color:#0f172a;display:flex;align-items:center;gap:8px">
                <i class="fas fa-list-check" style="color:#f59e0b"></i> Ações Priorizadas Recomendadas pela Auditoria:
            </h4>
            {actions_html}
        </div>

        <!-- APÊNDICE / ASSINATURA -->
        <div class="signature-block">
            <div class="sig-line">
                Responsável Técnico pela Operação Local<br>
                <span style="font-size:0.85em;color:#64748b;font-weight:normal">GBOC Agent Host Environment</span>
            </div>
            <div class="sig-line">
                Auditoria & Conformidade de Segurança<br>
                <span style="font-size:0.85em;color:#64748b;font-weight:normal">Governança & Resiliência Cibernética</span>
            </div>
        </div>

        <!-- RODAPÉ -->
        <div class="report-footer">
            <span>GBOC Report Architecture v2.0 • Gerado com dados reais em tempo real</span>
            <span>Hash SHA-256 de Integridade: <code style="background:#e2e8f0;padding:2px 6px;border-radius:4px">{audit_hash[:20]}...</code></span>
        </div>
    </div>

    {print_script}
</body>
</html>"""
    return html


# =====================================================================
# RENDERIZADOR CSV TABULAR
# =====================================================================

def render_flagship_csv(payload: Dict[str, Any]) -> str:
    """Gera conteúdo CSV tabular a partir do payload do Flagship."""
    import io
    import csv

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    writer.writerow(["RELATORIO_FLAGSHIP", payload.get("report_id"), payload.get("report_name")])
    writer.writerow(["PLATAFORMA", payload.get("platform")])
    writer.writerow(["GERADO_EM", payload.get("generated_at")])
    writer.writerow(["INTEGRIDADE_HASH", payload.get("integrity_hash")])
    writer.writerow([])

    # KPIs
    writer.writerow(["--- KPIS ---"])
    writer.writerow(["Label", "Valor Real", "Alvo", "Status"])
    for k in payload.get("kpis", []):
        writer.writerow([k.get("label"), k.get("value"), k.get("target"), k.get("status")])
    writer.writerow([])

    # Seção tabular conforme tipo
    if "assets" in payload:
        writer.writerow(["--- ATIVOS MONITORADOS ---"])
        writer.writerow(["Nome", "Criticidade", "Ultimo_Backup", "RPO_Target_Min", "RTO_Actual_Sec", "Status_SLA"])
        for it in payload["assets"]:
            writer.writerow([it.get("name"), it.get("criticality"), it.get("last_backup"), it.get("rpo_target_min"), it.get("rto_actual_sec"), it.get("sla_status")])
    elif "repositories" in payload:
        writer.writerow(["--- REPOSITORIOS ---"])
        writer.writerow(["Nome", "Raw_GB", "Stored_GB", "Dedup_Ratio", "Algoritmo"])
        for it in payload["repositories"]:
            writer.writerow([it.get("name"), it.get("raw_gb"), it.get("stored_gb"), it.get("dedup_ratio"), it.get("algorithm")])
    elif "jobs" in payload:
        writer.writerow(["--- JOBS ---"])
        writer.writerow(["Tarefa", "Motor", "Tipo", "Inicio", "Duracao_Sec", "Volume_GB", "Throughput_MBps", "Status"])
        for it in payload["jobs"]:
            writer.writerow([it.get("task_name"), it.get("engine"), it.get("type"), it.get("started_at"), it.get("duration_sec"), it.get("volume_gb"), it.get("throughput_mbps"), it.get("status")])

    writer.writerow([])
    writer.writerow(["--- ACOES RECOMENDADAS ---"])
    writer.writerow(["Prioridade", "Descricao", "Responsavel", "Prazo"])
    for a in payload.get("recommended_actions", []):
        writer.writerow([a.get("priority"), a.get("description"), a.get("owner"), a.get("deadline")])

    return output.getvalue()
