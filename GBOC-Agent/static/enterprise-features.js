/**
 * GBOC System v13.2.0 Enterprise Edition
 * Module: Enterprise Connectors, CDP, Tape Robotics & Compliance Controller
 * Copyright (c) 2026 Master11BR - Todos os direitos reservados.
 */

let _activeDbPolling = null;
let _cdpCheckpoints = [];

document.addEventListener('DOMContentLoaded', () => {
    if (typeof UnifiedSidebar === 'function') {
        new UnifiedSidebar().initialize();
    }
    detectEnterpriseDatabases();
    loadCdpStatus();
    loadCdpCheckpoints();
    loadTapeRoboticsInventory();
    loadComplianceCertificate();
});

function switchEnterpriseTab(tabId) {
    document.querySelectorAll('.ent-tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.ent-tab-content').forEach(content => content.classList.remove('active'));

    const activeBtn = document.getElementById(`tab-btn-${tabId}`);
    const activeContent = document.getElementById(`tab-content-${tabId}`);
    if (activeBtn) activeBtn.classList.add('active');
    if (activeContent) activeContent.classList.add('active');
}

// ── 1. Conectores Enterprise (Oracle, SAP, DB2) ──────────────────────────────
async function detectEnterpriseDatabases() {
    try {
        const res = await fetch('/api/v1/enterprise/databases/detect');
        if (!res.ok) return;
        const data = await res.json();
        const det = data.detected || {};

        const oracleBadge = document.getElementById('oracle-status-badge');
        const sapBadge = document.getElementById('sap-status-badge');
        const db2Badge = document.getElementById('db2-status-badge');

        if (oracleBadge) {
            oracleBadge.className = `badge badge-${det.oracle?.installed ? 'success' : 'secondary'}`;
            oracleBadge.innerHTML = det.oracle?.installed ? '<i class="fas fa-check-circle"></i> Oracle RMAN Conectado' : 'Não Detectado';
        }
        if (sapBadge) {
            sapBadge.className = `badge badge-${det.sap_hana?.installed ? 'success' : 'secondary'}`;
            sapBadge.innerHTML = det.sap_hana?.installed ? '<i class="fas fa-check-circle"></i> SAP HANA Backint Pronto' : 'Não Detectado';
        }
        if (db2Badge) {
            db2Badge.className = `badge badge-${det.ibm_db2?.installed ? 'success' : 'secondary'}`;
            db2Badge.innerHTML = det.ibm_db2?.installed ? '<i class="fas fa-check-circle"></i> IBM DB2 Online Pronto' : 'Não Detectado';
        }
    } catch (e) {
        console.error('Erro na detecção de bancos:', e);
    }
}

async function startOracleRmanAction() {
    const sid = document.getElementById('oracle-sid-input')?.value.trim() || 'ORCL';
    const type = document.getElementById('oracle-backup-type')?.value || 'INCREMENTAL_LEVEL_0';
    const delArch = document.getElementById('oracle-del-arch')?.checked !== false;

    try {
        const res = await fetch('/api/v1/enterprise/oracle/backup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ oracle_sid: sid, backup_type: type, archive_log_delete: delArch })
        });
        const data = await res.json();
        openEntMonitorModal(data.job_id, `Oracle RMAN Backup (${sid})`);
    } catch (e) {
        alert('Erro ao disparar Oracle RMAN: ' + e.message);
    }
}

async function startSapHanaAction() {
    const inst = document.getElementById('saphana-inst-input')?.value.trim() || 'HDB00';
    const tenant = document.getElementById('saphana-tenant-input')?.value.trim() || 'SYSTEMDB';

    try {
        const res = await fetch('/api/v1/enterprise/saphana/backup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instance_id: inst, tenant_db: tenant })
        });
        const data = await res.json();
        openEntMonitorModal(data.job_id, `SAP HANA Backint (${inst})`);
    } catch (e) {
        alert('Erro ao disparar SAP HANA: ' + e.message);
    }
}

