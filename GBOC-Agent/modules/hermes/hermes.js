/* ============================================================================
   GBOC System v14.0.0 Full Stable Enterprise Edition
   Module: Hermes Agent Local Controller (hermes.js)
   ============================================================================ */

document.addEventListener('DOMContentLoaded', () => {
    loadHermesAgentData();
});

async function loadHermesAgentData() {
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/hermes/status');
        const data = await r.json();

        const p = data.pillars || {};
        const q = p.store_and_forward_queue || {};
        const h = p.self_healing_watchdog || {};
        const m = p.p2p_lan_mesh || {};
        const bw = p.bandwidth_control || {};

        document.getElementById('h-queue-count').innerText = `${q.pending_messages || 0} msgs`;
        document.getElementById('h-heal-count').innerText = `${h.heal_events_logged || 0} eventos`;
        document.getElementById('h-mesh-count').innerText = `${m.peers_online || 0} peers`;
        document.getElementById('h-bw-val').innerText = bw.mode === 'manual' ? `${bw.current_throttle_mbps} Mbps` : 'Automático';
    } catch (e) {
        console.error('Erro ao carregar dados do Hermes Agent:', e);
    }
}

async function repairVSSWriters() {
    const term = document.getElementById('heal-terminal');
    if (term) term.innerHTML += `<div>[${new Date().toLocaleTimeString()}] Executando reparo automático de VSS Writers...</div>`;

    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/hermes/heal/vss', { method: 'POST' });
        const res = await r.json();
        if (term) term.innerHTML += `<div style="color:#10b981">[${new Date().toLocaleTimeString()}] VSS Reparo concluído: ${res.message || 'Sucesso'}</div>`;
    } catch (e) {
        if (term) term.innerHTML += `<div style="color:#ef4444">[${new Date().toLocaleTimeString()}] Erro no VSS Reparo: ${e.message}</div>`;
    }
}

async function restartBackupServices() {
    const term = document.getElementById('heal-terminal');
    if (term) term.innerHTML += `<div>[${new Date().toLocaleTimeString()}] Verificando e reiniciando serviços de backup...</div>`;

    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/hermes/heal/services', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({}) });
        const res = await r.json();
        if (term) term.innerHTML += `<div style="color:#10b981">[${new Date().toLocaleTimeString()}] Serviços verificados: ${res.message || 'Sucesso'}</div>`;
    } catch (e) {
        if (term) term.innerHTML += `<div style="color:#ef4444">[${new Date().toLocaleTimeString()}] Erro nos serviços: ${e.message}</div>`;
    }
}
