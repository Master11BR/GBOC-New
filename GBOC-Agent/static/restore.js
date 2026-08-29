/*
==============================================================================
GBOC System v13.2.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
// ============================================================================
// GBOC Agent v9.0 - restore.js
// UI para restauração de arquivos de snapshots
// ============================================================================

let currentRepositoryId = null;
let currentSnapshotId = null;
let currentPath = '/';
let restorePollingInterval = null;
let selectedFiles = new Set();  // caminhos selecionados pelo usuário

function classifyRestoreError(message) {
    const raw = String(message || 'Erro desconhecido');
    const m = raw.toLowerCase();

    if (m.includes('wrong password') || m.includes('senha') || m.includes('password')) {
        return { title: 'Falha de autenticação', user: 'Senha/chave do repositório inválida para este motor.', detail: raw };
    }
    if (m.includes('not initialized') || m.includes('não está inicializado')) {
        return { title: 'Repositório não inicializado', user: 'O repositório ainda não foi inicializado. Execute um backup primeiro.', detail: raw };
    }
    if (m.includes('repositório não encontrado') || m.includes('repository') && m.includes('not found')) {
        return { title: 'Repositório não encontrado', user: 'O repositório selecionado não foi encontrado no agente.', detail: raw };
    }
    if (m.includes('acesso negado') || m.includes('permission denied') || m.includes('access denied')) {
        return { title: 'Acesso negado', user: 'Credenciais/permissões insuficientes para acessar o repositório.', detail: raw };
    }
    if (m.includes('timeout')) {
        return { title: 'Timeout de conexão', user: 'A operação excedeu o tempo limite ao acessar o repositório.', detail: raw };
    }
    if (m.includes('snapshot')) {
        return { title: 'Falha ao listar snapshots', user: 'Não foi possível listar snapshots com a configuração atual.', detail: raw };
    }

    return { title: 'Falha no módulo de restauração', user: 'Erro técnico ao acessar restauração. Verifique configuração do repositório e motor.', detail: raw };
}

function showRestoreDiagnostic(message) {
    const block = document.getElementById('restore-diagnostic-block');
    const title = document.getElementById('restore-diagnostic-title');
    const msg = document.getElementById('restore-diagnostic-message');
    const detail = document.getElementById('restore-diagnostic-detail');
    if (!block || !title || !msg || !detail) return;

    const d = classifyRestoreError(message);
    title.textContent = d.title;
    msg.textContent = d.user;
    detail.textContent = d.detail;
    block.style.display = 'block';
}

function hideRestoreDiagnostic() {
    const block = document.getElementById('restore-diagnostic-block');
    if (block) block.style.display = 'none';
}

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Inicializando página de restauração...');
    
    loadRepositories();
    attachEventListeners();
    checkActiveRestoreOnLoad();

    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission().catch(() => {});
    }
    
    console.log('✅ Página de restauração inicializada');
});

async function checkActiveRestoreOnLoad() {
    try {
        const res = await fetch('/api/restore/active');
        if (res.ok) {
            const data = await res.json();
            if (data.status === 'running' && data.active) {
                openRestoreModal(data.active.id);
                return;
            }
        }

        const cached = localStorage.getItem('gboc_active_restore_id');
        if (cached) {
            const stRes = await fetch(`/api/restore/status/${cached}`);
            if (stRes.ok) {
                const stData = await stRes.json();
                const info = stData.data || stData;
                if (info.status === 'running' || info.status === 'preparing') {
                    openRestoreModal(cached);
                } else {
                    localStorage.removeItem('gboc_active_restore_id');
                }
            }
        }
    } catch (e) {}
}

// ============================================================================
// EVENT LISTENERS
// ============================================================================

function attachEventListeners() {
    // Repositório
    const repoSelect = document.getElementById('restore-repository');
    if (repoSelect) {
        repoSelect.addEventListener('change', onRepositoryChange);
    }

    // Snapshot
    const snapSelect = document.getElementById('restore-snapshot');
    if (snapSelect) {
        snapSelect.addEventListener('change', onSnapshotChange);
    }

    // Navegação de arquivos
    const btnUp = document.getElementById('btn-file-up');
    if (btnUp) {
        btnUp.addEventListener('click', navigateUp);
    }

    const btnRefresh = document.getElementById('btn-file-refresh');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', refreshFileList);
    }

    // Restauração
    const btnRestore = document.getElementById('btn-start-restore');
    if (btnRestore) {
        btnRestore.addEventListener('click', startRestore);
    }

    // Histórico
    const btnHistory = document.getElementById('btn-restore-history');
    if (btnHistory) {
        btnHistory.addEventListener('click', showRestoreHistory);
    }

    // Modais
    const btnCloseRestore = document.getElementById('btn-close-restore-modal');
    if (btnCloseRestore) {
        btnCloseRestore.addEventListener('click', closeRestoreModal);
    }

    const btnCloseHistory = document.getElementById('btn-close-history-modal');
    if (btnCloseHistory) {
        btnCloseHistory.addEventListener('click', closeHistoryModal);
    }

    // Diagnóstico
    const btnDiagnose = document.getElementById('btn-diagnose-restore');
    if (btnDiagnose) {
        btnDiagnose.addEventListener('click', diagnoseSnapshots);
    }

    // Browse de pasta de destino
    const btnBrowseDest = document.getElementById('btn-browse-dest');
    if (btnBrowseDest) {
        btnBrowseDest.addEventListener('click', openDestBrowse);
    }
}

// ============================================================================
// REPOSITÓRIOS
// ============================================================================

async function loadRepositories() {
    try {
        const [repoRes, dupRes] = await Promise.allSettled([
            fetch('/api/repositories/'),
            fetch('/api/duplicati-native/backups')
        ]);

        let repos = [];
        if (repoRes.status === 'fulfilled' && repoRes.value.ok) {
            const data = await repoRes.value.json();
            repos = data.snapshots || data.data || (Array.isArray(data) ? data : []);
        }

        let dupBackups = [];
        if (dupRes.status === 'fulfilled' && dupRes.value.ok) {
            const data = await dupRes.value.json();
            dupBackups = data.items || [];
        }

        const mappedDup = dupBackups.map(item => {
            const b = item.Backup || item;
            const bId = String(b.ID || item.id || '1');
            return {
                id: `dup_native_${bId}`,
                name: b.Name || item.name || `Duplicati Backup #${bId}`,
                type: 'duplicati_native',
                is_duplicati_native: true,
                duplicati_id: bId
            };
        });

        const allRepos = [...repos, ...mappedDup];
        const select = document.getElementById('restore-repository');
        
        if (!select) return;
        
        select.innerHTML = '<option value="">Selecione um repositório ou backup...</option>';
        
        if (allRepos && allRepos.length > 0) {
            allRepos.forEach(repo => {
                const opt = document.createElement('option');
                opt.value = repo.id;
                opt.textContent = `${repo.name} (${(repo.type || 'local').toUpperCase()})`;
                select.appendChild(opt);
            });
        } else {
            select.innerHTML = '<option value="">Nenhum repositório disponível</option>';
        }
    } catch (e) {
        console.error('Erro ao carregar repositórios:', e);
        showToast('Erro ao carregar repositórios', 'error');
    }
}

async function onRepositoryChange(e) {
    currentRepositoryId = e.target.value;
    currentSnapshotId = null;
    currentPath = '/';
    
    if (!currentRepositoryId) {
        clearSnapshots();
        clearFiles();
        return;
    }
    
    await loadSnapshots();
}

// ============================================================================
// SNAPSHOTS
// ============================================================================

async function loadSnapshots() {
    const select = document.getElementById('restore-snapshot');
    if (!select) return;
    
    select.innerHTML = '<option value="">Carregando snapshots...</option>';
    select.disabled = true;
    clearFiles();
    hideRestoreDiagnostic();
    
    try {
        let snapshotsUrl = `/api/restore/snapshots/${currentRepositoryId}`;
        if (String(currentRepositoryId).startsWith('dup_native_')) {
            const dupId = String(currentRepositoryId).replace('dup_native_', '');
            snapshotsUrl = `/api/duplicati-native/backups/${dupId}/filesets`;
        }

        const res = await fetch(snapshotsUrl);
        if (!res.ok) {
            const error = await res.json().catch(() => ({}));
            const detail = error.detail || error.message || 'Falha ao carregar snapshots';
            throw new Error(detail);
        }
        const data = await res.json();

        if (!select) return;

        select.innerHTML = '<option value="">Selecione um snapshot...</option>';

        if (data.snapshots && data.snapshots.length > 0) {
            data.snapshots.forEach(snap => {
                const opt = document.createElement('option');
                // usar ID completo para operações internas
                opt.value = snap.full_id || snap.id;
                const date = gbocFormatDateTime(snap.time);
                const labelId = snap.short_id || (snap.id ? String(snap.id).substring(0, 8) : 'snapshot');
                opt.textContent = `${labelId}... (${date})`;
                select.appendChild(opt);
            });
        } else {
            showToast('Nenhum snapshot encontrado neste repositório', 'info');
        }
    } catch (e) {
        console.error('Erro ao carregar snapshots:', e);
        if (select) {
            select.innerHTML = '<option value="">Erro ao carregar snapshots</option>';
        }
        showToast('Erro ao carregar snapshots: ' + e.message, 'error');
    }
}

function clearSnapshots() {
    const select = document.getElementById('restore-snapshot');
    if (select) {
        select.innerHTML = '<option value="">Selecione um snapshot...</option>';
    }
    clearFiles();
}

async function onSnapshotChange(e) {
    currentSnapshotId = e.target.value;
    currentPath = '/';
    selectedFiles.clear();

    if (!currentSnapshotId) {
        clearFiles();
        return;
    }

    await loadFiles();
}

// ============================================================================
// ARQUIVOS
// ============================================================================

async function loadFiles(path = '/') {
    if (!currentRepositoryId || !currentSnapshotId) {
        showToast('Selecione repositório e snapshot primeiro', 'warning');
        return;
    }

    // Mostrar loading
    const list = document.getElementById('restore-file-list');
    if (list) {
        list.innerHTML = '<div style="padding:20px; color:var(--text-muted); text-align:center;"><i class="fas fa-spinner fa-spin"></i> Carregando arquivos...</div>';
    }

    try {
        hideRestoreDiagnostic();
        currentPath = path;

        const url = `/api/restore/files/${currentRepositoryId}/${currentSnapshotId}?path=${encodeURIComponent(path)}`;
        const res = await fetch(url);
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || 'Falha ao carregar arquivos');
        }

        const data = await res.json();
        renderFileList(data.files || []);

        // Atualizar caminho exibido
        const pathDisplay = document.getElementById('restore-current-path');
        if (pathDisplay) {
            pathDisplay.textContent = path || '/';
        }
    } catch (e) {
        console.error('Erro ao carregar arquivos:', e);
        const fileList = document.getElementById('restore-file-list');
        if (fileList) {
            fileList.innerHTML = `<div style="padding:20px; color:var(--danger); text-align:center;"><i class="fas fa-exclamation-triangle"></i> ${e.message}</div>`;
        }
        showRestoreDiagnostic(e.message);
        showToast('Erro ao carregar arquivos: ' + e.message, 'error');
    }
}

function renderFileList(files) {
    const list = document.getElementById('restore-file-list');
    if (!list) return;

    list.innerHTML = '';

    if (!files || files.length === 0) {
        list.innerHTML = '<div style="padding:20px; color:var(--text-muted); text-align:center;">Nenhum arquivo encontrado</div>';
        return;
    }

    // Cabeçalho com "selecionar todos"
    const header = document.createElement('div');
    header.style.cssText = 'display:flex; align-items:center; padding:8px 12px; border-bottom:2px solid var(--border); background:var(--bg-card); gap:10px; font-size:0.85em; color:var(--text-muted); font-weight:600;';
    header.innerHTML = `
        <input type="checkbox" id="chk-select-all" title="Selecionar todos" style="width:16px;height:16px;cursor:pointer;accent-color:var(--primary);">
        <span style="flex:1;">Nome</span>
        <span style="min-width:70px; text-align:right;">Tamanho</span>
    `;
    list.appendChild(header);

    document.getElementById('chk-select-all')?.addEventListener('change', function() {
        const checked = this.checked;
        list.querySelectorAll('.file-row-chk').forEach(chk => {
            chk.checked = checked;
            const path = chk.dataset.path;
            if (path) { checked ? selectedFiles.add(path) : selectedFiles.delete(path); }
        });
        updateSelectionCount();
    });

    files.forEach(file => {
        const row = document.createElement('div');
        row.className = 'restore-file-row';
        row.style.cssText = 'display:flex; align-items:center; padding:9px 12px; border-bottom:1px solid var(--border); gap:10px; transition:background 0.15s;';

        const icon = file.is_dir ? 'fa-folder' : 'fa-file-alt';
        const iconColor = file.is_dir ? 'var(--warning)' : 'var(--text-muted)';
        const isChecked = selectedFiles.has(file.path) ? 'checked' : '';

        row.innerHTML = `
            <input type="checkbox" class="file-row-chk" data-path="${file.path}" ${isChecked}
                   style="width:16px;height:16px;cursor:pointer;accent-color:var(--primary);" title="Selecionar este item">
            <i class="fas ${icon}" style="color:${iconColor}; width:18px; text-align:center; flex-shrink:0;"></i>
            <span style="flex:1; color:var(--text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${file.path}">${file.name}</span>
            <span style="color:var(--text-muted); font-size:0.82em; min-width:70px; text-align:right;">${file.is_dir ? '—' : formatBytes(file.size || 0)}</span>
        `;

        // Checkbox: atualiza seleção
        const chk = row.querySelector('.file-row-chk');
        chk.addEventListener('change', function(e) {
            e.stopPropagation();
            if (this.checked) selectedFiles.add(file.path);
            else selectedFiles.delete(file.path);
            updateSelectionCount();
        });

        // Clique na linha: navegar em pastas ou selecionar arquivo
        row.addEventListener('click', function(e) {
            if (e.target.type === 'checkbox') return;
            if (file.is_dir) {
                loadFiles(file.path);
            } else {
                chk.checked = !chk.checked;
                if (chk.checked) selectedFiles.add(file.path);
                else selectedFiles.delete(file.path);
                updateSelectionCount();
            }
        });

        row.addEventListener('mouseenter', () => row.style.background = 'var(--bg-hover, rgba(0,0,0,0.04))');
        row.addEventListener('mouseleave', () => row.style.background = 'transparent');

        list.appendChild(row);
    });

    updateSelectionCount();
}

function updateSelectionCount() {
    const btn = document.getElementById('btn-start-restore');
    if (!btn) return;
    const n = selectedFiles.size;
    if (n > 0) {
        btn.innerHTML = `<i class="fas fa-play"></i> Restaurar ${n} item${n > 1 ? 's' : ''} selecionado${n > 1 ? 's' : ''}`;
    } else {
        btn.innerHTML = '<i class="fas fa-play"></i> Iniciar Restauração';
    }
}

function navigateUp() {
    if (currentPath === '/' || !currentPath) {
        showToast('Já está no diretório raiz', 'info');
        return;
    }
    
    const parts = currentPath.split('/').filter(p => p);
    parts.pop();
    const parentPath = '/' + parts.join('/');
    loadFiles(parentPath);
}

function refreshFileList() {
    loadFiles(currentPath);
}

function clearFiles() {
    selectedFiles.clear();
    const list = document.getElementById('restore-file-list');
    if (list) {
        list.innerHTML = '<div style="padding:20px; color:var(--text-muted); text-align:center;">Selecione um snapshot para ver os arquivos</div>';
    }

    const pathDisplay = document.getElementById('restore-current-path');
    if (pathDisplay) pathDisplay.value = '/';
    updateSelectionCount();
}

// ============================================================================
// RESTAURAÇÃO
// ============================================================================

async function startRestore() {
    if (!currentRepositoryId || !currentSnapshotId) {
        showToast('Selecione repositório e snapshot', 'warning');
        return;
    }

    const targetPath = document.getElementById('restore-target-path').value.trim();
    if (!targetPath) {
        showToast('Especifique o caminho de destino', 'warning');
        return;
    }

    // Usar arquivos selecionados; se nenhum, restaurar o caminho atual inteiro
    const filesToRestore = selectedFiles.size > 0 ? Array.from(selectedFiles) : [currentPath || '/'];
    const label = selectedFiles.size > 0 ? `${selectedFiles.size} item(s) selecionado(s)` : `pasta "${currentPath || '/'}"`;

    if (!confirm(`Restaurar ${label} para:\n${targetPath}`)) return;

    try {
        hideRestoreDiagnostic();
        const payload = {
            repository_id: currentRepositoryId,
            snapshot_id: currentSnapshotId,
            files: filesToRestore,
            target_path: targetPath,
            options: {}
        };

        const res = await fetch('/api/restore/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || 'Falha ao iniciar restauração');
        }

        const data = await res.json();
        const restoreId = data.restore_id || data.id;
        localStorage.setItem('gboc_active_restore_id', restoreId);
        showToast('Restauração iniciada!', 'success');
        openRestoreModal(restoreId);
    } catch (e) {
        console.error('Erro ao iniciar restauração:', e);
        showRestoreDiagnostic(e.message);
        showToast('Erro ao iniciar restauração: ' + e.message, 'error');
    }
}

// ============================================================================
// MONITORAMENTO DE RESTAURAÇÃO
// ============================================================================

async function openRestoreModal(restoreId) {
    const modal = document.getElementById('restore-monitor-modal');
    if (!modal) return;
    
    modal.classList.add('active');
    
    // Iniciar polling
    if (restorePollingInterval) clearInterval(restorePollingInterval);
    restorePollingInterval = setInterval(() => updateRestoreStatus(restoreId), 2000);
    
    // Primeira atualização
    await updateRestoreStatus(restoreId);
}

async function updateRestoreStatus(restoreId) {
    try {
        const res = await fetch(`/api/restore/status/${restoreId}`);
        if (!res.ok) throw new Error('Falha ao obter status');
        
        const data = await res.json();
        const status = data.data || {};
        
        // Atualizar progresso
        const progress = status.progress || 0;
        const progressBar = document.getElementById('restore-progress-bar');
        if (progressBar) {
            progressBar.style.width = `${progress}%`;
            progressBar.textContent = `${progress}%`;
        }
        
        // Atualizar status
        const statusBadge = document.getElementById('restore-status-badge');
        if (statusBadge) {
            statusBadge.textContent = (status.status || 'unknown').toUpperCase();
            statusBadge.className = `badge badge-${getStatusClass(status.status)}`;
        }
        
        // Atualizar estatísticas
        const filesRestored = document.getElementById('restore-files-restored');
        if (filesRestored) {
            filesRestored.textContent = `${status.files_restored || 0} arquivos`;
        }
        
        const bytesRestored = document.getElementById('restore-bytes-restored');
        if (bytesRestored) {
            bytesRestored.textContent = formatBytes(status.bytes_restored || 0);
        }
        
        const duration = document.getElementById('restore-duration');
        if (duration) {
            duration.textContent = formatDuration(status.duration_seconds || 0);
        }

        // Atualizar logs em tempo real
        const logsBox = document.getElementById('restore-live-logs');
        if (logsBox) {
            const logs = Array.isArray(status.logs) ? status.logs : [];
            if (logs.length) {
                logsBox.textContent = logs.map(l => {
                    const ts = l.timestamp ? gbocFormatDateTime(l.timestamp) : '—';
                    return `[${ts}] ${l.message}`;
                }).join('\n');
                logsBox.scrollTop = logsBox.scrollHeight;
            } else {
                logsBox.textContent = 'Sem logs até o momento...';
            }
        }

        // Se finalizou, parar polling
        if (status.status && !['running', 'preparing'].includes(status.status)) {
            if (restorePollingInterval) {
                clearInterval(restorePollingInterval);
                restorePollingInterval = null;
            }
            localStorage.removeItem('gboc_active_restore_id');
            if ((status.status === 'completed' || status.status === 'success') && progressBar) {
                progressBar.style.width = '100%';
                progressBar.textContent = '100%';
            }
            const isSuccess = (status.status === 'completed' || status.status === 'success');
            const toastType = isSuccess ? 'success' : (status.status === 'partial' ? 'warning' : 'error');
            showToast(`Restauração finalizada: ${status.status}`, toastType);

            if ('Notification' in window && Notification.permission === 'granted') {
                try {
                    new Notification('GBOC - Restauração Concluída', {
                        body: `Processo #${restoreId} finalizado com status: ${status.status} (${status.files_restored || 0} arquivos).`,
                        icon: '/favicon.ico'
                    });
                } catch(exN) {}
            }
        }
    } catch (e) {
        console.error('Erro ao atualizar status:', e);
    }
}

function getStatusClass(status) {
    const statusMap = {
        'running': 'info',
        'preparing': 'info',
        'completed': 'success',
        'success': 'success',
        'partial': 'warning',
        'failed': 'danger',
        'cancelled': 'warning',
        'interrupted': 'danger'
    };
    return statusMap[status] || 'secondary';
}

function closeRestoreModal() {
    const modal = document.getElementById('restore-monitor-modal');
    if (modal) {
        modal.classList.remove('active');
    }
    
    if (restorePollingInterval) {
        clearInterval(restorePollingInterval);
        restorePollingInterval = null;
    }
}

// ============================================================================
// HISTÓRICO
// ============================================================================

async function showRestoreHistory() {
    try {
        const res = await fetch('/api/restore/history?limit=50');
        if (!res.ok) throw new Error('Falha ao carregar histórico');
        
        const data = await res.json();
        renderRestoreHistory(data.history || []);
        
        const modal = document.getElementById('restore-history-modal');
        if (modal) {
            modal.classList.add('active');
        }
    } catch (e) {
        console.error('Erro ao carregar histórico:', e);
        showToast('Erro ao carregar histórico', 'error');
    }
}

function renderRestoreHistory(history) {
    const list = document.getElementById('restore-history-list');
    if (!list) return;

    list.innerHTML = '';

    if (!history || history.length === 0) {
        list.innerHTML = '<div style="padding:20px; color:var(--text-muted); text-align:center;">Nenhuma restauração registrada</div>';
        return;
    }

    // Cabeçalho
    const header = document.createElement('div');
    header.style.cssText = 'display:grid; grid-template-columns:1fr 90px 80px 80px 1fr 90px; gap:8px; padding:12px 15px; background:var(--bg-card); border-bottom:2px solid var(--border); font-weight:600; color:var(--text); font-size:0.85em;';
    header.innerHTML = `<div>Data</div><div>Status</div><div>Arquivos</div><div>Duração</div><div>Destino</div><div style="text-align:right;">Ações</div>`;
    list.appendChild(header);

    history.forEach(item => {
        const row = document.createElement('div');
        row.style.cssText = 'display:grid; grid-template-columns:1fr 90px 80px 80px 1fr 90px; gap:8px; padding:10px 15px; border-bottom:1px solid var(--border); align-items:center; color:var(--text); font-size:0.82em;';

        const date = gbocFormatDateTime(item.created_at);
        const normalizedStatus = item.status === 'success' ? 'completed' : item.status;
        const statusColor = normalizedStatus === 'completed'
            ? 'var(--success)'
            : (normalizedStatus === 'failed'
                ? 'var(--danger)'
                : (normalizedStatus === 'partial' ? 'var(--warning)' : 'var(--text-muted)'));
        const duration = formatDuration(item.duration_seconds || 0);

        row.innerHTML = `
            <div>${date}</div>
            <div><span style="color:${statusColor}; font-weight:600;">${normalizedStatus}</span></div>
            <div>${item.files_restored || 0}</div>
            <div>${duration}</div>
            <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${item.target_path}">${item.target_path}</div>
            <div style="text-align:right;">
                <button class="btn btn-sm btn-secondary" onclick="openRestoreModal(${item.id})" style="padding:3px 7px;font-size:0.78em;">
                    <i class="fas fa-eye"></i> Monitor
                </button>
            </div>
        `;
        list.appendChild(row);
    });
}

function closeHistoryModal() {
    const modal = document.getElementById('restore-history-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

// ============================================================================
// UTILITIES
// ============================================================================

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatDuration(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return [h, m, s].map(v => v.toString().padStart(2, '0')).join(':');
}

function showToast(msg, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `gboc-toast ${type === 'error' ? 'error' : ''}`;
    toast.textContent = msg;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// ============================================================================
// MODAL EVENT LISTENERS
// ============================================================================

// Fechar modal de restauração
const btnCloseRestoreBtn = document.getElementById('btn-close-restore-modal-btn');
if (btnCloseRestoreBtn) {
    btnCloseRestoreBtn.addEventListener('click', closeRestoreModal);
}

// Fechar modal de histórico
const btnCloseHistoryBtn = document.getElementById('btn-close-history-modal-btn');
if (btnCloseHistoryBtn) {
    btnCloseHistoryBtn.addEventListener('click', closeHistoryModal);
}

// Fechar ao clicar fora do modal (restauração)
const restoreModal = document.getElementById('restore-monitor-modal');
if (restoreModal) {
    restoreModal.addEventListener('click', function(e) {
        if (e.target === restoreModal) {
            closeRestoreModal();
        }
    });
}

// Fechar ao clicar fora do modal (histórico)
const historyModal = document.getElementById('restore-history-modal');
if (historyModal) {
    historyModal.addEventListener('click', function(e) {
        if (e.target === historyModal) {
            closeHistoryModal();
        }
    });
}

// Fechar modal de restauração ao pressionar ESC
document.addEventListener('keydown', function(e) {
    const modal = document.getElementById('restore-monitor-modal');
    if (modal && modal.classList.contains('active') && e.key === 'Escape') {
        closeRestoreModal();
    }
});

// Fechar modal de histórico ao pressionar ESC
document.addEventListener('keydown', function(e) {
    const modal = document.getElementById('restore-history-modal');
    if (modal && modal.classList.contains('active') && e.key === 'Escape') {
        closeHistoryModal();
    }
});

// ============================================================================
// BROWSE PASTA DE DESTINO
// ============================================================================

let destBrowsePath = null;

async function openDestBrowse() {
    const modal = document.getElementById('dest-browse-modal');
    if (!modal) return;
    destBrowsePath = null;
    modal.classList.add('active');
    await loadDestFolders(null);
}

function closeDestBrowse() {
    const modal = document.getElementById('dest-browse-modal');
    if (modal) modal.classList.remove('active');
}

async function loadDestFolders(path) {
    destBrowsePath = path;
    const list = document.getElementById('dest-folder-list');
    const pathDisplay = document.getElementById('dest-current-path');
    if (!list) return;

    list.innerHTML = '<div style="padding:16px; color:var(--text-muted); text-align:center;"><i class="fas fa-spinner fa-spin"></i> Carregando...</div>';

    try {
        const url = path ? `/api/fs/browse?path=${encodeURIComponent(path)}` : '/api/fs/browse';
        const res = await fetch(url);
        if (!res.ok) throw new Error('Falha ao listar pastas');
        const data = await res.json();

        if (pathDisplay) pathDisplay.value = data.path || path || '/';
        list.innerHTML = '';

        if (!data.items || data.items.length === 0) {
            list.innerHTML = '<div style="padding:16px; color:var(--text-muted); text-align:center;">Pasta vazia</div>';
            return;
        }

        data.items.forEach(item => {
            const row = document.createElement('div');
            row.style.cssText = 'display:flex; align-items:center; padding:9px 14px; border-bottom:1px solid var(--border); cursor:pointer; gap:10px; transition:background 0.15s;';
            row.innerHTML = `
                <i class="fas fa-folder" style="color:var(--warning); flex-shrink:0;"></i>
                <span style="flex:1; color:var(--text);">${item.name}</span>
                <i class="fas fa-chevron-right" style="color:var(--text-muted); font-size:0.75em;"></i>
            `;
            row.addEventListener('click', () => loadDestFolders(item.path));
            row.addEventListener('mouseenter', () => row.style.background = 'var(--bg-hover, rgba(0,0,0,0.04))');
            row.addEventListener('mouseleave', () => row.style.background = 'transparent');
            list.appendChild(row);
        });
    } catch (e) {
        list.innerHTML = `<div style="padding:16px; color:var(--danger); text-align:center;"><i class="fas fa-exclamation-triangle"></i> ${e.message}</div>`;
    }
}

function selectDestFolder() {
    const pathDisplay = document.getElementById('dest-current-path');
    const targetInput = document.getElementById('restore-target-path');
    if (pathDisplay && targetInput) {
        targetInput.value = pathDisplay.value || destBrowsePath || '';
    }
    closeDestBrowse();
}

// ============================================================================
// DIAGNÓSTICO
// ============================================================================

async function diagnoseSnapshots() {
    if (!currentRepositoryId) {
        showToast('Selecione um repositório para diagnosticar', 'warning');
        return;
    }

    try {
        const res = await fetch(`/api/restore/diagnose/${currentRepositoryId}`);
        const data = await res.json();

        const repoName = data.repository?.name || data.repository?.id || currentRepositoryId;
        const repoEngine = String(data.repository?.engine || 'desconhecido').toUpperCase();
        const repoType = String(data.repository?.type || 'desconhecido').toUpperCase();

        if (res.ok && data.status === 'success') {
            hideRestoreDiagnostic();
            showToast(`Diagnóstico OK: ${repoName} (${repoEngine}/${repoType})`, 'success');
            return;
        }

        const err = data.message || data.detail || 'Falha no diagnóstico';
        const hint = data.hint ? ` Dica: ${data.hint}` : '';
        showRestoreDiagnostic(`Repositório: ${repoName}\nEngine: ${repoEngine}\nTipo: ${repoType}\n${err}${hint}`);
        showToast('Diagnóstico detectou problema', 'warning');
    } catch (e) {
        console.error('Erro no diagnóstico de snapshots:', e);
        showRestoreDiagnostic(e.message || 'Erro ao executar diagnóstico preemptivo');
        showToast('Erro ao executar diagnóstico', 'error');
    }
}
