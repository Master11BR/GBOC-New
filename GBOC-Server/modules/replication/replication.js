// Module: Replication Controller (replication.js)
document.addEventListener('DOMContentLoaded', () => {
    loadReplicationRules();
});

async function loadReplicationRules() {
    const tbody = document.getElementById('replication-table-body');
    if (!tbody) return;
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/server/replication/overview');
        if (!r.ok) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted)">Nenhuma regra de replicação ativa.</td></tr>';
            return;
        }
        const data = await r.json();
        const rules = data.rules || [];
        if (!rules.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted)">Nenhuma regra de replicação ativa.</td></tr>';
            return;
        }
        tbody.innerHTML = rules.map(ru => `
            <tr>
                <td style="font-weight:600">${ru.name}</td>
                <td>${ru.source}</td>
                <td>${ru.target}</td>
                <td><span class="badge badge-success">${(ru.status || 'OK').toUpperCase()}</span></td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted)">Painel de replicação pronto.</td></tr>';
    }
}
