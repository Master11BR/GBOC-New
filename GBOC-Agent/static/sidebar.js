/*
==============================================================================
GBOC System v14.0.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
/**
 * GBOC Agent - Unified Sidebar Module
 * Sistema unificado de sidebar para todas as páginas
 */

// ============================================================================
// 1. AUTO-INJEÇÃO SÍNCRONA DO LAYOUT MANAGER (GUI HORIZONTAL / VERTICAL)
// ============================================================================
(function autoInjectLayoutManager() {
    if (!window.GBOCLayout && !document.getElementById('gboc-layout-manager-script')) {
        const s = document.createElement('script');
        s.id = 'gboc-layout-manager-script';
        s.src = '/static/gboc-layout-manager.js';
        if (document.head) {
            document.head.appendChild(s);
        } else {
            document.addEventListener('DOMContentLoaded', () => document.head.appendChild(s));
        }
    }
})();

// ============================================================================
// 2. CONFIGURAÇÕES E CONSTANTES
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

            // Injetar Layout Manager (GUI Horizontal/Vertical + Botão Paleta de Cores)
            if (!window.GBOCLayout && !document.getElementById('gboc-layout-manager-script')) {
                const lmScript = document.createElement('script');
                lmScript.id = 'gboc-layout-manager-script';
                lmScript.src = '/static/gboc-layout-manager.js';
                document.head.appendChild(lmScript);
            }

            // Carregar HTML do sidebar
            await this._loadSidebarHtml();

            // Injetar sidebar no DOM
            this._injectSidebar();

            // Inicializar grupos colapsáveis e autenticação da sidebar
            if (typeof window.initNavGroups === 'function') {
                window.initNavGroups();
            }

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
        const appDiv = document.querySelector(SIDEBAR_CONFIG.SELECTORS.APP) ||
                       document.querySelector('.app-layout') ||
                       document.querySelector('#sidebar-container') ||
                       document.body;

        if (!appDiv) {
            throw new Error(`Nenhum container válido para o sidebar foi encontrado.`);
        }

        // Remover sidebar existente se houver
        const existingSidebar = document.querySelector(SIDEBAR_CONFIG.SELECTORS.SIDEBAR);
        if (existingSidebar) {
            existingSidebar.remove();
        }

        if (appDiv.id === 'sidebar-container') {
            appDiv.innerHTML = this._sidebarHtml;
        } else {
            appDiv.insertAdjacentHTML('afterbegin', this._sidebarHtml);
        }
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
            <nav class="nav" style="padding-top:16px">
                <a href="/index.html" class="nav-link ${this.currentPage === 'dashboard' ? 'active' : ''}"><i class="fas fa-home nav-icon"></i> <span>Dashboard Agente</span></a>
                <div class="nav-group" id="fb-grp-tasks">
                    <button class="nav-group-header" onclick="toggleNavGroup('fb-grp-tasks')"><span><i class="fas fa-tasks nav-icon"></i> Tarefas & Motores</span><i class="fas fa-chevron-down nav-group-arrow"></i></button>
                    <div class="nav-group-items open" id="items-fb-grp-tasks">
                        <a href="/tasks.html" class="nav-link nav-sub"><i class="fas fa-list-check nav-icon"></i> <span>Tarefas de Backup</span></a>
                        <a href="/repositories.html" class="nav-link nav-sub"><i class="fas fa-database nav-icon"></i> <span>Repositórios Locais</span></a>
                        <a href="/restore.html" class="nav-link nav-sub"><i class="fas fa-undo nav-icon"></i> <span>Assistente Restauração</span></a>
                        <a href="/engines.html" class="nav-link nav-sub"><i class="fas fa-cogs nav-icon"></i> <span>Motores Nativos</span></a>
                    </div>
                </div>
            </nav>
        </aside>`;

        const appDiv = document.querySelector(SIDEBAR_CONFIG.SELECTORS.APP) ||
                       document.querySelector('.app-layout') ||
                       document.querySelector('#sidebar-container') ||
                       document.body;
        if (appDiv) {
            if (appDiv.id === 'sidebar-container') {
                appDiv.innerHTML = fallbackHtml;
            } else {
                appDiv.insertAdjacentHTML('afterbegin', fallbackHtml);
            }
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

/**
 * Função global para alternar o tema do sistema (Dark / Light)
 */
window.toggleTheme = function() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem(SIDEBAR_CONFIG.STORAGE.THEME, newTheme);
    window.updateThemeButton(newTheme);
};

window.updateThemeButton = function(theme) {
    const iconEl = document.getElementById(SIDEBAR_CONFIG.SELECTORS.THEME_ICON);
    const labelEl = document.getElementById(SIDEBAR_CONFIG.SELECTORS.THEME_LABEL);
    if (iconEl) {
        iconEl.className = theme === 'dark' ? 'fas fa-moon' : 'fas fa-sun';
    }
    if (labelEl) {
        labelEl.innerText = theme === 'dark' ? 'Tema Escuro' : 'Tema Claro';
    }
};

/**
 * Funções globais de navegação colapsável da Sidebar (Grupos de Menu)
 */
window.initNavGroups = function() {
    const groups = ['grp-backup','grp-virt','grp-security','grp-monitor','grp-system'];
    const cur = window.location.pathname;
    groups.forEach(grpId => {
        const items = document.getElementById('items-' + grpId);
        const arrow = document.getElementById('arrow-' + grpId);
        if (!items) return;
        const hasActive = Array.from(items.querySelectorAll('a')).some(a => {
            const href = a.getAttribute('href');
            return href && cur.startsWith(href) && href !== '/';
        });
        const savedOpen = localStorage.getItem('gboc-nav-' + grpId);
        const shouldOpen = hasActive || savedOpen === 'open';
        if (shouldOpen) {
            items.classList.add('open');
            if (arrow) arrow.style.transform = 'rotate(180deg)';
        }
    });
};

window.toggleNavGroup = function(grpId) {
    const items = document.getElementById('items-' + grpId);
    const arrow = document.getElementById('arrow-' + grpId);
    if (!items) return;
    const isOpen = items.classList.toggle('open');
    if (arrow) arrow.style.transform = isOpen ? 'rotate(180deg)' : '';
    localStorage.setItem('gboc-nav-' + grpId, isOpen ? 'open' : 'closed');
};

/**
 * Funções globais de autenticação no Sidebar
 */
window.gbocSetupSidebarAuth = function() {
    const token = localStorage.getItem('gboc_token');
    const user = localStorage.getItem('gboc_user');
    if(user){
        try {
            const u = JSON.parse(user);
            _gbocShowSidebarUser(u);
        } catch(e){}
    } else if(token){
        const btn = document.getElementById('logoutBtn');
        if(btn) btn.style.display = 'block';
    }
    fetch('/api/auth/status').then(r => r.json()).then(data => {
        if(data.authenticated && data.user){
            _gbocShowSidebarUser(data.user);
        } else if(data.auth_enabled){
            const btn = document.getElementById('logoutBtn');
            if(btn) btn.style.display = 'block';
        }
    }).catch(()=>{
        if(token){
            const btn = document.getElementById('logoutBtn');
            if(btn) btn.style.display = 'block';
        }
    });
};

function _gbocShowSidebarUser(u){
    const el = document.getElementById('sidebarUsername');
    const info = document.getElementById('sidebarUserInfo');
    const btn = document.getElementById('logoutBtn');
    if(el) el.textContent = u.display_name || u.username || '';
    if(info) info.style.display = 'block';
    if(btn) btn.style.display = 'block';
}

window.gbocLogout = async function(){
    if(!confirm('Deseja realmente sair?')) return;
    try {
        await fetch('/api/auth/logout', {method:'POST'});
    } catch(e){}
    localStorage.removeItem('gboc_token');
    localStorage.removeItem('gboc_user');
    document.cookie = 'gboc_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
    window.location.href = '/login.html';
};

/**
 * Unifica o indicador de status de conexão do cabeçalho em todas as páginas do sistema
 */
window.gbocSyncConnectionStatus = async function() {
    const dot = document.getElementById('wsDot');
    const label = document.getElementById('wsLabel');

    try {
        const res = await fetch('/api/system/info');
        if (res.ok) {
            const info = await res.json();
            const ver = info.gboc_version || '14.0.0';

            if (dot && label) {
                dot.className = 'ws-dot on';
                dot.style.background = 'var(--success)';
                dot.style.display = 'inline-block';
                dot.style.width = '8px';
                dot.style.height = '8px';
                dot.style.borderRadius = '50%';
                dot.style.marginRight = '4px';

                label.textContent = 'v' + ver + ' • Online (Conectado)';
                label.style.color = 'var(--success)';
                label.style.fontWeight = '600';
                label.style.fontSize = '.85em';
            }

            const appVerEl = document.getElementById('app-version');
            if (appVerEl) {
                appVerEl.textContent = 'v' + ver;
            }
            document.querySelectorAll('.serverVersionBadge, .agentVersionBadge, #versionBadge, #serverVersionBadge').forEach(el => {
                el.textContent = 'v' + ver;
            });
        } else {
            throw new Error('API Inacessível');
        }
    } catch(e) {
        if (dot && label) {
            dot.className = 'ws-dot off';
            dot.style.background = 'var(--danger)';
            label.textContent = 'Offline (Desconectado)';
            label.style.color = 'var(--danger)';
        }
    }
};

// Inicialização automática quando DOM estiver pronto
document.addEventListener('DOMContentLoaded', async function() {
    const savedTheme = localStorage.getItem(SIDEBAR_CONFIG.STORAGE.THEME) || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    window.updateThemeButton(savedTheme);
    await window.unifiedSidebar.initialize();
    window.gbocSyncConnectionStatus();
    setInterval(window.gbocSyncConnectionStatus, 10000);
});

console.log('✅ UnifiedSidebar module loaded');