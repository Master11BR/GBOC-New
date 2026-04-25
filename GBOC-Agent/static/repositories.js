// ============================================================================
// GBOC Agent v8.2 - repositories.js (CORRIGIDO)
// ✅ Visibilidade correta dos campos de credenciais na criação
// ✅ Preenchimento correto dos campos na edição
// ============================================================================

// State and constants
let repositoryPollingInterval = null;
const POLLING_INTERVAL_MS = 5000;

// Mapear tipos para ícones e nomes amigáveis
const typeIcons = {
    'local': { icon: 'fa-hdd', label: 'Local', color: '#4299e1' },
    'b2': { icon: 'fa-cloud', label: 'Backblaze B2', color: '#f59e0b' },
    's3': { icon: 'fa-aws', label: 'Amazon S3', color: '#ed8936' },
    'wasabi': { icon: 'fa-cloud', label: 'Wasabi', color: '#10b981' },
    'azure': { icon: 'fa-microsoft', label: 'Azure Blob', color: '#4299e1' },
    'gcs': { icon: 'fa-google', label: 'Google Cloud', color: '#48bb78' },
    'sftp': { icon: 'fa-server', label: 'SFTP/Rede', color: '#9f7aea' },
};

function getTypeInfo(type) {
    return typeIcons[type] || { icon: 'fa-database', label: type || 'Desconhecido', color: '#a0aec0' };
}

// ============================================================================
// UI HELPERS (Modals, Toasts)
// ============================================================================

window.openCreateLocalModal = function() {
    const modal = document.getElementById('createLocalModal');
    const form = document.getElementById('createLocalForm');
    modal.classList.add('active');
    form.reset();
};

window.openCreateCloudModal = function() {
    const modal = document.getElementById('createCloudModal');
    const form = document.getElementById('createCloudForm');
    modal.classList.add('active');
    form.reset();
    // Atualizar visibilidade inicial
    updateCreateCloudTypeVisibility();
};

window.closeCreateLocalModal = function() {
    document.getElementById('createLocalModal').classList.remove('active');
};

window.closeCreateCloudModal = function() {
    document.getElementById('createCloudModal').classList.remove('active');
};

window.closeCreateModal = function() {
    document.getElementById('createModal').classList.remove('active');
};

window.openEditModal = async function(repoId) {
    const modal = document.getElementById('editModal');
    modal.classList.add('active');
    const form = document.getElementById('editForm');
    form.reset();

    try {
        const response = await fetch(`/api/repositories/${repoId}`);
        if (!response.ok) {
            throw new Error('Falha ao carregar dados do repositório.');
        }
        const repo = await response.json();
        console.log('📦 Dados do repositório para edição:', repo);
        populateEditForm(repo);
    } catch (error) {
        showToast(error.message, true);
        closeEditModal();
    }
};

window.closeEditModal = function() {
    document.getElementById('editModal').classList.remove('active');
};

function showToast(msg, isError = false, timeout = 5000) {
    const toast = document.createElement('div');
    toast.className = `gboc-toast ${isError ? 'error' : ''}`;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, timeout);
}

// ============================================================================
// VISIBILIDADE DOS CAMPOS - CRIAÇÃO
// ============================================================================

function updateCreateTypeVisibility() {
    const typeSelect = document.getElementById('create-type');
    if (!typeSelect) return;

    const selectedType = typeSelect.value;
    const isLocal = selectedType === 'local';

    // Mostrar/ocultar info de armazenamento local
    const localInfo = document.getElementById('localStorageInfo');
    if (localInfo) {
        localInfo.style.display = isLocal ? 'block' : 'none';
    }

    // Mostrar/ocultar campo de bucket/path
    const pathGroup = document.getElementById('pathGroup');
    if (pathGroup) {
        pathGroup.style.display = isLocal ? 'none' : 'block';
    }

    // Ocultar todas as seções de credenciais primeiro
    const configSections = ['config_s3', 'config_wasabi', 'config_b2', 'config_azure', 'config_gcs'];
    configSections.forEach(id => {
        const section = document.getElementById(id);
        if (section) {
            section.style.display = 'none';
        }
    });

    // Mostrar seção correspondente ao tipo selecionado
    const sectionId = `config_${selectedType}`;
    const activeSection = document.getElementById(sectionId);
    if (activeSection) {
        activeSection.style.display = 'block';
    }

    console.log(`[SYNC] Tipo selecionado: ${selectedType}, Seção ativa: ${sectionId}`);
}

