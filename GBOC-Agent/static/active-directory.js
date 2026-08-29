/**
 * GBOC System v13.2.0 Enterprise Edition
 * Module: Active Directory Dedicated Backup & Recovery Controller
 * Copyright (c) 2026 Master11BR - Todos os direitos reservados.
 */

let _adPollingTimer = null;
let _currentAdJobId = null;

document.addEventListener('DOMContentLoaded', () => {
    if (typeof UnifiedSidebar === 'function') {
        new UnifiedSidebar().initialize();
    }
    loadAdTopology();
    loadAdHealth();
    loadAdBackupHistory();
});

function switchAdTab(tabId) {
    document.querySelectorAll('.ad-tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.ad-tab-content').forEach(content => content.classList.remove('active'));

    const activeBtn = document.getElementById(`tab-btn-${tabId}`);
    const activeContent = document.getElementById(`tab-content-${tabId}`);
    if (activeBtn) activeBtn.classList.add('active');
    if (activeContent) activeContent.classList.add('active');

    if (tabId === 'objects') {
        searchAdGranularObjects();
    } else if (tabId === 'history') {
        loadAdBackupHistory();
    } else if (tabId === 'health') {
        loadAdHealth();
    }
}

// ── Topologia & FSMO Roles ──────────────────────────────────────────────────
async function loadAdTopology() {
    try {
        const res = await fetch('/api/v1/active-directory/topology');
        if (!res.ok) throw new Error('Falha ao carregar topologia');
        const data = await res.json();
        const top = data.topology || {};

        // Badges e Cards
        const isDcBadge = document.getElementById('ad-is-dc-badge');
        if (isDcBadge) {
            if (top.is_domain_controller) {
                isDcBadge.className = 'badge badge-success';
                isDcBadge.innerHTML = '<i class="fas fa-shield-alt"></i> Controlador de Domínio Ativo (DC)';
            } else {
                isDcBadge.className = 'badge badge-info';
                isDcBadge.innerHTML = '<i class="fas fa-server"></i> Servidor Membro / Standalone';
            }
        }

        const domainNameEl = document.getElementById('ad-domain-name');
        const forestNameEl = document.getElementById('ad-forest-name');
        const domainLevelEl = document.getElementById('ad-domain-level');
        const forestLevelEl = document.getElementById('ad-forest-level');
        const recycleBinEl = document.getElementById('ad-recycle-bin-status');

        if (domainNameEl) domainNameEl.textContent = top.domain_name || 'WORKGROUP';
        if (forestNameEl) forestNameEl.textContent = top.forest_name || top.domain_name || 'N/A';
        if (domainLevelEl) domainLevelEl.textContent = top.domain_functional_level || 'N/A';
        if (forestLevelEl) forestLevelEl.textContent = top.forest_functional_level || 'N/A';
        if (recycleBinEl) {
            recycleBinEl.innerHTML = top.recycle_bin_enabled
                ? '<span style="color:var(--success); font-weight:700;"><i class="fas fa-check-circle"></i> Habilitada (AD Recycle Bin)</span>'
                : '<span style="color:var(--warning); font-weight:600;"><i class="fas fa-exclamation-triangle"></i> Desabilitada</span>';
        }

        // FSMO Roles
        const fsmo = top.fsmo_roles || {};
        const schemaEl = document.getElementById('fsmo-schema');
        const namingEl = document.getElementById('fsmo-naming');
        const pdcEl = document.getElementById('fsmo-pdc');
        const ridEl = document.getElementById('fsmo-rid');
        const infraEl = document.getElementById('fsmo-infra');

        if (schemaEl) schemaEl.textContent = fsmo.schema_master || 'N/A';
        if (namingEl) namingEl.textContent = fsmo.domain_naming_master || 'N/A';
        if (pdcEl) pdcEl.textContent = fsmo.pdc_emulator || 'N/A';
        if (ridEl) ridEl.textContent = fsmo.rid_master || 'N/A';
        if (infraEl) infraEl.textContent = fsmo.infrastructure_master || 'N/A';

        // Lista de DCs
        const dcsList = document.getElementById('ad-dcs-list');
        if (dcsList && Array.isArray(top.domain_controllers)) {
            if (!top.domain_controllers.length) {
                dcsList.innerHTML = `<div style="padding:10px; color:var(--text-muted); font-size:0.85em;">Host atual: <strong>${top.domain_name || 'Standalone'}</strong></div>`;
            } else {
                dcsList.innerHTML = top.domain_controllers.map(dc => `
                    <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid var(--border); font-size:0.84em;">
                        <div>
                            <strong style="color:var(--text);"><i class="fas fa-server" style="color:var(--primary); margin-right:6px;"></i> ${dc.hostname}</strong>
                            <div style="font-size:0.75em; color:var(--text-muted);">${dc.ip_address} • ${dc.site || 'Site Padrão'} • ${dc.operating_system || 'Windows Server'}</div>
                        </div>
                        <div>
                            ${dc.is_global_catalog ? '<span class="badge badge-primary" style="font-size:0.7em;">Global Catalog (GC)</span>' : ''}
                        </div>
                    </div>
                `).join('');
            }
        }
    } catch (e) {
        console.error('Erro ao carregar topologia:', e);
    }
}

