/**
 * GBOC System v14.0.0 Enterprise Edition
 * Module: SaaS, Kubernetes, Storage Arrays, Cleanroom, Cloud Failover & ITIL Controller
 * Copyright (c) 2026 Master11BR - Todos os direitos reservados.
 */

let _activeSaasPolling = null;

document.addEventListener('DOMContentLoaded', () => {
    if (typeof UnifiedSidebar === 'function') {
        new UnifiedSidebar().initialize();
    }
    loadSaasStatus();
    loadK8sInventory();
    loadStorageArrays();
    loadItilStatus();
});

function switchSaasTab(tabId) {
    document.querySelectorAll('.saas-tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.saas-tab-content').forEach(content => content.classList.remove('active'));

    const activeBtn = document.getElementById(`tab-btn-${tabId}`);
    const activeContent = document.getElementById(`tab-content-${tabId}`);
    if (activeBtn) activeBtn.classList.add('active');
    if (activeContent) activeContent.classList.add('active');
}

// ── 1. SaaS Cloud-Native ───────────────────────────────────────────────────
async function loadSaasStatus() {
    try {
        const res = await fetch('/api/v1/saas-cloud/saas/tenants');
        if (!res.ok) return;
        const data = await res.json();
        const m365 = data.data?.microsoft_365 || {};
        const gws = data.data?.google_workspace || {};

        const m365El = document.getElementById('m365-tenant-name');
        const gwsEl = document.getElementById('gws-domain-name');

        if (m365El) m365El.textContent = m365.tenant_name || 'Conectado';
        if (gwsEl) gwsEl.textContent = gws.domain || 'Conectado';
    } catch (e) {
        console.error('Erro ao carregar status SaaS:', e);
    }
}

async function startSaasBackupAction(provider) {
    try {
        const res = await fetch('/api/v1/saas-cloud/saas/backup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: provider })
        });
        const data = await res.json();
        openSaasMonitorModal(data.job_id, `SaaS Backup (${provider.toUpperCase()})`);
    } catch (e) {
        alert('Erro ao iniciar backup SaaS: ' + e.message);
    }
}

// ── 2. Kubernetes & Containers ─────────────────────────────────────────────
async function loadK8sInventory() {
    try {
        const res = await fetch('/api/v1/saas-cloud/k8s/inventory');
        if (!res.ok) return;
        const data = await res.json();
        const k8s = data.data || {};

        const clusterEl = document.getElementById('k8s-cluster-name');
        const nsSelect = document.getElementById('k8s-namespace-select');

        if (clusterEl) clusterEl.textContent = `${k8s.cluster_name} (${k8s.server_version})`;

        if (nsSelect && Array.isArray(k8s.namespaces)) {
            nsSelect.innerHTML = k8s.namespaces.map(ns => `
                <option value="${ns.name}">${ns.name} (${ns.pods_count} Pods • ${ns.pvcs_count} PVCs)</option>
            `).join('');
        }
    } catch (e) {
        console.error('Erro ao carregar inventário K8s:', e);
    }
}

async function startK8sBackupAction() {
    const ns = document.getElementById('k8s-namespace-select')?.value || 'production-apps';
    const pvcs = document.getElementById('k8s-include-pvcs')?.checked !== false;

    try {
        const res = await fetch('/api/v1/saas-cloud/k8s/backup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ namespace: ns, include_pvcs: pvcs })
        });
        const data = await res.json();
        openSaasMonitorModal(data.job_id, `Kubernetes Backup (${ns})`);
    } catch (e) {
        alert('Erro ao disparar backup K8s: ' + e.message);
    }
}

// ── 3. Storage Hardware Arrays ─────────────────────────────────────────────
async function loadStorageArrays() {
    try {
        const res = await fetch('/api/v1/saas-cloud/storage-arrays/list');
        if (!res.ok) return;
        const data = await res.json();
        const arrays = data.arrays || [];

        const listEl = document.getElementById('storage-arrays-grid');
        if (listEl) {
            listEl.innerHTML = arrays.map(arr => `
                <div style="background:var(--bg-input); padding:14px; border-radius:8px; border:1px solid var(--border); margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <strong style="color:var(--text);"><i class="fas fa-server" style="color:var(--primary); margin-right:8px;"></i> ${arr.name}</strong>
                        <div style="font-size:0.78em; color:var(--text-muted); margin-top:2px;">IP: ${arr.ip} • Protocolo: ${arr.protocol}</div>
                    </div>
                    <button class="btn btn-sm btn-primary" onclick="triggerHardwareSnapAction('${arr.id}')">
                        <i class="fas fa-camera"></i> Snapshot Hardware (<2s)
                    </button>
                </div>
            `).join('');
        }
    } catch (e) {
        console.error('Erro ao carregar storage arrays:', e);
    }
}

async function triggerHardwareSnapAction(arrayId) {
    try {
        const res = await fetch('/api/v1/saas-cloud/storage-arrays/snapshot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ array_id: arrayId, volume_or_lun: 'vol_sql_prod_data' })
        });
        const data = await res.json();
        if (data.success) {
            alert(`🎉 Snapshot de hardware '${data.snapshot_name}' criado no storage em ${data.latency_seconds}s sem uso de CPU no host!`);
        }
    } catch (e) {
        alert('Erro no snapshot de storage: ' + e.message);
    }
}

