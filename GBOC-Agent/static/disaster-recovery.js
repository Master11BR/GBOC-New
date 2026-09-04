/**
 * GBOC System v14.0.0 Enterprise Edition
 * Module: Disaster Recovery, P2V, Universal Restore & AD Explorer Controller
 * Copyright (c) 2026 Master11BR - Todos os direitos reservados.
 */

let _activeDrPolling = null;
let _currentJobId = null;

document.addEventListener('DOMContentLoaded', () => {
    if (typeof UnifiedSidebar === 'function') {
        new UnifiedSidebar().initialize();
    }
    loadDisasterRecoveryOverview();
    loadPhysicalDisks();
    loadDrReadiness();
    loadInstantVmsList();
});

function switchDrTab(tabId) {
    document.querySelectorAll('.dr-tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.dr-tab-content').forEach(content => content.classList.remove('active'));

    const activeBtn = document.getElementById(`tab-btn-${tabId}`);
    const activeContent = document.getElementById(`tab-content-${tabId}`);
    if (activeBtn) activeBtn.classList.add('active');
    if (activeContent) activeContent.classList.add('active');

    if (tabId === 'adexplorer') {
        searchAdObjects();
    } else if (tabId === 'instantvm') {
        loadInstantVmsList();
    }
}

// ── Overview & System State ──────────────────────────────────────────────────
async function loadDisasterRecoveryOverview() {
    try {
        const res = await fetch('/api/v1/dr/system-info');
        if (!res.ok) throw new Error('Falha ao carregar informações de DR do sistema');
        const data = await res.json();
        const info = data.data || {};

        // DC / Active Directory status
        const adBadge = document.getElementById('ad-status-badge');
        const adDetails = document.getElementById('ad-details-text');
        if (adBadge && adDetails) {
            if (info.is_domain_controller) {
                adBadge.className = 'badge badge-success';
                adBadge.innerHTML = '<i class="fas fa-shield-alt"></i> Controlador de Domínio (AD DS Ativo)';
                adDetails.innerHTML = `Domínio: <strong>${info.domain_name || 'Desconhecido'}</strong> • Base NTDS.dit & SYSVOL consistentes via VSS.`;
            } else {
                adBadge.className = 'badge badge-info';
                adBadge.innerHTML = '<i class="fas fa-server"></i> Servidor Membro / Standalone';
                adDetails.innerHTML = `Host: <strong>${info.hostname}</strong> • System State padrão (Registry SAM/SYSTEM + BCD).`;
            }
        }

        // VSS Writers status
        const vssCountEl = document.getElementById('vss-writers-count');
        const vssStatusEl = document.getElementById('vss-status-badge');
        if (vssCountEl && vssStatusEl) {
            vssCountEl.textContent = `${info.vss_writer_count || 0} Writers`;
            if (info.vss_healthy) {
                vssStatusEl.className = 'badge badge-success';
                vssStatusEl.innerHTML = '<i class="fas fa-check-circle"></i> VSS 100% Estável';
            } else {
                vssStatusEl.className = 'badge badge-warning';
                vssStatusEl.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Atenção em Writers VSS';
            }
        }

        // Renderizar lista de VSS Writers
        const writersList = document.getElementById('vss-writers-list');
        if (writersList && Array.isArray(info.vss_writers)) {
            writersList.innerHTML = info.vss_writers.slice(0, 8).map(w => `
                <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid var(--border); font-size:0.82em;">
                    <span style="color:var(--text); font-weight:600;"><i class="fas fa-cube" style="color:var(--primary); margin-right:6px;"></i> ${w.name}</span>
                    <span style="color:var(--success); font-family:monospace;">${w.state || 'Stable'}</span>
                </div>
            `).join('');
        }
    } catch (e) {
        console.error('Erro ao consultar visão geral de DR:', e);
    }
}

