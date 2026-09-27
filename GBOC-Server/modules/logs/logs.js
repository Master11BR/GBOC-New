// Module: Logs Controller (logs.js) - Premium Toast Notification UI
let activeFilter = 'all';
let allLogs = [];
let isLoading = false;
let searchTerm = '';

document.addEventListener('DOMContentLoaded', () => {
    initToastFilterEvents();
    loadLogsData();
});

function initToastFilterEvents() {
    document.querySelectorAll('.filter').forEach(button => {
        button.addEventListener('click', () => {
            activeFilter = button.dataset.filter;

            document.querySelectorAll('.filter').forEach(b => {
                b.classList.toggle('active', b === button);
            });

            render(true);
        });
    });

    const clearBtn = document.getElementById('clear');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            const items = visibleItems();
            if (!items.length) return;
            const ids = new Set(items.map(n => n.id));
            for (let i = allLogs.length - 1; i >= 0; i--) {
                if (ids.has(allLogs[i].id)) allLogs.splice(i, 1);
            }
            render(true);
        });
    }
}

function mapLogToType(level, message = '') {
    const lvl = (level || 'info').toLowerCase();
    const msg = (message || '').toLowerCase();
    if (lvl.includes('err') || lvl.includes('crit') || lvl.includes('fatal') || msg.includes('[error]') || msg.includes('[critical]') || msg.includes('falha') || msg.includes('error:')) return 'error';
    if (lvl.includes('warn') || msg.includes('[warning]') || msg.includes('[warn]') || msg.includes('alerta') || msg.includes('threshold=') || msg.includes('[perf-slow]')) return 'warning';
    if (lvl.includes('succ') || lvl.includes('ok') || msg.includes('[success]') || msg.includes('[ok]') || msg.includes('sucesso') || msg.includes('concluíd') || msg.includes('concluido') || msg.includes('migrada com sucesso') || msg.includes('iniciado com sucesso')) return 'success';
    return 'info';
}

function getLogIcon(type) {
    if (type === 'success') return '✓';
    if (type === 'info') return 'i';
    if (type === 'warning') return '!';
    if (type === 'error') return '×';
    return 'i';
}

function formatTimestamp(ts) {
    if (!ts) return '';
    try {
        const d = new Date(ts);
        if (isNaN(d.getTime())) return ts;
        return d.toLocaleString('pt-BR', { day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit' });
    } catch(e) { return ts; }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function visibleItems() {
    return allLogs.filter(n => {
        const matchType = activeFilter === 'all' || n.type === activeFilter;
        if (!matchType) return false;
        if (!searchTerm) return true;
        const term = searchTerm.toLowerCase();
        return (n.message && n.message.toLowerCase().includes(term)) ||
               (n.title && n.title.toLowerCase().includes(term)) ||
               (n.source && n.source.toLowerCase().includes(term)) ||
               (n.agent && n.agent.toLowerCase().includes(term));
    });
}

function render(animate = true) {
    const list = document.getElementById('list');
    const empty = document.getElementById('empty');
    const count = document.getElementById('count');
    if (!list) return;

    const items = visibleItems();
    list.innerHTML = '';

    items.forEach((n, index) => {
        const el = document.createElement('article');
        el.className = 'toast';
        el.dataset.type = n.type;
        el.dataset.id = n.id;
        if (!animate) el.style.animation = 'none';

        el.innerHTML = `
            <div class="icon" aria-hidden="true">${n.icon}</div>
            <div class="copy">
                <strong>
                    <span>${n.title}</span>
                    <span class="meta-badge">${escapeHtml(n.agent)}</span>
                    ${n.source ? `<span class="meta-badge" style="opacity:0.85">${escapeHtml(n.source)}</span>` : ''}
                    ${n.timestamp ? `<span class="time-badge">${n.timestamp}</span>` : ''}
                </strong>
                <span class="msg-text">${escapeHtml(n.message)}</span>
            </div>
            <div class="toast-actions">
                <button class="dismiss" aria-label="Remover notificação" title="Dispensar">×</button>
            </div>
        `;

        el.style.animationDelay = `${Math.min(index * 45, 600)}ms`;

        el.querySelector('.dismiss').addEventListener('click', (e) => {
            e.stopPropagation();
            remove(n.id, el);
        });
        list.appendChild(el);
    });

    if (count) count.textContent = `(${items.length})`;
    if (empty) empty.classList.toggle('show', items.length === 0);
}

function remove(id, element) {
    const i = allLogs.findIndex(n => n.id === id);
    if (i >= 0) allLogs.splice(i, 1);

    element.classList.add('removing');
    element.addEventListener('animationend', () => render(false), { once: true });
}

function handleSearchInput() {
    searchTerm = document.getElementById('log-search')?.value?.trim() || '';
    render(false);
}

async function loadLogsData() {
    if (isLoading) return;
    isLoading = true;
    const list = document.getElementById('list');
    const empty = document.getElementById('empty');

    try {
        const url = `/api/v1/logs?limit=250`;
        const r = await fetch(url);
        if (!r.ok) throw new Error('HTTP ' + r.status);

        const data = await r.json();
        const logs = data.logs || [];

        allLogs = logs.map((l, idx) => {
            const msg = l.message || '';
            const type = mapLogToType(l.level, msg);
            const origLevel = (l.level || '').toUpperCase();
            let displayTitle = origLevel || type.toUpperCase();
            if (type === 'success' && origLevel === 'INFO') {
                displayTitle = 'SUCCESS';
            }
            return {
                id: l.id || `${Date.now()}_${idx}`,
                type: type,
                icon: getLogIcon(type),
                title: displayTitle,
                agent: l.agent_name || l.agent_id || 'Servidor',
                source: l.source || 'core',
                message: msg,
                timestamp: formatTimestamp(l.timestamp)
            };
        });

        render(true);
    } catch (e) {
        console.error('Erro ao carregar logs:', e);
        if (allLogs.length === 0 && list) {
            list.innerHTML = `
                <article class="toast" data-type="error">
                    <div class="icon">×</div>
                    <div class="copy">
                        <strong>FALHA AO CONECTAR</strong>
                        <span class="msg-text">Não foi possível carregar os registros de logs do servidor.</span>
                    </div>
                    <div class="toast-actions">
                        <button class="dismiss" onclick="this.closest('.toast').remove()">×</button>
                    </div>
                </article>
            `;
            if (empty) empty.classList.remove('show');
        }
    } finally {
        isLoading = false;
    }
}