function updateCreateCloudTypeVisibility() {
    const typeSelect = document.getElementById('create-cloud-type');
    if (!typeSelect) return;

    const selectedType = typeSelect.value;

    // Ocultar todas as seções de credenciais primeiro
    const configSections = ['config_cloud_s3', 'config_cloud_wasabi', 'config_cloud_b2', 'config_cloud_azure', 'config_cloud_gcs'];
    configSections.forEach(id => {
        const section = document.getElementById(id);
        if (section) {
            section.style.display = 'none';
        }
    });

    // Mostrar seção correspondente ao tipo selecionado
    const sectionId = `config_cloud_${selectedType}`;
    const activeSection = document.getElementById(sectionId);
    if (activeSection) {
        activeSection.style.display = 'block';
    }

    console.log(`[SYNC] Tipo cloud selecionado: ${selectedType}, Seção ativa: ${sectionId}`);
}

// ============================================================================
// PREENCHIMENTO DO FORMULÁRIO DE EDIÇÃO
// ============================================================================

function populateEditForm(repo) {
    // Campos básicos
    document.getElementById('edit_id').value = repo.id;
    document.getElementById('edit_name').value = repo.name || '';
    document.getElementById('edit_engine').value = repo.engine || 'restic';
    document.getElementById('edit_type').value = repo.type || 'local';

    // Campo de path/bucket
    const pathInput = document.getElementById('edit_path');
    if (pathInput) {
        if (repo.type === 'local') {
            pathInput.value = repo.path || '';
        } else {
            pathInput.value = repo.bucket || repo.path || '';
        }
    }

    // Ocultar todas as seções de credenciais primeiro
    document.querySelectorAll('.edit-config-section').forEach(el => {
        el.style.display = 'none';
    });

    // Mostrar e preencher seção correspondente ao tipo
    const type = repo.type;
    const section = document.getElementById(`edit_config_${type}`);
    
    if (section) {
        section.style.display = 'block';

        // Preencher campos específicos de cada provider
        switch (type) {
            case 's3':
                setFieldValue('edit_aws_access_key', repo.aws_access_key || repo.access_key || '');
                setFieldValue('edit_aws_secret_key', ''); // Não preencher senha por segurança
                break;

            case 'wasabi':
                setFieldValue('edit_wasabi_access_key', repo.aws_access_key || repo.access_key || '');
                setFieldValue('edit_wasabi_secret_key', ''); // Não preencher senha por segurança
                setFieldValue('edit_wasabi_endpoint', repo.endpoint || 's3.wasabisys.com');
                break;

            case 'b2':
                setFieldValue('edit_b2_account_id', repo.b2_account_id || repo.access_key || '');
                setFieldValue('edit_b2_account_key', ''); // Não preencher senha por segurança
                break;

            case 'azure':
                setFieldValue('edit_azure_account_name', repo.azure_account_name || repo.access_key || '');
                setFieldValue('edit_azure_account_key', ''); // Não preencher senha por segurança
                break;

            case 'gcs':
                setFieldValue('edit_gcs_project_id', repo.gcs_project_id || '');
                setFieldValue('edit_gcs_credentials', repo.gcs_credentials || '');
                break;
        }
    }

    console.log(`📝 Formulário de edição preenchido para tipo: ${type}`);
}

function setFieldValue(fieldId, value) {
    const field = document.getElementById(fieldId);
    if (field) {
        field.value = value;
    }
}

// ============================================================================
// POLLING LOGIC
// ============================================================================

function startRepositoryPolling() {
    if (repositoryPollingInterval) return;
    repositoryPollingInterval = setInterval(window.loadRepositories, POLLING_INTERVAL_MS);
    window.loadRepositories();
}

function stopRepositoryPolling() {
    if (repositoryPollingInterval) {
        clearInterval(repositoryPollingInterval);
        repositoryPollingInterval = null;
    }
}

// ============================================================================
// CORE FUNCTIONS
// ============================================================================