// ── Discos Físicos Reais ────────────────────────────────────────────────────
async function loadPhysicalDisks() {
    const select = document.getElementById('p2v-source-disk');
    if (!select) return;

    try {
        select.innerHTML = '<option value="">Carregando discos físicos reais do host...</option>';
        const res = await fetch('/api/v1/dr/disks');
        if (!res.ok) throw new Error('Falha ao obter discos');
        const data = await res.json();
        const disks = data.disks || [];

        if (!disks.length) {
            select.innerHTML = '<option value="">Nenhum disco detectado</option>';
            return;
        }

        select.innerHTML = disks.map(d => {
            const driveLettersStr = d.drive_letters && d.drive_letters.length ? `[${d.drive_letters.join(', ')}] ` : '';
            const sysTag = d.is_system_disk ? ' ★ (DISCO DO SISTEMA OPERACIONAL)' : '';
            return `<option value="${d.disk_number}">Disco ${d.disk_number}: ${d.name} ${driveLettersStr}- ${d.size_gb} GB (${d.partition_style})${sysTag}</option>`;
        }).join('');

        const sysDisk = disks.find(d => d.is_system_disk);
        if (sysDisk) select.value = sysDisk.disk_number;
    } catch (e) {
        console.error('Erro ao listar discos:', e);
        select.innerHTML = '<option value="0">Disco 0 (C:\\ Sistema)</option>';
    }
}

// ── DR Readiness Score ───────────────────────────────────────────────────────
async function loadDrReadiness() {
    try {
        const res = await fetch('/api/v1/dr/readiness');
        if (!res.ok) return;
        const data = await res.json();
        const r = data.readiness || {};

        const scoreEl = document.getElementById('dr-score-val');
        const scoreFill = document.getElementById('dr-score-fill');
        const checklistEl = document.getElementById('dr-checklist-items');

        if (scoreEl) scoreEl.textContent = `${r.score || 0}%`;
        if (scoreFill) scoreFill.style.width = `${r.score || 0}%`;

        if (checklistEl && Array.isArray(r.checks)) {
            checklistEl.innerHTML = r.checks.map(c => `
                <div style="display:flex; align-items:flex-start; gap:10px; padding:10px; background:var(--bg-input); border-radius:8px; border:1px solid var(--border);">
                    <div style="font-size:1.1em; color:${c.status === 'PASSED' ? 'var(--success)' : (c.status === 'WARNING' ? 'var(--warning)' : 'var(--primary)')}">
                        <i class="${c.status === 'PASSED' ? 'fas fa-check-circle' : 'fas fa-info-circle'}"></i>
                    </div>
                    <div style="flex:1;">
                        <div style="font-weight:700; font-size:0.88em; color:var(--text);">${c.name}</div>
                        <div style="font-size:0.78em; color:var(--text-muted); margin-top:2px;">${c.detail}</div>
                    </div>
                    <span class="badge badge-${c.status === 'PASSED' ? 'success' : (c.status === 'WARNING' ? 'warning' : 'info')}" style="font-size:0.7em;">
                        ${c.status}
                    </span>
                </div>
            `).join('');
        }
    } catch (e) {
        console.error('Erro ao consultar DR readiness:', e);
    }
}

// ── P2V, System State, Boot Media ───────────────────────────────────────────
async function startP2VConversion() {
    const diskNum = parseInt(document.getElementById('p2v-source-disk')?.value || '0');
    const targetPath = document.getElementById('p2v-target-path')?.value.trim() || 'C:\\GBOC-DR\\Server_P2V_Clone.vhdx';
    const formatType = document.getElementById('p2v-format-type')?.value || 'VHDX';
    const isDynamic = document.getElementById('p2v-is-dynamic')?.checked !== false;

    try {
        const res = await fetch('/api/v1/dr/p2v/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                disk_number: diskNum,
                target_path: targetPath,
                format_type: formatType,
                is_dynamic: isDynamic
            })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || err.message || 'Falha ao iniciar P2V');
        }

        const data = await res.json();
        _currentJobId = data.job_id;
        openDrMonitorModal(_currentJobId, 'Clonagem P2V (VHDX Virtual Disk)');
    } catch (e) {
        alert('Erro ao iniciar clonagem P2V: ' + e.message);
    }
}

