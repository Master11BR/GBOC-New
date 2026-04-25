/**
 * GBOC Agent - Unified Sidebar Module
 * Sistema unificado de sidebar para todas as páginas
 */

class UnifiedSidebar {
    constructor() {
        this.sidebarHtml = null;
        this.isLoaded = false;
        this.currentPage = this.getCurrentPage();
    }

    /**
     * Inicializa o sidebar na página atual
     */
    async initialize() {
        try {
            // Evita corrida entre auto-init e init manual por página
            if (window.__gbocSidebarInitializing) return;
            if (window.__gbocSidebarInitialized) {
                this.updateActiveLink();
                return;
            }
            window.__gbocSidebarInitializing = true;

            console.log('🔵 UnifiedSidebar: Inicializando...');

            // Carregar HTML do sidebar
            await this.loadSidebarHtml();

            // Injetar sidebar no DOM
            this.injectSidebar();

            // Configurar navegação ativa
            this.updateActiveLink();

            // Configurar event listeners
            this.setupEventListeners();
            this.setupSidebarRuntime();

            this.isLoaded = true;
            window.__gbocSidebarInitialized = true;
            console.log('✅ UnifiedSidebar: Inicialização concluída');

            // Setup sidebar auth (user info + logout button)
            if (typeof gbocSetupSidebarAuth === 'function') {
                gbocSetupSidebarAuth();
            }

        } catch (error) {
            console.error('❌ UnifiedSidebar: Erro na inicialização:', error);
            this.createFallbackSidebar();
        } finally {
            window.__gbocSidebarInitializing = false;
        }
    }

    setupSidebarRuntime() {
        const saved = localStorage.getItem('gboc-theme') || 'dark';
        document.documentElement.setAttribute('data-theme', saved);
        if (typeof updateThemeButton === 'function') {
            updateThemeButton(saved);
        }
    }

    /**
     * Carrega o HTML do sidebar do arquivo _sidebar.html
     */
    async loadSidebarHtml() {
        try {
            const response = await fetch('/static/_sidebar.html');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            this.sidebarHtml = await response.text();
            console.log('✅ Sidebar HTML carregado');
        } catch (error) {
            console.error('❌ Erro ao carregar sidebar HTML:', error);
            throw error;
        }
    }

    /**
     * Injeta o sidebar no DOM da página
     */
    injectSidebar() {
        const appDiv = document.querySelector('.app');
        if (!appDiv) {
            throw new Error('Elemento .app não encontrado');
        }

        // Remover sidebar existente se houver
        const existingSidebar = appDiv.querySelector('aside.sidebar');
        if (existingSidebar) {
            existingSidebar.remove();
        }

        // Inserir novo sidebar no início do .app
        appDiv.insertAdjacentHTML('afterbegin', this.sidebarHtml);
        console.log('✅ Sidebar injetado no DOM');
    }

    /**
     * Atualiza o link ativo no sidebar baseado na página atual
     */
    updateActiveLink() {
        const navLinks = document.querySelectorAll('.nav-link');
        navLinks.forEach(link => link.classList.remove('active'));

        let activeFound = false;
        navLinks.forEach(link => {
            const href = link.getAttribute('href');
            if (this.isActiveLink(href)) {
                link.classList.add('active');
                activeFound = true;
            }
        });

        // fallback defensivo: marca dashboard se nada casar
        if (!activeFound) {
            const home = document.querySelector('.nav-link[href="/"]');
            if (home) home.classList.add('active');
        }

        console.log('✅ Link ativo atualizado:', window.location.pathname);
    }

    /**
     * Verifica se um link deve estar ativo baseado na página atual
     */
    isActiveLink(href) {
        if (!href) return false;

        const normalize = (p) => {
            if (!p) return '/';
            const x = p.toLowerCase();
            return x.endsWith('/') && x !== '/' ? x.slice(0, -1) : x;
        };

        const currentPath = normalize(window.location.pathname);
        const target = normalize(href);

        // Dashboard também representa páginas unificadas
        if (target === '/') {
            return currentPath === '/' || currentPath === '/index.html' ||
                   currentPath === '/overview.html' || currentPath === '/statistics.html';
        }

        return currentPath === target;
    }

