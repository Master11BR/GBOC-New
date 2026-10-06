// GBOC System v14.8.1 Enterprise Edition
// Module: SureRestore JavaScript Module

async function runSureRestoreTest() {
    const box = document.getElementById('surerestore-result-box');
    const details = document.getElementById('surerestore-details');
    if (!box || !details) return;
    box.style.display = 'block';
    details.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Montando snapshot em Sandbox Hyper-V e iniciando SO...';
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/surerestore/verify', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        });
        const d = await r.json().catch(() => ({}));
        const esc = (v) => String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
        if (!r.ok) {
            details.innerHTML = `<span style="color:var(--warning)"><strong>${esc(d.overall_state || 'Inconclusivo')}:</strong> ${esc(d.error?.message || d.detail || ('HTTP ' + r.status))}</span>`;
            return;
        }
        const stages = Object.entries(d.stages || {}).map(([k, v]) => `<p><strong>${esc(k)}:</strong> ${esc(v.status)} — ${esc(v.detail)}</p>`).join('');
        details.innerHTML = `
            <p><strong>ID da Verificação:</strong> ${esc(d.verification_id || '—')}</p>
            <p><strong>Duração:</strong> ${d.execution_time_seconds != null ? esc(d.execution_time_seconds) + 's' : '—'}</p>
            ${stages}
            <p><strong>Resultado:</strong> ${esc(d.summary || d.overall_state || '—')}</p>
        `;
    } catch(e) {
        details.innerHTML = `<span style="color:var(--danger)">Erro no SureRestore: ${e.message}</span>`;
    }
}