async function startSystemStateBackup() {
    const target = document.getElementById('sysstate-target-path')?.value.trim() || null;
    const includeAd = document.getElementById('sysstate-include-ad')?.checked !== false;

    try {
        const res = await fetch('/api/v1/dr/system-state/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_folder: target,
                include_ad: includeAd
            })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || err.message || 'Falha ao iniciar Backup System State');
        }

        const data = await res.json();
        _currentJobId = data.job_id;
        openDrMonitorModal(_currentJobId, 'Backup a Quente do System State & Active Directory');
    } catch (e) {
        alert('Erro ao iniciar backup: ' + e.message);
    }
}

async function buildRecoveryISO() {
    const mediaType = document.getElementById('iso-boot-type')?.value || 'winpe';
    const embedDrivers = document.getElementById('iso-embed-drivers')?.value === 'yes';

    try {
        const res = await fetch('/api/v1/dr/boot-media/build', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                media_type: mediaType,
                embed_drivers: embedDrivers
            })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || err.message || 'Falha ao criar Mídia de Boot');
        }

        const data = await res.json();
        _currentJobId = data.job_id;
        openDrMonitorModal(_currentJobId, 'GBOC Recovery Environment® (Mídia de Boot ISO/WinPE)');
    } catch (e) {
        alert('Erro ao gerar mídia de boot: ' + e.message);
    }
}

// ── Active Directory Granular Explorer ───────────────────────────────────────
async function searchAdObjects() {
    const filter = document.getElementById('ad-filter-type')?.value || 'all';
    const search = document.getElementById('ad-search-box')?.value || '';
    const tableBody = document.getElementById('ad-objects-table-body');
    if (!tableBody) return;

    tableBody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Consultando objetos do Active Directory...</td></tr>';

    try {
        const res = await fetch(`/api/v1/dr/ad-explorer/objects?filter=${filter}&search=${encodeURIComponent(search)}`);
        if (!res.ok) throw new Error('Falha ao pesquisar objetos');
        const data = await res.json();
        const list = data.objects || [];

        if (!list.length) {
            tableBody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-muted);">Nenhum objeto encontrado no catálogo.</td></tr>';
            return;
        }

        tableBody.innerHTML = list.map(obj => `
            <tr>
                <td><span class="badge badge-${obj.type === 'User' ? 'primary' : (obj.type === 'Group' ? 'success' : 'warning')}">${obj.type}</span></td>
                <td><strong>${obj.display_name}</strong><br><span style="font-size:0.75em; color:var(--text-muted);">${obj.sam_name || ''}</span></td>
                <td style="font-size:0.78em; color:var(--text-muted); max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${obj.dn || ''}">${obj.dn || '-'}</td>
                <td style="font-size:0.8em;">${obj.details || '-'}</td>
                <td style="text-align:right;">
                    <button class="btn btn-sm btn-success" onclick="restoreSpecificAdObject('${encodeURIComponent(obj.dn)}', '${obj.type}')" title="Restaurar item granularmente">
                        <i class="fas fa-undo"></i> Restaurar
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tableBody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--danger);">Erro: ${e.message}</td></tr>`;
    }
}

async function restoreSpecificAdObject(encodedDn, type) {
    const dn = decodeURIComponent(encodedDn);
    if (!confirm(`Confirma a restauração granular do objeto:\n${dn}?`)) return;

    try {
        const res = await fetch('/api/v1/dr/ad-explorer/restore-object', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ object_dn: dn, object_type: type })
        });
        const data = await res.json();
        if (data.success) {
            alert('✅ Objeto restaurado com sucesso no Active Directory!');
            searchAdObjects();
        } else {
            alert(`Falha: ${data.error || 'Erro ao restaurar'}`);
        }
    } catch (e) {
        alert('Erro ao executar restauração granular: ' + e.message);
    }
}

