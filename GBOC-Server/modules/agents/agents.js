// Module: Agents Controller (agents.js)
document.addEventListener('DOMContentLoaded', () => {
    loadAgentsList();
});

async function loadAgentsList() {
    const tbody = document.getElementById('agents-table-body');
    if (!tbody) return;
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/agents');
        if (!r.ok) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Nenhum agente cadastrado no momento.</td></tr>';
            return;
        }
        const data = await r.json();
        const list = Array.isArray(data) ? data : (data.agents || []);
        if (!list.length) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Nenhum agente cadastrado no momento.</td></tr>';
            return;
        }
        tbody.innerHTML = list.map(a => `
            <tr>
                <td style="font-weight:600">${a.hostname || a.agent_id}</td>
                <td>${a.ip_address || '—'}</td>
                <td>${a.os_info || 'Windows/Linux'}</td>
                <td><span class="badge badge-info">v${a.agent_version || '13.2.0'}</span></td>
                <td>${a.last_heartbeat || '—'}</td>
                <td><span class="badge ${a.status === 'online' ? 'badge-success' : 'badge-error'}">${(a.status || 'OFFLINE').toUpperCase()}</span></td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger)">Erro ao carregar agentes: ${e.message}</td></tr>`;
    }
}
