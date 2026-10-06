/*
 * GBOC — gráficos com opções (arquivo idêntico no Agente e no Server).
 *
 * Carregado pelo gboc-layout-manager.js em todas as telas. Para TODO gráfico Chart.js:
 *   • estilo único e legível (fonte, linhas finas, barras com cantos arredondados, grade discreta, dica ao passar
 *     o mouse com todos os valores do ponto) — acompanha o tema claro/escuro;
 *   • barra de opções: Formato (linha, área, barras, barras empilhadas / rosca, pizza, barras), Tabela de dados,
 *     Exportar PNG/CSV e Expandir. O formato escolhido fica salvo por gráfico;
 *   • Período / agrupamento / métrica quando a tela registra um carregador (GBOCCharts.options(...)).
 *
 * Uso numa tela (opcional, para período real vindo da API):
 *   GBOCCharts.options('chartTrend', {
 *       periods: [7, 30, 90, 365], period: 7,                 // dias (0 = todo o período)
 *       groups: ['auto','day','week','month'],                 // agrupamento (opcional)
 *       metrics: [{id:'volume', label:'Volume (GB)'}, ...],    // métrica (opcional, um eixo por vez)
 *       custom: true,                                          // permite "De … até …"
 *       onChange: (s) => recarregar(s)                         // s = {period, from, to, group, metric}
 *   });
 */