async function startIbmDb2Action() {
    const db = document.getElementById('ibmdb2-name-input')?.value.trim() || 'SAMPLE';

    try {
        const res = await fetch('/api/v1/enterprise/ibmdb2/backup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ db_name: db })
        });
        const data = await res.json();
        openEntMonitorModal(data.job_id, `IBM DB2 Online Backup (${db})`);
    } catch (e) {
        alert('Erro ao disparar IBM DB2: ' + e.message);
    }
}

// ── 2. Continuous Data Protection (CDP) ──────────────────────────────────────
async function loadCdpStatus() {
    try {
        const res = await fetch('/api/v1/enterprise/cdp/status');
        if (!res.ok) return;
        const data = await res.json();
        const cdp = data.data || {};

        const badge = document.getElementById('cdp-state-badge');
        const rpoVal = document.getElementById('cdp-rpo-val');
        const btnToggle = document.getElementById('cdp-toggle-btn');

        if (badge) {
            badge.className = `badge badge-${cdp.is_active ? 'success' : 'secondary'}`;
            badge.innerHTML = cdp.is_active ? '<i class="fas fa-satellite-dish fa-spin"></i> CDP Ativo (Streaming)' : '<i class="fas fa-pause"></i> CDP Pausado';
        }
        if (rpoVal) rpoVal.textContent = `${cdp.current_rpo_seconds || 10}s`;
        if (btnToggle) {
            btnToggle.innerHTML = cdp.is_active ? '<i class="fas fa-pause"></i> Pausar Daemon CDP' : '<i class="fas fa-play"></i> Iniciar Daemon CDP';
            btnToggle.className = `btn btn-${cdp.is_active ? 'warning' : 'success'}`;
        }
    } catch (e) {
        console.error('Erro no status do CDP:', e);
    }
}

async function toggleCdpDaemon() {
    const isCurrentlyActive = document.getElementById('cdp-state-badge')?.textContent.includes('Ativo');
    const endpoint = isCurrentlyActive ? '/api/v1/enterprise/cdp/stop' : '/api/v1/enterprise/cdp/start';

    try {
        const res = await fetch(endpoint, { method: 'POST' });
        if (res.ok) {
            loadCdpStatus();
            loadCdpCheckpoints();
        }
    } catch (e) {
        alert('Erro ao alternar CDP: ' + e.message);
    }
}

async function loadCdpCheckpoints() {
    try {
        const res = await fetch('/api/v1/enterprise/cdp/checkpoints?limit=30');
        if (!res.ok) return;
        const data = await res.json();
        _cdpCheckpoints = data.checkpoints || [];

        const slider = document.getElementById('cdp-time-slider');
        const countEl = document.getElementById('cdp-checkpoints-count');
        const tbody = document.getElementById('cdp-checkpoints-table-body');

        if (countEl) countEl.textContent = `${_cdpCheckpoints.length} Checkpoints`;

        if (slider) {
            slider.max = Math.max(0, _cdpCheckpoints.length - 1);
            slider.value = slider.max;
            updateSliderSelectedTime();
        }

        if (tbody) {
            tbody.innerHTML = _cdpCheckpoints.map(c => `
                <tr>
                    <td><strong>${c.checkpoint_id}</strong></td>
                    <td>${new Date(c.timestamp).toLocaleTimeString('pt-BR')} <span style="font-size:0.75em;color:var(--text-muted);">${new Date(c.timestamp).toLocaleDateString('pt-BR')}</span></td>
                    <td><span class="badge badge-success">${c.rpo_seconds}s RPO</span></td>
                    <td>${c.delta_size_kb} KB</td>
                    <td><span style="color:var(--success);"><i class="fas fa-check-circle"></i> ${c.consistency}</span></td>
                    <td style="text-align:right;">
                        <button class="btn btn-sm btn-secondary" onclick="executeRollbackAction('${c.checkpoint_id}')">
                            <i class="fas fa-history"></i> Rollback
                        </button>
                    </td>
                </tr>
            `).join('');
        }
    } catch (e) {
        console.error('Erro ao carregar checkpoints:', e);
    }
}

