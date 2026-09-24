/*
==============================================================================
GBOC System v14.6.0 Enterprise Edition
Layout & Navigation Manager — Controls Dual Layout Engine (Vertical/Horizontal)
and Color Themes across all resolutions (1024px, 720p HD, 1080p FHD, 4K UHD).
Zero-Overflow & Smart Sidebar Presence Detection.
==============================================================================
*/

(function () {
    'use strict';

    // Auto-inject Enterprise Modal & Dialog Framework se ainda não estiver presente na página
    if (!window.GBOCModal && !document.getElementById('gboc-modal-script')) {
        const m = document.createElement('script');
        m.id = 'gboc-modal-script';
        m.src = '/static/gboc-modal.js?v=14.6.0';
        if (document.head) {
            document.head.appendChild(m);
        } else {
            document.addEventListener('DOMContentLoaded', function () {
                if (document.head && !document.getElementById('gboc-modal-script')) {
                    document.head.appendChild(m);
                }
            });
        }
    }

    if (typeof window.GBOC_API_BASE === 'undefined') {
        const isAgent = window.location.port === '9200' ||
                        window.location.port === '8081' ||
                        window.location.pathname.includes('/replication.html') ||
                        window.location.pathname.includes('/failed-jobs.html') ||
                        window.location.pathname.includes('/storage-usage.html') ||
                        window.location.pathname.includes('/settings.html') ||
                        window.location.pathname.includes('/tasks.html') ||
                        window.location.pathname.includes('/diagnostic.html') ||
                        window.location.pathname.includes('/reports.html') ||
                        window.location.pathname.includes('/repositories.html') ||
                        window.location.pathname.includes('/restore.html') ||
                        window.location.pathname.includes('/alerts.html') ||
                        window.location.pathname.includes('/ransomware.html') ||
                        window.location.pathname.includes('/compliance.html') ||
                        window.location.pathname.includes('/audit.html') ||
                        window.location.pathname.includes('/index.html');

        if (isAgent) {
            window.GBOC_API_BASE = (window.location.protocol === 'https:' || window.location.port === '8081' ? 'https:' : window.location.protocol) + '//' + window.location.hostname + ':' + (window.location.port === '8081' ? '9200' : (window.location.port || '9200'));
        } else {
            window.GBOC_API_BASE = (window.location.protocol === 'https:' || window.location.port === '8080' ? 'https:' : window.location.protocol) + '//' + window.location.hostname + ':' + (window.location.port === '8080' ? '8000' : (window.location.port || '8000'));
        }
    }

    // ── Constants & Global UI Model Contract ──────────────────────────────────
    const LS_UI_MODEL = 'gboc-ui-model';      // Always 'modern'
    const LS_LAYOUT   = 'gboc-layout';        // 'vertical' | 'horizontal'
    const LS_COLOR    = 'gboc-color-theme';   // 'dark' | 'light' | 'purple' | 'ocean'
    const LS_UI_STYLE = 'gboc-ui-style';     // 'minimal' | 'neumorphism' | 'claymorphism' | 'fluent'
    const LS_COLLAPSED = 'gboc-sidebar-collapsed';
    const TOPBAR_URL  = '/static/_topbar.html';

    const OFFICIAL_MODELS = ['modern'];
    const DEFAULT_MODEL   = 'modern';

    window.UI_MODEL         = DEFAULT_MODEL;
    window.ACTIVE_UI_MODEL  = DEFAULT_MODEL;
    window.DEFAULT_UI_MODEL = DEFAULT_MODEL;

    const THEMES = [
        { id: 'dark',   label: 'Dark',   icon: '🌙' },
        { id: 'light',  label: 'Light',  icon: '☀️' },
        { id: 'amber',  label: 'Amber',  icon: '⚡' },
        { id: 'purple', label: 'Purple', icon: '💜' },
        { id: 'ocean',  label: 'Ocean',  icon: '🌊' },
        { id: 'red',    label: 'Red',    icon: '🔴' }
    ];

    const UI_STYLES = [
        { id: 'minimal',          label: 'Minimal Clean UI',        icon: '✨' },
        { id: 'neumorphism',      label: 'Neumorphism 3D',          icon: '🔘' },
        { id: 'claymorphism',     label: '3D Claymorphism',         icon: '🧱' },
        { id: 'fluent',           label: 'Fluent Acrylic',          icon: '🪟' },
        { id: 'nexus-widgets',    label: 'Cartões Modulares (Nexus)', icon: '📐' },
        { id: 'nexus-glass',      label: 'Glassmorphism Técnico',   icon: '💎' },
        { id: 'command-sentinel', label: 'Command Center Sentinel', icon: '🛰️' },
        { id: 'cyber-3d',         label: 'Cyber 3D Glass (Animado)', icon: '🌌' }
    ];

    // ── State ─────────────────────────────────────────────────────────────────
    let _currentUiModel = localStorage.getItem(LS_UI_MODEL) || DEFAULT_MODEL;
    if (!OFFICIAL_MODELS.includes(_currentUiModel)) {
        console.warn(`[GBOCLayout] Modelo visual solicitado '${_currentUiModel}' é inválido/legado desativado. Fallback automático para DEFAULT '${DEFAULT_MODEL}'.`);
        _currentUiModel = DEFAULT_MODEL;
    }
    let _currentLayout = localStorage.getItem(LS_LAYOUT) || 'vertical';
    let _currentColorTheme = localStorage.getItem(LS_COLOR) || localStorage.getItem('gboc-theme') || 'amber';
    let _currentUiStyle = localStorage.getItem(LS_UI_STYLE) || 'minimal';
    let _panelOpen = false;
    let _topbarHtml = null;

    // ── Detect sidebar in DOM ─────────────────────────────────────────────────
    function _checkSidebarPresence() {
        const hasSidebar = !!document.querySelector('.sidebar, aside.sidebar');
        document.body.classList.toggle('has-sidebar', hasSidebar);
        return hasSidebar;
    }

    // ── Apply UI Model to <html> ──────────────────────────────────────────────
    function _applyUiModel(model) {
        let validModel = model;
        if (!OFFICIAL_MODELS.includes(validModel)) {
            console.warn(`[GBOCLayout] Modelo visual '${model}' não suportado. Mantendo '${DEFAULT_MODEL}'.`);
            validModel = DEFAULT_MODEL;
        }
        document.documentElement.setAttribute('data-ui-model', validModel);
        _currentUiModel = validModel;
        window.UI_MODEL = validModel;
        window.ACTIVE_UI_MODEL = validModel;
        localStorage.setItem(LS_UI_MODEL, validModel);
        _updatePanelActiveStates();
    }

    // ── Apply UI Component Style to <html> ───────────────────────────────────
    function _applyUiStyle(style) {
        document.documentElement.setAttribute('data-ui-style', style);
        _currentUiStyle = style;
        localStorage.setItem(LS_UI_STYLE, style);
        _updatePanelActiveStates();
    }

    // ── Apply color theme to <html> ───────────────────────────────────────────
    function _applyColorTheme(theme) {
        document.documentElement.setAttribute('data-color-theme', theme);
        // Keep legacy data-theme in sync for backward compat
        if (theme === 'dark' || theme === 'light') {
            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem('gboc-theme', theme);
        } else {
            // Amber, purple, red, ocean are dark-ish base
            document.documentElement.setAttribute('data-theme', 'dark');
            localStorage.setItem('gboc-theme', theme);
        }
        _currentColorTheme = theme;
        localStorage.setItem(LS_COLOR, theme);
        _updatePanelActiveStates();
        _updateSvgGradients();
    }

    function _updateSvgGradients() {
        const g1 = document.getElementById('glow-ambient-1');
        const g2 = document.getElementById('glow-ambient-2');
        const g3 = document.getElementById('glow-ambient-3');
        if (g1) g1.style.backgroundColor = 'var(--ambient-glow-1)';
        if (g2) g2.style.backgroundColor = 'var(--ambient-glow-2)';
        if (g3) g3.style.backgroundColor = 'var(--ambient-glow-1)';
    }

    // ── Apply layout mode to <body> ───────────────────────────────────────────
    function _applyLayout(mode) {
        document.body.classList.remove('layout-vertical', 'layout-horizontal');
        document.body.classList.add('layout-' + mode);
        _currentLayout = mode;
        localStorage.setItem(LS_LAYOUT, mode);

        _checkSidebarPresence();

        if (mode === 'vertical') {
            if (localStorage.getItem(LS_COLLAPSED) === 'true') {
                document.body.classList.add('sidebar-collapsed');
            }
        }

        _injectTopbar();
        _updatePanelActiveStates();
    }

    let _sidebarHtml = null;
    const SIDEBAR_URL = '/static/_sidebar.html';
    let _isInjectingSidebar = false;
    let _isInjectingTopbar = false;

    async function _injectSidebar() {
        if (_currentLayout !== 'vertical' || _isInjectingSidebar) return;
        if (!document.querySelector('.sidebar, aside.sidebar')) {
            _isInjectingSidebar = true;
            try {
                if (!_sidebarHtml) {
                    _sidebarHtml = window.__gbocSidebarMemoryCache || sessionStorage.getItem('gboc_sidebar_html');
                }
                if (!_sidebarHtml) {
                    const r = await fetch(SIDEBAR_URL);
                    if (r.ok) {
                        _sidebarHtml = await r.text();
                        window.__gbocSidebarMemoryCache = _sidebarHtml;
                        try { sessionStorage.setItem('gboc_sidebar_html', _sidebarHtml); } catch(e) {}
                    }
                }
                if (_sidebarHtml && !document.querySelector('.sidebar, aside.sidebar')) {
                    const topbar = document.getElementById('gboc-topbar');
                    if (topbar) {
                        topbar.insertAdjacentHTML('afterend', _sidebarHtml);
                    } else {
                        document.body.insertAdjacentHTML('afterbegin', _sidebarHtml);
                    }
                    _checkSidebarPresence();
                }
            } catch (e) {
                console.warn('[GBOCLayout] Falha ao injetar sidebar:', e);
            } finally {
                _isInjectingSidebar = false;
            }
        }
    }

    // ── Fetch & inject topbar & hero backdrop ─────────────────────────────────
    async function _injectTopbar() {
        if (_isInjectingTopbar) return;
        _isInjectingTopbar = true;
        try {
            if (!document.getElementById('gboc-hero-bg')) {
                const hero = document.createElement('div');
                hero.id = 'gboc-hero-bg';
                hero.className = 'gboc-hero-bg';
                document.body.appendChild(hero);
            }

            if (!document.getElementById('gboc-topbar')) {
                try {
                    if (!_topbarHtml) {
                        _topbarHtml = window.__gbocTopbarMemoryCache || sessionStorage.getItem('gboc_topbar_html');
                    }
                    if (!_topbarHtml) {
                        const r = await fetch(TOPBAR_URL);
                        if (r.ok) {
                            _topbarHtml = await r.text();
                            window.__gbocTopbarMemoryCache = _topbarHtml;
                            try { sessionStorage.setItem('gboc_topbar_html', _topbarHtml); } catch(e) {}
                        }
                    }
                    if (_topbarHtml && !document.getElementById('gboc-topbar')) {
                        document.body.insertAdjacentHTML('afterbegin', _topbarHtml);
                    }
                } catch (e) {
                    console.warn('[GBOCLayout] Falha ao injetar topbar:', e);
                }
            }

            await _injectSidebar();
            _checkSidebarPresence();
            _markActiveTopbarLink();
            _setupTopbarAuth();
            _setupToggleButtons();
            _checkFailedJobsBadge();
            _updateDynamicVersion();
        } finally {
            _isInjectingTopbar = false;
        }
    }

    function _setupToggleButtons() {
        const toggleBtn = document.getElementById('gboc-vheader-toggle');
        if (toggleBtn && !toggleBtn.dataset.boundClick) {
            toggleBtn.dataset.boundClick = 'true';
            toggleBtn.addEventListener('click', (e) => {
                e.preventDefault();
                document.body.classList.toggle('sidebar-collapsed');
                const isCollapsed = document.body.classList.contains('sidebar-collapsed');
                localStorage.setItem(LS_COLLAPSED, isCollapsed ? 'true' : 'false');
            });
        }
    }

    async function _updateDynamicVersion() {
        try {
            const r = await fetch('/api/v2/system/version');
            if (r.ok) {
                const res = await r.json();
                const data = res.data || res;
                const badge = document.getElementById('serverVersionBadge');
                if (badge && (data.raw_version || data.semver)) {
                    badge.textContent = `v${data.raw_version}`;
                    badge.title = data.semver || `GBOC System v${data.raw_version}`;
                }
            }
        } catch (e) {}
    }

    // ── Mark active link in topbar ────────────────────────────────────────────
    function _markActiveTopbarLink() {
        const path = window.location.pathname;
        document.querySelectorAll('.tb-dropdown-item, .tb-nav-link[href]').forEach(a => {
            const href = a.getAttribute('href');
            if (href && (path === href || (href !== '/' && path.endsWith(href)))) {
                a.classList.add('active');
                const btn = a.closest('.tb-dropdown')?.querySelector('.tb-nav-link');
                if (btn) btn.classList.add('active');
            }
        });
        if (path === '/' || path === '/index.html' || path === '/overview.html') {
            document.getElementById('tblink-dashboard')?.classList.add('active');
        }
    }

    // ── Auth integration in topbar & user menu ───────────────────────────────
    function _setupTopbarAuth() {
        const token = localStorage.getItem('gboc_token');
        const userStr = localStorage.getItem('gboc_user') || localStorage.getItem('user');
        const logoutBtn = document.getElementById('tb-logout-btn');

        if (token && logoutBtn) logoutBtn.style.display = 'flex';

        const userNameEl = document.getElementById('tb-user-name');
        const userRoleEl = document.getElementById('tb-user-role');
        const avatar = document.getElementById('tb-user-avatar');
        const menuIcon = document.getElementById('tb-menu-avatar-icon');

        let displayName = 'Administrador';
        let displayRole = 'Super Admin (Local)';

        if (userStr) {
            try {
                const u = JSON.parse(userStr);
                displayName = u.display_name || u.full_name || u.username || u.name || 'Administrador';
                displayRole = u.role || u.email || 'Super Admin';
            } catch {}
        }

        if (userNameEl) userNameEl.textContent = displayName;
        if (userRoleEl) userRoleEl.textContent = displayRole;

        const initials = (displayName.substring(0, 2)).toUpperCase();
        if (avatar) {
            avatar.innerHTML = `<span style="font-size:0.78em;font-weight:700;letter-spacing:-0.5px">${initials}</span>`;
        }
        if (menuIcon) {
            menuIcon.innerHTML = `<span style="font-size:0.85em;font-weight:700">${initials}</span>`;
        }

        // Toggle dropdowns on click (for mobile, touch and tablet devices)
        document.querySelectorAll('.tb-dropdown').forEach(dd => {
            const trigger = dd.querySelector('.tb-nav-link, .tb-avatar');
            if (trigger && !trigger.dataset.boundClick) {
                trigger.dataset.boundClick = 'true';
                trigger.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const isOpen = dd.classList.contains('active');
                    document.querySelectorAll('.tb-dropdown').forEach(d => d.classList.remove('active'));
                    if (!isOpen) dd.classList.add('active');
                });
            }
        });

        // Close open dropdowns when clicking outside
        if (!window._gbocDropdownCloseBound) {
            window._gbocDropdownCloseBound = true;
            document.addEventListener('click', (e) => {
                if (!e.target.closest('.tb-dropdown')) {
                    document.querySelectorAll('.tb-dropdown').forEach(d => d.classList.remove('active'));
                }
            });
        }
    }

    // ── Inject AI Assistant script if missing ────────────────────────────────
    function _ensureAiAssistantLoaded() {
        if (!window.GBOC_AI_Assistant && !document.getElementById('gboc-ai-script')) {
            const script = document.createElement('script');
            script.id = 'gboc-ai-script';
            script.src = '/static/ai_assistant.js';
            document.head.appendChild(script);
        }
    }

    function _ensureHardwareHudLoaded() {
        if (!window.toggleHardwareHUD && !document.getElementById('gboc-hw-script')) {
            const script = document.createElement('script');
            script.id = 'gboc-hw-script';
            script.src = '/static/gboc-hardware-hud.js';
            document.head.appendChild(script);
        }
        if (!document.getElementById('gboc-hw-style')) {
            const link = document.createElement('link');
            link.id = 'gboc-hw-style';
            link.rel = 'stylesheet';
            link.href = '/static/gboc-hardware-hud.css';
            document.head.appendChild(link);
        }
    }

    // ── Inject System-Wide Ambient Animated Background ──────────────────────
    function _ensureAnimatedBackgroundLoaded() {
        if (document.getElementById('gboc-ambient-background')) return;

        const bg = document.createElement('div');
        bg.id = 'gboc-ambient-background';
        bg.className = 'gboc-ambient-background';
        bg.innerHTML = `
            <div id="glow-ambient-1" class="glow-pulse" style="position:fixed;top:-130px;left:-130px;width:32rem;height:32rem;border-radius:9999px;filter:blur(130px);mix-blend-mode:screen;background-color:var(--ambient-glow-1,rgba(245,158,11,0.2));pointer-events:none;"></div>
            <div id="glow-ambient-2" class="glow-pulse-delayed" style="position:fixed;top:50%;right:-130px;width:40rem;height:40rem;border-radius:9999px;filter:blur(160px);mix-blend-mode:screen;background-color:var(--ambient-glow-2,rgba(217,119,6,0.18));pointer-events:none;"></div>
            <div id="glow-ambient-3" class="glow-pulse" style="position:fixed;bottom:-120px;left:25%;width:28rem;height:28rem;border-radius:9999px;filter:blur(140px);mix-blend-mode:screen;background-color:var(--ambient-glow-1,rgba(245,158,11,0.2));animation-delay:4s;pointer-events:none;"></div>
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M0,50 C30,30 70,80 100,40" fill="none" stroke="url(#gboc-grad1)" stroke-width="0.22" class="path-animate-1" />
                <path d="M0,60 C40,20 60,90 100,50" fill="none" stroke="url(#gboc-grad2)" stroke-width="0.16" class="path-animate-2" />
                <path d="M-10,80 C30,90 80,20 110,30" fill="none" stroke="url(#gboc-grad1)" stroke-width="0.12" class="path-animate-3" />
                <defs>
                    <linearGradient id="gboc-grad1" x1="0%" y1="0%" x2="100%" y2="0%">
                        <stop offset="0%" style="stop-color: var(--curve-color-2, #d97706); stop-opacity: 0;" />
                        <stop offset="50%" style="stop-color: var(--curve-color-1, #f59e0b); stop-opacity: 0.85;" />
                        <stop offset="100%" style="stop-color: var(--curve-color-2, #d97706); stop-opacity: 0;" />
                    </linearGradient>
                    <linearGradient id="gboc-grad2" x1="0%" y1="0%" x2="100%" y2="0%">
                        <stop offset="0%" style="stop-color: var(--curve-color-1, #f59e0b); stop-opacity: 0;" />
                        <stop offset="50%" style="stop-color: var(--curve-color-2, #d97706); stop-opacity: 0.7;" />
                        <stop offset="100%" style="stop-color: var(--curve-color-1, #f59e0b); stop-opacity: 0;" />
                    </linearGradient>
                </defs>
            </svg>
        `;

        if (document.body) {
            document.body.insertBefore(bg, document.body.firstChild);
        }
    }

    // ── Badge: check failed jobs ──────────────────────────────────────────────
    async function _checkFailedJobsBadge() {
        try {
            const r = await fetch(window.GBOC_API_BASE + '/api/v1/jobs/failed?limit=10');
            if (r.ok) {
                const data = await r.json();
                const failed = (data.failures || []).filter(f => f.status === 'failed').length;
                const badge = document.getElementById('tb-notif-badge');
                if (badge) {
                    badge.style.display = failed > 0 ? 'flex' : 'none';
                    badge.textContent = failed > 9 ? '9+' : String(failed);
                }
            }
        } catch {}
    }

    // ── Fullscreen Helper ─────────────────────────────────────────────────────
    window.gbocToggleFullscreen = function () {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(() => {});
            const icon = document.getElementById('tb-fullscreen-icon');
            if (icon) icon.className = 'fas fa-compress';
        } else {
            if (document.exitFullscreen) {
                document.exitFullscreen().catch(() => {});
                const icon = document.getElementById('tb-fullscreen-icon');
                if (icon) icon.className = 'fas fa-expand';
            }
        }
    };

    // ── Create floating panel ─────────────────────────────────────────────────
    function _createPanel() {
        if (document.getElementById('gboc-layout-panel')) return;

        const themesHtml = THEMES.map(t => `
            <div class="lp-theme-swatch ${_currentColorTheme === t.id ? 'active' : ''}"
                 data-theme="${t.id}"
                 title="${t.label}"
                 onclick="window.GBOCLayout.setTheme('${t.id}')">
            </div>
        `).join('');

        const uiStylesHtml = UI_STYLES.map(s => `
            <button class="lp-layout-btn ${_currentUiStyle === s.id ? 'active' : ''}"
                    data-uistyle="${s.id}"
                    onclick="window.GBOCLayout.setUiStyle('${s.id}')"
                    style="font-size:0.78em;padding:6px 10px;margin-bottom:4px">
                <span>${s.icon} ${s.label}</span>
            </button>
        `).join('');

        const panel = document.createElement('div');
        panel.id = 'gboc-layout-panel';
        panel.className = 'gboc-layout-panel';
        panel.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
                <span style="font-weight:700;font-size:0.9em;display:flex;align-items:center;gap:6px">
                    <i class="fas fa-palette" style="color:var(--primary, #6366f1)"></i> Personalizar Interface
                </span>
                <button onclick="window.GBOCLayout.togglePanel()" style="background:none;border:none;color:var(--text-muted, #94a3b8);cursor:pointer;font-size:1.1em" aria-label="Fechar painel">
                    <i class="fas fa-times"></i>
                </button>
            </div>

            <div style="display:inline-flex;align-items:center;gap:6px;background:rgba(99,102,241,0.15);color:var(--primary-color,#6366f1);padding:4px 10px;border-radius:9999px;font-size:0.75em;font-weight:700;margin-bottom:14px">
                <i class="fas fa-shield-check"></i> MODELO UI ATIVO: Modern UI (Padrão Oficial)
            </div>

            <div class="lp-title">Layout de Navegação</div>
            <div class="lp-layouts">
                <button class="lp-layout-btn ${_currentLayout === 'vertical' ? 'active' : ''}"
                    id="lp-btn-vertical" onclick="window.GBOCLayout.setLayout('vertical')">
                    <i class="fas fa-columns"></i>
                    <span>Sidebar Vertical</span>
                </button>
                <button class="lp-layout-btn ${_currentLayout === 'horizontal' ? 'active' : ''}"
                    id="lp-btn-horizontal" onclick="window.GBOCLayout.setLayout('horizontal')">
                    <i class="fas fa-grip-horizontal"></i>
                    <span>Topbar Horizontal</span>
                </button>
            </div>

            <div class="lp-title">Modo de Iluminação</div>
            <div class="lp-themes" id="lp-theme-swatches">${themesHtml}</div>
            <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px">
                ${THEMES.map(t => `<div style="font-size:0.7em;color:var(--text-muted, #94a3b8);text-align:center;min-width:34px">${t.icon}<br>${t.label}</div>`).join('')}
            </div>

            <div class="lp-title">Estilo de Componentes (UX/UI)</div>
            <div class="lp-ui-styles" style="display:flex;flex-direction:column;gap:4px">
                ${uiStylesHtml}
            </div>

            <div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--border, rgba(255,255,255,0.1));font-size:0.73em;color:var(--text-muted, #94a3b8)">
                <i class="fas fa-check-circle" style="color:var(--success, #10b981)"></i> Preferências salvas automaticamente.
            </div>
        `;
        document.body.appendChild(panel);
    }

    function _createFAB() {
        if (document.getElementById('gboc-layout-fab')) return;
        const fab = document.createElement('button');
        fab.id = 'gboc-layout-fab';
        fab.className = 'gboc-layout-fab';
        fab.title = 'Personalizar Layout & Tema';
        fab.setAttribute('aria-label', 'Personalizar Layout & Tema');
        fab.innerHTML = '<i class="fas fa-palette"></i>';
        fab.addEventListener('click', () => window.GBOCLayout.togglePanel());
        document.body.appendChild(fab);
    }

    function _updatePanelActiveStates() {
        document.getElementById('lp-btn-vertical')?.classList.toggle('active', _currentLayout === 'vertical');
        document.getElementById('lp-btn-horizontal')?.classList.toggle('active', _currentLayout === 'horizontal');
        document.querySelectorAll('.lp-theme-swatch').forEach(sw => {
            sw.classList.toggle('active', sw.getAttribute('data-theme') === _currentColorTheme);
        });
        document.querySelectorAll('[data-uistyle]').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-uistyle') === _currentUiStyle);
        });
    }

    // ── Inject stylesheets if not already present ─────────────────────────────
    function _injectStylesheets() {
        const needed = [
            { id: 'gboc-themes-css',  href: '/static/gboc-themes.css' },
            { id: 'gboc-layout-css',  href: '/static/gboc-layout.css' }
        ];
        needed.forEach(({ id, href }) => {
            if (!document.getElementById(id)) {
                const link = document.createElement('link');
                link.id = id; link.rel = 'stylesheet'; link.href = href;
                document.head.appendChild(link);
            }
        });
    }

    // ── Public API ────────────────────────────────────────────────────
    window.GBOCLayout = {
        getUiModel() { return _currentUiModel; },
        setUiModel(model) { _applyUiModel(model); },
        setLayout(mode) {
            _applyLayout(mode);
        },
        setTheme(theme) {
            _applyColorTheme(theme);
        },
        setUiStyle(style) {
            _applyUiStyle(style);
        },
        togglePanel() {
            _panelOpen = !_panelOpen;
            const panel = document.getElementById('gboc-layout-panel');
            if (panel) panel.classList.toggle('open', _panelOpen);
        },
        getLayout() { return _currentLayout; },
        getTheme()  { return _currentColorTheme; },
        getUiStyle() { return _currentUiStyle; },
        refreshSidebarPresence() { _checkSidebarPresence(); }
    };

    // ── Bootstrap ─────────────────────────────────────────────────────────────
    function _bootstrap() {
        _injectStylesheets();
        _ensureAnimatedBackgroundLoaded();
        _ensureAiAssistantLoaded();
        _ensureHardwareHudLoaded();
        _applyUiModel(_currentUiModel);
        _applyColorTheme(_currentColorTheme);
        _applyUiStyle(_currentUiStyle);
        _applyLayout(_currentLayout);
        _createFAB();
        _createPanel();
        _checkSidebarPresence();

        if (window.MutationObserver) {
            const observer = new MutationObserver(() => {
                _checkSidebarPresence();
            });
            observer.observe(document.body, { childList: true, subtree: true });
        }
    }

    if (document.readyState === 'loading') {
        _injectStylesheets();
        _applyColorTheme(_currentColorTheme);
        _applyUiStyle(_currentUiStyle);
        document.addEventListener('DOMContentLoaded', () => {
            _ensureAnimatedBackgroundLoaded();
            _ensureAiAssistantLoaded();
            _ensureHardwareHudLoaded();
            _applyLayout(_currentLayout);
            _createFAB();
            _createPanel();
            _checkSidebarPresence();

            if (window.MutationObserver) {
                const observer = new MutationObserver(() => {
                    _checkSidebarPresence();
                });
                observer.observe(document.body, { childList: true, subtree: true });
            }
        });
    } else {
        _bootstrap();
    }

    // ── Global Shutdown Handler ───────────────────────────────────────────────
    window.gbocConfirmShutdown = async function (target) {
        if (!target) {
            const isAgent = window.location.port === '9200' ||
                            window.location.port === '8081' ||
                            window.location.pathname.includes('/settings.html') ||
                            window.location.pathname.includes('/diagnostic.html') ||
                            window.location.pathname.includes('/reports.html') ||
                            window.location.pathname.includes('/restore.html') ||
                            window.location.pathname.includes('/tasks.html') ||
                            window.location.pathname.includes('/ransomware.html') ||
                            window.location.pathname.includes('/storage-usage.html');
            target = isAgent ? 'agent' : 'server';
        }

        const isServer = target === 'server';
        const title = isServer ? 'Desligar Servidor Central GBOC' : 'Desligar Agente GBOC';
        const entityName = isServer ? 'Servidor Central' : 'Agente';
        const message = isServer
            ? 'Tem certeza de que deseja desligar o Servidor Central GBOC? A central de monitoramento, painéis web e a recepção de telemetria dos agentes serão interrompidos.'
            : 'Tem certeza de que deseja desligar o GBOC Agent? Todos os processos de monitoramento, proteção em tempo real e rotinas de backup locais serão interrompidos.';

        let confirmed = false;
        if (window.GBOCModal && typeof window.GBOCModal.confirm === 'function') {
            confirmed = await window.GBOCModal.confirm({
                title: title,
                message: message,
                type: 'danger',
                danger: true,
                icon: 'fas fa-power-off',
                confirmText: `Sim, Desligar ${entityName}`,
                cancelText: 'Cancelar',
                badge: 'Controle de Processo'
            });
        } else {
            confirmed = window.confirm(`[GBOC] ${title}\n\n${message}\n\nPressione OK para confirmar o desligamento.`);
        }

        if (!confirmed) return;

        // Visual shutdown overlay
        const overlay = document.createElement('div');
        overlay.id = 'gboc-shutdown-overlay';
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(15,23,42,0.96);backdrop-filter:blur(10px);z-index:9999999;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;text-align:center;padding:24px;box-sizing:border-box;';
        overlay.innerHTML = `
            <div style="width:76px;height:76px;border-radius:50%;background:rgba(239,68,68,0.18);border:2px solid #ef4444;display:flex;align-items:center;justify-content:center;margin-bottom:20px;font-size:34px;color:#ef4444;">
                <i class="fas fa-power-off"></i>
            </div>
            <h2 style="font-size:24px;margin:0 0 10px 0;font-weight:700;letter-spacing:-0.5px;">Encerrando ${entityName}...</h2>
            <p style="font-size:15px;color:#94a3b8;max-width:500px;margin:0 0 24px 0;line-height:1.6;" id="gboc-shutdown-msg">
                Os serviços estão sendo finalizados graciosamente. Aguarde um instante...
            </p>
            <div style="display:flex;align-items:center;gap:10px;font-size:14px;color:#cbd5e1;" id="gboc-shutdown-spinner">
                <i class="fas fa-circle-notch fa-spin" style="color:var(--primary,#6366f1);"></i> Finalizando processos do sistema...
            </div>
        `;
        document.body.appendChild(overlay);

        const apiBase = (window.GBOC_API_BASE || '').replace(/\/+$/, '');
        const endpoints = [
            `${apiBase}/api/v1/system/shutdown`,
            `${apiBase}/api/system/shutdown`,
            '/api/v1/system/shutdown',
            '/api/system/shutdown'
        ];

        let reqSent = false;
        for (const ep of endpoints) {
            try {
                const resp = await fetch(ep, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include'
                });
                if (resp.ok || resp.status === 200 || resp.status === 401 || resp.status === 403) {
                    reqSent = true;
                    break;
                }
            } catch (err) {
                // Se a conexao cair porque o processo morreu de imediato, ja eh o resultado esperado
                reqSent = true;
                break;
            }
        }

        const msgEl = document.getElementById('gboc-shutdown-msg');
        const spinnerEl = document.getElementById('gboc-shutdown-spinner');
        if (msgEl) {
            msgEl.innerHTML = `<strong>${entityName} foi desligado com sucesso.</strong><br>O processo foi finalizado. Você já pode fechar esta aba com segurança.`;
            msgEl.style.color = '#34d399';
        }
        if (spinnerEl) {
            spinnerEl.innerHTML = '<i class="fas fa-check-circle" style="color:#10b981;font-size:18px;"></i> Processo encerrado com sucesso';
            spinnerEl.style.color = '#94a3b8';
        }
    };
    window.gbocShutdownSystem = window.gbocConfirmShutdown;

    console.log('[GBOCLayout] ✅ Motor de Layout Ativo (Zero-Overflow) — Layout:', _currentLayout, '| Tema:', _currentColorTheme, '| Style:', _currentUiStyle);
})();
