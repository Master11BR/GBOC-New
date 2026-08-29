// GBOC System v13.2.0 Enterprise Edition
// Module: Multi-Tenant MSP JavaScript Controller

var TENANT_API = '/api/v1/tenant';
var cachedOrgs = [];
var isEditingOrg = false;

document.addEventListener('DOMContentLoaded', function () {
    // Apenas carrega se estiver na rota onde o script é inserido de forma isolada
    if (document.getElementById('multitenant-org-table')) {
        loadMultiTenantData();
    }
});

async function loadMultiTenantData() {
    const tbody = document.getElementById('multitenant-org-table');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px"><i class="fas fa-spinner fa-spin"></i> Carregando Organizações MSP...</td></tr>';
    
    try {
        const r = await fetch((window.GBOC_API_BASE || '') + TENANT_API + '/organizations');
        const d = await r.json();
        
        cachedOrgs = d.organizations || [];
        
        // Atualizar KPIs
        const totalOrgs = cachedOrgs.length;
        const activeOrgs = cachedOrgs.filter(o => o.status === 'active').length;
        const totalMaxAgents = cachedOrgs.reduce((acc, curr) => acc + parseInt(curr.max_agents || 0), 0);
        
        if (document.getElementById('mt-kpi-total')) document.getElementById('mt-kpi-total').textContent = totalOrgs;
        if (document.getElementById('mt-kpi-active')) document.getElementById('mt-kpi-active').textContent = activeOrgs;
        if (document.getElementById('mt-kpi-agents')) document.getElementById('mt-kpi-agents').textContent = totalMaxAgents;

        if (cachedOrgs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--text-muted)">Nenhuma organização MSP cadastrada.</td></tr>';
            return;
        }

        tbody.innerHTML = cachedOrgs.map(o => {
            const planBadge = o.plan === 'Enterprise 10x' ? 'mt-badge-danger' : o.plan === 'Pro Managed' ? 'mt-badge-info' : 'mt-badge-success';
            const statusBadge = o.status === 'active' ? 'mt-badge-success' : 'mt-badge-danger';
            const statusLabel = o.status === 'active' ? 'ATIVO' : 'INATIVO';

            return `<tr>
                <td><code>${o.id}</code></td>
                <td><strong style="color:var(--text);font-size:0.95em">${o.name}</strong></td>
                <td><span class="${planBadge}">${o.plan}</span></td>
                <td><strong style="color:var(--text)">${o.max_agents}</strong> Agentes</td>
                <td><span class="${statusBadge}">${statusLabel}</span></td>
                <td style="text-align:right">
                    <div style="display:flex;gap:6px;justify-content:flex-end">
                        <button class="btn btn-sm btn-secondary" onclick="openOrgModal('${o.id}')" title="Editar Organização"><i class="fas fa-edit"></i></button>
                        <button class="btn btn-sm btn-danger" onclick="deleteOrganization('${o.id}')" title="Excluir"><i class="fas fa-trash"></i></button>
                    </div>
                </td>
            </tr>`;
        }).join('');

    } catch(e) {
        console.error('Erro ao carregar dados de tenant/msp:', e);
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--danger)">Erro de conexão: ${e.message}</td></tr>`;
    }
}

function openOrgModal(orgId = null) {
    const modal = document.getElementById('mt-org-modal');
    const title = document.getElementById('mt-modal-title');
    const inputId = document.getElementById('mt-org-id');
    const inputName = document.getElementById('mt-org-name');
    const selectPlan = document.getElementById('mt-org-plan');
    const inputMaxAgents = document.getElementById('mt-org-max-agents');
    const selectStatus = document.getElementById('mt-org-status');

    if (!modal) return;

    if (orgId) {
        isEditingOrg = true;
        title.innerHTML = '<i class="fas fa-edit" style="color:var(--primary)"></i> Editar Organização MSP';
        
        const org = cachedOrgs.find(o => o.id === orgId);
        if (org) {
            inputId.value = org.id;
            inputId.disabled = true; // Não permite mudar ID
            inputName.value = org.name;
            selectPlan.value = org.plan;
            inputMaxAgents.value = org.max_agents;
            selectStatus.value = org.status;
        }
    } else {
        isEditingOrg = false;
        title.innerHTML = '<i class="fas fa-plus-circle" style="color:var(--primary)"></i> Adicionar Organização MSP';
        
        inputId.value = '';
        inputId.disabled = false;
        inputName.value = '';
        selectPlan.value = 'Standard';
        inputMaxAgents.value = '25';
        selectStatus.value = 'active';
    }

    modal.classList.add('show');
}

function closeOrgModal() {
    const modal = document.getElementById('mt-org-modal');
    if (modal) {
        modal.classList.remove('show');
    }
}

async function saveOrganization() {
    const orgId = document.getElementById('mt-org-id').value.trim();
    const name = document.getElementById('mt-org-name').value.trim();
    const plan = document.getElementById('mt-org-plan').value;
    const maxAgents = parseInt(document.getElementById('mt-org-max-agents').value || '25');
    const status = document.getElementById('mt-org-status').value;

    if (!orgId || !name) {
        alert('Por favor, preencha o ID e o Nome da Organização.');
        return;
    }

    // Regra simples para formatar ID
    const formattedId = orgId.toLowerCase().replace(/[^a-z0-9-_]/g, '-');

    const payload = {
        id: formattedId,
        name: name,
        plan: plan,
        max_agents: maxAgents,
        status: status
    };

    try {
        let url = (window.GBOC_API_BASE || '') + TENANT_API + '/organizations';
        let method = 'POST';

        if (isEditingOrg) {
            url += '/' + orgId;
            method = 'PUT';
            // Remover ID do payload no PUT para evitar validações errôneas do backend
            delete payload.id;
        }

        const r = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const d = await r.json();
        
        if (d.status === 'success') {
            closeOrgModal();
            loadMultiTenantData();
            // Atualiza dropdown de tenants no CRUD de usuários se ele existir
            if (typeof loadTenantsDropdown === 'function') {
                loadTenantsDropdown();
            }
        } else {
            alert('Falha ao salvar: ' + (d.message || d.detail || 'Erro desconhecido'));
        }
    } catch(e) {
        console.error('Erro ao salvar organização:', e);
        alert('Erro ao salvar: ' + e.message);
    }
}

async function deleteOrganization(orgId) {
    if (!confirm(`Tem certeza de que deseja excluir a organização '${orgId}'? Todos os usuários e agentes associados serão desvinculados.`)) {
        return;
    }

    try {
        const r = await fetch((window.GBOC_API_BASE || '') + TENANT_API + '/organizations/' + orgId, {
            method: 'DELETE'
        });
        const d = await r.json();

        if (d.status === 'success') {
            loadMultiTenantData();
            if (typeof loadTenantsDropdown === 'function') {
                loadTenantsDropdown();
            }
        } else {
            alert('Falha ao excluir: ' + (d.message || d.detail || 'Erro desconhecido'));
        }
    } catch(e) {
        console.error('Erro ao excluir organização:', e);
        alert('Erro ao excluir: ' + e.message);
    }
}

// Exportar globalmente
window.loadMultiTenantData = loadMultiTenantData;
window.openOrgModal = openOrgModal;
window.closeOrgModal = closeOrgModal;
window.saveOrganization = saveOrganization;
window.deleteOrganization = deleteOrganization;
