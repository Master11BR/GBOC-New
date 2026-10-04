/* GBOC Server — Gerenciamento Remoto de Agentes (aba "Gerenciamento Remoto")
 * Opera um agente a partir do Server: visão geral, tarefas (executar, habilitar, histórico),
 * execuções em andamento (parar), repositórios (testar), logs, alertas e configuração da sincronização.
 * Usa /api/v1/agents/{id}/remote/... — canal WebSocket do agente (atravessa NAT) ou HTTP direto.
 */
(function () {
    'use strict';
    const base = () => (window.GBOC_API_BASE || '');
    const esc = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const S = { agents: [], agent: null, tab: 'tasks', timer: null, loaded: false };

    function bytes(b) {
        if (b == null || isNaN(b)) return '—';
        const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0, n = +b;
        while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
        return n.toLocaleString('pt-BR', { maximumFractionDigits: n < 100 ? 1 : 0 }) + ' ' + u[i];
    }
    const dt = (v) => v ? new Date(String(v).replace(' ', 'T')).toLocaleString('pt-BR') : '—';
    const dur = (s) => { if (s == null) return '—'; s = Math.round(+s); if (s < 60) return s + 's'; const m = Math.floor(s / 60); if (m < 60) return `${m}min ${s % 60}s`; return `${Math.floor(m / 60)}h ${m % 60}min`; };
    const paths = (v) => { if (Array.isArray(v)) return v; if (typeof v === 'string' && v.trim().startsWith('[')) { try { return JSON.parse(v); } catch (e) { /* texto */ } } return v ? [String(v)] : []; };
    const toast = (m, t) => (typeof showToast === 'function' ? showToast(m, t) : alert(m));
    const badge = (txt, tone) => `<span class="badge ${tone === 'ok' ? 'badge-success' : tone === 'bad' ? 'badge-error' : tone === 'warn' ? 'badge-warning' : 'badge-info'}">${esc(txt)}</span>`;
    const stTone = (s) => { s = String(s || '').toLowerCase(); return ['completed', 'success', 'ok'].includes(s) ? 'ok' : ['failed', 'error'].includes(s) ? 'bad' : ['running', 'pending', 'queued'].includes(s) ? 'warn' : 'info'; };

    async function api(path, opts) {
        const r = await fetch(`${base()}/api/v1/agents/${encodeURIComponent(S.agent)}/remote/api/${path.replace(/^\//, '')}`,
            Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}));
        const ch = r.headers.get('X-GBOC-Channel');
        if (ch) { const el = document.getElementById('rm-channel-used'); if (el) el.textContent = ch === 'websocket' ? 'via WebSocket' : ch === 'http' ? 'via HTTP direto' : ''; }
        let d; try { d = await r.json(); } catch (e) { d = {}; }
        if (!r.ok) throw new Error((typeof d.detail === 'string' ? d.detail : '') || d.message || ('HTTP ' + r.status));
        return d;
    }

    function shell(root) {
        root.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:16px">
            <h2 style="font-size:1.3em;margin:0"><i class="fas fa-satellite-dish" style="color:var(--primary);margin-right:8px"></i> Gerenciamento Remoto de Agentes</h2>
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
                <select id="rm-agent" class="form-control" style="min-width:260px;width:auto"></select>
                <button class="btn" id="rm-refresh"><i class="fas fa-rotate"></i> Atualizar</button>
                <button class="btn btn-primary" id="rm-sync"><i class="fas fa-cloud-arrow-up"></i> Sincronizar agora</button>
                <button class="btn" id="rm-term" title="Terminal, processos e serviços"><i class="fas fa-terminal"></i> Terminal</button>
            </div>
        </div>
        <div id="rm-summary" class="kpi-grid" style="margin-bottom:14px"></div>
        <div id="rm-tabs" style="display:flex;gap:6px;flex-wrap:wrap;border-bottom:1px solid var(--border);padding-bottom:10px;margin-bottom:12px">
            ${[['tasks', 'fa-list-check', 'Tarefas'], ['running', 'fa-spinner', 'Em execução'], ['repos', 'fa-database', 'Repositórios'],
               ['logs', 'fa-file-lines', 'Logs'], ['alerts', 'fa-bell', 'Alertas'], ['config', 'fa-sliders', 'Sincronização']]
                .map(([k, i, l]) => `<button class="btn btn-sm ${k === S.tab ? 'btn-primary' : ''}" data-rt="${k}"><i class="fas ${i}"></i> ${l}</button>`).join('')}
            <span id="rm-channel-used" style="margin-left:auto;font-size:.78em;color:var(--text-muted);align-self:center"></span>
        </div>
        <div id="rm-body" class="panel" style="padding:14px;min-height:200px"></div>`;
        root.querySelector('#rm-agent').addEventListener('change', (e) => { S.agent = e.target.value; refreshAll(); });
        root.querySelector('#rm-refresh').addEventListener('click', refreshAll);
        root.querySelector('#rm-sync').addEventListener('click', syncNow);
        root.querySelector('#rm-term').addEventListener('click', () => {
            if (typeof switchTab === 'function') switchTab('rmm');
            setTimeout(() => { const s = document.getElementById('rmm-agent-select'); if (s) { if (![...s.options].some(o => o.value === S.agent)) s.insertAdjacentHTML('beforeend', `<option value="${esc(S.agent)}">${esc(S.agent)}</option>`); s.value = S.agent; s.dispatchEvent(new Event('change')); } }, 400);
        });
        root.querySelectorAll('[data-rt]').forEach(b => b.addEventListener('click', () => {
            S.tab = b.dataset.rt;
            root.querySelectorAll('[data-rt]').forEach(x => x.classList.toggle('btn-primary', x === b));
            renderTab();
        }));
    }

    async function loadAgents() {
        const r = await fetch(base() + '/api/v1/agents');
        const d = await r.json();
        S.agents = (Array.isArray(d) ? d : (d.agents || [])).sort((a, b) => String(a.hostname || '').localeCompare(String(b.hostname || '')));
        const sel = document.getElementById('rm-agent');
        sel.innerHTML = S.agents.map(a => `<option value="${esc(a.agent_id)}">${a.status === 'online' ? '🟢' : '⚪'} ${esc(a.hostname || a.agent_id)}${a.ip_address ? ' — ' + esc(a.ip_address) : ''}</option>`).join('')
            || '<option value="">Nenhum agente registrado</option>';
        if (!S.agent || !S.agents.some(a => a.agent_id === S.agent)) {
            const on = S.agents.find(a => a.status === 'online');
            S.agent = (on || S.agents[0] || {}).agent_id || null;
        }
        if (S.agent) sel.value = S.agent;
    }

    async function summary() {
        const box = document.getElementById('rm-summary');
        box.innerHTML = '<div style="color:var(--text-muted)"><i class="fas fa-spinner fa-spin"></i> Conectando ao agente...</div>';
        try {
            const r = await fetch(`${base()}/api/v1/agents/${encodeURIComponent(S.agent)}/remote/status`);
            const d = await r.json();
            if (!r.ok) throw new Error(d.message || ('HTTP ' + r.status));
            const a = d.agent || {}, h = d.health || {}, c = d.channels || {}, l = (h.last_24h || {}), up = (h.uptime || {});
            const link = (d.server_link || {}).server || {};
            const tile = (label, value, sub, tone, icon) => `
                <div class="kpi-card" style="border-top:3px solid ${tone === 'ok' ? 'var(--success)' : tone === 'bad' ? 'var(--danger)' : tone === 'warn' ? 'var(--warning)' : 'var(--primary)'}">
                    <div class="kpi-header"><span>${esc(label)}</span><div class="kpi-icon"><i class="fas ${icon}"></i></div></div>
                    <div class="kpi-value" style="font-size:1.35em">${value}</div><div class="kpi-sub">${sub}</div></div>`;
            box.innerHTML = [
                tile('Conexão', c.reachable ? 'Acessível' : 'Inacessível', `${c.websocket ? 'WebSocket ativo' : 'Sem WebSocket'} · ${esc(d.address?.host || 'sem IP')}:${esc(d.address?.port || '')}`,
                     c.reachable ? 'ok' : 'bad', 'fa-plug'),
                tile('Agente', esc(a.hostname || S.agent), `v${esc(h.version || a.agent_version || '?')} · ${esc(a.os_info || '')}`, 'info', 'fa-server'),
                tile('Últimas 24 h', l.total != null ? `${l.ok}/${l.total}` : '—', l.total != null ? `${l.failed} falha(s) · ${(+l.success_rate || 0).toLocaleString('pt-BR')}% sucesso` : 'sem dados',
                     l.failed ? 'bad' : (l.total ? 'ok' : 'info'), 'fa-chart-simple'),
                tile('Recursos', `${(+a.cpu_usage || 0).toFixed(0)}% CPU`, `RAM ${(+a.ram_usage || 0).toFixed(0)}% · Disco ${(+a.disk_usage || 0).toFixed(0)}% · ativo há ${esc(up.uptime_str || '—')}`,
                     (+a.disk_usage || 0) >= 90 ? 'bad' : 'info', 'fa-microchip'),
                tile('Sincronização', link.last_sync_at ? dt(link.last_sync_at) : '—', `Heartbeat ${dt(link.last_heartbeat || a.last_heartbeat)} · a cada ${esc(link.sync_interval_minutes || '?')} min`, 'info', 'fa-arrows-rotate'),
            ].join('');
            if (!c.reachable) box.insertAdjacentHTML('beforeend', `<div style="grid-column:1/-1;color:var(--danger);font-size:.88em"><i class="fas fa-triangle-exclamation"></i> ${esc((d.health_error || {}).message || 'Agente inacessível')}</div>`);
        } catch (e) {
            box.innerHTML = `<div style="grid-column:1/-1;color:var(--danger)"><i class="fas fa-triangle-exclamation"></i> ${esc(e.message)}</div>`;
        }
    }

    async function syncNow() {
        const b = document.getElementById('rm-sync'); b.disabled = true;
        try { await api('api/server/sync', { method: 'POST', body: '{}' }); toast('Sincronização solicitada ao agente', 'success'); setTimeout(summary, 1500); }
        catch (e) { toast('Falha: ' + e.message, 'error'); }
        finally { b.disabled = false; }
    }

    function loading(msg) { document.getElementById('rm-body').innerHTML = `<div style="color:var(--text-muted);padding:20px"><i class="fas fa-spinner fa-spin"></i> ${esc(msg || 'Carregando...')}</div>`; }
    function fail(e) { document.getElementById('rm-body').innerHTML = `<div style="color:var(--danger);padding:16px"><i class="fas fa-triangle-exclamation"></i> ${esc(e.message || e)}</div>`; }

    async function tabTasks() {
        loading('Carregando tarefas do agente...');
        try {
            const d = await api('api/tasks/');
            const tasks = d.tasks || [];
            document.getElementById('rm-body').innerHTML = !tasks.length ? '<p style="color:var(--text-muted)">Nenhuma tarefa neste agente.</p>' : `
                <div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Tarefa</th><th>Motor</th><th>Repositório</th><th>Agendamento</th><th>Ativa</th><th>Última execução</th><th style="text-align:right">Ações</th></tr></thead><tbody>
                ${tasks.map(t => `<tr>
                    <td><strong>${esc(t.name)}</strong><div style="font-size:.78em;color:var(--text-muted)">${esc(paths(t.source_paths).join(', ')).slice(0, 160)}</div></td>
                    <td>${esc(t.engine || '—')}</td><td>${esc(t.repository_name || '—')}</td>
                    <td>${t.schedule_cron ? `<code>${esc(t.schedule_cron)}</code>${t.schedule_enabled ? '' : ' ' + badge('desativado', 'warn')}` : '<span style="color:var(--text-muted)">manual</span>'}</td>
                    <td><label style="cursor:pointer"><input type="checkbox" data-en="${t.id}" ${t.enabled !== false ? 'checked' : ''}> ${t.enabled !== false ? 'Sim' : 'Não'}</label></td>
                    <td>${t.last_status ? badge(t.last_status, stTone(t.last_status)) : '—'}<div style="font-size:.78em;color:var(--text-muted)">${dt(t.last_run)}</div></td>
                    <td style="text-align:right;white-space:nowrap">
                        <button class="btn btn-sm btn-primary" data-run="${t.id}" title="Executar agora"><i class="fas fa-play"></i> Executar</button>
                        <button class="btn btn-sm" data-hist="${t.id}" title="Histórico"><i class="fas fa-clock-rotate-left"></i></button>
                    </td></tr>
                    <tr id="rm-hist-${t.id}" style="display:none"><td colspan="7" style="background:var(--bg-input)"></td></tr>`).join('')}
                </tbody></table></div>`;
            document.querySelectorAll('#rm-body [data-run]').forEach(b => b.onclick = async () => {
                if (!confirm('Executar esta tarefa agora no agente?')) return;
                b.disabled = true;
                try { const r = await api(`api/tasks/${b.dataset.run}/run`, { method: 'POST', body: '{}' }); toast(r.message || 'Tarefa enviada', 'success'); S.tab = 'running'; markTab(); renderTab(); }
                catch (e) { toast('Falha: ' + e.message, 'error'); b.disabled = false; }
            });
            document.querySelectorAll('#rm-body [data-en]').forEach(c => c.onchange = async () => {
                try { await api(`api/tasks/${c.dataset.en}`, { method: 'PUT', body: JSON.stringify({ enabled: c.checked }) }); toast(c.checked ? 'Tarefa habilitada' : 'Tarefa desabilitada', 'success'); }
                catch (e) { toast('Falha: ' + e.message, 'error'); c.checked = !c.checked; }
            });
            document.querySelectorAll('#rm-body [data-hist]').forEach(b => b.onclick = async () => {
                const row = document.getElementById('rm-hist-' + b.dataset.hist);
                if (row.style.display !== 'none') { row.style.display = 'none'; return; }
                row.style.display = ''; row.firstElementChild.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
                try {
                    const h = await api(`api/tasks/${b.dataset.hist}/history?limit=10`);
                    const list = h.history || [];
                    row.firstElementChild.innerHTML = !list.length ? 'Sem execuções.' : `<table class="data-table" style="font-size:.85em"><thead><tr><th>Início</th><th>Status</th><th>Duração</th><th>Processado</th><th>Novos dados</th><th>Erro</th></tr></thead><tbody>
                        ${list.map(x => `<tr><td>${dt(x.started_at)}</td><td>${badge(x.status, stTone(x.status))}</td><td>${dur(x.duration_seconds)}</td><td>${bytes(x.bytes_processed)}</td><td>${bytes(x.bytes_added)}</td><td style="color:var(--danger);max-width:380px;overflow-wrap:anywhere">${esc((x.error_message || '').slice(0, 200))}</td></tr>`).join('')}</tbody></table>`;
                } catch (e) { row.firstElementChild.innerHTML = `<span style="color:var(--danger)">${esc(e.message)}</span>`; }
            });
        } catch (e) { fail(e); }
    }

    async function tabRunning() {
        loading('Consultando execuções...');
        try {
            const d = await api('api/tasks/running/detailed');
            const ex = d.executions || [];
            document.getElementById('rm-body').innerHTML = !ex.length ? '<p style="color:var(--text-muted)"><i class="fas fa-circle-check" style="color:var(--success)"></i> Nenhuma execução em andamento. (Atualiza a cada 5 s)</p>' : `
                <table class="data-table"><thead><tr><th>Tarefa</th><th>Início</th><th>Progresso</th><th>Arquivo atual</th><th>Processado</th><th></th></tr></thead><tbody>
                ${ex.map(x => `<tr><td><strong>${esc(x.task_name || x.name || ('Tarefa ' + x.task_id))}</strong></td><td>${dt(x.started_at)}</td>
                    <td style="min-width:160px"><div style="background:var(--bg-input);border-radius:6px;height:10px;overflow:hidden"><div style="width:${Math.min(100, +x.progress || 0)}%;height:100%;background:var(--primary)"></div></div><span style="font-size:.8em">${(+x.progress || 0).toFixed(0)}%</span></td>
                    <td style="font-size:.8em;max-width:320px;overflow-wrap:anywhere">${esc(x.current_file || '—')}</td><td>${bytes(x.bytes_processed)}</td>
                    <td><button class="btn btn-sm" style="color:var(--danger)" data-stop="${x.id || x.execution_id}"><i class="fas fa-stop"></i> Parar</button></td></tr>`).join('')}</tbody></table>`;
            document.querySelectorAll('#rm-body [data-stop]').forEach(b => b.onclick = async () => {
                if (!confirm('Interromper esta execução?')) return;
                try { await api(`api/tasks/execution/${b.dataset.stop}/stop`, { method: 'POST', body: '{}' }); toast('Execução interrompida', 'success'); tabRunning(); }
                catch (e) { toast('Falha: ' + e.message, 'error'); }
            });
        } catch (e) { fail(e); }
    }

    async function tabRepos() {
        loading('Carregando repositórios...');
        try {
            const d = await api('api/repositories/');
            const repos = Array.isArray(d) ? d : (d.repositories || []);
            document.getElementById('rm-body').innerHTML = !repos.length ? '<p style="color:var(--text-muted)">Nenhum repositório.</p>' : `
                <table class="data-table"><thead><tr><th>Repositório</th><th>Motor</th><th>Tipo</th><th>Destino</th><th>Status</th><th></th></tr></thead><tbody>
                ${repos.map(r => `<tr><td><strong>${esc(r.name)}</strong></td><td>${esc(r.engine)}</td><td>${esc(r.type)}</td>
                    <td style="font-size:.82em;max-width:360px;overflow-wrap:anywhere">${esc(r.path || r.bucket || '—')}</td><td>${badge(r.status || '—', ['active', 'ready'].includes(r.status) ? 'ok' : 'warn')}</td>
                    <td><button class="btn btn-sm" data-test="${r.id}"><i class="fas fa-vial"></i> Testar acesso</button></td></tr>`).join('')}</tbody></table>`;
            document.querySelectorAll('#rm-body [data-test]').forEach(b => b.onclick = async () => {
                b.disabled = true; b.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Testando';
                try { const r = await api(`api/repositories/${b.dataset.test}/test`, { method: 'POST', body: '{}' }); toast(r.message || (r.success === false ? 'Falhou' : 'Repositório acessível'), r.success === false ? 'error' : 'success'); }
                catch (e) { toast('Falha: ' + e.message, 'error'); }
                finally { b.disabled = false; b.innerHTML = '<i class="fas fa-vial"></i> Testar acesso'; }
            });
        } catch (e) { fail(e); }
    }

    async function tabLogs() {
        const body = document.getElementById('rm-body');
        body.innerHTML = `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
            <select id="rm-lv" class="form-control" style="width:auto"><option value="">Todos os níveis</option><option>ERROR</option><option>WARNING</option><option>INFO</option></select>
            <select id="rm-lh" class="form-control" style="width:auto"><option value="1">Última hora</option><option value="24" selected>24 h</option><option value="168">7 dias</option></select>
            <input id="rm-ls" class="form-control" placeholder="Buscar..." style="flex:1;min-width:180px"><button class="btn btn-sm" id="rm-lgo"><i class="fas fa-magnifying-glass"></i></button></div>
            <div id="rm-lout"></div>`;
        const go = async () => {
            const out = document.getElementById('rm-lout'); out.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            const q = new URLSearchParams({ limit: 300, hours: document.getElementById('rm-lh').value });
            if (document.getElementById('rm-lv').value) q.set('level', document.getElementById('rm-lv').value);
            if (document.getElementById('rm-ls').value) q.set('search', document.getElementById('rm-ls').value);
            try {
                const d = await api('api/logs/?' + q.toString());
                const logs = d.logs || [];
                out.innerHTML = !logs.length ? '<p style="color:var(--text-muted)">Nenhum log no filtro.</p>' : `<div style="max-height:60vh;overflow:auto"><table class="data-table" style="font-size:.84em"><thead><tr><th>Data</th><th>Nível</th><th>Origem</th><th>Mensagem</th></tr></thead><tbody>
                    ${logs.map(l => `<tr><td style="white-space:nowrap">${dt(l.timestamp)}</td><td>${badge(l.level, /err|crit/i.test(l.level) ? 'bad' : /warn/i.test(l.level) ? 'warn' : 'info')}</td><td>${esc(l.source)}</td><td style="overflow-wrap:anywhere">${esc((l.message || '').slice(0, 400))}</td></tr>`).join('')}</tbody></table></div>`;
            } catch (e) { out.innerHTML = `<span style="color:var(--danger)">${esc(e.message)}</span>`; }
        };
        document.getElementById('rm-lgo').onclick = go;
        ['rm-lv', 'rm-lh'].forEach(id => document.getElementById(id).onchange = go);
        go();
    }

    async function tabAlerts() {
        loading('Carregando alertas...');
        try {
            const d = await api('api/alerts/?resolved=false&limit=100');
            const al = d.alerts || [];
            document.getElementById('rm-body').innerHTML = !al.length ? '<p style="color:var(--text-muted)"><i class="fas fa-circle-check" style="color:var(--success)"></i> Nenhum alerta aberto.</p>' : `
                <table class="data-table"><thead><tr><th>Data</th><th>Severidade</th><th>Alerta</th><th></th></tr></thead><tbody>
                ${al.map(a => `<tr><td style="white-space:nowrap">${dt(a.timestamp)}</td><td>${badge(a.severity, /crit|error/i.test(a.severity) ? 'bad' : /warn/i.test(a.severity) ? 'warn' : 'info')}</td>
                    <td><strong>${esc(a.title || a.type)}</strong><div style="font-size:.82em;color:var(--text-muted);overflow-wrap:anywhere">${esc((a.message || '').slice(0, 300))}</div></td>
                    <td style="white-space:nowrap">${a.acknowledged ? '' : `<button class="btn btn-sm" data-ack="${a.id}"><i class="fas fa-eye"></i> Reconhecer</button>`}
                        <button class="btn btn-sm" data-res="${a.id}"><i class="fas fa-check"></i> Resolver</button></td></tr>`).join('')}</tbody></table>`;
            document.querySelectorAll('#rm-body [data-ack]').forEach(b => b.onclick = async () => { try { await api(`api/alerts/${b.dataset.ack}/acknowledge`, { method: 'PUT', body: '{}' }); tabAlerts(); } catch (e) { toast(e.message, 'error'); } });
            document.querySelectorAll('#rm-body [data-res]').forEach(b => b.onclick = async () => { try { await api(`api/alerts/${b.dataset.res}/resolve`, { method: 'PUT', body: '{}' }); tabAlerts(); } catch (e) { toast(e.message, 'error'); } });
        } catch (e) { fail(e); }
    }

    async function tabConfig() {
        loading('Lendo configuração do agente...');
        try {
            const d = await api('api/server/status');
            const s = d.server || {};
            const cfg = s.config || s;
            document.getElementById('rm-body').innerHTML = `
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px">
                    <div><div style="font-size:.82em;color:var(--text-muted)">Servidor configurado no agente</div><div style="font-weight:600;overflow-wrap:anywhere">${esc(s.server_url || cfg.server_url || '—')}</div>
                        <div style="font-size:.82em;margin-top:6px">${s.is_registered ? badge('Registrado', 'ok') : badge('Não registrado', 'warn')} ${s.paired ? badge('Pareado', 'ok') : badge('Sem chave', 'bad')} ${s.websocket_connected ? badge('WebSocket ativo', 'ok') : badge('Sem WebSocket', 'warn')}</div>
                        <div style="font-size:.8em;color:var(--text-muted);margin-top:6px">Última sincronização: ${dt(s.last_sync_at)} · Último heartbeat: ${dt(s.last_heartbeat)}</div></div>
                    <label style="font-size:.85em">Intervalo do heartbeat (min)
                        <div style="display:flex;gap:6px"><input id="rm-hb" type="number" min="1" max="60" class="form-control" value="${esc(cfg.heartbeat_interval_minutes || s.heartbeat_interval || 2)}"><button class="btn btn-sm btn-primary" id="rm-hb-save">Aplicar</button></div></label>
                    <label style="font-size:.85em">Intervalo de sincronização (min)
                        <div style="display:flex;gap:6px"><input id="rm-si" type="number" min="5" max="1440" class="form-control" value="${esc(cfg.sync_interval_minutes || s.sync_interval || 10)}"><button class="btn btn-sm btn-primary" id="rm-si-save">Aplicar</button></div></label>
                </div>
                <p style="font-size:.8em;color:var(--text-muted);margin-top:12px">Intervalos menores deixam relatórios e painéis mais atualizados, com mais tráfego entre agente e Server. Recomendado: heartbeat 2 min, sincronização 10–15 min.</p>`;
            document.getElementById('rm-hb-save').onclick = async () => {
                try { const r = await api('api/server/config/heartbeat?interval_minutes=' + encodeURIComponent(document.getElementById('rm-hb').value), { method: 'POST', body: '{}' }); toast(r.message || 'Aplicado', r.status === 'error' ? 'error' : 'success'); } catch (e) { toast(e.message, 'error'); }
            };
            document.getElementById('rm-si-save').onclick = async () => {
                try { const r = await api('api/server/config/sync-interval?interval_minutes=' + encodeURIComponent(document.getElementById('rm-si').value), { method: 'POST', body: '{}' }); toast(r.message || 'Aplicado', r.status === 'error' ? 'error' : 'success'); } catch (e) { toast(e.message, 'error'); }
            };
        } catch (e) { fail(e); }
    }

    function markTab() { document.querySelectorAll('#rm-tabs [data-rt]').forEach(x => x.classList.toggle('btn-primary', x.dataset.rt === S.tab)); }

    function renderTab() {
        clearInterval(S.timer);
        if (!S.agent) { document.getElementById('rm-body').innerHTML = '<p style="color:var(--text-muted)">Selecione um agente.</p>'; return; }
        ({ tasks: tabTasks, running: tabRunning, repos: tabRepos, logs: tabLogs, alerts: tabAlerts, config: tabConfig }[S.tab] || tabTasks)();
        if (S.tab === 'running') S.timer = setInterval(() => {
            const t = document.getElementById('tab-remote');
            if (!document.hidden && t && t.classList.contains('active') && S.tab === 'running') tabRunning(); else clearInterval(S.timer);
        }, 5000);
    }

    function refreshAll() { if (!S.agent) return; summary(); renderTab(); }

    window.GBOCRemote = {
        async init(agentId) {
            const root = document.getElementById('remote-mgmt');
            if (!root) return;
            if (!S.loaded) { shell(root); S.loaded = true; }
            try { await loadAgents(); } catch (e) { document.getElementById('rm-body').innerHTML = `<span style="color:var(--danger)">${esc(e.message)}</span>`; return; }
            if (agentId) { S.agent = agentId; document.getElementById('rm-agent').value = agentId; }
            refreshAll();
        }
    };
})();
