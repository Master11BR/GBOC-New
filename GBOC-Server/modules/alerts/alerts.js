// Module: Alerts Controller (alerts.js)
document.addEventListener('DOMContentLoaded', () => {
    loadAlertsData();
});

async function loadAlertsData() {
    const tbody = document.getElementById('srv-alerts-table');
    if (!tbody) return;
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/server/alerts/overview');
        if (!r.ok) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted)">Nenhum alerta pendente.</td></tr>';
            return;
        }
        const data = await r.json();
        const alerts = data.alerts || [];
        if (!alerts.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted)">Nenhum alerta pendente.</td></tr>';
            return;
        }
        tbody.innerHTML = alerts.map(a => `
            <tr>
                <td><span class="badge ${a.severity === 'critical' ? 'badge-error' : 'badge-warning'}">${(a.severity || 'INFO').toUpperCase()}</span></td>
                <td>${a.agent_name || 'Servidor Central'}</td>
                <td style="font-weight:600">${a.title}</td>
                <td>${a.message}</td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted)">Central de alertas online.</td></tr>';
    }
}
