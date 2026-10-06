/* GBOC System v14.8.1 Enterprise Edition */
/* Module: Reports JavaScript Controller (Server) */

let srvFlagships = [];
let srvAllReports = [];
let srvSelectedReportId = null;
let srvCurrentCategory = 'ALL';
let srvCurrentMode = 'flagships';

// Renomeada: no dashboard existia outra loadReportsTab() (Relatórios Consolidados) que era
// sobrescrita por esta, deixando os KPIs da aba sem carregar.
async function loadReportsModule() {
    console.log('[ReportsModule] Carregando módulo de relatórios...');
    loadFlagships();
    loadInternalDataModules();
}

function switchReportsMode(mode) {
    srvCurrentMode = mode;
    const secFlagships = document.getElementById('sectionFlagships');
    const secModules = document.getElementById('sectionDataModules');
    const btnFlagships = document.getElementById('btnTabFlagships');
    const btnModules = document.getElementById('btnTabDataModules');

    if (mode === 'flagships') {
        if (secFlagships) secFlagships.style.display = 'block';
        if (secModules) secModules.style.display = 'none';
        if (btnFlagships) {
            btnFlagships.classList.add('btn-primary');
            btnFlagships.classList.remove('btn-default');
        }
        if (btnModules) {
            btnModules.classList.remove('btn-primary');
        }
    } else {
        if (secFlagships) secFlagships.style.display = 'none';
        if (secModules) secModules.style.display = 'block';
        if (btnModules) {
            btnModules.classList.add('btn-primary');
            btnModules.classList.remove('btn-default');
        }
        if (btnFlagships) {
            btnFlagships.classList.remove('btn-primary');
        }
    }
}

// ---------------------------------------------------------------------
// 7 Flagships v2.0 Controller
// ---------------------------------------------------------------------

async function loadFlagships() {
    const grid = document.getElementById('flagshipsGrid');
    if (!grid) return;

    try {
        const base = window.GBOC_API_BASE || '';
        const r = await fetch(`${base}/api/v1/reports/flagships`);
        const d = await r.json();
        srvFlagships = d.flagships || [];
        renderFlagshipsGrid();
    } catch (e) {
        console.error('[ReportsModule] Erro ao carregar flagships:', e);
        if (grid) {
            grid.innerHTML = `<p style="color:var(--danger);padding:20px;grid-column:1/-1;text-align:center">Erro ao conectar com API de Flagships: ${e.message}</p>`;
        }
    }
}

