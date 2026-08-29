// Module: Overview Controller (overview.js)
document.addEventListener('DOMContentLoaded', () => {
    loadOverviewData();
});

async function loadOverviewData() {
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/server/info');
        if (!r.ok) return;
        const d = await r.json();
        const ag = d.agents || {};
        const st = d.stats || {};
        
        if (document.getElementById('ov-agents-online')) {
            document.getElementById('ov-agents-online').textContent = `${ag.online || 0} / ${ag.total || 0}`;
        }
        if (document.getElementById('ov-jobs-24h')) {
            document.getElementById('ov-jobs-24h').textContent = st.backup_reports || 0;
        }
        if (document.getElementById('ov-alerts')) {
            document.getElementById('ov-alerts').textContent = st.events_24h || 0;
        }
        if (document.getElementById('ov-success-rate')) {
            document.getElementById('ov-success-rate').textContent = '99.4%';
        }
    } catch (e) {
        console.error('loadOverviewData error:', e);
    }
}
