// ==============================================================================
// GBOC System v14.0.0 Enterprise Edition
// Module: Ransomware Guardian Controller (ransomware.js)
// ==============================================================================

document.addEventListener('DOMContentLoaded', () => {
    loadServerRansomwareData();
});

async function syncRansomwareCentral() {
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/server/ransomware/sync', { method: 'POST' });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || d.message || `HTTP ${r.status}`);
        await loadServerRansomwareData();
    } catch (e) {
        console.error('syncRansomwareCentral error:', e);
    }
}

async function runGuardianAIDiagnostic() {
    const summaryEl = document.getElementById('rw-ai-summary');
    if (summaryEl) summaryEl.textContent = 'Executando diagnóstico IA híbrido...';
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/server/ransomware/preemptive_diag', { method: 'POST' });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || d.message || `HTTP ${r.status}`);

        const health = d.global_health_score ?? 0;
        const status = d.overall_status || 'UNKNOWN';
        const nodes = d.nodes_scanned || 0;
        const text = d.ai_executive_summary || 'Diagnóstico concluído.';

        if (summaryEl) {
            summaryEl.textContent = `Status: ${status} | Saúde: ${health}% | Nós analisados: ${nodes}. ${text}`;
        }
    } catch (e) {
        console.error('runGuardianAIDiagnostic error:', e);
        if (summaryEl) summaryEl.textContent = `Falha no diagnóstico IA: ${String(e.message || e)}`;
    }
}

async function loadCentralStats() {
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/server/ransomware/central_stats?limit=50');
        if (!r.ok) return;
        const d = await r.json();
        if (document.getElementById('rw-kpi-central-events')) {
            document.getElementById('rw-kpi-central-events').textContent = d.total_events || 0;
        }
        if (document.getElementById('rw-kpi-central-incidents')) {
            document.getElementById('rw-kpi-central-incidents').textContent = d.total_incidents || 0;
        }
    } catch (e) {
        console.error('loadCentralStats error:', e);
    }
}

async function loadServerRansomwareData() {
    const tbody = document.getElementById('rw-agents-table');
    const eventsTbody = document.getElementById('rw-events-table');

    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/server/ransomware/overview');
        if (!r.ok) return;
        const d = await r.json();

        if (document.getElementById('rw-status-label')) document.getElementById('rw-status-label').textContent = d.status_label || 'SENTINEL ACTIVE';
        if (document.getElementById('rw-kpi-protected')) document.getElementById('rw-kpi-protected').textContent = `${d.protected_agents || 0} / ${d.total_agents || 0}`;
        if (document.getElementById('rw-kpi-canaries')) document.getElementById('rw-kpi-canaries').textContent = d.total_canaries || 0;
        if (document.getElementById('rw-kpi-compromised')) document.getElementById('rw-kpi-compromised').textContent = d.total_compromised || 0;
        if (document.getElementById('rw-kpi-worm')) document.getElementById('rw-kpi-worm').textContent = d.worm_storage_locked ? 'ATIVO (WORM)' : 'DESATIVADO';

        const agents = d.agents || [];
        if (tbody) {
            if (!agents.length) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">Nenhum agente registrado no momento.</td></tr>';
            } else {
                tbody.innerHTML = agents.map(a => `
                    <tr>
                        <td style="font-weight:600">${a.hostname}</td>
                        <td>${a.ip_address}</td>
                        <td><span class="badge ${a.is_protected ? 'badge-success' : 'badge-error'}">${a.is_protected ? 'PROTEGIDO' : 'EXPOSTO'}</span></td>
                        <td><strong style="color:var(--primary)">${a.canaries || 0}</strong></td>
                        <td style="color:${a.compromised > 0 ? 'var(--danger)' : 'inherit'};font-weight:${a.compromised > 0 ? '700' : 'normal'}">${a.compromised || 0}</td>
                        <td><span class="badge badge-info">${(a.threat_level || 'LOW').toUpperCase()}</span></td>
                        <td style="font-size:0.82em;color:var(--text-muted)">${a.last_scan || 'Hoje'}</td>
                    </tr>
                `).join('');
            }
        }
    } catch (e) {
        console.error('loadServerRansomwareData error:', e);
    }

    // Load Events
    try {
        const r2 = await fetch(window.GBOC_API_BASE + '/api/v1/server/ransomware/events');
        if (!r2.ok) return;
        const d2 = await r2.json();
        const events = d2.events || [];

        if (eventsTbody) {
            if (!events.length) {
                eventsTbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">Nenhum evento ou alarme de ransomware registrado. Sistema 100% íntegro.</td></tr>';
            } else {
                eventsTbody.innerHTML = events.map(ev => `
                    <tr>
                        <td>#${ev.id}</td>
                        <td><span class="badge badge-warning">${ev.event_type}</span></td>
                        <td style="font-weight:600">${ev.agent_hostname}</td>
                        <td>${ev.message}</td>
                        <td style="font-size:0.82em;color:var(--text-muted)">${ev.timestamp}</td>
                    </tr>
                `).join('');
            }
        }
    } catch (e) {
        console.error('loadRansomwareEvents error:', e);
    }
    
    // Load Local Protection Status
    await loadLocalProtection();
    await loadCentralStats();
}