// ── Universal Hardware Restore ───────────────────────────────────────────────
async function runUniversalRestoreInjection() {
    const targetVol = document.getElementById('ur-target-volume')?.value.trim();
    const driversPath = document.getElementById('ur-drivers-path')?.value.trim() || null;
    const resultBox = document.getElementById('ur-result-console');

    if (!targetVol) {
        alert('Informe a letra do volume alvo (ex: E:\\ ou D:\\)');
        return;
    }

    if (!confirm(`Deseja aplicar o Universal Hardware Restore no volume '${targetVol}'?\nIsso ativará os drivers de boot e corrigirá o registro offline.`)) return;

    if (resultBox) {
        resultBox.style.display = 'block';
        resultBox.textContent = 'Executando injeção de drivers e correção de registro offline...';
    }

    try {
        const res = await fetch('/api/v1/dr/universal-restore/inject', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_volume: targetVol, drivers_folder: driversPath })
        });
        const data = await res.json();
        if (resultBox && Array.isArray(data.logs)) {
            resultBox.textContent = data.logs.join('\n');
        }
        if (data.success) {
            alert('🎉 Universal Hardware Restore concluído com sucesso no volume!');
        } else {
            alert(`Aviso: ${data.error || 'Erro no processo'}`);
        }
    } catch (e) {
        alert('Erro ao executar Universal Restore: ' + e.message);
    }
}

// ── Instant VM Boot ──────────────────────────────────────────────────────────
async function startInstantVmAction() {
    const vhdxPath = document.getElementById('ivm-source-vhdx')?.value.trim();
    const vmName = document.getElementById('ivm-vm-name')?.value.trim() || null;
    const ramMb = parseInt(document.getElementById('ivm-ram-mb')?.value || '4096');
    const vCpus = parseInt(document.getElementById('ivm-vcpus')?.value || '2');

    if (!vhdxPath) {
        alert('Informe o caminho do arquivo VHDX de backup para boot instantâneo.');
        return;
    }

    try {
        const res = await fetch('/api/v1/dr/instant-vm/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source_vhdx_path: vhdxPath,
                vm_name: vmName,
                memory_mb: ramMb,
                cpu_cores: vCpus
            })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || err.message || 'Falha ao iniciar Instant VM');
        }

        const data = await res.json();
        alert(`🚀 Instant VM '${data.instance?.vm_name}' inicializada com sucesso em ${data.instance?.boot_time_seconds}s!`);
        loadInstantVmsList();
    } catch (e) {
        alert('Erro ao iniciar Instant VM: ' + e.message);
    }
}

async function loadInstantVmsList() {
    const tbody = document.getElementById('instant-vms-table-body');
    if (!tbody) return;

    try {
        const res = await fetch('/api/v1/dr/instant-vm/list');
        if (!res.ok) return;
        const data = await res.json();
        const vms = data.instances || [];

        if (!vms.length) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:18px; color:var(--text-muted);">Nenhuma VM instantânea em execução no momento.</td></tr>';
            return;
        }

        tbody.innerHTML = vms.map(v => `
            <tr>
                <td><strong>${v.vm_name}</strong></td>
                <td><span class="badge badge-${v.status === 'RUNNING' ? 'success' : 'secondary'}">${v.status}</span></td>
                <td>${v.memory_mb} MB / ${v.cpu_cores} vCPU</td>
                <td>${v.boot_time_seconds}s</td>
                <td style="font-size:0.78em; color:var(--text-muted); max-width:180px; overflow:hidden; text-overflow:ellipsis;" title="${v.source_vhdx}">${v.source_vhdx}</td>
                <td style="text-align:right;">
                    ${v.status === 'RUNNING' ? `
                        <button class="btn btn-sm btn-danger" onclick="stopInstantVmAction('${v.instance_id}')">
                            <i class="fas fa-stop"></i> Encerrar
                        </button>
                    ` : '<span style="color:var(--text-muted);font-size:0.8em;">Desalocada</span>'}
                </td>
            </tr>
        `).join('');
    } catch (e) {
        console.error('Erro ao listar Instant VMs:', e);
    }
}

async function stopInstantVmAction(instanceId) {
    if (!confirm(`Deseja encerrar e desalocar a Instant VM #${instanceId}?`)) return;

    try {
        const res = await fetch(`/api/v1/dr/instant-vm/stop/${instanceId}`, { method: 'POST' });
        if (res.ok) {
            loadInstantVmsList();
        }
    } catch (e) {
        alert('Erro ao parar Instant VM: ' + e.message);
    }
}

