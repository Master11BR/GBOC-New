// ==============================================================================
// GBOC System v13.2.0 Enterprise Edition
// Module: Users & Roles & Audit Controller (users.js)
// ==============================================================================

var USERS_API = '/api/v1/users';
var cachedRoles = [];
var cachedTenants = [];
var availablePermissions = [];
var permissionsGrouped = {};

document.addEventListener('DOMContentLoaded', function () {
    loadAllUsersModule();
});

function switchUsersTab(tabId) {
    document.querySelectorAll('.tabs-header .tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    
    const btn = document.getElementById('tab-btn-' + tabId.replace('tab-', ''));
    const pane = document.getElementById(tabId);
    if (btn) btn.classList.add('active');
    if (pane) pane.classList.add('active');
}

async function loadAllUsersModule() {
    await Promise.allSettled([
        loadPermissionsCatalog(),
        loadMyProfile(),
        loadRoles(),
        loadTenantsDropdown(),
        loadUsers(),
        loadAudit()
    ]);
}

async function loadPermissionsCatalog() {
    try {
        const r = await fetch(USERS_API + '/permissions');
        const d = await r.json();
        availablePermissions = d.permissions || [];
        permissionsGrouped = d.grouped_by_module || {};
    } catch (e) {
        console.error('loadPermissionsCatalog:', e);
    }
}

async function loadMyProfile() {
    try {
        const r = await fetch(USERS_API + '/status');
        const d = await r.json();
        const u = d.user || {};
        if (document.getElementById('my-avatar')) document.getElementById('my-avatar').textContent = (u.display_name || u.username || 'A')[0].toUpperCase();
        if (document.getElementById('my-name')) document.getElementById('my-name').textContent = u.display_name || u.username || 'Administrador Master';
        if (document.getElementById('my-username')) document.getElementById('my-username').textContent = u.username ? '@' + u.username : '@admin';
        const role = u.role || 'admin';
        if (document.getElementById('my-role')) document.getElementById('my-role').innerHTML = '<span class="badge-crit">' + role.toUpperCase() + '</span>';
    } catch (e) {
        console.error('loadMyProfile:', e);
    }
}

async function loadTenantsDropdown() {
    const sel = document.getElementById('usr-tenant');
    if (!sel) return;
    try {
        const r = await fetch('/api/v1/tenant/organizations');
        const d = await r.json();
        cachedTenants = d.organizations || [];
        
        sel.innerHTML = '<option value="">Nenhuma (Administrador Global)</option>' + 
            cachedTenants.map(t => `<option value="${t.id}">${t.name} (${t.id})</option>`).join('');
    } catch (e) {
        console.error('loadTenantsDropdown:', e);
    }
}

async function loadRoles() {
    try {
        const r = await fetch(USERS_API + '/roles');
        const d = await r.json();
        cachedRoles = d.roles || [];
        
        if (document.getElementById('kpi-roles')) document.getElementById('kpi-roles').textContent = cachedRoles.length;
        
        const tbody = document.getElementById('roles-table-body');
        if (!tbody) return;

        if (!cachedRoles.length) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:20px;color:var(--text-muted)">Nenhum nível cadastrado</td></tr>';
            return;
        }

        tbody.innerHTML = cachedRoles.map(role => {
            const isSys = role.is_system;
            const sysBadge = isSys ? '<span class="badge-info"><i class="fas fa-lock"></i> Sistema</span>' : '<span class="badge-purple"><i class="fas fa-palette"></i> Customizado</span>';
            
            let permsHtml = '';
            if (role.permissions.includes('*')) {
                permsHtml = '<span class="badge-crit"><i class="fas fa-star"></i> Todas (Superusuário)</span>';
            } else if (role.permissions.length === 0) {
                permsHtml = '<span class="badge-warn">Nenhuma Permissão</span>';
            } else {
                permsHtml = `<span class="badge-ok"><i class="fas fa-check-circle"></i> ${role.permissions.length} Permissões</span>`;
            }

            const deleteBtn = isSys ? 
                `<button class="btn btn-sm btn-secondary" disabled title="Nível do Sistema não pode ser excluído"><i class="fas fa-lock"></i></button>` :
                `<button class="btn btn-sm btn-danger" onclick="deleteRole(${role.id})" title="Excluir Nível"><i class="fas fa-trash"></i></button>`;

            return `<tr>
                <td><strong>${role.name}</strong></td>
                <td><span style="font-weight:600;color:var(--primary)">${role.display_name}</span></td>
                <td style="font-size:0.84em;color:var(--text-muted)">${role.description || '-'}</td>
                <td>${sysBadge}</td>
                <td><strong style="color:var(--text)">${role.user_count || 0}</strong> usuário(s)</td>
                <td>${permsHtml}</td>
                <td style="text-align:right">
                    <div style="display:flex;gap:4px;justify-content:flex-end">
                        <button class="btn btn-sm btn-secondary" onclick="openRoleModal(${role.id})" title="Editar Permissões"><i class="fas fa-edit"></i></button>
                        ${deleteBtn}
                    </div>
                </td>
            </tr>`;
        }).join('');

        updateUserRoleDropdown();
    } catch (e) {
        console.error('loadRoles:', e);
    }
}

