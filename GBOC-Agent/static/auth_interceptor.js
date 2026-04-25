/**
 * GBOC Agent - Auth Interceptor
 * Intercepts all fetch calls and redirects to login on 401
 * Include this script in all pages BEFORE other scripts.
 */
(function() {
    const originalFetch = window.fetch;
    let _redirecting = false;

    // Timezone visual padrão do sistema: sempre horário local do cliente
    const _origDateToLocaleString = Date.prototype.toLocaleString;

    window.gbocFormatDateTime = function(value) {
        if (!value) return '—';
        try {
            const raw = String(value);
            // NÃO forçar 'Z': timestamps sem timezone devem respeitar o fuso local
            const d = new Date(raw);
            if (Number.isNaN(d.getTime())) return String(value);
            return _origDateToLocaleString.call(d, 'pt-BR', {
                day: '2-digit', month: '2-digit', year: 'numeric',
                hour: '2-digit', minute: '2-digit', second: '2-digit'
            });
        } catch {
            return String(value);
        }
    };

    // Compat: chamadas Date.toLocaleString() sem parâmetros agora usam padrão local pt-BR
    Date.prototype.toLocaleString = function(locales, options) {
        if (typeof locales === 'undefined' && typeof options === 'undefined') {
            return _origDateToLocaleString.call(this, 'pt-BR', {
                day: '2-digit', month: '2-digit', year: 'numeric',
                hour: '2-digit', minute: '2-digit', second: '2-digit'
            });
        }

        if (typeof locales === 'string' && locales.toLowerCase() === 'pt-br') {
            return _origDateToLocaleString.call(this, locales, options || {
                day: '2-digit', month: '2-digit', year: 'numeric',
                hour: '2-digit', minute: '2-digit', second: '2-digit'
            });
        }

        return _origDateToLocaleString.call(this, locales, options);
    };

    function _doRedirectToLogin() {
        if (_redirecting) return;
        _redirecting = true;
        localStorage.removeItem('gboc_token');
        localStorage.removeItem('gboc_user');
        window.location.href = '/login.html';
    }

    window.fetch = async function(...args) {
        // Add auth token to requests if available
        const token = localStorage.getItem('gboc_token');
        if (token) {
            if (typeof args[1] === 'undefined') args[1] = {};
            if (!args[1].headers) args[1].headers = {};

            // If headers is a Headers object, convert approach
            if (args[1].headers instanceof Headers) {
                if (!args[1].headers.has('Authorization')) {
                    args[1].headers.set('Authorization', 'Bearer ' + token);
                }
            } else {
                if (!args[1].headers['Authorization']) {
                    args[1].headers['Authorization'] = 'Bearer ' + token;
                }
            }
        }

        const response = await originalFetch.apply(this, args);

        // If 401 and we're not already on login page
        if (response.status === 401 && !window.location.pathname.includes('login')) {
            try {
                const cloned = response.clone();
                const data = await cloned.json();
                if (data.code === 'AUTH_REQUIRED') {
                    _doRedirectToLogin();
                    return response;
                }
            } catch(e) {
                // Not JSON or parsing failed - redirect anyway for 401
                _doRedirectToLogin();
            }
        }

        return response;
    };

    // On page load, check auth status
    document.addEventListener('DOMContentLoaded', async function() {
        try {
            const res = await originalFetch('/api/auth/status');
            const data = await res.json();
            if (data.auth_enabled && !data.authenticated) {
                if (!window.location.pathname.includes('login')) {
                    _doRedirectToLogin();
                }
            }
        } catch(e) {
            // Server might be down - don't redirect
        }
    });
})();
