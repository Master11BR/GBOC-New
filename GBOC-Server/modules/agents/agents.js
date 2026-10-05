// Module: Agents Controller (agents.js)
document.addEventListener('DOMContentLoaded', () => {
    if (window.gbocTabHidden && window.gbocTabHidden('tab-agents')) return;   // painel: carrega ao abrir a aba
    loadAgentsList();
});

async function loadAgentsList() {
    const tbody = document.getElementById('agents-table-body');
    if (!tbody) return;
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/agents');
        if (!r.ok) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Nenhum agente cadastrado no momento.</td></tr>';
            return;
        }
        const data = await r.json();
        const list = Array.isArray(data) ? data : (data.agents || []);
        if (!list.length) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Nenhum agente cadastrado no momento.</td></tr>';
            return;
        }
        tbody.innerHTML = list.map(a => `
            <tr>
                <td style="font-weight:600">${a.hostname || a.agent_id}</td>
                <td>${a.ip_address || '—'}</td>
                <td>${a.os_info || 'Windows/Linux'}</td>
                <td><span class="badge badge-info">${(a.agent_version ? (a.agent_version.startsWith('v') ? a.agent_version : 'v' + a.agent_version) : 'v14.6.0')}</span></td>
                <td>${a.last_heartbeat || '—'}</td>
                <td><span class="badge ${a.status === 'online' ? 'badge-success' : 'badge-error'}">${(a.status || 'OFFLINE').toUpperCase()}</span></td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger)">Erro ao carregar agentes: ${e.message}</td></tr>`;
    }
}

// ── Pareamento de Agentes (chave Server <-> Agente) ─────────────────────────
async function gbocLoadPairingKey() {
    const input = document.getElementById('pairing-key');
    const status = document.getElementById('pairing-status');
    if (!input) return;
    try {
        const r = await fetch((window.GBOC_API_BASE || '') + '/api/v1/agents/pairing');
        const d = await r.json().catch(() => ({}));
        if (!r.ok) {
            input.value = '';
            if (status) status.textContent = r.status === 403
                ? 'Apenas administradores podem visualizar a chave de pareamento.'
                : ('Chave indisponível: ' + (d.detail || d.message || ('HTTP ' + r.status)));
            return;
        }
        input.value = d.pairing_key || '';
        if (status) status.textContent = d.managed_by_env
            ? 'Chave definida pela variável de ambiente GBOC_AGENT_PAIRING_KEY.'
            : 'Cabeçalho usado: ' + (d.header || 'X-GBOC-Agent-Key');
    } catch (e) {
        if (status) status.textContent = 'Falha ao carregar a chave: ' + e.message;
    }
}

function gbocTogglePairingKey() {
    const input = document.getElementById('pairing-key');
    if (input) input.type = input.type === 'password' ? 'text' : 'password';
}

async function gbocCopyPairingKey() {
    const input = document.getElementById('pairing-key');
    const status = document.getElementById('pairing-status');
    if (!input || !input.value) return;
    try {
        await navigator.clipboard.writeText(input.value);
        if (status) status.textContent = 'Chave copiada para a área de transferência.';
    } catch (e) {
        input.type = 'text'; input.select();
        if (status) status.textContent = 'Selecione e copie manualmente (Ctrl+C).';
    }
}

async function gbocRotatePairingKey() {
    if (!confirm('Gerar uma nova chave? Todos os agentes deixarão de sincronizar até receberem a nova chave.')) return;
    const status = document.getElementById('pairing-status');
    try {
        const r = await fetch((window.GBOC_API_BASE || '') + '/api/v1/agents/pairing/rotate', { method: 'POST' });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || d.message || ('HTTP ' + r.status));
        const input = document.getElementById('pairing-key');
        if (input) input.value = d.pairing_key || '';
        if (status) status.textContent = 'Nova chave gerada. Atualize-a em todos os agentes.';
    } catch (e) {
        if (status) status.textContent = 'Falha ao gerar nova chave: ' + e.message;
    }
}
