// Module: Compliance Controller (compliance.js)
document.addEventListener('DOMContentLoaded', () => {
    loadComplianceData();
});

async function loadComplianceData() {
    const tbody = document.getElementById('cp-agents-table');
    if (!tbody) return;
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/server/compliance/overview');
        if (!r.ok) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Nenhuma auditoria realizada.</td></tr>';
            return;
        }
        const data = await r.json();

        if (document.getElementById('cp-kpi-score')) document.getElementById('cp-kpi-score').textContent = `${data.score || 100}%`;
        if (document.getElementById('cp-kpi-lgpd')) document.getElementById('cp-kpi-lgpd').textContent = data.lgpd_status || 'COMPLIANT';
        if (document.getElementById('cp-kpi-nodes')) document.getElementById('cp-kpi-nodes').textContent = data.ecosystem_total_nodes || (data.agents ? data.agents.length : 0);
        if (document.getElementById('cp-kpi-cipher')) document.getElementById('cp-kpi-cipher').textContent = data.encryption_algorithm || 'AES-256-GCM';

        const agents = data.agents || [];
        if (!agents.length) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Nenhum nó localizado no ecossistema.</td></tr>';
            return;
        }
        tbody.innerHTML = agents.map(a => {
            const isServer = a.agent_id === 'servidor-central';
            const badgeClass = a.status === 'COMPLIANT' ? 'badge-success' : 'badge-error';
            const rowStyle = isServer ? 'background:rgba(79,163,232,0.06);font-weight:600' : '';
            return `
                <tr style="${rowStyle}">
                    <td>${a.hostname}</td>
                    <td><span class="badge ${isServer ? 'badge-info' : 'badge-secondary'}">${a.role || 'Nó'}</span></td>
                    <td><strong style="color:${a.score >= 80 ? 'var(--success)' : 'var(--danger)'}">${a.score}%</strong></td>
                    <td style="color:var(--success)">${a.passing || 0}</td>
                    <td style="color:${a.failing > 0 ? 'var(--danger)' : 'inherit'}">${a.failing || 0}</td>
                    <td><span class="badge ${badgeClass}">${a.status || 'OK'}</span></td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.error('loadComplianceData error:', e);
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger)">Erro ao carregar compliance do ecossistema: ${e.message}</td></tr>`;
    }
}
