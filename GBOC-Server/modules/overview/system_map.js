/*
 * GBOC Server — Mapa do Sistema (todos os Agentes)
 * Origens → Tarefas → Repositórios → Destinos, com saúde, discos, testes de recuperação e próximos passos.
 * Dados reais do inventário sincronizado pelos Agentes: GET /api/v1/dashboard/system-map[?agent_id=]
 * Monta a própria marcação dentro de <div id="system-map-root"></div>.
 */
(function () {
    'use strict';

    const ENDPOINT = '/api/v1/dashboard/system-map';
    const LS_AGENT = 'gboc_system_map_agent';
    const REFRESH_MS = 20000;
    const STATES = {
        ok:      { txt: 'Em dia',           icon: 'fa-check-circle',        cls: 'ok' },
        running: { txt: 'Executando',       icon: 'fa-sync-alt',            cls: 'running' },
        late:    { txt: 'Atrasado',         icon: 'fa-exclamation-triangle', cls: 'late' },
        error:   { txt: 'Cópia incompleta', icon: 'fa-times-circle',        cls: 'error' },
        never:   { txt: 'Nunca executou',   icon: 'fa-circle-notch',        cls: 'never' },
        paused:  { txt: 'Pausada',          icon: 'fa-pause-circle',        cls: 'paused' },
        offline: { txt: 'Agente offline',   icon: 'fa-plug',                cls: 'error' },
        manual:  { txt: 'Manual',           icon: 'fa-hand-pointer',        cls: 'never' }
    };
    const SEV_ICON = { error: 'fa-times-circle', warning: 'fa-exclamation-triangle', info: 'fa-info-circle' };

    let data = null;
    let agentFilter = '';
    try { agentFilter = localStorage.getItem(LS_AGENT) || ''; } catch (e) { agentFilter = ''; }
    const multi = () => !agentFilter && data && data.agents && data.agents.length > 1;
    const hostPfx = (n) => (multi() && n.hostname ? n.hostname + ' · ' : '');
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
        const repoSize = (r) => (r.size_bytes != null ? fmtBytes(r.size_bytes) : (r.protected_bytes ? fmtBytes(r.protected_bytes) : ''));
        const cols = [
            { h: `Pastas de origem (${d.sources.length})`, html: d.sources.map((s) => nodeHtml('src', s.id, s.path, hostPfx(s) + s.label, s.state)).join('') },
            { h: `Tarefas (${d.tasks.length})`, html: d.tasks.map((t) => nodeHtml('task', t.id, t.name, hostPfx(t) + taskSub(t), t.state)).join('') },
            { h: `Repositórios (${d.repositories.length})`, html: d.repositories.map((r) => nodeHtml('repo', r.id, r.name,
                `${hostPfx(r)}${repoSize(r) ? repoSize(r) + ' · ' : ''}${r.label}`, r.state)).join('') },
            { h: `Destinos (${d.destinations.length})`, html: d.destinations.map((x) => nodeHtml('dest', x.id, x.label,
                `${x.size_bytes ? fmtBytes(x.size_bytes) + ' · ' : ''}${x.detail}${x.agents && x.agents.length > 1 ? ' · ' + x.agents.length + ' agentes' : ''}`, x.state)).join('') }
        ];
        if (!d.sources.length && !d.tasks.length && !d.repositories.length) {
            root.innerHTML = `<div class="gsm-empty"><i class="fas fa-project-diagram"></i> ${d.agents && d.agents.length
                ? 'Nenhuma tarefa ou repositório sincronizado pelos Agentes ainda.' : 'Nenhum Agente registrado neste Server.'}</div>`;
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

    // Arestas já vêm prontas do Server (ids incluem o agent_id)
    function edges() {
        return Array.isArray(data.edges) ? data.edges : [];
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
                // Destinos/repositórios/tarefas são gerenciados no Gerenciamento Remoto do Agente
                if (typeof window.switchTab === 'function') window.switchTab('remote');
            });
        });
    }

    // ── Render: painéis inferiores ───────────────────────
    function track(p) {
        if (p == null) return '';
        return `<div class="gsm-track"><i class="${p >= 90 ? 'crit' : p >= 80 ? 'warn' : ''}" style="width:${Math.max(0, Math.min(100, p))}%"></i></div>`;
    }

    function renderDestinations(el) {
        const d = data;
        if (!d.destinations.length) { el.innerHTML = '<div class="gsm-sub">Nenhum repositório sincronizado.</div>'; return; }
        el.innerHTML = d.destinations.map((x) => {
            const repos = d.repositories.filter((r) => r.destination === x.id);
            let disk = '';
            if (x.capacity_bytes) {
                const p = (1 - (x.free_bytes || 0) / x.capacity_bytes) * 100;
                disk = track(p) + `<div class="gsm-sub">${fmtBytes(x.free_bytes)} livres de ${fmtBytes(x.capacity_bytes)} (${p.toFixed(0)}% ocupado)</div>`;
            }
            const lines = repos.map((r) => `<div class="gsm-row gsm-sub"><span>${esc(hostPfx(r))}<span class="gsm-mono">${esc(r.name)}</span> · ${esc(r.engine || '')}${r.snapshot_count != null ? ' · ' + r.snapshot_count + ' snapshots' : ''}</span>
                <span>${r.size_bytes != null ? fmtBytes(r.size_bytes) : 'não medido'}${r.size_recorded_at ? ' · medido ' + fmtAgo(r.size_recorded_at) : ''}</span></div>`).join('');
            return `<div class="gsm-item">
                <div class="gsm-row"><span><strong class="gsm-mono">${esc(x.label)}</strong> <span class="gsm-sub">${esc(x.detail)}</span></span>
                <strong class="gsm-mono">${x.size_bytes ? fmtBytes(x.size_bytes) : '—'}</strong></div>
                <div class="gsm-sub">${repos.length} repositório(s)${x.agents && x.agents.length ? ' · ' + esc(x.agents.join(', ')) : ''}</div>
                ${disk}${lines}</div>`;
        }).join('') + '<div class="gsm-sub" style="margin-top:8px">Tamanho medido pelo Agente no repositório (arquivos + versões guardadas).</div>';
    }

    function renderComputer(el) {
        const d = data;
        let html = '';
        let lastHost = null;
        d.volumes.forEach((v) => {
            if (v.hostname !== lastHost) {
                lastHost = v.hostname;
                const ag = (d.agents || []).find((a) => a.agent_id === v.agent_id) || {};
                html += `<div class="gsm-host"><i class="fas fa-desktop"></i> ${esc(v.hostname)}
                    <span class="gsm-chip ${ag.online ? 'ok' : 'error'}" style="margin-left:auto">${ag.online ? 'Online' : 'Offline'}</span></div>`;
            }
            const sizes = v.total ? `${fmtBytes(v.free)} livres de ${fmtBytes(v.total)}` : 'volume não informado pelo Agente';
            html += `<div class="gsm-item"><div class="gsm-row"><strong class="gsm-mono">${esc(v.root)}</strong>
                <span class="gsm-mono gsm-sub">${sizes}</span></div>${track(v.percent)}
                <div class="gsm-sub">${v.percent != null ? v.percent.toFixed(0) + '% ocupado · ' : ''}${v.sources} pasta(s) de origem</div></div>`;
            d.sources.filter((s) => s.agent_id === v.agent_id && volOf(s, v)).forEach((s) => {
                const S = st(s.state);
                html += `<div class="gsm-item gsm-row" style="padding-left:12px"><span><i class="fas fa-folder-open" style="color:#f59e0b;margin-right:8px"></i>
                    <span class="gsm-mono">${esc(s.path)}</span><div class="gsm-sub">${s.tasks.length} tarefa(s)${s.last_attempt ? ' · última tentativa ' + fmtAgo(s.last_attempt) : ''}</div></span>
                    <span class="gsm-chip ${S.cls}"><i class="fas ${S.icon}"></i> ${esc(s.label)}</span></div>`;
            });
        });
        el.innerHTML = html || '<div class="gsm-sub">Nenhuma pasta de origem sincronizada.</div>';
    }

    // Pasta pertence ao volume: compara o início do caminho com a raiz (sem diferenciar maiúsculas no Windows)
    function volOf(s, v) {
        const p = String(s.path).replace(/\//g, '\\').toLowerCase();
        const r = String(v.root).replace(/\//g, '\\').toLowerCase();
        const longer = data.volumes.some((o) => o !== v && o.agent_id === v.agent_id && String(o.root).length > String(v.root).length
            && p.startsWith(String(o.root).replace(/\//g, '\\').toLowerCase()));
        return !longer && (p === r.replace(/\\$/, '') || p.startsWith(r.endsWith('\\') ? r : r + '\\') || (r === '\\' && p.startsWith('\\')));
    }

    function renderHealth(el) {
        const d = data;
        const up = d.upcoming.length ? d.upcoming.map((u) => `<div class="gsm-item gsm-row">
            <span><i class="far fa-calendar-alt" style="margin-right:8px;color:var(--text-muted)"></i>${esc(hostPfx(u))}${esc(u.name)}</span>
            <span><span class="gsm-sub">${esc(u.type || '')}</span> <span class="gsm-mono">${fmtDate(u.at)}</span></span></div>`).join('')
            : '<div class="gsm-sub">Nenhuma execução agendada nos próximos 8 dias.</div>';
        const RT = { passed: ['ok', 'Aprovado'], success: ['ok', 'Aprovado'], completed: ['ok', 'Aprovado'], running: ['running', 'Executando'],
                     partial: ['late', 'Parcial'], failed: ['error', 'Falhou'], error: ['error', 'Erro'] };
        const rt = (d.restore_tests || []).map((r) => {
            const [cls, txt] = r.status ? (RT[String(r.status).toLowerCase()] || ['never', r.status]) : ['never', 'Nunca feito'];
            return `<div class="gsm-item gsm-row"><span><i class="fas fa-shield-alt" style="margin-right:8px;color:var(--text-muted)"></i>Último teste de recuperação${multi() || (d.agents || []).length > 1 ? ' · ' + esc(r.hostname) : ''}
                ${r.repository_name ? `<div class="gsm-sub">${esc(r.repository_name)}</div>` : ''}</span>
                <span>${r.at ? `<span class="gsm-sub">${fmtAgo(r.at)}</span> ` : ''}<span class="gsm-chip ${cls}">${esc(txt)}</span></span></div>`;
        }).join('');
        const iss = d.issues.length ? d.issues.map((i) =>
            `<div class="gsm-issue ${esc(i.severity)}"><i class="fas ${SEV_ICON[i.severity] || 'fa-info-circle'}"></i><span>${esc(i.text)}</span></div>`).join('')
            : '<div class="gsm-ok-all"><i class="fas fa-check-circle"></i> Nenhum problema encontrado.</div>';
        el.innerHTML = `<div class="gsm-sub" style="margin-bottom:4px">Próximas execuções</div>${up}${rt}
            <div class="gsm-sub" style="margin:14px 0 0">Saúde</div>${iss}`;
    }

    // ── Estrutura da seção ────────────────────────────────
    function skeleton(root) {
        root.innerHTML = `<div class="gsm-wrap">
            <div class="panel gsm-panel">
                <div class="gsm-hdr"><h3><i class="fas fa-project-diagram" style="color:#10b981"></i> Mapa do sistema</h3>
                    <div class="gsm-tools"><select id="gsmAgent" class="gsm-select" title="Filtrar por Agente"><option value="">Todos os agentes</option></select>
                    <span class="gsm-sub" id="gsmUpdated">Passe o mouse para ver o caminho dos dados</span></div></div>
                <div class="gsm-map" id="gsmMap"><div class="gsm-empty"><i class="fas fa-spinner fa-spin"></i> Carregando mapa...</div></div>
            </div>
            <div class="gsm-grid3">
                <div class="panel gsm-panel"><div class="gsm-hdr"><h3><i class="fas fa-cloud" style="color:#10b981"></i> Destinos</h3></div><div class="gsm-body" id="gsmDest"></div></div>
                <div class="panel gsm-panel"><div class="gsm-hdr"><h3><i class="fas fa-hdd" style="color:#10b981"></i> Computadores (origens)</h3></div><div class="gsm-body" id="gsmComp"></div></div>
                <div class="panel gsm-panel"><div class="gsm-hdr"><h3><i class="fas fa-calendar-check" style="color:#10b981"></i> Próximos passos e saúde</h3></div><div class="gsm-body" id="gsmHealth"></div></div>
            </div></div>`;
        const extra = document.createElement('style');
        extra.textContent = `.gsm-panel{padding:0 !important;overflow:hidden}
            .gsm-hdr{padding:14px 18px;border-bottom:1px solid var(--border-color,rgba(148,163,184,.15));display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
            .gsm-hdr h3{margin:0 !important;font-size:.95em;display:flex;align-items:center;gap:8px}
            .gsm-tools{display:flex;gap:12px;align-items:center}
            .gsm-select{padding:5px 10px;border-radius:8px;border:1px solid var(--border-color,#334155);background:var(--bg-input,#0f172a);color:var(--text-primary,#e2e8f0);font-size:.85em}
            .gsm-body{padding:16px}
            .gsm-host{display:flex;align-items:center;gap:8px;font-weight:600;margin:12px 0 2px;font-size:.92em}
            .gsm-host:first-child{margin-top:0}`;
        document.head.appendChild(extra);
        const sel = root.querySelector('#gsmAgent');
        sel.addEventListener('change', () => {
            agentFilter = sel.value;
            try { localStorage.setItem(LS_AGENT, agentFilter); } catch (e) { /* preferência só desta sessão */ }
            load();
        });
    }

    function fillAgents() {
        const sel = document.getElementById('gsmAgent');
        if (!sel || !data) return;
        const list = data.agents_all || [];
        if (agentFilter && !list.some((a) => a.agent_id === agentFilter)) agentFilter = '';
        sel.innerHTML = '<option value="">Todos os agentes</option>' + list.map((a) =>
            `<option value="${esc(a.agent_id)}"${a.agent_id === agentFilter ? ' selected' : ''}>${esc(a.hostname)}${a.online ? '' : ' (offline)'}</option>`).join('');
    }

    function renderError(msg) {
        const m = document.getElementById('gsmMap');
        if (m) m.innerHTML = `<div class="gsm-empty"><i class="fas fa-exclamation-triangle" style="color:#f59e0b"></i> ${esc(msg)}</div>`;
    }

    // ── Carregamento ──────────────────────────────────────
    function visible() {
        const r = document.getElementById('system-map-root');
        return r && !document.hidden && r.offsetParent !== null;
    }

    async function load(force) {
        if (inflight || (!force && !visible())) return;
        inflight = true;
        try {
            const url = ENDPOINT + (agentFilter ? '?agent_id=' + encodeURIComponent(agentFilter) : '');
            const res = await fetch(url, { cache: 'no-store', credentials: 'same-origin' });
            const j = await res.json().catch(() => ({}));
            if (!res.ok || j.status !== 'success') throw new Error(j.message || j.detail || `HTTP ${res.status} ao consultar o mapa do sistema`);
            data = j;
            fillAgents();
            renderMap(document.getElementById('gsmMap'));
            renderDestinations(document.getElementById('gsmDest'));
            renderComputer(document.getElementById('gsmComp'));
            renderHealth(document.getElementById('gsmHealth'));
            const upd = document.getElementById('gsmUpdated');
            if (upd) upd.textContent = 'Atualizado ' + new Date(j.generated_at).toLocaleTimeString('pt-BR') + ' · passe o mouse para ver o caminho';
        } catch (e) {
            console.error('[SystemMap]', e);
            renderError(e.message);
        } finally {
            inflight = false;
        }
    }

    function init() {
        const root = document.getElementById('system-map-root');
        if (!root) return;
        injectCss();
        skeleton(root);
        load(true);
        clearInterval(timer);
        timer = setInterval(() => load(false), REFRESH_MS);
        let rz = null;
        window.addEventListener('resize', () => {
            clearTimeout(rz);
            rz = setTimeout(() => { const m = document.getElementById('gsmMap'); if (m && data && visible()) drawEdges(m); }, 120);
        });
        document.addEventListener('visibilitychange', () => { if (!document.hidden) load(false); });
        // Ao voltar para a aba Visão Geral, redesenha (as linhas dependem do layout visível)
        const tab = root.closest('.tab-section');
        if (tab && 'MutationObserver' in window) {
            new MutationObserver(() => { if (tab.classList.contains('active')) load(true); })
                .observe(tab, { attributes: true, attributeFilter: ['class'] });
        }
    }

    window.GBOCSystemMap = { reload: () => load(true) };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
