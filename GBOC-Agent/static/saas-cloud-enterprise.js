/**
 * GBOC System v14.1.0 Enterprise Edition
 * Module: SaaS, Kubernetes, Storage Arrays, Cleanroom, Cloud Failover & ITIL Controller
 * Copyright (c) 2026 Master11BR - Todos os direitos reservados.
 * Zero-Mock: 100% de integração com APIs reais e dados do sistema host.
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
        const m365Badge = document.getElementById('m365-badge-status');
        const m365Details = document.getElementById('m365-details');

        const gwsEl = document.getElementById('gws-domain-name');
        const gwsBadge = document.getElementById('gws-badge-status');
        const gwsDetails = document.getElementById('gws-details');

        if (m365El) m365El.textContent = m365.tenant_name || 'Não Configurado';
        if (m365Badge) {
            if (m365.connected) {
                m365Badge.className = 'badge badge-success';
                m365Badge.innerHTML = '<i class="fas fa-check-circle"></i> Conectado (Graph API)';
            } else {
                m365Badge.className = 'badge badge-warning';
                m365Badge.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Não Conectado';
            }
        }
        if (m365Details && m365.message) {
            m365Details.textContent = m365.message;
        }

        if (gwsEl) gwsEl.textContent = gws.domain || 'Não Configurado';
        if (gwsBadge) {
            if (gws.connected) {
                gwsBadge.className = 'badge badge-success';
                gwsBadge.innerHTML = '<i class="fas fa-check-circle"></i> Conectado (Google API)';
            } else {
                gwsBadge.className = 'badge badge-warning';
                gwsBadge.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Não Conectado';
            }
        }
        if (gwsDetails && gws.message) {
            gwsDetails.textContent = gws.message;
        }
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
        if (data.status === 'error') {
            alert(`⚠️ ${data.error || data.message}`);
            return;
        }
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

        if (clusterEl) {
            if (k8s.available) {
                clusterEl.textContent = `${k8s.cluster_name} (${k8s.server_version})`;
            } else {
                clusterEl.textContent = 'kubectl não disponível no host';
                clusterEl.className = 'badge badge-warning';
            }
        }

        if (nsSelect) {
            if (Array.isArray(k8s.namespaces) && k8s.namespaces.length > 0) {
                nsSelect.innerHTML = k8s.namespaces.map(ns => `
                    <option value="${ns.name}">${ns.name}</option>
                `).join('');
            } else {
                nsSelect.innerHTML = '<option value="" disabled selected>Nenhum namespace detectado</option>';
            }
        }
    } catch (e) {
        console.error('Erro ao carregar inventário K8s:', e);
    }
}

async function startK8sBackupAction() {
    const ns = document.getElementById('k8s-namespace-select')?.value;
    const pvcs = document.getElementById('k8s-include-pvcs')?.checked !== false;

    if (!ns) {
        alert('Selecione ou informe um namespace Kubernetes válido.');
        return;
    }

    try {
        const res = await fetch('/api/v1/saas-cloud/k8s/backup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ namespace: ns, include_pvcs: pvcs })
        });
        const data = await res.json();
        if (data.status === 'error') {
            alert(`⚠️ ${data.error}`);
            return;
        }
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
            if (arrays.length === 0) {
                listEl.innerHTML = '<div style="color:var(--text-muted); font-size:0.85em; padding:12px;">Nenhum array de storage SAN/NAS configurado no host. Cadastre storage_arrays.json para integrar NetApp, Pure, Dell ou HPE.</div>';
            } else {
                listEl.innerHTML = arrays.map(arr => `
                    <div style="background:var(--bg-input); padding:14px; border-radius:8px; border:1px solid var(--border); margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
                        <div>
                            <strong style="color:var(--text);"><i class="fas fa-server" style="color:var(--primary); margin-right:8px;"></i> ${arr.name}</strong>
                            <div style="font-size:0.78em; color:var(--text-muted); margin-top:2px;">IP: ${arr.ip} • Protocolo: ${arr.protocol}</div>
                        </div>
                        <button class="btn btn-sm btn-primary" onclick="triggerHardwareSnapAction('${arr.id}')">
                            <i class="fas fa-camera"></i> Snapshot Hardware
                        </button>
                    </div>
                `).join('');
            }
        }
    } catch (e) {
        console.error('Erro ao carregar storage arrays:', e);
    }
}

async function triggerHardwareSnapAction(arrayId) {
    const vol = prompt('Informe o nome do volume ou LUN no storage:');
    if (!vol) return;

    try {
        const res = await fetch('/api/v1/saas-cloud/storage-arrays/snapshot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ array_id: arrayId, volume_or_lun: vol })
        });
        const data = await res.json();
        if (data.success) {
            alert(`🎉 Snapshot de hardware criado com sucesso!`);
        } else {
            alert(`Aviso: ${data.error}`);
        }
    } catch (e) {
        alert('Erro no snapshot de storage: ' + e.message);
    }
}

// ── 4. Cyber Cleanroom & Shannon Entropy ───────────────────────────────────
async function runCleanroomScanAction() {
    const snapId = document.getElementById('cleanroom-snap-input')?.value?.trim();
    const consoleEl = document.getElementById('cleanroom-scan-console');

    if (!snapId) {
        alert('Informe o ID do Snapshot ou o caminho físico do arquivo para varredura forense.');
        return;
    }

    if (consoleEl) consoleEl.textContent = `Iniciando varredura forense real de Entropia de Shannon em: ${snapId}...`;

    try {
        const res = await fetch('/api/v1/saas-cloud/cleanroom/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ snapshot_id: snapId })
        });
        const data = await res.json();
        if (consoleEl && Array.isArray(data.logs)) {
            consoleEl.textContent = data.logs.join('\n');
        } else if (consoleEl) {
            consoleEl.textContent = data.error || 'Varredura finalizada.';
        }
    } catch (e) {
        if (consoleEl) consoleEl.textContent = 'Erro na varredura: ' + e.message;
    }
}

// ── 5. Multi-Cloud Direct Failover ─────────────────────────────────────────
async function launchCloudFailoverAction(provider) {
    const imgPath = prompt(`Informe o caminho da imagem VHDX para failover na ${provider.toUpperCase()}:`);
    if (!imgPath) return;

    if (!confirm(`Confirmar inicialização de procedimento de Failover para ${provider.toUpperCase()} a partir de:\n${imgPath}?`)) return;

    try {
        const res = await fetch('/api/v1/saas-cloud/cloud-failover/launch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: provider, backup_image_path: imgPath })
        });
        const data = await res.json();
        if (data.success) {
            alert(`🎉 Procedimento concluído!\n${data.logs.join('\n')}`);
        } else {
            alert(`Aviso de pré-requisito:\n${data.error || (data.logs ? data.logs.join('\n') : 'Falha desconhecida')}`);
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

        if (snowEl) {
            if (itil.servicenow?.configured) {
                snowEl.innerHTML = '<span class="badge badge-success"><i class="fas fa-check-circle"></i> Conectado</span>';
            } else {
                snowEl.innerHTML = '<span class="badge badge-warning"><i class="fas fa-info-circle"></i> Não Configurado</span>';
            }
        }

        if (jiraEl) {
            if (itil.jira_service_management?.configured) {
                jiraEl.innerHTML = '<span class="badge badge-success"><i class="fas fa-check-circle"></i> Conectado</span>';
            } else {
                jiraEl.innerHTML = '<span class="badge badge-warning"><i class="fas fa-info-circle"></i> Não Configurado</span>';
            }
        }
    } catch (e) {
        console.error('Erro no status ITIL:', e);
    }
}

async function testItilWebhookAction(systemType) {
    try {
        const res = await fetch('/api/v1/saas-cloud/itil/test-incident', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ system_type: systemType })
        });
        const data = await res.json();
        if (data.success) {
            alert(`✅ Webhook enviado com sucesso para ${systemType}!`);
        } else {
            alert(`Aviso: ${data.error}`);
        }
    } catch (e) {
        alert('Erro ao disparar webhook: ' + e.message);
    }
}

// ── Modal de Monitoramento ──────────────────────────────────────────────────
function openSaasMonitorModal(jobId, title) {
    const modal = document.getElementById('saas-monitor-modal');
    const titleEl = document.getElementById('saas-modal-title');
    const logsEl = document.getElementById('saas-live-logs');

    if (titleEl) titleEl.innerHTML = `<i class="fas fa-spinner fa-spin" style="color:var(--primary)"></i> ${title}`;
    if (logsEl) logsEl.textContent = 'Iniciando sincronização e coleta de telemetria...';
    if (modal) modal.style.display = 'block';

    if (_activeSaasPolling) {
        if (_activeSaasPolling.stop) _activeSaasPolling.stop();
        else clearInterval(_activeSaasPolling);
        _activeSaasPolling = null;
    }
    if (window.gbocPerf?.smartInterval) {
        _activeSaasPolling = window.gbocPerf.smartInterval(() => pollJobStatus(jobId), 1500);
    } else {
        _activeSaasPolling = setInterval(() => pollJobStatus(jobId), 1500);
    }
}

function closeSaasMonitorModal() {
    const modal = document.getElementById('saas-monitor-modal');
    if (modal) modal.style.display = 'none';
    if (_activeSaasPolling) {
        if (_activeSaasPolling.stop) _activeSaasPolling.stop();
        else clearInterval(_activeSaasPolling);
        _activeSaasPolling = null;
    }
}

async function pollJobStatus(jobId) {
    const endpoint = jobId.startsWith('saas') ? `/api/v1/saas-cloud/saas/status/${jobId}` : `/api/v1/saas-cloud/k8s/status/${jobId}`;
    try {
        const res = await fetch(endpoint);
        if (!res.ok) return;
        const data = await res.json();
        const job = data.job;

        const fill = document.getElementById('saas-modal-progress-fill');
        const pct = document.getElementById('saas-modal-progress-pct');
        const logsEl = document.getElementById('saas-live-logs');

        if (job && fill && pct) {
            fill.style.width = `${job.progress || 0}%`;
            pct.textContent = `${job.progress || 0}%`;
        }

        if (job && logsEl && Array.isArray(job.logs)) {
            const formatted = job.logs.map(l => typeof l === 'object' ? `[${l.timestamp?.slice(11, 19)}] ${l.message}` : l).join('\n');
            logsEl.textContent = formatted || 'Processando dados...';
            logsEl.scrollTop = logsEl.scrollHeight;
        }

        if (job && (job.status === 'completed' || job.status === 'failed')) {
            if (_activeSaasPolling) {
                if (_activeSaasPolling.stop) _activeSaasPolling.stop();
                else clearInterval(_activeSaasPolling);
                _activeSaasPolling = null;
            }
            const titleEl = document.getElementById('saas-modal-title');
            if (titleEl) {
                titleEl.innerHTML = job.status === 'completed' ?
                    '<i class="fas fa-check-circle" style="color:var(--success)"></i> Operação Concluída' :
                    '<i class="fas fa-times-circle" style="color:var(--danger)"></i> Operação Falhou';
            }
        }
    } catch (e) {
        console.error('Erro ao consultar job:', e);
    }
}
