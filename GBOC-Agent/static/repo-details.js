/*
 * GBOC — Detalhes do repositório (configurações salvas + configurações lidas do provedor de nuvem).
 * Arquivo idêntico no Agente (static/repo-details.js) e no Server (modules/agents/repo_details.js).
 *
 * Uso: GBOCRepoDetails.open(repoId, { get: async (path) => json })
 *   path = 'api/agent-ops/repositories/<id>/details?live=0|1'  (sem barra inicial)
 *   No Agente o padrão é fetch('/' + path); no Server use o proxy do Gerenciamento Remoto.
 */
(function () {
    'use strict';
    if (window.GBOCRepoDetails) return;

    const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const fmtBytes = (b) => {
        if (b == null || isNaN(b)) return '—';
        const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']; let i = 0; let n = Number(b);
        while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
        return (i ? n.toFixed(2) : n) + ' ' + u[i];
    };
    const yesNo = (v) => v === true ? 'Sim' : v === false ? 'Não' : '—';
    const dash = (v) => (v === null || v === undefined || v === '') ? '—' : esc(v);

    function css() {
        if (document.getElementById('gboc-rd-css')) return;
        const s = document.createElement('style');
        s.id = 'gboc-rd-css';
        s.textContent = `
.gboc-rd-ov{position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(3px);z-index:10050;display:flex;align-items:flex-start;justify-content:center;padding:4vh 16px;overflow:auto}
.gboc-rd{background:var(--bg-main,#121212);color:var(--text-primary,var(--text,#e2e8f0));border:1px solid var(--card-border,var(--border-color,#334155));border-radius:12px;width:min(1100px,100%);box-shadow:0 20px 60px rgba(0,0,0,.4)}
.gboc-rd-h{display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid var(--card-border,var(--border-color,#334155));flex-wrap:wrap}
.gboc-rd-h h3{margin:0;font-size:1.15em;flex:1;min-width:200px}
.gboc-rd-b{padding:16px 20px;display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.gboc-rd-c{border:1px solid var(--card-border,var(--border-color,#334155));border-radius:10px;padding:12px 14px;background:var(--bg-card,rgba(127,127,127,.06))}
.gboc-rd-c.wide{grid-column:1/-1}
.gboc-rd,.gboc-rd *{box-sizing:border-box}
.gboc-rd-b>*{min-width:0}
.gboc-rd-c{overflow-wrap:anywhere}
.gboc-rd-c table{display:block;overflow-x:auto}
.gboc-rd-c h4{margin:0 0 8px;font-size:.92em;color:var(--primary-color,#60a5fa);display:flex;align-items:center;gap:6px}
.gboc-rd-kv{display:grid;grid-template-columns:minmax(120px,40%) 1fr;gap:4px 10px;font-size:.86em}
.gboc-rd-kv>div:nth-child(odd){color:var(--text-muted,#94a3b8)}
.gboc-rd-kv>div{word-break:break-word}
.gboc-rd-t{width:100%;border-collapse:collapse;font-size:.84em}
.gboc-rd-t th,.gboc-rd-t td{padding:5px 6px;border-bottom:1px solid var(--card-border,var(--border-color,#334155));text-align:left}
.gboc-rd-t th{color:var(--text-muted,#94a3b8);font-weight:600}
.gboc-rd-chip{display:inline-block;padding:1px 8px;border-radius:10px;font-size:.8em;font-weight:600}
.gboc-rd-ok{background:rgba(72,187,120,.15);color:var(--success-color,#48bb78)}
.gboc-rd-warn{background:rgba(237,137,54,.15);color:var(--warning-color,#ed8936)}
.gboc-rd-bad{background:rgba(245,101,101,.15);color:var(--danger-color,#f56565)}
.gboc-rd-muted{background:rgba(148,163,184,.15);color:var(--text-muted,#94a3b8)}
.gboc-rd-alert{grid-column:1/-1;padding:10px 12px;border-radius:8px;font-size:.88em}
.gboc-rd-btn{border:1px solid var(--card-border,var(--border-color,#334155));background:transparent;color:inherit;border-radius:8px;padding:7px 12px;cursor:pointer;font-size:.88em}
.gboc-rd-btn.primary{background:var(--primary-color,#3b82f6);border-color:transparent;color:#fff}
.gboc-rd-btn:disabled{opacity:.6;cursor:wait}
@media (max-width:600px){.gboc-rd-b{grid-template-columns:1fr}.gboc-rd-kv{grid-template-columns:1fr}.gboc-rd-kv>div:nth-child(odd){margin-top:6px}}`;
        document.head.appendChild(s);
    }

    const chip = (txt, tone) => `<span class="gboc-rd-chip gboc-rd-${tone}">${esc(txt)}</span>`;
    const kv = (rows) => '<div class="gboc-rd-kv">' + rows.filter(Boolean).map(([k, v]) => `<div>${esc(k)}</div><div>${v}</div>`).join('') + '</div>';
    const card = (icon, title, body, wide) => `<div class="gboc-rd-c${wide ? ' wide' : ''}"><h4><i class="fas ${icon}"></i>${esc(title)}</h4>${body}</div>`;

    function cronText(c, en) {
        if (!c) return 'Manual';
        return esc(c) + (en === false ? ' (pausado)' : '');
    }

    function renderStored(d) {
        const g = d.general || {}, c = d.connection || {}, im = d.immutability || {};
        const cloud = g.type && g.type !== 'local';
        const out = [];
        if (cloud && c.secret_saved === false) {
            out.push(`<div class="gboc-rd-alert gboc-rd-bad"><i class="fas fa-key"></i> <b>Chave secreta do provedor não está salva.</b> ${esc(c.secret)}</div>`);
        }
        out.push(card('fa-info-circle', 'Geral', kv([
            ['Nome', esc(g.name)], ['ID', dash(g.id)], ['Provedor', esc(g.provider)], ['Motor', esc(g.engine)],
            ['Status', esc(g.status)], ['Habilitado', yesNo(g.enabled)], ['Inicializado', yesNo(g.initialized)],
            ['Criado em', dash(g.created_at)], ['Atualizado em', dash(g.updated_at)]
        ])));
        if (cloud) {
            out.push(card('fa-cloud', 'Conexão (configuração salva)', kv([
                ['Bucket / contêiner', dash(c.bucket)], ['Prefixo', dash(c.prefix)],
                ['Região', dash(c.region) + (c.region && !c.region_informed ? ' <small>(deduzida)</small>' : '')],
                ['Endpoint', dash(c.endpoint)], ['Chave de acesso', dash(c.access_key)],
                ['Chave secreta', c.secret_saved ? chip('salva (criptografada)', 'ok') : chip('não salva', 'bad')],
                ['Senha de criptografia', c.encryption_password === 'definida' ? chip('definida', 'ok') : chip('não definida', 'bad')]
            ])));
        } else {
            const l = d.local || {};
            out.push(card('fa-hdd', 'Armazenamento local', kv([
                ['Caminho', dash(c.path)], ['Pasta existe', yesNo(l.exists)], ['Gravável', yesNo(l.writable)],
                ['Disco total', fmtBytes(l.disk_total_bytes)], ['Disco livre', fmtBytes(l.disk_free_bytes)],
                ['Uso do disco', l.disk_used_pct != null ? esc(l.disk_used_pct) + '%' : '—'],
                ['Senha de criptografia', c.encryption_password === 'definida' ? chip('definida', 'ok') : chip('não definida', 'bad')]
            ])));
        }
        const e = d.engine || {};
        out.push(card('fa-cogs', 'Motor de backup', kv([
            ['Motor', esc(e.engine)], e.variable ? ['Variável', esc(e.variable)] : null, ['Destino usado', `<code>${dash(e.target)}</code>`]
        ])));
        const modeTxt = { off: 'Desativada', object_lock: 'S3 Object Lock', local_worm: 'WORM local' }[im.mode] || im.mode;
        const lc = im.last_check || {};
        out.push(card('fa-lock', 'Imutabilidade (política no GBOC)', kv([
            ['Modo', im.mode === 'off' ? chip(modeTxt, 'muted') : chip(modeTxt, 'ok')],
            im.mode !== 'off' ? ['Retenção', esc(im.days) + ' dia(s)' + (im.mode === 'object_lock' ? ' · ' + esc(im.lock_mode) : '')] : null,
            ['Última verificação', lc.at ? `${esc(lc.at)} ${lc.protected ? chip('protegido', 'ok') : chip('não protegido', 'bad')}` : '—'],
            lc.summary ? ['Resultado', esc(lc.summary)] : null
        ])));
        const u = d.usage;
        out.push(card('fa-database', 'Uso medido pelo GBOC', u ? kv([
            ['Tamanho', fmtBytes(u.size_bytes)], ['Snapshots', dash(u.snapshot_count)], ['Medido em', dash(u.recorded_at)]
        ]) : '<div style="font-size:.86em;color:var(--text-muted,#94a3b8)">Ainda não medido.</div>'));
        if (d.other_settings) {
            out.push(card('fa-sliders-h', 'Outras configurações', kv(Object.entries(d.other_settings).map(([k, v]) => [k, dash(v)]))));
        }
        const t = d.tasks || [];
        out.push(card('fa-tasks', `Tarefas que gravam neste repositório (${t.length})`, t.length ? `
            <table class="gboc-rd-t"><thead><tr><th>Tarefa</th><th>Agendamento</th><th>Retenção</th><th>Última execução</th><th>Resultado</th></tr></thead><tbody>
            ${t.map((x) => `<tr><td>${esc(x.name)}${x.enabled === false ? ' ' + chip('desativada', 'muted') : ''}</td><td>${cronText(x.schedule_cron, x.schedule_enabled)}</td>
                <td>${x.retention_days ? esc(x.retention_days) + ' dia(s)' : '—'}</td><td>${dash(x.last_run)}</td>
                <td>${x.last_status ? chip(x.last_status, /success|completed|ok/i.test(x.last_status) ? 'ok' : /fail|error/i.test(x.last_status) ? 'bad' : 'muted') : '—'}</td></tr>`).join('')}
            </tbody></table>` : '<div style="font-size:.86em;color:var(--text-muted,#94a3b8)">Nenhuma tarefa usa este repositório.</div>', true));
        return out.join('');
    }

    function state(v) {
        if (!v) return '—';
        if (v.error) return chip(v.error, /permissão/.test(v.error) ? 'warn' : 'muted');
        return null;
    }

    function renderLive(cl, stored) {
        if (!cl) return '';
        if (cl.error && cl.reachable === undefined) {
            return card('fa-cloud', 'Configurações lidas do provedor', `<div class="gboc-rd-alert ${cl.secret_missing ? 'gboc-rd-bad' : 'gboc-rd-warn'}">${esc(cl.error)}</div>`, true);
        }
        if (!cl.reachable) {
            return card('fa-cloud', 'Configurações lidas do provedor', `<div class="gboc-rd-alert gboc-rd-bad"><b>Não foi possível acessar o bucket.</b> ${esc(cl.error || '')}</div>`, true);
        }
        const rows = [];
        rows.push(['Acesso', `${chip('conectado', 'ok')} ${cl.latency_ms != null ? esc(cl.latency_ms) + ' ms' : ''}`]);
        rows.push(['Bucket / prefixo', esc(cl.bucket) + (cl.prefix ? ' / ' + esc(cl.prefix) : '')]);
        if (cl.endpoint) rows.push(['Endpoint', esc(cl.endpoint)]);
        if (cl.location) {
            const st = state(cl.location);
            const cfgReg = (stored.connection || {}).region;
            rows.push(['Região do bucket', st || (esc(cl.location.region) + (cfgReg && cl.location.region && cfgReg !== cl.location.region ? ' ' + chip('difere da configurada (' + cfgReg + ')', 'warn') : ''))]);
        }
        if (cl.versioning) rows.push(['Versionamento', state(cl.versioning) || chip(cl.versioning.status, cl.versioning.status === 'Enabled' ? 'ok' : 'muted') + (cl.versioning.mfa_delete === 'Enabled' ? ' · MFA Delete' : '')]);
        if (cl.object_lock) {
            const o = cl.object_lock;
            rows.push(['Object Lock', state(o) || (o.configured === false || !o.enabled ? chip('desativado', 'muted')
                : chip('habilitado', 'ok') + (o.default_mode ? ` · retenção padrão ${esc(o.default_mode)} ${o.default_days ? esc(o.default_days) + ' dia(s)' : esc(o.default_years) + ' ano(s)'}` : ' · sem retenção padrão'))]);
        }
        if (cl.encryption) rows.push(['Criptografia no servidor', state(cl.encryption) || (cl.encryption.configured ? (cl.encryption.rules || []).map((r) => esc(r.algorithm) + (r.kms_key ? ' (KMS)' : '')).join(', ') : chip('não configurada', 'muted'))]);
        if (cl.public_access_block) {
            const p = cl.public_access_block;
            const all = p.BlockPublicAcls && p.IgnorePublicAcls && p.BlockPublicPolicy && p.RestrictPublicBuckets;
            rows.push(['Bloqueio de acesso público', state(p) || (p.configured === false ? chip('não configurado', 'muted') : chip(all ? 'todos ativos' : 'parcial', all ? 'ok' : 'warn'))]);
        }
        if (cl.policy_status && !cl.policy_status.error && cl.policy_status.is_public != null) rows.push(['Bucket público', cl.policy_status.is_public ? chip('SIM — público', 'bad') : chip('não', 'ok')]);
        if (cl.policy) rows.push(['Política do bucket', state(cl.policy) || (cl.policy.configured ? 'configurada' : chip('nenhuma', 'muted'))]);
        if (cl.acl) rows.push(['ACL', state(cl.acl) || (`dono: ${dash(cl.acl.owner)}<br>` + (cl.acl.grants || []).map((g) => /público/.test(g) ? chip(g, 'bad') : esc(g)).join('<br>'))]);
        if (cl.tags) rows.push(['Tags', state(cl.tags) || (cl.tags.configured ? Object.entries(cl.tags.tags || {}).map(([k, v]) => `${esc(k)}=${esc(v)}`).join(', ') || '—' : chip('nenhuma', 'muted'))]);
        if (cl.cors) rows.push(['CORS', state(cl.cors) || (cl.cors.configured ? esc(cl.cors.rules) + ' regra(s)' : chip('nenhum', 'muted'))]);
        if (cl.access_logging) rows.push(['Log de acesso', state(cl.access_logging) || (cl.access_logging.configured ? esc(cl.access_logging.target) : chip('desativado', 'muted'))]);
        if (cl.replication) rows.push(['Replicação', state(cl.replication) || (cl.replication.configured ? (cl.replication.rules || []).map((r) => `${esc(r.id || '')} → ${esc(r.destination)} (${esc(r.status)})`).join('<br>') : chip('não configurada', 'muted'))]);
        let html = kv(rows);
        if (cl.lifecycle) {
            const lc = cl.lifecycle;
            html += '<h4 style="margin-top:12px"><i class="fas fa-recycle"></i>Ciclo de vida</h4>';
            html += state(lc) || (!lc.configured ? '<div style="font-size:.86em">' + chip('nenhuma regra', 'muted') + '</div>' : `
                <table class="gboc-rd-t"><thead><tr><th>Regra</th><th>Status</th><th>Prefixo</th><th>Expira</th><th>Versões antigas</th><th>Upload incompleto</th><th>Transições</th></tr></thead><tbody>
                ${(lc.rules || []).map((r) => `<tr><td>${dash(r.id)}</td><td>${chip(r.status, r.status === 'Enabled' ? 'ok' : 'muted')}</td><td>${r.prefix ? esc(r.prefix) : '(todo o bucket)'}</td>
                    <td>${r.expiration_days ? esc(r.expiration_days) + ' dia(s)' : '—'}</td><td>${r.noncurrent_expiration_days ? esc(r.noncurrent_expiration_days) + ' dia(s)' : '—'}</td>
                    <td>${r.abort_multipart_days ? esc(r.abort_multipart_days) + ' dia(s)' : '—'}</td><td>${(r.transitions || []).map(esc).join('<br>') || '—'}</td></tr>`).join('')}
                </tbody></table>`);
            const im = stored.immutability || {};
            if (lc.configured && im.mode === 'object_lock' && (lc.rules || []).some((r) => r.status === 'Enabled' && r.expiration_days && r.expiration_days < (im.days || 0))) {
                html += `<div class="gboc-rd-alert gboc-rd-warn" style="margin-top:8px">Há regra de expiração menor que a retenção imutável (${esc(im.days)} dias).</div>`;
            }
        }
        const ob = cl.objects;
        if (ob) {
            html += '<h4 style="margin-top:12px"><i class="fas fa-boxes"></i>Objetos ' + (cl.prefix ? 'sob o prefixo' : 'no bucket') + '</h4>';
            if (ob.error) html += state(ob);
            else {
                const no = ob.newest_object;
                html += kv([
                    ['Quantidade', esc(ob.count) + (ob.partial ? ' ' + chip('contagem parcial', 'warn') : '')],
                    ['Tamanho', fmtBytes(ob.size_bytes) + (ob.partial ? ' (parcial)' : '')],
                    ['Mais antigo', dash(ob.oldest)], ['Mais recente', dash(ob.newest)],
                    ob.storage_classes ? ['Classes', Object.entries(ob.storage_classes).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(', ') || '—'] : null,
                    no ? ['Objeto mais recente', `<code>${esc(no.key)}</code>`] : null,
                    no && !no.error ? ['Bloqueio do objeto', no.locked ? chip(`bloqueado (${no.lock_mode}) até ${no.retain_until}`, 'ok') : chip('não bloqueado', (stored.immutability || {}).mode === 'object_lock' ? 'bad' : 'muted')] : null,
                    no && !no.error && no.encryption ? ['Criptografia do objeto', esc(no.encryption)] : null,
                    no && no.error ? ['Objeto mais recente', state(no)] : null
                ]);
            }
        }
        if (cl.note) html += `<div style="font-size:.82em;color:var(--text-muted,#94a3b8);margin-top:8px">${esc(cl.note)}</div>`;
        html += `<div style="font-size:.78em;color:var(--text-muted,#94a3b8);margin-top:8px">Consultado em ${esc(cl.checked_at)} (${esc(cl.duration_s)} s)</div>`;
        return card('fa-cloud', 'Configurações lidas do provedor (agora)', html, true);
    }

    async function open(repoId, opts) {
        opts = opts || {};
        css();
        const get = opts.get || (async (p) => {
            const r = await fetch('/' + p);
            const j = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(j.detail || j.message || ('HTTP ' + r.status));
            return j;
        });
        const ov = document.createElement('div');
        ov.className = 'gboc-rd-ov';
        ov.innerHTML = `<div class="gboc-rd" role="dialog" aria-modal="true">
            <div class="gboc-rd-h"><h3><i class="fas fa-database"></i> <span data-rd-title>Repositório</span></h3>
              <button class="gboc-rd-btn primary" data-rd-live style="display:none"><i class="fas fa-cloud-download-alt"></i> Consultar nuvem agora</button>
              <button class="gboc-rd-btn" data-rd-close><i class="fas fa-times"></i> Fechar</button></div>
            <div class="gboc-rd-b" data-rd-body><div style="grid-column:1/-1;padding:20px;text-align:center"><i class="fas fa-spinner fa-spin"></i> Carregando…</div></div></div>`;
        document.body.appendChild(ov);
        const close = () => { ov.remove(); document.removeEventListener('keydown', onKey); };
        const onKey = (e) => { if (e.key === 'Escape') close(); };
        document.addEventListener('keydown', onKey);
        ov.addEventListener('click', (e) => { if (e.target === ov) close(); });
        ov.querySelector('[data-rd-close]').onclick = close;
        const body = ov.querySelector('[data-rd-body]');
        const btn = ov.querySelector('[data-rd-live]');
        let stored = null;
        const base = `api/agent-ops/repositories/${encodeURIComponent(repoId)}/details`;
        const load = async (live) => {
            try {
                if (live) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Consultando…'; }
                const d = await get(base + '?live=' + (live ? 'true' : 'false'));
                stored = d;
                ov.querySelector('[data-rd-title]').textContent = `${(d.general || {}).name || 'Repositório'} — ${(d.general || {}).provider || ''}`;
                const isCloud = (d.general || {}).type && d.general.type !== 'local';
                btn.style.display = isCloud ? '' : 'none';
                body.innerHTML = renderStored(d) + (live ? renderLive(d.cloud, d) : (isCloud ? `<div class="gboc-rd-c wide" style="font-size:.86em;color:var(--text-muted,#94a3b8)"><i class="fas fa-info-circle"></i> Clique em <b>Consultar nuvem agora</b> para ler do provedor versionamento, Object Lock, criptografia, ciclo de vida, acesso público, tags, objetos e demais configurações do bucket.</div>` : ''));
            } catch (e) {
                body.innerHTML = `<div class="gboc-rd-alert gboc-rd-bad">${esc(e.message || e)}</div>` + (stored ? renderStored(stored) : '');
            } finally {
                btn.disabled = false; btn.innerHTML = '<i class="fas fa-cloud-download-alt"></i> Consultar nuvem agora';
            }
        };
        btn.onclick = () => load(true);
        await load(!!opts.live);
    }

    window.GBOCRepoDetails = { open };
})();