function updateUserRoleDropdown() {
    const sel = document.getElementById('usr-role');
    if (!sel) return;
    if (!cachedRoles.length) {
        sel.innerHTML = '<option value="admin">Administrador Total</option>';
        return;
    }
    sel.innerHTML = cachedRoles.map(r => `<option value="${r.name}">${r.display_name} (${r.name})</option>`).join('');
}

async function loadUsers() {
    try {
        const r = await fetch(USERS_API);
        const d = await r.json();
        const users = d.users || [];
        if (document.getElementById('kpi-users')) document.getElementById('kpi-users').textContent = users.length;
        if (document.getElementById('kpi-sessions')) document.getElementById('kpi-sessions').textContent = d.active_sessions || 1;

        const tbody = document.getElementById('users-table-body');
        if (!tbody) return;

        if (!users.length) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-muted)">Nenhum usuário cadastrado.</td></tr>';
            return;
        }

        tbody.innerHTML = users.map(u => {
            const active = u.status === 'active' || u.is_active !== false;
            const statusBadge = active ? '<span class="badge-ok">ATIVO</span>' : '<span class="badge-crit">INATIVO</span>';
            const roleObj = cachedRoles.find(r => r.name === u.role);
            const roleName = roleObj ? roleObj.display_name : (u.role || 'ADMIN').toUpperCase();
            const roleBadge = u.role === 'admin' ? 'badge-crit' : 'badge-info';
            const tenantName = u.tenant_name || 'Global Admin';

            return `<tr>
                <td>
                    <div style="display:flex;align-items:center;gap:10px">
                        <div style="width:32px;height:32px;border-radius:8px;background:rgba(0,240,255,0.1);color:var(--primary);display:flex;align-items:center;justify-content:center;font-weight:700">
                            ${(u.display_name || u.username)[0].toUpperCase()}
                        </div>
                        <div>
                            <strong style="font-size:0.92em">@${u.username}</strong>
                        </div>
                    </div>
                </td>
                <td>${u.display_name || u.username}</td>
                <td><span class="${roleBadge}">${roleName}</span></td>
                <td><strong style="color:var(--primary);font-size:0.9em">${tenantName}</strong></td>
                <td>${statusBadge}</td>
                <td style="font-size:0.82em;color:var(--text-muted)">${u.last_login || 'Agora'}</td>
                <td style="text-align:right">
                    <div style="display:flex;gap:4px;justify-content:flex-end">
                        <button class="btn btn-sm btn-secondary" onclick="editUser(${u.id})" title="Editar Usuário"><i class="fas fa-edit"></i></button>
                        <button class="btn btn-sm btn-danger" onclick="deleteUser(${u.id})" title="Excluir"><i class="fas fa-trash"></i></button>
                    </div>
                </td>
            </tr>`;
        }).join('');
    } catch (e) {
        console.error('loadUsers:', e);
    }
}

async function loadAudit() {
    try {
        const r = await fetch(USERS_API + '/audit');
        const d = await r.json();
        const logs = d.logs || d.entries || [];
        const tbody = document.getElementById('audit-table-body');
        if (!tbody) return;

        if (!logs.length) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--text-muted)">Nenhum registro de auditoria.</td></tr>';
            return;
        }

        tbody.innerHTML = logs.map(l => `
            <tr>
                <td><strong style="color:var(--primary)">@${l.username || 'admin'}</strong></td>
                <td><span class="badge-info">${l.action}</span></td>
                <td style="font-size:0.85em">${l.details || '—'}</td>
                <td style="font-family:monospace">${l.ip || '127.0.0.1'}</td>
                <td style="font-size:0.82em;color:var(--text-muted)">${l.timestamp}</td>
            </tr>
        `).join('');
    } catch (e) {
        console.error('loadAudit:', e);
    }
}