    /**
     * Configura event listeners do sidebar
     */
    setupEventListeners() {
        const navLinks = document.querySelectorAll('.nav-link');
        navLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                const clickedLink = e.target.closest('.nav-link');
                if (!clickedLink) return;
                navLinks.forEach(l => l.classList.remove('active'));
                clickedLink.classList.add('active');
            });
        });
    }

    /**
     * Identifica a página atual baseada na URL
     */
    getCurrentPage() {
        const path = window.location.pathname;

        if (path === '/' || path === '/index.html') return 'dashboard';
        if (path.includes('/repositories')) return 'repositories';
        if (path.includes('/tasks')) return 'tasks';
        if (path.includes('/restore')) return 'restore';
        if (path.includes('/logs')) return 'logs';
        if (path.includes('/overview')) return 'overview';
        if (path.includes('/statistics')) return 'statistics';
        if (path.includes('/settings')) return 'settings';

        return 'unknown';
    }

    /**
     * Cria um sidebar básico como fallback em caso de erro
     */
    createFallbackSidebar() {
        console.warn('⚠️ Criando sidebar de fallback');

        const fallbackHtml = `
        <aside class="sidebar">
            <div class="sidebar-header">
                <a href="/" class="logo">
                    <i class="fas fa-shield-alt logo-icon"></i> GBOC Agent
                </a>
            </div>
            <nav class="nav">
                <a href="/" class="nav-link ${this.currentPage === 'dashboard' ? 'active' : ''}">
                    <i class="fas fa-home nav-icon"></i> Dashboard
                </a>
                <a href="/repositories.html" class="nav-link ${this.currentPage === 'repositories' ? 'active' : ''}">
                    <i class="fas fa-server nav-icon"></i> Repositórios
                </a>
                <a href="/tasks.html" class="nav-link ${this.currentPage === 'tasks' ? 'active' : ''}">
                    <i class="fas fa-tasks nav-icon"></i> Tarefas
                </a>
                <a href="/restore.html" class="nav-link ${this.currentPage === 'restore' ? 'active' : ''}">
                    <i class="fas fa-undo nav-icon"></i> Restauração
                </a>
                <a href="/duplicati-native.html" class="nav-link">
                    <i class="fas fa-plug nav-icon"></i> Duplicati Nativo
                </a>
                <a href="/logs.html" class="nav-link ${this.currentPage === 'logs' ? 'active' : ''}">
                    <i class="fas fa-file-alt nav-icon"></i> Logs
                </a>
                <a href="/overview.html" class="nav-link ${this.currentPage === 'overview' ? 'active' : ''}">
                    <i class="fas fa-chart-line nav-icon"></i> Overview
                </a>
                <a href="/statistics.html" class="nav-link ${this.currentPage === 'statistics' ? 'active' : ''}">
                    <i class="fas fa-chart-bar nav-icon"></i> Estatísticas
                </a>
                <a href="/settings.html" class="nav-link ${this.currentPage === 'settings' ? 'active' : ''}">
                    <i class="fas fa-cogs nav-icon"></i> Configurações
                </a>
                <a href="#" class="nav-link" onclick="gbocLogout(); return false;">
                    <i class="fas fa-sign-out-alt nav-icon"></i> Sair
                </a>
            </nav>
        </aside>`;

        const appDiv = document.querySelector('.app');
        if (appDiv) {
            appDiv.insertAdjacentHTML('afterbegin', fallbackHtml);
            console.log('✅ Sidebar de fallback criado');
        }
    }

    /**
     * Método público para recarregar o sidebar (útil após navegação SPA)
     */
    async reload() {
        console.log('🔄 Recarregando sidebar...');
        this.currentPage = this.getCurrentPage();
        await this.initialize();
    }
}

// Instância global do sidebar
window.unifiedSidebar = new UnifiedSidebar();

// Funções globais usadas pelo HTML do sidebar (injetado dinamicamente)
window.toggleTheme = function() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('gboc-theme', next);
    if (typeof window.updateThemeButton === 'function') {
        window.updateThemeButton(next);
    }
};

window.updateThemeButton = function(theme) {
    const icon = document.getElementById('themeIcon');
    const label = document.getElementById('themeLabel');
    if (icon && label) {
        icon.className = theme === 'dark' ? 'fas fa-moon' : 'fas fa-sun';
        label.textContent = theme === 'dark' ? 'Tema Escuro' : 'Tema Claro';
    }
};

window._gbocShowSidebarUser = function(u) {
    const el = document.getElementById('sidebarUsername');
    const info = document.getElementById('sidebarUserInfo');
    const btn = document.getElementById('logoutBtn');
    const link = document.getElementById('sidebarLogoutLink');
    if (el) el.textContent = (u && (u.display_name || u.username)) || '';
    if (info) info.style.display = 'block';
    if (btn) btn.style.display = 'block';
    if (link) link.style.display = 'flex';
};

window.gbocSetupSidebarAuth = function() {
    const token = localStorage.getItem('gboc_token');
    const user = localStorage.getItem('gboc_user');
    const btn = document.getElementById('logoutBtn');
    const link = document.getElementById('sidebarLogoutLink');

    if (user) {
        try {
            const u = JSON.parse(user);
            window._gbocShowSidebarUser(u);
        } catch (e) {
            if (btn) btn.style.display = 'block';
            if (link) link.style.display = 'flex';
        }
    } else if (token) {
        if (btn) btn.style.display = 'block';
        if (link) link.style.display = 'flex';
    }

    fetch('/api/auth/status')
        .then(r => r.json())
        .then(data => {
            if (data && data.authenticated && data.user) {
                window._gbocShowSidebarUser(data.user);
            } else if (data && data.auth_enabled) {
                if (btn) btn.style.display = 'block';
                if (link) link.style.display = 'flex';
            }
        })
        .catch(() => {
            if (token) {
                if (btn) btn.style.display = 'block';
                if (link) link.style.display = 'flex';
            }
        });
};

window.gbocLogout = async function() {
    if (!confirm('Deseja realmente sair?')) return;
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {}
    localStorage.removeItem('gboc_token');
    localStorage.removeItem('gboc_user');
    document.cookie = 'gboc_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
    window.location.href = '/login.html';
};

// Inicialização automática quando DOM estiver pronto
document.addEventListener('DOMContentLoaded', async function() {
    await window.unifiedSidebar.initialize();
});

// Helper global para padronização de data/hora (evita mistura UTC/local)
window.gbocFormatDateTime = function(value) {
    if (!value) return '—';
    try {
        let s = String(value);
        // Se vier sem timezone (YYYY-MM-DDTHH:mm:ss[.fff]), tratar como UTC
        if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(s)) {
            s += 'Z';
        }
        const d = new Date(s);
        if (Number.isNaN(d.getTime())) return String(value);
        return d.toLocaleString('pt-BR', {
            timeZone: 'America/Sao_Paulo',
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit', second: '2-digit'
        });
    } catch {
        return String(value);
    }
};

console.log('✅ UnifiedSidebar module loaded');
