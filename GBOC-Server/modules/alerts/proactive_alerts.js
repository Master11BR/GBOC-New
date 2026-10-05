/* GBOC Server — Alertas proativos (aba Central de Alertas)
 * Alertas abertos (reconhecer / encerrar), histórico, regras com limites e canais (e-mail, Teams, webhook).
 * API: /api/v1/proactive-alerts/...
 */
(function () {
    'use strict';
    const base = () => (window.GBOC_API_BASE || '');
    const esc = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const toast = (m, t) => (typeof showToast === 'function' ? showToast(m, t) : alert(m));
    const dt = (v) => v ? new Date(String(v).replace(' ', 'T')).toLocaleString('pt-BR') : '—';
    const S = { history: false, config: false, rules: [], settings: {}, timer: null };

    async function api(path, opts) {
        const r = await fetch(base() + '/api/v1/proactive-alerts' + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}));
        let d; try { d = await r.json(); } catch (e) { d = {}; }
        if (!r.ok) throw new Error((typeof d.detail === 'string' ? d.detail : '') || d.message || ('HTTP ' + r.status));
        return d;
    }

    function shell(root) {
        root.innerHTML = `
        <div class="panel" style="padding:14px;margin-bottom:18px">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
                <div>
                    <h3 style="margin:0;font-size:1.05em"><i class="fas fa-bolt" style="color:var(--warning);margin-right:6px"></i> Alertas proativos</h3>
                    <div style="font-size:.78em;color:var(--text-muted);margin-top:2px">Avisam antes do incidente: disco que vai encher, RPO estourado, falhas seguidas, agente sem comunicação e teste de restauração reprovado.</div>
                </div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
                    <span id="pa-counts"></span>
                    <label style="font-size:.82em;display:flex;gap:6px;align-items:center"><input type="checkbox" id="pa-hist"> Histórico (30 dias)</label>
                    <button class="btn btn-sm" id="pa-eval"><i class="fas fa-rotate"></i> Avaliar agora</button>
                    <button class="btn btn-sm" id="pa-cfg"><i class="fas fa-sliders"></i> Regras e canais</button>
                </div>
            </div>
            <div id="pa-config" style="display:none;margin-top:12px"></div>
            <div id="pa-list" style="margin-top:12px"></div>
            <div id="pa-last" style="font-size:.75em;color:var(--text-muted);margin-top:6px"></div>
        </div>`;
        root.querySelector('#pa-hist').onchange = (e) => { S.history = e.target.checked; loadEvents(); };
        root.querySelector('#pa-eval').onclick = evaluateNow;
        root.querySelector('#pa-cfg').onclick = () => { S.config = !S.config; renderConfig(); };
    }

    const sevPill = (e) => e.status === 'resolved' ? '<span class="badge badge-success">Normalizado</span>'
        : e.status === 'acknowledged' ? `<span class="badge badge-info" title="Reconhecido por ${esc(e.acknowledged_by)}">Reconhecido</span>`
        : e.severity === 'critical' ? '<span class="badge badge-error">Crítico</span>' : '<span class="badge badge-warning">Aviso</span>';

    async function loadEvents() {
        const box = document.getElementById('pa-list');
        if (!box) return;
        try {
            const d = await api(`/events?status=${S.history ? 'all' : 'open'}&days=30`);
            const o = d.open || {};
            document.getElementById('pa-counts').innerHTML =
                `${o.critical ? `<span class="badge badge-error" style="margin-right:4px">${o.critical} crítico(s)</span>` : ''}${o.warning ? `<span class="badge badge-warning">${o.warning} aviso(s)</span>` : ''}${!o.critical && !o.warning ? '<span class="badge badge-success"><i class="fas fa-check"></i> Nenhum alerta aberto</span>' : ''}`;
            const le = d.last_evaluation || {};
            document.getElementById('pa-last').textContent = le.evaluated_at ? `Última avaliação: ${dt(le.evaluated_at)} · ${le.conditions} condição(ões) · ${le.new} novo(s), ${le.resolved} normalizado(s)` +
                (le.notifications && Object.keys(le.notifications).length ? ' · Notificações: ' + Object.entries(le.notifications).map(([k, v]) => `${k} ${v}`).join(', ') : '') : 'A avaliação automática roda a cada poucos minutos.';
            const ev = d.events || [];
            if (!ev.length) { box.innerHTML = `<p style="color:var(--text-muted);margin:4px 0">${S.history ? 'Nenhum alerta nos últimos 30 dias.' : 'Tudo certo — nenhum alerta proativo aberto.'}</p>`; return; }
            box.innerHTML = `<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Situação</th><th>Alerta</th><th>Desde</th><th>Visto por último</th><th>Avisos</th><th style="text-align:right">Ações</th></tr></thead><tbody>
                ${ev.map(e => `<tr>
                    <td>${sevPill(e)}</td>
                    <td><strong>${esc(e.title)}</strong><div style="font-size:.8em;color:var(--text-muted);max-width:620px">${esc(e.message)}</div></td>
                    <td style="white-space:nowrap">${dt(e.first_seen)}</td><td style="white-space:nowrap">${e.status === 'resolved' ? 'Normalizado ' + dt(e.resolved_at) : dt(e.last_seen)}</td>
                    <td>${e.notify_count || 0}${e.last_notify_error ? ` <i class="fas fa-triangle-exclamation" style="color:var(--warning)" title="${esc(e.last_notify_error)}"></i>` : ''}</td>
                    <td style="text-align:right;white-space:nowrap">
                        ${e.report_code ? `<button class="btn btn-sm" data-rep="${esc(e.report_code)}" data-agent="${esc(e.agent_id || '')}" title="Abrir relatório de apoio"><i class="fas fa-file-contract"></i> ${esc(e.report_code)}</button>` : ''}
                        ${e.status === 'open' ? `<button class="btn btn-sm" data-ack="${e.id}" title="Para os lembretes até normalizar"><i class="fas fa-check"></i> Reconhecer</button>` : ''}
                        ${e.status !== 'resolved' ? `<button class="btn btn-sm" data-res="${e.id}" title="Encerrar (volta a alertar se a condição persistir)"><i class="fas fa-xmark"></i></button>` : ''}
                    </td></tr>`).join('')}</tbody></table></div>`;
            box.querySelectorAll('[data-ack]').forEach(b => b.onclick = async () => { try { await api(`/events/${b.dataset.ack}/ack`, { method: 'POST' }); toast('Alerta reconhecido', 'success'); loadEvents(); } catch (e) { toast(e.message, 'error'); } });
            box.querySelectorAll('[data-res]').forEach(b => b.onclick = async () => { try { await api(`/events/${b.dataset.res}/resolve`, { method: 'POST' }); toast('Alerta encerrado', 'success'); loadEvents(); } catch (e) { toast(e.message, 'error'); } });
            box.querySelectorAll('[data-rep]').forEach(b => b.onclick = () => {
                if (typeof switchTab === 'function') switchTab('reports');
                setTimeout(() => {
                    const sel = document.getElementById('rc-agent');
                    if (sel && b.dataset.agent && [...sel.options].some(o => o.value === b.dataset.agent)) sel.value = b.dataset.agent;
                    if (window.GBOCReportCenter) GBOCReportCenter.open('real', b.dataset.rep);
                }, 500);
            });
        } catch (e) { box.innerHTML = `<p style="color:var(--danger)">Erro ao carregar alertas proativos: ${esc(e.message)}</p>`; }
    }

    async function evaluateNow() {
        const b = document.getElementById('pa-eval'); b.disabled = true; b.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Avaliando...';
        try {
            const d = await api('/evaluate', { method: 'POST' });
            if (d.status === 'busy') toast('Já existe uma avaliação em andamento', 'info');
            else toast(`Avaliação concluída: ${d.new} novo(s), ${d.resolved} normalizado(s)`, 'success');
            loadEvents();
        } catch (e) { toast('Falha: ' + e.message, 'error'); }
        finally { b.disabled = false; b.innerHTML = '<i class="fas fa-rotate"></i> Avaliar agora'; }
    }

    async function renderConfig() {
        const box = document.getElementById('pa-config');
        if (!S.config) { box.style.display = 'none'; return; }
        box.style.display = 'block';
        box.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Carregando...';
        try {
            const [r, st] = await Promise.all([api('/rules'), api('/settings')]);
            S.rules = r.rules || []; S.settings = st.settings || {};
            const def = (st.default_recipients || []).join(', ');
            box.innerHTML = `
            <div style="border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:12px">
                <h4 style="margin:0 0 8px;font-size:.92em"><i class="fas fa-paper-plane" style="color:var(--primary)"></i> Canais de notificação</h4>
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;align-items:end">
                    <label style="font-size:.82em">E-mails dos alertas (vírgula)<input id="pa-rcpt" class="form-control" value="${esc(S.settings.recipients || '')}" placeholder="${esc(def || 'ex.: noc@empresa.com.br')}${def ? ' (padrão)' : ''}"></label>
                    <label style="font-size:.82em">Webhook do Microsoft Teams<input id="pa-teams" class="form-control" value="${esc(S.settings.teams_webhook_url || '')}" placeholder="https://… (Workflows → “Postar em um canal quando uma solicitação de webhook for recebida”)"></label>
                    <label style="font-size:.82em">Avaliar a cada (min)<input id="pa-int" type="number" min="1" max="240" class="form-control" value="${esc(S.settings.interval_minutes || 5)}"></label>
                    <label style="font-size:.82em;display:flex;gap:6px;align-items:center"><input type="checkbox" id="pa-en" ${String(S.settings.enabled) !== 'false' ? 'checked' : ''}> Enviar notificações</label>
                </div>
                <div style="font-size:.76em;color:var(--text-muted);margin-top:6px">E-mail usa o SMTP de Configurações &gt; Notificações. O webhook genérico (Slack, etc.) também vem de lá.</div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
                    <button class="btn btn-sm btn-primary" id="pa-save-ch"><i class="fas fa-save"></i> Salvar canais</button>
                    <button class="btn btn-sm" data-test="email"><i class="fas fa-envelope"></i> Testar e-mail</button>
                    <button class="btn btn-sm" data-test="teams"><i class="fas fa-users"></i> Testar Teams</button>
                    <button class="btn btn-sm" data-test="webhook"><i class="fas fa-link"></i> Testar webhook</button>
                </div>
            </div>
            <div style="border:1px solid var(--border);border-radius:8px;padding:12px">
                <h4 style="margin:0 0 8px;font-size:.92em"><i class="fas fa-list-check" style="color:var(--primary)"></i> Regras</h4>
                <div style="overflow-x:auto"><table class="data-table" style="font-size:.9em"><thead><tr><th>Ativa</th><th>Regra</th><th>Limite (N)</th><th>Severidade</th><th>E-mail</th><th>Teams</th><th>Webhook</th><th>Repetir a cada</th><th>Avisar normalização</th></tr></thead><tbody>
                ${S.rules.map(r => `<tr data-rule="${esc(r.rule_type)}">
                    <td><input type="checkbox" data-f="enabled" ${r.enabled ? 'checked' : ''}></td>
                    <td>${esc(r.label)}<div style="font-size:.78em;color:var(--text-muted)">Relatório de apoio: ${esc(r.report)}</div></td>
                    <td>${r.has_threshold ? `<input type="number" step="any" min="0" data-f="threshold" value="${esc(r.threshold)}" class="form-control" style="width:90px;display:inline-block"> <span style="font-size:.8em">${esc(r.unit)}</span>` : '—'}</td>
                    <td><select data-f="severity" class="form-control" style="width:auto"><option value="critical" ${r.severity === 'critical' ? 'selected' : ''}>Crítico</option><option value="warning" ${r.severity === 'warning' ? 'selected' : ''}>Aviso</option></select></td>
                    <td><input type="checkbox" data-f="notify_email" ${r.notify_email ? 'checked' : ''}></td>
                    <td><input type="checkbox" data-f="notify_teams" ${r.notify_teams ? 'checked' : ''}></td>
                    <td><input type="checkbox" data-f="notify_webhook" ${r.notify_webhook ? 'checked' : ''}></td>
                    <td><input type="number" min="0" max="720" data-f="repeat_hours" value="${esc(r.repeat_hours)}" class="form-control" style="width:80px;display:inline-block"> <span style="font-size:.8em">h</span></td>
                    <td><input type="checkbox" data-f="notify_resolved" ${r.notify_resolved ? 'checked' : ''}></td></tr>`).join('')}
                </tbody></table></div>
                <div style="font-size:.76em;color:var(--text-muted);margin-top:6px">"Repetir a cada" = lembrete enquanto o alerta estiver aberto e não reconhecido (0 = só avisa uma vez).</div>
                <button class="btn btn-sm btn-primary" id="pa-save-rules" style="margin-top:8px"><i class="fas fa-save"></i> Salvar regras</button>
            </div>`;
            box.querySelector('#pa-save-ch').onclick = async () => {
                try {
                    await api('/settings', { method: 'PUT', body: JSON.stringify({ recipients: box.querySelector('#pa-rcpt').value, teams_webhook_url: box.querySelector('#pa-teams').value,
                        interval_minutes: +box.querySelector('#pa-int').value || 5, enabled: box.querySelector('#pa-en').checked }) });
                    toast('Canais salvos', 'success'); renderConfig();
                } catch (e) { toast(e.message, 'error'); }
            };
            box.querySelectorAll('[data-test]').forEach(b => b.onclick = async () => {
                b.disabled = true;
                try { await api('/test', { method: 'POST', body: JSON.stringify({ channel: b.dataset.test }) }); toast('Mensagem de teste enviada', 'success'); }
                catch (e) { toast(e.message, 'error'); } finally { b.disabled = false; }
            });
            box.querySelector('#pa-save-rules').onclick = async () => {
                const rules = [...box.querySelectorAll('[data-rule]')].map(tr => {
                    const o = { rule_type: tr.dataset.rule };
                    tr.querySelectorAll('[data-f]').forEach(i => { o[i.dataset.f] = i.type === 'checkbox' ? i.checked : i.value; });
                    return o;
                });
                try { await api('/rules', { method: 'PUT', body: JSON.stringify({ rules }) }); toast('Regras salvas', 'success'); }
                catch (e) { toast(e.message, 'error'); }
            };
        } catch (e) { box.innerHTML = `<p style="color:var(--danger)">${esc(e.message)}</p>`; }
    }

    window.GBOCProactive = {
        init() {
            const root = document.getElementById('proactive-alerts');
            if (!root) return;
            if (!root.dataset.ready) { shell(root); root.dataset.ready = '1'; }
            loadEvents();
            clearInterval(S.timer);
            S.timer = setInterval(() => {
                const tab = document.getElementById('tab-alerts');
                if (tab && tab.classList.contains('active')) loadEvents(); else clearInterval(S.timer);
            }, 60000);
        },
    };
})();
