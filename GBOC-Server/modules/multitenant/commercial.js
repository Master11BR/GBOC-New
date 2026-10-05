/* GBOC Server — Comercial MSP (aba Multi-Tenant): licença, preços por cliente e fechamento mensal.
 * API: /api/v1/license, /api/v1/billing/...
 */
(function () {
    'use strict';
    const base = () => (window.GBOC_API_BASE || '');
    const esc = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const toast = (m, t) => (typeof showToast === 'function' ? showToast(m, t) : alert(m));
    const dt = (v) => v ? new Date(String(v).replace(' ', 'T')).toLocaleString('pt-BR') : '—';
    const money = (v, c) => (+v || 0).toLocaleString('pt-BR', { style: 'currency', currency: c || 'BRL' });
    const gb = (b) => ((+b || 0) / 1073741824).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' GB';
    const S = { period: null, currency: 'BRL' };

    async function api(path, opts) {
        const r = await fetch(base() + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}));
        let d; try { d = await r.json(); } catch (e) { d = {}; }
        if (!r.ok) throw new Error((typeof d.detail === 'string' ? d.detail : '') || d.message || ('HTTP ' + r.status));
        return d;
    }
    function prevMonth() { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1); return d.toISOString().slice(0, 7); }

    function shell(root) {
        root.innerHTML = `
        <div class="panel" style="padding:14px;margin-bottom:16px" id="cm-license"></div>
        <div class="panel" style="padding:14px;margin-bottom:16px">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
                <h3 style="margin:0;font-size:1em"><i class="fas fa-file-invoice-dollar" style="color:var(--primary)"></i> Fechamento mensal de faturamento</h3>
                <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
                    <input type="month" id="cm-period" class="form-control" style="width:auto">
                    <button class="btn btn-sm" id="cm-preview"><i class="fas fa-calculator"></i> Calcular</button>
                    <button class="btn btn-sm btn-primary" id="cm-close"><i class="fas fa-lock"></i> Fechar o mês</button>
                    <button class="btn btn-sm" id="cm-prices"><i class="fas fa-tags"></i> Preços</button>
                </div>
            </div>
            <p style="font-size:.78em;color:var(--text-muted);margin:6px 0">Agentes ativos no mês × preço por agente + pico de armazenamento do mês × preço por TB + mensalidade. Ao fechar, os valores ficam congelados e o demonstrativo aparece no Portal do Cliente.</p>
            <div id="cm-pricing" style="display:none"></div>
            <div id="cm-preview-box"></div>
            <h4 style="margin:14px 0 6px;font-size:.9em">Meses fechados</h4>
            <div id="cm-closings"></div>
        </div>`;
        const per = root.querySelector('#cm-period');
        per.value = S.period || prevMonth();
        root.querySelector('#cm-preview').onclick = () => { S.period = per.value; preview(); };
        root.querySelector('#cm-close').onclick = closeMonth;
        root.querySelector('#cm-prices').onclick = pricing;
        per.onchange = () => { S.period = per.value; preview(); };
    }

    async function license() {
        const box = document.getElementById('cm-license');
        try {
            const d = (await api('/api/v1/license')).license;
            const tone = { valid: 'var(--success)', expiring: 'var(--warning)', grace: 'var(--danger)', expired: 'var(--danger)', invalid: 'var(--danger)', none: 'var(--text-muted)' }[d.state];
            box.innerHTML = `<div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;align-items:center">
                <h3 style="margin:0;font-size:1em"><i class="fas fa-certificate" style="color:var(--primary)"></i> Licença do GBOC</h3>
                <span style="color:${tone};font-weight:600">${esc(d.message)}</span></div>
                <div class="kpi-grid" style="margin-top:10px">
                    <div class="kpi-card"><div class="kpi-header"><span>Agentes em uso</span></div><div class="kpi-value">${esc(d.used_agents)}${d.max_agents ? ' / ' + esc(d.max_agents) : ''}</div><div class="kpi-sub">${d.enforced ? 'limite da licença' : 'sem limite (avaliação)'}</div></div>
                    <div class="kpi-card"><div class="kpi-header"><span>Licenciado para</span></div><div class="kpi-value" style="font-size:1.05em">${esc(d.customer || '—')}</div><div class="kpi-sub">${d.license_id ? 'ID ' + esc(String(d.license_id).slice(0, 8)) : ''}</div></div>
                    <div class="kpi-card"><div class="kpi-header"><span>Validade</span></div><div class="kpi-value" style="font-size:1.05em">${d.expires ? new Date(d.expires + 'T00:00').toLocaleDateString('pt-BR') : '—'}</div><div class="kpi-sub">${d.days_left != null ? d.days_left + ' dia(s)' : ''}</div></div>
                </div>
                <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
                    <input id="cm-lic" class="form-control" style="flex:1;min-width:260px;font-family:monospace;font-size:.8em" placeholder="Cole aqui a licença recebida do fornecedor">
                    <button class="btn btn-sm btn-primary" id="cm-lic-save"><i class="fas fa-check"></i> Instalar licença</button>
                    ${d.state !== 'none' ? '<button class="btn btn-sm" id="cm-lic-del" style="color:var(--danger)"><i class="fas fa-trash"></i> Remover</button>' : ''}
                </div>
                ${d.public_key_installed ? '' : '<p style="font-size:.76em;color:var(--warning);margin:6px 0 0">Chave pública de licença não instalada neste Server (license_public_key.pem) — gere com tools/license_tool.py keygen.</p>'}
                <p style="font-size:.74em;color:var(--text-muted);margin:6px 0 0">Com licença: novos agentes acima do limite são recusados (os existentes continuam). Aviso 30 dias antes do vencimento e 15 dias de carência. Limites por cliente (plano) valem para novos agentes e inscrições.</p>`;
            box.querySelector('#cm-lic-save').onclick = async () => {
                try { await api('/api/v1/license', { method: 'PUT', body: JSON.stringify({ license_key: box.querySelector('#cm-lic').value }) }); toast('Licença instalada', 'success'); license(); }
                catch (e) { toast(e.message, 'error'); }
            };
            const del = box.querySelector('#cm-lic-del');
            if (del) del.onclick = async () => { if (!confirm('Remover a licença? O Server volta ao modo avaliação.')) return; await api('/api/v1/license', { method: 'DELETE' }); license(); };
        } catch (e) { box.innerHTML = `<p style="color:var(--danger)">${esc(e.message)}</p>`; }
    }

    async function preview() {
        const box = document.getElementById('cm-preview-box');
        box.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Calculando...';
        try {
            const d = await api('/api/v1/billing/preview?period=' + encodeURIComponent(S.period));
            S.currency = d.currency;
            box.innerHTML = `<div style="font-size:.85em;margin:6px 0">${d.closed ? '<span class="badge badge-success">mês fechado</span> valores abaixo são o recálculo atual; o fechado está em "Meses fechados".' : d.partial ? '<span class="badge badge-warning">mês em andamento</span> prévia — os valores mudam até o fim do mês.' : '<span class="badge badge-info">aberto</span> pronto para fechar.'}</div>
                <div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Cliente</th><th>Plano</th><th>Agentes</th><th>Armazenamento (pico)</th><th>Execuções</th><th>Mensalidade</th><th>Preço/agente</th><th>Preço/TB</th><th style="text-align:right">Valor</th></tr></thead><tbody>
                ${d.rows.map(r => `<tr><td><strong>${esc(r.tenant_name)}</strong></td><td>${esc(r.plan || '—')}</td>
                    <td>${r.agents}${r.max_agents ? '/' + r.max_agents : ''}${r.over_limit ? ' <span class="badge badge-error">acima do plano</span>' : ''}</td>
                    <td>${gb(r.storage_bytes)}</td><td>${r.executions} <span style="color:var(--text-muted);font-size:.85em">(${r.success} ok)</span></td>
                    <td>${money(r.base_fee, r.currency)}</td><td>${money(r.price_per_agent, r.currency)}</td><td>${money(r.price_per_tb, r.currency)}</td>
                    <td style="text-align:right;font-weight:700">${money(r.amount, r.currency)}</td></tr>`).join('')}
                <tr><td colspan="8" style="text-align:right"><b>Total</b></td><td style="text-align:right;font-weight:800">${money(d.total, d.currency)}</td></tr></tbody></table></div>`;
        } catch (e) { box.innerHTML = `<p style="color:var(--danger)">${esc(e.message)}</p>`; }
    }

    async function closings() {
        const box = document.getElementById('cm-closings');
        try {
            const d = await api('/api/v1/billing/closings');
            const ps = d.periods || [];
            box.innerHTML = !ps.length ? '<p style="color:var(--text-muted)">Nenhum mês fechado.</p>' : `<table class="data-table"><thead><tr><th>Mês</th><th>Clientes</th><th>Total</th><th>Fechado em</th><th></th></tr></thead><tbody>
                ${ps.map(p => `<tr><td><strong>${esc(p.period)}</strong></td><td>${p.tenants}</td><td>${money(p.total, p.currency)}</td><td>${dt(p.closed_at)} · ${esc(p.closed_by)}</td>
                    <td style="white-space:nowrap"><a class="btn btn-sm" href="${base()}/api/v1/billing/closings/${p.period}/export"><i class="fas fa-file-csv"></i> CSV</a>
                    <button class="btn btn-sm" data-reopen="${p.period}" style="color:var(--danger)"><i class="fas fa-lock-open"></i> Reabrir</button></td></tr>`).join('')}</tbody></table>`;
            box.querySelectorAll('[data-reopen]').forEach(b => b.onclick = async () => {
                if (!confirm(`Reabrir ${b.dataset.reopen}? Os valores congelados serão descartados e o mês poderá ser recalculado.`)) return;
                try { await api('/api/v1/billing/close/' + b.dataset.reopen, { method: 'DELETE' }); closings(); preview(); } catch (e) { toast(e.message, 'error'); }
            });
        } catch (e) { box.innerHTML = `<p style="color:var(--danger)">${esc(e.message)}</p>`; }
    }

    async function closeMonth() {
        const ok = window.gbocConfirm ? await gbocConfirm(`Fechar o faturamento de ${S.period}? Os valores ficam congelados e disponíveis no portal de cada cliente.`, { title: 'Fechar mês', type: 'warning' }) : confirm('Fechar?');
        if (!ok) return;
        try { const d = await api('/api/v1/billing/close', { method: 'POST', body: JSON.stringify({ period: S.period }) }); toast(`Mês ${d.period} fechado: ${money(d.total, d.currency)}`, 'success'); closings(); preview(); }
        catch (e) { toast(e.message, 'error'); }
    }

    async function pricing() {
        const box = document.getElementById('cm-pricing');
        if (box.style.display === 'block') { box.style.display = 'none'; return; }
        box.style.display = 'block';
        try {
            const d = await api('/api/v1/billing/pricing');
            const f = (v) => v == null ? '' : v;
            box.innerHTML = `<div style="border:1px solid var(--border);border-radius:8px;padding:12px;margin:8px 0">
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                    <label style="font-size:.82em">Preço padrão por agente<input type="number" step="0.01" min="0" id="pp-agent" class="form-control" value="${d.defaults.price_per_agent}"></label>
                    <label style="font-size:.82em">Preço padrão por TB<input type="number" step="0.01" min="0" id="pp-tb" class="form-control" value="${d.defaults.price_per_tb}"></label>
                    <label style="font-size:.82em">Mensalidade padrão<input type="number" step="0.01" min="0" id="pp-base" class="form-control" value="${d.defaults.base_fee}"></label>
                    <label style="font-size:.82em">Moeda<input id="pp-cur" class="form-control" maxlength="3" value="${esc(d.defaults.currency)}" style="width:80px"></label>
                    <label style="font-size:.82em"><input type="checkbox" id="pp-auto" ${d.auto_close ? 'checked' : ''}> Fechar automaticamente no dia 1</label>
                </div>
                <table class="data-table" style="margin-top:10px;font-size:.88em"><thead><tr><th>Cliente</th><th>Plano</th><th>Preço/agente</th><th>Preço/TB</th><th>Mensalidade</th></tr></thead><tbody>
                ${d.tenants.map(t => `<tr data-org="${esc(t.org_id)}"><td>${esc(t.name)}</td><td>${esc(t.plan || '')}</td>
                    <td><input type="number" step="0.01" min="0" data-k="price_per_agent" class="form-control" placeholder="padrão" value="${f(t.price_per_agent)}"></td>
                    <td><input type="number" step="0.01" min="0" data-k="price_per_tb" class="form-control" placeholder="padrão" value="${f(t.price_per_tb)}"></td>
                    <td><input type="number" step="0.01" min="0" data-k="base_fee" class="form-control" placeholder="padrão" value="${f(t.base_fee)}"></td></tr>`).join('')}</tbody></table>
                <button class="btn btn-sm btn-primary" id="pp-save" style="margin-top:8px"><i class="fas fa-save"></i> Salvar preços</button></div>`;
            box.querySelector('#pp-save').onclick = async () => {
                const tenants = [...box.querySelectorAll('[data-org]')].map(tr => {
                    const o = { org_id: tr.dataset.org }; tr.querySelectorAll('[data-k]').forEach(i => { o[i.dataset.k] = i.value; }); return o;
                });
                try {
                    await api('/api/v1/billing/pricing', { method: 'PUT', body: JSON.stringify({ tenants, auto_close: box.querySelector('#pp-auto').checked,
                        defaults: { price_per_agent: box.querySelector('#pp-agent').value, price_per_tb: box.querySelector('#pp-tb').value, base_fee: box.querySelector('#pp-base').value, currency: box.querySelector('#pp-cur').value.toUpperCase() } }) });
                    toast('Preços salvos', 'success'); preview();
                } catch (e) { toast(e.message, 'error'); }
            };
        } catch (e) { box.innerHTML = `<p style="color:var(--danger)">${esc(e.message)}</p>`; }
    }

    window.GBOCCommercial = {
        init() {
            const root = document.getElementById('msp-commercial');
            if (!root) return;
            if (!root.dataset.ready) { shell(root); root.dataset.ready = '1'; S.period = root.querySelector('#cm-period').value; }
            license(); preview(); closings();
        },
    };
})();