(function () {
    'use strict';
    if (window.GBOCCharts) return;

    const LS = 'gboc-chart-prefs';
    const regs = {};               // id -> opções registradas pela tela
    const state = {};              // id -> {period, from, to, group, metric}
    let prefs = {};
    try { prefs = JSON.parse(localStorage.getItem(LS) || '{}') || {}; } catch (e) { prefs = {}; }
    const savePrefs = () => { try { localStorage.setItem(LS, JSON.stringify(prefs)); } catch (e) { /* sem storage */ } };

    const CIRCULAR = ['doughnut', 'pie', 'polarArea'];
    const ORIG = new WeakMap();    // dataset -> cor de fundo original (para voltar de "área" para "barras")
    const FORMATS_XY = [['line', 'Linha'], ['area', 'Área'], ['bar', 'Barras'], ['stacked', 'Barras empilhadas']];
    const FORMATS_CIRC = [['doughnut', 'Rosca'], ['pie', 'Pizza'], ['hbar', 'Barras']];
    const PERIOD_LABEL = { 1: '24 h', 7: '7 dias', 14: '14 dias', 30: '30 dias', 90: '90 dias', 180: '6 meses', 365: '1 ano', 730: '2 anos', 0: 'Tudo' };
    const GROUP_LABEL = { auto: 'Automático', hour: 'Por hora', day: 'Por dia', week: 'Por semana', month: 'Por mês' };

    const css = (name, fb) => {
        const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return v || fb;
    };
    const isLight = () => {
        const t = document.documentElement.getAttribute('data-color-theme') || document.documentElement.getAttribute('data-theme') || '';
        return /light/.test(t);
    };
    const ink = () => ({
        text: css('--text-primary', isLight() ? '#0f172a' : '#e5e7eb'),
        muted: css('--text-muted', isLight() ? '#64748b' : '#94a3b8'),
        grid: isLight() ? 'rgba(15,23,42,0.07)' : 'rgba(255,255,255,0.06)',
        surface: css('--bg-card', isLight() ? '#ffffff' : '#111318'),
    });
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const chartId = (ch) => (ch.canvas && (ch.canvas.id || ch.canvas.getAttribute('data-chart-id'))) || ('chart-' + ch.id);
    const alpha = (c, a) => {
        if (typeof c !== 'string') return c;
        const m = c.match(/^#([0-9a-f]{6})$/i);
        if (m) { const n = parseInt(m[1], 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; }
        const r = c.match(/^rgba?\(([^)]+)\)$/i);
        if (r) { const p = r[1].split(',').map(s => s.trim()); return `rgba(${p[0]},${p[1]},${p[2]},${a})`; }
        return c;
    };
    const solid = (c) => (Array.isArray(c) ? c[0] : c);

    // ── Estilo global ──────────────────────────────────────────────────────────
    function applyDefaults(Chart) {
        const k = ink();
        const d = Chart.defaults;
        d.font.family = "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif";
        d.font.size = 12;
        d.locale = 'pt-BR';                     // 35.000 / 1,5 (antes 35,000 / 1.5)
        d.color = k.muted;
        d.borderColor = k.grid;
        d.maintainAspectRatio = false;
        d.interaction = Object.assign({}, d.interaction, { mode: 'index', intersect: false });
        d.animation = Object.assign({}, d.animation, { duration: 350 });
        const pl = d.plugins;
        pl.legend.labels.usePointStyle = true;
        pl.legend.labels.pointStyle = 'circle';
        pl.legend.labels.boxWidth = 8;
        pl.legend.labels.boxHeight = 8;
        pl.legend.labels.padding = 14;
        pl.legend.labels.color = k.muted;
        // Legenda com bolinha cheia na cor da série (antes: círculo vazado quando a série não tinha preenchimento)
        if (!pl.legend.labels.$gbocGen) {
            const gen = pl.legend.labels.generateLabels;
            const faint = (c) => !c || c === 'transparent' || /rgba\([^)]*,\s*0(\.\d+)?\s*\)$/.test(String(c));
            pl.legend.labels.generateLabels = function (chart) {
                return gen.call(this, chart).map(l => {
                    if (typeof l.strokeStyle === 'string' && faint(l.fillStyle)) l.fillStyle = l.strokeStyle;
                    if (typeof l.fillStyle === 'string' && /^rgba\(/.test(l.fillStyle)) l.fillStyle = l.fillStyle.replace(/,\s*[\d.]+\s*\)$/, ',1)');
                    l.lineWidth = 0; l.lineDash = [];
                    return l;
                });
            };
            pl.legend.labels.$gbocGen = true;
        }
        pl.tooltip.backgroundColor = isLight() ? 'rgba(255,255,255,0.97)' : 'rgba(17,19,24,0.96)';
        pl.tooltip.titleColor = k.text;
        pl.tooltip.bodyColor = k.text;
        pl.tooltip.borderColor = isLight() ? 'rgba(15,23,42,0.12)' : 'rgba(255,255,255,0.12)';
        pl.tooltip.borderWidth = 1;
        pl.tooltip.padding = 10;
        pl.tooltip.cornerRadius = 8;
        pl.tooltip.usePointStyle = true;
        pl.tooltip.boxPadding = 4;
        d.elements.line.borderWidth = 2;
        d.elements.line.tension = 0.3;
        d.elements.point.radius = 0;
        d.elements.point.hoverRadius = 5;
        d.elements.point.hitRadius = 12;
        d.elements.bar.borderRadius = 4;
        d.elements.bar.borderSkipped = 'start';
        d.elements.arc.borderWidth = 2;
        d.elements.arc.borderColor = k.surface;
        d.scale.grid.color = k.grid;
        d.scale.grid.tickColor = 'transparent';
        d.scale.border = Object.assign({}, d.scale.border, { display: false });
        d.scale.ticks.color = k.muted;
    }

    // Reaplica cores de texto/grade em gráficos que fixaram cores escuras (#a0aec0 etc.) — legível nos dois temas
    // Sempre o objeto de configuração cru (ch.config.options): ch.options é um Proxy do Chart.js e copiar/espalhar
    // as propriedades dele quebra (TypeError t.startsWith).
    const rawOpts = (ch) => { const c = ch.config; if (!c.options) c.options = {}; return c.options; };

    function harmonize(ch) {
        const k = ink();
        const o = rawOpts(ch);
        if (o.plugins && o.plugins.legend && o.plugins.legend.labels) o.plugins.legend.labels.color = k.muted;
        Object.values(o.scales || {}).forEach(s => {
            if (!s) return;
            if (s.ticks && !/^#(4299e1|48bb78|f56565)/i.test(String(s.ticks.color || ''))) s.ticks.color = k.muted;
            if (s.grid && s.grid.display !== false) s.grid.color = k.grid;
            s.border = Object.assign({}, s.border, { display: false });
        });
    }

    // ── Formato do gráfico ──────────────────────────────────────────────────────
    function baseType(ch) {
        if (!ch.$gbocBase) ch.$gbocBase = { type: ch.config.type, indexAxis: rawOpts(ch).indexAxis };
        return ch.$gbocBase.type;
    }
    function formatsFor(ch) { return CIRCULAR.includes(baseType(ch)) ? FORMATS_CIRC : FORMATS_XY; }
    function currentFormat(ch, natural) {
        const id = chartId(ch);
        if (!natural && prefs[id] && prefs[id].format) return prefs[id].format;
        const t = baseType(ch);
        if (CIRCULAR.includes(t)) return t === 'polarArea' ? 'doughnut' : t;
        if (t === 'line') return (ch.data.datasets || []).some(d => d.fill && d.fill !== false) ? 'area' : 'line';
        if (t === 'bar') { const sc = rawOpts(ch).scales; return sc && sc.x && sc.x.stacked ? 'stacked' : 'bar'; }
        return null;
    }
    function applyFormat(ch, fmt, persist) {
        const t = baseType(ch);
        if (!['line', 'bar', ...CIRCULAR].includes(t) || !fmt) return;
        const sets = ch.data.datasets || [];
        const o = rawOpts(ch);
        if (CIRCULAR.includes(t)) {
            if (fmt === 'hbar') {
                ch.config.type = 'bar';
                o.indexAxis = 'y';
                o.scales = o.scales || {};
                o.scales.x = Object.assign({ beginAtZero: true }, o.scales.x || {});
                o.scales.y = Object.assign({ grid: { display: false } }, o.scales.y || {});
                if (o.plugins && o.plugins.legend) o.plugins.legend.display = false;
                sets.forEach(d => { d.borderRadius = 4; d.borderWidth = 0; });
            } else {
                ch.config.type = fmt;
                o.indexAxis = ch.$gbocBase.indexAxis;
                if (o.plugins && o.plugins.legend) o.plugins.legend.display = true;
                sets.forEach(d => { d.borderWidth = 2; });
            }
        } else {
            const own = sets.filter(d => !d.type || d.type === t || ORIG.has(d));
            own.forEach(d => { if (!ORIG.has(d)) ORIG.set(d, d.backgroundColor); });
            if (fmt === 'line' || fmt === 'area') {
                ch.config.type = 'line';
                own.forEach(d => {
                    delete d.type;
                    const c = solid(d.borderColor) || solid(ORIG.get(d));
                    d.borderColor = c;
                    d.fill = fmt === 'area' ? 'origin' : false;
                    d.backgroundColor = fmt === 'area' ? alpha(c, 0.18) : c;
                    d.borderWidth = 2; d.pointRadius = 0;
                });
            } else {
                ch.config.type = 'bar';
                own.forEach(d => {
                    delete d.type;
                    const c = solid(d.borderColor) || solid(ORIG.get(d));
                    d.backgroundColor = Array.isArray(ORIG.get(d)) ? ORIG.get(d) : alpha(c, 0.85);
                    d.borderColor = c; d.borderWidth = 0; d.borderRadius = 4; d.fill = false;
                    d.maxBarThickness = 28;
                });
            }
            o.scales = o.scales || {};
            const stacked = fmt === 'stacked';
            ['x', 'y'].forEach(ax => { o.scales[ax] = Object.assign({}, o.scales[ax] || {}, { stacked }); });
            o.scales.x.offset = (fmt === 'bar' || fmt === 'stacked');   // barras não ficam cortadas nas bordas
        }
        if (persist) { const id = chartId(ch); prefs[id] = Object.assign({}, prefs[id], { format: fmt }); savePrefs(); }
        try { ch.update(); } catch (e) { console.warn('[GBOCCharts] formato:', e); }
    }

    // ── Tabela, exportação e tela cheia ─────────────────────────────────────────
    function rows(ch) {
        const labels = ch.data.labels || [];
        const sets = (ch.data.datasets || []).filter(d => !d.hidden);
        const head = ['', ...sets.map(d => d.label || 'Valor')];
        const body = labels.map((l, i) => [Array.isArray(l) ? l.join(' ') : l, ...sets.map(d => {
            const v = d.data[i];
            return v && typeof v === 'object' ? (v.y ?? v.r ?? '') : (v ?? '');
        })]);
        return { head, body };
    }
    const fmtNum = (v) => typeof v === 'number' ? v.toLocaleString('pt-BR', { maximumFractionDigits: 2 }) : esc(v);
    function toggleTable(ch, bar) {
        const card = bar.parentElement;
        let t = card.querySelector(':scope > .gboc-chart-table');
        if (t) { t.remove(); return; }
        const { head, body } = rows(ch);
        t = document.createElement('div');
        t.className = 'gboc-chart-table';
        t.innerHTML = `<table><thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
            <tbody>${body.map(r => `<tr>${r.map((c, i) => i ? `<td>${fmtNum(c)}</td>` : `<th>${esc(c)}</th>`).join('')}</tr>`).join('') ||
            `<tr><td colspan="${head.length}">Sem dados no período</td></tr>`}</tbody></table>`;
        card.appendChild(t);
    }
    function download(name, url) {
        const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
    }
    function exportCSV(ch) {
        const { head, body } = rows(ch);
        const q = (v) => { const s = String(v ?? ''); return /[";\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
        const csv = '﻿' + [head, ...body].map(r => r.map(q).join(';')).join('\r\n');
        const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
        download(chartId(ch) + '.csv', url); setTimeout(() => URL.revokeObjectURL(url), 2000);
    }
    function exportPNG(ch) {
        const src = ch.canvas;
        const c = document.createElement('canvas'); c.width = src.width; c.height = src.height;
        const g = c.getContext('2d'); g.fillStyle = ink().surface; g.fillRect(0, 0, c.width, c.height); g.drawImage(src, 0, 0);
        download(chartId(ch) + '.png', c.toDataURL('image/png'));
    }
    function toggleExpand(ch, bar) {
        const card = bar.parentElement;
        const on = !card.classList.contains('gboc-chart-expanded');
        card.classList.toggle('gboc-chart-expanded', on);
        document.body.classList.toggle('gboc-chart-expanded-open', on);
        setTimeout(() => ch.resize(), 60);
    }

    // ── Barra de opções ─────────────────────────────────────────────────────────
    function cardOf(canvas) {
        return canvas.closest('.card, .chart-card, .chart-panel, .chart-container, .glass-card, .panel, .stat-card, .chart-box, .dp-card, .rpt-card') ||
            (canvas.parentElement && canvas.parentElement.parentElement) || canvas.parentElement;
    }
    function selectHtml(cls, title, opts, cur) {
        return `<label class="gboc-cb-sel" title="${esc(title)}"><span>${esc(title)}</span><select data-k="${cls}">${opts.map(([v, l]) =>
            `<option value="${esc(v)}" ${String(v) === String(cur) ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></label>`;
    }
    function buildBar(ch) {
        const canvas = ch.canvas;
        if (!canvas || !canvas.isConnected) return;
        const host = canvas.parentElement;
        if (!host || host.querySelector(':scope > .gboc-chart-bar') || (host.parentElement && host.parentElement.querySelector(':scope > .gboc-chart-bar[data-for="' + chartId(ch) + '"]'))) {
            return;   // barra já existe (gráfico recriado pela tela ao trocar o período)
        }
        const card = cardOf(canvas);
        const id = chartId(ch);
        const reg = regs[id] || {};
        const st = state[id] || (state[id] = { period: reg.period, group: reg.group || (reg.groups ? reg.groups[0] : undefined), metric: reg.metric || (reg.metrics ? reg.metrics[0].id : undefined) });
        const fmt = currentFormat(ch);
        const parts = [];
        if (reg.periods) {
            const opts = reg.periods.map(p => [p, PERIOD_LABEL[p] || (p + ' dias')]);
            if (reg.custom) opts.push(['custom', 'Personalizado…']);
            parts.push(selectHtml('period', 'Período', opts, st.from ? 'custom' : st.period));
            if (reg.custom) parts.push(`<span class="gboc-cb-range" style="${st.from ? '' : 'display:none'}"><input type="date" data-k="from" value="${esc(st.from || '')}"> até <input type="date" data-k="to" value="${esc(st.to || '')}"><button type="button" data-a="apply" title="Aplicar período">OK</button></span>`);
        }
        if (reg.groups) parts.push(selectHtml('group', 'Agrupar', reg.groups.map(g => [g, GROUP_LABEL[g] || g]), st.group));
        if (reg.metrics) parts.push(selectHtml('metric', 'Métrica', reg.metrics.map(m => [m.id, m.label]), st.metric));
        if (fmt) parts.push(selectHtml('format', 'Formato', formatsFor(ch), fmt));
        parts.push(`<span class="gboc-cb-btns">
            <button type="button" data-a="table" title="Mostrar/ocultar tabela de dados"><i class="fas fa-table"></i></button>
            <button type="button" data-a="csv" title="Exportar CSV"><i class="fas fa-file-csv"></i></button>
            <button type="button" data-a="png" title="Exportar imagem PNG"><i class="fas fa-image"></i></button>
            <button type="button" data-a="expand" title="Expandir"><i class="fas fa-expand"></i></button></span>`);
        const bar = document.createElement('div');
        bar.className = 'gboc-chart-bar';
        bar.dataset.for = id;
        bar.innerHTML = parts.join('');
        // a barra fica logo acima da área do gráfico, sem mexer na altura fixa do contêiner do canvas
        const anchor = (host !== card && host.children.length === 1) ? host : canvas;
        anchor.parentElement.insertBefore(bar, anchor);
        const live = () => { const cv = document.getElementById(id) || canvas; return window.Chart.getChart(cv) || ch; };
        bar.addEventListener('change', (e) => {
            const k = e.target.dataset.k;
            if (k === 'format') return applyFormat(live(), e.target.value, true);
            if (k === 'period') {
                const range = bar.querySelector('.gboc-cb-range');
                if (e.target.value === 'custom') { if (range) range.style.display = ''; return; }
                if (range) range.style.display = 'none';
                st.period = +e.target.value; st.from = st.to = undefined;
            } else if (k === 'group') st.group = e.target.value;
            else if (k === 'metric') st.metric = e.target.value;
            else return;
            notify(id);
        });
        bar.addEventListener('click', (e) => {
            const b = e.target.closest('button[data-a]');
            if (!b) return;
            const a = b.dataset.a;
            const c = live();
            if (a === 'table') toggleTable(c, bar);
            else if (a === 'csv') exportCSV(c);
            else if (a === 'png') exportPNG(c);
            else if (a === 'expand') toggleExpand(c, bar);
            else if (a === 'apply') {
                const f = bar.querySelector('[data-k=from]').value, t = bar.querySelector('[data-k=to]').value;
                if (!f || !t || f > t) { alert('Informe as datas "de" e "até" (início antes do fim).'); return; }
                st.from = f; st.to = t; notify(id);
            }
        });
    }
    function notify(id) {
        const reg = regs[id];
        if (!reg || typeof reg.onChange !== 'function') return;
        const st = state[id];
        prefs[id] = Object.assign({}, prefs[id], { period: st.period, group: st.group, metric: st.metric });
        savePrefs();
        try { reg.onChange(Object.assign({}, st)); } catch (e) { console.warn('[GBOCCharts] recarregar:', e); }
    }

    // ── Plugin: estilo + formato salvo + barra em todo gráfico ───────────────────
    const plugin = {
        id: 'gbocChartOptions',
        beforeInit(ch) { baseType(ch); harmonize(ch); },
        afterInit(ch) {
            const f = prefs[chartId(ch)] && prefs[chartId(ch)].format;
            if (f && f !== currentFormat(ch, true)) setTimeout(() => applyFormat(ch, f, false), 0);
            setTimeout(() => buildBar(ch), 0);
        },
    };

    function injectCss() {
        if (document.getElementById('gboc-charts-css')) return;
        const s = document.createElement('style');
        s.id = 'gboc-charts-css';
        s.textContent = `
.gboc-chart-bar{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:6px;margin:0 0 8px;font-size:12px;color:var(--text-muted,#94a3b8)}
.gboc-chart-bar .gboc-cb-sel{display:inline-flex;align-items:center;gap:4px;margin:0}
.gboc-chart-bar .gboc-cb-sel span{font-size:11px;opacity:.85}
.gboc-chart-bar select{max-width:150px}
.gboc-chart-bar select,.gboc-chart-bar input[type=date]{background:var(--bg-input,rgba(255,255,255,.04));color:var(--text-primary,#e5e7eb);border:1px solid var(--border,rgba(255,255,255,.12));border-radius:6px;padding:3px 6px;font-size:12px;height:26px}
.gboc-chart-bar .gboc-cb-btns{display:inline-flex;gap:2px}
.gboc-chart-bar button{background:transparent;border:1px solid transparent;color:var(--text-muted,#94a3b8);border-radius:6px;height:26px;min-width:26px;padding:0 6px;cursor:pointer;font-size:12px}
.gboc-chart-bar button:hover,.gboc-chart-bar button:focus-visible{color:var(--text-primary,#e5e7eb);border-color:var(--border,rgba(255,255,255,.15));outline:none}
.gboc-chart-table{margin-top:10px;max-height:260px;overflow:auto;border:1px solid var(--border,rgba(255,255,255,.1));border-radius:8px}
.gboc-chart-table table{width:100%;border-collapse:collapse;font-size:12px}
.gboc-chart-table th,.gboc-chart-table td{padding:5px 10px;border-bottom:1px solid var(--border,rgba(255,255,255,.06));text-align:right;white-space:nowrap}
.gboc-chart-table thead th{position:sticky;top:0;background:var(--bg-card,#111318);color:var(--text-muted,#94a3b8);font-weight:600}
.gboc-chart-table tbody th{text-align:left;font-weight:500;color:var(--text-primary,#e5e7eb)}
.gboc-chart-expanded{position:fixed!important;inset:4vh 4vw!important;z-index:9000!important;background:var(--bg-card,#111318)!important;padding:16px!important;overflow:auto;box-shadow:0 20px 80px rgba(0,0,0,.6);border-radius:12px;display:flex;flex-direction:column}
.gboc-chart-expanded canvas{flex:1;min-height:60vh}
.gboc-chart-expanded > div:has(> canvas){flex:1;height:auto!important;min-height:60vh}
body.gboc-chart-expanded-open::after{content:'';position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:8999}
@media (max-width:640px){.gboc-chart-bar{justify-content:flex-start}.gboc-chart-bar .gboc-cb-sel span{display:none}}`;
        document.head.appendChild(s);
    }

    function boot() {
        const Chart = window.Chart;
        if (!Chart || !Chart.register) return false;
        if (Chart.$gbocReady) return true;
        Chart.$gbocReady = true;
        injectCss();
        applyDefaults(Chart);
        Chart.register(plugin);
        // gráficos criados antes deste arquivo carregar
        Object.values(Chart.instances || {}).forEach(ch => { try { harmonize(ch); ch.update('none'); buildBar(ch); } catch (e) { /* */ } });
        // troca de tema: reaplica cores
        new MutationObserver(() => {
            applyDefaults(Chart);
            Object.values(Chart.instances || {}).forEach(ch => { try { harmonize(ch); ch.update('none'); } catch (e) { /* */ } });
        }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-color-theme', 'data-theme'] });
        setTimeout(() => document.dispatchEvent(new Event('gboc:charts-ready')), 0);
        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape') return;
            const open = document.querySelector('.gboc-chart-expanded');
            if (open) { const bar = open.querySelector('.gboc-chart-bar'); const cv = open.querySelector('canvas'); const ch = cv && Chart.getChart(cv); if (bar && ch) toggleExpand(ch, bar); }
        });
        return true;
    }

    window.GBOCCharts = {
        /** Registra período/agrupamento/métrica para um gráfico (id do canvas). Retorna o estado salvo. */
        options(id, opts) {
            regs[id] = opts || {};
            const p = prefs[id] || {};
            const st = state[id] = state[id] || {};
            if (opts.periods) st.period = opts.periods.includes(p.period) ? p.period : (opts.period ?? opts.periods[0]);
            if (opts.groups) st.group = opts.groups.includes(p.group) ? p.group : (opts.group || opts.groups[0]);
            if (opts.metrics) st.metric = opts.metrics.some(m => m.id === p.metric) ? p.metric : (opts.metric || opts.metrics[0].id);
            // gráfico já desenhado antes do registro: refaz a barra com as novas opções
            const old = document.querySelector('.gboc-chart-bar[data-for="' + id + '"]');
            if (old) old.remove();
            const cv = document.getElementById(id);
            const ch = cv && window.Chart && window.Chart.getChart(cv);
            if (ch) buildBar(ch);
            return Object.assign({}, st);
        },
        state(id) { return Object.assign({}, state[id] || {}); },
        /** Altera o período/agrupamento de um gráfico pelo código da tela (ex.: seletor geral da página). */
        set(id, patch) {
            const st = state[id] = Object.assign(state[id] || {}, patch || {});
            if (patch && 'period' in patch) { st.from = st.to = undefined; }
            const bar = document.querySelector('.gboc-chart-bar[data-for="' + id + '"]');
            if (bar) {
                const sel = bar.querySelector('select[data-k=period]');
                if (sel && st.period !== undefined) sel.value = String(st.period);
                const rg = bar.querySelector('.gboc-cb-range'); if (rg) rg.style.display = 'none';
            }
            prefs[id] = Object.assign({}, prefs[id], { period: st.period, group: st.group, metric: st.metric });
            savePrefs();
            return Object.assign({}, st);
        },
        /** Registra e já devolve o estado: opts.load(estado, query) é chamado quando o usuário muda o período. */
        bind(id, opts) {
            const o = Object.assign({}, opts);
            const load = o.load;
            o.onChange = (st) => load(st, window.GBOCCharts.query(id));
            return window.GBOCCharts.options(id, o);
        },
        /** Dias do período atual (0 = tudo); usa o padrão quando o gráfico não foi registrado. */
        days(id, def) { const st = state[id]; return st && st.period !== undefined && !st.from ? st.period : def; },
        /** Monta a query string padrão: days=… ou date_from/date_to, e group. */
        query(id, extra) {
            const st = state[id] || {};
            const q = new URLSearchParams(extra || {});
            if (st.from && st.to) { q.set('date_from', st.from); q.set('date_to', st.to); }
            else if (st.period !== undefined) q.set('days', st.period);
            if (st.group) q.set('group', st.group);
            return q.toString();
        },
        applyFormat, boot,
    };

    if (!boot()) {
        let tries = 0;
        const t = setInterval(() => { if (boot() || ++tries > 120) clearInterval(t); }, 250);
    }
})();