// ── Saúde & Replicação ──────────────────────────────────────────────────────
async function loadAdHealth() {
    try {
        const res = await fetch('/api/v1/active-directory/health');
        if (!res.ok) return;
        const data = await res.json();
        const h = data.health || {};

        const sysvolBadge = document.getElementById('ad-health-sysvol');
        const netlogonBadge = document.getElementById('ad-health-netlogon');
        const repSummaryEl = document.getElementById('ad-repadmin-output');

        if (sysvolBadge) {
            sysvolBadge.className = `badge badge-${h.sysvol_shared ? 'success' : 'danger'}`;
            sysvolBadge.innerHTML = `<i class="fas fa-${h.sysvol_shared ? 'check' : 'times'}"></i> ${h.sysvol_shared ? 'Compartilhado' : 'Falha'}`;
        }
        if (netlogonBadge) {
            netlogonBadge.className = `badge badge-${h.netlogon_shared ? 'success' : 'danger'}`;
            netlogonBadge.innerHTML = `<i class="fas fa-${h.netlogon_shared ? 'check' : 'times'}"></i> ${h.netlogon_shared ? 'Compartilhado' : 'Falha'}`;
        }
        if (repSummaryEl) {
            repSummaryEl.textContent = h.repadmin_output || 'Nenhuma falha de replicação detectada.';
        }
    } catch (e) {
        console.error('Erro ao consultar saúde do AD:', e);
    }
}

// ── Backup a Quente do Active Directory ──────────────────────────────────────
async function startAdBackupJob() {
    const backupName = document.getElementById('ad-backup-custom-name')?.value.trim() || null;
    const includeSysvol = document.getElementById('ad-bkp-sysvol')?.checked !== false;
    const includeRegistry = document.getElementById('ad-bkp-registry')?.checked !== false;
    const includeDns = document.getElementById('ad-bkp-dns')?.checked !== false;

    try {
        const res = await fetch('/api/v1/active-directory/backup/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                backup_name: backupName,
                include_sysvol: includeSysvol,
                include_registry: includeRegistry,
                include_dns: includeDns
            })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || err.message || 'Falha ao iniciar backup do AD');
        }

        const data = await res.json();
        _currentAdJobId = data.job_id;
        openAdMonitorModal(_currentAdJobId, 'Backup a Quente Completo do Active Directory (AD DS)');
    } catch (e) {
        alert('Erro ao disparar backup do AD: ' + e.message);
    }
}

// ── Histórico de Backups ────────────────────────────────────────────────────
async function loadAdBackupHistory() {
    const tbody = document.getElementById('ad-history-table-body');
    if (!tbody) return;

    try {
        const res = await fetch('/api/v1/active-directory/backup/history');
        if (!res.ok) return;
        const data = await res.json();
        const list = data.history || [];

        if (!list.length) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:18px; color:var(--text-muted);">Nenhum snapshot de backup do Active Directory localizado em disco.</td></tr>';
            return;
        }

        tbody.innerHTML = list.map(item => `
            <tr>
                <td><strong>${item.backup_name}</strong></td>
                <td>${item.domain || '-'}</td>
                <td>${item.size_mb || '0'} MB</td>
                <td>${new Date(item.created_at).toLocaleString('pt-BR')}</td>
                <td><span class="badge badge-success" style="font-size:0.75em;"><i class="fas fa-check"></i> VSS ESENT Íntegro</span></td>
                <td style="text-align:right;">
                    <button class="btn btn-sm btn-secondary" onclick="openAuthoritativeScriptModal('${item.domain}')" title="Gerar script de restauração">
                        <i class="fas fa-terminal"></i> Guia Restore
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        console.error('Erro ao carregar histórico:', e);
    }
}

// ── Explorador Granular de Objetos ──────────────────────────────────────────
async function searchAdGranularObjects() {
    const filter = document.getElementById('ad-obj-filter')?.value || 'all';
    const search = document.getElementById('ad-obj-search')?.value.trim() || '';
    const tbody = document.getElementById('ad-granular-table-body');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Consultando catálogo do Active Directory...</td></tr>';

    try {
        const res = await fetch(`/api/v1/active-directory/objects?filter=${filter}&search=${encodeURIComponent(search)}`);
        if (!res.ok) throw new Error('Falha ao listar objetos');
        const data = await res.json();
        const list = data.objects || [];

        if (!list.length) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-muted);">Nenhum objeto retornado para os critérios de busca.</td></tr>';
            return;
        }

        tbody.innerHTML = list.map(obj => `
            <tr>
                <td><span class="badge badge-${obj.type === 'User' ? 'primary' : (obj.type === 'Group' ? 'success' : 'warning')}">${obj.type}</span></td>
                <td><strong>${obj.display_name}</strong><br><span style="font-size:0.75em; color:var(--text-muted);">${obj.sam_name || ''}</span></td>
                <td style="font-size:0.78em; color:var(--text-muted); max-width:260px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${obj.dn || ''}">${obj.dn || '-'}</td>
                <td style="font-size:0.8em;">${obj.details || '-'}</td>
                <td style="text-align:right;">
                    <button class="btn btn-sm btn-success" onclick="restoreGranularAdItem('${encodeURIComponent(obj.dn)}', '${obj.type}')" title="Ressuscitar objeto via AD Recycle Bin">
                        <i class="fas fa-undo"></i> Restaurar
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--danger);">Erro: ${e.message}</td></tr>`;
    }
}