function openUserModal(userId = null) {
    document.getElementById('usr-id').value = userId || '';
    document.getElementById('usr-display').value = '';
    document.getElementById('usr-username').value = '';
    document.getElementById('usr-username').disabled = false;
    document.getElementById('usr-password').value = '';
    document.getElementById('usr-active').checked = true;
    if (document.getElementById('usr-tenant')) document.getElementById('usr-tenant').value = '';
    
    loadTenantsDropdown().then(() => {
        if (userId) {
            document.getElementById('modal-user-title').textContent = 'Editar Usuário';
            document.getElementById('usr-pw-hint').textContent = '(opcional se não quiser alterar)';
            document.getElementById('usr-status-group').style.display = 'block';

            fetch(USERS_API).then(r => r.json()).then(d => {
                const u = (d.users || []).find(x => x.id === userId);
                if (u) {
                    document.getElementById('usr-display').value = u.display_name || '';
                    document.getElementById('usr-username').value = u.username || '';
                    document.getElementById('usr-username').disabled = true;
                    document.getElementById('usr-role').value = u.role || 'admin';
                    document.getElementById('usr-active').checked = u.status === 'active';
                    if (document.getElementById('usr-tenant')) document.getElementById('usr-tenant').value = u.tenant_id || '';
                }
            });
        } else {
            document.getElementById('modal-user-title').textContent = 'Novo Usuário';
            document.getElementById('usr-pw-hint').textContent = '(obrigatória)';
            document.getElementById('usr-status-group').style.display = 'none';
        }
    });

    document.getElementById('user-modal').classList.add('show');
}

function closeUserModal() { document.getElementById('user-modal').classList.remove('show'); }

async function saveUser() {
    const userId = document.getElementById('usr-id').value;
    const display_name = document.getElementById('usr-display').value.trim();
    const username = document.getElementById('usr-username').value.trim();
    const password = document.getElementById('usr-password').value;
    const role = document.getElementById('usr-role').value;
    const is_active = document.getElementById('usr-active').checked;
    const tenant_id = document.getElementById('usr-tenant') ? document.getElementById('usr-tenant').value : null;

    if (!userId && (!username || !password)) {
        alert('Preencha nome de usuário e senha');
        return;
    }

    closeUserModal();

    try {
        let r;
        if (userId) {
            const payload = { 
                display_name: display_name || username, 
                role, 
                status: is_active ? 'active' : 'inactive', 
                tenant_id: tenant_id || null 
            };
            
            // Se senha foi preenchida, altera a senha primeiro
            if (password) {
                await fetch(USERS_API + '/' + userId + '/password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ new_password: password })
                });
            }

            r = await fetch(USERS_API + '/' + userId, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } else {
            r = await fetch(USERS_API, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    display_name: display_name || username, 
                    username, 
                    password, 
                    role, 
                    tenant_id: tenant_id || null 
                })
            });
        }

        const d = await r.json();
        if (!r.ok) {
            alert('Erro: ' + (d.detail || d.message || 'Falha ao salvar usuário'));
            return;
        }
        loadAllUsersModule();
    } catch (e) {
        alert('Erro: ' + e.message);
    }
}

function editUser(id) { openUserModal(id); }

async function deleteUser(id) {
    if (!confirm('Excluir este usuário permanentemente?')) return;
    try {
        const r = await fetch(USERS_API + '/' + id, { method: 'DELETE' });
        const d = await r.json();
        if (!r.ok) { alert('Erro: ' + (d.detail || 'Falha ao excluir')); return; }
        loadAllUsersModule();
    } catch (e) { alert('Erro: ' + e.message); }
}

function openRoleModal(roleId = null) {
    document.getElementById('role-id').value = roleId || '';
    document.getElementById('role-name').value = '';
    document.getElementById('role-name').disabled = false;
    document.getElementById('role-display').value = '';
    document.getElementById('role-desc').value = '';

    renderPermissionsMatrix([]);

    if (roleId) {
        document.getElementById('modal-role-title').textContent = 'Editar Nível de Acesso';
        const role = cachedRoles.find(r => r.id === roleId);
        if (role) {
            document.getElementById('role-name').value = role.name;
            document.getElementById('role-name').disabled = true;
            document.getElementById('role-display').value = role.display_name;
            document.getElementById('role-desc').value = role.description || '';
            renderPermissionsMatrix(role.permissions || []);
        }
    } else {
        document.getElementById('modal-role-title').textContent = 'Novo Nível Customizado';
    }

    document.getElementById('role-modal').classList.add('show');
}

