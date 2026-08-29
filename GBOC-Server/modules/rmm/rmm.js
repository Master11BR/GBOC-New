// GBOC System v13.2.0 Enterprise Edition
// Module: RMM & Remote Terminal JavaScript Module

async function populateRMMAgentSelect() {
    const sel = document.getElementById('rmm-agent-select');
    if(!sel) return;
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/agents');
        if(!r.ok) return;
        const data = await r.json();
        const agents = Array.isArray(data) ? data : (data.agents || []);
        const currentVal = sel.value;
        
        sel.innerHTML = '<option value="agente-local">🖥️ Servidor Central (Host Local) [ONLINE]</option>';
        agents.forEach(a => {
            const agentId = a.agent_id || a.id;
            if(agentId && agentId !== 'agente-local' && agentId !== 'servidor-central') {
                const host = a.hostname || agentId;
                const ip = a.ip_address ? ` (${a.ip_address})` : '';
                const isOnline = String(a.status || '').toLowerCase() === 'online';
                const statusBadge = isOnline ? '🟢 [ONLINE]' : '🔴 [OFFLINE]';
                
                const opt = document.createElement('option');
                opt.value = agentId;
                opt.textContent = `${statusBadge} ${host}${ip}`;
                opt.dataset.isOnline = isOnline ? 'true' : 'false';
                sel.appendChild(opt);
            }
        });
        if(currentVal) sel.value = currentVal;
    } catch(e) {
        console.warn('Erro ao carregar lista de agentes para RMM:', e);
    }
}

async function runRMMCommand() {
    const input = document.getElementById('rmm-cmd-input');
    const output = document.getElementById('rmm-terminal-output');
    const sel = document.getElementById('rmm-agent-select');
    const agentId = sel?.value || 'agente-local';
    const cmd = input.value.trim();
    if(!cmd) return;

    const opt = sel?.options[sel.selectedIndex];
    const isOffline = opt?.dataset?.isOnline === 'false';

    if (isOffline) {
        output.innerText += `\n\n❌ [BLOQUEIO RMM]: O agente '${agentId}' está OFFLINE. Não é possível enviar comandos ao terminal enquanto o sistema não estiver conectado.`;
        output.scrollTop = output.scrollHeight;
        return;
    }

    output.innerText += `\n\n> Executando no Agente [${agentId}]: ${cmd}\nAguardando resposta...`;
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/rmm/execute', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({agent_id: agentId, command: cmd, shell: 'powershell'})
        });
        const rawText = await r.text();
        let res;
        try { res = JSON.parse(rawText); } catch(_) { res = { message: rawText || `HTTP ${r.status}` }; }
        if (!r.ok) {
            output.innerText += `\n❌ [ERRO DE EXECUÇÃO]: ${res.output || res.message || 'Agente offline ou inacessível.'}`;
        } else {
            output.innerText += `\n${res.stdout || res.output || res.stderr || res.message || 'Comando concluído sem retorno.'}`;
        }
        output.scrollTop = output.scrollHeight;
    } catch(e) {
        output.innerText += `\n❌ [ERRO DE CONEXÃO RMM AGENTE]: ${e.message}`;
    }
}

async function loadRMMProcesses() {
    const agentId = document.getElementById('rmm-agent-select')?.value || 'agente-local';
    const tbody = document.getElementById('rmm-process-table');
    if(!tbody) return;
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center"><i class="fas fa-spinner fa-spin"></i> Carregando processos do agente [${agentId}]...</td></tr>`;
    try {
        const r = await fetch(window.GBOC_API_BASE + `/api/v1/rmm/processes?agent_id=${encodeURIComponent(agentId)}`);
        const rawText = await r.text();
        let d;
        try { d = JSON.parse(rawText); } catch(_) { d = {}; }
        
        if (!r.ok || d.status === 'error') {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger)">❌ Agente [${agentId}] está OFFLINE. Impossível listar processos.</td></tr>`;
            return;
        }

        const procs = d.processes || [];
        if(procs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Nenhum processo retornado pelo agente [${agentId}].</td></tr>`;
            return;
        }
        tbody.innerHTML = procs.map(p => `
            <tr>
                <td><strong>${p.pid}</strong></td>
                <td>${p.name}</td>
                <td><span class="badge badge-info">${p.cpu}%</span></td>
                <td><span class="badge badge-warning">${p.memory} MB</span></td>
                <td>${p.user || 'N/A'}</td>
                <td><button class="btn btn-danger" style="padding:2px 6px;font-size:0.75em" onclick="killRMMProcess(${p.pid})">Kill</button></td>
            </tr>
        `).join('');
    } catch(e) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger)">Erro: ${e.message}</td></tr>`;
    }
}

async function killRMMProcess(pid) {
    const agentId = document.getElementById('rmm-agent-select')?.value || 'agente-local';
    if(!confirm(`Confirma encerrar processo PID ${pid} no agente [${agentId}]?`)) return;
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/rmm/process/kill', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({agent_id: agentId, pid: pid})
        });
        const rawText = await r.text();
        let res;
        try { res = JSON.parse(rawText); } catch(_) { res = { message: rawText, status: 'error' }; }
        if (typeof showToast === 'function') {
            showToast(res.message || 'Solicitação enviada', res.status === 'success' ? 'success' : 'error');
        }
        loadRMMProcesses();
    } catch(e) {
        if (typeof showToast === 'function') {
            showToast(`Erro ao matar processo: ${e.message}`, 'error');
        }
    }
}

async function toggleRMMIsolation() {
    const agentId = document.getElementById('rmm-agent-select')?.value || 'agente-local';
    if(!confirm(`⚠️ APOSTA DE SEGURANÇA: Deseja ativar o ISOLAMENTO DE REDE de emergência do agente [${agentId}]?`)) return;
    try {
        const r = await fetch(window.GBOC_API_BASE + `/api/v1/rmm/proxy/${encodeURIComponent(agentId)}/api/v1/rmm/isolation`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({enable: true})
        });
        const rawText = await r.text();
        let res;
        try { res = JSON.parse(rawText); } catch(_) { res = { message: rawText }; }
        if (typeof showToast === 'function') {
            showToast(res.message || `Isolamento de Rede Solicitado para ${agentId}`, "warning");
        }
    } catch(e) {
        if (typeof showToast === 'function') {
            showToast(`Falha ao isolar rede: ${e.message}`, "error");
        }
    }
}