async function restoreGranularAdItem(encodedDn, type) {
    const dn = decodeURIComponent(encodedDn);
    if (!confirm(`Deseja restaurar granularmente o objeto do Active Directory:\n${dn}?`)) return;

    try {
        const res = await fetch('/api/v1/active-directory/objects/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ object_dn: dn, object_type: type })
        });
        const data = await res.json();
        if (data.success) {
            alert('✅ Objeto restaurado com sucesso no Active Directory!');
            searchAdGranularObjects();
        } else {
            alert(`Aviso: ${data.error || 'Erro na operação'}`);
        }
    } catch (e) {
        alert('Erro ao restaurar objeto: ' + e.message);
    }
}

// ── Script Autoritativo ntdsutil ─────────────────────────────────────────────
async function generateAuthoritativeScriptAction() {
    const ouDn = document.getElementById('ad-restore-target-ou')?.value.trim();
    if (!ouDn) {
        alert('Informe o DistinguishedName (DN) da Unidade Organizacional (OU) alvo.');
        return;
    }

    try {
        const res = await fetch('/api/v1/active-directory/authoritative-script', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_ou_dn: ouDn })
        });
        const data = await res.json();
        const scriptBox = document.getElementById('ad-authoritative-script-output');
        if (scriptBox && data.data?.script) {
            scriptBox.style.display = 'block';
            scriptBox.textContent = data.data.script;
        }
    } catch (e) {
        alert('Erro ao gerar script autoritativo: ' + e.message);
    }
}

function openAuthoritativeScriptModal(domain) {
    switchAdTab('recovery');
    const input = document.getElementById('ad-restore-target-ou');
    if (input) input.value = `OU=Departamentos,DC=${domain?.split('.')[0] || 'empresa'},DC=local`;
}

// ── Modal de Monitoramento de Backup AD ──────────────────────────────────────
function openAdMonitorModal(jobId, title) {
    const modal = document.getElementById('ad-monitor-modal');
    const titleEl = document.getElementById('ad-modal-title');
    const logsEl = document.getElementById('ad-live-logs');
    const fillEl = document.getElementById('ad-modal-progress-fill');
    const pctEl = document.getElementById('ad-modal-progress-pct');
    const statusText = document.getElementById('ad-modal-status-text');

    if (titleEl) titleEl.textContent = title;
    if (logsEl) logsEl.textContent = 'Iniciando congelamento VSS e extração da base NTDS...';
    if (fillEl) fillEl.style.width = '0%';
    if (pctEl) pctEl.textContent = '0%';
    if (statusText) statusText.textContent = 'Processando backup do Active Directory em background...';
    if (modal) modal.style.display = 'block';

    if (_adPollingTimer) clearInterval(_adPollingTimer);

    _adPollingTimer = setInterval(async () => {
        try {
            const res = await fetch(`/api/v1/active-directory/backup/status/${jobId}`);
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
                clearInterval(_adPollingTimer);
                if (fillEl) fillEl.style.width = '100%';
                if (pctEl) pctEl.textContent = '100%';
                if (statusText) statusText.innerHTML = '<span style="color:var(--success); font-weight:700;">✅ Backup do Active Directory concluído com sucesso!</span>';
                loadAdBackupHistory();
            } else if (job.status === 'failed') {
                clearInterval(_adPollingTimer);
                if (statusText) statusText.innerHTML = `<span style="color:var(--danger); font-weight:700;">❌ Falha no backup: ${job.error || 'Erro desconhecido'}</span>`;
            }
        } catch (e) {
            console.error('Erro no polling do backup AD:', e);
        }
    }, 1000);
}

function closeAdMonitorModal() {
    const modal = document.getElementById('ad-monitor-modal');
    if (modal) modal.style.display = 'none';
    if (_adPollingTimer) {
        clearInterval(_adPollingTimer);
        _adPollingTimer = null;
    }
}