function closeRoleModal() { document.getElementById('role-modal').classList.remove('show'); }

function renderPermissionsMatrix(selectedPerms = []) {
    const container = document.getElementById('permissions-matrix-container');
    if (!container) return;
    const isAll = selectedPerms.includes('*');

    container.innerHTML = Object.entries(permissionsGrouped).map(([mod, perms]) => {
        return `<div class="perm-card">
            <div class="perm-card-header">${mod}</div>
            ${perms.map(p => {
                const checked = isAll || selectedPerms.includes(p.id) ? 'checked' : '';
                return `<label class="perm-item">
                    <input type="checkbox" class="perm-chk" value="${p.id}" ${checked}>
                    <span>${p.name}</span>
                </label>`;
            }).join('')}
        </div>`;
    }).join('');
}

async function saveRole() {
    const roleId = document.getElementById('role-id').value;
    const name = document.getElementById('role-name').value.trim();
    const display_name = document.getElementById('role-display').value.trim();
    const description = document.getElementById('role-desc').value.trim();

    const selected = Array.from(document.querySelectorAll('.perm-chk:checked')).map(c => c.value);

    if (!name || !display_name) {
        alert('Preencha o identificador e o nome do nível de acesso.');
        return;
    }

    closeRoleModal();

    try {
        let r;
        if (roleId) {
            r = await fetch(USERS_API + '/roles/' + roleId, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ display_name, description, permissions: selected })
            });
        } else {
            r = await fetch(USERS_API + '/roles', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, display_name, description, permissions: selected })
            });
        }

        const d = await r.json();
        if (!r.ok) { alert('Erro: ' + (d.detail || 'Falha ao salvar nível')); return; }
        loadAllUsersModule();
    } catch (e) { alert('Erro: ' + e.message); }
}

async function deleteRole(roleId) {
    if (!confirm('Excluir este nível de acesso customizado?')) return;
    try {
        const r = await fetch(USERS_API + '/roles/' + roleId, { method: 'DELETE' });
        const d = await r.json();
        if (!r.ok) { alert('Erro: ' + (d.detail || 'Falha ao excluir')); return; }
        loadAllUsersModule();
    } catch (e) { alert('Erro: ' + e.message); }
}

async function changeMyPassword() {
    const cur = document.getElementById('pw-current').value;
    const n1 = document.getElementById('pw-new').value;
    const n2 = document.getElementById('pw-confirm').value;
    const msg = document.getElementById('pw-msg');

    if (!cur || !n1 || !n2) {
        msg.className = 'pw-msg err';
        msg.textContent = 'Preencha todos os campos de senha.';
        return;
    }
    if (n1 !== n2) {
        msg.className = 'pw-msg err';
        msg.textContent = 'A nova senha e a confirmação não coincidem.';
        return;
    }

    try {
        const r = await fetch(USERS_API + '/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: cur, new_password: n1 })
        });
        const d = await r.json();
        if (!r.ok) {
            msg.className = 'pw-msg err';
            msg.textContent = d.detail || 'Erro ao alterar senha.';
            return;
        }
        msg.className = 'pw-msg ok';
        msg.textContent = '✓ Senha alterada com sucesso!';
        document.getElementById('pw-current').value = '';
        document.getElementById('pw-new').value = '';
        document.getElementById('pw-confirm').value = '';
    } catch (e) {
        msg.className = 'pw-msg err';
        msg.textContent = 'Erro: ' + e.message;
    }
}

// Exportar globalmente para eventos onclick
window.loadAllUsersModule = loadAllUsersModule;
window.openUserModal = openUserModal;
window.closeUserModal = closeUserModal;
window.saveUser = saveUser;
window.editUser = editUser;
window.deleteUser = deleteUser;
window.openRoleModal = openRoleModal;
window.closeRoleModal = closeRoleModal;
window.saveRole = saveRole;
window.deleteRole = deleteRole;
window.changeMyPassword = changeMyPassword;
window.loadTenantsDropdown = loadTenantsDropdown;
