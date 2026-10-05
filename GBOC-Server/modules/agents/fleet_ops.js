/* GBOC Server — Operações em lote e atualização do GBOC Agent (aba "Gerenciamento Remoto")
 * Seleciona vários agentes e executa a mesma ação; publica o pacote de atualização e atualiza a frota.
 * API: /api/v1/fleet/...
 */
(function () {
    'use strict';
    const base = () => (window.GBOC_API_BASE || '');
    const esc = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const toast = (m, t) => (typeof showToast === 'function' ? showToast(m, t) : alert(m));
    const dt = (v) => v ? new Date(String(v).replace(' ', 'T')).toLocaleString('pt-BR') : '—';
    const S = { agents: [], pkg: null, src: null, sel: new Set(), filter: '', open: false, job: null, timer: null };
    const ACTIONS = [
        ['sync', 'fa-cloud-arrow-up', 'Sincronizar agora', ''],
        ['run_tasks', 'fa-play', 'Executar tarefas', 'Executa as tarefas ativas (opcional: só as que contêm um texto no nome).'],
        ['pause_schedules', 'fa-pause', 'Pausar agendamentos', 'Útil em manutenção: guarda quais tarefas estavam agendadas.'],
        ['resume_schedules', 'fa-play-circle', 'Retomar agendamentos', 'Reativa exatamente as tarefas pausadas.'],
        ['stop_running', 'fa-stop', 'Parar execuções', 'Interrompe os backups em andamento.'],
        ['test_repositories', 'fa-plug-circle-check', 'Testar repositórios', 'Confere acesso e credenciais de todos os repositórios.'],
        ['restore_test', 'fa-vial-circle-check', 'Teste de restauração', 'Restaura uma amostra e confere o SHA-256 (pode demorar).'],
        ['update_agent', 'fa-arrow-up-from-bracket', 'Atualizar GBOC Agent', 'Instala o pacote publicado e reinicia o serviço do agente.'],
    ];

    async function api(path, opts) {
        const r = await fetch(base() + '/api/v1/fleet' + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}));
        let d; try { d = await r.json(); } catch (e) { d = {}; }
        if (!r.ok) throw new Error((typeof d.detail === 'string' ? d.detail : '') || d.message || ('HTTP ' + r.status));
        return d;
    }

    function shell(root) {
        root.innerHTML = `
        <div class="panel" style="padding:14px;margin-bottom:18px">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;cursor:pointer" id="fo-head">
                <div>
                    <h3 style="margin:0;font-size:1.05em"><i class="fas fa-layer-group" style="color:var(--primary);margin-right:6px"></i> Operações em lote e atualização da frota</h3>
                    <div style="font-size:.78em;color:var(--text-muted);margin-top:2px" id="fo-sub">Execute a mesma ação em vários agentes e mantenha todos na mesma versão.</div>
                </div>
                <button class="btn btn-sm" id="fo-toggle"><i class="fas fa-chevron-down"></i> Abrir</button>
            </div>
            <div id="fo-body" style="display:none;margin-top:12px"></div>
        </div>`;
        root.querySelector('#fo-head').onclick = (e) => { if (e.target.closest('input,select')) return; S.open = !S.open; render(); };
    }

    async function load() {
        try {
            const [f, p] = await Promise.all([api('/agents'), api('/update/package')]);
            S.agents = f.agents || []; S.pkg = p.package; S.src = p.agent_source;
            const outdated = S.agents.filter(a => a.outdated).length;
            document.getElementById('fo-sub').innerHTML = `${S.agents.length} agente(s) · ${S.agents.filter(a => a.online).length} online`
                + (S.pkg ? ` · pacote publicado v${esc(S.pkg.version || '?')}` + (outdated ? ` · <b style="color:var(--warning)">${outdated} desatualizado(s)</b>` : ' · todos atualizados') : ' · nenhum pacote de atualização publicado');
            if (S.open) render();
        } catch (e) { document.getElementById('fo-sub').textContent = 'Erro: ' + e.message; }
    }

    function render() {
        const body = document.getElementById('fo-body');
        const tg = document.getElementById('fo-toggle');
        tg.innerHTML = S.open ? '<i class="fas fa-chevron-up"></i> Fechar' : '<i class="fas fa-chevron-down"></i> Abrir';
        if (!S.open) { body.style.display = 'none'; return; }
        body.style.display = 'block';
        const flt = S.filter.toLowerCase();
        const list = S.agents.filter(a => !flt || `${a.hostname} ${a.agent_id} ${a.tenant_name || ''} ${a.ip_address || ''}`.toLowerCase().includes(flt));
        const pkg = S.pkg;
        body.innerHTML = `
        <div style="display:grid;grid-template-columns:minmax(0,2fr) minmax(260px,1fr);gap:14px">
            <div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px">
                    <input id="fo-filter" class="form-control" placeholder="Filtrar por nome, cliente ou IP..." value="${esc(S.filter)}" style="flex:1;min-width:180px">
                    <button class="btn btn-sm" data-selq="online">Online</button><button class="btn btn-sm" data-selq="outdated">Desatualizados</button>
                    <button class="btn btn-sm" data-selq="all">Todos</button><button class="btn btn-sm" data-selq="none">Nenhum</button>
                </div>
                <div style="max-height:340px;overflow:auto;border:1px solid var(--border);border-radius:8px">
                <table class="data-table" style="font-size:.88em;margin:0"><thead><tr><th style="width:28px"></th><th>Agente</th><th>Cliente</th><th>Versão</th><th>Situação</th><th>Último contato</th></tr></thead><tbody>
                ${list.map(a => `<tr><td><input type="checkbox" data-ag="${esc(a.agent_id)}" ${S.sel.has(a.agent_id) ? 'checked' : ''}></td>
                    <td><strong>${esc(a.hostname || a.agent_id)}</strong><div style="font-size:.75em;color:var(--text-muted)">${esc(a.ip_address || '')}</div></td>
                    <td>${esc(a.tenant_name || '—')}</td>
                    <td>${esc(a.agent_version || '—')}${a.outdated ? ' <span class="badge badge-warning">desatualizado</span>' : ''}</td>
                    <td>${a.online ? '<span class="badge badge-success">online</span>' : '<span class="badge badge-error">offline</span>'}${a.websocket ? ' <i class="fas fa-bolt" title="Canal WebSocket ativo" style="color:var(--success)"></i>' : ''}</td>
                    <td style="white-space:nowrap">${dt(a.last_heartbeat)}</td></tr>`).join('') || '<tr><td colspan="6">Nenhum agente.</td></tr>'}
                </tbody></table></div>
                <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:end">
                    <label style="font-size:.82em">Ação<select id="fo-action" class="form-control" style="min-width:230px">${ACTIONS.map(([k, , l]) => `<option value="${k}">${l}</option>`).join('')}</select></label>
                    <label style="font-size:.82em" id="fo-name-l">Nome contém (opcional)<input id="fo-name" class="form-control" placeholder="ex.: SQL"></label>
                    <button class="btn btn-primary" id="fo-go"><i class="fas fa-bolt"></i> Executar em <span id="fo-count">${S.sel.size}</span> agente(s)</button>
                </div>
                <div id="fo-hint" style="font-size:.76em;color:var(--text-muted);margin-top:4px"></div>
                <div id="fo-job" style="margin-top:12px"></div>
            </div>
            <div>
                <div style="border:1px solid var(--border);border-radius:8px;padding:12px">
                    <h4 style="margin:0 0 6px;font-size:.92em"><i class="fas fa-box-open" style="color:var(--primary)"></i> Pacote de atualização do Agent</h4>
                    ${pkg ? `<div style="font-size:.84em;line-height:1.6"><b>Versão ${esc(pkg.version || '?')}</b> · ${esc(pkg.files)} arquivos · ${(pkg.size / 1048576).toFixed(1)} MB<br>
                        Publicado em ${dt(pkg.published_at)} por ${esc(pkg.published_by)}<br><span style="color:var(--text-muted)">${esc(pkg.source)}</span><br>
                        <code style="font-size:.85em;overflow-wrap:anywhere">SHA-256 ${esc(pkg.sha256)}</code></div>`
                        : '<p style="font-size:.84em;color:var(--text-muted)">Nenhum pacote publicado.</p>'}
                    <div style="display:flex;flex-direction:column;gap:6px;margin-top:8px">
                        <button class="btn btn-sm" id="fo-build" ${S.src ? '' : 'disabled'} title="${S.src ? esc(S.src.path) : 'Pasta do Agent não encontrada ao lado do Server'}"><i class="fas fa-hammer"></i> Gerar da pasta do Agent${S.src ? ' (v' + esc(S.src.version || '?') + ')' : ''}</button>
                        <label class="btn btn-sm" style="cursor:pointer;margin:0"><i class="fas fa-upload"></i> Enviar ZIP do GBOC Agent<input type="file" id="fo-zip" accept=".zip,application/zip" style="display:none"></label>
                    </div>
                    <p style="font-size:.74em;color:var(--text-muted);margin:8px 0 0">O agente baixa o pacote do Server (funciona atrás de NAT), confere o SHA-256 e a sintaxe, guarda cópia dos arquivos substituídos e reinicia o serviço. Configurações, banco local, logs e repositórios não são alterados.</p>
                </div>
                <div style="margin-top:12px"><h4 style="margin:0 0 6px;font-size:.92em"><i class="fas fa-clock-rotate-left"></i> Lotes recentes</h4><div id="fo-hist" style="font-size:.84em"></div></div>
            </div>
        </div>`;
        const act = body.querySelector('#fo-action');
        const hint = () => {
            const a = ACTIONS.find(x => x[0] === act.value);
            body.querySelector('#fo-hint').textContent = a[3] || '';
            body.querySelector('#fo-name-l').style.display = act.value === 'run_tasks' ? '' : 'none';
        };
        act.onchange = hint; hint();
        body.querySelector('#fo-filter').oninput = (e) => { S.filter = e.target.value; const pos = e.target.selectionStart; render(); const f = document.getElementById('fo-filter'); f.focus(); f.setSelectionRange(pos, pos); };
        body.querySelectorAll('[data-ag]').forEach(c => c.onchange = () => { c.checked ? S.sel.add(c.dataset.ag) : S.sel.delete(c.dataset.ag); body.querySelector('#fo-count').textContent = S.sel.size; });
        body.querySelectorAll('[data-selq]').forEach(b => b.onclick = () => {
            const q = b.dataset.selq;
            S.sel = new Set(q === 'none' ? [] : list.filter(a => q === 'all' || (q === 'online' && a.online) || (q === 'outdated' && a.outdated)).map(a => a.agent_id));
            render();
        });
        body.querySelector('#fo-go').onclick = start;
        body.querySelector('#fo-build').onclick = async () => {
            const b = body.querySelector('#fo-build'); b.disabled = true; b.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Gerando...';
            try { await api('/update/package/build', { method: 'POST' }); toast('Pacote publicado', 'success'); await load(); render(); }
            catch (e) { toast(e.message, 'error'); b.disabled = false; }
        };
        body.querySelector('#fo-zip').onchange = async (e) => {
            const file = e.target.files[0]; if (!file) return;
            toast('Enviando pacote...', 'info');
            try {
                const r = await fetch(base() + '/api/v1/fleet/update/package/upload', { method: 'POST', headers: { 'Content-Type': 'application/zip' }, body: file });
                const d = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(d.detail || d.message || ('HTTP ' + r.status));
                toast(`Pacote v${d.package.version || '?'} publicado`, 'success'); await load(); render();
            } catch (err) { toast('Falha: ' + err.message, 'error'); }
        };
        history();
        if (S.job) showJob(S.job);
    }

    async function start() {
        const action = document.getElementById('fo-action').value;
        const ids = [...S.sel];
        if (!ids.length) { toast('Selecione ao menos um agente', 'warning'); return; }
        const label = ACTIONS.find(a => a[0] === action)[2];
        const msg = `${label} em ${ids.length} agente(s)?` + (action === 'update_agent' ? ` Os agentes serão atualizados para a v${S.pkg ? S.pkg.version : '?'} e o serviço será reiniciado.` : '');
        const ok = window.gbocConfirm ? await gbocConfirm(msg, { title: 'Operação em lote', type: ['stop_running', 'update_agent', 'pause_schedules'].includes(action) ? 'warning' : 'primary' }) : confirm(msg);
        if (!ok) return;
        const params = {};
        if (action === 'run_tasks') params.name_contains = document.getElementById('fo-name').value;
        try {
            const d = await api('/batch', { method: 'POST', body: JSON.stringify({ action, agent_ids: ids, params }) });
            S.job = d.job; showJob(d.job); pollJob(d.job.id);
        } catch (e) { toast(e.message, 'error'); }
    }

    function showJob(j) {
        const box = document.getElementById('fo-job');
        if (!box || !j) return;
        const res = j.results || [];
        const pend = (j.agent_ids || []).length - res.length;
        box.innerHTML = `<div style="border:1px solid var(--border);border-radius:8px;padding:10px">
            <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px"><b>Lote #${j.id} — ${esc(j.action_label || j.action)}</b>
            <span>${j.status === 'running' ? '<i class="fas fa-spinner fa-spin"></i> em andamento' : `<span class="badge badge-success">${j.ok_count} ok</span> ${j.fail_count ? `<span class="badge badge-error">${j.fail_count} com erro</span>` : ''}`}</span></div>
            <table class="data-table" style="font-size:.86em;margin-top:6px"><thead><tr><th>Agente</th><th>Resultado</th><th>Detalhe</th><th>Tempo</th></tr></thead><tbody>
            ${res.map(r => `<tr><td>${esc(r.hostname)}</td><td>${r.status === 'ok' ? '<span class="badge badge-success">OK</span>' : r.status === 'skipped' ? '<span class="badge badge-info">sem ação</span>' : r.status === 'running' ? '<i class="fas fa-spinner fa-spin"></i>' : '<span class="badge badge-error">Erro</span>'}</td>
                <td style="overflow-wrap:anywhere;max-width:420px">${esc(r.message || '')}</td><td>${r.seconds != null ? esc(r.seconds) + 's' : ''}</td></tr>`).join('')}
            ${pend > 0 ? `<tr><td colspan="4" style="color:var(--text-muted)">${pend} agente(s) na fila…</td></tr>` : ''}</tbody></table></div>`;
    }

    function pollJob(id) {
        clearInterval(S.timer);
        S.timer = setInterval(async () => {
            try {
                const d = await api('/jobs/' + id);
                S.job = d.job; showJob(d.job);
                if (d.job.status !== 'running') { clearInterval(S.timer); history(); if (d.job.action === 'update_agent') setTimeout(load, 15000); }
            } catch (e) { clearInterval(S.timer); }
        }, 2500);
    }

    async function history() {
        const box = document.getElementById('fo-hist');
        if (!box) return;
        try {
            const d = await api('/jobs?limit=8');
            box.innerHTML = (d.jobs || []).map(j => `<div style="display:flex;justify-content:space-between;gap:6px;padding:4px 0;border-bottom:1px solid var(--border);cursor:pointer" data-job="${j.id}">
                <span>#${j.id} ${esc(j.action_label)} · ${j.agents} agente(s)<br><span style="color:var(--text-muted);font-size:.85em">${dt(j.created_at)} · ${esc(j.created_by)}</span></span>
                <span>${j.status === 'running' ? '<i class="fas fa-spinner fa-spin"></i>' : `<span class="badge badge-success">${j.ok_count}</span>${j.fail_count ? ` <span class="badge badge-error">${j.fail_count}</span>` : ''}`}</span></div>`).join('') || '<span style="color:var(--text-muted)">Nenhum lote executado.</span>';
            box.querySelectorAll('[data-job]').forEach(el => el.onclick = async () => { const d2 = await api('/jobs/' + el.dataset.job); S.job = d2.job; showJob(d2.job); if (d2.job.status === 'running') pollJob(d2.job.id); });
        } catch (e) { box.textContent = e.message; }
    }

    window.GBOCFleet = {
        init() {
            const root = document.getElementById('fleet-ops');
            if (!root) return;
            if (!root.dataset.ready) { shell(root); root.dataset.ready = '1'; }
            load();
        },
    };
})();
