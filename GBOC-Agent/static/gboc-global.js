/*
==============================================================================
GBOC System v14.6.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
/**
 * GBOC Agent - Global Functions
 * Funções utilitárias globais para todas as páginas
 */

console.log('✅ GBOC Global Functions carregado - 14.6.0');

// Auto-inject modal framework if not present
(function autoInjectModalSystem() {
    if (!window.GBOCModal && !document.getElementById('gboc-modal-script')) {
        const m = document.createElement('script');
        m.id = 'gboc-modal-script';
        m.src = '/static/gboc-modal.js';
        if (document.head) {
            document.head.appendChild(m);
        } else {
            document.addEventListener('DOMContentLoaded', () => document.head.appendChild(m));
        }
    }
})();

// Modern Logout function
async function handleLogout() {
    console.log('🚪 handleLogout chamado');
    const ok = window.gbocConfirm ? await window.gbocConfirm('Deseja realmente encerrar sua sessão e sair do sistema?', {
        title: 'Encerrar Sessão',
        icon: 'fas fa-right-from-bracket',
        type: 'warning',
        confirmText: 'Sair do Sistema'
    }) : confirm('Deseja realmente sair do sistema?');

    if (ok) {
        console.log('✅ Confirmação de logout aceita');
        try {
            if (window.fetch) await fetch('/api/auth/logout', { method: 'POST' }).catch(() => {});
        } catch (e) {}
        localStorage.removeItem('gboc_token');
        localStorage.removeItem('gboc_server_token');
        localStorage.removeItem('gboc_user');
        document.cookie = 'gboc_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
        document.cookie = 'gboc_server_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
        console.log('🔄 Redirecionando para login...');
        window.location.href = '/login.html';
    } else {
        console.log('❌ Logout cancelado pelo usuário');
    }
}

// Format helpers
function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function fmtUptime(sec) {
    if (!sec || sec < 0) return '--';
    const days = Math.floor(sec / 86400);
    const hours = Math.floor((sec % 86400) / 3600);
    const mins = Math.floor((sec % 3600) / 60);
    
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
}

function fmtBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
}

function fmtDate(dateStr) {
    if (!dateStr) return '--';
    try {
        const d = new Date(dateStr);
        return d.toLocaleString('pt-BR');
    } catch (e) {
        return String(dateStr);
    }
}

function timeAgo(dateStr) {
    if (!dateStr) return '--';
    try {
        const now = Date.now();
        const then = new Date(dateStr).getTime();
        const diff = Math.floor((now - then) / 1000);
        
        if (diff < 60) return 'agora';
        if (diff < 3600) return Math.floor(diff / 60) + 'm atrás';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h atrás';
        return Math.floor(diff / 86400) + 'd atrás';
    } catch (e) {
        return String(dateStr);
    }
}

// Get current user info
function getCurrentUser() {
    try {
        const userStr = localStorage.getItem('gboc_user');
        return userStr ? JSON.parse(userStr) : null;
    } catch (e) {
        return null;
    }
}

// Display user info in header
function displayUserInfo() {
    const user = getCurrentUser();
    if (!user) return;
    
    // Try to find user display element
    const userDisplay = document.getElementById('userDisplay');
    if (userDisplay) {
        userDisplay.innerHTML = `
            <i class="fas fa-user-circle"></i>
            <span>${user.display_name || user.username}</span>
        `;
    }
}

// Auto-load user info on page load
document.addEventListener('DOMContentLoaded', function() {
    displayUserInfo();
});

