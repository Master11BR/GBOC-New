// GBOC System v13.2.0 Enterprise Edition
// Module: Backups JavaScript Module

async function loadBackupsTab() {
    const tbody = document.getElementById('table-backups');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center"><i class="fas fa-spinner fa-spin"></i> Carregando backups...</td></tr>';
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/backups/recent');
        const d = await r.json();
        const reports = d.reports || [];
        if (reports.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Nenhum backup registrado.</td></tr>';
            return;
        }
        tbody.innerHTML = reports.map(b => `
            <tr>
                <td><span class="badge badge-${b.status === 'success' ? 'success' : 'danger'}">${b.status.toUpperCase()}</span></td>
                <td><strong>${b.agent_id}</strong></td>
                <td>${b.job_name}</td>
                <td>${b.duration_seconds}s</td>
                <td>${(b.size_bytes / (1024*1024*1024)).toFixed(2)} GB</td>
                <td>${b.timestamp}</td>
            </tr>
        `).join('');
    } catch(e) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger)">Erro: ${e.message}</td></tr>`;
    }
}
