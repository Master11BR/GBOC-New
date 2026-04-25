/**
 * GBOC Agent - Unified Sidebar Module
 * Sistema unificado de sidebar para todas as páginas
 */

// ============================================================================
// 1. CONFIGURAÇÕES E CONSTANTES
// ============================================================================
const SIDEBAR_CONFIG = {
    SELECTORS: {
        APP: '.app',
        NAV_LINK: '.nav-link',
        SIDEBAR: 'aside.sidebar',
        THEME_ICON: 'themeIcon',
        THEME_LABEL: 'themeLabel',
        USER_NAME: 'sidebarUsername',
        USER_INFO: 'sidebarUserInfo',
        LOGOUT_BTN: 'logoutBtn',
        LOGOUT_LINK: 'sidebarLogoutLink'
    },
    STORAGE: {
        THEME: 'gboc-theme',
        TOKEN: 'gboc_token',
        USER: 'gboc_user'
    },
    API: {
        AUTH_STATUS: '/api/auth/status',
        AUTH_LOGOUT: '/api/auth/logout'
    },
    ASSETS: {
        SIDEBAR_HTML: '/static/_sidebar.html'
    }
};

// ============================================================================
// 2. CLASSE PRINCIPAL
// ============================================================================
class UnifiedSidebar {
    constructor() {
        this._sidebarHtml = null;
        this._isLoaded = false;
        this.currentPage = this._getCurrentPage();
    }

    /**
     * Inicializa o sidebar na página atual
     * @returns {Promise<void>}
     */
    async initialize() {
        try {
            // Evita corrida entre auto-init e init manual por página
            if (window.__gbocSidebarInitializing) return;
            if (window.__gbocSidebarInitialized) {
                this._updateActiveLink();
                return;
            }
            window.__gbocSidebarInitializing = true;

            console.log('🔵 UnifiedSidebar: Inicializando...');

            // Carregar HTML do sidebar
            await this._loadSidebarHtml();

            // Injetar sidebar no DOM
            this._injectSidebar();

            // Configurar navegação ativa
            this._updateActiveLink();

            // Configurar event listeners
            this._setupEventListeners();
            this._setupSidebarRuntime();

            this._isLoaded = true;
            window.__gbocSidebarInitialized = true;
            console.log('✅ UnifiedSidebar: Inicialização concluída');

            // Setup sidebar auth (user info + logout button)
            if (typeof window.gbocSetupSidebarAuth === 'function') {
                window.gbocSetupSidebarAuth();
            }

        } catch (error) {
            console.error('❌ UnifiedSidebar: Erro na inicialização:', error);
            this._createFallbackSidebar();
        } finally {
            window.__gbocSidebarInitializing = false;
        }
    }

    /**
     * Configura o tema inicial armazenado no localStorage
     * @private
     */
    _setupSidebarRuntime() {
        const saved = localStorage.getItem(SIDEBAR_CONFIG.STORAGE.THEME) || 'dark';
        document.documentElement.setAttribute('data-theme', saved);
        if (typeof window.updateThemeButton === 'function') {
            window.updateThemeButton(saved);
        }
    }

    /**
     * Carrega o HTML do sidebar da API/Assets
     * @private
     * @returns {Promise<void>}
     */
    async _loadSidebarHtml() {
        try {
            const response = await fetch(SIDEBAR_CONFIG.ASSETS.SIDEBAR_HTML);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            this._sidebarHtml = await response.text();
            console.log('✅ Sidebar HTML carregado');
        } catch (error) {
            console.error('❌ Erro ao carregar sidebar HTML:', error);
            throw error;
        }
    }

    /**
     * Injeta o sidebar no DOM da página
     * @private
     */
    _injectSidebar() {
        const appDiv = document.querySelector(SIDEBAR_CONFIG.SELECTORS.APP);
        if (!appDiv) {
            throw new Error(`Elemento ${SIDEBAR_CONFIG.SELECTORS.APP} não encontrado`);
        }

        // Remover sidebar existente se houver
        const existingSidebar = appDiv.querySelector(SIDEBAR_CONFIG.SELECTORS.SIDEBAR);
        if (existingSidebar) {
            existingSidebar.remove();
        }

        // Inserir novo sidebar no início do container principal
        appDiv.insertAdjacentHTML('afterbegin', this._sidebarHtml);
        console.log('✅ Sidebar injetado no DOM');
    }

    /**
     * Atualiza o link ativo no sidebar baseado na página atual
     * @private
     */
    _updateActiveLink() {
        const navLinks = document.querySelectorAll(SIDEBAR_CONFIG.SELECTORS.NAV_LINK);
        navLinks.forEach(link => link.classList.remove('active'));

        let activeFound = false;
        navLinks.forEach(link => {
            const href = link.getAttribute('href');
            if (this._isActiveLink(href)) {
                link.classList.add('active');
                activeFound = true;
            }
        });

        // fallback defensivo: marca dashboard se nada casar
        if (!activeFound) {
            const home = document.querySelector(`${SIDEBAR_CONFIG.SELECTORS.NAV_LINK}[href="/"]`);
            if (home) home.classList.add('active');
        }

        console.log('✅ Link ativo atualizado:', window.location.pathname);
    }