async function loadLocalProtection() {
    const avName = document.getElementById('av-name');
    const avText = document.getElementById('av-status-text');
    const avIcon = document.getElementById('av-icon');
    const card = document.getElementById('local-protection-card');
    const tbody = document.getElementById('local-events-table');

    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/server/ransomware/local_protection');
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();

        if (avName) {
            if (data.av_installed) {
                avName.innerText = data.av_name || 'Antivírus / EDR detectado';
                if (data.av_active) {
                    avText.innerText = "Proteção local ATIVA e operante.";
                    avIcon.className = "fas fa-check-circle";
                    avIcon.style.color = "var(--success)";
                    card.style.borderLeft = "4px solid var(--success)";
                } else {
                    avText.innerText = "Proteção local instalada, mas INATIVA.";
                    avIcon.className = "fas fa-exclamation-triangle";
                    avIcon.style.color = "var(--warning)";
                    card.style.borderLeft = "4px solid var(--warning)";
                }
            } else {
                avName.innerText = data.av_name || "Nenhum Antivírus / EDR detectado";
                avText.innerText = "O host está VULNERÁVEL.";
                avIcon.className = "fas fa-times-circle";
                avIcon.style.color = "var(--danger)";
                card.style.borderLeft = "4px solid var(--danger)";
                card.style.backgroundColor = "rgba(240,107,107,0.05)";
            }
        }

        if (tbody) {
            if (data.recent_security_events && data.recent_security_events.length > 0) {
                tbody.innerHTML = data.recent_security_events.map(ev => {
                    return `<tr>
                        <td style="white-space:nowrap">${ev.time ? new Date(ev.time).toLocaleString() : '—'}</td>
                        <td><span class="badge badge-warning">${ev.id ?? '—'}</span></td>
                        <td>${ev.message || '—'}</td>
                    </tr>`;
                }).join('');
            } else {
                tbody.innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--text-muted)">Nenhum evento de segurança recente encontrado no host local.</td></tr>`;
            }
        }
    } catch(e) {
        console.error("Falha ao carregar proteção local:", e);
        if (avName) avName.innerText = "Validação local indisponível";
        if (avText) avText.innerText = "Não foi possível consultar o status real do antivírus/EDR.";
        if (avIcon) {
            avIcon.className = "fas fa-exclamation-circle";
            avIcon.style.color = "var(--warning)";
        }
        if (card) {
            card.style.borderLeft = "4px solid var(--warning)";
            card.style.backgroundColor = "rgba(240,169,64,0.05)";
        }
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--warning)">Falha ao validar proteção local: ${String(e.message || e)}</td></tr>`;
        }
    }
}
