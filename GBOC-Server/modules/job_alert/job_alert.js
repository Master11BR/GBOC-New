/**
 * GBOC Server v14.0.0 — Job Alert Module UI Script
 */

async function loadServerJobAlertData() {
    try {
        const res = await fetch(window.GBOC_API_BASE + '/api/v1/server/jobs/failed');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        if (data.status === 'success') {
            const failures = data.failures || [];
            document.getElementById('srv-job-failed-count').textContent = failures.length;

            const tbody = document.getElementById('table-server-job-failures');
            if (tbody) {
                if (failures.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)"><i class="fas fa-check-circle" style="color:var(--success)"></i> Nenhuma falha de job registrada no momento. Sistema operando 100% normal.</td></tr>';
                } else {
                    tbody.innerHTML = failures.map(f => `
                        <tr>
                            <td><span class="badge badge-error">FALHA</span></td>
                            <td><strong>${f.task_name || f.task_id}</strong><br><small style="color:var(--text-muted)">ID: ${f.task_id}</small></td>
                            <td><i class="fas fa-server"></i> ${f.agent_id || 'Servidor Central'}</td>
                            <td style="color:var(--danger)">${f.reason}</td>
                            <td>${f.retry_count || 1}</td>
                            <td>
                                <button class="btn btn-success" style="padding:4px 10px;font-size:0.8em" onclick="resolveServerJobFailure('${f.task_id}')">
                                    <i class="fas fa-check"></i> Resolver
                                </button>
                            </td>
                        </tr>
                    `).join('');
                }
            }
        }
    } catch (e) {
        console.error('Erro ao carregar alertas de jobs no servidor:', e);
    }
}

async function resolveServerJobFailure(taskId) {
    try {
        const res = await fetch(window.GBOC_API_BASE + `/api/v1/server/jobs/resolve/${taskId}`, { method: 'POST' });
        if (res.ok) {
            await loadServerJobAlertData();
        }
    } catch (e) {
        console.error('Erro ao resolver falha de job:', e);
    }
}

async function testServerAlertChannel() {
    try {
        const res = await fetch(window.GBOC_API_BASE + '/api/v1/server/jobs/test-alert', { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            alert(data.message || 'Alerta de teste enviado com sucesso.');
        }
    } catch (e) {
        console.error('Erro ao testar canal de alerta:', e);
    }
}

window.loadServerJobAlertData = loadServerJobAlertData;
window.resolveServerJobFailure = resolveServerJobFailure;
window.testServerAlertChannel = testServerAlertChannel;