function updateSliderSelectedTime() {
    const slider = document.getElementById('cdp-time-slider');
    const label = document.getElementById('cdp-slider-timestamp');
    if (!slider || !label || !_cdpCheckpoints.length) return;

    const idx = parseInt(slider.value);
    const chk = _cdpCheckpoints[idx] || _cdpCheckpoints[0];
    if (chk) {
        label.innerHTML = `Ponto Selecionado: <strong>${new Date(chk.timestamp).toLocaleString('pt-BR')}</strong> (ID: ${chk.checkpoint_id})`;
    }
}

async function rollbackFromSlider() {
    const slider = document.getElementById('cdp-time-slider');
    if (!slider || !_cdpCheckpoints.length) return;
    const idx = parseInt(slider.value);
    const chk = _cdpCheckpoints[idx];
    if (chk) {
        executeRollbackAction(chk.checkpoint_id);
    }
}

async function executeRollbackAction(chkId) {
    if (!confirm(`Deseja executar o Point-in-Time Rollback para o checkpoint:\n${chkId}?`)) return;

    try {
        const res = await fetch('/api/v1/enterprise/cdp/rollback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ checkpoint_id: chkId })
        });
        const data = await res.json();
        if (data.success) {
            alert(`🎉 Point-in-Time Rollback concluído com sucesso para ${data.restored_timestamp}!`);
        } else {
            alert('Falha: ' + (data.error || 'Erro no rollback'));
        }
    } catch (e) {
        alert('Erro ao executar rollback: ' + e.message);
    }
}

// ── 3. Robótica de Fitas LTO ────────────────────────────────────────────────
async function loadTapeRoboticsInventory() {
    try {
        const res = await fetch('/api/v1/enterprise/tape-robotics/inventory');
        if (!res.ok) return;
        const data = await res.json();
        const ch = data.changer || {};
        const slots = data.slots || [];
        const drives = data.drives || [];

        const nameEl = document.getElementById('tape-robot-name');
        const slotsGrid = document.getElementById('tape-slots-grid');
        const drivesBox = document.getElementById('tape-drives-box');

        if (nameEl) nameEl.textContent = `${ch.vendor} ${ch.product} (${ch.total_slots} Slots • Firmware ${ch.firmware})`;

        if (drivesBox) {
            drivesBox.innerHTML = drives.map(d => `
                <div style="background:var(--bg-input); padding:12px; border-radius:8px; border:1px solid var(--border); margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <strong style="color:var(--text);"><i class="fas fa-tape" style="color:var(--primary); margin-right:6px;"></i> ${d.name}</strong>
                        <div style="font-size:0.78em; color:var(--text-muted);">Mídia Carregada: <strong style="color:var(--success); font-family:monospace;">${d.loaded_barcode || 'VAZIO (EMPTY)'}</strong></div>
                    </div>
                    <span class="badge badge-${d.loaded_barcode ? 'success' : 'secondary'}">${d.status}</span>
                </div>
            `).join('');
        }

        if (slotsGrid) {
            slotsGrid.innerHTML = slots.map(s => `
                <div style="background:var(--bg-input); border:1px solid ${s.is_full ? 'var(--primary)' : 'var(--border)'}; border-radius:6px; padding:8px; text-align:center; position:relative;">
                    <div style="font-size:0.7em; font-weight:700; color:var(--text-muted);">Slot #${s.slot_number}</div>
                    <div style="font-size:0.85em; font-weight:700; color:${s.is_full ? 'var(--text)' : 'var(--text-muted)'}; margin:4px 0;">
                        ${s.barcode ? `<span style="font-family:monospace; color:var(--primary);">${s.barcode}</span>` : 'VAZIO'}
                    </div>
                    <div style="font-size:0.68em; color:var(--text-muted);">${s.slot_type}</div>
                    ${s.is_full ? `
                        <button class="btn btn-sm btn-primary" style="margin-top:6px; font-size:0.68em; padding:2px 6px;" onclick="moveTapeToDriveAction(${s.slot_number}, 0)">
                            <i class="fas fa-arrow-right"></i> Carregar Drive
                        </button>
                    ` : ''}
                </div>
            `).join('');
        }
    } catch (e) {
        console.error('Erro na robótica de fitas:', e);
    }
}

