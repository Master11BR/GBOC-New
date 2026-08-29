/*
==============================================================================
GBOC System v13.2.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
/**
 * GBOC v13.2.0 - Activity Heatmap (GitHub-style)
 * Renders a year-view heatmap of backup activity using Canvas.
 */
class ActivityHeatmap {
    constructor(container, options = {}) {
        this.container = typeof container === 'string' ? document.getElementById(container) : container;
        this.cellSize = options.cellSize || 14;
        this.cellGap = options.cellGap || 3;
        this.weeks = options.weeks || 52;
        this.colors = options.colors || ['#1a202c', '#1e4a3a', '#276749', '#38a169', '#48bb78'];
        this.data = {};
        this.canvas = null;
        this.ctx = null;
        this.tooltip = null;
        this._init();
    }

    _init() {
        const w = (this.cellSize + this.cellGap) * this.weeks + 40;
        const h = (this.cellSize + this.cellGap) * 7 + 30;
        this.canvas = document.createElement('canvas');
        this.canvas.width = w;
        this.canvas.height = h;
        this.canvas.style.cssText = 'max-width:100%;cursor:crosshair;';
        this.container.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');

        // Tooltip
        this.tooltip = document.createElement('div');
        this.tooltip.style.cssText = 'position:fixed;background:#2d3748;color:#eaeaea;padding:6px 10px;border-radius:6px;font-size:0.78em;pointer-events:none;display:none;z-index:9999;box-shadow:0 2px 8px rgba(0,0,0,.4);';
        document.body.appendChild(this.tooltip);

        this.canvas.addEventListener('mousemove', e => this._onHover(e));
        this.canvas.addEventListener('mouseleave', () => { this.tooltip.style.display = 'none'; });
    }

    setData(data) {
        // data: { "YYYY-MM-DD": count, ... }
        this.data = data || {};
        this.render();
    }

    render() {
        const ctx = this.ctx;
        const cs = this.cellSize;
        const gap = this.cellGap;
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Day labels
        const days = ['', 'Seg', '', 'Qua', '', 'Sex', ''];
        ctx.fillStyle = '#a0aec0';
        ctx.font = '10px sans-serif';
        days.forEach((d, i) => {
            if (d) ctx.fillText(d, 0, 28 + i * (cs + gap) + cs - 2);
        });

        // Cells
        const today = new Date();
        const maxVal = Math.max(1, ...Object.values(this.data));
        this._cells = [];

        for (let w = 0; w < this.weeks; w++) {
            for (let d = 0; d < 7; d++) {
                const date = new Date(today);
                date.setDate(date.getDate() - ((this.weeks - 1 - w) * 7 + (6 - d)));
                const key = date.toISOString().slice(0, 10);
                const count = this.data[key] || 0;
                const level = count === 0 ? 0 : Math.min(4, Math.ceil((count / maxVal) * 4));
                const x = 35 + w * (cs + gap);
                const y = 20 + d * (cs + gap);

                ctx.fillStyle = this.colors[level];
                ctx.beginPath();
                ctx.roundRect(x, y, cs, cs, 2);
                ctx.fill();

                this._cells.push({ x, y, key, count, date: new Date(date) });
            }
        }

        // Month labels
        ctx.fillStyle = '#a0aec0';
        ctx.font = '10px sans-serif';
        let lastMonth = -1;
        for (let w = 0; w < this.weeks; w++) {
            const date = new Date(today);
            date.setDate(date.getDate() - (this.weeks - 1 - w) * 7);
            if (date.getMonth() !== lastMonth) {
                lastMonth = date.getMonth();
                const months = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
                ctx.fillText(months[lastMonth], 35 + w * (cs + gap), 14);
            }
        }
    }

    _onHover(e) {
        const rect = this.canvas.getBoundingClientRect();
        const scaleX = this.canvas.width / rect.width;
        const mx = (e.clientX - rect.left) * scaleX;
        const my = (e.clientY - rect.top) * scaleX;
        const cs = this.cellSize;

        const cell = (this._cells || []).find(c =>
            mx >= c.x && mx <= c.x + cs && my >= c.y && my <= c.y + cs
        );

        if (cell) {
            this.tooltip.style.display = 'block';
            this.tooltip.style.left = (e.clientX + 12) + 'px';
            this.tooltip.style.top = (e.clientY - 30) + 'px';
            const dateStr = cell.date.toLocaleDateString('pt-BR');
            this.tooltip.textContent = `${dateStr}: ${cell.count} backup${cell.count !== 1 ? 's' : ''}`;
        } else {
            this.tooltip.style.display = 'none';
        }
    }

    async loadFromAPI(days = 365) {
        try {
            const res = await fetch(`/api/statistics/daily-activity?days=${days}`);
            if (res.ok) {
                const data = await res.json();
                this.setData(data.activity || data);
            }
        } catch (e) {
            console.warn('[Heatmap] API error:', e);
        }
    }

    destroy() {
        if (this.tooltip && this.tooltip.parentNode) this.tooltip.parentNode.removeChild(this.tooltip);
        if (this.canvas && this.canvas.parentNode) this.canvas.parentNode.removeChild(this.canvas);
    }
}

window.ActivityHeatmap = ActivityHeatmap;
