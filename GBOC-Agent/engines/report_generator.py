#!/usr/bin/env python3
"""
GBOC 11.7c - Report Generator Engine
Generates HTML/PDF reports for backup operations, SLA, capacity, executive summary.
"""

import logging
import io
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def _get_core():
    from shared_core import get_shared_core
    return get_shared_core()


def _query(sql: str, params: tuple = ()) -> List[Dict]:
    core = _get_core()
    with core.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        cols = [d[0] for d in cursor.description] if cursor.description else []
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _query_one(sql: str, params: tuple = ()) -> Optional[Dict]:
    rows = _query(sql, params)
    return rows[0] if rows else None


# ─── Data Collectors ────────────────────────────────────────────────

def collect_summary(days: int = 30) -> Dict[str, Any]:
    row = _query_one("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as ok,
               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
               SUM(COALESCE(bytes_processed,0)) as bytes,
               SUM(COALESCE(files_processed,0)) as files,
               AVG(CASE WHEN status='completed' THEN duration_seconds END) as avg_dur,
               MAX(started_at) as last_exec
        FROM task_executions
        WHERE started_at >= NOW() - INTERVAL '%s days'
    """ % int(days))
    total = (row or {}).get('total', 0) or 0
    ok = (row or {}).get('ok', 0) or 0
    return {
        "period_days": days,
        "total_executions": total,
        "successful": ok,
        "failed": (row or {}).get('failed', 0) or 0,
        "success_rate": round(ok / total * 100, 1) if total else 0,
        "total_bytes": (row or {}).get('bytes', 0) or 0,
        "total_files": (row or {}).get('files', 0) or 0,
        "avg_duration_sec": round((row or {}).get('avg_dur', 0) or 0, 1),
        "last_execution": str((row or {}).get('last_exec', '')),
    }


def collect_tasks_detail(days: int = 30) -> List[Dict]:
    return _query("""
        SELECT t.id, t.name, t.engine,
               COUNT(te.id) as total,
               SUM(CASE WHEN te.status='completed' THEN 1 ELSE 0 END) as ok,
               SUM(CASE WHEN te.status='failed' THEN 1 ELSE 0 END) as fail,
               SUM(COALESCE(te.bytes_processed,0)) as bytes,
               AVG(CASE WHEN te.status='completed' THEN te.duration_seconds END) as avg_dur,
               MAX(te.started_at) as last_run
        FROM tasks t
        LEFT JOIN task_executions te ON t.id=te.task_id
            AND te.started_at >= NOW() - INTERVAL '%s days'
        GROUP BY t.id, t.name, t.engine
        ORDER BY t.name
    """ % int(days))


def collect_daily_trend(days: int = 30) -> List[Dict]:
    return _query("""
        SELECT DATE(started_at) as day,
               COUNT(*) as total,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as ok,
               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as fail
        FROM task_executions
        WHERE started_at >= NOW() - INTERVAL '%s days'
        GROUP BY DATE(started_at)
        ORDER BY day
    """ % int(days))


def collect_engine_comparison(days: int = 30) -> List[Dict]:
    return _query("""
        SELECT t.engine,
               COUNT(te.id) as total,
               SUM(CASE WHEN te.status='completed' THEN 1 ELSE 0 END) as ok,
               SUM(COALESCE(te.bytes_processed,0)) as bytes,
               AVG(CASE WHEN te.status='completed' THEN te.duration_seconds END) as avg_dur
        FROM tasks t
        LEFT JOIN task_executions te ON t.id=te.task_id
            AND te.started_at >= NOW() - INTERVAL '%s days'
        GROUP BY t.engine
        ORDER BY t.engine
    """ % int(days))


def collect_errors(days: int = 30, limit: int = 20) -> List[Dict]:
    return _query("""
        SELECT te.error_message, t.name as task_name, t.engine,
               te.started_at, te.status
        FROM task_executions te
        JOIN tasks t ON te.task_id=t.id
        WHERE te.status='failed'
          AND te.started_at >= NOW() - INTERVAL '%s days'
        ORDER BY te.started_at DESC
        LIMIT %s
    """ % (int(days), int(limit)))


def collect_sla() -> List[Dict]:
    rows = _query("""
        SELECT t.id, t.name, t.engine,
               COUNT(te.id) as total_30d,
               SUM(CASE WHEN te.status='completed' THEN 1 ELSE 0 END) as ok_30d,
               MAX(CASE WHEN te.status='completed' THEN te.started_at END) as last_success,
               MAX(CASE WHEN te.status='failed' THEN te.started_at END) as last_failure
        FROM tasks t
        LEFT JOIN task_executions te ON t.id=te.task_id
            AND te.started_at >= NOW() - INTERVAL '30 days'
        GROUP BY t.id, t.name, t.engine
    """)
    for r in rows:
        total = r.get('total_30d', 0) or 0
        ok = r.get('ok_30d', 0) or 0
        r['success_rate'] = round(ok / total * 100, 1) if total else 0
        r['compliant'] = r['success_rate'] >= 95
    return rows


def collect_repos() -> List[Dict]:
    return _query("""
        SELECT r.id, r.name, r.engine, r.type, r.status,
               COUNT(t.id) as task_count
        FROM repositories r
        LEFT JOIN tasks t ON r.id=t.repository_id
        GROUP BY r.id, r.name, r.engine, r.type, r.status
        ORDER BY r.name
    """)


def collect_capacity() -> Dict[str, Any]:
    import psutil
    disk = psutil.disk_usage('C:' if __import__('platform').system() == 'Windows' else '/')
    return {
        "total_gb": round(disk.total / (1024 ** 3), 2),
        "used_gb": round(disk.used / (1024 ** 3), 2),
        "free_gb": round(disk.free / (1024 ** 3), 2),
        "usage_pct": round(disk.used / disk.total * 100, 1),
    }


# ─── HTML Report Builder ───────────────────────────────────────────

_CSS = """
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0f1923;color:#e2e8f0;padding:40px}
.report{max-width:1100px;margin:0 auto}
.header{text-align:center;margin-bottom:40px;padding-bottom:24px;border-bottom:2px solid #2d3748}
.header h1{font-size:2em;color:#fff;margin-bottom:4px}
.header .subtitle{color:#a0aec0;font-size:.95em}
.section{margin-bottom:32px}
.section h2{font-size:1.25em;color:#4299e1;margin-bottom:14px;display:flex;align-items:center;gap:8px;padding-bottom:8px;border-bottom:1px solid #2d3748}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:24px}
.kpi{background:#1a202c;border:1px solid #2d3748;border-radius:10px;padding:18px;text-align:center}
.kpi .val{font-size:1.8em;font-weight:700;line-height:1.2}
.kpi .label{font-size:.78em;color:#a0aec0;margin-top:2px}
.kpi.green .val{color:#48bb78}.kpi.red .val{color:#f56565}.kpi.blue .val{color:#4299e1}
.kpi.orange .val{color:#ed8936}.kpi.purple .val{color:#805ad5}
table{width:100%;border-collapse:collapse;background:#1a202c;border:1px solid #2d3748;border-radius:8px;overflow:hidden;margin-bottom:20px}
th{background:#2d3748;color:#a0aec0;padding:10px 14px;text-align:left;font-size:.82em;font-weight:600;text-transform:uppercase}
td{padding:10px 14px;border-top:1px solid #2d3748;font-size:.88em}
tr:hover{background:rgba(66,153,225,.05)}
.badge{display:inline-block;padding:2px 10px;border-radius:10px;font-size:.75em;font-weight:600}
.badge-ok{background:rgba(72,187,120,.15);color:#48bb78}
.badge-fail{background:rgba(245,101,101,.15);color:#f56565}
.badge-warn{background:rgba(237,137,54,.15);color:#ed8936}
.bar-bg{height:8px;background:#2d3748;border-radius:4px;overflow:hidden;margin-top:4px}
.bar-fill{height:100%;border-radius:4px;transition:width .4s}
.chart-placeholder{background:#1a202c;border:1px solid #2d3748;border-radius:10px;padding:20px;margin-bottom:16px;text-align:center}
.mini-chart{display:flex;align-items:flex-end;gap:3px;height:60px;justify-content:center}
.mini-bar{width:12px;border-radius:3px 3px 0 0;min-height:4px}
.error-item{background:#1a202c;border:1px solid #2d3748;border-radius:8px;padding:14px;margin-bottom:8px;border-left:3px solid #f56565}
.error-item .msg{font-size:.85em;color:#e2e8f0;margin-bottom:4px}
.error-item .meta{font-size:.75em;color:#a0aec0}
.footer{text-align:center;margin-top:40px;padding-top:20px;border-top:1px solid #2d3748;color:#a0aec0;font-size:.8em}
@media print{body{background:#fff;color:#1a202c;padding:20px}
  .kpi{background:#f7fafc;border-color:#e2e8f0}
  table{background:#fff;border-color:#e2e8f0}
  th{background:#edf2f7;color:#1a202c}
  td{border-color:#e2e8f0}
  .header h1{color:#1a202c}
  .section h2{color:#2b6cb0}
  .error-item{background:#fff;border-color:#e2e8f0;border-left-color:#e53e3e}
}
</style>
"""


def _fmt_bytes(b):
    if not b:
        return "0 B"
    for u in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(b) < 1024:
            return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} PB"


def _fmt_dur(s):
    if not s:
        return "—"
    s = float(s)
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s / 60:.0f}m {s % 60:.0f}s"
    return f"{s / 3600:.0f}h {(s % 3600) / 60:.0f}m"


def _fmt_date(d):
    if not d:
        return "—"
    if isinstance(d, str):
        return d[:19].replace('T', ' ')
    return d.strftime('%Y-%m-%d %H:%M:%S') if hasattr(d, 'strftime') else str(d)[:19]


def _rate_badge(rate):
    rate = float(rate or 0)
    cls = 'badge-ok' if rate >= 95 else 'badge-warn' if rate >= 80 else 'badge-fail'
    return f'<span class="badge {cls}">{rate:.1f}%</span>'


def _sla_badge(compliant):
    if compliant:
        return '<span class="badge badge-ok">Compliant</span>'
    return '<span class="badge badge-fail">Non-Compliant</span>'


def _bar_html(pct, color='#4299e1'):
    pct = min(100, max(0, float(pct or 0)))
    return f'<div class="bar-bg"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div>'


def _mini_chart_html(data_points: List[Dict], ok_key='ok', fail_key='fail', max_bars=30):
    if not data_points:
        return '<div class="chart-placeholder"><em>Sem dados para o período</em></div>'
    pts = data_points[-max_bars:]
    max_val = max(max((p.get(ok_key, 0) or 0) + (p.get(fail_key, 0) or 0) for p in pts), 1)
    bars = ''
    for p in pts:
        ok_h = int(((p.get(ok_key, 0) or 0) / max_val) * 50) + 4
        fail_h = int(((p.get(fail_key, 0) or 0) / max_val) * 50)
        bars += f'<div style="display:flex;flex-direction:column;gap:1px;align-items:center">'
        if fail_h > 0:
            bars += f'<div class="mini-bar" style="height:{fail_h}px;background:#f56565"></div>'
        bars += f'<div class="mini-bar" style="height:{ok_h}px;background:#48bb78"></div>'
        bars += '</div>'
    return f'<div class="mini-chart">{bars}</div>'


# ─── Report Types ──────────────────────────────────────────────────

def generate_executive_summary(days: int = 30) -> str:
    """Full executive summary report in HTML"""
    summary = collect_summary(days)
    tasks = collect_tasks_detail(days)
    trend = collect_daily_trend(days)
    engines = collect_engine_comparison(days)
    sla = collect_sla()
    repos = collect_repos()
    capacity = collect_capacity()
    errors = collect_errors(days, 10)
    now = datetime.now()

    compliant = sum(1 for s in sla if s.get('compliant'))
    sla_rate = round(compliant / len(sla) * 100, 1) if sla else 0

    html = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>GBOC Executive Report — {now.strftime('%d/%m/%Y')}</title>{_CSS}</head><body>
<div class="report">
<div class="header">
  <h1>📊 GBOC — Relatório Executivo de Backup</h1>
  <div class="subtitle">Período: últimos {days} dias • Gerado em: {now.strftime('%d/%m/%Y %H:%M:%S')}</div>
</div>

<div class="section">
  <h2>📈 Resumo Geral</h2>
  <div class="kpi-row">
    <div class="kpi blue"><div class="val">{summary['total_executions']}</div><div class="label">Execuções</div></div>
    <div class="kpi green"><div class="val">{summary['successful']}</div><div class="label">Sucesso</div></div>
    <div class="kpi red"><div class="val">{summary['failed']}</div><div class="label">Falhas</div></div>
    <div class="kpi {'green' if summary['success_rate']>=95 else 'orange' if summary['success_rate']>=80 else 'red'}"><div class="val">{summary['success_rate']}%</div><div class="label">Taxa de Sucesso</div></div>
    <div class="kpi purple"><div class="val">{_fmt_bytes(summary['total_bytes'])}</div><div class="label">Dados Protegidos</div></div>
    <div class="kpi blue"><div class="val">{_fmt_dur(summary['avg_duration_sec'])}</div><div class="label">Duração Média</div></div>
  </div>
  {_mini_chart_html(trend)}
</div>

<div class="section">
  <h2>🎯 Compliance SLA</h2>
  <div class="kpi-row">
    <div class="kpi {'green' if sla_rate>=95 else 'orange' if sla_rate>=80 else 'red'}"><div class="val">{sla_rate}%</div><div class="label">SLA Compliance Geral</div></div>
    <div class="kpi green"><div class="val">{compliant}/{len(sla)}</div><div class="label">Tarefas Compliant</div></div>
  </div>
  <table><thead><tr><th>Tarefa</th><th>Engine</th><th>Exec. 30d</th><th>Taxa</th><th>SLA</th><th>Último Sucesso</th></tr></thead><tbody>"""

    for s in sla:
        html += f"""<tr><td>{s['name']}</td><td>{s['engine']}</td><td>{s.get('total_30d',0) or 0}</td>
        <td>{_rate_badge(s['success_rate'])}</td><td>{_sla_badge(s.get('compliant'))}</td>
        <td>{_fmt_date(s.get('last_success'))}</td></tr>"""

    html += """</tbody></table></div>

<div class="section">
  <h2>📋 Detalhamento por Tarefa</h2>
  <table><thead><tr><th>Tarefa</th><th>Engine</th><th>Execuções</th><th>Sucesso</th><th>Falhas</th><th>Taxa</th><th>Dados</th><th>Duração Média</th><th>Última Exec.</th></tr></thead><tbody>"""

    for t in tasks:
        total = t.get('total', 0) or 0
        ok = t.get('ok', 0) or 0
        rate = round(ok / total * 100, 1) if total else 0
        html += f"""<tr><td><strong>{t['name']}</strong></td><td>{t['engine']}</td>
        <td>{total}</td><td>{ok}</td><td>{t.get('fail',0) or 0}</td>
        <td>{_rate_badge(rate)}</td><td>{_fmt_bytes(t.get('bytes',0))}</td>
        <td>{_fmt_dur(t.get('avg_dur'))}</td><td>{_fmt_date(t.get('last_run'))}</td></tr>"""

    html += """</tbody></table></div>

<div class="section">
  <h2>⚙️ Comparação de Engines</h2>
  <table><thead><tr><th>Engine</th><th>Execuções</th><th>Sucesso</th><th>Taxa</th><th>Dados Totais</th><th>Duração Média</th></tr></thead><tbody>"""

    for e in engines:
        total = e.get('total', 0) or 0
        ok = e.get('ok', 0) or 0
        rate = round(ok / total * 100, 1) if total else 0
        html += f"""<tr><td><strong>{e['engine']}</strong></td><td>{total}</td><td>{ok}</td>
        <td>{_rate_badge(rate)}</td><td>{_fmt_bytes(e.get('bytes',0))}</td>
        <td>{_fmt_dur(e.get('avg_dur'))}</td></tr>"""

    html += """</tbody></table></div>

<div class="section">
  <h2>🗄️ Repositórios</h2>
  <table><thead><tr><th>Nome</th><th>Engine</th><th>Tipo</th><th>Status</th><th>Tarefas</th></tr></thead><tbody>"""

    for r in repos:
        st_cls = 'badge-ok' if r['status'] == 'active' else 'badge-fail'
        html += f"""<tr><td>{r['name']}</td><td>{r['engine']}</td><td>{r['type']}</td>
        <td><span class="badge {st_cls}">{r['status']}</span></td><td>{r.get('task_count',0)}</td></tr>"""

    html += f"""</tbody></table></div>

<div class="section">
  <h2>💾 Capacidade de Armazenamento</h2>
  <div class="kpi-row">
    <div class="kpi blue"><div class="val">{capacity['total_gb']} GB</div><div class="label">Total</div></div>
    <div class="kpi orange"><div class="val">{capacity['used_gb']} GB</div><div class="label">Usado</div></div>
    <div class="kpi green"><div class="val">{capacity['free_gb']} GB</div><div class="label">Livre</div></div>
    <div class="kpi {'green' if capacity['usage_pct']<80 else 'orange' if capacity['usage_pct']<90 else 'red'}"><div class="val">{capacity['usage_pct']}%</div><div class="label">Utilização</div></div>
  </div>
  {_bar_html(capacity['usage_pct'], '#4299e1' if capacity['usage_pct']<80 else '#ed8936' if capacity['usage_pct']<90 else '#f56565')}
</div>"""

    if errors:
        html += """<div class="section"><h2>❌ Erros Recentes</h2>"""
        for e in errors:
            msg = (e.get('error_message') or 'Sem mensagem')[:200]
            html += f"""<div class="error-item">
              <div class="msg">{msg}</div>
              <div class="meta">{e.get('task_name','')} • {e.get('engine','')} • {_fmt_date(e.get('started_at'))}</div>
            </div>"""
        html += "</div>"

    html += f"""
<div class="footer">
  GBOC Agent 11.7c — Relatório gerado automaticamente em {now.strftime('%d/%m/%Y %H:%M:%S')}
</div>
</div></body></html>"""
    return html


def generate_sla_report(days: int = 30) -> str:
    """SLA compliance focused report"""
    sla = collect_sla()
    summary = collect_summary(days)
    now = datetime.now()
    compliant = sum(1 for s in sla if s.get('compliant'))
    sla_rate = round(compliant / len(sla) * 100, 1) if sla else 0

    html = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>GBOC SLA Report — {now.strftime('%d/%m/%Y')}</title>{_CSS}</head><body>
<div class="report">
<div class="header">
  <h1>🎯 GBOC — Relatório de Compliance SLA</h1>
  <div class="subtitle">Gerado em: {now.strftime('%d/%m/%Y %H:%M:%S')}</div>
</div>
<div class="section">
  <div class="kpi-row">
    <div class="kpi {'green' if sla_rate>=95 else 'red'}"><div class="val">{sla_rate}%</div><div class="label">SLA Compliance</div></div>
    <div class="kpi blue"><div class="val">{len(sla)}</div><div class="label">Tarefas Monitoradas</div></div>
    <div class="kpi green"><div class="val">{compliant}</div><div class="label">Compliant</div></div>
    <div class="kpi red"><div class="val">{len(sla)-compliant}</div><div class="label">Non-Compliant</div></div>
  </div>
  <table><thead><tr><th>Tarefa</th><th>Engine</th><th>Execuções (30d)</th><th>Sucesso</th><th>Taxa</th><th>SLA</th><th>Último Sucesso</th><th>Última Falha</th></tr></thead><tbody>"""

    for s in sla:
        html += f"""<tr><td><strong>{s['name']}</strong></td><td>{s['engine']}</td>
        <td>{s.get('total_30d',0) or 0}</td><td>{s.get('ok_30d',0) or 0}</td>
        <td>{_rate_badge(s['success_rate'])}</td><td>{_sla_badge(s.get('compliant'))}</td>
        <td>{_fmt_date(s.get('last_success'))}</td><td>{_fmt_date(s.get('last_failure'))}</td></tr>"""

    html += f"""</tbody></table></div>
<div class="footer">GBOC Agent 11.7c — Relatório SLA gerado em {now.strftime('%d/%m/%Y %H:%M:%S')}</div>
</div></body></html>"""
    return html


def generate_capacity_report() -> str:
    """Storage capacity and forecast report"""
    capacity = collect_capacity()
    repos = collect_repos()
    trend = collect_daily_trend(90)
    now = datetime.now()

    # Simple growth estimation
    total_bytes_recent = sum(r.get('total', 0) or 0 for r in _query("""
        SELECT SUM(bytes_processed) as total FROM task_executions
        WHERE started_at >= NOW() - INTERVAL '30 days' AND status='completed'
    """))
    daily_growth_gb = round((total_bytes_recent or 0) / (1024**3) / 30, 2)
    days_until_full = int(capacity['free_gb'] / daily_growth_gb) if daily_growth_gb > 0 else None

    html = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>GBOC Capacity Report — {now.strftime('%d/%m/%Y')}</title>{_CSS}</head><body>
<div class="report">
<div class="header">
  <h1>💾 GBOC — Relatório de Capacidade</h1>
  <div class="subtitle">Gerado em: {now.strftime('%d/%m/%Y %H:%M:%S')}</div>
</div>
<div class="section">
  <h2>📊 Visão Geral de Armazenamento</h2>
  <div class="kpi-row">
    <div class="kpi blue"><div class="val">{capacity['total_gb']} GB</div><div class="label">Capacidade Total</div></div>
    <div class="kpi orange"><div class="val">{capacity['used_gb']} GB</div><div class="label">Espaço Usado</div></div>
    <div class="kpi green"><div class="val">{capacity['free_gb']} GB</div><div class="label">Espaço Livre</div></div>
    <div class="kpi {'green' if capacity['usage_pct']<80 else 'red'}"><div class="val">{capacity['usage_pct']}%</div><div class="label">Utilização</div></div>
  </div>
  {_bar_html(capacity['usage_pct'], '#4299e1' if capacity['usage_pct']<80 else '#f56565')}
</div>
<div class="section">
  <h2>📈 Previsão de Crescimento</h2>
  <div class="kpi-row">
    <div class="kpi blue"><div class="val">{daily_growth_gb} GB/dia</div><div class="label">Crescimento Diário</div></div>
    <div class="kpi blue"><div class="val">{round(daily_growth_gb*30,1)} GB/mês</div><div class="label">Crescimento Mensal</div></div>
    <div class="kpi {'green' if not days_until_full or days_until_full>180 else 'orange' if days_until_full>60 else 'red'}"><div class="val">{days_until_full or '∞'} dias</div><div class="label">Dias até Cheio</div></div>
  </div>
</div>
<div class="section">
  <h2>🗄️ Repositórios</h2>
  <table><thead><tr><th>Nome</th><th>Engine</th><th>Tipo</th><th>Status</th><th>Tarefas</th></tr></thead><tbody>"""

    for r in repos:
        st = 'badge-ok' if r['status'] == 'active' else 'badge-fail'
        html += f"""<tr><td>{r['name']}</td><td>{r['engine']}</td><td>{r['type']}</td>
        <td><span class="badge {st}">{r['status']}</span></td><td>{r.get('task_count',0)}</td></tr>"""

    html += f"""</tbody></table></div>
<div class="footer">GBOC Agent 11.7c — Relatório de Capacidade gerado em {now.strftime('%d/%m/%Y %H:%M:%S')}</div>
</div></body></html>"""
    return html


def generate_error_report(days: int = 30) -> str:
    """Detailed error analysis report"""
    errors = collect_errors(days, 50)
    summary = collect_summary(days)
    now = datetime.now()

    # Group errors by task
    by_task = {}
    for e in errors:
        name = e.get('task_name', 'Unknown')
        by_task.setdefault(name, []).append(e)

    html = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>GBOC Error Report — {now.strftime('%d/%m/%Y')}</title>{_CSS}</head><body>
<div class="report">
<div class="header">
  <h1>❌ GBOC — Relatório de Erros</h1>
  <div class="subtitle">Últimos {days} dias • Gerado em: {now.strftime('%d/%m/%Y %H:%M:%S')}</div>
</div>
<div class="section">
  <div class="kpi-row">
    <div class="kpi red"><div class="val">{summary['failed']}</div><div class="label">Total de Falhas</div></div>
    <div class="kpi blue"><div class="val">{summary['total_executions']}</div><div class="label">Total Execuções</div></div>
    <div class="kpi orange"><div class="val">{len(by_task)}</div><div class="label">Tarefas Afetadas</div></div>
  </div>
</div>"""

    for task_name, task_errors in by_task.items():
        html += f"""<div class="section"><h2>📋 {task_name} ({len(task_errors)} erros)</h2>"""
        for e in task_errors[:10]:
            msg = (e.get('error_message') or 'Sem mensagem')[:300]
            html += f"""<div class="error-item">
              <div class="msg">{msg}</div>
              <div class="meta">{e.get('engine','')} • {_fmt_date(e.get('started_at'))}</div>
            </div>"""
        html += "</div>"

    html += f"""<div class="footer">GBOC Agent 11.7c — Relatório de Erros gerado em {now.strftime('%d/%m/%Y %H:%M:%S')}</div>
</div></body></html>"""
    return html


# Map of report types
REPORT_TYPES = {
    "executive": {"fn": generate_executive_summary, "label": "Relatório Executivo", "desc": "Resumo completo de backup, SLA, capacidade e erros"},
    "sla": {"fn": generate_sla_report, "label": "Relatório SLA", "desc": "Compliance de SLA por tarefa"},
    "capacity": {"fn": generate_capacity_report, "label": "Relatório de Capacidade", "desc": "Uso de armazenamento e previsão de crescimento"},
    "errors": {"fn": generate_error_report, "label": "Relatório de Erros", "desc": "Análise detalhada de falhas"},
}

