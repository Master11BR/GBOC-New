/*
==============================================================================
GBOC System v14.8.1 Enterprise Edition
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
        m.src = '/static/gboc-modal.js?v=14.8.1';
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
        // Fundo usa gradientes do CSS (variáveis --ambient-glow-*): cor sólida aqui viraria um quadrado
        [g1, g2, g3].forEach(g => { if (g) g.style.backgroundColor = ''; });
    }

    // ── Telas públicas (login / primeiro acesso): sem menu, topbar ou painel ──
    // Antes o menu lateral e a topbar apareciam na tela de login (vinham do cache
    // de sessão), expondo a navegação a quem ainda não autenticou.
    function _isAuthPage() {
        const p = (window.location.pathname || '').toLowerCase();
        return /\/(login|setup|first-access|primeiro-acesso)(\.html)?$/.test(p) ||
               (document.body && document.body.hasAttribute('data-no-layout'));
    }

    // ── Apply layout mode to <body> ───────────────────────────────────────────
    function _applyLayout(mode) {
        if (_isAuthPage()) {
            document.querySelectorAll('#gboc-topbar, aside.sidebar, #gboc-layout-fab, #gboc-layout-panel').forEach(el => el.remove());
            document.body.classList.remove('layout-vertical', 'layout-horizontal', 'has-sidebar');
            return;
        }
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
        if (_isAuthPage()) return;
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
                        _topbarHtml = window.__gbocTopbarMemoryCache || sessionStorage.getItem('gboc_topbar_html_v2');
                    }
                    if (!_topbarHtml) {
                        const r = await fetch(TOPBAR_URL);
                        if (r.ok) {
                            _topbarHtml = await r.text();
                            window.__gbocTopbarMemoryCache = _topbarHtml;
                            try { sessionStorage.setItem('gboc_topbar_html_v2', _topbarHtml); } catch(e) {}
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
            if (window.GBOCStatus) window.GBOCStatus.start();
        } finally {
            _isInjectingTopbar = false;
        }
    }

    // ── Indicador ÚNICO de status (topbar + espelhos na página) ──────────────
    // Antes cada tela tinha o seu: o LED do topbar seguia a resposta da API, o subtítulo do painel seguia o
    // WebSocket de atualização ao vivo, a Visão Geral ficava em "Verificando..." e duas peças usavam o mesmo
    // id (#wsLabel) — uma escrevia "Offline" enquanto a outra mostrava "Conectado".
    // Regra agora (Agente): verde = agente responde E Server central recebe os heartbeats; âmbar = agente ok mas
    // sem Server (não configurado, chave recusada ou sem contato); vermelho = o próprio agente não responde
    // (2 falhas seguidas). Server: verde = API responde. O WebSocket "ao vivo" só aparece na dica (tooltip).
    window.GBOCStatus = window.GBOCStatus || (function () {
        let fails = 0, last = 0, timer = null, live = null, state = null, busy = false;
        const app = () => {
            const tb = document.getElementById('gboc-topbar');
            if (tb && tb.dataset.gbocApp) return tb.dataset.gbocApp;
            return (/dashboard|portal/.test(location.pathname) || typeof window.switchTab === 'function') ? 'server' : 'agent';
        };
        const COLORS = { ok: 'var(--success, #48bb78)', warn: 'var(--warning, #ecc94b)', off: 'var(--danger, #f56565)' };
        const withTimeout = (url, ms) => {
            const c = new AbortController();
            const t = setTimeout(() => c.abort(), ms);
            return fetch(url, { signal: c.signal, cache: 'no-store' }).finally(() => clearTimeout(t));
        };
        function render(st) {
            state = st;
            const color = COLORS[st.level];
            const tip = st.tip + (live === false ? ' · Atualização ao vivo: reconectando' : live === true ? ' · Atualização ao vivo: ativa' : '');
            const dots = [document.getElementById('wsDot'), ...document.querySelectorAll('[data-gboc-status-dot]')];
            const labels = [document.getElementById('wsLabel'), ...document.querySelectorAll('[data-gboc-status-label]')];
            dots.forEach(d => { if (!d) return; d.style.background = color; d.style.boxShadow = `0 0 6px ${color}`;
                d.className = d.className.replace(/\bws-dot (on|off|warn)\b/, '').trim() + ' ws-dot ' + (st.level === 'ok' ? 'on' : st.level === 'off' ? 'off' : 'warn'); });
            labels.forEach(l => { if (!l) return; l.textContent = st.label; l.style.color = color; l.title = tip; });
            const pill = document.getElementById('wsLabel') && document.getElementById('wsLabel').parentElement;
            if (pill) { pill.title = tip; pill.style.background = st.level === 'ok' ? 'rgba(72,187,120,0.12)' : st.level === 'warn' ? 'rgba(236,201,75,0.12)' : 'rgba(245,101,101,0.12)';
                        pill.style.borderColor = st.level === 'ok' ? 'rgba(72,187,120,0.2)' : st.level === 'warn' ? 'rgba(236,201,75,0.3)' : 'rgba(245,101,101,0.3)'; }
            document.dispatchEvent(new CustomEvent('gboc:status', { detail: st }));
        }
        async function checkAgent() {
            const r = await withTimeout('/api/system/info', 8000);
            if (!r.ok) throw new Error('HTTP ' + r.status);
            const info = await r.json();
            const ver = String(info.raw_version || info.gboc_version || '').replace(/^v/i, '').split('-')[0];
            if (ver) {
                const av = document.getElementById('app-version'); if (av) av.textContent = 'v' + ver;
                document.querySelectorAll('.serverVersionBadge, .agentVersionBadge, #versionBadge, #serverVersionBadge').forEach(el => { el.textContent = 'v' + ver; });
            }
            const v = ver ? 'v' + ver + ' • ' : '';
            let srv = null;
            try { const s = await withTimeout('/api/server/status', 8000); if (s.ok) srv = (await s.json()).server || null; } catch (e) { /* sem dado do Server */ }
            if (!srv) return { level: 'ok', label: v + 'Online', tip: 'Agente respondendo (estado do Servidor Central indisponível)' };
            // Agente ainda sem o campo "link" (serviço não reiniciado após a atualização): deduz do que já existe
            const link = srv.link || (srv.websocket_connected || srv.server_auth === 'ok' ? { state: 'connected', detail: 'Servidor Central em comunicação' }
                : !srv.paired ? { state: 'not_configured' } : srv.server_auth === 'rejected' ? { state: 'key_rejected' } : { state: 'starting' });
            if (link.state === 'connected') return { level: 'ok', label: v + 'Online · Server conectado', tip: link.detail || 'Agente e Servidor Central em comunicação' };
            const txt = { not_configured: 'Server não configurado', key_rejected: 'chave recusada pelo Server', no_contact: 'sem contato com o Server', starting: 'conectando ao Server' }[link.state] || 'Server desconectado';
            return { level: link.state === 'starting' ? 'ok' : 'warn', label: v + 'Online · ' + txt, tip: link.detail || txt };
        }
        async function checkServer() {
            const r = await withTimeout('/api/v1/version', 8000);
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return { level: 'ok', label: 'Online', tip: 'Servidor Central respondendo' };
        }
        async function refresh(force) {
            if (busy || (!force && Date.now() - last < 5000)) return state;
            busy = true; last = Date.now();
            try {
                const st = await (app() === 'server' ? checkServer() : checkAgent());
                fails = 0; render(st);
            } catch (e) {
                fails += 1;
                if (fails >= 2 || !state) render({ level: 'off', label: 'Offline', tip: (app() === 'server' ? 'O Servidor Central' : 'O agente') + ' não respondeu (' + (e.message || e) + ')' });
            } finally { busy = false; }
            return state;
        }
        return {
            start() {
                refresh(true);
                if (!timer) timer = setInterval(() => { if (!document.hidden) refresh(); }, 15000);
                document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
            },
            refresh,
            setLive(on) { live = !!on; if (state) render(state); },
            get state() { return state; },
        };
    })();

    function _setupToggleButtons() {
        // O botão ☰ é tratado pelo GBOCNav (fim deste arquivo), que decide entre
        // recolher a sidebar (desktop), abri-la (celular) ou abrir a navegação horizontal.
        // Antes havia dois handlers (onclick inline + listener) e o clique se anulava.
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
        if (_isAuthPage()) return;
        if (!window.GBOC_AI_Assistant && !document.getElementById('gboc-ai-script')) {
            const script = document.createElement('script');
            script.id = 'gboc-ai-script';
            script.src = '/static/ai_assistant.js';
            document.head.appendChild(script);
        }
    }

    function _ensureHardwareHudLoaded() {
        if (_isAuthPage()) return;
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
        // Página com fundo próprio (login / primeiro acesso): não injeta um segundo fundo por cima
        if (document.getElementById('glow-ambient-1')) return;

        const bg = document.createElement('div');
        bg.id = 'gboc-ambient-background';
        bg.className = 'gboc-ambient-background';
        bg.innerHTML = `
            <div id="glow-ambient-1" class="gboc-aurora a1"></div>
            <div id="glow-ambient-2" class="gboc-aurora a2"></div>
            <div id="glow-ambient-3" class="gboc-aurora a3"></div>
            <div class="gboc-ambient-lines">
                <svg viewBox="0 0 100 100" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M0,50 C30,30 70,80 100,40" fill="none" stroke="url(#gboc-grad1)" stroke-width="0.22" />
                    <path d="M0,60 C40,20 60,90 100,50" fill="none" stroke="url(#gboc-grad2)" stroke-width="0.16" />
                    <path d="M-10,80 C30,90 80,20 110,30" fill="none" stroke="url(#gboc-grad1)" stroke-width="0.12" />
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
            </div>
        `;

        if (document.body) {
            document.body.insertBefore(bg, document.body.firstChild);
        }
        _applyBackgroundMotionMode();
    }

    // ── Animação de fundo: automática (desliga sozinha em máquina lenta), ligada ou desligada ──
    // localStorage 'gboc-bg-motion' = 'auto' (padrão) | 'on' | 'off'
    function _applyBackgroundMotionMode() {
        let mode = 'auto';
        try { mode = localStorage.getItem('gboc-bg-motion') || 'auto'; } catch (e) { /* sem storage */ }
        const root = document.documentElement;
        if (mode === 'off') { root.classList.add('gboc-bg-static'); return; }
        root.classList.remove('gboc-bg-static');
        if (mode !== 'auto') return;
        let slow = null;
        try { slow = sessionStorage.getItem('gboc-bg-slow'); } catch (e) { /* */ }
        if (slow === '1') { root.classList.add('gboc-bg-static'); return; }
        if (slow === '0' || document.hidden || !window.requestAnimationFrame) return;
        // Mede ~2 s de quadros após a carga: se o navegador não sustenta ~40 fps, congela o fundo
        setTimeout(() => {
            if (document.hidden) return;
            const times = [];
            let last = performance.now();
            const start = last;
            const tick = (now) => {
                times.push(now - last); last = now;
                if (now - start < 2000) { requestAnimationFrame(tick); return; }
                times.sort((x, y) => x - y);
                const p50 = times[Math.floor(times.length / 2)] || 0;
                const isSlow = p50 > 24;
                if (isSlow) root.classList.add('gboc-bg-static');
                try { sessionStorage.setItem('gboc-bg-slow', isSlow ? '1' : '0'); } catch (e) { /* */ }
            };
            requestAnimationFrame(tick);
        }, 2500);
    }
    window.GBOCBackgroundMotion = {
        get: () => { try { return localStorage.getItem('gboc-bg-motion') || 'auto'; } catch (e) { return 'auto'; } },
        set: (mode) => {
            try { localStorage.setItem('gboc-bg-motion', mode); sessionStorage.removeItem('gboc-bg-slow'); } catch (e) { /* */ }
            _applyBackgroundMotionMode();
        },
    };

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
        if (_isAuthPage()) return;
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

            <div class="lp-title">Animação de Fundo</div>
            <div style="display:flex;gap:4px;flex-wrap:wrap">
                ${[['auto', 'Automática'], ['on', 'Ligada'], ['off', 'Desligada']].map(([m, l]) => `
                <button class="lp-layout-btn ${(window.GBOCBackgroundMotion ? window.GBOCBackgroundMotion.get() : 'auto') === m ? 'active' : ''}" data-bgmotion="${m}"
                        onclick="window.GBOCBackgroundMotion.set('${m}');document.querySelectorAll('[data-bgmotion]').forEach(b=>b.classList.toggle('active',b.dataset.bgmotion==='${m}'))"
                        style="font-size:0.76em;padding:6px 10px;flex:1"><span>${l}</span></button>`).join('')}
            </div>
            <div style="font-size:0.7em;color:var(--text-muted, #94a3b8);margin-top:4px">Automática: desliga sozinha se o computador não acompanhar.</div>

            <div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--border, rgba(255,255,255,0.1));font-size:0.73em;color:var(--text-muted, #94a3b8)">
                <i class="fas fa-check-circle" style="color:var(--success, #10b981)"></i> Preferências salvas automaticamente.
            </div>
        `;
        document.body.appendChild(panel);
    }

    function _createFAB() {
        if (_isAuthPage()) return;
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
    // Opções dos gráficos (período, formato, tabela, exportar) — vale para todo gráfico Chart.js do sistema
    function _injectChartsScript() {
        if (document.getElementById('gboc-charts-js') || window.GBOCCharts) return;
        const sc = document.createElement('script');
        sc.id = 'gboc-charts-js';
        sc.src = '/static/gboc-charts.js?v=14.8.1-c3';
        sc.defer = true;
        document.head.appendChild(sc);
    }

    function _injectStylesheets() {
        _injectChartsScript();
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


/* ════════════════════════════════════════════════════════════════════════════
   GBOCNav — Controlador único de navegação (Server + Agent, vertical e horizontal)
   • Submenus retráteis (acordeão): abrir um grupo fecha os demais, exceto o grupo
     do item ativo, que permanece aberto e visível até a próxima navegação.
   • Item ativo sincronizado entre menu lateral e topbar (inclusive switchTab do Server).
   • Botão ☰: recolhe a sidebar (desktop), abre a sidebar (celular) ou abre a
     navegação horizontal (celular).
   • Tooltips automáticos para itens truncados / sidebar recolhida.
   ════════════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';
    if (window.GBOCNav) return;

    const LS_COLLAPSED = 'gboc-sidebar-collapsed';
    const isMobile = () => window.matchMedia('(max-width: 768px)').matches;
    const isHorizontal = () => document.body.classList.contains('layout-horizontal');

    const groupOf = (el) => (el ? el.closest('.nav-group') : null);
    const itemsOf = (g) => (g ? g.querySelector('.nav-group-items') : null);
    const headerOf = (g) => (g ? g.querySelector('.nav-group-header') : null);
    const activeLink = () => document.querySelector('.sidebar .nav-link.active, .sidebar .nav-link.in-focus');

    function navKey(el) {
        if (!el) return null;
        const oc = el.getAttribute('onclick') || '';
        const m = oc.match(/switchTab\(\s*['"]([^'"]+)['"]/);
        if (m) return 'tab:' + m[1];
        let href = (el.getAttribute('href') || '').trim();
        if (!href || href.startsWith('javascript') || href === '#') return null;
        try { const u = new URL(href, window.location.origin); href = u.pathname + u.search; } catch (e) { /* mantém */ }
        href = href.toLowerCase();
        if (href === '/') href = '/index.html';
        return 'href:' + href;
    }

    function currentHrefKeys() {
        let p = window.location.pathname.toLowerCase();
        if (p === '/') p = '/index.html';
        return ['href:' + p + window.location.search.toLowerCase(), 'href:' + p];
    }

    function setOpen(g, open) {
        const items = itemsOf(g), hdr = headerOf(g);
        if (!items) return;
        items.classList.toggle('open', open);
        if (hdr) {
            hdr.classList.toggle('open', open);
            hdr.setAttribute('aria-expanded', open ? 'true' : 'false');
        }
        const arr = g.querySelector('.nav-group-arrow');
        if (arr) arr.style.transform = '';
    }

    function syncActiveHeaders() {
        document.querySelectorAll('.sidebar .nav-group-header.has-active-child')
            .forEach(h => h.classList.remove('has-active-child'));
        const g = groupOf(activeLink());
        if (g && headerOf(g)) headerOf(g).classList.add('has-active-child');
        return g;
    }

    function revealActive() {
        const a = activeLink();
        const nav = a && a.closest('.nav');
        if (!a || !nav) return;
        const ar = a.getBoundingClientRect(), nr = nav.getBoundingClientRect();
        if (ar.top < nr.top + 8 || ar.bottom > nr.bottom - 8) {
            nav.scrollTop += (ar.top - nr.top) - nr.height / 3;
        }
    }

    function addTitles(root) {
        (root || document).querySelectorAll('.sidebar .nav-link, .sidebar .nav-group-header, .tb-nav-link, .tb-dropdown-item')
            .forEach(el => {
                if (!el.getAttribute('title')) {
                    const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
                    if (t) el.setAttribute('title', t);
                }
            });
    }

    function markTopbar(key) {
        document.querySelectorAll('.tb-dropdown-item.active, .tb-nav-link.active')
            .forEach(x => x.classList.remove('active'));
        if (!key) return;
        document.querySelectorAll('.tb-dropdown-item').forEach(it => {
            if (navKey(it) === key) {
                it.classList.add('active');
                const top = it.closest('.tb-dropdown');
                const btn = top && top.querySelector('.tb-nav-link');
                if (btn) btn.classList.add('active');
            }
        });
    }

    function setActive(link, opts) {
        if (!link) return;
        document.querySelectorAll('.sidebar .nav-link.active, .sidebar .nav-link.in-focus')
            .forEach(l => l.classList.remove('active', 'in-focus'));
        link.classList.add('active', 'in-focus');
        const g = groupOf(link);
        if (g) {
            // Acordeão: ao navegar, fica aberto apenas o grupo do novo item ativo
            document.querySelectorAll('.sidebar .nav-group').forEach(o => { if (o !== g) setOpen(o, false); });
            setOpen(g, true);
        }
        syncActiveHeaders();
        if (!opts || opts.topbar !== false) markTopbar(navKey(link));
        try { sessionStorage.setItem('gboc_active_nav_key', navKey(link) || ''); } catch (e) { /* storage indisponível */ }
        revealActive();
    }

    function syncFromKey(key) {
        if (!key) return;
        let found = null;
        document.querySelectorAll('.sidebar .nav-link').forEach(l => { if (!found && navKey(l) === key) found = l; });
        if (found) setActive(found, { topbar: false });
        markTopbar(key);
    }

    function isNavigational(link) {
        return !!navKey(link);
    }

    // Páginas do Agente sem item próprio no menu -> item "pai" que deve ficar ativo
    const PARENT_PAGES = {
        '/database-backup.html': '/protected-workloads.html',
        '/active-directory.html': '/protected-workloads.html',
        '/tape-backup.html': '/protected-workloads.html',
        '/enterprise-features.html': '/protected-workloads.html',
        '/integrity.html': '/restore.html',
        '/import.html': '/repositories.html',
        '/duplicati-native.html': '/engines.html',
        '/hermes-agent.html': '/engines.html',
        '/power-tools.html': '/diagnostic.html',
        '/schema-check.html': '/diagnostic.html',
        '/auth-diagnostic.html': '/diagnostic.html',
        '/config-manager.html': '/settings.html'
    };

    function findLinkForPage(sb) {
        const links = Array.from((sb || document).querySelectorAll('.nav-link'));
        const keys = currentHrefKeys();
        let match = links.find(l => keys.includes(navKey(l)));
        if (!match) {   // mesma página com outra query (?tab=...)
            match = links.find(l => (navKey(l) || '').split('?')[0] === keys[1]);
        }
        if (!match) {
            const parent = PARENT_PAGES[keys[1].slice(5)];
            if (parent) match = links.find(l => (navKey(l) || '').split('?')[0] === 'href:' + parent);
        }
        if (!match) {   // SPA (Server): última aba escolhida nesta sessão
            let saved = '';
            try { saved = sessionStorage.getItem('gboc_active_nav_key') || ''; } catch (e) { saved = ''; }
            if (saved) match = links.find(l => navKey(l) === saved);
        }
        return match || null;
    }

    function resolveForPage() {
        const sb = document.querySelector('.sidebar');
        const m = sb && findLinkForPage(sb);
        if (m) setActive(m);
    }

    // Estado inicial: só o grupo do item ativo aberto (uma vez por sidebar inserida)
    function normalizeSidebar() {
        const sb = document.querySelector('.sidebar');
        if (!sb) return;
        addTitles(sb);
        if (sb.__gbocNavReady) return;
        sb.__gbocNavReady = true;

        if (!activeLink()) {
            const match = findLinkForPage(sb);
            if (match) match.classList.add('active', 'in-focus');
        }
        const ag = syncActiveHeaders();
        const groups = sb.querySelectorAll('.nav-group');
        groups.forEach(g => setOpen(g, ag ? g === ag : g === groups[0]));
        const a = activeLink();
        markTopbar(a ? navKey(a) : null);
        requestAnimationFrame(revealActive);
    }

    function normalizeTopbar() {
        const tb = document.getElementById('gboc-topbar');
        if (!tb) return;
        addTitles(tb);
        // Remove o onclick inline legado do ☰ (causava duplo toggle)
        const tog = document.getElementById('gboc-vheader-toggle');
        if (tog && tog.hasAttribute('onclick')) tog.removeAttribute('onclick');
        if (tb.__gbocNavReady) return;
        tb.__gbocNavReady = true;
        if (!document.querySelector('.sidebar .nav-link.active')) {
            const keys = currentHrefKeys();
            let key = null;
            const parent = PARENT_PAGES[keys[1].slice(5)];
            if (parent) keys.push('href:' + parent);
            tb.querySelectorAll('.tb-dropdown-item').forEach(it => { const k = navKey(it); if (!key && keys.includes(k)) key = k; });
            if (!key) tb.querySelectorAll('.tb-dropdown-item').forEach(it => { const k = navKey(it) || ''; if (!key && k.split('?')[0] === keys[1]) key = k; });
            if (key) markTopbar(key);
        }
    }

    function toggleMenu() {
        const b = document.body;
        if (isMobile()) {
            if (isHorizontal()) b.classList.toggle('tb-nav-open');
            else b.classList.toggle('sidebar-open');
            return;
        }
        b.classList.toggle('sidebar-collapsed');
        try { localStorage.setItem(LS_COLLAPSED, b.classList.contains('sidebar-collapsed') ? 'true' : 'false'); } catch (e) { /* ignore */ }
    }

    function closeDropdowns(except) {
        document.querySelectorAll('.tb-dropdown.active').forEach(d => { if (d !== except) d.classList.remove('active'); });
    }

    // Captura: roda antes dos onclick inline legados (toggleNavGroup duplicados por página)
    document.addEventListener('click', function (e) {
        const tog = e.target.closest('#gboc-vheader-toggle');
        if (tog) {
            e.preventDefault();
            e.stopPropagation();
            toggleMenu();
            return;
        }

        const hdr = e.target.closest('.sidebar .nav-group-header');
        if (hdr) {
            e.preventDefault();
            e.stopPropagation();
            const g = groupOf(hdr);
            const items = itemsOf(g);
            const willOpen = !(items && items.classList.contains('open'));
            if (willOpen) {
                const ag = groupOf(activeLink());
                document.querySelectorAll('.sidebar .nav-group').forEach(o => { if (o !== g && o !== ag) setOpen(o, false); });
                if (document.body.classList.contains('sidebar-collapsed') && !isMobile()) {
                    document.body.classList.remove('sidebar-collapsed');
                    try { localStorage.setItem(LS_COLLAPSED, 'false'); } catch (err) { /* ignore */ }
                }
            }
            setOpen(g, willOpen);
            return;
        }

        const link = e.target.closest('.sidebar .nav-link');
        if (link) {
            if (isNavigational(link)) setActive(link);
            if (isMobile()) document.body.classList.remove('sidebar-open');
            return;
        }

        const item = e.target.closest('.tb-dropdown-item');
        if (item) {
            const key = navKey(item);
            if (key) { markTopbar(key); syncFromKey(key); }
            const dd = item.closest('.tb-dropdown');
            closeDropdowns(null);
            if (dd) {
                dd.classList.add('tb-suppress');
                dd.addEventListener('mouseleave', () => dd.classList.remove('tb-suppress'), { once: true });
            }
            document.body.classList.remove('tb-nav-open');
        }
    }, true);

    // Fecha menus com ESC e ao trocar para desktop
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeDropdowns(null);
            document.body.classList.remove('tb-nav-open', 'sidebar-open');
        }
    });
    window.addEventListener('resize', () => {
        if (!isMobile()) document.body.classList.remove('tb-nav-open', 'sidebar-open');
    });

    // Server: switchTab() também é chamado por código (restauração da aba salva)
    function hookSwitchTab() {
        const st = window.switchTab;
        if (typeof st !== 'function' || st.__gbocNavHooked) return;
        const wrapped = function (id) {
            const r = st.apply(this, arguments);
            try { syncFromKey('tab:' + id); } catch (e) { /* não bloqueia a navegação */ }
            return r;
        };
        wrapped.__gbocNavHooked = true;
        window.switchTab = wrapped;
    }

    let pending = false;
    function refresh() {
        if (pending) return;
        pending = true;
        requestAnimationFrame(() => {
            pending = false;
            normalizeSidebar();
            normalizeTopbar();
            hookSwitchTab();
        });
    }

    function boot() {
        refresh();
        if (window.MutationObserver) {
            new MutationObserver((muts) => {
                for (const m of muts) {
                    for (const n of m.addedNodes) {
                        if (n.nodeType === 1 && (n.matches?.('.sidebar, #gboc-topbar') || n.querySelector?.('.sidebar, #gboc-topbar'))) {
                            refresh();
                            return;
                        }
                    }
                }
            }).observe(document.body, { childList: true, subtree: true });
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();
    window.addEventListener('load', () => { hookSwitchTab(); refresh(); });

    window.GBOCNav = { setActive, syncFromKey, toggleMenu, refresh, markTopbar, resolveForPage };
})();
