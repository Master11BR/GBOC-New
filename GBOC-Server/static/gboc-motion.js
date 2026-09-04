/* ============================================================================
   GBOC System v14.0.0 Full Stable Enterprise — Motion Principles & UX Engine (Kyle Zantos)
   Automatic Skeleton Screens, Lazy Loading & Smooth Motion Animations
   ============================================================================ */

(function(window) {
    'use strict';

    const GBOCMotion = {
        /**
         * Inicializa o observador de Intersection Observer para lazy loading de elementos.
         */
        initLazyLoading(selector = '.lazy-load') {
            if (!('IntersectionObserver' in window)) {
                document.querySelectorAll(selector).forEach(el => el.classList.add('lazy-loaded'));
                return;
            }

            const observer = new IntersectionObserver((entries, obs) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('lazy-loaded');
                        obs.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.1, rootMargin: '50px' });

            document.querySelectorAll(selector).forEach(el => observer.observe(el));
        },

        /**
         * Gera esqueleto visual animado em tabelas durante o carregamento de dados.
         */
        showTableSkeleton(tbodyEl, rows = 5, cols = 4) {
            if (typeof tbodyEl === 'string') tbodyEl = document.querySelector(tbodyEl);
            if (!tbodyEl) return;

            let html = '';
            for (let i = 0; i < rows; i++) {
                html += '<tr class="skeleton-row-container">';
                for (let j = 0; j < cols; j++) {
                    html += `<td><div class="skeleton skeleton-text" style="width:${Math.floor(Math.random() * 40 + 50)}%"></div></td>`;
                }
                html += '</tr>';
            }
            tbodyEl.innerHTML = html;
        },

        /**
         * Gera esqueleto visual para cards e estatísticas.
         */
        showCardSkeleton(containerEl, count = 3) {
            if (typeof containerEl === 'string') containerEl = document.querySelector(containerEl);
            if (!containerEl) return;

            let html = '';
            for (let i = 0; i < count; i++) {
                html += `
                    <div class="panel skeleton-card-container motion-slide-up" style="background:var(--bg-card,#182035);padding:20px;border-radius:14px;border:1px solid var(--border,#2a3f5f)">
                        <div class="skeleton skeleton-title"></div>
                        <div class="skeleton skeleton-text" style="width:85%"></div>
                        <div class="skeleton skeleton-text" style="width:40%"></div>
                    </div>
                `;
            }
            containerEl.innerHTML = html;
        },

        /**
         * Aplica animações de transição de entrada/saída a um elemento DOM.
         */
        animate(element, motionClass = 'motion-slide-up', duration = 300) {
            if (typeof element === 'string') element = document.querySelector(element);
            if (!element) return Promise.resolve();

            return new Promise((resolve) => {
                element.classList.remove('motion-slide-up', 'motion-slide-down', 'motion-fade-in', 'motion-fade-out');
                element.classList.add(motionClass);

                setTimeout(() => {
                    resolve(element);
                }, duration);
            });
        }
    };

    document.addEventListener('DOMContentLoaded', () => {
        GBOCMotion.initLazyLoading();
    });

    window.GBOCMotion = GBOCMotion;
})(window);