window.loadRepositories = async function() {
    let hasPendingRepos = false;
    try {
        const response = await fetch('/api/repositories/');
        if (!response.ok) {
            const errorResult = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(errorResult.detail || `Network response was not ok (${response.status})`);
        }
        
        const repos = await response.json();
        const listContainer = document.getElementById('repo-list');
        const listBody = document.getElementById('repo-list-body');

        if (repos && repos.length > 0) {
            listBody.innerHTML = repos.map(repo => {
                const typeInfo = getTypeInfo(repo.type);
                let statusBadge;

                switch(repo.status) {
                    case 'pending_initialization':
                        statusBadge = `<span class="status-badge status-pending"><i class="fas fa-spinner fa-spin"></i> Inicializando...</span>`;
                        hasPendingRepos = true;
                        break;
                    case 'active':
                        statusBadge = `<span class="status-badge status-active">Ativo</span>`;
                        break;
                    case 'init_failed':
                        statusBadge = `<span class="status-badge status-error"><i class="fas fa-exclamation-circle"></i> Falha na Inicialização</span>`;
                        break;
                    default:
                        statusBadge = `<span class="status-badge status-unknown">${repo.status || 'desconhecido'}</span>`;
                }

                const pathOrBucket = repo.type === 'local' ? (repo.path || 'N/A') : (repo.bucket || repo.endpoint || 'N/A');

                return `
                <div class="repo-row">
                    <div class="col col-name" title="${repo.name}"><i class="fas fa-folder"></i> ${repo.name}</div>
                    <div class="col col-engine"><i class="fas fa-cog"></i> ${repo.engine || 'restic'}</div>
                    <div class="col col-type" style="color:${typeInfo.color};"><i class="fas ${typeInfo.icon}"></i> ${typeInfo.label}</div>
                    <div class="col col-path" title="${pathOrBucket}">${pathOrBucket}</div>
                    <div class="col col-status">${statusBadge}</div>
                    <div class="col col-actions">
                        <button type="button" class="btn btn-secondary repo-test-btn" data-repo-id="${repo.id}"><i class="fas fa-plug"></i> Testar</button>
                        <button class="btn btn-primary repo-edit-btn" data-repo-id="${repo.id}" ${repo.status === 'pending_initialization' ? 'disabled' : ''}><i class="fas fa-edit"></i> Editar</button>
                        <button class="btn repo-delete-btn" data-repo-id="${repo.id}" data-repo-name="${repo.name}"><i class="fas fa-trash"></i> Excluir</button>
                    </div>
                </div>`;
            }).join('');

            // Anexar listeners diretos aos botões de teste após renderizar
            const testButtons = listBody.querySelectorAll('.repo-test-btn');
            testButtons.forEach(btn => {
                btn.addEventListener('click', async (ev) => {
                    ev.preventDefault();
                    ev.stopPropagation();
                    const repoId = parseInt(btn.dataset.repoId, 10);
                    try {
                        showToast('Testando conexão do repositório...', false, 2000);
                        btn.setAttribute('disabled', 'disabled');
                        const resp = await fetch(`/api/repositories/${repoId}/test`, { method: 'POST' });
                        const raw = await resp.json().catch(() => ({}));
                        const payload = raw?.data || raw;
                        if (resp.ok && (raw.success !== false)) {
                            const summary = payload.summary || `Engine: ${(payload.engine || 'desconhecido').toUpperCase()}\nTipo: ${(payload.repo_type || 'desconhecido').toUpperCase()}`;
                            showToast(`✅ Conexão válida\n${summary}`);
                        } else {
                            const err = raw.error || raw.detail || raw.message || payload.message || 'Falha ao testar repositório.';
                            showToast(`${err}`, true);
                        }
                    } catch (err) {
                        console.error('Erro ao testar repositório:', err);
                        showToast('Erro de conexão ao testar repositório.', true);
                    } finally {
                        try { btn.removeAttribute('disabled'); } catch (e) {}
                    }
                });
            });
        } else {
            listBody.innerHTML = `
                <div class="empty-state" style="text-align:center; padding:40px; color:#a0aec0;">
                    <i class="fas fa-folder-open" style="font-size:48px; margin-bottom:15px; opacity:0.5;"></i>
                    <p>Nenhum repositório configurado.</p>
                    <p style="font-size:0.9em;">Clique em "Novo Repositório" para começar.</p>
                </div>`;
        }

    } catch (error) {
        console.error('Error loading repositories:', error);
    } finally {
        if (!hasPendingRepos) stopRepositoryPolling();
        const btnNewLocal = document.getElementById('btn-new-local-repo');
        const btnNewCloud = document.getElementById('btn-new-cloud-repo');
        if (btnNewLocal) btnNewLocal.removeAttribute('disabled');
        if (btnNewCloud) btnNewCloud.removeAttribute('disabled');
    }
}

