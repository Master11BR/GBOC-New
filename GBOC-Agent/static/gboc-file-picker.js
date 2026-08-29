/**
 * GBOC System v13.2.0 Enterprise Edition
 * Component: Modern Visual File Picker & Tree Explorer
 */

(function() {
    let _currentPath = null;
    let _selectedPaths = new Set();
    let _onConfirmCallback = null;

    function _initPickerDOM() {
        if (document.getElementById('gboc-fp-modal')) return;

        // Injetar CSS
        if (!document.getElementById('gboc-fp-style')) {
            const link = document.createElement('link');
            link.id = 'gboc-fp-style';
            link.rel = 'stylesheet';
            link.href = '/static/gboc-file-picker.css';
            document.head.appendChild(link);
        }

        const modal = document.createElement('div');
        modal.id = 'gboc-fp-modal';
        modal.className = 'gboc-fp-modal';
        modal.onclick = function(e) {
            if (e.target === modal) closeGbocFilePicker();
        };

        modal.innerHTML = `
            <div class="gboc-fp-dialog" onclick="event.stopPropagation()">
                <div class="gboc-fp-header">
                    <h3><i class="fas fa-folder-tree"></i> Explorador Visual de Arquivos & Pastas</h3>
                    <button class="gboc-hw-btn-icon" onclick="closeGbocFilePicker()"><i class="fas fa-times"></i></button>
                </div>

                <!-- Quick Presets -->
                <div class="gboc-fp-presets">
                    <span class="gboc-fp-preset-title"><i class="fas fa-bolt"></i> Atalhos:</span>
                    <button type="button" class="gboc-fp-preset-btn" onclick="addPickerPreset('docs')">
                        <i class="fas fa-user-folder"></i> Documentos & Desktop
                    </button>
                    <button type="button" class="gboc-fp-preset-btn" onclick="addPickerPreset('db')">
                        <i class="fas fa-database"></i> Bancos de Dados
                    </button>
                    <button type="button" class="gboc-fp-preset-btn" onclick="addPickerPreset('web')">
                        <i class="fas fa-globe"></i> IIS / Web (wwwroot)
                    </button>
                    <button type="button" class="gboc-fp-preset-btn" onclick="addPickerPreset('programdata')">
                        <i class="fas fa-cogs"></i> ProgramData
                    </button>
                </div>

                <!-- Breadcrumbs -->
                <div class="gboc-fp-crumbs" id="gboc-fp-crumbs-bar">
                    <span class="gboc-fp-crumb active" onclick="browsePickerPath(null)"><i class="fas fa-server"></i> Unidades Raiz</span>
                </div>

                <!-- Items List -->
                <div class="gboc-fp-body" id="gboc-fp-items-list">
                    <div style="text-align:center; padding:30px; color:#94a3b8;">
                        <i class="fas fa-spinner fa-spin" style="font-size:1.5rem; color:#38bdf8; margin-bottom:8px;"></i>
                        <div>Carregando estrutura de pastas...</div>
                    </div>
                </div>

                <!-- Selected Badges -->
                <div class="gboc-fp-selected-bar">
                    <div class="gboc-fp-selected-title">
                        <span>Pastas Selecionadas (<span id="gboc-fp-count">0</span>):</span>
                        <a href="javascript:void(0)" onclick="clearPickerSelection()" style="color:#f87171;font-size:0.75rem;text-decoration:none">Limpar Todas</a>
                    </div>
                    <div class="gboc-fp-badges-list" id="gboc-fp-badges">
                        <span style="color:#64748b;font-size:0.8rem">Nenhuma pasta marcada</span>
                    </div>
                </div>

                <!-- Footer -->
                <div class="gboc-fp-footer">
                    <button type="button" class="btn btn-secondary" onclick="closeGbocFilePicker()">Cancelar</button>
                    <button type="button" class="btn btn-primary" onclick="confirmPickerSelection()"><i class="fas fa-check"></i> Aplicar Seleção</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
    }

    async function _fetchBrowse(path) {
        let url = '/api/fs/browse';
        if (path) {
            url += `?path=${encodeURIComponent(path)}`;
        }
        try {
            const resp = await fetch(url);
            return await resp.json();
        } catch (err) {
            console.error('[FilePicker] Erro no browse:', err);
            return { success: false, error: err.message };
        }
    }

    window.browsePickerPath = async function(path) {
        _currentPath = path;
        const itemsContainer = document.getElementById('gboc-fp-items-list');
        const crumbsContainer = document.getElementById('gboc-fp-crumbs-bar');
        if (!itemsContainer) return;

        itemsContainer.innerHTML = `
            <div style="text-align:center; padding:30px; color:#94a3b8;">
                <i class="fas fa-spinner fa-spin" style="font-size:1.5rem; color:#38bdf8; margin-bottom:8px;"></i>
                <div>Navegando em ${path || 'Raiz'}...</div>
            </div>
        `;

        // Atualizar Breadcrumbs
        let crumbHtml = `<span class="gboc-fp-crumb ${!path ? 'active' : ''}" onclick="browsePickerPath(null)"><i class="fas fa-server"></i> Unidades Raiz</span>`;
        if (path) {
            const parts = path.split(/[\\/]/).filter(p => p);
            let accum = '';
            parts.forEach((p, idx) => {
                accum += (idx === 0 && path.includes(':')) ? p + '\\' : (accum.endsWith('\\') ? '' : '\\') + p;
                const isLast = idx === parts.length - 1;
                crumbHtml += ` <span style="color:#64748b">/</span> <span class="gboc-fp-crumb ${isLast ? 'active' : ''}" onclick="browsePickerPath('${accum.replace(/\\/g, '\\\\')}')">${p}</span>`;
            });
        }
        if (crumbsContainer) crumbsContainer.innerHTML = crumbHtml;

        const data = await _fetchBrowse(path);
        const items = data.items || [];

        if (items.length === 0) {
            itemsContainer.innerHTML = `<div style="text-align:center; padding:30px; color:#64748b;">Pasta vazia ou sem permissão de leitura.</div>`;
            return;
        }

        let html = '';
        items.forEach(item => {
            const fullPath = item.path;
            const isDir = item.is_dir;
            const isChecked = _selectedPaths.has(fullPath);
            const iconClass = !path ? 'fas fa-hdd gboc-fp-item-icon drive' : (isDir ? 'fas fa-folder gboc-fp-item-icon' : 'fas fa-file gboc-fp-item-icon file');

            html += `
                <div class="gboc-fp-row">
                    <div class="gboc-fp-item-info" onclick="${isDir ? `browsePickerPath('${fullPath.replace(/\\/g, '\\\\')}')` : ''}">
                        <i class="${iconClass}"></i>
                        <span class="gboc-fp-item-name">${item.name}</span>
                    </div>
                    <input type="checkbox" class="gboc-fp-checkbox" ${isChecked ? 'checked' : ''} onchange="togglePathSelection('${fullPath.replace(/\\/g, '\\\\')}', this.checked)">
                </div>
            `;
        });

        itemsContainer.innerHTML = html;
    };

    window.togglePathSelection = function(path, isChecked) {
        if (isChecked) {
            _selectedPaths.add(path);
        } else {
            _selectedPaths.delete(path);
        }
        _updateSelectedBadges();
    };

    window.addPickerPreset = function(presetType) {
        if (presetType === 'docs') {
            _selectedPaths.add('C:\\Users');
        } else if (presetType === 'db') {
            _selectedPaths.add('C:\\Program Files\\PostgreSQL');
            _selectedPaths.add('C:\\ProgramData\\MySQL');
        } else if (presetType === 'web') {
            _selectedPaths.add('C:\\inetpub\\wwwroot');
        } else if (presetType === 'programdata') {
            _selectedPaths.add('C:\\ProgramData');
        }
        _updateSelectedBadges();
        if (_currentPath) browsePickerPath(_currentPath);
    };

    window.clearPickerSelection = function() {
        _selectedPaths.clear();
        _updateSelectedBadges();
        if (_currentPath !== undefined) browsePickerPath(_currentPath);
    };

    function _updateSelectedBadges() {
        const countEl = document.getElementById('gboc-fp-count');
        const listEl = document.getElementById('gboc-fp-badges');
        if (!listEl) return;

        if (countEl) countEl.textContent = _selectedPaths.size;

        if (_selectedPaths.size === 0) {
            listEl.innerHTML = `<span style="color:#64748b;font-size:0.8rem">Nenhuma pasta marcada</span>`;
            return;
        }

        let html = '';
        _selectedPaths.forEach(p => {
            html += `
                <span class="gboc-fp-badge">
                    <i class="fas fa-folder"></i> ${p}
                    <span class="gboc-fp-badge-remove" onclick="togglePathSelection('${p.replace(/\\/g, '\\\\')}', false); browsePickerPath(_currentPath)">&times;</span>
                </span>
            `;
        });
        listEl.innerHTML = html;
    }

    window.openGbocFilePicker = function(initialPaths, onConfirm) {
        _initPickerDOM();
        _selectedPaths.clear();
        _onConfirmCallback = onConfirm;

        if (initialPaths) {
            const rawList = Array.isArray(initialPaths) ? initialPaths : initialPaths.split('\n');
            rawList.map(p => p.trim()).filter(p => p).forEach(p => _selectedPaths.add(p));
        }

        _updateSelectedBadges();
        const modal = document.getElementById('gboc-fp-modal');
        if (modal) {
            modal.classList.add('show');
            browsePickerPath(null);
        }
    };

    window.closeGbocFilePicker = function() {
        const modal = document.getElementById('gboc-fp-modal');
        if (modal) modal.classList.remove('show');
    };

    window.confirmPickerSelection = function() {
        const selectedArray = Array.from(_selectedPaths);
        if (_onConfirmCallback && typeof _onConfirmCallback === 'function') {
            _onConfirmCallback(selectedArray);
        }
        closeGbocFilePicker();
    };
})();
