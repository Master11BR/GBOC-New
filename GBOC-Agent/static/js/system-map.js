/*
 * GBOC Agent — Mapa do Sistema
 * Origens → Tarefas → Repositórios → Destinos, com saúde, discos e próximos passos.
 * Dados reais de GET /api/overview/system-map (sem dados simulados).
 */
(function () {
    'use strict';

    const ENDPOINT = '/api/overview/system-map';
    const REFRESH_MS = 20000;
    const STATES = {
        ok:      { txt: 'Em dia',           icon: 'fa-check-circle',        cls: 'ok' },
        running: { txt: 'Executando',       icon: 'fa-sync-alt',            cls: 'running' },
        late:    { txt: 'Atrasado',         icon: 'fa-exclamation-triangle', cls: 'late' },
        error:   { txt: 'Cópia incompleta', icon: 'fa-times-circle',        cls: 'error' },
        never:   { txt: 'Nunca executou',   icon: 'fa-circle-notch',        cls: 'never' },
        paused:  { txt: 'Pausada',          icon: 'fa-pause-circle',        cls: 'paused' },
        manual:  { txt: 'Manual',           icon: 'fa-hand-pointer',        cls: 'never' }
    };
    const SEV_ICON = { error: 'fa-times-circle', warning: 'fa-exclamation-triangle', info: 'fa-info-circle' };

    let data = null;
    let timer = null;
    let inflight = false;

    const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const st = (s) => STATES[s] || STATES.never;

    function fmtBytes(b) {
        const n = Number(b) || 0;
        if (n <= 0) return '0 B';
        const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
        const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1);
        return (n / Math.pow(1024, i)).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' ' + u[i];
    }
    function fmtDate(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        if (isNaN(d)) return '';
        return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    }
    function fmtAgo(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        if (isNaN(d)) return '';
        const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
        if (s < 90) return 'agora';
        if (s < 3600) return `há ${Math.round(s / 60)} min`;
        if (s < 86400) return `há ${Math.round(s / 3600)} h`;
        return `há ${Math.round(s / 86400)} d`;
    }

    // ── Estilos (escopo .gsm-*) ───────────────────────────
    function injectCss() {
        if (document.getElementById('gsm-css')) return;
        const css = `
        .gsm-wrap{margin-bottom:24px}
        .gsm-map{position:relative;padding:18px 20px 14px}
        .gsm-cols{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:56px;position:relative;z-index:1}
        .gsm-col h4{margin:0 0 14px;font-size:1.02em;font-weight:500;color:var(--text-muted)}
        .gsm-col-body{display:flex;flex-direction:column;justify-content:center;gap:12px;min-height:100%}
        .gsm-node{border:2px solid var(--gsm-c,var(--border-color,#334155));border-left-width:5px;border-radius:12px;padding:10px 14px;background:var(--bg-card,#111827);cursor:pointer;transition:opacity .2s,transform .15s,box-shadow .2s;min-width:0}
        .gsm-node:hover{transform:translateY(-1px);box-shadow:0 4px 14px rgba(0,0,0,.25)}
        .gsm-node .t{font-family:ui-monospace,Consolas,monospace;font-size:1.02em;color:var(--text-primary,var(--text));white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .gsm-node.task .t,.gsm-node.dest .t{font-family:inherit}
        .gsm-node .s{font-size:.85em;color:var(--text-muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .gsm-node .bar{height:3px;border-radius:2px;background:rgba(148,163,184,.2);margin-top:6px;overflow:hidden}
        .gsm-node .bar i{display:block;height:100%;background:var(--gsm-c)}
        .gsm-dim .gsm-node:not(.hl){opacity:.28}
        .gsm-svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:0;overflow:visible}
        .gsm-svg path{fill:none;stroke:rgba(148,163,184,.35);stroke-width:1.6;transition:stroke .2s,opacity .2s}
        .gsm-dim .gsm-svg path:not(.hl){opacity:.12}
        .gsm-svg path.hl{stroke:var(--primary-color,#38bdf8);stroke-width:2.4}
        .gsm-s-ok{--gsm-c:#10b981}.gsm-s-running{--gsm-c:#38bdf8}.gsm-s-late{--gsm-c:#f59e0b}
        .gsm-s-error{--gsm-c:#f43f5e}.gsm-s-never{--gsm-c:#64748b}.gsm-s-paused{--gsm-c:#64748b}
        .gsm-legend{display:flex;flex-wrap:wrap;gap:8px;margin-top:26px}
        .gsm-chip{display:inline-flex;align-items:center;gap:6px;font-size:.8em;padding:4px 10px;border-radius:7px;border:1px solid var(--gsm-c);color:var(--gsm-c);background:color-mix(in srgb,var(--gsm-c) 8%,transparent)}
        .gsm-chip.ok{--gsm-c:#10b981}.gsm-chip.running{--gsm-c:#38bdf8}.gsm-chip.late{--gsm-c:#f59e0b}.gsm-chip.error{--gsm-c:#f43f5e}.gsm-chip.never,.gsm-chip.paused{--gsm-c:#94a3b8}
        .gsm-empty{padding:28px;text-align:center;color:var(--text-muted)}
        .gsm-grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;margin-top:20px}
        .gsm-grid3 .panel-body{min-height:0}
        .gsm-row{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
        .gsm-mono{font-family:ui-monospace,Consolas,monospace}
        .gsm-sub{font-size:.8em;color:var(--text-muted)}
        .gsm-track{height:8px;border-radius:5px;background:rgba(148,163,184,.18);margin:8px 0 4px;overflow:hidden}
        .gsm-track i{display:block;height:100%;border-radius:5px;background:#3b82f6}
        .gsm-track i.warn{background:#f59e0b}.gsm-track i.crit{background:#f43f5e}
        .gsm-item{padding:10px 0;border-bottom:1px solid var(--border-color,rgba(148,163,184,.15))}
        .gsm-item:last-child{border-bottom:none}
        .gsm-issue{display:flex;gap:10px;align-items:flex-start;padding:10px 12px;border-radius:10px;margin-top:8px;font-size:.88em;border:1px solid}
        .gsm-issue.error{border-color:rgba(244,63,94,.45);background:rgba(244,63,94,.07)}
        .gsm-issue.warning{border-color:rgba(245,158,11,.45);background:rgba(245,158,11,.07)}
        .gsm-issue.info{border-color:rgba(148,163,184,.35);background:rgba(148,163,184,.06)}
        .gsm-issue.error i{color:#f43f5e}.gsm-issue.warning i{color:#f59e0b}.gsm-issue.info i{color:#94a3b8}
        .gsm-ok-all{display:flex;gap:10px;align-items:center;color:#10b981;padding:10px 0}
        @media(max-width:1100px){.gsm-grid3{grid-template-columns:1fr}}
        @media(max-width:900px){.gsm-cols{grid-template-columns:1fr;gap:18px}.gsm-svg{display:none}}
        `;
        const el = document.createElement('style');
        el.id = 'gsm-css';
        el.textContent = css;
        document.head.appendChild(el);
    }

    // ── Render: mapa ──────────────────────────────────────
    function nodeHtml(kind, id, title, sub, state, extra) {
        return `<div class="gsm-node ${kind} gsm-s-${esc(st(state).cls)}" data-id="${esc(id)}" title="${esc(title)}">
            <div class="t">${esc(title)}</div><div class="s">${esc(sub)}</div>${extra || ''}</div>`;
    }

    function renderMap(root) {
        const d = data;
        const taskSub = (t) => {
            const kind = t.type && t.type !== 'backup' ? t.type : (t.engine || 'backup');
            let s = `${kind} · ${t.label}`;
            if (t.state === 'running' && t.progress != null) s += ` · ${t.progress}%`;
            else if (t.next_run) s += ` · próx. ${fmtDate(t.next_run)}`;
            return s;
        };
        const cols = [
            { h: `Pastas de origem (${d.sources.length})`, html: d.sources.map((s) => nodeHtml('src', s.id, s.path, s.label, s.exists ? s.state : 'error')).join('') },
            { h: `Tarefas (${d.tasks.length})`, html: d.tasks.map((t) => {
                const bar = t.state === 'running' && t.progress != null ? `<div class="bar"><i style="width:${Math.max(0, Math.min(100, t.progress))}%"></i></div>` : '';
                return nodeHtml('task', t.id, t.name, taskSub(t), t.state, bar);
            }).join('') },
            { h: `Repositórios (${d.repositories.length})`, html: d.repositories.map((r) => nodeHtml('repo', r.id, r.name,
                `${r.protected_bytes ? fmtBytes(r.protected_bytes) + ' · ' : ''}${r.label}`, r.state)).join('') },
            { h: `Destinos (${d.destinations.length})`, html: d.destinations.map((x) => nodeHtml('dest', x.id, x.label, x.detail, x.state)).join('') }
        ];
        if (!d.sources.length && !d.tasks.length && !d.repositories.length) {
            root.innerHTML = '<div class="gsm-empty"><i class="fas fa-project-diagram"></i> Nenhuma tarefa ou repositório cadastrado ainda. <a href="/tasks.html">Criar tarefa</a></div>';
            return;
        }
        const legend = ['ok', 'running', 'late', 'error', 'never', 'paused']
            .map((k) => `<span class="gsm-chip ${k}"><i class="fas ${STATES[k].icon}"></i> ${STATES[k].txt}</span>`).join('');
        root.innerHTML = `<svg class="gsm-svg"></svg><div class="gsm-cols">${cols.map((c) =>
            `<div class="gsm-col"><h4>${esc(c.h)}</h4><div class="gsm-col-body">${c.html || '<div class="gsm-sub">—</div>'}</div></div>`).join('')}</div>
            <div class="gsm-legend">${legend}</div>`;
        bindMap(root);
        requestAnimationFrame(() => drawEdges(root));
    }

    function edges() {
        const e = [];
        data.tasks.forEach((t) => {
            (t.sources || []).forEach((p) => {
                const key = 'src:' + (p.replace(/[\\/]+$/, '').toLowerCase() || p.toLowerCase());
                e.push([key, t.id]);
            });
            if (t.repository_id != null) e.push([t.id, 'repo:' + t.repository_id]);
        });
        data.repositories.forEach((r) => e.push([r.id, r.destination]));
        return e;
    }

    function drawEdges(root) {
        const svg = root.querySelector('.gsm-svg');
        if (!svg) return;
        const box = root.getBoundingClientRect();
        const pos = {};
        root.querySelectorAll('.gsm-node').forEach((n) => { pos[n.dataset.id] = n.getBoundingClientRect(); });
        svg.setAttribute('viewBox', `0 0 ${box.width} ${box.height}`);
        svg.innerHTML = edges().map(([a, b]) => {
            const ra = pos[a], rb = pos[b];
            if (!ra || !rb) return '';
            const x1 = ra.right - box.left, y1 = ra.top + ra.height / 2 - box.top;
            const x2 = rb.left - box.left, y2 = rb.top + rb.height / 2 - box.top;
            const dx = Math.max(24, (x2 - x1) / 2);
            return `<path data-a="${esc(a)}" data-b="${esc(b)}" d="M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}"/>`;
        }).join('');
    }

    // Caminho completo (para trás e para frente) a partir de um nó
    function connected(id) {
        const e = edges();
        const set = new Set([id]);
        const walk = (cur, dir) => e.forEach(([a, b]) => {
            const nxt = dir > 0 ? (a === cur ? b : null) : (b === cur ? a : null);
            if (nxt && !set.has(nxt)) { set.add(nxt); walk(nxt, dir); }
        });
        walk(id, 1); walk(id, -1);
        return set;
    }

    function bindMap(root) {
        root.querySelectorAll('.gsm-node').forEach((n) => {
            n.addEventListener('mouseenter', () => {
                const set = connected(n.dataset.id);
                root.classList.add('gsm-dim');
                root.querySelectorAll('.gsm-node').forEach((x) => x.classList.toggle('hl', set.has(x.dataset.id)));
                root.querySelectorAll('.gsm-svg path').forEach((p) => p.classList.toggle('hl', set.has(p.dataset.a) && set.has(p.dataset.b)));
            });
            n.addEventListener('mouseleave', () => {
                root.classList.remove('gsm-dim');
                root.querySelectorAll('.hl').forEach((x) => x.classList.remove('hl'));
            });
            n.addEventListener('click', () => {
                const id = n.dataset.id;
                if (id.startsWith('task:') || id.startsWith('src:')) window.location.href = '/tasks.html';
                else window.location.href = '/repositories.html';
            });
        });
    }

    // ── Render: painéis inferiores ───────────────────────
    function renderDestinations(el) {
        const d = data;
        if (!d.repositories.length) { el.innerHTML = '<div class="gsm-sub">Nenhum repositório cadastrado.</div>'; return; }
        el.innerHTML = d.repositories.map((r) => {
            const dest = d.destinations.find((x) => x.id === r.destination) || {};
            let track = '';
            if (dest.disk) {
                const p = dest.disk.percent;
                track = `<div class="gsm-track"><i class="${p >= 90 ? 'crit' : p >= 80 ? 'warn' : ''}" style="width:${p}%"></i></div>
                    <div class="gsm-sub">${esc(dest.label)}: ${fmtBytes(dest.disk.free)} livres de ${fmtBytes(dest.disk.total)} (${p.toFixed(0)}% ocupado)</div>`;
            }
            return `<div class="gsm-item">
                <div class="gsm-row"><span><strong class="gsm-mono">${esc(r.name)}</strong> <span class="gsm-sub">${esc(r.engine || '')}</span></span>
                <strong class="gsm-mono">${r.protected_bytes ? fmtBytes(r.protected_bytes) : '—'}</strong></div>
                <div class="gsm-row gsm-sub"><span>${esc(dest.detail || dest.label || '')}${r.bucket ? ' · ' + esc(r.bucket) : ''} · ${r.tasks.length} tarefa(s)</span>
                <span>${esc(r.label)}</span></div>${track}</div>`;
        }).join('') + '<div class="gsm-sub" style="margin-top:8px">Tamanho = dados de origem do último backup concluído de cada tarefa.</div>';
    }

    function renderComputer(el) {
        const d = data;
        const vols = d.volumes.map((v) => {
            if (v.error) return `<div class="gsm-item"><div class="gsm-row"><strong class="gsm-mono">${esc(v.root)}</strong><span class="gsm-sub">${esc(v.error)}</span></div></div>`;
            const p = v.percent || 0;
            return `<div class="gsm-item"><div class="gsm-row"><strong class="gsm-mono">${esc(v.root)}</strong>
                <span class="gsm-mono gsm-sub">${fmtBytes(v.free)} livres de ${fmtBytes(v.total)}</span></div>
                <div class="gsm-track"><i class="${p >= 90 ? 'crit' : p >= 80 ? 'warn' : ''}" style="width:${p}%"></i></div>
                <div class="gsm-sub">${p.toFixed(0)}% ocupado · ${v.sources} pasta(s) de origem</div></div>`;
        }).join('');
        const srcs = d.sources.map((s) => {
            const S = st(s.exists ? s.state : 'error');
            return `<div class="gsm-item gsm-row"><span><i class="fas fa-folder-open" style="color:#f59e0b;margin-right:8px"></i>
                <span class="gsm-mono">${esc(s.path)}</span><div class="gsm-sub">${s.tasks.length} tarefa(s)${s.last_attempt ? ' · última tentativa ' + fmtAgo(s.last_attempt) : ''}</div></span>
                <span class="gsm-chip ${S.cls}"><i class="fas ${S.icon}"></i> ${esc(s.label)}</span></div>`;
        }).join('');
        el.innerHTML = (vols || '<div class="gsm-sub">Nenhuma pasta de origem configurada.</div>') + srcs;
    }

    function renderHealth(el) {
        const d = data;
        const up = d.upcoming.length ? d.upcoming.map((u) => `<div class="gsm-item gsm-row">
            <span><i class="far fa-calendar-alt" style="margin-right:8px;color:var(--text-muted)"></i>${esc(u.name)}</span>
            <span><span class="gsm-sub">${esc(u.type || '')}</span> <span class="gsm-mono">${fmtDate(u.at)}</span></span></div>`).join('')
            : '<div class="gsm-sub">Nenhuma execução agendada nos próximos 8 dias.</div>';
        const iss = d.issues.length ? d.issues.map((i) =>
            `<div class="gsm-issue ${esc(i.severity)}"><i class="fas ${SEV_ICON[i.severity] || 'fa-info-circle'}"></i><span>${esc(i.text)}</span></div>`).join('')
            : '<div class="gsm-ok-all"><i class="fas fa-check-circle"></i> Nenhum problema encontrado.</div>';
        el.innerHTML = `<div class="gsm-sub" style="margin-bottom:4px">Próximas execuções</div>${up}<div class="gsm-sub" style="margin:14px 0 0">Saúde</div>${iss}`;
    }

    function renderError(msg) {
        const m = document.getElementById('gsmMap');
        if (m) m.innerHTML = `<div class="gsm-empty"><i class="fas fa-exclamation-triangle" style="color:#f59e0b"></i> ${esc(msg)}</div>`;
    }

    // ── Carregamento ──────────────────────────────────────
    async function load() {
        if (inflight || document.hidden) return;
        inflight = true;
        try {
            const res = await fetch(ENDPOINT, { cache: 'no-store' });
            if (!res.ok) throw new Error(`HTTP ${res.status} ao consultar o mapa do sistema`);
            const j = await res.json();
            if (j.status !== 'success') throw new Error(j.message || 'Resposta inválida do Agente');
            data = j;
            renderMap(document.getElementById('gsmMap'));
            renderDestinations(document.getElementById('gsmDest'));
            renderComputer(document.getElementById('gsmComp'));
            renderHealth(document.getElementById('gsmHealth'));
            const upd = document.getElementById('gsmUpdated');
            if (upd) upd.textContent = 'Atualizado ' + new Date(j.generated_at).toLocaleTimeString('pt-BR');
        } catch (e) {
            console.error('[SystemMap]', e);
            renderError(e.message);
        } finally {
            inflight = false;
        }
    }

    function init() {
        if (!document.getElementById('gsmMap')) return;
        injectCss();
        load();
        clearInterval(timer);
        timer = setInterval(load, REFRESH_MS);
        let rz = null;
        window.addEventListener('resize', () => {
            clearTimeout(rz);
            rz = setTimeout(() => { const m = document.getElementById('gsmMap'); if (m && data) drawEdges(m); }, 120);
        });
        document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
    }

    window.GBOCSystemMap = { reload: load };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
