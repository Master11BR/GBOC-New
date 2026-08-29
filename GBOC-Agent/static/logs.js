/*
==============================================================================
GBOC System v13.2.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
/* 📜 Logs Viewer */
document.addEventListener('DOMContentLoaded', () => {
    if(document.getElementById('logViewer')) {
        loadLogs();
        setInterval(loadLogs, 5000);
    }
});

async function loadLogs() {
    const viewer = document.getElementById('logViewer');
    if (!viewer) return;
    try {
        const response = await fetch('/api/logs/?limit=100');
        const data = await response.json();
        if (data.status === 'success') {
            const html = data.logs.map(log => `
                <div class="log-line log-${log.level.includes('error') ? 'error' : 'info'}">
                    <span class="log-timestamp">[${log.timestamp}]</span>
                    <span>${log.message}</span>
                </div>
            `).join('');
            if (viewer.innerHTML !== html) viewer.innerHTML = html;
        }
    } catch (e) { console.error(e); }
} 