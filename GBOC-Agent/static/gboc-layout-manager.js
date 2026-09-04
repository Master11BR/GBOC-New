/*
==============================================================================
GBOC System v14.0.0 Enterprise Edition
Layout & Navigation Manager — Controls Dual Layout Engine (Vertical/Horizontal)
and Color Themes across all resolutions (1024px, 720p HD, 1080p FHD, 4K UHD).
Zero-Overflow & Smart Sidebar Presence Detection.
==============================================================================
*/

(function () {
    'use strict';

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

    // ── Constants ─────────────────────────────────────────────────────────────
    const LS_LAYOUT = 'gboc-layout';          // 'vertical' | 'horizontal'
    const LS_COLOR  = 'gboc-color-theme';     // 'dark' | 'light' | 'purple' | 'ocean'
    const LS_COLLAPSED = 'gboc-sidebar-collapsed';
    const TOPBAR_URL = '/static/_topbar.html';

    const THEMES = [
        { id: 'dark',   label: 'Dark',   icon: '🌙' },
        { id: 'light',  label: 'Light',  icon: '☀️' },
        { id: 'purple', label: 'Purple', icon: '💜' },
        { id: 'ocean',  label: 'Ocean',  icon: '🌊' }
    ];

    // ── State ─────────────────────────────────────────────────────────────────
    let _currentLayout = localStorage.getItem(LS_LAYOUT) || 'vertical';
    let _currentColorTheme = localStorage.getItem(LS_COLOR) || localStorage.getItem('gboc-theme') || 'dark';
    let _panelOpen = false;
    let _topbarHtml = null;

    // ── Detect sidebar in DOM ─────────────────────────────────────────────────
    function _checkSidebarPresence() {
        const hasSidebar = !!document.querySelector('.sidebar, aside.sidebar');
        document.body.classList.toggle('has-sidebar', hasSidebar);
        return hasSidebar;
    }

    // ── Apply color theme to <html> ───────────────────────────────────────────
    function _applyColorTheme(theme) {
        document.documentElement.setAttribute('data-color-theme', theme);
        // Keep legacy data-theme in sync for backward compat
        if (theme === 'dark' || theme === 'light') {
            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem('gboc-theme', theme);
        } else {
            // Purple and ocean are dark-ish base
            document.documentElement.setAttribute('data-theme', theme === 'ocean' ? 'light' : 'dark');
        }
        _currentColorTheme = theme;
        localStorage.setItem(LS_COLOR, theme);
        _updatePanelActiveStates();
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

    async function _injectSidebar() {
        if (_currentLayout !== 'vertical') return;
        if (!document.querySelector('.sidebar, aside.sidebar')) {
            try {
                if (!_sidebarHtml) {
                    const r = await fetch(SIDEBAR_URL);
                    if (r.ok) {
                        _sidebarHtml = await r.text();
                    }
                }
                if (_sidebarHtml) {
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
            }
        }
    }

    // ── Fetch & inject topbar & hero backdrop ─────────────────────────────────
    async function _injectTopbar() {
        if (!document.getElementById('gboc-hero-bg')) {
            const hero = document.createElement('div');
            hero.id = 'gboc-hero-bg';
            hero.className = 'gboc-hero-bg';
            document.body.appendChild(hero);
        }

        if (!document.getElementById('gboc-topbar')) {
            try {
                if (!_topbarHtml) {
                    const r = await fetch(TOPBAR_URL);
                    if (r.ok) {
                        _topbarHtml = await r.text();
                    }
                }
                if (_topbarHtml) {
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
            const r = await fetch('/api/v1/version');
            if (r.ok) {
                const data = await r.json();
                const badge = document.getElementById('serverVersionBadge');
                if (badge && data.raw_version) {
                    badge.textContent = `v${data.raw_version}`;
                    badge.title = data.semver || `GBOC Agent v${data.raw_version}`;
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

        const panel = document.createElement('div');
        panel.id = 'gboc-layout-panel';
        panel.className = 'gboc-layout-panel';
        panel.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
                <span style="font-weight:700;font-size:0.9em;display:flex;align-items:center;gap:6px">
                    <i class="fas fa-palette" style="color:var(--primary, #6366f1)"></i> Personalizar Interface
                </span>
                <button onclick="window.GBOCLayout.togglePanel()" style="background:none;border:none;color:var(--text-muted, #94a3b8);cursor:pointer;font-size:1.1em" aria-label="Fechar painel">
                    <i class="fas fa-times"></i>
                </button>
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

            <div class="lp-title">Tema de Cor</div>
            <div class="lp-themes" id="lp-theme-swatches">${themesHtml}</div>
            <div style="display:flex;gap:12px;flex-wrap:wrap">
                ${THEMES.map(t => `<div style="font-size:0.7em;color:var(--text-muted, #94a3b8);text-align:center;min-width:34px">${t.icon}<br>${t.label}</div>`).join('')}
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
        setLayout(mode) {
            _applyLayout(mode);
        },
        setTheme(theme) {
            _applyColorTheme(theme);
        },
        togglePanel() {
            _panelOpen = !_panelOpen;
            const panel = document.getElementById('gboc-layout-panel');
            if (panel) panel.classList.toggle('open', _panelOpen);
        },
        getLayout() { return _currentLayout; },
        getTheme()  { return _currentColorTheme; },
        refreshSidebarPresence() { _checkSidebarPresence(); }
    };

    // ── Bootstrap ─────────────────────────────────────────────────────────────
    function _bootstrap() {
        _injectStylesheets();
        _ensureAiAssistantLoaded();
        _ensureHardwareHudLoaded();
        _applyColorTheme(_currentColorTheme);
        _applyLayout(_currentLayout);
        _createFAB();
        _createPanel();
        _checkSidebarPresence();

        // Observe dynamic DOM changes for sidebar injection
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
        document.addEventListener('DOMContentLoaded', () => {
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

    console.log('[GBOCLayout] ✅ Motor de Layout Ativo (Zero-Overflow) — Layout:', _currentLayout, '| Tema:', _currentColorTheme);
})();
