/*
==============================================================================
GBOC System v14.0.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
/*
 * 🔔 GBOC Agent - Toast Notifications (BLINDADO)
 * - Não quebra se carregado no <head> (espera document.body existir)
 * - Cria showToast() global e compatível com legado
 */

(function () {
    if (window.ToastNotification) return;

    class ToastNotification {
        constructor() {
            this.container = null;
            this.createContainer();
        }

        createContainer() {
            const ensure = () => {
                if (!document.body) return;

                if (!document.getElementById('toast-container')) {
                    this.container = document.createElement('div');
                    this.container.id = 'toast-container';
                    this.container.style.cssText = `
                        position: fixed;
                        top: 20px;
                        right: 20px;
                        z-index: 10000;
                        display: flex;
                        flex-direction: column;
                        gap: 10px;
                        max-width: 420px;
                    `;
                    document.body.appendChild(this.container);
                } else {
                    this.container = document.getElementById('toast-container');
                }
            };

            // tenta agora; se não der, agenda
            ensure();
            if (!this.container) {
                document.addEventListener('DOMContentLoaded', ensure, { once: true });
            }
        }

        show(message, type = 'info', duration = 5000) {
            if (!this.container) this.createContainer();
            if (!this.container) {
                // fallback sem quebrar página
                console.log(`[TOAST:${type}] ${message}`);
                return null;
            }

            const toast = document.createElement('div');
            const id = 'toast-' + Date.now();
            toast.id = id;

            const colors = {
                success: { bg: '#48bb78', icon: '✅' },
                error: { bg: '#f56565', icon: '❌' },
                warning: { bg: '#ed8936', icon: '⚠️' },
                info: { bg: '#4299e1', icon: 'ℹ️' },
                loading: { bg: '#9f7aea', icon: '⏳' }
            };

            const style = colors[type] || colors.info;

            toast.style.cssText = `
                background: ${style.bg};
                color: white;
                padding: 12px 16px;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.35);
                display: flex;
                align-items: center;
                gap: 10px;
                animation: slideIn 0.25s ease;
                cursor: pointer;
                min-width: 320px;
                max-width: 420px;
                word-break: break-word;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                font-size: 14px;
            `;

            toast.innerHTML = `
                <span style="font-size: 18px;">${style.icon}</span>
                <span style="flex: 1;">${message}</span>
                <span style="font-size: 18px; opacity: 0.75;">×</span>
            `;

            toast.onclick = () => this.remove(id);
            this.container.appendChild(toast);

            if (duration > 0) {
                setTimeout(() => this.remove(id), duration);
            }
            return id;
        }

        remove(id) {
            const el = document.getElementById(id);
            if (el) {
                el.style.opacity = '0';
                el.style.transform = 'translateX(420px)';
                el.style.transition = 'all 0.25s ease';
                setTimeout(() => el.remove(), 250);
            }
        }

        update(id, message, type = 'info', duration = 5000) {
            this.remove(id);
            return this.show(message, type, duration);
        }
    }

    window.ToastNotification = ToastNotification;
    window.toast = new ToastNotification();

    // showToast global padronizado + compatível com legado:
    // showToast("msg", "info|success|warning|error|loading", 5000)
    // showToast("msg", true, 5000) (legado: boolean => erro)
    if (!window.showToast) {
        window.showToast = function (message, typeOrIsError = 'info', duration = 5000) {
            const isBoolean = typeof typeOrIsError === 'boolean';
            const type = isBoolean ? (typeOrIsError ? 'error' : 'info') : String(typeOrIsError || 'info');

            if (window.toast && typeof window.toast.show === 'function') {
                window.toast.show(message, type, duration);
                return;
            }

            alert(message);
        };
    }

    if (!document.getElementById('toast-styles')) {
        const style = document.createElement('style');
        style.id = 'toast-styles';
        style.textContent = `
            @keyframes slideIn {
                from { transform: translateX(420px); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
        `;
        document.head.appendChild(style);
    }
})();