/* ============================================================================
   GBOC System v14.0.0 Full Stable Enterprise Edition
   Module: Hermes Server Control Center (hermes.js)
   ============================================================================ */

document.addEventListener('DOMContentLoaded', () => {
    loadHermesServerData();
});

async function loadHermesServerData() {
    const skel = document.getElementById('hermes-skeleton');
    const list = document.getElementById('hermes-agents-list');

    if (skel) skel.style.display = 'block';
    if (list) list.style.display = 'none';

    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/server/hermes/agents');
        const data = await r.json();

        renderHermesStats(data);
        renderAgentsList(data.agents || []);

        if (skel) skel.style.display = 'none';
        if (list) list.style.display = 'block';
    } catch (e) {
        console.error('Erro ao carregar dados do Hermes Server:', e);
        if (skel) skel.innerHTML = `<div class="alert-card error"><i class="fas fa-exclamation-triangle"></i> Falha ao comunicar com o módulo Hermes: ${e.message}</div>`;
    }
}

function renderHermesStats(data) {
    const qStat = document.getElementById('h-stat-queue');
    const hStat = document.getElementById('h-stat-heal');
    const mStat = document.getElementById('h-stat-mesh');

    if (qStat) qStat.innerText = `${data.total_pending_queue || 0} msgs`;
    if (hStat) hStat.innerText = `${data.total_heal_events || 0} reparos`;
    if (mStat) mStat.innerText = `${data.total_mesh_peers || 0} peers`;
}

function renderAgentsList(agents) {
    const container = document.getElementById('hermes-agents-list');
    if (!container) return;

    if (agents.length === 0) {
        container.innerHTML = `
            <div style="text-align:center;padding:24px;color:var(--text-muted);font-size:0.88em">
                <i class="fas fa-info-circle" style="font-size:1.4em;margin-bottom:8px;display:block"></i>
                Nenhum agente Hermes registrado no momento.
            </div>
        `;
        return;
    }

    let html = '<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));gap:16px">';
    agents.forEach(a => {
        html += `
            <div class="p2p-node-card">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
                    <span style="font-weight:700;font-size:0.95em;color:var(--text)"><i class="fas fa-desktop" style="color:var(--primary)"></i> ${a.hostname || a.agent_id}</span>
                    <span class="badge" style="background:rgba(16,185,129,0.15);color:var(--success);border:1px solid rgba(16,185,129,0.3)">Online</span>
                </div>
                <div style="font-size:0.8em;color:var(--text-muted);line-height:1.6">
                    • <strong>Fila Pendente</strong>: ${a.pending_messages || 0} mensagens<br>
                    • <strong>Burst Syncs</strong>: ${a.burst_sync_count || 0} sincronizações<br>
                    • <strong>IP LAN Mesh</strong>: ${a.ip_address || 'Localhost'}
                </div>
            </div>
        `;
    });
    html += '</div>';
    container.innerHTML = html;
}
