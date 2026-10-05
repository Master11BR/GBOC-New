/* ============================================================================
   GBOC System — Module: Engine Migration Controller (engine_migration.js)
   Migração REAL de tarefas para o Motor Nativo GBOC, executada no Agente dono das
   tarefas (Server e Agente podem estar em máquinas diferentes).
   Fluxo: 1. Agente  2. Tarefas  3. Repositório nativo de destino  4. Execução
   ============================================================================ */

let gDiscoveredData = null;
let gMigrationAgent = '';

document.addEventListener('DOMContentLoaded', () => {
    // Página standalone: os painéis antigos (2-4) foram substituídos pelo fluxo abaixo
    ['wizard-step-2', 'wizard-step-3', 'wizard-step-4'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    if (window.gbocTabHidden && window.gbocTabHidden('tab-engine-migration')) return;   // painel: descobre ao abrir a aba
    runEngineDiscovery();
});

function _migEsc(v) {
    return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _migApi(path) {
    return (window.GBOC_API_BASE || '') + '/api/v1/migration' + path;
}

async function _migJson(resp) {
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || data.message || ('HTTP ' + resp.status));
    return data;
}

function goToWizardStep(stepNum) {
    for (let i = 1; i <= 4; i++) {
        const nav = document.getElementById(`step-nav-${i}`);
        if (!nav) continue;
        nav.classList.toggle('active', i <= stepNum);
        nav.style.opacity = i <= stepNum ? '1' : '0.6';
        nav.style.color = i <= stepNum ? 'var(--primary)' : '';
    }
}

async function runEngineDiscovery() {
    const loader = document.getElementById('discovery-skeleton-loader');
    const results = document.getElementById('discovery-results');
    if (!results) return;
    if (loader) { loader.style.display = 'block'; loader.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Carregando agentes...'; }
    results.style.display = 'none';
    goToWizardStep(1);

    let agents = [];
    try {
        agents = (await _migJson(await fetch(_migApi('/agents')))).agents || [];
    } catch (e) {
        if (loader) loader.innerHTML = `<div class="alert-card critical">Falha ao listar agentes: ${_migEsc(e.message)}</div>`;
        return;
    }
    if (loader) loader.style.display = 'none';
    results.style.display = 'block';

    if (!agents.length) {
        results.innerHTML = '<div class="empty show">Nenhum agente registrado. A migração é feita no Agente que possui as tarefas.</div>';
        return;
    }
    if (!gMigrationAgent || !agents.some(a => a.agent_id === gMigrationAgent)) gMigrationAgent = agents[0].agent_id;

    results.innerHTML = `
        <div class="panel" style="padding:16px;margin-bottom:16px">
            <label class="form-label" for="mig-agent">1. Agente</label>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
                <select id="mig-agent" class="form-control" style="flex:1;min-width:240px">
                    ${agents.map(a => `<option value="${_migEsc(a.agent_id)}" ${a.agent_id === gMigrationAgent ? 'selected' : ''}>
                        ${_migEsc(a.hostname)} (${_migEsc(a.ip_address || 'sem IP')}) — ${_migEsc((a.status || 'desconhecido').toUpperCase())}</option>`).join('')}
                </select>
                <button class="btn btn-secondary" onclick="loadMigrationDiscovery()"><i class="fas fa-search"></i> Descobrir</button>
            </div>
        </div>
        <div id="mig-body"></div>`;
    document.getElementById('mig-agent').addEventListener('change', (e) => {
        gMigrationAgent = e.target.value;
        loadMigrationDiscovery();
    });
    loadMigrationDiscovery();
}

async function loadMigrationDiscovery() {
    const body = document.getElementById('mig-body');
    if (!body) return;
    body.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted)"><i class="fas fa-spinner fa-spin"></i> Consultando o agente...</div>';
    try {
        gDiscoveredData = await _migJson(await fetch(_migApi('/discover?agent_id=' + encodeURIComponent(gMigrationAgent))));
    } catch (e) {
        body.innerHTML = `<div class="alert-card critical"><div><div class="alert-title">Descoberta indisponível</div><div class="alert-msg">${_migEsc(e.message)}</div></div></div>`;
        return;
    }
    goToWizardStep(2);
    renderDiscoverySummary(gDiscoveredData);
}

function renderDiscoverySummary(data) {
    const body = document.getElementById('mig-body');
    if (!body) return;
    const s = data.summary || {};
    const legacy = (data.tasks || []).filter(t => t.can_migrate);
    const natives = data.native_repositories || [];

    body.innerHTML = `
        <div class="kpi-grid" style="margin-bottom:16px">
            <div class="kpi-card"><div class="kpi-header"><span>Motores em uso</span></div><div class="kpi-value">${s.total_engines_found ?? 0}</div>
                <div class="kpi-sub">${(data.engines || []).map(e => `${_migEsc(e.name)} (${e.tasks})`).join(' · ') || '—'}</div></div>
            <div class="kpi-card"><div class="kpi-header"><span>Tarefas</span></div><div class="kpi-value">${s.total_tasks_found ?? 0}</div>
                <div class="kpi-sub">${s.legacy_tasks_found ?? 0} em motor externo</div></div>
            <div class="kpi-card"><div class="kpi-header"><span>Repositórios</span></div><div class="kpi-value">${s.total_repositories_found ?? 0}</div>
                <div class="kpi-sub">${s.native_repositories_found ?? 0} no Motor Nativo</div></div>
        </div>

        <div class="panel" style="padding:16px;margin-bottom:16px">
            <h3 style="margin-bottom:10px">2. Tarefas a migrar</h3>
            ${legacy.length ? legacy.map(t => `
                <label class="selection-card" style="display:flex;gap:12px;align-items:center;padding:10px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px;cursor:pointer">
                    <input type="checkbox" class="chk-task-item" value="${t.id}" checked style="width:18px;height:18px">
                    <div>
                        <div style="font-weight:700">${_migEsc(t.name)}</div>
                        <div style="font-size:.8em;color:var(--text-muted)">Motor atual: ${_migEsc(t.current_engine)} · Repositório: ${_migEsc(t.repository_name || '—')}
                            · Agendamento: ${_migEsc(t.schedule || 'manual')}</div>
                    </div>
                </label>`).join('') : '<div class="empty show">Todas as tarefas deste agente já usam o Motor Nativo GBOC.</div>'}
        </div>

        ${legacy.length ? `
        <div class="panel" style="padding:16px;margin-bottom:16px">
            <h3 style="margin-bottom:10px">3. Repositório nativo de destino</h3>
            <select id="mig-target" class="form-control" style="margin-bottom:10px">
                ${natives.map(r => `<option value="${r.id}">${_migEsc(r.name)} — ${_migEsc(r.target_path)}</option>`).join('')}
                <option value="__new__" ${natives.length ? '' : 'selected'}>+ Criar novo repositório nativo local</option>
            </select>
            <div id="mig-new-repo" style="display:${natives.length ? 'none' : 'grid'};grid-template-columns:1fr 1fr;gap:10px">
                <div><label class="form-label">Nome do novo repositório</label>
                    <input id="mig-new-name" class="form-control" placeholder="Ex.: Nativo ${_migEsc((data.tasks[0] || {}).name || 'Backups')}"></div>
                <div><label class="form-label">Senha do motor (mín. 8 caracteres)</label>
                    <input id="mig-new-pwd" type="password" class="form-control" autocomplete="new-password"></div>
            </div>
            <p style="font-size:.82em;color:var(--text-muted);margin-top:10px">
                As tarefas passam a usar o Motor Nativo a partir da próxima execução. Os backups já feitos permanecem no
                repositório de origem e continuam disponíveis para restauração.
            </p>
        </div>
        <div style="display:flex;justify-content:flex-end;margin-bottom:16px">
            <button class="btn btn-primary" id="mig-run" onclick="startExecutionMigration()"><i class="fas fa-shuffle"></i> 4. Migrar tarefas selecionadas</button>
        </div>` : ''}
        <div id="mig-report"></div>`;

    const sel = document.getElementById('mig-target');
    if (sel) sel.addEventListener('change', () => {
        document.getElementById('mig-new-repo').style.display = sel.value === '__new__' ? 'grid' : 'none';
    });
    goToWizardStep(legacy.length ? 3 : 2);
}

// Compatibilidade: chamado por versões anteriores da página
function renderSelectionList(data) { renderDiscoverySummary(data); }

async function startExecutionMigration() {
    const report = document.getElementById('mig-report');
    const btn = document.getElementById('mig-run');
    const taskIds = Array.from(document.querySelectorAll('.chk-task-item:checked')).map(c => c.value);
    const target = document.getElementById('mig-target')?.value;
    if (!taskIds.length) { alert('Selecione ao menos uma tarefa.'); return; }

    const params = {};
    if (target === '__new__') {
        params.new_repository_name = (document.getElementById('mig-new-name')?.value || '').trim();
        params.motor_password = document.getElementById('mig-new-pwd')?.value || '';
        if (!params.new_repository_name) { alert('Informe o nome do novo repositório nativo.'); return; }
        if (params.motor_password.length < 8) { alert('A senha do motor precisa ter pelo menos 8 caracteres.'); return; }
    } else {
        params.target_repository_id = parseInt(target, 10);
    }
    if (!confirm(`Migrar ${taskIds.length} tarefa(s) para o Motor Nativo GBOC?`)) return;

    goToWizardStep(4);
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Migrando...'; }
    try {
        const res = await _migJson(await fetch(_migApi('/execute'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_id: gMigrationAgent, selected_task_ids: taskIds, selected_repo_ids: [], target_params: params })
        }));
        const ok = res.status === 'success';
        const html = `
            <div class="alert-card ${ok ? 'info' : 'warning'}">
                <div>
                    <div class="alert-title">${ok ? 'Migração concluída' : 'Nada foi alterado'}</div>
                    <div class="alert-msg">${_migEsc(res.message)}</div>
                    ${(res.migrated_tasks || []).map(m => `<div class="alert-msg">✓ ${_migEsc(m.name)}: ${_migEsc(m.from_engine)} → Motor Nativo (${_migEsc(m.to_repository)})</div>`).join('')}
                    ${(res.skipped || []).map(m => `<div class="alert-msg">— ${_migEsc(m.name || m.id)}: ${_migEsc(m.reason)}</div>`).join('')}
                </div>
            </div>`;
        await loadMigrationDiscovery();   // recarrega a lista (tarefas migradas somem dela)
        const rep = document.getElementById('mig-report');
        if (rep) rep.innerHTML = html;
    } catch (e) {
        if (report) report.innerHTML = `<div class="alert-card critical"><div><div class="alert-title">Falha na migração</div><div class="alert-msg">${_migEsc(e.message)}</div></div></div>`;
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-shuffle"></i> 4. Migrar tarefas selecionadas'; }
    }
}
