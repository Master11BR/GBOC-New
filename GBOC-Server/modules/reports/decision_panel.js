/* GBOC Server — Painel de Decisão (Dashboard Central)
 * Gráficos para decisão rápida: proteção dentro do RPO, tendência de sucesso, quem mais falha,
 * idade do último backup por agente, armazenamento com projeção e ações prioritárias.
 * Dados: GET /api/v1/analytics/decision (mesmos critérios dos relatórios).
 */
(function () {
    'use strict';
    const base = () => (window.GBOC_API_BASE || '');
    const esc = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const ST = { ok: '#0ca30c', warn: '#fab219', serious: '#ec835a', bad: '#d03b3b', neutral: '#8a8984' };
    const charts = {};
    let days = 14, timer = null, busy = false;

    function css(name, fallback) {
        const v = getComputedStyle(document.body).getPropertyValue(name).trim();
        return v || fallback;
    }
    function bytes(b) {
        if (b == null) return '—';
        const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']; let i = 0; let n = Math.abs(+b);
        while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
        return (b < 0 ? '-' : '') + n.toLocaleString('pt-BR', { maximumFractionDigits: n < 100 ? 1 : 0 }) + ' ' + u[i];
    }
    function age(h) {
        if (h == null) return 'nunca';
        if (h < 1) return Math.round(h * 60) + ' min';
        if (h < 48) return h.toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' h';
        return (h / 24).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' dias';
    }
    const pct = (v) => v == null ? '—' : v.toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + '%';
    const tone = (v, goal) => v == null ? 'neutral' : v >= goal ? 'ok' : v >= goal - 10 ? 'warn' : 'bad';

    function shell(root) {
        root.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin:4px 0 12px">
            <h3 style="margin:0;font-size:1.05em"><i class="fas fa-compass" style="color:var(--primary);margin-right:6px"></i> Painel de Decisão</h3>
            <div style="display:flex;gap:6px;align-items:center">
                <span id="dp-updated" style="font-size:.78em;color:var(--text-muted)"></span>
                <div class="period-btns">
                    ${[7, 14, 30, 90, 180, 365].map(d => `<button class="period-btn ${d === days ? 'active' : ''}" data-days="${d}">${d === 365 ? '1A' : d === 180 ? '6M' : d + 'D'}</button>`).join('')}
                </div>
            </div>
        </div>
        <div class="kpi-grid" id="dp-kpis" style="margin-bottom:14px"></div>
        <div class="charts-row" style="margin-bottom:14px">
            <div class="chart-panel"><h3 style="margin:0 0 10px;font-size:.92em">Execuções por dia</h3><div style="height:220px"><canvas id="dp-runs"></canvas></div></div>
            <div class="chart-panel"><h3 style="margin:0 0 10px;font-size:.92em">Taxa de sucesso diária <span id="dp-goal" style="color:var(--text-muted);font-weight:400"></span></h3><div style="height:220px"><canvas id="dp-rate"></canvas></div></div>
        </div>
        <div class="charts-row" style="margin-bottom:14px">
            <div class="chart-panel"><h3 style="margin:0 0 10px;font-size:.92em">Idade do último backup válido (pior tarefa de cada agente)</h3><div id="dp-age-wrap" style="height:260px"><canvas id="dp-age"></canvas></div></div>
            <div class="chart-panel"><h3 style="margin:0 0 10px;font-size:.92em">Agentes com mais falhas</h3><div id="dp-fail-wrap" style="height:260px"><canvas id="dp-fail"></canvas></div></div>
        </div>
        <div class="charts-row" style="margin-bottom:14px">
            <div class="chart-panel"><h3 style="margin:0 0 10px;font-size:.92em">Armazenamento ocupado e projeção de 30 dias</h3><div style="height:230px"><canvas id="dp-storage"></canvas></div></div>
            <div class="chart-panel"><h3 style="margin:0 0 10px;font-size:.92em"><i class="fas fa-list-check" style="color:var(--warning)"></i> Ações prioritárias</h3><div id="dp-actions" style="max-height:230px;overflow-y:auto"></div></div>
        </div>`;
        root.querySelectorAll('[data-days]').forEach(b => b.addEventListener('click', () => {
            days = +b.dataset.days;
            root.querySelectorAll('[data-days]').forEach(x => x.classList.toggle('active', x === b));
            load();
        }));
    }

    function kpis(k) {
        const rpoT = k.rpo_pct == null ? 'neutral' : (k.rpo_pct >= 100 ? 'ok' : k.rpo_pct >= 90 ? 'warn' : 'bad');
        const tiles = [
            ['Proteção dentro do RPO', pct(k.rpo_pct), `${k.tasks_in_rpo}/${k.tasks_total} tarefas · alvo ${k.rpo_target_h} h`, rpoT, 'fa-shield-halved'],
            ['Sucesso nas últimas 24 h', pct(k.success_24h_pct), `${k.runs_24h} execuções · meta ${k.success_goal}%`, tone(k.success_24h_pct, k.success_goal), 'fa-circle-check'],
            ['Agentes online', `${k.agents_online}/${k.agents_total}`, k.agents_online === k.agents_total ? 'todos comunicando' : `${k.agents_total - k.agents_online} sem comunicação`, k.agents_online === k.agents_total ? 'ok' : 'bad', 'fa-server'],
            ['Falhas pendentes', String(k.pending_failures), 'aguardando retentativa/resolução', k.pending_failures ? 'bad' : 'ok', 'fa-triangle-exclamation'],
            ['Armazenamento ocupado', bytes(k.storage_total), k.storage_growth_month ? `+${bytes(k.storage_growth_month)}/mês · ${k.repos_at_risk} repositório(s) em risco` : `${k.repos_at_risk} repositório(s) em risco`, k.repos_at_risk ? 'bad' : 'neutral', 'fa-hard-drive'],
        ];
        document.getElementById('dp-kpis').innerHTML = tiles.map(([l, v, s, t, i]) => `
            <div class="kpi-card" style="border-top:3px solid ${t === 'neutral' ? 'var(--primary)' : ST[t]}">
                <div class="kpi-header"><span>${esc(l)}</span><div class="kpi-icon" style="color:${t === 'neutral' ? 'var(--primary)' : ST[t]}"><i class="fas ${i}"></i></div></div>
                <div class="kpi-value">${esc(v)}</div><div class="kpi-sub">${t !== 'neutral' ? `<i class="fas fa-${t === 'ok' ? 'check' : t === 'warn' ? 'exclamation' : 'xmark'}" style="color:${ST[t]}"></i> ` : ''}${esc(s)}</div>
            </div>`).join('');
    }

    function draw(id, cfg) {
        if (typeof Chart === 'undefined') return;
        if (charts[id]) charts[id].destroy();
        const el = document.getElementById(id);
        if (el) charts[id] = new Chart(el.getContext('2d'), cfg);
    }

    function baseOpts(extra) {
        const ink = css('--text-muted', '#9aa'), grid = css('--border', 'rgba(128,128,128,.2)');
        return Object.assign({
            responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
            plugins: { legend: { labels: { color: ink, boxWidth: 12 } }, tooltip: { mode: 'index', intersect: false } },
            scales: { x: { ticks: { color: ink, maxRotation: 0, autoSkip: true, maxTicksLimit: 10 }, grid: { color: grid, display: false } },
                      y: { ticks: { color: ink }, grid: { color: grid }, beginAtZero: true } }
        }, extra || {});
    }

    function render(d) {
        kpis(d.kpis);
        const primary = css('--primary', '#2a78d6');
        document.getElementById('dp-goal').textContent = `· meta ${d.kpis.success_goal}%`;
        draw('dp-runs', { type: 'bar', data: { labels: d.daily.labels, datasets: [
            { label: 'Sucesso', data: d.daily.success, backgroundColor: ST.ok, stack: 's', borderRadius: 3 },
            { label: 'Falha', data: d.daily.failed, backgroundColor: ST.bad, stack: 's', borderRadius: 3 }] },
            options: baseOpts({ scales: { x: { stacked: true, ticks: { color: css('--text-muted', '#999'), maxTicksLimit: 10 }, grid: { display: false } },
                                          y: { stacked: true, beginAtZero: true, ticks: { color: css('--text-muted', '#999'), precision: 0 }, grid: { color: css('--border', '#333') } } } }) });
        draw('dp-rate', { type: 'line', data: { labels: d.daily.labels, datasets: [
            { label: 'Taxa de sucesso', data: d.daily.rate, borderColor: primary, backgroundColor: primary, borderWidth: 2, pointRadius: 3, spanGaps: true, tension: .25 },
            { label: 'Meta', data: d.daily.labels.map(() => d.kpis.success_goal), borderColor: ST.bad, borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0 }] },
            options: baseOpts({ scales: { x: { ticks: { color: css('--text-muted', '#999'), maxTicksLimit: 10 }, grid: { display: false } },
                                          y: { min: 0, max: 100, ticks: { color: css('--text-muted', '#999'), callback: v => v + '%' }, grid: { color: css('--border', '#333') } } } }) });
        const ages = d.backup_age || [];
        document.getElementById('dp-age-wrap').style.height = Math.max(160, 30 + ages.length * 26) + 'px';
        draw('dp-age', { type: 'bar', data: { labels: ages.map(a => a.host), datasets: [{ label: 'Idade (h)',
            data: ages.map(a => a.age_h == null ? (d.kpis.rpo_target_h * 2) : +a.age_h.toFixed(1)),
            backgroundColor: ages.map(a => ST[a.tone] || ST.neutral), borderRadius: 3 }] },
            options: baseOpts({ indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: {
                label: (c) => { const a = ages[c.dataIndex]; return `${a.task}: ${a.age_h == null ? 'nunca concluiu com sucesso' : age(a.age_h)} (alvo ${a.target_h.toFixed(0)} h)`; } } } },
                scales: { x: { beginAtZero: true, ticks: { color: css('--text-muted', '#999'), callback: v => v + 'h' }, grid: { color: css('--border', '#333') } },
                          y: { ticks: { color: css('--text', '#ddd') }, grid: { display: false } } } }) });
        const fl = d.failures_by_agent || [];
        document.getElementById('dp-fail-wrap').style.height = Math.max(160, 30 + fl.length * 26) + 'px';
        if (!fl.length) {
            if (charts['dp-fail']) { charts['dp-fail'].destroy(); delete charts['dp-fail']; }
            document.getElementById('dp-fail-wrap').innerHTML = '<div style="padding:40px;text-align:center;color:var(--success)"><i class="fas fa-circle-check"></i> Nenhuma falha no período</div>';
        } else {
            if (!document.getElementById('dp-fail')) document.getElementById('dp-fail-wrap').innerHTML = '<canvas id="dp-fail"></canvas>';
            draw('dp-fail', { type: 'bar', data: { labels: fl.map(a => a.host), datasets: [{ label: 'Falhas', data: fl.map(a => a.failures), backgroundColor: ST.bad, borderRadius: 3 }] },
                options: baseOpts({ indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${fl[c.dataIndex].failures} falhas · ${fl[c.dataIndex].rate}% de sucesso` } } },
                    scales: { x: { beginAtZero: true, ticks: { color: css('--text-muted', '#999'), precision: 0 }, grid: { color: css('--border', '#333') } },
                              y: { ticks: { color: css('--text', '#ddd') }, grid: { display: false } } } }) });
        }
        const st = d.storage;
        const labels = st.labels.concat(st.proj_labels);
        draw('dp-storage', { type: 'line', data: { labels, datasets: [
            { label: 'Ocupado', data: st.values.concat(st.proj_labels.map(() => null)), borderColor: primary, backgroundColor: primary, borderWidth: 2, pointRadius: 2, spanGaps: true },
            { label: 'Projeção (tendência)', data: st.values.map((v, i) => i === st.values.length - 1 ? v : null).concat(st.projection),
              borderColor: primary, borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, spanGaps: true }] },
            options: baseOpts({ plugins: { legend: { labels: { color: css('--text-muted', '#999'), boxWidth: 12 } }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${bytes(c.parsed.y)}` } } },
                scales: { x: { ticks: { color: css('--text-muted', '#999'), maxTicksLimit: 10 }, grid: { display: false } },
                          y: { beginAtZero: true, ticks: { color: css('--text-muted', '#999'), callback: v => bytes(v) }, grid: { color: css('--border', '#333') } } } }) });
        const acts = d.actions || [];
        document.getElementById('dp-actions').innerHTML = acts.length ? acts.map(a => `
            <div style="display:flex;gap:10px;align-items:flex-start;padding:8px 6px;border-bottom:1px solid var(--border)">
                <i class="fas fa-${a.severity === 'bad' ? 'circle-xmark' : 'triangle-exclamation'}" style="color:${ST[a.severity] || ST.warn};margin-top:3px"></i>
                <div style="flex:1;font-size:.86em">${esc(a.text)}</div>
                ${a.report ? `<button class="btn btn-sm" title="Abrir relatório ${esc(a.report)}" data-rep="${esc(a.report)}" data-agent="${esc(a.agent_id || '')}">${esc(a.report)}</button>` : ''}
            </div>`).join('') : '<div style="padding:30px;text-align:center;color:var(--success)"><i class="fas fa-circle-check"></i> Nenhuma ação pendente</div>';
        document.querySelectorAll('#dp-actions [data-rep]').forEach(b => b.addEventListener('click', () => {
            if (typeof switchTab === 'function') switchTab('reports');
            setTimeout(() => {
                const sel = document.getElementById('rc-agent');
                if (sel && b.dataset.agent) sel.value = b.dataset.agent;
                if (window.GBOCReportCenter) GBOCReportCenter.open('real', b.dataset.rep);
            }, 600);
        }));
        document.getElementById('dp-updated').textContent = 'Atualizado ' + new Date().toLocaleTimeString('pt-BR');
    }

    async function load() {
        if (busy) return;
        busy = true;
        try {
            const r = await fetch(`${base()}/api/v1/analytics/decision?days=${days}`);
            const d = await r.json();
            if (!r.ok || d.status !== 'success') throw new Error(d.detail || d.message || 'HTTP ' + r.status);
            render(d);
        } catch (e) {
            const k = document.getElementById('dp-kpis');
            if (k) k.innerHTML = `<div style="grid-column:1/-1;color:var(--danger)">Painel de decisão indisponível: ${esc(e.message)}</div>`;
        } finally { busy = false; }
    }

    function init() {
        const root = document.getElementById('decision-panel');
        if (!root) return;
        shell(root);
        load();
        clearInterval(timer);
        timer = setInterval(() => {
            const tab = document.getElementById('tab-overview');
            if (!document.hidden && tab && tab.classList.contains('active')) load();
        }, 60000);
    }

    window.GBOCDecisionPanel = { init, reload: load };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