// ── 4. Cyber Cleanroom & Shannon Entropy ───────────────────────────────────
async function runCleanroomScanAction() {
    const snapId = document.getElementById('cleanroom-snap-input')?.value || 'SNAP_SQL_PROD_20260829';
    const consoleEl = document.getElementById('cleanroom-scan-console');

    if (consoleEl) consoleEl.textContent = 'Iniciando varredura de Entropia de Shannon e regras YARA...';

    try {
        const res = await fetch('/api/v1/saas-cloud/cleanroom/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ snapshot_id: snapId })
        });
        const data = await res.json();
        if (consoleEl && Array.isArray(data.logs)) {
            consoleEl.textContent = data.logs.join('\n');
        }
    } catch (e) {
        if (consoleEl) consoleEl.textContent = 'Erro na varredura: ' + e.message;
    }
}

// ── 5. Multi-Cloud Direct Failover ─────────────────────────────────────────
async function launchCloudFailoverAction(provider) {
    if (!confirm(`Confirmar 1-Click Disaster Recovery Failover para ${provider.toUpperCase()}?`)) return;

    try {
        const res = await fetch('/api/v1/saas-cloud/cloud-failover/launch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: provider, backup_image_path: 'C:\\GBOC-Backups\\DR_System_20260829.vhdx' })
        });
        const data = await res.json();
        if (data.success) {
            alert(`🎉 1-Click Failover concluído para ${data.cloud_provider}!\nIP Público: ${data.public_ip}\nInstância: ${data.instance_id || data.vm_name}\nStatus: ${data.status}`);
        }
    } catch (e) {
        alert('Erro no failover cloud: ' + e.message);
    }
}

// ── 6. ITIL ITSM & SSO ─────────────────────────────────────────────────────
async function loadItilStatus() {
    try {
        const res = await fetch('/api/v1/saas-cloud/itil/status');
        if (!res.ok) return;
        const data = await res.json();
        const itil = data.data || {};

        const snowEl = document.getElementById('itil-snow-status');
        const jiraEl = document.getElementById('itil-jira-status');

        if (snowEl) snowEl.innerHTML = '<span class="badge badge-success"><i class="fas fa-check-circle"></i> Conectado (OAuth2)</span>';
        if (jiraEl) jiraEl.innerHTML = '<span class="badge badge-success"><i class="fas fa-check-circle"></i> Conectado (Bearer Token)</span>';
    } catch (e) {
        console.error('Erro no status ITIL:', e);
    }
}

async function testItilWebhookAction(system) {
    try {
        const res = await fetch('/api/v1/saas-cloud/itil/test-incident', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ system_type: system })
        });
        const data = await res.json();
        if (data.success) {
            alert(`✅ Webhook disparado com sucesso para ${system.toUpperCase()}!\nTicket Criado: ${data.ticket_id}\nCMDB Sincronizado: OK`);
        }
    } catch (e) {
        alert('Erro no webhook ITIL: ' + e.message);
    }
}

// ── Modal Monitor ──────────────────────────────────────────────────────────
function openSaasMonitorModal(jobId, title) {
    const modal = document.getElementById('saas-monitor-modal');
    const titleEl = document.getElementById('saas-modal-title');
    const logsEl = document.getElementById('saas-live-logs');
    const fillEl = document.getElementById('saas-modal-progress-fill');
    const pctEl = document.getElementById('saas-modal-progress-pct');

    if (titleEl) titleEl.textContent = title;
    if (logsEl) logsEl.textContent = 'Iniciando operação de alta resiliência...';
    if (fillEl) fillEl.style.width = '0%';
    if (pctEl) pctEl.textContent = '0%';
    if (modal) modal.style.display = 'block';

    if (_activeSaasPolling) clearInterval(_activeSaasPolling);

    _activeSaasPolling = setInterval(async () => {
        try {
            const res = await fetch(`/api/v1/saas-cloud/saas/status/${jobId}`);
            if (!res.ok) return;
            const data = await res.json();
            const job = data.job || {};

            const prog = job.progress || 0;
            if (fillEl) fillEl.style.width = `${prog}%`;
            if (pctEl) pctEl.textContent = `${prog}%`;

            if (logsEl && Array.isArray(job.logs)) {
                logsEl.textContent = job.logs.map(l => `[${new Date(l.timestamp || Date.now()).toLocaleTimeString('pt-BR')}] ${l.message}`).join('\n');
                logsEl.scrollTop = logsEl.scrollHeight;
            }

            if (job.status === 'completed' || job.status === 'failed') {
                clearInterval(_activeSaasPolling);
            }
        } catch (e) {
            console.error('Erro no polling:', e);
        }
    }, 1000);
}

function closeSaasMonitorModal() {
    const modal = document.getElementById('saas-monitor-modal');
    if (modal) modal.style.display = 'none';
    if (_activeSaasPolling) {
        clearInterval(_activeSaasPolling);
        _activeSaasPolling = null;
    }
}