window.createLocalRepository = async function(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);

    // Validar senhas
    if (data.encryption_password !== data.encryption_password_confirm) {
        showToast('As senhas de criptografia não conferem!', true);
        return;
    }

    // Montar payload para repositório local
    const payload = {
        name: data.name,
        type: 'local',
        engine: data.engine,
        motor_password: data.encryption_password,
    };

    console.log('📤 Enviando payload de criação local:', payload);

    try {
        const response = await fetch('/api/repositories/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (response.ok) {
            closeCreateLocalModal();
            showToast(result.message || 'Repositório local criado com sucesso!');
            startRepositoryPolling();
        } else {
            showToast(result.detail || 'Falha ao criar repositório local.', true);
        }
    } catch (error) {
        console.error('Erro ao criar repositório local:', error);
        showToast('Erro de conexão ao criar repositório local.', true);
    }
}

window.createCloudRepository = async function(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);

    // Validar senhas
    if (data.encryption_password !== data.encryption_password_confirm) {
        showToast('As senhas de criptografia não conferem!', true);
        return;
    }

    // Montar payload base para repositório cloud
    const payload = {
        name: data.name,
        type: data.type,
        motor_password: data.encryption_password,
        cloud_password: data.encryption_password,
        bucket: data.path, // Campo "path" no form é o bucket para cloud
    };

    // Credenciais específicas por provider
    switch (data.type) {
        case 's3':
            if (data.aws_access_key) payload.access_key = data.aws_access_key;
            if (data.aws_secret_key) payload.secret_key = data.aws_secret_key;
            break;
        case 'b2':
            if (data.b2_account_id) payload.access_key = data.b2_account_id;
            if (data.b2_account_key) payload.secret_key = data.b2_account_key;
            break;
        case 'azure':
            if (data.azure_account_name) payload.access_key = data.azure_account_name;
            if (data.azure_account_key) payload.secret_key = data.azure_account_key;
            break;
        case 'gcs':
            if (data.gcs_project_id) payload.access_key = data.gcs_project_id;
            if (data.gcs_credentials) payload.secret_key = data.gcs_credentials;
            break;
        case 'wasabi':
            if (data.access_key) payload.access_key = data.access_key;
            if (data.secret_key) payload.secret_key = data.secret_key;
            if (data.endpoint) payload.endpoint = data.endpoint;
            break;
    }

    console.log('📤 Enviando payload de criação cloud:', payload);

    try {
        const response = await fetch('/api/repositories/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (response.ok) {
            closeCreateCloudModal();
            showToast(result.message || 'Repositório cloud criado com sucesso!');
            startRepositoryPolling();
        } else {
            showToast(result.detail || 'Falha ao criar repositório cloud.', true);
        }
    } catch (error) {
        console.error('Erro ao criar repositório cloud:', error);
        showToast('Erro de conexão ao criar repositório cloud.', true);
    }
}

window.testLocalConnection = async function() {
    const form = document.getElementById('createLocalForm');
    if (!form) return;
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);

    if (!data.name) {
        showToast('Informe o nome do repositório para testar.', true);
        return;
    }
    if (!data.encryption_password) {
        showToast('Informe a senha de criptografia para testar.', true);
        return;
    }

    const payload = {
        name: data.name,
        engine: data.engine || 'restic',
        type: 'local',
        motor_password: data.encryption_password,
    };

    try {
        const response = await fetch('/api/repositories/test-connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json().catch(() => ({}));
        if (response.ok && (result.success !== false)) {
            showToast(result.message || 'Conexão local testada com sucesso.');
        } else {
            showToast(result.detail || result.message || 'Falha ao testar conexão local.', true);
        }
    } catch (err) {
        console.error('Erro ao testar conexão local:', err);
        showToast('Erro de conexão ao testar repositório local.', true);
    }
};

