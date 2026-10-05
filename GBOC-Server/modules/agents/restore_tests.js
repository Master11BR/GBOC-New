/* GBOC Server — Testes de restauração (aba "Restaurar e Validar")
 * Agenda e executa testes reais de restauração nos agentes e mostra a evidência (arquivos conferidos por SHA-256).
 * API: /api/v1/restore-tests/...
 */
(function () {
    'use strict';
    const base = () => (window.GBOC_API_BASE || '');
    const esc = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const toast = (m, t) => (typeof showToast === 'function' ? showToast(m, t) : alert(m));
    const dt = (v) => v ? new Date(String(v).replace(' ', 'T')).toLocaleString('pt-BR') : '—';
    const WD = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];
    const LABEL = { passed: ['Aprovado', 'badge-success'], partial: ['Parcial', 'badge-warning'], failed: ['Reprovado', 'badge-error'], running: ['Em execução', 'badge-info'], error: ['Não executado', 'badge-error'] };
    const S = { agents: [], days: 30, agent: '', timer: null };

    function bytes(b) {
        if (b == null || isNaN(b)) return '—';
        const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0, n = +b;
        while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
        return n.toLocaleString('pt-BR', { maximumFractionDigits: n < 100 ? 1 : 0 }) + ' ' + u[i];
    }
    const dur = (s) => { if (s == null) return '—'; s = Math.round(+s); if (s < 60) return s + 's'; const m = Math.floor(s / 60); return m < 60 ? `${m}min ${s % 60}s` : `${Math.floor(m / 60)}h ${m % 60}min`; };
    const pill = (st) => { const [t, c] = LABEL[String(st || '').toLowerCase()] || [st || '—', 'badge-info']; return `<span class="badge ${c}">${esc(t)}</span>`; };

    async function api(path, opts) {
        const r = await fetch(base() + '/api/v1/restore-tests' + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}));
        let d; try { d = await r.json(); } catch (e) { d = {}; }
        if (!r.ok) throw new Error((typeof d.detail === 'string' ? d.detail : '') || d.message || ('HTTP ' + r.status));
        return d;
    }

    function shell(root) {
        root.innerHTML = `
        <div class="panel" style="padding:14px;margin-bottom:18px">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
                <div>
                    <h3 style="margin:0;font-size:1.05em"><i class="fas fa-vial-circle-check" style="color:var(--success);margin-right:6px"></i> Testes de restauração</h3>
                    <div style="font-size:.78em;color:var(--text-muted);margin-top:2px">O agente restaura de verdade uma amostra do snapshot mais recente, confere tamanho e SHA-256 de cada arquivo e guarda a evidência (usada nos relatórios REP-09 e REP-10).</div>
                </div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
                    <select id="rt-agent" class="form-control" style="width:auto;min-width:220px"><option value="">Todos os agentes</option></select>
                    <select id="rt-days" class="form-control" style="width:auto"><option value="7">7 dias</option><option value="30" selected>30 dias</option><option value="90">90 dias</option><option value="365">12 meses</option></select>
                    <button class="btn btn-sm btn-primary" id="rt-run"><i class="fas fa-play"></i> Testar agora</button>
                    <button class="btn btn-sm" id="rt-new"><i class="fas fa-calendar-plus"></i> Agendar</button>
                </div>
            </div>
            <div id="rt-form" style="display:none;margin-top:12px"></div>
            <div id="rt-kpis" class="kpi-grid" style="margin-top:12px"></div>
            <h4 style="margin:14px 0 6px;font-size:.92em"><i class="fas fa-clock-rotate-left"></i> Agendamentos</h4>
            <div id="rt-scheds" style="font-size:.9em"></div>
            <h4 style="margin:14px 0 6px;font-size:.92em"><i class="fas fa-list"></i> Resultados</h4>
            <div id="rt-running" style="font-size:.85em;color:var(--text-muted)"></div>
            <div id="rt-results"></div>
        </div>`;
        root.querySelector('#rt-agent').onchange = (e) => { S.agent = e.target.value; loadResults(); };
        root.querySelector('#rt-days').onchange = (e) => { S.days = +e.target.value; loadResults(); };
        root.querySelector('#rt-run').onclick = runNow;
        root.querySelector('#rt-new').onclick = () => form();
    }

    async function loadAgents() {
        try {
            const d = await fetch(base() + '/api/v1/fleet/agents').then(r => r.json());
            S.agents = d.agents || [];
            const sel = document.getElementById('rt-agent');
            sel.innerHTML = '<option value="">Todos os agentes</option>' + S.agents.map(a =>
                `<option value="${esc(a.agent_id)}">${esc(a.hostname || a.agent_id)}${a.online ? '' : ' (offline)'}</option>`).join('');
            sel.value = S.agent;
        } catch (e) { /* lista opcional */ }
    }

    async function loadSchedules() {
        const box = document.getElementById('rt-scheds');
        try {
            const d = await api('/schedules');
            const list = d.schedules || [];
            if (!list.length) { box.innerHTML = '<p style="color:var(--text-muted);margin:2px 0">Nenhum teste agendado. Recomendado: semanal ou mensal para cada servidor.</p>'; return; }
            box.innerHTML = `<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Nome</th><th>Agente</th><th>Repositório</th><th>Quando</th><th>Amostra</th><th>Último</th><th>Próximo</th><th></th></tr></thead><tbody>
                ${list.map(s => `<tr><td><strong>${esc(s.name)}</strong>${s.enabled ? '' : ' <span class="badge badge-warning">pausado</span>'}</td>
                    <td>${esc(s.hostname || s.agent_id)}</td><td>${s.repository_id ? 'ID ' + esc(s.repository_id) : 'Todos'}</td><td>${esc(s.description)}</td>
                    <td>${esc(s.sample_size)} arq. ≤ ${esc(s.max_file_mb)} MB</td>
                    <td>${s.last_run_at ? dt(s.last_run_at) + ' ' + pill(s.last_status) : '—'}${s.last_error ? `<div style="font-size:.78em;color:var(--danger);max-width:260px">${esc(String(s.last_error).slice(0, 140))}</div>` : ''}</td>
                    <td>${s.next_run_at ? dt(s.next_run_at) : '—'}</td>
                    <td style="white-space:nowrap"><button class="btn btn-sm" title="Executar agora" data-srun="${s.id}"><i class="fas fa-play"></i></button>
                        <button class="btn btn-sm" title="${s.enabled ? 'Pausar' : 'Retomar'}" data-stog="${s.id}"><i class="fas fa-${s.enabled ? 'pause' : 'play-circle'}"></i></button>
                        <button class="btn btn-sm" title="Excluir" data-sdel="${s.id}" style="color:var(--danger)"><i class="fas fa-trash"></i></button></td></tr>`).join('')}</tbody></table></div>`;
            box.querySelectorAll('[data-srun]').forEach(b => b.onclick = async () => {
                try { const d2 = await api(`/schedules/${b.dataset.srun}/run`, { method: 'POST' }); toast(d2.message, 'success'); poll(); }
                catch (e) { toast(e.message, 'error'); }
            });
            box.querySelectorAll('[data-stog]').forEach(b => b.onclick = async () => {
                const s = list.find(x => String(x.id) === b.dataset.stog);
                try { await api(`/schedules/${s.id}`, { method: 'PUT', body: JSON.stringify({ ...s, enabled: !s.enabled }) }); loadSchedules(); }
                catch (e) { toast(e.message, 'error'); }
            });
            box.querySelectorAll('[data-sdel]').forEach(b => b.onclick = async () => {
                if (!confirm('Excluir este agendamento de teste?')) return;
                try { await api(`/schedules/${b.dataset.sdel}`, { method: 'DELETE' }); loadSchedules(); } catch (e) { toast(e.message, 'error'); }
            });
        } catch (e) { box.innerHTML = `<p style="color:var(--danger)">${esc(e.message)}</p>`; }
    }

    async function loadResults() {
        const box = document.getElementById('rt-results');
        try {
            const q = new URLSearchParams({ days: S.days });
            if (S.agent) q.set('agent_id', S.agent);
            const d = await api('?' + q);
            const tests = d.tests || [];
            const running = d.running || [];
            const host = (id) => (S.agents.find(a => a.agent_id === id) || {}).hostname || id;
            const lr = Object.entries(d.last_runs || {}).flatMap(([aid, v]) => (v.results || []).filter(r => r.comm).map(r => ({ aid, at: v.at, ...r })));
            document.getElementById('rt-running').innerHTML = (running.length ? `<i class="fas fa-spinner fa-spin"></i> Em execução: ${running.map(a => esc(host(a))).join(', ')}` : '') +
                (lr.length ? `<div style="color:var(--danger);margin-top:4px">${lr.slice(0, 5).map(r => `<i class="fas fa-triangle-exclamation"></i> ${esc(host(r.aid))} (${dt(r.at)}): ${esc(r.message)}`).join('<br>')}</div>` : '');
            const passed = tests.filter(t => t.status === 'passed').length;
            const failed = tests.filter(t => ['failed', 'partial', 'error'].includes(t.status)).length;
            const lastByRepo = {};
            tests.forEach(t => { const k = t.agent_id + '|' + t.repository_id; if (!lastByRepo[k]) lastByRepo[k] = t; });
            const repos = Object.values(lastByRepo);
            const durs = tests.filter(t => t.status === 'passed' && t.duration_seconds != null).map(t => +t.duration_seconds);
            document.getElementById('rt-kpis').innerHTML = [
                ['Testes no período', tests.length, `${passed} aprovado(s)`, 'blue', 'fa-vial'],
                ['Com problema', failed, failed ? 'investigar' : 'nenhum', failed ? 'red' : 'green', 'fa-triangle-exclamation'],
                ['Repositórios testados', repos.length, `${repos.filter(t => t.status === 'passed').length} com último teste aprovado`, 'green', 'fa-database'],
                ['Duração média', durs.length ? dur(durs.reduce((a, b) => a + b, 0) / durs.length) : '—', 'restaurar + conferir', 'orange', 'fa-stopwatch'],
            ].map(([l, v, s, c, i]) => `<div class="kpi-card"><div class="kpi-header"><span>${l}</span><div class="kpi-icon ${c}"><i class="fas ${i}"></i></div></div><div class="kpi-value">${esc(v)}</div><div class="kpi-sub">${esc(s)}</div></div>`).join('');
            if (!tests.length) { box.innerHTML = '<p style="color:var(--text-muted)">Nenhum teste no período. Use "Testar agora" ou agende testes periódicos.</p>'; return; }
            box.innerHTML = `<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Data</th><th>Agente</th><th>Repositório</th><th>Snapshot</th><th>Resultado</th><th>Conferidos</th><th>Por hash</th><th>Volume</th><th>Duração</th><th>Origem</th><th></th></tr></thead><tbody>
                ${tests.map(t => `<tr><td style="white-space:nowrap">${dt(t.started_at)}</td><td>${esc(t.hostname || t.agent_id)}</td><td>${esc(t.repository_name || t.repository_id)}<div style="font-size:.75em;color:var(--text-muted)">${esc(t.engine || '')}</div></td>
                    <td style="font-size:.85em">${esc(t.snapshot_id || '—')}${t.snapshot_time ? `<div style="color:var(--text-muted)">${dt(t.snapshot_time)}</div>` : ''}</td>
                    <td>${pill(t.status)}${t.error_message ? `<div style="font-size:.76em;color:var(--danger);max-width:260px">${esc(String(t.error_message).slice(0, 160))}</div>` : ''}</td>
                    <td>${t.files_tested != null ? `${esc(t.files_ok)}/${esc(t.files_tested)}` : '—'}</td><td>${esc(t.files_hash_verified ?? '—')}</td><td>${bytes(t.bytes_restored)}</td><td>${dur(t.duration_seconds)}</td>
                    <td style="font-size:.8em">${String(t.triggered_by || '').startsWith('server:schedule') ? 'Agendado' : String(t.triggered_by || '').startsWith('server:batch') ? 'Lote' : 'Manual'}</td>
                    <td><button class="btn btn-sm" data-ev="${esc(t.agent_id)}|${esc(t.ext_id)}" title="Evidência"><i class="fas fa-file-shield"></i></button></td></tr>`).join('')}</tbody></table></div>`;
            box.querySelectorAll('[data-ev]').forEach(b => b.onclick = () => { const [a, id] = b.dataset.ev.split('|'); evidence(a, id); });
        } catch (e) { box.innerHTML = `<p style="color:var(--danger)">${esc(e.message)}</p>`; }
    }

    async function evidence(agent, id) {
        try {
            const d = await api(`/${encodeURIComponent(agent)}/${encodeURIComponent(id)}`);
            const t = d.test; const det = Array.isArray(t.details) ? t.details : [];
            const html = `<div style="font-size:.88em">
                <p><b>${esc(t.hostname || t.agent_id)}</b> · ${esc(t.repository_name)}${t.snapshot_id ? ' · snapshot ' + esc(t.snapshot_id) : ''} ${t.snapshot_time ? '(' + dt(t.snapshot_time) + ')' : ''}</p>
                <p>${pill(t.status)} ${esc(t.files_ok)}/${esc(t.files_tested)} arquivos conferidos · ${esc(t.files_hash_verified)} por SHA-256 · ${bytes(t.bytes_restored)} em ${dur(t.duration_seconds)}</p>
                ${t.error_message ? `<p style="color:var(--danger)">${esc(t.error_message)}</p>` : ''}
                <table class="data-table" style="font-size:.9em"><thead><tr><th>Arquivo</th><th>Tamanho</th><th>Conferência</th><th>SHA-256</th></tr></thead><tbody>
                ${det.map(x => `<tr><td style="overflow-wrap:anywhere;max-width:340px">${esc(x.path)}</td><td>${bytes(x.restored_size ?? x.expected_size)}</td>
                    <td><span style="color:${x.ok ? 'var(--success)' : 'var(--danger)'}"><i class="fas fa-${x.ok ? 'check' : 'xmark'}"></i></span> ${esc(x.note || x.check)}</td>
                    <td style="font-family:monospace;font-size:.78em;overflow-wrap:anywhere;max-width:260px">${esc(x.sha256 || '—')}</td></tr>`).join('') || '<tr><td colspan="4">Sem arquivos (o teste falhou antes da restauração).</td></tr>'}
                </tbody></table>
                <p style="font-size:.78em;color:var(--text-muted)">Hash da evidência: <code>${esc(t.evidence_hash || '—')}</code></p></div>`;
            if (typeof window.gbocAlert === 'function') gbocAlert({ title: 'Evidência do teste de restauração', message: html, allowHtml: true, size: 'xl', type: 'info', badge: 'GBOC Evidência' });
            else {
                const w = window.open('', '_blank');
                w.document.write(`<!DOCTYPE html><meta charset="utf-8"><title>Evidência</title><body style="font-family:Segoe UI,Arial;padding:16px">${html}</body>`);
            }
        } catch (e) { toast(e.message, 'error'); }
    }

    async function runNow() {
        if (!S.agent) { toast('Selecione um agente no filtro para testar agora (ou agende para vários).', 'warning'); return; }
        try { const d = await api('/run', { method: 'POST', body: JSON.stringify({ agent_id: S.agent }) }); toast(d.message, 'success'); poll(); }
        catch (e) { toast(e.message, 'error'); }
    }

    function poll() {
        clearInterval(S.timer);
        let n = 0;
        loadResults();
        S.timer = setInterval(() => { n++; loadResults(); loadSchedules(); if (n > 40) clearInterval(S.timer); }, 5000);
    }

    function form() {
        const f = document.getElementById('rt-form');
        f.style.display = 'block';
        f.innerHTML = `<div style="border:1px solid var(--border);border-radius:8px;padding:12px">
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;align-items:end">
                <label style="font-size:.82em">Agente<select id="rf-agent" class="form-control">${S.agents.map(a => `<option value="${esc(a.agent_id)}" ${a.agent_id === S.agent ? 'selected' : ''}>${esc(a.hostname || a.agent_id)}</option>`).join('')}</select></label>
                <label style="font-size:.82em">Repositório (ID, vazio = todos)<input id="rf-repo" class="form-control" placeholder="todos"></label>
                <label style="font-size:.82em">Frequência<select id="rf-freq" class="form-control"><option value="daily">Diário</option><option value="weekly" selected>Semanal</option><option value="monthly">Mensal</option></select></label>
                <label style="font-size:.82em" id="rf-wd-l">Dia da semana<select id="rf-wd" class="form-control">${WD.map((w, i) => `<option value="${i}" ${i === 6 ? 'selected' : ''}>${w}</option>`).join('')}</select></label>
                <label style="font-size:.82em;display:none" id="rf-dom-l">Dia do mês<input id="rf-dom" type="number" min="1" max="28" value="1" class="form-control"></label>
                <label style="font-size:.82em">Horário<input id="rf-time" type="time" value="02:00" class="form-control"></label>
                <label style="font-size:.82em">Arquivos na amostra<input id="rf-sample" type="number" min="1" max="50" value="5" class="form-control"></label>
                <label style="font-size:.82em">Tamanho máx. por arquivo (MB)<input id="rf-max" type="number" min="1" max="5000" value="100" class="form-control"></label>
            </div>
            <div style="font-size:.76em;color:var(--text-muted);margin-top:6px">Reprovação gera alerta proativo (e-mail/Teams). Prefira horários fora da janela de backup.</div>
            <div style="display:flex;gap:8px;margin-top:10px"><button class="btn btn-sm btn-primary" id="rf-save"><i class="fas fa-save"></i> Salvar</button><button class="btn btn-sm" id="rf-cancel">Cancelar</button></div></div>`;
        const freq = f.querySelector('#rf-freq');
        freq.onchange = () => { f.querySelector('#rf-wd-l').style.display = freq.value === 'weekly' ? '' : 'none'; f.querySelector('#rf-dom-l').style.display = freq.value === 'monthly' ? '' : 'none'; };
        f.querySelector('#rf-cancel').onclick = () => { f.style.display = 'none'; f.innerHTML = ''; };
        f.querySelector('#rf-save').onclick = async () => {
            const [hh, mm] = (f.querySelector('#rf-time').value || '02:00').split(':');
            const ag = f.querySelector('#rf-agent');
            const body = { agent_id: ag.value, name: `Teste de restauração — ${ag.options[ag.selectedIndex]?.text || ag.value}`, repository_id: f.querySelector('#rf-repo').value.trim() || null,
                frequency: freq.value, weekday: +f.querySelector('#rf-wd').value, day_of_month: +f.querySelector('#rf-dom').value, hour: +hh, minute: +mm,
                sample_size: +f.querySelector('#rf-sample').value, max_file_mb: +f.querySelector('#rf-max').value };
            try { await api('/schedules', { method: 'POST', body: JSON.stringify(body) }); toast('Teste agendado', 'success'); f.style.display = 'none'; f.innerHTML = ''; loadSchedules(); }
            catch (e) { toast(e.message, 'error'); }
        };
    }

    window.GBOCRestoreTests = {
        async init(agentId) {
            const root = document.getElementById('restore-tests');
            if (!root) return;
            if (!root.dataset.ready) { shell(root); root.dataset.ready = '1'; }
            if (agentId) S.agent = agentId;
            await loadAgents();
            loadSchedules();
            loadResults();
        },
    };
})();