// ── Virtual Lab Sandbox ──────────────────────────────────────────────────────
async function runVirtualLabSandboxTest() {
    const snapId = document.getElementById('vlab-snapshot-id')?.value.trim() || 'snap-latest';
    const resultBox = document.getElementById('vlab-result-console');

    if (resultBox) {
        resultBox.style.display = 'block';
        resultBox.textContent = 'Iniciando Virtual Lab Sandbox com switch isolado anti-colisão...';
    }

    try {
        const res = await fetch('/api/v1/dr/virtual-lab/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ snapshot_id: snapId })
        });
        const data = await res.json();
        if (resultBox && Array.isArray(data.logs)) {
            resultBox.textContent = data.logs.join('\n');
        }
        if (data.success) {
            alert('🎉 Virtual Lab Sandbox concluído com sucesso! Integridade de boot 100% verificada.');
        }
    } catch (e) {
        alert('Erro no teste de Virtual Lab: ' + e.message);
    }
}

// ── Exportar Runbook ─────────────────────────────────────────────────────────
async function exportDrRunbook() {
    try {
        const res = await fetch('/api/v1/dr/export', { method: 'POST' });
        if (!res.ok) throw new Error('Falha ao exportar plano de DR');
        const data = await res.json();
        
        const blob = new Blob([JSON.stringify(data.dr_plan || data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `GBOC_Disaster_Recovery_Plan_${new Date().toISOString().slice(0,10)}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (e) {
        alert('Erro ao exportar Runbook de DR: ' + e.message);
    }
}

// ── Monitor Modal ────────────────────────────────────────────────────────────
function openDrMonitorModal(jobId, title) {
    const modal = document.getElementById('dr-monitor-modal');
    const titleEl = document.getElementById('dr-modal-title');
    const logsEl = document.getElementById('dr-live-logs');
    const fillEl = document.getElementById('dr-modal-progress-fill');
    const pctEl = document.getElementById('dr-modal-progress-pct');
    const statusText = document.getElementById('dr-modal-status-text');

    if (titleEl) titleEl.textContent = title;
    if (logsEl) logsEl.textContent = 'Inicializando monitor de execução...';
    if (fillEl) fillEl.style.width = '0%';
    if (pctEl) pctEl.textContent = '0%';
    if (statusText) statusText.textContent = 'Executando em background...';
    if (modal) modal.style.display = 'block';

    if (_activeDrPolling) clearInterval(_activeDrPolling);

    _activeDrPolling = setInterval(async () => {
        try {
            const res = await fetch(`/api/v1/dr/job/status/${jobId}`);
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

            if (job.status === 'completed') {
                clearInterval(_activeDrPolling);
                if (fillEl) fillEl.style.width = '100%';
                if (pctEl) pctEl.textContent = '100%';
                if (statusText) statusText.innerHTML = '<span style="color:var(--success); font-weight:700;">✅ Operação concluída com sucesso!</span>';
            } else if (job.status === 'failed' || job.status === 'cancelled') {
                clearInterval(_activeDrPolling);
                if (statusText) statusText.innerHTML = `<span style="color:var(--danger); font-weight:700;">❌ Status: ${job.status.toUpperCase()} (${job.error || 'Cancelado pelo operador'})</span>`;
            }
        } catch (e) {
            console.error('Erro no polling do job DR:', e);
        }
    }, 1000);
}

async function cancelCurrentDrJob() {
    if (!_currentJobId) return;
    if (!confirm(`Deseja realmente cancelar a tarefa ${_currentJobId}?`)) return;

    try {
        const res = await fetch(`/api/v1/dr/job/cancel/${_currentJobId}`, { method: 'POST' });
        if (res.ok) {
            if (_activeDrPolling) clearInterval(_activeDrPolling);
            const statusText = document.getElementById('dr-modal-status-text');
            if (statusText) statusText.innerHTML = '<span style="color:var(--danger); font-weight:700;">⚠️ Operação cancelada.</span>';
        }
    } catch (e) {
        alert('Erro ao cancelar: ' + e.message);
    }
}

function closeDrMonitorModal() {
    const modal = document.getElementById('dr-monitor-modal');
    if (modal) modal.style.display = 'none';
    if (_activeDrPolling) {
        clearInterval(_activeDrPolling);
        _activeDrPolling = null;
    }
}
