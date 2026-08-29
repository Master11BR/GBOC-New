// Module: Logs Controller (logs.js)
document.addEventListener('DOMContentLoaded', () => {
    loadLogsData();
});

async function loadLogsData() {
    const tbody = document.getElementById('table-logs');
    if (!tbody) return;
    try {
        const level = document.getElementById('log-level')?.value || '';
        const search = document.getElementById('log-search')?.value || '';
        let url = `/api/v1/logs?limit=100`;
        if (level) url += `&level=${level}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;

        const r = await fetch(url);
        if (!r.ok) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">Nenhum log encontrado.</td></tr>';
            return;
        }
        const data = await r.json();
        const logs = data.logs || [];
        if (!logs.length) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">Nenhum log encontrado.</td></tr>';
            return;
        }
        tbody.innerHTML = logs.map(l => `
            <tr>
                <td><span class="badge ${l.level === 'ERROR' ? 'badge-error' : (l.level === 'WARNING' ? 'badge-warning' : 'badge-success')}">${l.level || 'INFO'}</span></td>
                <td style="font-weight:600">${l.agent_name || 'Servidor'}</td>
                <td>${l.source || 'core'}</td>
                <td>${l.message}</td>
                <td>${l.timestamp || ''}</td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">Registro de logs ativo.</td></tr>';
    }
}
