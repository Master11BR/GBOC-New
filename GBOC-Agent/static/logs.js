/*
==============================================================================
GBOC System v14.6.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
/* 📜 Logs Viewer */
var _logsSmartInterval = null;
document.addEventListener('DOMContentLoaded', () => {
    if(document.getElementById('logViewer')) {
        loadLogs();
        _logsSmartInterval = (window.gbocPerf && window.gbocPerf.smartInterval)
            ? window.gbocPerf.smartInterval(loadLogs, 5000)
            : setInterval(loadLogs, 5000);
    }
});

async function loadLogs() {
    const viewer = document.getElementById('logViewer');
    if (!viewer) return;
    try {
        const fetchFn = async (signal) => {
            const response = await fetch('/api/logs/?limit=100', { signal });
            return await response.json();
        };

        const data = window.gbocPerf?.makeCancellable
            ? await window.gbocPerf.makeCancellable('loadLogs', fetchFn)
            : await fetchFn();

        if (data && data.status === 'success' && Array.isArray(data.logs)) {
            const html = data.logs.map(log => `
                <div class="log-line log-${(log.level || '').includes('error') ? 'error' : 'info'}">
                    <span class="log-timestamp">[${log.timestamp || ''}]</span>
                    <span>${log.message || ''}</span>
                </div>
            `).join('');
            if (window.gbocPerf && window.gbocPerf.safeRender) {
                window.gbocPerf.safeRender(viewer, html);
            } else if (viewer.innerHTML !== html) {
                viewer.innerHTML = html;
            }
        }
    } catch (e) {
        if (e.name !== 'AbortError') console.error(e);
    }
} 