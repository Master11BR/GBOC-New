/* ============================================================================
   GBOC System v14.0.0 Full Stable Enterprise Edition
   Module: Engine Migration Controller (engine_migration.js)
   Wizard de Migração de 4 Etapas com Motion Principles & Progress Bar Fluida
   ============================================================================ */

let gDiscoveredData = null;

document.addEventListener('DOMContentLoaded', () => {
    runEngineDiscovery();
});

function goToWizardStep(stepNum) {
    document.querySelectorAll('.wizard-step-pane').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.step-item').forEach(s => s.classList.remove('active'));

    const targetPane = document.getElementById(`wizard-step-${stepNum}`);
    if (targetPane) {
        targetPane.classList.add('active');
        if (window.GBOCMotion) {
            window.GBOCMotion.animate(targetPane, 'motion-slide-up');
        }
    }

    for (let i = 1; i <= stepNum; i++) {
        const navItem = document.getElementById(`step-nav-${i}`);
        if (navItem) navItem.classList.add('active');
    }
}

async function runEngineDiscovery() {
    const loader = document.getElementById('discovery-skeleton-loader');
    const results = document.getElementById('discovery-results');

    if (loader) loader.style.display = 'block';
    if (results) results.style.display = 'none';

    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/migration/discover?agent_id=local');
        const data = await r.json();
        gDiscoveredData = data;

        renderDiscoverySummary(data);
        renderSelectionList(data);

        if (loader) loader.style.display = 'none';
        if (results) results.style.display = 'block';
    } catch (e) {
        console.error('Erro ao descobrir motores:', e);
        if (loader) loader.innerHTML = `<div class="alert-card error"><i class="fas fa-exclamation-triangle"></i> Falha na descoberta: ${e.message}</div>`;
    }
}

function renderDiscoverySummary(data) {
    const results = document.getElementById('discovery-results');
    if (!results) return;

    const summary = data.summary || {};
    results.innerHTML = `
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:16px;margin-bottom:20px">
            <div class="selection-card">
                <div style="font-size:0.8em;color:var(--text-muted)">Motores Encontrados</div>
                <div style="font-size:1.8em;font-weight:700;color:var(--primary)">${summary.total_engines_found || 2}</div>
            </div>
            <div class="selection-card">
                <div style="font-size:0.8em;color:var(--text-muted)">Tarefas Cadastradas</div>
                <div style="font-size:1.8em;font-weight:700;color:var(--success)">${summary.total_tasks_found || 0}</div>
            </div>
            <div class="selection-card">
                <div style="font-size:0.8em;color:var(--text-muted)">Repositórios Detectados</div>
                <div style="font-size:1.8em;font-weight:700;color:var(--warning)">${summary.total_repositories_found || 0}</div>
            </div>
        </div>
    `;
}

function renderSelectionList(data) {
    const tasksDiv = document.getElementById('list-tasks-selection');
    const reposDiv = document.getElementById('list-repos-selection');

    if (tasksDiv) {
        const tasks = data.tasks || [];
        if (tasks.length === 0) {
            tasksDiv.innerHTML = '<div style="font-size:0.85em;color:var(--text-muted)">Nenhuma tarefa legada encontrada para migração.</div>';
        } else {
            let html = '';
            tasks.forEach(t => {
                html += `
                    <div class="selection-card">
                        <label style="display:flex;align-items:center;gap:12px;cursor:pointer">
                            <input type="checkbox" class="chk-task-item" value="${t.id}" checked style="width:18px;height:18px">
                            <div>
                                <div style="font-weight:700;font-size:0.92em">${t.name}</div>
                                <div style="font-size:0.78em;color:var(--text-muted)">Motor Atual: ${t.current_engine} | Agendamento: ${t.schedule}</div>
                            </div>
                        </label>
                    </div>
                `;
            });
            tasksDiv.innerHTML = html;
        }
    }

    if (reposDiv) {
        const repos = data.repositories || [];
        let html = '';
        repos.forEach(r => {
            html += `
                <div class="selection-card">
                    <label style="display:flex;align-items:center;gap:12px;cursor:pointer">
                        <input type="checkbox" class="chk-repo-item" value="${r.id}" checked style="width:18px;height:18px">
                        <div>
                            <div style="font-weight:700;font-size:0.92em">${r.name}</div>
                            <div style="font-size:0.78em;color:var(--text-muted)">Tipo: ${r.engine_type} | Caminho: ${r.target_path}</div>
                        </div>
                    </label>
                </div>
            `;
        });
        reposDiv.innerHTML = html;
    }
}

async function startExecutionMigration() {
    goToWizardStep(4);

    const bar = document.getElementById('migration-progress-bar');
    const statusText = document.getElementById('migration-status-text');
    const reportDiv = document.getElementById('migration-final-report');

    const selectedTasks = Array.from(document.querySelectorAll('.chk-task-item:checked')).map(c => c.value);
    const selectedRepos = Array.from(document.querySelectorAll('.chk-repo-item:checked')).map(c => c.value);

    const params = {
        chunking: document.getElementById('cfg-chunking').value,
        compression: document.getElementById('cfg-compression').value,
        worm_immutability: document.getElementById('cfg-worm').checked
    };

    if (bar) bar.style.width = '35%';
    if (statusText) statusText.innerText = 'Convertendo tarefas e repositórios...';

    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/migration/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                agent_id: 'local',
                selected_task_ids: selectedTasks,
                selected_repo_ids: selectedRepos,
                target_params: params
            })
        });

        const res = await r.json();

        if (bar) bar.style.width = '100%';
        if (statusText) statusText.innerText = 'Migração Concluída!';

        if (reportDiv) {
            reportDiv.style.display = 'block';
            document.getElementById('migration-report-details').innerHTML = `
                • <strong>Mensagem</strong>: ${res.message}<br>
                • <strong>Motor Alvo</strong>: Motor Nativo GBOC v4 (FastCDC 4KB-4MB)<br>
                • <strong>Imutabilidade WORM</strong>: ${params.worm_immutability ? 'Ativa 🔒' : 'Inativa'}
            `;
        }
    } catch (e) {
        if (statusText) statusText.innerText = 'Erro na migração: ' + e.message;
    }
}
