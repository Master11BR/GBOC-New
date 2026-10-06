/* GBOC Server — Políticas e Implantação (aba "Políticas e Implantação")
 * Políticas centrais (agendamento, retenção, novas tentativas, janela de manutenção, banda, imutabilidade),
 * conformidade (fora da política) e instalação em massa do GBOC Agent (tokens de instalação).
 * API: /api/v1/policies, /api/v1/fleet/install-tokens
 */
(function () {
    'use strict';
    const base = () => (window.GBOC_API_BASE || '');
    const esc = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const toast = (m, t) => (typeof showToast === 'function' ? showToast(m, t) : alert(m));
    const dt = (v) => v ? new Date(String(v).replace(' ', 'T')).toLocaleString('pt-BR') : '—';
    const DAYS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
    const S = { policies: [], agents: [], tenants: [], comp: null, edit: null, timer: null };

    async function api(path, opts) {
        const r = await fetch(base() + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}));
        let d; try { d = await r.json(); } catch (e) { d = {}; }
        if (!r.ok) throw new Error((typeof d.detail === 'string' ? d.detail : '') || d.message || ('HTTP ' + r.status));
        return d;
    }
    const daysTxt = (d) => (d || []).map(i => DAYS[i]).join(', ');

    function shell(root) {
        root.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px">
            <h2 style="font-size:1.3em;margin:0"><i class="fas fa-sitemap" style="color:var(--primary);margin-right:8px"></i> Políticas e Implantação</h2>
            <div style="display:flex;gap:8px"><button class="btn" id="pc-refresh"><i class="fas fa-rotate"></i> Atualizar</button>
                <button class="btn btn-primary" id="pc-new"><i class="fas fa-plus"></i> Nova política</button></div>
        </div>
        <div id="pc-kpis" class="kpi-grid" style="margin-bottom:14px"></div>
        <div class="panel" style="padding:14px;margin-bottom:16px">
            <h3 style="margin:0 0 8px;font-size:1em"><i class="fas fa-list-check" style="color:var(--primary)"></i> Políticas centrais</h3>
            <p style="font-size:.8em;color:var(--text-muted);margin:0 0 8px">Defina o padrão uma vez e aplique em vários agentes. Se um agente estiver em mais de uma política, vale a de maior prioridade.</p>
            <div id="pc-editor" style="display:none;margin-bottom:12px"></div>
            <div id="pc-list"></div>
        </div>
        <div class="panel" style="padding:14px;margin-bottom:16px">
            <h3 style="margin:0 0 8px;font-size:1em"><i class="fas fa-scale-balanced" style="color:var(--primary)"></i> Conformidade (fora da política)</h3>
            <div id="pc-comp"></div>
        </div>
        <div class="panel" style="padding:14px">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
                <h3 style="margin:0;font-size:1em"><i class="fas fa-download" style="color:var(--primary)"></i> Instalação em massa do GBOC Agent</h3>
                <button class="btn btn-sm btn-primary" id="it-new"><i class="fas fa-key"></i> Novo token de instalação</button>
            </div>
            <p style="font-size:.8em;color:var(--text-muted);margin:6px 0 8px">Um comando por máquina (ou GPO/Intune) baixa o Agent deste Server, instala sem perguntas e já inscreve no cliente certo — sem digitar a chave de pareamento. Requer um pacote do Agent publicado (Gerenciamento Remoto &gt; Operações em lote).</p>
            <div id="it-form" style="display:none"></div>
            <div id="it-result"></div>
            <div id="it-list"></div>
        </div>`;
        root.querySelector('#pc-refresh').onclick = load;
        root.querySelector('#pc-new').onclick = () => editor(null);
        root.querySelector('#it-new').onclick = tokenForm;
    }

    async function load() {
        try {
            const [p, f, t, c] = await Promise.all([api('/api/v1/policies'), api('/api/v1/fleet/agents'),
                api('/api/v1/tenant/organizations').catch(() => ({})), api('/api/v1/policies/compliance')]);
            S.policies = p.policies || []; S.agents = f.agents || []; S.comp = c;
            S.tenants = t.organizations || t.tenants || (Array.isArray(t) ? t : []);
            const sm = c.summary || {};
            document.getElementById('pc-kpis').innerHTML = [
                ['Políticas ativas', S.policies.filter(x => x.enabled).length, `${S.policies.length} cadastrada(s)`, 'blue', 'fa-sitemap'],
                ['Conformes', sm.conforme || 0, 'agentes', 'green', 'fa-circle-check'],
                ['Fora da política', sm.fora || 0, sm.fora ? 'reaplicar' : 'nenhum', sm.fora ? 'red' : 'green', 'fa-triangle-exclamation'],
                ['Sem política', sm.sem_politica || 0, sm.sem_dados ? `${sm.sem_dados} sem dados` : 'agentes', 'orange', 'fa-circle-question'],
            ].map(([l, v, s, cl, i]) => `<div class="kpi-card"><div class="kpi-header"><span>${l}</span><div class="kpi-icon ${cl}"><i class="fas ${i}"></i></div></div><div class="kpi-value">${esc(v)}</div><div class="kpi-sub">${esc(s)}</div></div>`).join('');
            renderList(); renderComp();
        } catch (e) { document.getElementById('pc-list').innerHTML = `<p style="color:var(--danger)">${esc(e.message)}</p>`; }
        loadTokens();
    }

    function summary(s) {
        const out = [];
        if (s.schedule) out.push(`Agenda ${esc(s.schedule.cron || '')}${s.schedule.enabled === false ? ' (desligada)' : ''}`);
        if (s.retention) out.push('Retenção ' + Object.entries(s.retention).map(([k, v]) => `${v}${{ days: 'd', weekly: 's', monthly: 'm', yearly: 'a' }[k]}`).join('/'));
        if (s.retry) out.push(`Novas tentativas ${s.retry.enabled === false ? 'off' : (s.retry.max_attempts ?? '') + 'x'}`);
        if (s.maintenance_windows) out.push(s.maintenance_windows.length ? `Manutenção: ${s.maintenance_windows.map(w => daysTxt(w.days) + ' ' + w.start + '–' + w.end).join('; ')}` : 'Sem janela de manutenção');
        if (s.bandwidth) out.push(`Banda ${s.bandwidth.default_mbps ? s.bandwidth.default_mbps + ' Mbps' : 'livre'}${(s.bandwidth.rules || []).length ? ' + ' + s.bandwidth.rules.length + ' regra(s)' : ''}`);
        if (s.immutability) out.push(`Imutável ${s.immutability.days} dias (${s.immutability.lock_mode})`);
        return out.join(' · ');
    }

    function target(p) {
        const parts = [];
        if (p.scope_all) parts.push('Todos os agentes');
        if (p.tenant_id) parts.push('Cliente ' + ((S.tenants.find(t => (t.org_id || t.id) === p.tenant_id) || {}).name || p.tenant_id));
        if ((p.agent_ids || []).length) parts.push(`${p.agent_ids.length} agente(s)`);
        return parts.join(' + ');
    }

    function renderList() {
        const box = document.getElementById('pc-list');
        if (!S.policies.length) { box.innerHTML = '<p style="color:var(--text-muted)">Nenhuma política. Crie a primeira com "Nova política".</p>'; return; }
        box.innerHTML = `<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Política</th><th>Alvo</th><th>Tarefas</th><th>Define</th><th>Prioridade</th><th>Efetiva em</th><th>Última aplicação</th><th></th></tr></thead><tbody>
            ${S.policies.map(p => `<tr><td><strong>${esc(p.name)}</strong> <span style="font-size:.75em;color:var(--text-muted)">v${p.version}</span>${p.enabled ? '' : ' <span class="badge badge-warning">desativada</span>'}<div style="font-size:.78em;color:var(--text-muted)">${esc(p.description || '')}</div></td>
                <td>${esc(target(p))}</td><td>${p.task_filter ? 'nome contém "' + esc(p.task_filter) + '"' : 'todas'}</td>
                <td style="font-size:.8em;max-width:380px">${summary(p.settings || {})}</td><td>${p.priority}</td>
                <td>${p.effective_on}/${p.targets}</td><td>${dt(p.last_applied_at)}</td>
                <td style="white-space:nowrap"><button class="btn btn-sm btn-primary" data-apply="${p.id}" ${p.enabled ? '' : 'disabled'}><i class="fas fa-play"></i> Aplicar</button>
                    <button class="btn btn-sm" data-edit="${p.id}"><i class="fas fa-pen"></i></button>
                    <button class="btn btn-sm" data-del="${p.id}" style="color:var(--danger)"><i class="fas fa-trash"></i></button></td></tr>`).join('')}</tbody></table></div>
            <div id="pc-job" style="margin-top:10px"></div>`;
        box.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => editor(S.policies.find(p => String(p.id) === b.dataset.edit)));
        box.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
            if (!confirm('Excluir esta política? O que já foi aplicado nos agentes continua como está.')) return;
            try { await api('/api/v1/policies/' + b.dataset.del, { method: 'DELETE' }); load(); } catch (e) { toast(e.message, 'error'); }
        });
        box.querySelectorAll('[data-apply]').forEach(b => b.onclick = async () => {
            const p = S.policies.find(x => String(x.id) === b.dataset.apply);
            const ok = window.gbocConfirm ? await gbocConfirm(`Aplicar "${p.name}" em ${p.effective_on} agente(s)? As tarefas e configurações serão ajustadas conforme a política.`, { title: 'Aplicar política', type: 'warning' }) : confirm('Aplicar?');
            if (!ok) return;
            try { const d = await api(`/api/v1/policies/${p.id}/apply`, { method: 'POST', body: '{}' }); pollJob(d.job.id); }
            catch (e) { toast(e.message, 'error'); }
        });
    }

    function pollJob(id) {
        clearInterval(S.timer);
        const show = (j) => {
            const box = document.getElementById('pc-job'); if (!box) return;
            box.innerHTML = `<div style="border:1px solid var(--border);border-radius:8px;padding:10px;font-size:.88em"><b>Lote #${j.id} — ${esc(j.action_label)}</b> ${j.status === 'running' ? '<i class="fas fa-spinner fa-spin"></i>' : `<span class="badge badge-success">${j.ok_count} ok</span> ${j.fail_count ? `<span class="badge badge-error">${j.fail_count} erro(s)</span>` : ''}`}
                ${(j.results || []).map(r => `<div style="margin-top:4px">${r.status === 'ok' ? '<i class="fas fa-check" style="color:var(--success)"></i>' : r.status === 'running' ? '<i class="fas fa-spinner fa-spin"></i>' : '<i class="fas fa-xmark" style="color:var(--danger)"></i>'} <b>${esc(r.hostname)}</b> ${esc(r.message || '')}</div>`).join('')}</div>`;
        };
        S.timer = setInterval(async () => {
            try { const d = await api('/api/v1/fleet/jobs/' + id); show(d.job); if (d.job.status !== 'running') { clearInterval(S.timer); setTimeout(load, 4000); } }
            catch (e) { clearInterval(S.timer); }
        }, 2000);
    }

    function renderComp() {
        const box = document.getElementById('pc-comp');
        const rows = (S.comp && S.comp.agents) || [];
        if (!rows.length) { box.innerHTML = '<p style="color:var(--text-muted)">Nenhum agente com política. Crie e aplique uma política.</p>'; return; }
        box.innerHTML = `<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Agente</th><th>Política efetiva</th><th>Situação</th><th>Aplicada</th><th>Diferenças</th><th></th></tr></thead><tbody>
            ${rows.map(r => `<tr><td><strong>${esc(r.hostname)}</strong></td><td>${esc(r.policy)} v${esc(r.version)}</td>
                <td>${r.state === 'conforme' ? '<span class="badge badge-success">Conforme</span>' : r.state === 'sem dados' ? '<span class="badge badge-info">Sem dados</span>' : '<span class="badge badge-error">Fora da política</span>'}</td>
                <td style="font-size:.82em">${r.applied ? 'v' + esc(r.applied.version) + ' em ' + dt(r.applied.applied_at) : '—'}</td>
                <td style="font-size:.8em;max-width:480px">${(r.issues || []).map(i => '• ' + esc(i)).join('<br>') || '—'}</td>
                <td>${r.state !== 'conforme' ? `<button class="btn btn-sm" data-reapply="${r.policy_id}|${esc(r.agent_id)}"><i class="fas fa-rotate-right"></i> Reaplicar</button>` : ''}</td></tr>`).join('')}</tbody></table></div>
            <p style="font-size:.76em;color:var(--text-muted)">Comparado com os dados sincronizados pelos agentes (atualiza a cada sincronização). ${S.comp.without_policy.length} agente(s) sem política.</p>`;
        box.querySelectorAll('[data-reapply]').forEach(b => b.onclick = async () => {
            const [pid, aid] = b.dataset.reapply.split('|');
            try { const d = await api(`/api/v1/policies/${pid}/apply`, { method: 'POST', body: JSON.stringify({ agent_ids: [aid] }) }); toast('Reaplicando…', 'info'); pollJob(d.job.id); }
            catch (e) { toast(e.message, 'error'); }
        });
    }

    // ── editor ──
    function winRow(w, withMbps) {
        return `<div class="pc-win" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:4px 0">
            ${DAYS.map((d, i) => `<label style="font-size:.78em"><input type="checkbox" data-d="${i}" ${(w.days || []).includes(i) ? 'checked' : ''}> ${d}</label>`).join('')}
            <input type="time" data-s value="${esc(w.start || '08:00')}" class="form-control" style="width:auto"> até
            <input type="time" data-e value="${esc(w.end || '18:00')}" class="form-control" style="width:auto">
            ${withMbps ? `<input type="number" min="0" step="any" data-m value="${esc(w.mbps ?? 10)}" class="form-control" style="width:90px"> Mbps`
                : `<input data-l value="${esc(w.label || '')}" placeholder="descrição" class="form-control" style="width:160px">`}
            <button class="btn btn-sm" data-rm type="button"><i class="fas fa-xmark"></i></button></div>`;
    }
    function readWins(box, withMbps) {
        return [...box.querySelectorAll('.pc-win')].map(r => {
            const o = { days: [...r.querySelectorAll('[data-d]:checked')].map(c => +c.dataset.d), start: r.querySelector('[data-s]').value, end: r.querySelector('[data-e]').value };
            if (withMbps) o.mbps = +r.querySelector('[data-m]').value || 0; else o.label = r.querySelector('[data-l]').value;
            return o;
        });
    }

    function editor(p) {
        S.edit = p;
        const s = (p && p.settings) || {};
        const box = document.getElementById('pc-editor');
        box.style.display = 'block';
        const chk = (k) => s[k] !== undefined ? 'checked' : '';
        const tenants = S.tenants.map(t => `<option value="${esc(t.org_id || t.id)}" ${(p && p.tenant_id) === (t.org_id || t.id) ? 'selected' : ''}>${esc(t.name)}</option>`).join('');
        const sel = new Set((p && p.agent_ids) || []);
        box.innerHTML = `<div style="border:1px solid var(--border);border-radius:8px;padding:12px">
            <h4 style="margin:0 0 8px">${p ? 'Editar política' : 'Nova política'}</h4>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px">
                <label style="font-size:.82em">Nome<input id="pe-name" class="form-control" value="${esc(p ? p.name : '')}" placeholder="Ex.: Servidores de arquivos"></label>
                <label style="font-size:.82em">Descrição<input id="pe-desc" class="form-control" value="${esc(p ? p.description : '')}"></label>
                <label style="font-size:.82em">Prioridade (maior vence)<input id="pe-prio" type="number" min="0" max="1000" class="form-control" value="${esc(p ? p.priority : 100)}"></label>
                <label style="font-size:.82em">Tarefas: nome contém (vazio = todas)<input id="pe-filter" class="form-control" value="${esc(p ? p.task_filter : '')}" placeholder="ex.: SQL"></label>
            </div>
            <div style="margin-top:10px;font-size:.85em"><b>Alvo</b>
                <label style="margin-left:10px"><input type="checkbox" id="pe-all" ${p && p.scope_all ? 'checked' : ''}> Todos os agentes</label>
                <label style="margin-left:10px">Cliente <select id="pe-tenant" class="form-control" style="width:auto;display:inline-block"><option value="">—</option>${tenants}</select></label>
                <label style="margin-left:10px"><input type="checkbox" id="pe-enabled" ${!p || p.enabled ? 'checked' : ''}> Política ativa</label>
                <div style="max-height:140px;overflow:auto;border:1px solid var(--border);border-radius:6px;padding:6px;margin-top:6px;display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:2px">
                    ${S.agents.map(a => `<label style="font-size:.8em"><input type="checkbox" data-ag="${esc(a.agent_id)}" ${sel.has(a.agent_id) ? 'checked' : ''}> ${esc(a.hostname || a.agent_id)} <span style="color:var(--text-muted)">${esc(a.tenant_name || '')}</span></label>`).join('')}
                </div></div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin-top:12px">
                <fieldset style="border:1px solid var(--border);border-radius:8px;padding:8px"><legend style="font-size:.85em"><label><input type="checkbox" id="pe-sch-on" ${chk('schedule')}> Agendamento</label></legend>
                    <label style="font-size:.8em">Cron (min hora dia mês dia-semana; 0=Seg)<input id="pe-cron" class="form-control" value="${esc((s.schedule || {}).cron || '0 22 * * *')}"></label>
                    <label style="font-size:.8em"><input type="checkbox" id="pe-sch-en" ${(s.schedule || {}).enabled === false ? '' : 'checked'}> Agendamento ativo</label></fieldset>
                <fieldset style="border:1px solid var(--border);border-radius:8px;padding:8px"><legend style="font-size:.85em"><label><input type="checkbox" id="pe-ret-on" ${chk('retention')}> Retenção</label></legend>
                    ${[['days', 'Diária (dias)'], ['weekly', 'Semanal'], ['monthly', 'Mensal'], ['yearly', 'Anual']].map(([k, l]) => `<label style="font-size:.8em;display:inline-block;width:46%">${l}<input type="number" min="0" data-ret="${k}" class="form-control" value="${esc((s.retention || {})[k] ?? '')}"></label>`).join(' ')}</fieldset>
                <fieldset style="border:1px solid var(--border);border-radius:8px;padding:8px"><legend style="font-size:.85em"><label><input type="checkbox" id="pe-rt-on" ${chk('retry')}> Novas tentativas</label></legend>
                    <label style="font-size:.8em"><input type="checkbox" id="pe-rt-en" ${(s.retry || {}).enabled === false ? '' : 'checked'}> Repetir backups que falharem</label>
                    <label style="font-size:.8em;display:inline-block;width:46%">Tentativas<input type="number" min="0" max="10" id="pe-rt-n" class="form-control" value="${esc((s.retry || {}).max_attempts ?? 3)}"></label>
                    <label style="font-size:.8em;display:inline-block;width:46%">Intervalo (min)<input type="number" min="1" id="pe-rt-d" class="form-control" value="${esc((s.retry || {}).delay_minutes ?? 15)}"></label></fieldset>
                <fieldset style="border:1px solid var(--border);border-radius:8px;padding:8px"><legend style="font-size:.85em"><label><input type="checkbox" id="pe-imm-on" ${chk('immutability')}> Backup imutável</label></legend>
                    <label style="font-size:.8em;display:inline-block;width:46%">Dias de retenção<input type="number" min="1" max="3650" id="pe-imm-d" class="form-control" value="${esc((s.immutability || {}).days ?? 30)}"></label>
                    <label style="font-size:.8em;display:inline-block;width:46%">Bloqueio (nuvem)<select id="pe-imm-m" class="form-control"><option ${(s.immutability || {}).lock_mode === 'GOVERNANCE' ? '' : 'selected'}>COMPLIANCE</option><option ${(s.immutability || {}).lock_mode === 'GOVERNANCE' ? 'selected' : ''}>GOVERNANCE</option></select></label>
                    <label style="font-size:.78em"><input type="checkbox" id="pe-imm-b" ${(s.immutability || {}).apply_bucket ? 'checked' : ''}> Aplicar a retenção padrão no bucket (S3/Wasabi com Object Lock)</label>
                    <div style="font-size:.74em;color:var(--text-muted)">Nuvem: S3 Object Lock. Local (nativo/restic): somente leitura + ACL.</div></fieldset>
            </div>
            <fieldset style="border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:12px"><legend style="font-size:.85em"><label><input type="checkbox" id="pe-mw-on" ${chk('maintenance_windows')}> Janelas de manutenção (backups agendados não iniciam)</label></legend>
                <div id="pe-mw">${(s.maintenance_windows || []).map(w => winRow(w)).join('')}</div><button class="btn btn-sm" type="button" id="pe-mw-add"><i class="fas fa-plus"></i> Janela</button></fieldset>
            <fieldset style="border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:12px"><legend style="font-size:.85em"><label><input type="checkbox" id="pe-bw-on" ${chk('bandwidth')}> Limite de banda de upload</label></legend>
                <label style="font-size:.8em">Padrão (Mbps, 0 = sem limite) <input type="number" min="0" step="any" id="pe-bw-def" class="form-control" style="width:110px;display:inline-block" value="${esc((s.bandwidth || {}).default_mbps ?? 0)}"></label>
                <div id="pe-bw">${((s.bandwidth || {}).rules || []).map(w => winRow(w, true)).join('')}</div><button class="btn btn-sm" type="button" id="pe-bw-add"><i class="fas fa-plus"></i> Regra por horário</button></fieldset>
            <div style="display:flex;gap:8px;margin-top:12px"><button class="btn btn-primary" id="pe-save"><i class="fas fa-save"></i> Salvar</button><button class="btn" id="pe-cancel">Cancelar</button></div></div>`;
        const bindRm = () => box.querySelectorAll('[data-rm]').forEach(b => b.onclick = () => b.closest('.pc-win').remove());
        box.querySelector('#pe-mw-add').onclick = () => { box.querySelector('#pe-mw').insertAdjacentHTML('beforeend', winRow({ days: [0, 1, 2, 3, 4], start: '08:00', end: '18:00' })); box.querySelector('#pe-mw-on').checked = true; bindRm(); };
        box.querySelector('#pe-bw-add').onclick = () => { box.querySelector('#pe-bw').insertAdjacentHTML('beforeend', winRow({ days: [0, 1, 2, 3, 4], start: '08:00', end: '18:00', mbps: 20 }, true)); box.querySelector('#pe-bw-on').checked = true; bindRm(); };
        bindRm();
        box.querySelector('#pe-cancel').onclick = () => { box.style.display = 'none'; box.innerHTML = ''; };
        box.querySelector('#pe-save').onclick = async () => {
            const q = (id) => box.querySelector(id);
            const settings = {};
            if (q('#pe-sch-on').checked) settings.schedule = { cron: q('#pe-cron').value.trim(), enabled: q('#pe-sch-en').checked };
            if (q('#pe-ret-on').checked) { settings.retention = {}; box.querySelectorAll('[data-ret]').forEach(i => { if (i.value !== '') settings.retention[i.dataset.ret] = +i.value; }); }
            if (q('#pe-rt-on').checked) settings.retry = { enabled: q('#pe-rt-en').checked, max_attempts: +q('#pe-rt-n').value, delay_minutes: +q('#pe-rt-d').value };
            if (q('#pe-imm-on').checked) settings.immutability = { days: +q('#pe-imm-d').value, lock_mode: q('#pe-imm-m').value, apply_bucket: q('#pe-imm-b').checked };
            if (q('#pe-mw-on').checked) settings.maintenance_windows = readWins(q('#pe-mw'));
            if (q('#pe-bw-on').checked) settings.bandwidth = { default_mbps: +q('#pe-bw-def').value || 0, rules: readWins(q('#pe-bw'), true) };
            const body = { name: q('#pe-name').value, description: q('#pe-desc').value, priority: +q('#pe-prio').value, task_filter: q('#pe-filter').value,
                scope_all: q('#pe-all').checked, tenant_id: q('#pe-tenant').value || null, enabled: q('#pe-enabled').checked,
                agent_ids: [...box.querySelectorAll('[data-ag]:checked')].map(c => c.dataset.ag), settings };
            try {
                await api('/api/v1/policies' + (p ? '/' + p.id : ''), { method: p ? 'PUT' : 'POST', body: JSON.stringify(body) });
                toast('Política salva — use "Aplicar" para enviar aos agentes', 'success'); box.style.display = 'none'; box.innerHTML = ''; load();
            } catch (e) { toast(e.message, 'error'); }
        };
        box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // ── instalação em massa ──
    async function loadTokens() {
        const box = document.getElementById('it-list');
        try {
            const d = await api('/api/v1/fleet/install-tokens');
            S.publicUrl = d.public_url || location.origin;
            const tk = d.tokens || [];
            box.innerHTML = (tk.length ? `<table class="data-table" style="margin-top:8px"><thead><tr><th>Token</th><th>Cliente</th><th>Validade</th><th>Usos</th><th>Situação</th><th>Criado</th><th></th></tr></thead><tbody>
                ${tk.map(t => `<tr><td><strong>${esc(t.name)}</strong><div style="font-size:.75em;color:var(--text-muted)"><code>${esc(t.token_prefix)}…</code></div></td><td>${esc(t.tenant_name || '—')}</td><td>${dt(t.expires_at)}</td>
                    <td>${t.uses}${t.max_uses ? '/' + t.max_uses : ''}</td><td><span class="badge ${t.state === 'ativo' ? 'badge-success' : 'badge-warning'}">${esc(t.state)}</span></td><td>${dt(t.created_at)}<div style="font-size:.75em;color:var(--text-muted)">${esc(t.created_by)}</div></td>
                    <td>${t.state === 'ativo' ? `<button class="btn btn-sm" data-revoke="${t.id}" style="color:var(--danger)"><i class="fas fa-ban"></i> Revogar</button>` : ''}</td></tr>`).join('')}</tbody></table>` : '<p style="color:var(--text-muted)">Nenhum token criado.</p>')
                + ((d.enrollments || []).length ? `<h4 style="margin:12px 0 4px;font-size:.88em">Inscrições recentes</h4><table class="data-table" style="font-size:.86em"><thead><tr><th>Data</th><th>Máquina</th><th>IP</th><th>Token</th><th>Resultado</th></tr></thead><tbody>
                ${d.enrollments.slice(0, 15).map(e => `<tr><td>${dt(e.created_at)}</td><td>${esc(e.hostname)}</td><td>${esc(e.ip_address)}</td><td>${esc(e.token_name || '')}</td><td>${e.status === 'enrolled' ? '<span class="badge badge-success">inscrito</span>' : `<span class="badge badge-error">recusado</span> <span style="font-size:.85em">${esc(e.message || '')}</span>`}</td></tr>`).join('')}</tbody></table>` : '');
            box.querySelectorAll('[data-revoke]').forEach(b => b.onclick = async () => {
                if (!confirm('Revogar este token? Máquinas ainda não instaladas não conseguirão usá-lo.')) return;
                try { await api(`/api/v1/fleet/install-tokens/${b.dataset.revoke}/revoke`, { method: 'POST' }); loadTokens(); } catch (e) { toast(e.message, 'error'); }
            });
        } catch (e) { box.innerHTML = `<p style="color:var(--danger)">${esc(e.message)}</p>`; }
    }

    function tokenForm() {
        const f = document.getElementById('it-form');
        f.style.display = 'block';
        f.innerHTML = `<div style="border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;align-items:end">
            <label style="font-size:.82em">Nome<input id="itf-name" class="form-control" placeholder="Ex.: Filial Campinas — outubro"></label>
            <label style="font-size:.82em">Cliente dos agentes<select id="itf-tenant" class="form-control"><option value="">— (sem cliente)</option>${S.tenants.map(t => `<option value="${esc(t.org_id || t.id)}">${esc(t.name)}</option>`).join('')}</select></label>
            <label style="font-size:.82em">Validade (dias)<input id="itf-days" type="number" min="1" max="365" value="7" class="form-control"></label>
            <label style="font-size:.82em">Limite de máquinas (0 = sem limite)<input id="itf-uses" type="number" min="0" value="0" class="form-control"></label>
            <label style="font-size:.82em;grid-column:1/-1">URL do Server acessada pelas máquinas<input id="itf-url" class="form-control" value="${esc(S.publicUrl || location.origin)}"></label>
            <label style="font-size:.82em;grid-column:1/-1"><input type="checkbox" id="itf-ss" ${/^https:\/\/(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|[^./]+[:/])/i.test(S.publicUrl || location.origin) ? 'checked' : ''}> O Server usa certificado autoassinado (o comando aceita o certificado sem validar)</label>
            <div><button class="btn btn-primary" id="itf-go"><i class="fas fa-key"></i> Gerar token</button> <button class="btn" id="itf-cancel">Cancelar</button></div></div>`;
        f.querySelector('#itf-cancel').onclick = () => { f.style.display = 'none'; };
        f.querySelector('#itf-go').onclick = async () => {
            const u = f.querySelector('#itf-url').value.trim();
            if (/^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])([:/]|$)/i.test(u) && !confirm('A URL usa "localhost": as outras máquinas não vão alcançar o Server. Gerar mesmo assim? (Use o nome ou IP do Server na rede.)')) return;
            try {
                const d = await api('/api/v1/fleet/install-tokens', { method: 'POST', body: JSON.stringify({ name: f.querySelector('#itf-name').value, tenant_id: f.querySelector('#itf-tenant').value || null,
                    expires_days: +f.querySelector('#itf-days').value, max_uses: +f.querySelector('#itf-uses').value, public_url: u, self_signed: f.querySelector('#itf-ss').checked }) });
                f.style.display = 'none';
                const r = document.getElementById('it-result');
                r.innerHTML = `<div style="border:1px solid var(--success);border-radius:8px;padding:12px;margin-bottom:10px">
                    <b><i class="fas fa-circle-check" style="color:var(--success)"></i> Token criado — copie agora, ele não será mostrado de novo.</b>
                    ${d.warning ? `<div style="margin-top:6px;color:var(--warning);font-size:.84em"><i class="fas fa-triangle-exclamation"></i> ${esc(d.warning)}</div>` : ''}
                    <div style="margin-top:8px;font-size:.82em">Comando único (PowerShell como Administrador, GPO de inicialização ou script do Intune):</div>
                    <textarea readonly class="form-control" style="width:100%;height:58px;font-family:monospace;font-size:.78em">${esc(d.one_liner)}</textarea>
                    <div style="font-size:.82em;margin-top:6px">Instalação manual a partir do pacote do Agent:</div>
                    <textarea readonly class="form-control" style="width:100%;height:40px;font-family:monospace;font-size:.78em">${esc(d.manual)}</textarea>
                    <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap"><button class="btn btn-sm" id="itr-copy"><i class="fas fa-copy"></i> Copiar comando</button>
                        <button class="btn btn-sm" id="itr-dl"><i class="fas fa-file-arrow-down"></i> Baixar script .ps1 (GPO/Intune)</button></div>
                    <div style="font-size:.76em;color:var(--text-muted);margin-top:6px">Intune: Dispositivos &gt; Scripts &gt; PowerShell (executar como sistema, 64 bits). GPO: Configuração do computador &gt; Scripts &gt; Inicialização.</div></div>`;
                r.querySelector('#itr-copy').onclick = () => { navigator.clipboard && navigator.clipboard.writeText(d.one_liner); toast('Comando copiado', 'success'); };
                r.querySelector('#itr-dl').onclick = () => {
                    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob(['﻿' + d.script], { type: 'text/plain' }));
                    a.download = 'Instalar-GBOC-Agent.ps1'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
                };
                loadTokens();
            } catch (e) { toast(e.message, 'error'); }
        };
    }

    window.GBOCPolicies = {
        init() {
            const root = document.getElementById('policies-center');
            if (!root) return;
            if (!root.dataset.ready) { shell(root); root.dataset.ready = '1'; }
            load();
        },
    };
})();
