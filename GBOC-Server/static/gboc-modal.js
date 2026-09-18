/*
==============================================================================
GBOC System v14.4.0 Enterprise Edition — Modern Modal & Dialog Framework
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Kyle Zantos Motion Principles: Glassmorphism, Fluid Transitions & Accessible Dialogs
==============================================================================
*/

(function (window, document) {
    'use strict';

    if (window.GBOCModal && window.GBOCModal.__initialized) {
        return;
    }

    // ========================================================================
    // 1. INJEÇÃO DE ESTILOS CSS DO MODAL SYSTEM
    // ========================================================================
    function injectModalStyles() {
        if (document.getElementById('gboc-modal-styles')) return;

        const style = document.createElement('style');
        style.id = 'gboc-modal-styles';
        style.textContent = `
            /* Container do Diálogo */
            .gboc-dialog-overlay {
                position: fixed;
                inset: 0;
                background: rgba(10, 15, 29, 0.78);
                backdrop-filter: blur(10px);
                -webkit-backdrop-filter: blur(10px);
                z-index: 999999;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 16px;
                opacity: 0;
                visibility: hidden;
                transition: opacity 0.24s cubic-bezier(0.16, 1, 0.3, 1), visibility 0.24s cubic-bezier(0.16, 1, 0.3, 1);
            }
            .gboc-dialog-overlay.gboc-active {
                opacity: 1;
                visibility: visible;
            }

            /* Cartão do Diálogo */
            .gboc-dialog-card {
                background: var(--bg-card, #182033);
                color: var(--text, #f8fafc);
                border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
                border-radius: 18px;
                box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.8), 0 0 0 1px rgba(255, 255, 255, 0.08);
                width: 100%;
                max-width: 520px;
                overflow: hidden;
                transform: scale(0.92) translateY(16px);
                opacity: 0;
                transition: transform 0.26s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.26s cubic-bezier(0.16, 1, 0.3, 1);
            }
            .gboc-dialog-overlay.gboc-active .gboc-dialog-card {
                transform: scale(1) translateY(0);
                opacity: 1;
            }

            /* Cabeçalho / Ícone */
            .gboc-dialog-header {
                padding: 24px 24px 12px 24px;
                display: flex;
                align-items: flex-start;
                gap: 16px;
            }
            .gboc-dialog-icon-wrapper {
                width: 48px;
                height: 48px;
                border-radius: 14px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1.4rem;
                flex-shrink: 0;
            }
            .gboc-dialog-icon-info {
                background: rgba(99, 102, 241, 0.15);
                color: #818cf8;
                border: 1px solid rgba(99, 102, 241, 0.3);
                box-shadow: 0 0 16px rgba(99, 102, 241, 0.2);
            }
            .gboc-dialog-icon-danger {
                background: rgba(239, 68, 68, 0.15);
                color: #ef4444;
                border: 1px solid rgba(239, 68, 68, 0.3);
                box-shadow: 0 0 16px rgba(239, 68, 68, 0.2);
            }
            .gboc-dialog-icon-warning {
                background: rgba(245, 158, 11, 0.15);
                color: #f59e0b;
                border: 1px solid rgba(245, 158, 11, 0.3);
                box-shadow: 0 0 16px rgba(245, 158, 11, 0.2);
            }
            .gboc-dialog-icon-success {
                background: rgba(16, 185, 129, 0.15);
                color: #10b981;
                border: 1px solid rgba(16, 185, 129, 0.3);
                box-shadow: 0 0 16px rgba(16, 185, 129, 0.2);
            }

            .gboc-dialog-title-group {
                flex: 1;
            }
            .gboc-dialog-badge {
                display: inline-block;
                font-size: 0.72rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                padding: 2px 8px;
                border-radius: 6px;
                background: rgba(255, 255, 255, 0.08);
                color: var(--text-muted, #94a3b8);
                margin-bottom: 6px;
            }
            .gboc-dialog-title {
                margin: 0;
                font-size: 1.2rem;
                font-weight: 700;
                color: var(--text, #f8fafc);
                line-height: 1.3;
            }

            /* Corpo da Mensagem */
            .gboc-dialog-body {
                padding: 0 24px 20px 24px;
                color: var(--text-secondary, #cbd5e1);
                font-size: 0.95rem;
                line-height: 1.55;
            }
            .gboc-dialog-message {
                margin: 0;
                white-space: pre-line;
                word-break: break-word;
            }
            .gboc-dialog-details {
                margin-top: 14px;
                background: rgba(0, 0, 0, 0.35);
                border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
                border-radius: 8px;
                padding: 10px 12px;
                font-family: 'Consolas', 'Fira Code', monospace;
                font-size: 0.82rem;
                color: #94a3b8;
                max-height: 140px;
                overflow-y: auto;
                white-space: pre-wrap;
                word-break: break-all;
            }
            .gboc-dialog-input-wrap {
                margin-top: 16px;
            }
            .gboc-dialog-input {
                width: 100%;
                background: var(--bg-input, #0f172a);
                border: 1px solid var(--border, rgba(255, 255, 255, 0.15));
                border-radius: 10px;
                padding: 10px 14px;
                color: var(--text, #f8fafc);
                font-size: 0.95rem;
                outline: none;
                transition: border-color 0.2s, box-shadow 0.2s;
                box-sizing: border-box;
            }
            .gboc-dialog-input:focus {
                border-color: var(--primary-color, #6366f1);
                box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.25);
            }

            /* Rodapé de Ações */
            .gboc-dialog-actions {
                padding: 16px 24px 20px 24px;
                background: rgba(0, 0, 0, 0.15);
                border-top: 1px solid var(--border, rgba(255, 255, 255, 0.06));
                display: flex;
                justify-content: flex-end;
                gap: 12px;
            }
            .gboc-dialog-btn {
                padding: 10px 20px;
                border-radius: 10px;
                font-size: 0.92rem;
                font-weight: 600;
                cursor: pointer;
                border: none;
                display: inline-flex;
                align-items: center;
                gap: 8px;
                transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
                outline: none;
            }
            .gboc-dialog-btn:active {
                transform: scale(0.97);
            }
            .gboc-dialog-btn-cancel {
                background: rgba(255, 255, 255, 0.06);
                color: var(--text-secondary, #cbd5e1);
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            .gboc-dialog-btn-cancel:hover {
                background: rgba(255, 255, 255, 0.12);
                color: var(--text, #ffffff);
            }
            .gboc-dialog-btn-confirm {
                background: linear-gradient(135deg, #6366f1, #4f46e5);
                color: #ffffff;
                box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
            }
            .gboc-dialog-btn-confirm:hover {
                box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5);
                transform: translateY(-1px);
            }
            .gboc-dialog-btn-danger {
                background: linear-gradient(135deg, #ef4444, #dc2626);
                color: #ffffff;
                box-shadow: 0 4px 14px rgba(239, 68, 68, 0.35);
            }
            .gboc-dialog-btn-danger:hover {
                box-shadow: 0 6px 20px rgba(239, 68, 68, 0.5);
                transform: translateY(-1px);
            }
            .gboc-dialog-btn-success {
                background: linear-gradient(135deg, #10b981, #059669);
                color: #ffffff;
                box-shadow: 0 4px 14px rgba(16, 185, 129, 0.35);
            }
            .gboc-dialog-btn-success:hover {
                box-shadow: 0 6px 20px rgba(16, 185, 129, 0.5);
                transform: translateY(-1px);
            }

            /* Light mode adjustments */
            [data-theme="light"] .gboc-dialog-overlay {
                background: rgba(15, 23, 42, 0.55);
            }
            [data-theme="light"] .gboc-dialog-card {
                background: #ffffff;
                color: #0f172a;
                border-color: rgba(0, 0, 0, 0.1);
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
            }
            [data-theme="light"] .gboc-dialog-body {
                color: #334155;
            }
            [data-theme="light"] .gboc-dialog-details {
                background: #f1f5f9;
                color: #475569;
                border-color: #e2e8f0;
            }
            [data-theme="light"] .gboc-dialog-btn-cancel {
                background: #e2e8f0;
                color: #334155;
                border-color: #cbd5e1;
            }
            [data-theme="light"] .gboc-dialog-btn-cancel:hover {
                background: #cbd5e1;
                color: #0f172a;
            }
            [data-theme="light"] .gboc-dialog-input {
                background: #f8fafc;
                color: #0f172a;
                border-color: #cbd5e1;
            }

            /* Global styling for regular .modal and .modal-overlay HTML elements */
            .modal, .modal-overlay {
                backdrop-filter: blur(8px) !important;
                -webkit-backdrop-filter: blur(8px) !important;
                transition: opacity 0.22s cubic-bezier(0.16, 1, 0.3, 1), visibility 0.22s ease !important;
            }
            .modal.active, .modal-overlay.show, .modal[style*="display: flex"], .modal[style*="display: block"] {
                display: flex !important;
            }
            .modal-content, .modal-box {
                border-radius: 16px !important;
                border: 1px solid var(--border, rgba(255,255,255,0.12)) !important;
                box-shadow: 0 25px 60px -10px rgba(0,0,0,0.7) !important;
                animation: gbocModalIn 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;
            }
            @keyframes gbocModalIn {
                from { opacity: 0; transform: scale(0.93) translateY(12px); }
                to { opacity: 1; transform: scale(1) translateY(0); }
            }
            @keyframes gbocModalOut {
                from { opacity: 1; transform: scale(1) translateY(0); }
                to { opacity: 0; transform: scale(0.95) translateY(8px); }
            }
        `;
        document.head.appendChild(style);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', injectModalStyles);
    } else {
        injectModalStyles();
    }

    // ========================================================================
    // 2. DIALOG BUILDER & CONTROLLER
    // ========================================================================
    const GBOCModal = {
        __initialized: true,

        /**
         * Confirmação moderna (substitui window.confirm)
         * @param {string|object} msgOrOptions - Mensagem ou objeto de opções
         * @param {object} [extraOptions] - Opções complementares
         * @returns {Promise<boolean>}
         */
        confirm(msgOrOptions, extraOptions = {}) {
            injectModalStyles();
            let opts = {};
            if (typeof msgOrOptions === 'string') {
                opts = { message: msgOrOptions, ...extraOptions };
            } else if (typeof msgOrOptions === 'object' && msgOrOptions !== null) {
                opts = { ...msgOrOptions, ...extraOptions };
            }

            const title = opts.title || 'Confirmação';
            const message = opts.message || 'Deseja prosseguir com esta ação?';
            const type = opts.type || (opts.danger ? 'danger' : 'primary');
            const isDanger = type === 'danger' || !!opts.danger;
            const confirmText = opts.confirmText || (isDanger ? 'Sim, Confirmar' : 'Confirmar');
            const cancelText = opts.cancelText || 'Cancelar';
            const badge = opts.badge || 'GBOC Enterprise';
            const details = opts.details || null;

            let iconClass = opts.icon;
            if (!iconClass) {
                if (isDanger) iconClass = 'fas fa-triangle-exclamation';
                else if (type === 'warning') iconClass = 'fas fa-exclamation-circle';
                else if (type === 'success') iconClass = 'fas fa-circle-check';
                else iconClass = 'fas fa-circle-question';
            }

            const iconThemeClass = isDanger ? 'gboc-dialog-icon-danger' : 
                                   (type === 'warning' ? 'gboc-dialog-icon-warning' : 
                                   (type === 'success' ? 'gboc-dialog-icon-success' : 'gboc-dialog-icon-info'));

            const confirmBtnClass = isDanger ? 'gboc-dialog-btn-danger' : 
                                    (type === 'success' ? 'gboc-dialog-btn-success' : 'gboc-dialog-btn-confirm');

            return new Promise((resolve) => {
                const overlay = document.createElement('div');
                overlay.className = 'gboc-dialog-overlay';
                overlay.setAttribute('role', 'dialog');
                overlay.setAttribute('aria-modal', 'true');

                overlay.innerHTML = `
                    <div class="gboc-dialog-card">
                        <div class="gboc-dialog-header">
                            <div class="gboc-dialog-icon-wrapper ${iconThemeClass}">
                                <i class="${iconClass}"></i>
                            </div>
                            <div class="gboc-dialog-title-group">
                                <span class="gboc-dialog-badge">${badge}</span>
                                <h3 class="gboc-dialog-title">${title}</h3>
                            </div>
                        </div>
                        <div class="gboc-dialog-body">
                            <p class="gboc-dialog-message">${message}</p>
                            ${details ? `<div class="gboc-dialog-details">${escapeHtml(details)}</div>` : ''}
                        </div>
                        <div class="gboc-dialog-actions">
                            <button type="button" class="gboc-dialog-btn gboc-dialog-btn-cancel" id="gboc-dialog-cancel">
                                <i class="fas fa-times"></i> ${cancelText}
                            </button>
                            <button type="button" class="gboc-dialog-btn ${confirmBtnClass}" id="gboc-dialog-confirm">
                                <i class="${isDanger ? 'fas fa-check' : 'fas fa-check'}"></i> ${confirmText}
                            </button>
                        </div>
                    </div>
                `;

                document.body.appendChild(overlay);

                // Anima entrada
                requestAnimationFrame(() => {
                    overlay.classList.add('gboc-active');
                });

                const btnConfirm = overlay.querySelector('#gboc-dialog-confirm');
                const btnCancel = overlay.querySelector('#gboc-dialog-cancel');

                if (btnConfirm) btnConfirm.focus();

                function cleanup(result) {
                    overlay.classList.remove('gboc-active');
                    document.removeEventListener('keydown', handleKey);
                    setTimeout(() => {
                        overlay.remove();
                        resolve(result);
                    }, 240);
                }

                function handleKey(e) {
                    if (e.key === 'Escape') {
                        e.preventDefault();
                        cleanup(false);
                    } else if (e.key === 'Enter' && document.activeElement !== btnCancel) {
                        e.preventDefault();
                        cleanup(true);
                    }
                }

                document.addEventListener('keydown', handleKey);

                btnConfirm.addEventListener('click', () => cleanup(true));
                btnCancel.addEventListener('click', () => cleanup(false));
                overlay.addEventListener('click', (e) => {
                    if (e.target === overlay) cleanup(false);
                });
            });
        },

        /**
         * Alerta moderno (substitui window.alert)
         * @param {string|object} msgOrOptions
         * @param {object} [extraOptions]
         * @returns {Promise<void>}
         */
        alert(msgOrOptions, extraOptions = {}) {
            injectModalStyles();
            let opts = {};
            if (typeof msgOrOptions === 'string') {
                opts = { message: msgOrOptions, ...extraOptions };
            } else if (typeof msgOrOptions === 'object' && msgOrOptions !== null) {
                opts = { ...msgOrOptions, ...extraOptions };
            }

            const title = opts.title || 'Aviso do Sistema';
            const message = opts.message || '';
            const type = opts.type || 'info';
            const btnText = opts.btnText || 'Entendido';
            const badge = opts.badge || 'GBOC Info';
            const details = opts.details || null;

            let iconClass = opts.icon;
            if (!iconClass) {
                if (type === 'error' || type === 'danger') iconClass = 'fas fa-circle-xmark';
                else if (type === 'warning') iconClass = 'fas fa-triangle-exclamation';
                else if (type === 'success') iconClass = 'fas fa-circle-check';
                else iconClass = 'fas fa-circle-info';
            }

            const iconThemeClass = (type === 'error' || type === 'danger') ? 'gboc-dialog-icon-danger' : 
                                   (type === 'warning' ? 'gboc-dialog-icon-warning' : 
                                   (type === 'success' ? 'gboc-dialog-icon-success' : 'gboc-dialog-icon-info'));

            const confirmBtnClass = (type === 'error' || type === 'danger') ? 'gboc-dialog-btn-danger' : 
                                    (type === 'success' ? 'gboc-dialog-btn-success' : 'gboc-dialog-btn-confirm');

            return new Promise((resolve) => {
                const overlay = document.createElement('div');
                overlay.className = 'gboc-dialog-overlay';
                overlay.setAttribute('role', 'dialog');
                overlay.setAttribute('aria-modal', 'true');

                overlay.innerHTML = `
                    <div class="gboc-dialog-card">
                        <div class="gboc-dialog-header">
                            <div class="gboc-dialog-icon-wrapper ${iconThemeClass}">
                                <i class="${iconClass}"></i>
                            </div>
                            <div class="gboc-dialog-title-group">
                                <span class="gboc-dialog-badge">${badge}</span>
                                <h3 class="gboc-dialog-title">${title}</h3>
                            </div>
                        </div>
                        <div class="gboc-dialog-body">
                            <p class="gboc-dialog-message">${message}</p>
                            ${details ? `<div class="gboc-dialog-details">${escapeHtml(details)}</div>` : ''}
                        </div>
                        <div class="gboc-dialog-actions">
                            <button type="button" class="gboc-dialog-btn ${confirmBtnClass}" id="gboc-dialog-ok">
                                <i class="fas fa-check"></i> ${btnText}
                            </button>
                        </div>
                    </div>
                `;

                document.body.appendChild(overlay);

                requestAnimationFrame(() => {
                    overlay.classList.add('gboc-active');
                });

                const btnOk = overlay.querySelector('#gboc-dialog-ok');
                if (btnOk) btnOk.focus();

                function cleanup() {
                    overlay.classList.remove('gboc-active');
                    document.removeEventListener('keydown', handleKey);
                    setTimeout(() => {
                        overlay.remove();
                        resolve();
                    }, 240);
                }

                function handleKey(e) {
                    if (e.key === 'Escape' || e.key === 'Enter') {
                        e.preventDefault();
                        cleanup();
                    }
                }

                document.addEventListener('keydown', handleKey);
                btnOk.addEventListener('click', cleanup);
                overlay.addEventListener('click', (e) => {
                    if (e.target === overlay) cleanup();
                });
            });
        },

        /**
         * Prompt moderno para entrada de texto
         * @param {string|object} msgOrOptions
         * @param {string} [defaultValue='']
         * @param {object} [extraOptions]
         * @returns {Promise<string|null>}
         */
        prompt(msgOrOptions, defaultValue = '', extraOptions = {}) {
            injectModalStyles();
            let opts = {};
            if (typeof msgOrOptions === 'string') {
                opts = { message: msgOrOptions, defaultValue, ...extraOptions };
            } else if (typeof msgOrOptions === 'object' && msgOrOptions !== null) {
                opts = { defaultValue, ...msgOrOptions, ...extraOptions };
            }

            const title = opts.title || 'Entrada de Dados';
            const message = opts.message || 'Informe o valor:';
            const placeholder = opts.placeholder || '';
            const inputType = opts.inputType || 'text';
            const confirmText = opts.confirmText || 'Confirmar';
            const cancelText = opts.cancelText || 'Cancelar';
            const badge = opts.badge || 'GBOC Prompt';

            return new Promise((resolve) => {
                const overlay = document.createElement('div');
                overlay.className = 'gboc-dialog-overlay';
                overlay.setAttribute('role', 'dialog');
                overlay.setAttribute('aria-modal', 'true');

                overlay.innerHTML = `
                    <div class="gboc-dialog-card">
                        <div class="gboc-dialog-header">
                            <div class="gboc-dialog-icon-wrapper gboc-dialog-icon-info">
                                <i class="fas fa-pen-to-square"></i>
                            </div>
                            <div class="gboc-dialog-title-group">
                                <span class="gboc-dialog-badge">${badge}</span>
                                <h3 class="gboc-dialog-title">${title}</h3>
                            </div>
                        </div>
                        <div class="gboc-dialog-body">
                            <p class="gboc-dialog-message">${message}</p>
                            <div class="gboc-dialog-input-wrap">
                                <input type="${inputType}" class="gboc-dialog-input" id="gboc-prompt-input" 
                                       placeholder="${placeholder}" value="${escapeHtml(opts.defaultValue || '')}">
                            </div>
                        </div>
                        <div class="gboc-dialog-actions">
                            <button type="button" class="gboc-dialog-btn gboc-dialog-btn-cancel" id="gboc-dialog-cancel">
                                <i class="fas fa-times"></i> ${cancelText}
                            </button>
                            <button type="button" class="gboc-dialog-btn gboc-dialog-btn-confirm" id="gboc-dialog-confirm">
                                <i class="fas fa-check"></i> ${confirmText}
                            </button>
                        </div>
                    </div>
                `;

                document.body.appendChild(overlay);

                requestAnimationFrame(() => {
                    overlay.classList.add('gboc-active');
                    const inp = overlay.querySelector('#gboc-prompt-input');
                    if (inp) {
                        inp.focus();
                        inp.select();
                    }
                });

                const inputEl = overlay.querySelector('#gboc-prompt-input');
                const btnConfirm = overlay.querySelector('#gboc-dialog-confirm');
                const btnCancel = overlay.querySelector('#gboc-dialog-cancel');

                function cleanup(val) {
                    overlay.classList.remove('gboc-active');
                    document.removeEventListener('keydown', handleKey);
                    setTimeout(() => {
                        overlay.remove();
                        resolve(val);
                    }, 240);
                }

                function handleKey(e) {
                    if (e.key === 'Escape') {
                        e.preventDefault();
                        cleanup(null);
                    } else if (e.key === 'Enter') {
                        e.preventDefault();
                        cleanup(inputEl ? inputEl.value : '');
                    }
                }

                document.addEventListener('keydown', handleKey);
                btnConfirm.addEventListener('click', () => cleanup(inputEl ? inputEl.value : ''));
                btnCancel.addEventListener('click', () => cleanup(null));
                overlay.addEventListener('click', (e) => {
                    if (e.target === overlay) cleanup(null);
                });
            });
        },

        /**
         * Abre qualquer modal HTML existente com animação suave e suporte a ESC
         * @param {string|HTMLElement} elOrId
         */
        open(elOrId) {
            const el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
            if (!el) return;

            injectModalStyles();
            el.classList.add('active', 'show', 'gboc-modal-active');
            if (el.style.display === 'none') {
                el.style.display = 'flex';
            }

            // Keyboard ESC listener
            const escHandler = (e) => {
                if (e.key === 'Escape') {
                    GBOCModal.close(el);
                    document.removeEventListener('keydown', escHandler);
                }
            };
            el.__escHandler = escHandler;
            document.addEventListener('keydown', escHandler);
        },

        /**
         * Fecha qualquer modal HTML existente
         * @param {string|HTMLElement} elOrId
         */
        close(elOrId) {
            const el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
            if (!el) return;

            el.classList.remove('active', 'show', 'gboc-modal-active');
            if (el.__escHandler) {
                document.removeEventListener('keydown', el.__escHandler);
                delete el.__escHandler;
            }
        }
    };

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // Exposição Global
    window.GBOCModal = GBOCModal;
    window.gbocConfirm = GBOCModal.confirm.bind(GBOCModal);
    window.gbocAlert = GBOCModal.alert.bind(GBOCModal);
    window.gbocPrompt = GBOCModal.prompt.bind(GBOCModal);
    window.openGBOCModal = GBOCModal.open.bind(GBOCModal);
    window.closeGBOCModal = GBOCModal.close.bind(GBOCModal);

    console.log('✨ GBOC Enterprise Modal & Dialog Framework v14.4.0 carregado com sucesso.');

})(window, document);
