/*
==============================================================================
GBOC System v14.0.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
/* 📥 Import Wrapper */
async function scanAndImportWithProgress() {
    if (!confirm('Iniciar importação?')) return;
    if (window.progressModal) {
        window.progressModal.show('Importando');
        window.progressModal.setProgress(10, 'Iniciando...');
    }
    try {
        const res = await fetch('/api/import/scan-and-import', { method: 'POST' });
        if (res.ok) pollProgress();
    } catch (e) {
        if (window.progressModal) window.progressModal.complete(false, e.message);
    }
}

function pollProgress() {
    const interval = setInterval(async () => {
        try {
            const res = await fetch('/api/import/progress');
            const data = await res.json();
            if (window.progressModal) window.progressModal.setProgress(data.progress, data.message);
            if (data.stage === 'done' || data.stage === 'error') {
                clearInterval(interval);
                if (window.progressModal) window.progressModal.complete(data.stage === 'done', data.message);
                if (data.stage === 'done') setTimeout(() => window.location.reload(), 2000);
            }
        } catch { clearInterval(interval); }
    }, 1000);
}
// Exporta para window
window.scanAndImportWithProgress = scanAndImportWithProgress; 