    /**
     * Verifica se um link deve estar ativo baseado na página atual
     * @private
     * @param {string} href - A URL alvo a ser validada
     * @returns {boolean}
     */
    _isActiveLink(href) {
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
     * @private
     */
    _setupEventListeners() {
        const navLinks = document.querySelectorAll(SIDEBAR_CONFIG.SELECTORS.NAV_LINK);
        navLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                const clickedLink = e.target.closest(SIDEBAR_CONFIG.SELECTORS.NAV_LINK);
                if (!clickedLink) return;
                navLinks.forEach(l => l.classList.remove('active'));
                clickedLink.classList.add('active');
            });
        });
    }

    /**
     * Identifica a página atual baseada na URL
     * @private
     * @returns {string} Nome da página atual
     */
    _getCurrentPage() {
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
     * Cria um sidebar básico como fallback em caso de erro na requisição HTML
     * @private
     */
    _createFallbackSidebar() {
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

        const appDiv = document.querySelector(SIDEBAR_CONFIG.SELECTORS.APP);
        if (appDiv) {
            appDiv.insertAdjacentHTML('afterbegin', fallbackHtml);
            console.log('✅ Sidebar de fallback criado');
        }
    }

    /**
     * Método público para recarregar o sidebar (útil após navegação SPA)
     * @public
     */
    async reload() {
        console.log('🔄 Recarregando sidebar...');
        this.currentPage = this._getCurrentPage();
        await this.initialize();
    }
}

// ============================================================================
// 3. INSTÂNCIA GLOBAL E FUNÇÕES AUXILIARES
// ============================================================================

// Instância global do sidebar
window.unifiedSidebar = new UnifiedSidebar();

/**
 * Alterna entre tema claro e escuro
 */
window.toggleTheme = function() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem(SIDEBAR_CONFIG.STORAGE.THEME, next);
    if (typeof window.updateThemeButton === 'function') {
        window.updateThemeButton(next);
    }
};

/**
 * Atualiza o visual do botão de tema
 * @param {string} theme - 'dark' ou 'light'
 */
window.updateThemeButton = function(theme) {
    const icon = document.getElementById(SIDEBAR_CONFIG.SELECTORS.THEME_ICON);
    const label = document.getElementById(SIDEBAR_CONFIG.SELECTORS.THEME_LABEL);
    if (icon && label) {
        icon.className = theme === 'dark' ? 'fas fa-moon' : 'fas fa-sun';
        label.textContent = theme === 'dark' ? 'Tema Escuro' : 'Tema Claro';
    }
};

/**
 * Exibe o usuário na interface do sidebar
 * @param {Object} u - Objeto contendo os dados do usuário
 */
window._gbocShowSidebarUser = function(u) {
    const el = document.getElementById(SIDEBAR_CONFIG.SELECTORS.USER_NAME);
    const info = document.getElementById(SIDEBAR_CONFIG.SELECTORS.USER_INFO);
    const btn = document.getElementById(SIDEBAR_CONFIG.SELECTORS.LOGOUT_BTN);
    const link = document.getElementById(SIDEBAR_CONFIG.SELECTORS.LOGOUT_LINK);
    
    if (el) el.textContent = (u && (u.display_name || u.username)) || '';
    if (info) info.style.display = 'block';
    if (btn) btn.style.display = 'block';
    if (link) link.style.display = 'flex';
};

/**
 * Verifica autenticação e configura os botões e informações do usuário no sidebar
 */
window.gbocSetupSidebarAuth = function() {
    const token = localStorage.getItem(SIDEBAR_CONFIG.STORAGE.TOKEN);
    const user = localStorage.getItem(SIDEBAR_CONFIG.STORAGE.USER);
    
    const btn = document.getElementById(SIDEBAR_CONFIG.SELECTORS.LOGOUT_BTN);
    const link = document.getElementById(SIDEBAR_CONFIG.SELECTORS.LOGOUT_LINK);

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

    fetch(SIDEBAR_CONFIG.API.AUTH_STATUS)
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

/**
 * Executa o fluxo de logout do usuário
 */
window.gbocLogout = async function() {
    if (!confirm('Deseja realmente sair?')) return;
    try {
        await fetch(SIDEBAR_CONFIG.API.AUTH_LOGOUT, { method: 'POST' });
    } catch (e) {
        console.warn('⚠️ Falha ao invalidar sessão na API, procedendo com limpeza local.', e);
    }
    
    localStorage.removeItem(SIDEBAR_CONFIG.STORAGE.TOKEN);
    localStorage.removeItem(SIDEBAR_CONFIG.STORAGE.USER);
    document.cookie = `${SIDEBAR_CONFIG.STORAGE.TOKEN}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;`;
    window.location.href = '/login.html';
};

/**
 * Helper global para padronização de data/hora (evita mistura UTC/local)
 * @param {string|Date} value - Valor da data
 * @returns {string} Data formatada ou o valor original se for inválido
 */
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

// ============================================================================
// 4. INICIALIZAÇÃO
// ============================================================================

// Inicialização automática quando DOM estiver pronto
document.addEventListener('DOMContentLoaded', async function() {
    await window.unifiedSidebar.initialize();
});

console.log('✅ UnifiedSidebar module loaded');