async function moveTapeToDriveAction(slotNum, driveIndex) {
    if (!confirm(`Comandar braço robótico para mover fita do Slot #${slotNum} para o Drive #${driveIndex}?`)) return;

    try {
        const res = await fetch('/api/v1/enterprise/tape-robotics/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_slot: slotNum, target_drive_or_slot: driveIndex, is_drive_target: true })
        });
        const data = await res.json();
        if (data.success) {
            alert('✅ Fita carregada no drive com sucesso pelo robô SCSI!');
            loadTapeRoboticsInventory();
        }
    } catch (e) {
        alert('Erro ao mover fita: ' + e.message);
    }
}

// ── 4. Auditoria & Certificados Internacionais ──────────────────────────────
async function loadComplianceCertificate() {
    try {
        const res = await fetch('/api/v1/enterprise/compliance/certificate');
        if (!res.ok) return;
        const data = await res.json();
        const cert = data.certificate || {};

        const certIdEl = document.getElementById('cert-id-val');
        const hashEl = document.getElementById('cert-hash-val');
        const gridEl = document.getElementById('cert-standards-grid');

        if (certIdEl) certIdEl.textContent = cert.certificate_id;
        if (hashEl) hashEl.textContent = cert.cryptographic_proof_sha256;

        if (gridEl && cert.standards_evaluated) {
            gridEl.innerHTML = Object.entries(cert.standards_evaluated).map(([k, s]) => `
                <div style="background:var(--bg-input); padding:14px; border-radius:8px; border:1px solid var(--border);">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <strong style="font-size:0.88em; color:var(--text);">${s.name}</strong>
                        <span class="badge badge-success" style="font-size:0.72em;">${s.status}</span>
                    </div>
                    <div style="font-size:0.8em; color:var(--text-muted);">Índice de Conformidade: <strong>${s.compliance_score}%</strong></div>
                </div>
            `).join('');
        }
    } catch (e) {
        console.error('Erro no certificado de conformidade:', e);
    }
}

// ── Modal de Monitoramento ──────────────────────────────────────────────────
function openEntMonitorModal(jobId, title) {
    const modal = document.getElementById('ent-monitor-modal');
    const titleEl = document.getElementById('ent-modal-title');
    const logsEl = document.getElementById('ent-live-logs');
    const fillEl = document.getElementById('ent-modal-progress-fill');
    const pctEl = document.getElementById('ent-modal-progress-pct');

    if (titleEl) titleEl.textContent = title;
    if (logsEl) logsEl.textContent = 'Iniciando operação corporativa...';
    if (fillEl) fillEl.style.width = '0%';
    if (pctEl) pctEl.textContent = '0%';
    if (modal) modal.style.display = 'block';

    if (_activeDbPolling) clearInterval(_activeDbPolling);

    _activeDbPolling = setInterval(async () => {
        try {
            const res = await fetch(`/api/v1/enterprise/job/status/${jobId}`);
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
                clearInterval(_activeDbPolling);
            }
        } catch (e) {
            console.error('Erro no polling:', e);
        }
    }, 1000);
}

function closeEntMonitorModal() {
    const modal = document.getElementById('ent-monitor-modal');
    if (modal) modal.style.display = 'none';
    if (_activeDbPolling) {
        clearInterval(_activeDbPolling);
        _activeDbPolling = null;
    }
}