window.testCloudConnection = async function() {
    const form = document.getElementById('createCloudForm');
    if (!form) return;
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);

    if (!data.name) {
        showToast('Informe o nome do repositório para testar.', true);
        return;
    }
    if (!data.encryption_password) {
        showToast('Informe a senha de criptografia para testar.', true);
        return;
    }
    if (!data.type) {
        showToast('Selecione o provedor para testar.', true);
        return;
    }

    const payload = {
        name: data.name,
        type: data.type,
        motor_password: data.encryption_password,
        cloud_password: data.encryption_password,
        bucket: data.path,
    };

    switch (data.type) {
        case 's3':
            if (data.aws_access_key) payload.access_key = data.aws_access_key;
            if (data.aws_secret_key) payload.secret_key = data.aws_secret_key;
            if (data.aws_region) payload.region = data.aws_region;
            break;
        case 'b2':
            if (data.b2_account_id) payload.access_key = data.b2_account_id;
            if (data.b2_account_key) payload.secret_key = data.b2_account_key;
            break;
        case 'azure':
            if (data.azure_account_name) payload.access_key = data.azure_account_name;
            if (data.azure_account_key) payload.secret_key = data.azure_account_key;
            break;
        case 'gcs':
            if (data.gcs_project_id) payload.access_key = data.gcs_project_id;
            if (data.gcs_credentials) payload.secret_key = data.gcs_credentials;
            break;
        case 'wasabi':
            if (data.access_key) payload.access_key = data.access_key;
            if (data.secret_key) payload.secret_key = data.secret_key;
            if (data.endpoint) payload.endpoint = data.endpoint;
            if (data.region) payload.region = data.region;
            break;
    }

    try {
        const response = await fetch('/api/repositories/test-connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json().catch(() => ({}));
        if (response.ok && (result.success !== false)) {
            showToast(result.message || 'Conexão cloud testada com sucesso.');
        } else {
            showToast(result.detail || result.message || 'Falha ao testar conexão cloud.', true);
        }
    } catch (err) {
        console.error('Erro ao testar conexão cloud:', err);
        showToast('Erro de conexão ao testar repositório cloud.', true);
    }
};

window.createRepository = async function(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);

    // Validar senhas
    if (data.encryption_password !== data.encryption_password_confirm) {
        showToast('As senhas de criptografia não conferem!', true);
        return;
    }

    // Montar payload base
    const payload = {
        name: data.name,
        type: data.type,
        engine: data.engine,
    };

    // Enviar ambas as senhas - motor_password é sempre necessária
    payload.motor_password = data.encryption_password;
    if (data.type !== 'local') {
        payload.cloud_password = data.encryption_password;
    }

    // Adicionar campos específicos por tipo
    const repoType = data.type;

    if (repoType !== 'local') {
        payload.bucket = data.path; // Campo "path" no form é o bucket para cloud
    }

    // Credenciais específicas por provider
    switch (repoType) {
        case 's3':
            if (data.aws_access_key) payload.access_key = data.aws_access_key;
            if (data.aws_secret_key) payload.secret_key = data.aws_secret_key;
            break;
        case 'b2':
            if (data.b2_account_id) payload.access_key = data.b2_account_id;
            if (data.b2_account_key) payload.secret_key = data.b2_account_key;
            break;
        case 'azure':
            if (data.azure_account_name) payload.access_key = data.azure_account_name;
            if (data.azure_account_key) payload.secret_key = data.azure_account_key;
            break;
        case 'gcs':
            if (data.gcs_project_id) payload.access_key = data.gcs_project_id;
            if (data.gcs_credentials) payload.secret_key = data.gcs_credentials;
            break;
        case 'wasabi':
            if (data.access_key) payload.access_key = data.access_key;
            if (data.secret_key) payload.secret_key = data.secret_key;
            if (data.endpoint) payload.endpoint = data.endpoint;
            break;
    }

    console.log('📤 Enviando payload de criação:', payload);

    try {
        const response = await fetch('/api/repositories/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (response.ok) {
            closeCreateModal();
            showToast(result.message || 'Repositório criado com sucesso!');
            startRepositoryPolling();
        } else {
            showToast(result.detail || 'Falha ao criar repositório.', true);
        }
    } catch (error) {
        console.error('Erro ao criar repositório:', error);
        showToast('Erro de conexão ao criar repositório.', true);
    }
}

