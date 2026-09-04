/*
==============================================================================
GBOC System v14.0.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
/**
 * GBOC v14.0.0 - Execution Timeline (Gantt-like)
 * Renders backup execution timeline with hover details.
 */
class ExecutionTimeline {
    constructor(container, options = {}) {
        this.container = typeof container === 'string' ? document.getElementById(container) : container;
        this.barHeight = options.barHeight || 24;
        this.barGap = options.barGap || 6;
        this.colors = {
            completed: '#48bb78',
            failed: '#f56565',
            running: '#4299e1',
            pending: '#a0aec0'
        };
        this.data = [];
        this.el = null;
        this.tooltip = null;
        this._init();
    }

    _init() {
        this.el = document.createElement('div');
        this.el.style.cssText = 'position:relative;overflow-x:auto;overflow-y:auto;max-height:400px;';
        this.container.appendChild(this.el);

        this.tooltip = document.createElement('div');
        this.tooltip.style.cssText = 'position:fixed;background:#2d3748;color:#eaeaea;padding:8px 12px;border-radius:6px;font-size:.78em;pointer-events:none;display:none;z-index:9999;box-shadow:0 2px 8px rgba(0,0,0,.4);max-width:280px;';
        document.body.appendChild(this.tooltip);
    }

    setData(executions) {
        this.data = executions || [];
        this.render();
    }

    render() {
        if (!this.data.length) {
            this.el.innerHTML = '<div style="text-align:center;color:#a0aec0;padding:30px;">Sem execuções para exibir</div>';
            return;
        }

        // Determine time range
        const now = new Date();
        let minTime = new Date(now - 24 * 60 * 60 * 1000);
        let maxTime = new Date(now);

        this.data.forEach(ex => {
            const s = new Date(ex.started_at);
            const e = ex.completed_at ? new Date(ex.completed_at) : now;
            if (s < minTime) minTime = s;
            if (e > maxTime) maxTime = e;
        });

        const range = maxTime - minTime || 1;
        const width = Math.max(800, this.container.clientWidth - 180);
        const labelW = 160;
        const totalW = labelW + width + 20;
        const totalH = this.data.length * (this.barHeight + this.barGap) + 40;

        let html = `<div style="position:relative;width:${totalW}px;min-height:${totalH}px;">`;

        // Time axis
        html += `<div style="position:absolute;top:0;left:${labelW}px;width:${width}px;height:24px;display:flex;justify-content:space-between;font-size:.72em;color:#a0aec0;">`;
        for (let i = 0; i <= 6; i++) {
            const t = new Date(minTime.getTime() + (range / 6) * i);
            html += `<span>${t.toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit'})}</span>`;
        }
        html += '</div>';

        // Bars
        this.data.forEach((ex, idx) => {
            const s = new Date(ex.started_at);
            const e = ex.completed_at ? new Date(ex.completed_at) : now;
            const left = ((s - minTime) / range) * width;
            const w = Math.max(4, ((e - s) / range) * width);
            const top = 28 + idx * (this.barHeight + this.barGap);
            const color = this.colors[ex.status] || '#a0aec0';
            const name = ex.task_name || `Task #${ex.task_id}`;

            // Label
            html += `<div style="position:absolute;top:${top}px;left:0;width:${labelW - 8}px;height:${this.barHeight}px;display:flex;align-items:center;font-size:.78em;color:#eaeaea;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${this._esc(name)}">${this._esc(name)}</div>`;

            // Bar
            html += `<div class="tl-bar" data-idx="${idx}" style="position:absolute;top:${top}px;left:${labelW + left}px;width:${w}px;height:${this.barHeight}px;background:${color};border-radius:4px;cursor:pointer;opacity:.85;transition:opacity .15s;" onmouseenter="this.style.opacity='1'" onmouseleave="this.style.opacity='.85'"></div>`;
        });

        html += '</div>';
        this.el.innerHTML = html;

        // Attach hover events
        this.el.querySelectorAll('.tl-bar').forEach(bar => {
            bar.addEventListener('mousemove', e => this._showTooltip(e, parseInt(bar.dataset.idx)));
            bar.addEventListener('mouseleave', () => { this.tooltip.style.display = 'none'; });
        });
    }

    _showTooltip(e, idx) {
        const ex = this.data[idx];
        if (!ex) return;
        const dur = ex.duration_seconds ? `${Math.floor(ex.duration_seconds / 60)}m ${ex.duration_seconds % 60}s` : '-';
        const start = ex.started_at ? new Date(ex.started_at).toLocaleString('pt-BR') : '-';
        this.tooltip.innerHTML = `
            <strong>${this._esc(ex.task_name || 'Task #' + ex.task_id)}</strong><br>
            Status: <span style="color:${this.colors[ex.status]||'#a0aec0'}">${ex.status}</span><br>
            Início: ${start}<br>
            Duração: ${dur}<br>
            ${ex.files_processed ? 'Arquivos: ' + ex.files_processed + '<br>' : ''}
            ${ex.bytes_processed ? 'Dados: ' + this._fmtBytes(ex.bytes_processed) : ''}
        `;
        this.tooltip.style.display = 'block';
        this.tooltip.style.left = (e.clientX + 14) + 'px';
        this.tooltip.style.top = (e.clientY - 10) + 'px';
    }

    _esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
    _fmtBytes(b) {
        if (!b) return '0 B';
        const u = ['B', 'KB', 'MB', 'GB'];
        let i = 0; while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
        return b.toFixed(1) + ' ' + u[i];
    }

    async loadFromAPI(hours = 24) {
        try {
            const res = await fetch(`/api/statistics/executions?hours=${hours}&limit=50`);
            if (res.ok) {
                const data = await res.json();
                this.setData(data.executions || data);
            }
        } catch (e) {
            console.warn('[Timeline] API error:', e);
        }
    }

    destroy() {
        if (this.tooltip && this.tooltip.parentNode) this.tooltip.parentNode.removeChild(this.tooltip);
        if (this.el && this.el.parentNode) this.el.parentNode.removeChild(this.el);
    }
}

window.ExecutionTimeline = ExecutionTimeline;
