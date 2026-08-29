/*
==============================================================================
GBOC System v13.2.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
/**
 * GBOC v13.2.0 - Dashboard Widget Framework
 * Draggable, resizable, collapsible widget system.
 */
class DashboardWidgets {
    constructor(container, options = {}) {
        this.container = typeof container === 'string' ? document.getElementById(container) : container;
        this.widgets = [];
        this.dragging = null;
        this.storageKey = options.storageKey || 'gboc_widget_layout';
        this.container.style.cssText += ';display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:20px;';
    }

    addWidget(config) {
        const id = config.id || 'w-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
        const w = document.createElement('div');
        w.id = id;
        w.className = 'dashboard-widget';
        w.dataset.widgetId = id;
        w.style.cssText = `background:var(--bg-card);border:1px solid var(--border);border-radius:12px;overflow:hidden;transition:box-shadow .2s;${config.span ? 'grid-column:span ' + config.span + ';' : ''}`;

        w.innerHTML = `
            <div class="widget-header" style="padding:14px 18px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;cursor:move;user-select:none;">
                <h4 style="margin:0;font-size:.92em;display:flex;align-items:center;gap:8px;">
                    <i class="fas ${config.icon || 'fa-chart-bar'}" style="color:${config.color || 'var(--primary)'}"></i>
                    ${config.title || 'Widget'}
                </h4>
                <div style="display:flex;gap:6px;">
                    ${config.fullscreen !== false ? `<button class="wbtn" onclick="dashboardWidgets.toggleFullscreen('${id}')" title="Tela cheia"><i class="fas fa-expand"></i></button>` : ''}
                    <button class="wbtn" onclick="dashboardWidgets.toggleCollapse('${id}')" title="Minimizar"><i class="fas fa-minus"></i></button>
                    ${config.refresh ? `<button class="wbtn" onclick="dashboardWidgets.refreshWidget('${id}')" title="Atualizar"><i class="fas fa-sync-alt"></i></button>` : ''}
                </div>
            </div>
            <div class="widget-body" id="${id}-body" style="padding:${config.noPadding ? '0' : '16px'};min-height:${config.minHeight || '120px'};position:relative;">
                ${config.html || '<div style="text-align:center;color:var(--text-muted);padding:20px;">Carregando...</div>'}
            </div>
        `;

        // Drag events
        const header = w.querySelector('.widget-header');
        header.addEventListener('mousedown', e => this._dragStart(e, w));

        this.container.appendChild(w);
        this.widgets.push({ id, el: w, config, collapsed: false });

        // Auto-refresh
        if (config.onLoad) {
            try { config.onLoad(document.getElementById(id + '-body'), id); } catch (e) { console.error(e); }
        }

        return id;
    }

    refreshWidget(id) {
        const widget = this.widgets.find(w => w.id === id);
        if (widget && widget.config.onLoad) {
            const body = document.getElementById(id + '-body');
            if (body) {
                try { widget.config.onLoad(body, id); } catch (e) { console.error(e); }
            }
        }
    }

    toggleCollapse(id) {
        const widget = this.widgets.find(w => w.id === id);
        if (!widget) return;
        const body = document.getElementById(id + '-body');
        if (!body) return;
        widget.collapsed = !widget.collapsed;
        body.style.display = widget.collapsed ? 'none' : '';
    }

    toggleFullscreen(id) {
        const el = document.getElementById(id);
        if (!el) return;
        if (!document.fullscreenElement) {
            el.requestFullscreen?.();
            el.style.maxHeight = '100vh';
            el.style.overflow = 'auto';
        } else {
            document.exitFullscreen?.();
            el.style.maxHeight = '';
            el.style.overflow = '';
        }
    }

    _dragStart(e, el) {
        if (e.target.tagName === 'BUTTON' || e.target.tagName === 'I') return;
        this.dragging = el;
        el.style.opacity = '0.6';
        el.style.zIndex = '100';

        const onMove = (ev) => {
            // Reorder based on mouse position
            const siblings = [...this.container.children].filter(c => c !== el && c.classList.contains('dashboard-widget'));
            const after = siblings.find(s => {
                const rect = s.getBoundingClientRect();
                return ev.clientY < rect.top + rect.height / 2;
            });
            if (after) this.container.insertBefore(el, after);
            else this.container.appendChild(el);
        };

        const onUp = () => {
            el.style.opacity = '1';
            el.style.zIndex = '';
            this.dragging = null;
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            this._saveLayout();
        };

        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    }

    _saveLayout() {
        try {
            const order = [...this.container.children]
                .filter(c => c.classList.contains('dashboard-widget'))
                .map(c => c.dataset.widgetId);
            localStorage.setItem(this.storageKey, JSON.stringify(order));
        } catch (e) {}
    }

    _loadLayout() {
        try {
            const order = JSON.parse(localStorage.getItem(this.storageKey) || '[]');
            if (!order.length) return;
            order.forEach(id => {
                const el = document.getElementById(id);
                if (el) this.container.appendChild(el);
            });
        } catch (e) {}
    }

    removeWidget(id) {
        const idx = this.widgets.findIndex(w => w.id === id);
        if (idx >= 0) {
            this.widgets[idx].el.remove();
            this.widgets.splice(idx, 1);
        }
    }

    refreshAll() {
        this.widgets.forEach(w => this.refreshWidget(w.id));
    }
}

// Global style for widget buttons
(function() {
    const style = document.createElement('style');
    style.textContent = `.wbtn{background:none;border:none;color:var(--text-muted);cursor:pointer;padding:4px 6px;border-radius:4px;font-size:.78em;transition:all .15s;}.wbtn:hover{color:var(--text);background:var(--bg-input);}`;
    document.head.appendChild(style);
})();

window.DashboardWidgets = DashboardWidgets;