function renderFlagshipsGrid() {
    const grid = document.getElementById('flagshipsGrid');
    if (!grid) return;

    if (!srvFlagships || srvFlagships.length === 0) {
        grid.innerHTML = '<p style="color:var(--text-muted);text-align:center;grid-column:1/-1;padding:30px">Nenhum relatório flagship localizado.</p>';
        return;
    }

    const iconMap = {
        'REP-F1': 'fa-shield-halved',
        'REP-F2': 'fa-biohazard',
        'REP-F3': 'fa-hard-drive',
        'REP-F4': 'fa-scale-balanced',
        'REP-F5': 'fa-gauge-high',
        'REP-F6': 'fa-coins',
        'REP-F7': 'fa-truck-medical'
    };

    grid.innerHTML = srvFlagships.map(f => {
        const icon = iconMap[f.id] || 'fa-chart-line';
        return `
            <div class="flagship-card">
                <div>
                    <div class="flagship-card-top">
                        <span class="flagship-code"><i class="fas ${icon}"></i> ${f.id}</span>
                        <span class="flagship-target"><i class="fas fa-users"></i> ${f.audience || 'TI / Gestão'}</span>
                    </div>
                    <div class="flagship-title">${f.name}</div>
                    <div class="flagship-desc">${f.objective || f.description || ''}</div>
                    <div class="flagship-replaces">
                        <strong>Substitui / Consolida:</strong> ${f.replaces || 'Módulos de dados'}
                    </div>
                </div>
                <div class="flagship-actions">
                    <button class="btn btn-primary btn-sm" onclick="openFlagship('${f.id}', 'html')" style="flex:1">
                        <i class="fas fa-eye"></i> Visualizar
                    </button>
                    <button class="btn btn-sm" onclick="openFlagship('${f.id}', 'pdf')" title="Imprimir em A4 / Salvar PDF">
                        <i class="fas fa-print"></i> PDF/A4
                    </button>
                    <button class="btn btn-sm" onclick="openFlagship('${f.id}', 'csv')" title="Exportar dados tabulares">
                        <i class="fas fa-file-csv"></i> CSV
                    </button>
                    <button class="btn btn-sm" onclick="openFlagship('${f.id}', 'json')" title="API Payload JSON">
                        <i class="fas fa-code"></i> JSON
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function openFlagship(flagshipId, format) {
    const base = window.GBOC_API_BASE || '';
    let url = `${base}/api/v1/reports/flagships/${flagshipId}?format=${format}`;
    if (format === 'pdf') {
        url = `${base}/api/v1/reports/flagships/${flagshipId}?format=html&print=1`;
    }
    window.open(url, '_blank');
}

// ---------------------------------------------------------------------
// 50 Internal Data Modules Controller
// ---------------------------------------------------------------------

async function loadInternalDataModules() {
    const container = document.getElementById('srvReportsList');
    if (!container) return;

    try {
        const base = window.GBOC_API_BASE || '';
        const r = await fetch(base + '/api/v1/reports/catalog');
        const d = await r.json();
        srvAllReports = d.reports || [];
        renderSrvReportsList();
    } catch (e) {
        console.error('[ReportsModule] Erro ao carregar catálogo interno:', e);
        container.innerHTML = `<p style="color:var(--danger);padding:20px;text-align:center;">Erro ao conectar com API: ${e.message}</p>`;
    }
}

function renderSrvReportsList() {
    const container = document.getElementById('srvReportsList');
    if (!container) return;

    const searchTxt = (document.getElementById('srvReportSearch')?.value || '').trim().toLowerCase();

    const filtered = srvAllReports.filter(rep => {
        const repCat = (rep.category || '').toLowerCase();
        const repName = (rep.name || '').toLowerCase();
        const repCode = (rep.code || '').toLowerCase();
        const repId = String(rep.id || '');

        const matchCat = srvCurrentCategory === 'ALL' || repCat.includes(srvCurrentCategory.toLowerCase());
        const matchTxt = !searchTxt || repName.includes(searchTxt) || repCat.includes(searchTxt) || repId === searchTxt || repCode.includes(searchTxt);
        return matchCat && matchTxt;
    });

    if (filtered.length === 0) {
        container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px">Nenhum relatório localizado no catálogo.</p>';
        return;
    }

    container.innerHTML = filtered.map(rep => {
        const isAI = (rep.category || '').includes('AI');
        const badgeClass = isAI ? 'badge-warning' : 'badge-info';
        const isSelected = srvSelectedReportId === rep.id;

        return `
            <div class="srv-report-card ${isSelected ? 'selected' : ''}" onclick="selectSrvReport(${rep.id})">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <span style="font-size:0.75em;color:var(--primary);font-weight:700">#${rep.id} • ${rep.code || ''}</span>
                    <span class="badge ${badgeClass}" style="font-size:0.65em">${rep.category || 'Geral'}</span>
                </div>
                <div class="title">${rep.name || 'Sem Nome'}</div>
                <div style="font-size:0.75em;color:var(--text-muted);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${rep.description || ''}</div>
            </div>
        `;
    }).join('');
}

function filterSrvReports() {
    renderSrvReportsList();
}

function setSrvCategoryFilter(cat, element) {
    srvCurrentCategory = cat || 'ALL';
    const sel = document.getElementById('srvReportCategorySelect');
    if (sel && sel.value !== srvCurrentCategory) {
        sel.value = srvCurrentCategory;
    }
    renderSrvReportsList();
}

function selectSrvReport(id) {
    srvSelectedReportId = id;
    renderSrvReportsList();

    const rep = srvAllReports.find(r => r.id === id);
    if (!rep) return;

    document.getElementById('srvViewerTitle').innerHTML = `<i class="fas fa-file-alt" style="color:var(--primary)"></i> #${rep.id} - ${rep.name || ''}`;
    
    document.getElementById('btnSrvRunCurrent').disabled = false;
    document.getElementById('btnSrvPrint').disabled = true;
    document.getElementById('btnSrvCsv').disabled = true;
    document.getElementById('btnSrvJson').disabled = true;

    const body = document.getElementById('srvViewerBody');
    body.innerHTML = `
        <div style="background:var(--bg-input);padding:16px;border-radius:10px;border:1px solid var(--border);margin-bottom:16px">
            <div style="font-size:0.8em;color:var(--primary);font-weight:700;text-transform:uppercase">CATEGORIA: ${rep.category || 'Geral'} | FORMATO: ${rep.format || 'PDF/HTML/CSV'}</div>
            <h2 style="margin:8px 0;font-size:1.4em">${rep.name || ''}</h2>
            <p style="color:var(--text-muted);font-size:0.9em;margin-bottom:8px">${rep.description || ''}</p>
            <div style="font-size:0.8em;color:var(--text-muted)">Código de Auditoria: <code>${rep.code || 'REP-' + rep.id}</code></div>
        </div>
        <div style="text-align:center;padding:50px 20px">
            <p style="color:var(--text-muted);margin-bottom:20px;font-size:0.95em">Clique no botão abaixo para extrair as métricas em tempo real do PostgreSQL e gerar a síntese de IA.</p>
            <button class="btn btn-primary" onclick="runSrvSelectedReport()" style="padding:12px 28px;font-size:1em"><i class="fas fa-play"></i> Processar & Gerar Relatório #${rep.id}</button>
        </div>
    `;
}

async function runSrvSelectedReport() {
    if (!srvSelectedReportId) return;
    const body = document.getElementById('srvViewerBody');
    if (!body) return;
    const base = window.GBOC_API_BASE || '';
    ['btnSrvPrint', 'btnSrvCsv', 'btnSrvJson'].forEach(id => { const b = document.getElementById(id); if (b) b.disabled = false; });
    body.innerHTML = `<iframe title="Relatório" src="${base}/api/v1/reports/v2/${srvSelectedReportId}?format=embed"
        style="width:100%;height:78vh;border:1px solid var(--border);border-radius:10px;background:#fff"></iframe>`;
}

function exportSrvReport(format) {
    if (!srvSelectedReportId) return;
    const base = window.GBOC_API_BASE || '';
    const url = `${base}/api/v1/reports/export/${srvSelectedReportId}?format=${format}${format === 'html' ? '&print=1' : ''}`;
    window.open(url, '_blank');
}



document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('flagshipsGrid') || document.getElementById('srvReportsList')) loadReportsModule();
});
