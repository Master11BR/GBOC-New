/* GBOC Server — Central de Relatórios (aba Relatórios do dashboard)
 * Catálogo dos relatórios reais (motor report_core) + relatórios executivos (flagships),
 * com filtros de período / agente / cliente, pré-visualização e exportação.
 */
(function () {
    'use strict';
    const base = () => (window.GBOC_API_BASE || '');
    const esc = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const ICONS = {
        'Operação': 'fa-gears', 'SLA': 'fa-stopwatch', 'Risco': 'fa-triangle-exclamation', 'Capacidade': 'fa-hard-drive',
        'Desempenho': 'fa-gauge-high', 'Inventário': 'fa-server', 'Recuperação': 'fa-life-ring', 'Segurança': 'fa-shield-halved',
        'Comercial': 'fa-coins', 'Executivo': 'fa-briefcase'
    };
    const state = { catalog: [], flagships: [], category: 'Todos', search: '', current: null, loaded: false };

    function params() {
        const days = document.getElementById('rc-days')?.value || document.getElementById('rpt-days')?.value || 30;
        const agent = document.getElementById('rc-agent')?.value || '';
        const tenant = document.getElementById('rc-tenant')?.value || '';
        const q = new URLSearchParams({ days });
        if (agent) q.set('agent_id', agent);
        if (tenant) q.set('tenant_id', tenant);
        return q.toString();
    }

    function shell(root) {
        root.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
            <h3 style="margin:0;font-size:1.1em;color:var(--primary)"><i class="fas fa-file-contract"></i> Central de Relatórios</h3>
            <span style="font-size:.8em;color:var(--text-muted)"><i class="fas fa-database"></i> Calculados a partir dos dados reais sincronizados pelos agentes</span>
        </div>
        <div class="rc-filters" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px">
            <select id="rc-days" class="form-control" style="width:auto">
                <option value="7">Últimos 7 dias</option><option value="30" selected>Últimos 30 dias</option>
                <option value="90">Últimos 90 dias</option><option value="180">Últimos 180 dias</option><option value="365">Últimos 12 meses</option>
            </select>
            <select id="rc-agent" class="form-control" style="width:auto;min-width:200px"><option value="">Todos os agentes</option></select>
            <select id="rc-tenant" class="form-control" style="width:auto;min-width:180px"><option value="">Todos os clientes</option></select>
            <input id="rc-search" class="form-control" placeholder="Buscar relatório..." style="flex:1;min-width:200px">
        </div>
        <div id="rc-cats" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px"></div>
        <div id="rc-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px"></div>
        <div id="rc-viewer" style="display:none;margin-top:16px"></div>
        <div class="panel" style="padding:14px;margin-top:16px">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
                <h4 style="margin:0;font-size:.98em"><i class="fas fa-envelope-open-text" style="color:var(--primary)"></i> Envios agendados por e-mail</h4>
                <button class="btn btn-sm btn-primary" id="rc-new-sched"><i class="fas fa-plus"></i> Novo agendamento</button>
            </div>
            <div id="rc-sched-form" style="display:none;margin-top:12px"></div>
            <div id="rc-sched-list" style="margin-top:10px;font-size:.88em"></div>
        </div>
        <div class="panel" style="padding:14px;margin-top:16px" id="rc-brand"></div>`;
        root.querySelector('#rc-new-sched').addEventListener('click', () => schedForm(state.current && state.current.kind === 'real' ? state.current.ref : null));
        root.querySelector('#rc-search').addEventListener('input', (e) => { state.search = e.target.value.toLowerCase(); renderGrid(); });
        ['rc-days', 'rc-agent', 'rc-tenant'].forEach(id => root.querySelector('#' + id).addEventListener('change', () => {
            if (state.current) openReport(state.current.kind, state.current.ref);
        }));
    }

    async function loadFilters() {
        try {
            const r = await fetch(base() + '/api/v1/agents');
            const d = await r.json();
            const agents = Array.isArray(d) ? d : (d.agents || []);
            const sel = document.getElementById('rc-agent');
            agents.sort((a, b) => String(a.hostname || '').localeCompare(String(b.hostname || '')))
                .forEach(a => sel.insertAdjacentHTML('beforeend', `<option value="${esc(a.agent_id)}">${esc(a.hostname || a.agent_id)}${a.ip_address ? ' (' + esc(a.ip_address) + ')' : ''}</option>`));
        } catch (e) { /* filtro opcional */ }
        try {
            const r = await fetch(base() + '/api/v1/tenant/organizations');
            const d = await r.json();
            const orgs = d.organizations || d.tenants || (Array.isArray(d) ? d : []);
            const sel = document.getElementById('rc-tenant');
            orgs.forEach(o => sel.insertAdjacentHTML('beforeend', `<option value="${esc(o.org_id || o.tenant_id || o.id)}">${esc(o.name || o.org_id)}</option>`));
            if (!orgs.length) sel.style.display = 'none';
        } catch (e) { document.getElementById('rc-tenant').style.display = 'none'; }
    }

    async function loadCatalog() {
        const grid = document.getElementById('rc-grid');
        grid.innerHTML = '<p style="color:var(--text-muted)"><i class="fas fa-spinner fa-spin"></i> Carregando catálogo...</p>';
        try {
            const [c, f] = await Promise.all([
                fetch(base() + '/api/v1/reports/catalog').then(r => r.json()),
                fetch(base() + '/api/v1/reports/flagships').then(r => r.json()).catch(() => ({ flagships: [] }))
            ]);
            state.catalog = (c.reports || []).map(r => ({ kind: 'real', ref: r.code, ...r }));
            state.flagships = (f.flagships || []).map(r => ({ kind: 'flagship', ref: r.id, code: r.id, category: 'Executivo',
                name: r.name, description: r.objective || r.description || '', audience: r.audience }));
            renderCats();
            renderGrid();
        } catch (e) {
            grid.innerHTML = `<p style="color:var(--danger)">Erro ao carregar catálogo: ${esc(e.message)}</p>`;
        }
    }

    function all() { return state.flagships.concat(state.catalog); }

    function renderCats() {
        const cats = ['Todos'].concat([...new Set(all().map(r => r.category))]);
        document.getElementById('rc-cats').innerHTML = cats.map(c =>
            `<button type="button" class="btn btn-sm ${c === state.category ? 'btn-primary' : ''}" data-cat="${esc(c)}">
                ${c !== 'Todos' ? `<i class="fas ${ICONS[c] || 'fa-file'}"></i> ` : ''}${esc(c)}</button>`).join('');
        document.querySelectorAll('#rc-cats button').forEach(b => b.addEventListener('click', () => {
            state.category = b.dataset.cat; renderCats(); renderGrid();
        }));
    }

    function renderGrid() {
        const list = all().filter(r => (state.category === 'Todos' || r.category === state.category) &&
            (!state.search || (r.name + ' ' + r.code + ' ' + r.description).toLowerCase().includes(state.search)));
        const grid = document.getElementById('rc-grid');
        if (!list.length) { grid.innerHTML = '<p style="color:var(--text-muted)">Nenhum relatório encontrado.</p>'; return; }
        grid.innerHTML = list.map(r => `
            <div class="panel" style="padding:12px;display:flex;flex-direction:column;justify-content:space-between;gap:8px;border-left:3px solid ${r.kind === 'flagship' ? 'var(--warning)' : 'var(--primary)'}">
                <div>
                    <div style="display:flex;justify-content:space-between;gap:6px;font-size:.74em;font-weight:700">
                        <span style="color:var(--primary)"><i class="fas ${ICONS[r.category] || 'fa-file'}"></i> ${esc(r.code)} · ${esc(r.category)}</span>
                        ${r.audience ? `<span style="color:var(--text-muted);font-weight:500">${esc(r.audience)}</span>` : ''}
                    </div>
                    <div style="font-weight:650;font-size:.92em;margin:4px 0">${esc(r.name)}</div>
                    <div style="font-size:.78em;color:var(--text-muted);line-height:1.4">${esc(r.description)}</div>
                </div>
                <div style="display:flex;gap:6px;flex-wrap:wrap">
                    <button class="btn btn-primary btn-sm" style="flex:1" data-open="${esc(r.kind)}|${esc(r.ref)}"><i class="fas fa-eye"></i> Visualizar</button>
                    <button class="btn btn-sm" title="Imprimir / PDF" data-pdf="${esc(r.kind)}|${esc(r.ref)}"><i class="fas fa-print"></i></button>
                    <button class="btn btn-sm" title="CSV" data-csv="${esc(r.kind)}|${esc(r.ref)}"><i class="fas fa-file-csv"></i></button>
                </div>
            </div>`).join('');
        grid.querySelectorAll('[data-open]').forEach(b => b.addEventListener('click', () => { const [k, ref] = b.dataset.open.split('|'); openReport(k, ref); }));
        grid.querySelectorAll('[data-pdf]').forEach(b => b.addEventListener('click', () => { const [k, ref] = b.dataset.pdf.split('|'); window.open(urlFor(k, ref, 'html'), '_blank'); }));
        grid.querySelectorAll('[data-csv]').forEach(b => b.addEventListener('click', () => { const [k, ref] = b.dataset.csv.split('|'); window.open(urlFor(k, ref, 'csv'), '_blank'); }));
    }

    function urlFor(kind, ref, format) {
        if (kind === 'flagship') {
            const f = format === 'embed' ? 'html' : format;
            return `${base()}/api/v1/reports/flagships/${encodeURIComponent(ref)}?format=${f}${format === 'html' ? '&print=1' : ''}`;
        }
        return `${base()}/api/v1/reports/v2/${encodeURIComponent(ref)}?format=${format}&${params()}`;
    }

    function openReport(kind, ref) {
        const r = all().find(x => x.kind === kind && String(x.ref) === String(ref));
        state.current = { kind, ref };
        const v = document.getElementById('rc-viewer');
        v.style.display = 'block';
        v.innerHTML = `
            <div class="panel" style="padding:12px">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px">
                    <div><strong style="color:var(--primary)">${esc(r ? r.code : ref)}</strong> — ${esc(r ? r.name : '')}
                        ${kind === 'real' ? '<span style="font-size:.78em;color:var(--text-muted)"> · os filtros acima se aplicam</span>' : ''}</div>
                    <div style="display:flex;gap:6px;flex-wrap:wrap">
                        <button class="btn btn-sm" id="rc-v-new"><i class="fas fa-up-right-from-square"></i> Nova aba</button>
                        <button class="btn btn-sm btn-primary" id="rc-v-pdf"><i class="fas fa-print"></i> Imprimir / PDF</button>
                        <button class="btn btn-sm" id="rc-v-csv"><i class="fas fa-file-csv"></i> CSV</button>
                        ${kind === 'real' ? '<button class="btn btn-sm" id="rc-v-html"><i class="fas fa-download"></i> HTML</button><button class="btn btn-sm" id="rc-v-json"><i class="fas fa-code"></i> JSON</button>' : ''}
                        ${kind === 'real' ? '<button class="btn btn-sm" id="rc-v-sched"><i class="fas fa-clock"></i> Agendar envio</button>' : ''}
                        <button class="btn btn-sm" id="rc-v-close" title="Fechar"><i class="fas fa-times"></i></button>
                    </div>
                </div>
                <iframe id="rc-frame" title="Relatório" src="${urlFor(kind, ref, 'embed')}"
                    style="width:100%;height:78vh;border:1px solid var(--border);border-radius:8px;background:#fff"></iframe>
            </div>`;
        v.querySelector('#rc-v-new').onclick = () => window.open(urlFor(kind, ref, 'html'), '_blank');
        v.querySelector('#rc-v-pdf').onclick = () => {
            const fr = document.getElementById('rc-frame');
            try { fr.contentWindow.focus(); fr.contentWindow.print(); } catch (e) { window.open(urlFor(kind, ref, 'html'), '_blank'); }
        };
        v.querySelector('#rc-v-csv').onclick = () => window.open(urlFor(kind, ref, 'csv'), '_blank');
        const h = v.querySelector('#rc-v-html'); if (h) h.onclick = () => window.open(urlFor(kind, ref, 'download'), '_blank');
        const j = v.querySelector('#rc-v-json'); if (j) j.onclick = () => window.open(urlFor(kind, ref, 'json'), '_blank');
        const sc = v.querySelector('#rc-v-sched'); if (sc) sc.onclick = () => schedForm(ref);
        v.querySelector('#rc-v-close').onclick = () => { v.style.display = 'none'; v.innerHTML = ''; state.current = null; };
        v.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // ── Agendamentos ──
    const WD = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];
    async function loadSchedules() {
        const box = document.getElementById('rc-sched-list');
        if (!box) return;
        try {
            const d = await fetch(base() + '/api/v1/reports/schedules').then(r => r.json());
            const list = d.schedules || [];
            if (!list.length) { box.innerHTML = '<p style="color:var(--text-muted);margin:6px 0">Nenhum envio agendado. Use "Agendar envio" em um relatório ou "Novo agendamento".</p>'; return; }
            box.innerHTML = `<div style="overflow-x:auto"><table class="data-table" style="font-size:.95em"><thead><tr><th>Nome</th><th>Relatório</th><th>Quando</th><th>Período</th><th>Destinatários</th><th>Último envio</th><th>Próximo</th><th></th></tr></thead><tbody>
                ${list.map(s => `<tr>
                    <td><strong>${esc(s.name)}</strong>${s.enabled ? '' : ' <span class="badge badge-warning">pausado</span>'}</td>
                    <td>${esc(s.report_code)}</td><td>${esc(s.description)}</td><td>${esc(s.days)} dias</td>
                    <td style="max-width:220px;overflow-wrap:anywhere">${esc(s.recipients) || ''}${s.send_to_client ? `${s.recipients ? '<br>' : ''}<span class="badge badge-info"><i class="fas fa-user-tie"></i> contatos do cliente</span>` : ''}</td>
                    <td>${s.last_run_at ? esc(new Date(s.last_run_at).toLocaleString('pt-BR')) : '—'}
                        ${s.last_status === 'error' ? `<br><span style="color:var(--danger);font-size:.85em" title="${esc(s.last_error)}"><i class="fas fa-triangle-exclamation"></i> ${esc((s.last_error || '').slice(0, 60))}</span>` : (s.last_status === 'sent' ? ' <i class="fas fa-check" style="color:var(--success)"></i>' : '')}</td>
                    <td>${s.next_run_at ? esc(new Date(s.next_run_at).toLocaleString('pt-BR')) : '—'}</td>
                    <td style="white-space:nowrap">
                        <button class="btn btn-sm" title="Enviar agora" data-srun="${s.id}"><i class="fas fa-paper-plane"></i></button>
                        <button class="btn btn-sm" title="${s.enabled ? 'Pausar' : 'Retomar'}" data-stog="${s.id}"><i class="fas fa-${s.enabled ? 'pause' : 'play'}"></i></button>
                        <button class="btn btn-sm" title="Excluir" data-sdel="${s.id}" style="color:var(--danger)"><i class="fas fa-trash"></i></button>
                    </td></tr>`).join('')}</tbody></table></div>`;
            box.querySelectorAll('[data-srun]').forEach(b => b.onclick = async () => {
                b.disabled = true; b.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
                const r = await fetch(`${base()}/api/v1/reports/schedules/${b.dataset.srun}/run`, { method: 'POST' });
                const d2 = await r.json().catch(() => ({}));
                if (typeof showToast === 'function') showToast(r.ok ? (d2.message || 'Enviado') : ('Falha no envio: ' + (d2.message || r.status)), r.ok ? 'success' : 'error');
                loadSchedules();
            });
            box.querySelectorAll('[data-stog]').forEach(b => b.onclick = async () => {
                const s = list.find(x => String(x.id) === b.dataset.stog);
                await fetch(`${base()}/api/v1/reports/schedules/${s.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...s, enabled: !s.enabled }) });
                loadSchedules();
            });
            box.querySelectorAll('[data-sdel]').forEach(b => b.onclick = async () => {
                if (!confirm('Excluir este agendamento?')) return;
                await fetch(`${base()}/api/v1/reports/schedules/${b.dataset.sdel}`, { method: 'DELETE' });
                loadSchedules();
            });
        } catch (e) { box.innerHTML = `<p style="color:var(--danger)">Erro ao carregar agendamentos: ${esc(e.message)}</p>`; }
    }

    function schedForm(ref) {
        const f = document.getElementById('rc-sched-form');
        const opts = state.catalog.map(r => `<option value="${esc(r.code)}" ${r.code === ref ? 'selected' : ''}>${esc(r.code)} — ${esc(r.name)}</option>`).join('');
        const agent = document.getElementById('rc-agent')?.value || '';
        const tenant = document.getElementById('rc-tenant')?.value || '';
        const days = document.getElementById('rc-days')?.value || 30;
        f.style.display = 'block';
        f.innerHTML = `
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;align-items:end">
                <label style="font-size:.82em">Relatório<select id="sf-rep" class="form-control">${opts}</select></label>
                <label style="font-size:.82em">Frequência<select id="sf-freq" class="form-control"><option value="daily">Diário</option><option value="weekly" selected>Semanal</option><option value="monthly">Mensal</option></select></label>
                <label style="font-size:.82em" id="sf-wd-l">Dia da semana<select id="sf-wd" class="form-control">${WD.map((w, i) => `<option value="${i}">${w}</option>`).join('')}</select></label>
                <label style="font-size:.82em;display:none" id="sf-dom-l">Dia do mês<input id="sf-dom" type="number" min="1" max="28" value="1" class="form-control"></label>
                <label style="font-size:.82em">Horário<input id="sf-time" type="time" value="08:00" class="form-control"></label>
                <label style="font-size:.82em">Período do relatório<select id="sf-days" class="form-control">
                    ${[7, 30, 90, 180, 365].map(d => `<option value="${d}" ${String(d) === String(days) ? 'selected' : ''}>Últimos ${d} dias</option>`).join('')}</select></label>
                <label style="font-size:.82em;grid-column:1/-1">Destinatários (separados por vírgula)<input id="sf-to" class="form-control" placeholder="diretoria@cliente.com.br, ti@cliente.com.br"></label>
                ${tenant ? `<label style="font-size:.82em;grid-column:1/-1;display:flex;gap:8px;align-items:center"><input type="checkbox" id="sf-client" checked>
                    Enviar também aos contatos do cliente (cadastrados em "Marca nos relatórios") — o relatório sai com a marca do cliente</label>` : ''}
            </div>
            <div style="font-size:.78em;color:var(--text-muted);margin-top:6px">Escopo: ${agent ? 'agente selecionado no filtro' : 'todos os agentes'}${tenant ? ' · cliente selecionado' : ''}. O envio usa o SMTP de Configurações &gt; Notificações e anexa o relatório em HTML (pronto para PDF) e CSV.</div>
            <div style="display:flex;gap:8px;margin-top:10px">
                <button class="btn btn-sm btn-primary" id="sf-save"><i class="fas fa-save"></i> Salvar agendamento</button>
                <button class="btn btn-sm" id="sf-cancel">Cancelar</button>
            </div>`;
        const freq = f.querySelector('#sf-freq');
        freq.onchange = () => {
            f.querySelector('#sf-wd-l').style.display = freq.value === 'weekly' ? '' : 'none';
            f.querySelector('#sf-dom-l').style.display = freq.value === 'monthly' ? '' : 'none';
        };
        f.querySelector('#sf-cancel').onclick = () => { f.style.display = 'none'; f.innerHTML = ''; };
        f.querySelector('#sf-save').onclick = async () => {
            const [hh, mm] = (f.querySelector('#sf-time').value || '08:00').split(':');
            const body = { report_code: f.querySelector('#sf-rep').value, frequency: freq.value, weekday: +f.querySelector('#sf-wd').value,
                day_of_month: +f.querySelector('#sf-dom').value, hour: +hh, minute: +mm, days: +f.querySelector('#sf-days').value,
                recipients: f.querySelector('#sf-to').value, agent_id: agent || null, tenant_id: tenant || null,
                send_to_client: !!(f.querySelector('#sf-client') && f.querySelector('#sf-client').checked) };
            const r = await fetch(base() + '/api/v1/reports/schedules', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            const d = await r.json().catch(() => ({}));
            if (!r.ok) { alert(d.detail || d.message || 'Não foi possível salvar.'); return; }
            f.style.display = 'none'; f.innerHTML = '';
            if (typeof showToast === 'function') showToast('Agendamento salvo: ' + (d.schedule?.description || ''), 'success');
            loadSchedules();
        };
        f.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }


    // ── Marca nos relatórios (white-label por cliente) ──
    const BR = { list: [], tenants: [], key: '_default', company: '' };
    async function loadBranding() {
        const box = document.getElementById('rc-brand');
        if (!box) return;
        try {
            const d = await fetch(base() + '/api/v1/reports/branding').then(r => r.json());
            BR.list = d.branding || []; BR.tenants = d.tenants || []; BR.company = d.company_name || '';
            renderBranding();
        } catch (e) { box.innerHTML = `<p style="color:var(--danger)">Erro ao carregar a marca: ${esc(e.message)}</p>`; }
    }

    function renderBranding() {
        const box = document.getElementById('rc-brand');
        const cur = BR.list.find(b => b.scope_key === BR.key) || {};
        const isDefault = BR.key === '_default';
        const tenantName = (BR.tenants.find(t => t.org_id === BR.key) || {}).name || BR.key;
        const configured = new Set(BR.list.map(b => b.scope_key));
        box.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px">
                <h4 style="margin:0;font-size:.98em"><i class="fas fa-palette" style="color:var(--primary)"></i> Marca nos relatórios (white-label)</h4>
                <select id="br-key" class="form-control" style="width:auto;min-width:260px">
                    <option value="_default" ${isDefault ? 'selected' : ''}>Padrão — sua empresa (provedor)${configured.has('_default') ? ' ✓' : ''}</option>
                    ${BR.tenants.map(t => `<option value="${esc(t.org_id)}" ${t.org_id === BR.key ? 'selected' : ''}>Cliente: ${esc(t.name)} (${t.agents} agente${t.agents == 1 ? '' : 's'})${configured.has(t.org_id) ? ' ✓' : ''}</option>`).join('')}
                </select>
            </div>
            <p style="font-size:.8em;color:var(--text-muted);margin:0 0 10px">${isDefault
                ? 'Usada em todos os relatórios. Relatórios filtrados por cliente usam a marca do cliente (quando cadastrada) com "Relatório preparado por" a sua empresa.'
                : `Usada quando o relatório é filtrado pelo cliente <b>${esc(tenantName)}</b> e nos envios agendados para ele. Campos vazios herdam a marca padrão.`}</p>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;align-items:start">
                <label style="font-size:.82em">Nome exibido<input id="br-name" class="form-control" maxlength="120" value="${esc(cur.display_name || '')}" placeholder="${esc(isDefault ? (BR.company || 'Sua empresa') : tenantName)}"></label>
                <label style="font-size:.82em">Cor principal<div style="display:flex;gap:6px"><input id="br-color" type="color" value="${esc(cur.primary_color || '#2a78d6')}" style="width:52px;height:36px;border:1px solid var(--border);border-radius:6px;background:none;padding:2px">
                    <input id="br-color-t" class="form-control" value="${esc(cur.primary_color || '')}" placeholder="#2a78d6 (padrão)" maxlength="7"></div></label>
                <label style="font-size:.82em">Contato no rodapé<input id="br-contact" class="form-control" maxlength="200" value="${esc(cur.contact || '')}" placeholder="suporte@empresa.com.br · (11) 4000-0000"></label>
                <label style="font-size:.82em;grid-column:1/-1">Texto do rodapé<input id="br-footer" class="form-control" maxlength="400" value="${esc(cur.footer_text || '')}" placeholder="Ex.: Documento confidencial — uso interno do cliente."></label>
                ${isDefault ? '' : `<label style="font-size:.82em;grid-column:1/-1">E-mails do cliente para envio automático (separados por vírgula)<input id="br-emails" class="form-control" value="${esc(cur.client_emails || '')}" placeholder="diretoria@cliente.com.br, ti@cliente.com.br"></label>`}
                <div style="font-size:.82em;grid-column:1/-1">Logotipo (PNG, JPG, SVG ou WEBP, até 300 KB)
                    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:4px">
                        <div id="br-logo-prev" style="min-width:120px;min-height:48px;border:1px dashed var(--border);border-radius:6px;padding:6px;background:#fff;display:flex;align-items:center;justify-content:center">
                            ${cur.logo_data ? `<img src="${esc(cur.logo_data)}" alt="" style="max-height:48px;max-width:220px">` : '<span style="color:#888;font-size:.85em">sem logotipo</span>'}</div>
                        <input type="file" id="br-logo" accept="image/png,image/jpeg,image/svg+xml,image/webp,image/gif" class="form-control" style="width:auto">
                        <button class="btn btn-sm" id="br-logo-rm" type="button"><i class="fas fa-eraser"></i> Remover logotipo</button>
                    </div></div>
            </div>
            <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
                <button class="btn btn-sm btn-primary" id="br-save"><i class="fas fa-save"></i> Salvar marca</button>
                <button class="btn btn-sm" id="br-preview"><i class="fas fa-eye"></i> Pré-visualizar (REP-01)</button>
                ${cur.scope_key ? '<button class="btn btn-sm" id="br-del" style="color:var(--danger)"><i class="fas fa-trash"></i> Remover marca</button>' : ''}
            </div>`;
        let logo = cur.logo_data || null;
        box.querySelector('#br-key').onchange = (e) => { BR.key = e.target.value; renderBranding(); };
        const ct = box.querySelector('#br-color-t'), cc = box.querySelector('#br-color');
        cc.oninput = () => { ct.value = cc.value; };
        ct.oninput = () => { if (/^#[0-9a-fA-F]{6}$/.test(ct.value)) cc.value = ct.value; };
        box.querySelector('#br-logo').onchange = (e) => {
            const file = e.target.files[0]; if (!file) return;
            if (file.size > 300 * 1024) { alert('O logotipo deve ter até 300 KB.'); e.target.value = ''; return; }
            const rd = new FileReader();
            rd.onload = () => { logo = rd.result; box.querySelector('#br-logo-prev').innerHTML = `<img src="${esc(logo)}" alt="" style="max-height:48px;max-width:220px">`; };
            rd.readAsDataURL(file);
        };
        box.querySelector('#br-logo-rm').onclick = () => { logo = null; box.querySelector('#br-logo-prev').innerHTML = '<span style="color:#888;font-size:.85em">sem logotipo</span>'; };
        box.querySelector('#br-save').onclick = async () => {
            const body = { display_name: box.querySelector('#br-name').value, primary_color: ct.value.trim(), logo_data: logo,
                contact: box.querySelector('#br-contact').value, footer_text: box.querySelector('#br-footer').value,
                client_emails: box.querySelector('#br-emails') ? box.querySelector('#br-emails').value : '' };
            const r = await fetch(`${base()}/api/v1/reports/branding/${encodeURIComponent(BR.key)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            const d = await r.json().catch(() => ({}));
            if (!r.ok) { alert(d.detail || d.message || 'Não foi possível salvar.'); return; }
            if (typeof showToast === 'function') showToast('Marca salva', 'success');
            loadBranding();
        };
        box.querySelector('#br-preview').onclick = () => {
            const q = new URLSearchParams({ format: 'html', days: document.getElementById('rc-days')?.value || 30 });
            if (!isDefault) q.set('tenant_id', BR.key);
            window.open(`${base()}/api/v1/reports/v2/REP-01?${q}`, '_blank');
        };
        const del = box.querySelector('#br-del');
        if (del) del.onclick = async () => {
            if (!confirm('Remover a marca personalizada? Os relatórios voltam ao visual padrão.')) return;
            await fetch(`${base()}/api/v1/reports/branding/${encodeURIComponent(BR.key)}`, { method: 'DELETE' });
            loadBranding();
        };
    }

    window.GBOCReportCenter = {
        init() {
            const root = document.getElementById('report-center');
            if (!root) return;
            if (!state.loaded) { shell(root); loadFilters(); state.loaded = true; }
            loadCatalog();
            loadSchedules();
            loadBranding();
        },
        open: openReport,
    };
})();