window.updateRepository = async function(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);
    const repoId = data.id;

    // Montar payload apenas com campos alterados
    const payload = {};
    
    if (data.name) payload.name = data.name;
    if (data.path) payload.bucket = data.path;
    
    // Incluir o tipo para ajudar o backend na validação
    const type = document.getElementById('edit_type').value;
    if (type) payload.type = type;

    // Credenciais - só enviar se preenchidas (não vazias)
    // Usar nomes específicos para garantir que o backend receba exatamente o que foi alterado
    switch (type) {
        case 's3':
            if (data.aws_access_key) payload.aws_access_key = data.aws_access_key;
            if (data.aws_secret_key) payload.aws_secret_key = data.aws_secret_key;
            break;
        case 'b2':
            if (data.b2_account_id) payload.b2_account_id = data.b2_account_id;
            if (data.b2_account_key) payload.b2_account_key = data.b2_account_key;
            break;
        case 'azure':
            if (data.azure_account_name) payload.azure_account_name = data.azure_account_name;
            if (data.azure_account_key) payload.azure_account_key = data.azure_account_key;
            break;
        case 'gcs':
            if (data.gcs_project_id) payload.gcs_project_id = data.gcs_project_id;
            if (data.gcs_credentials) payload.gcs_credentials = data.gcs_credentials;
            break;
        case 'wasabi':
            if (data.access_key) payload.access_key = data.access_key;
            if (data.secret_key) payload.secret_key = data.secret_key;
            if (data.endpoint) payload.endpoint = data.endpoint;
            break;
    }

    // Compatibilidade: manter access_key/secret_key se preenchidos
    if (payload.b2_account_id || payload.aws_access_key || payload.azure_account_name || payload.gcs_project_id) {
        payload.access_key = payload.b2_account_id || payload.aws_access_key || payload.azure_account_name || payload.gcs_project_id;
    }
    if (payload.b2_account_key || payload.aws_secret_key || payload.azure_account_key || payload.gcs_credentials) {
        payload.secret_key = payload.b2_account_key || payload.aws_secret_key || payload.azure_account_key || payload.gcs_credentials;
    }

    console.log('📤 Enviando payload de atualização:', payload);

    try {
        const response = await fetch(`/api/repositories/${repoId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (response.ok) {
            closeEditModal();
            showToast(result.message || 'Repositório atualizado com sucesso.');
            loadRepositories();
        } else {
            showToast(result.detail || 'Falha ao atualizar repositório.', true);
        }
    } catch (error) {
        console.error('Erro ao atualizar repositório:', error);
        showToast('Erro de conexão ao atualizar repositório.', true);
    }
};

window.deleteRepo = async function(id, name) {
    if (!confirm(`Tem certeza que deseja excluir o repositório "${name}"?`)) return;
    
    const keepFolder = confirm(`Deseja MANTER a pasta de dados local?\n\nClique "OK" para manter os arquivos.\nClique "Cancelar" para excluir tudo.`);

    try {
        const response = await fetch(`/api/repositories/${id}?keep_folder=${keepFolder}`, { method: 'DELETE' });
        const result = await response.json();
        if (response.ok) {
            showToast(result.message || `Repositório "${name}" excluído.`);
            loadRepositories();
        } else {
            showToast(result.detail || 'Falha ao excluir.', true);
        }
    } catch (error) {
        showToast('Erro de conexão ao excluir.', true);
    }
}

// ============================================================================
// INITIALIZATION
// ============================================================================

function initRepoPage() {
    console.log('🚀 Inicializando página de repositórios...');

    // Botões do modal de criação - Local e Cloud
    const btnNewLocal = document.getElementById('btn-new-local-repo');
    if (btnNewLocal) btnNewLocal.addEventListener('click', window.openCreateLocalModal);

    const btnNewCloud = document.getElementById('btn-new-cloud-repo');
    if (btnNewCloud) btnNewCloud.addEventListener('click', window.openCreateCloudModal);

    // Botões de fechar modais de criação
    const btnCloseCreateLocal = document.getElementById('btn-close-create-local');
    if (btnCloseCreateLocal) btnCloseCreateLocal.addEventListener('click', window.closeCreateLocalModal);

    const btnCancelCreateLocal = document.getElementById('btn-cancel-create-local');
    if (btnCancelCreateLocal) btnCancelCreateLocal.addEventListener('click', window.closeCreateLocalModal);

    const btnCloseCreateCloud = document.getElementById('btn-close-create-cloud');
    if (btnCloseCreateCloud) btnCloseCreateCloud.addEventListener('click', window.closeCreateCloudModal);

    const btnCancelCreateCloud = document.getElementById('btn-cancel-create-cloud');
    if (btnCancelCreateCloud) btnCancelCreateCloud.addEventListener('click', window.closeCreateCloudModal);

    // Formulários de criação
    const createLocalForm = document.getElementById('createLocalForm');
    if (createLocalForm) createLocalForm.addEventListener('submit', window.createLocalRepository);

    const createCloudForm = document.getElementById('createCloudForm');
    if (createCloudForm) createCloudForm.addEventListener('submit', window.createCloudRepository);

    // Seletor de tipo para cloud - IMPORTANTE: usar evento change
    const createCloudTypeSelect = document.getElementById('create-cloud-type');
    if (createCloudTypeSelect) {
        createCloudTypeSelect.addEventListener('change', updateCreateCloudTypeVisibility);
        // Executar uma vez para estado inicial
        updateCreateCloudTypeVisibility();
    }

    // Botões do modal de edição
    const btnCloseEdit = document.getElementById('btn-close-edit');
    if (btnCloseEdit) btnCloseEdit.addEventListener('click', window.closeEditModal);

    const btnCancelEdit = document.getElementById('btn-cancel-edit');
    if (btnCancelEdit) btnCancelEdit.addEventListener('click', window.closeEditModal);

    // Formulário de edição
    const editForm = document.getElementById('editForm');
    if (editForm) editForm.addEventListener('submit', window.updateRepository);

    // Event delegation para botões dinâmicos na lista
    const repoList = document.getElementById('repo-list');
    if (repoList) {
        repoList.addEventListener('click', async function(e) {
            const testBtn = e.target.closest('.repo-test-btn');
            if (testBtn) {
                const repoId = parseInt(testBtn.dataset.repoId, 10);
                try {
                    showToast('Testando conexão do repositório...', false, 2000);
                    testBtn.setAttribute('disabled', 'disabled');
                    const resp = await fetch(`/api/repositories/${repoId}/test`, { method: 'POST' });
                    const raw = await resp.json().catch(() => ({}));
                    const payload = raw?.data || raw;
                    if (resp.ok && (raw.success !== false)) {
                        const summary = payload.summary || `Engine: ${(payload.engine || 'desconhecido').toUpperCase()}\nTipo: ${(payload.repo_type || 'desconhecido').toUpperCase()}`;
                        showToast(`✅ Conexão válida\n${summary}`);
                    } else {
                        const err = raw.error || raw.detail || raw.message || payload.message || 'Falha ao testar repositório.';
                        showToast(`${err}`, true);
                    }
                } catch (err) {
                    console.error('Erro ao testar repositório:', err);
                    showToast('Erro de conexão ao testar repositório.', true);
                } finally {
                    try { testBtn.removeAttribute('disabled'); } catch (e) {}
                }
                return;
            }

            const editBtn = e.target.closest('.repo-edit-btn');
            if (editBtn) {
                const repoId = parseInt(editBtn.dataset.repoId, 10);
                window.openEditModal(repoId);
                return;
            }

            const deleteBtn = e.target.closest('.repo-delete-btn');
            if (deleteBtn) {
                const repoId = parseInt(deleteBtn.dataset.repoId, 10);
                const repoName = deleteBtn.dataset.repoName;
                window.deleteRepo(repoId, repoName);
            }
        });
    }

    // Carregar repositórios
    loadRepositories();

    console.log('✅ Página de repositórios inicializada');
}

//
