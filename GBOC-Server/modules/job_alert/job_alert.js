/**
 * GBOC Server — Central de Jobs com Falha (agentes + o próprio servidor).
 * Dados reais de /api/v1/server/jobs/failed (antes: lista em memória que ficava sempre vazia).
 */
(function () {
    'use strict';
    const API = () => (window.GBOC_API_BASE || '') + '/api/v1';
    const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const dt = (v) => v ? new Date(String(v).replace(' ', 'T')).toLocaleString('pt-BR') : '—';
    const val = (id) => (document.getElementById(id) || {}).value || '';
    let DATA = { failures: [], kpis: {} };
    let filtersLoaded = false;

    function toast(msg, type) {
        if (typeof window.showToast === 'function') window.showToast(msg, type); else alert(msg);
    }

    async function loadFilters() {
        if (filtersLoaded) return;
        filtersLoaded = true;
        try {
            const r = await fetch(API() + '/agents');
            const d = await r.json();
            const agents = Array.isArray(d) ? d : (d.agents || []);
            const sel = document.getElementById('jf-agent');
            agents.forEach((a) => sel.insertAdjacentHTML('beforeend', `<option value="${esc(a.agent_id)}">${esc(a.hostname || a.agent_id)}</option>`));
        } catch (e) { /* filtro opcional */ }
        try {
            const r = await fetch(API() + '/tenant/organizations');
            if (r.ok) {
                const d = await r.json();
                const orgs = d.organizations || d.tenants || (Array.isArray(d) ? d : []);
                const sel = document.getElementById('jf-tenant');
                if (orgs.length && sel) {
                    orgs.forEach((o) => sel.insertAdjacentHTML('beforeend', `<option value="${esc(o.org_id || o.tenant_id || o.id)}">${esc(o.name || o.org_id)}</option>`));
                    sel.style.display = '';
                }
            }
        } catch (e) { /* sem multi-tenant */ }
    }

    function query() {
        const q = new URLSearchParams({ days: val('jf-days') || '30' });
        if (val('jf-agent')) q.set('agent_id', val('jf-agent'));
        if (val('jf-tenant')) q.set('tenant_id', val('jf-tenant'));
        if (val('jf-origin')) q.set('origin', val('jf-origin'));
        return q;
    }

    async function loadServerJobAlertData() {
        const tbody = document.getElementById('table-server-job-failures');
        if (!tbody) return;
        await loadFilters();
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted)"><i class="fas fa-spinner fa-spin"></i> Carregando falhas...</td></tr>';
        try {
            const res = await fetch(API() + '/server/jobs/failed?' + query());
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.status !== 'success') throw new Error(data.detail || data.message || ('HTTP ' + res.status));
            DATA = data;
            const k = data.kpis || {};
            const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
            set('srv-job-failed-count', k.active ?? 0);
            set('srv-job-failed-split', `${k.active_agent || 0} de agentes · ${k.active_server || 0} do servidor`);
            set('srv-job-agents', k.agents_affected ?? 0);
            set('srv-job-escalated-count', k.escalations ?? 0);
            set('srv-job-resolved-rate', k.recovery_rate == null ? '—' : String(k.recovery_rate).replace('.', ',') + '%');
            renderServerJobFailures();
            const h = document.querySelector('#tab-job-alert details');
            if (h && h.open) loadServerJobHistory();
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--danger)"><i class="fas fa-triangle-exclamation"></i> Não foi possível carregar as falhas: ${esc(e.message)}</td></tr>`;
        }
    }

    function statusBadge(f) {
        if (f.status === 'active') return '<span class="badge badge-error">ATIVA</span>';
        if (f.status === 'acknowledged') return `<span class="badge badge-warning" title="${esc((f.acknowledged || {}).by || '')} ${esc(dt((f.acknowledged || {}).at))}">RECONHECIDA</span>`;
        return `<span class="badge badge-success" title="${esc(dt(f.recovered_at))}">RECUPERADA</span>`;
    }

    function renderServerJobFailures() {
        const tbody = document.getElementById('table-server-job-failures');
        if (!tbody) return;
        const onlyActive = val('jf-status') === 'active';
        const rows = (DATA.failures || []).filter((f) => !onlyActive || f.status === 'active');
        if (!rows.length) {
            const total = (DATA.failures || []).length;
            tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-muted)"><i class="fas fa-check-circle" style="color:var(--success)"></i> Nenhuma falha ativa no filtro selecionado${total ? ` — ${total} falha(s) já recuperada(s) ou reconhecida(s) no período (mude o filtro de status para ver)` : ''}.</td></tr>`;
            return;
        }
        tbody.innerHTML = rows.map((f, i) => {
            const cnt = f.consecutive ? `${f.consecutive} seguida(s)` : '';
            const retry = f.max_retries ? `<div style="font-size:.78em;color:var(--text-muted)">tentativas ${f.retry_count || 0}/${f.max_retries}${f.escalated ? ' · escalada' : ''}</div>` : '';
            const actions = f.status === 'active'
                ? `<button class="btn btn-success" style="padding:4px 10px;font-size:.8em" data-ack="${i}" title="Some das ativas até acontecer uma falha mais nova"><i class="fas fa-check"></i> Reconhecer</button>`
                : (f.status === 'acknowledged' ? `<button class="btn btn-secondary" style="padding:4px 10px;font-size:.8em" data-unack="${i}"><i class="fas fa-undo"></i> Reabrir</button>` : '');
            return `<tr>
                <td>${statusBadge(f)}</td>
                <td style="font-size:.85em">${esc(f.kind_label)}</td>
                <td><strong>${esc(f.title)}</strong>${f.subtitle ? `<div style="font-size:.78em;color:var(--text-muted)">${esc(f.subtitle)}</div>` : ''}${f.schedule_paused ? '<div style="font-size:.78em;color:var(--warning)">agendamento pausado</div>' : ''}</td>
                <td><i class="fas ${f.origin === 'server' ? 'fa-shield-halved' : 'fa-server'}"></i> ${esc(f.hostname)}</td>
                <td style="color:var(--danger);max-width:420px;font-size:.86em;white-space:normal">${esc(f.reason || '—')}</td>
                <td style="white-space:nowrap">${esc(f.failures ?? '')}${cnt ? `<div style="font-size:.78em;color:var(--text-muted)">${cnt}</div>` : ''}${retry}</td>
                <td style="font-size:.82em;white-space:nowrap">${dt(f.last_failed_at)}${f.first_failed_at && f.first_failed_at !== f.last_failed_at ? `<div style="color:var(--text-muted)">desde ${dt(f.first_failed_at)}</div>` : ''}</td>
                <td>${actions}</td></tr>`;
        }).join('');
        tbody.querySelectorAll('[data-ack]').forEach((b) => b.onclick = () => ack(rows[+b.dataset.ack].key, true));
        tbody.querySelectorAll('[data-unack]').forEach((b) => b.onclick = () => ack(rows[+b.dataset.unack].key, false));
    }

    async function ack(key, on) {
        try {
            const res = await fetch(API() + `/server/jobs/${on ? 'resolve' : 'unresolve'}/${encodeURIComponent(key)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
            const d = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(d.detail || d.message || ('HTTP ' + res.status));
            loadServerJobAlertData();
        } catch (e) { toast('Falha: ' + e.message, 'error'); }
    }

    async function loadServerJobHistory() {
        const tb = document.getElementById('table-server-job-history');
        if (!tb) return;
        const q = query(); q.delete('origin');
        if (q.get('agent_id') === '__server__') { tb.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">O histórico mostra execuções dos agentes.</td></tr>'; return; }
        try {
            const res = await fetch(API() + '/server/jobs/history?' + q);
            const d = await res.json();
            const rows = d.executions || [];
            tb.innerHTML = rows.length ? rows.map((r) => `<tr><td style="white-space:nowrap;font-size:.84em">${dt(r.at)}</td><td style="font-size:.84em">${esc(r.kind_label)}</td>
                <td>${esc(r.hostname)}</td><td>${esc(r.title)}</td><td style="color:var(--danger);font-size:.84em">${esc(r.reason || '—')}</td></tr>`).join('')
                : '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">Nenhuma execução com falha no período.</td></tr>';
        } catch (e) { tb.innerHTML = `<tr><td colspan="5" style="color:var(--danger)">${esc(e.message)}</td></tr>`; }
    }

    async function testServerAlertChannel() {
        try {
            const res = await fetch(API() + '/server/jobs/test-alert', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
            const d = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(d.detail || d.message || ('HTTP ' + res.status));
            toast(d.message || 'Alerta de teste enviado.', 'success');
        } catch (e) {
            toast('Teste de alerta falhou: ' + e.message + ' — configure os canais em Alertas e Falhas > Regras e canais.', 'error');
        }
    }

    window.loadServerJobAlertData = loadServerJobAlertData;
    window.renderServerJobFailures = renderServerJobFailures;
    window.loadServerJobHistory = loadServerJobHistory;
    window.resolveServerJobFailure = (key) => ack(key, true);
    window.testServerAlertChannel = testServerAlertChannel;
})();
