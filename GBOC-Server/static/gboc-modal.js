/*
==============================================================================
GBOC System v14.5.0 Enterprise Edition — Modern Modal & Dialog Framework
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
    // 1. UTILITÁRIOS DE SEGURANÇA (XSS PREVENTION & SANITIZAÇÃO)
    // ========================================================================
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function sanitize(content, allowHtml = false) {
        if (allowHtml) {
            return String(content || '');
        }
        return escapeHtml(content);
    }

    function generateUniqueId(prefix = 'gboc-dlg') {
        return `${prefix}-${Math.random().toString(36).substring(2, 9)}-${Date.now()}`;
    }

    // ========================================================================
    // 2. GERENCIADOR DE FOCO & ACESSIBILIDADE (GBOCFocusManager)
    // ========================================================================
    const FOCUSABLE_SELECTOR = 'button:not([disabled]), [href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]):not([disabled])';

    const GBOCFocusManager = {
        getFocusableElements(container) {
            if (!container) return [];
            return Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR)).filter(el => {
                return el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0;
            });
        },

        trapFocus(event, container) {
            if (event.key !== 'Tab') return;
            const focusables = this.getFocusableElements(container);
            if (focusables.length === 0) {
                event.preventDefault();
                return;
            }

            const firstEl = focusables[0];
            const lastEl = focusables[focusables.length - 1];

            if (event.shiftKey) {
                if (document.activeElement === firstEl || !container.contains(document.activeElement)) {
                    event.preventDefault();
                    lastEl.focus();
                }
            } else {
                if (document.activeElement === lastEl || !container.contains(document.activeElement)) {
                    event.preventDefault();
                    firstEl.focus();
                }
            }
        },

        saveFocus() {
            return document.activeElement;
        },

        restoreFocus(prevElement) {
            if (prevElement && typeof prevElement.focus === 'function' && document.body.contains(prevElement)) {
                try {
                    prevElement.focus();
                } catch (e) {}
            }
        }
    };

    // ========================================================================
    // 3. GERENCIADOR DA PILHA DE MODAIS (GBOCModalManager — LIFO STACK)
    // ========================================================================
    let scrollLockCount = 0;
    let originalPaddingRight = '';

    const GBOCModalManager = {
        stack: [],

        push(entry) {
            this.stack.push(entry);
            this.lockScroll();
        },

        pop(id) {
            const index = id ? this.stack.findIndex(m => m.id === id) : this.stack.length - 1;
            if (index >= 0) {
                const removed = this.stack.splice(index, 1)[0];
                this.unlockScroll();
                
                // Se ainda há modais na pilha, foca no topo
                const topModal = this.getTop();
                if (topModal && topModal.element) {
                    const focusables = GBOCFocusManager.getFocusableElements(topModal.element);
                    if (focusables.length > 0) {
                        focusables[0].focus();
                    }
                } else if (removed.prevFocus) {
                    GBOCFocusManager.restoreFocus(removed.prevFocus);
                }
                return removed;
            }
            return null;
        },

        getTop() {
            return this.stack.length > 0 ? this.stack[this.stack.length - 1] : null;
        },

        closeTop() {
            const top = this.getTop();
            if (top && typeof top.onEscape === 'function') {
                top.onEscape();
            }
        },

        lockScroll() {
            if (scrollLockCount === 0) {
                const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
                originalPaddingRight = document.body.style.paddingRight || '';
                if (scrollbarWidth > 0) {
                    document.body.style.paddingRight = `${scrollbarWidth}px`;
                }
                document.documentElement.classList.add('gboc-modal-open');
                document.body.classList.add('gboc-modal-open');
            }
            scrollLockCount++;
        },

        unlockScroll() {
            scrollLockCount = Math.max(0, scrollLockCount - 1);
            if (scrollLockCount === 0) {
                document.documentElement.classList.remove('gboc-modal-open');
                document.body.classList.remove('gboc-modal-open');
                document.body.style.paddingRight = originalPaddingRight;
            }
        }
    };

    // Ouvinte global para Teclado (Tab Trap & Escape LIFO)
    document.addEventListener('keydown', (e) => {
        const top = GBOCModalManager.getTop();
        if (!top) return;

        if (e.key === 'Escape') {
            e.preventDefault();
            GBOCModalManager.closeTop();
        } else if (e.key === 'Tab' && top.element) {
            GBOCFocusManager.trapFocus(e, top.element);
        }
    });

    // ========================================================================
    // 4. DIALOG BUILDER & CORE API (GBOCModal)
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
            let opts = {};
            if (typeof msgOrOptions === 'string') {
                opts = { message: msgOrOptions, ...extraOptions };
            } else if (typeof msgOrOptions === 'object' && msgOrOptions !== null) {
                opts = { ...msgOrOptions, ...extraOptions };
            }

            const rawMsg = String(opts.message || '');
            const lowerMsg = rawMsg.toLowerCase();
            let type = opts.type;
            if (!type) {
                if (opts.danger || lowerMsg.includes('excluir') || lowerMsg.includes('remover') || lowerMsg.includes('cancelar') || lowerMsg.includes('deletar') || lowerMsg.includes('desconectar') || lowerMsg.includes('reset') || lowerMsg.includes('encerrar') || lowerMsg.includes('kill') || rawMsg.includes('⚠️')) {
                    type = 'danger';
                } else if (lowerMsg.includes('atenção') || lowerMsg.includes('aviso')) {
                    type = 'warning';
                } else {
                    type = 'primary';
                }
            }

            const allowHtml = !!opts.allowHtml;
            const title = sanitize(opts.title || (type === 'danger' ? 'Confirmação de Segurança' : 'Confirmação'), allowHtml);
            const message = sanitize(rawMsg || 'Deseja prosseguir com esta ação?', allowHtml);
            const isDanger = type === 'danger' || !!opts.danger;
            const confirmText = sanitize(opts.confirmText || (isDanger ? 'Sim, Confirmar' : 'Confirmar'), false);
            const cancelText = sanitize(opts.cancelText || 'Cancelar', false);
            const badge = sanitize(opts.badge || 'GBOC Enterprise', false);
            const details = opts.details ? escapeHtml(opts.details) : null;
            const sizeClass = opts.size ? `gboc-dialog-card--${opts.size}` : 'gboc-dialog-card--md';

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

            const uid = generateUniqueId('gboc-confirm');
            const titleId = `title-${uid}`;
            const msgId = `msg-${uid}`;
            const prevFocus = GBOCFocusManager.saveFocus();

            return new Promise((resolve) => {
                const overlay = document.createElement('div');
                overlay.className = 'gboc-dialog-overlay';
                overlay.id = uid;
                overlay.setAttribute('role', 'dialog');
                overlay.setAttribute('aria-modal', 'true');
                overlay.setAttribute('aria-labelledby', titleId);
                overlay.setAttribute('aria-describedby', msgId);

                overlay.innerHTML = `
                    <div class="gboc-dialog-card ${sizeClass}">
                        <div class="gboc-dialog-header">
                            <div class="gboc-dialog-icon-wrapper ${iconThemeClass}">
                                <i class="${iconClass}"></i>
                            </div>
                            <div class="gboc-dialog-title-group">
                                <span class="gboc-dialog-badge">${badge}</span>
                                <h3 class="gboc-dialog-title" id="${titleId}">${title}</h3>
                            </div>
                        </div>
                        <div class="gboc-dialog-body">
                            <p class="gboc-dialog-message" id="${msgId}">${message}</p>
                            ${details ? `<div class="gboc-dialog-details">${details}</div>` : ''}
                        </div>
                        <div class="gboc-dialog-actions">
                            <button type="button" class="gboc-dialog-btn gboc-dialog-btn-cancel" data-gboc-action="cancel">
                                <i class="fas fa-times"></i> ${cancelText}
                            </button>
                            <button type="button" class="gboc-dialog-btn ${confirmBtnClass}" data-gboc-action="confirm">
                                <i class="fas fa-check"></i> ${confirmText}
                            </button>
                        </div>
                    </div>
                `;

                document.body.appendChild(overlay);

                let isClosed = false;
                function cleanup(result) {
                    if (isClosed) return;
                    isClosed = true;

                    GBOCModalManager.pop(uid);
                    overlay.classList.remove('gboc-active');
                    setTimeout(() => {
                        overlay.remove();
                        resolve(result);
                    }, 240);
                }

                GBOCModalManager.push({
                    id: uid,
                    element: overlay,
                    prevFocus,
                    onEscape: () => cleanup(false)
                });

                // Entrada suave
                requestAnimationFrame(() => {
                    overlay.classList.add('gboc-active');
                    const btnConfirm = overlay.querySelector('[data-gboc-action="confirm"]');
                    if (btnConfirm) btnConfirm.focus();
                });

                const btnConfirm = overlay.querySelector('[data-gboc-action="confirm"]');
                const btnCancel = overlay.querySelector('[data-gboc-action="cancel"]');

                if (btnConfirm) btnConfirm.addEventListener('click', () => cleanup(true));
                if (btnCancel) btnCancel.addEventListener('click', () => cleanup(false));

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
            let opts = {};
            if (typeof msgOrOptions === 'string') {
                opts = { message: msgOrOptions, ...extraOptions };
            } else if (typeof msgOrOptions === 'object' && msgOrOptions !== null) {
                opts = { ...msgOrOptions, ...extraOptions };
            }

            const rawMsg = String(opts.message || '');
            const lowerMsg = rawMsg.toLowerCase();
            let type = opts.type;
            if (!type) {
                if (lowerMsg.includes('sucesso') || lowerMsg.includes('concluíd') || lowerMsg.includes('iniciad') || lowerMsg.includes('salvo') || rawMsg.includes('🚀') || rawMsg.includes('✅') || rawMsg.includes('⚡') || rawMsg.includes('🛠️')) {
                    type = 'success';
                } else if (lowerMsg.includes('erro') || lowerMsg.includes('falha') || lowerMsg.includes('exception') || lowerMsg.includes('invalid') || rawMsg.includes('❌') || rawMsg.includes('✗')) {
                    type = 'error';
                } else if (lowerMsg.includes('atenção') || lowerMsg.includes('aviso') || lowerMsg.includes('warning') || rawMsg.includes('⚠️')) {
                    type = 'warning';
                } else {
                    type = 'info';
                }
            }

            const allowHtml = !!opts.allowHtml;
            const title = sanitize(opts.title || (type === 'success' ? 'Operação Concluída' : (type === 'error' || type === 'danger' ? 'Erro no Sistema' : (type === 'warning' ? 'Atenção' : 'Aviso do Sistema'))), allowHtml);
            const message = sanitize(rawMsg || '', allowHtml);
            const btnText = sanitize(opts.btnText || 'Entendido', false);
            const badge = sanitize(opts.badge || (type === 'success' ? 'GBOC Sucesso' : (type === 'error' || type === 'danger' ? 'GBOC Erro' : 'GBOC Info')), false);
            const details = opts.details ? escapeHtml(opts.details) : null;
            const sizeClass = opts.size ? `gboc-dialog-card--${opts.size}` : 'gboc-dialog-card--md';

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

            const uid = generateUniqueId('gboc-alert');
            const titleId = `title-${uid}`;
            const msgId = `msg-${uid}`;
            const prevFocus = GBOCFocusManager.saveFocus();

            return new Promise((resolve) => {
                const overlay = document.createElement('div');
                overlay.className = 'gboc-dialog-overlay';
                overlay.id = uid;
                overlay.setAttribute('role', 'dialog');
                overlay.setAttribute('aria-modal', 'true');
                overlay.setAttribute('aria-labelledby', titleId);
                overlay.setAttribute('aria-describedby', msgId);

                overlay.innerHTML = `
                    <div class="gboc-dialog-card ${sizeClass}">
                        <div class="gboc-dialog-header">
                            <div class="gboc-dialog-icon-wrapper ${iconThemeClass}">
                                <i class="${iconClass}"></i>
                            </div>
                            <div class="gboc-dialog-title-group">
                                <span class="gboc-dialog-badge">${badge}</span>
                                <h3 class="gboc-dialog-title" id="${titleId}">${title}</h3>
                            </div>
                        </div>
                        <div class="gboc-dialog-body">
                            <p class="gboc-dialog-message" id="${msgId}">${message}</p>
                            ${details ? `<div class="gboc-dialog-details">${details}</div>` : ''}
                        </div>
                        <div class="gboc-dialog-actions">
                            <button type="button" class="gboc-dialog-btn ${confirmBtnClass}" data-gboc-action="ok">
                                <i class="fas fa-check"></i> ${btnText}
                            </button>
                        </div>
                    </div>
                `;

                document.body.appendChild(overlay);

                let isClosed = false;
                function cleanup() {
                    if (isClosed) return;
                    isClosed = true;

                    GBOCModalManager.pop(uid);
                    overlay.classList.remove('gboc-active');
                    setTimeout(() => {
                        overlay.remove();
                        resolve();
                    }, 240);
                }

                GBOCModalManager.push({
                    id: uid,
                    element: overlay,
                    prevFocus,
                    onEscape: () => cleanup()
                });

                requestAnimationFrame(() => {
                    overlay.classList.add('gboc-active');
                    const btnOk = overlay.querySelector('[data-gboc-action="ok"]');
                    if (btnOk) btnOk.focus();
                });

                const btnOk = overlay.querySelector('[data-gboc-action="ok"]');
                if (btnOk) btnOk.addEventListener('click', cleanup);
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
            let opts = {};
            if (typeof msgOrOptions === 'string') {
                opts = { message: msgOrOptions, defaultValue, ...extraOptions };
            } else if (typeof msgOrOptions === 'object' && msgOrOptions !== null) {
                opts = { defaultValue, ...msgOrOptions, ...extraOptions };
            }

            const allowHtml = !!opts.allowHtml;
            const title = sanitize(opts.title || 'Entrada de Dados', allowHtml);
            const message = sanitize(opts.message || 'Informe o valor:', allowHtml);
            const placeholder = escapeHtml(opts.placeholder || '');
            const inputType = escapeHtml(opts.inputType || 'text');
            const confirmText = sanitize(opts.confirmText || 'Confirmar', false);
            const cancelText = sanitize(opts.cancelText || 'Cancelar', false);
            const badge = sanitize(opts.badge || 'GBOC Prompt', false);
            const initialVal = escapeHtml(opts.defaultValue || defaultValue || '');
            const sizeClass = opts.size ? `gboc-dialog-card--${opts.size}` : 'gboc-dialog-card--md';

            const uid = generateUniqueId('gboc-prompt');
            const titleId = `title-${uid}`;
            const msgId = `msg-${uid}`;
            const prevFocus = GBOCFocusManager.saveFocus();

            return new Promise((resolve) => {
                const overlay = document.createElement('div');
                overlay.className = 'gboc-dialog-overlay';
                overlay.id = uid;
                overlay.setAttribute('role', 'dialog');
                overlay.setAttribute('aria-modal', 'true');
                overlay.setAttribute('aria-labelledby', titleId);
                overlay.setAttribute('aria-describedby', msgId);

                overlay.innerHTML = `
                    <div class="gboc-dialog-card ${sizeClass}">
                        <div class="gboc-dialog-header">
                            <div class="gboc-dialog-icon-wrapper gboc-dialog-icon-info">
                                <i class="fas fa-pen-to-square"></i>
                            </div>
                            <div class="gboc-dialog-title-group">
                                <span class="gboc-dialog-badge">${badge}</span>
                                <h3 class="gboc-dialog-title" id="${titleId}">${title}</h3>
                            </div>
                        </div>
                        <div class="gboc-dialog-body">
                            <p class="gboc-dialog-message" id="${msgId}">${message}</p>
                            <div class="gboc-dialog-input-wrap">
                                <input type="${inputType}" class="gboc-dialog-input" data-gboc-input="prompt" 
                                       placeholder="${placeholder}" value="${initialVal}">
                            </div>
                        </div>
                        <div class="gboc-dialog-actions">
                            <button type="button" class="gboc-dialog-btn gboc-dialog-btn-cancel" data-gboc-action="cancel">
                                <i class="fas fa-times"></i> ${cancelText}
                            </button>
                            <button type="button" class="gboc-dialog-btn gboc-dialog-btn-confirm" data-gboc-action="confirm">
                                <i class="fas fa-check"></i> ${confirmText}
                            </button>
                        </div>
                    </div>
                `;

                document.body.appendChild(overlay);

                const inputEl = overlay.querySelector('[data-gboc-input="prompt"]');
                const btnConfirm = overlay.querySelector('[data-gboc-action="confirm"]');
                const btnCancel = overlay.querySelector('[data-gboc-action="cancel"]');

                let isClosed = false;
                function cleanup(val) {
                    if (isClosed) return;
                    isClosed = true;

                    GBOCModalManager.pop(uid);
                    overlay.classList.remove('gboc-active');
                    setTimeout(() => {
                        overlay.remove();
                        resolve(val);
                    }, 240);
                }

                GBOCModalManager.push({
                    id: uid,
                    element: overlay,
                    prevFocus,
                    onEscape: () => cleanup(null)
                });

                requestAnimationFrame(() => {
                    overlay.classList.add('gboc-active');
                    if (inputEl) {
                        inputEl.focus();
                        inputEl.select();
                    }
                });

                if (btnConfirm) btnConfirm.addEventListener('click', () => cleanup(inputEl ? inputEl.value : ''));
                if (btnCancel) btnCancel.addEventListener('click', () => cleanup(null));

                if (inputEl) {
                    inputEl.addEventListener('keydown', (e) => {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            cleanup(inputEl.value);
                        }
                    });
                }

                overlay.addEventListener('click', (e) => {
                    if (e.target === overlay) cleanup(null);
                });
            });
        },

        /**
         * Modal de Carregamento / Operação Assíncrona Não-Bloqueante
         * @param {string|object} msgOrOptions
         * @param {object} [extraOptions]
         * @returns {{ update: Function, close: Function }}
         */
        loading(msgOrOptions, extraOptions = {}) {
            let opts = {};
            if (typeof msgOrOptions === 'string') {
                opts = { message: msgOrOptions, ...extraOptions };
            } else if (typeof msgOrOptions === 'object' && msgOrOptions !== null) {
                opts = { ...msgOrOptions, ...extraOptions };
            }

            const allowHtml = !!opts.allowHtml;
            const title = sanitize(opts.title || 'Processando Operação...', allowHtml);
            const message = sanitize(opts.message || 'Por favor, aguarde a conclusão.', allowHtml);
            const badge = sanitize(opts.badge || 'GBOC Background Task', false);
            const cancellable = !!opts.cancellable;
            const cancelText = sanitize(opts.cancelText || 'Cancelar Tarefa', false);
            const sizeClass = opts.size ? `gboc-dialog-card--${opts.size}` : 'gboc-dialog-card--sm';

            const uid = generateUniqueId('gboc-loading');
            const titleId = `title-${uid}`;
            const msgId = `msg-${uid}`;
            const prevFocus = GBOCFocusManager.saveFocus();

            const overlay = document.createElement('div');
            overlay.className = 'gboc-dialog-overlay';
            overlay.id = uid;
            overlay.setAttribute('role', 'dialog');
            overlay.setAttribute('aria-modal', 'true');
            overlay.setAttribute('aria-labelledby', titleId);
            overlay.setAttribute('aria-describedby', msgId);

            overlay.innerHTML = `
                <div class="gboc-dialog-card ${sizeClass}">
                    <div class="gboc-dialog-header">
                        <div class="gboc-dialog-icon-wrapper gboc-dialog-icon-loading">
                            <div class="gboc-dialog-spinner"></div>
                        </div>
                        <div class="gboc-dialog-title-group">
                            <span class="gboc-dialog-badge">${badge}</span>
                            <h3 class="gboc-dialog-title" id="${titleId}">${title}</h3>
                        </div>
                    </div>
                    <div class="gboc-dialog-body">
                        <p class="gboc-dialog-message" id="${msgId}">${message}</p>
                        <div class="gboc-dialog-progress-bar">
                            <div class="gboc-dialog-progress-fill indeterminate" data-gboc-progress="fill"></div>
                        </div>
                    </div>
                    ${cancellable ? `
                        <div class="gboc-dialog-actions">
                            <button type="button" class="gboc-dialog-btn gboc-dialog-btn-cancel" data-gboc-action="cancel">
                                <i class="fas fa-times"></i> ${cancelText}
                            </button>
                        </div>
                    ` : ''}
                </div>
            `;

            document.body.appendChild(overlay);

            let isClosed = false;
            let onCancelCallback = typeof opts.onCancel === 'function' ? opts.onCancel : null;

            function closeLoader(reason = 'done') {
                if (isClosed) return;
                isClosed = true;

                GBOCModalManager.pop(uid);
                overlay.classList.remove('gboc-active');
                setTimeout(() => {
                    overlay.remove();
                }, 240);
            }

            GBOCModalManager.push({
                id: uid,
                element: overlay,
                prevFocus,
                onEscape: () => {
                    if (cancellable) {
                        if (onCancelCallback) onCancelCallback();
                        closeLoader('cancelled');
                    }
                }
            });

            requestAnimationFrame(() => {
                overlay.classList.add('gboc-active');
                const btnCancel = overlay.querySelector('[data-gboc-action="cancel"]');
                if (btnCancel) btnCancel.focus();
            });

            const btnCancel = overlay.querySelector('[data-gboc-action="cancel"]');
            if (btnCancel) {
                btnCancel.addEventListener('click', () => {
                    if (onCancelCallback) onCancelCallback();
                    closeLoader('cancelled');
                });
            }

            return {
                update(updateOpts = {}) {
                    if (isClosed) return;
                    if (updateOpts.title) {
                        const tEl = overlay.querySelector(`#${titleId}`);
                        if (tEl) tEl.innerHTML = sanitize(updateOpts.title, allowHtml);
                    }
                    if (updateOpts.message) {
                        const mEl = overlay.querySelector(`#${msgId}`);
                        if (mEl) mEl.innerHTML = sanitize(updateOpts.message, allowHtml);
                    }
                    if (typeof updateOpts.progress === 'number') {
                        const fill = overlay.querySelector('[data-gboc-progress="fill"]');
                        if (fill) {
                            fill.classList.remove('indeterminate');
                            fill.style.width = `${Math.min(100, Math.max(0, updateOpts.progress))}%`;
                        }
                    }
                },
                close() {
                    closeLoader('done');
                }
            };
        },

        /**
         * Abre qualquer modal HTML existente com controle de stack e suporte a ESC
         * @param {string|HTMLElement} elOrId
         */
        open(elOrId) {
            const el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
            if (!el) return;

            el.classList.add('active', 'show', 'gboc-modal-active');
            if (el.style.display === 'none') {
                el.style.display = 'flex';
            }

            const uid = el.id || generateUniqueId('gboc-html-modal');
            const prevFocus = GBOCFocusManager.saveFocus();

            GBOCModalManager.push({
                id: uid,
                element: el,
                prevFocus,
                onEscape: () => GBOCModal.close(el)
            });

            // Foco inicial
            const focusables = GBOCFocusManager.getFocusableElements(el);
            if (focusables.length > 0) {
                focusables[0].focus();
            }
        },

        /**
         * Fecha qualquer modal HTML existente
         * @param {string|HTMLElement} elOrId
         */
        close(elOrId) {
            const el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
            if (!el) return;

            const uid = el.id;
            GBOCModalManager.pop(uid);

            el.classList.remove('active', 'show', 'gboc-modal-active');
        }
    };

    // ========================================================================
    // 5. EXPOSIÇÃO GLOBAL & INTERCEPTAÇÃO TRANSPARENTE
    // ========================================================================
    window.GBOCModal = GBOCModal;
    window.GBOCFocusManager = GBOCFocusManager;
    window.GBOCModalManager = GBOCModalManager;

    window.gbocConfirm = GBOCModal.confirm.bind(GBOCModal);
    window.gbocAlert = GBOCModal.alert.bind(GBOCModal);
    window.gbocPrompt = GBOCModal.prompt.bind(GBOCModal);
    window.gbocLoading = GBOCModal.loading.bind(GBOCModal);
    window.openGBOCModal = GBOCModal.open.bind(GBOCModal);
    window.closeGBOCModal = GBOCModal.close.bind(GBOCModal);

    // Substituição transparente e assíncrona dos diálogos nativos do navegador
    try {
        window._nativeAlert = window._nativeAlert || window.alert;
        window.alert = function (msg) {
            return GBOCModal.alert(msg);
        };
    } catch (e) {}

    console.log('✨ GBOC Enterprise Modal & Dialog Framework v15.0.0 carregado com sucesso.');

})(window, document);
