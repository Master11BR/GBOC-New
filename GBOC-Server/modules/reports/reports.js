/* GBOC System v14.6.0 Enterprise Edition */
/* Module: Reports JavaScript Controller (Server) */

let srvFlagships = [];
let srvAllReports = [];
let srvSelectedReportId = null;
let srvCurrentCategory = 'ALL';
let srvCurrentMode = 'flagships';

async function loadReportsTab() {
    console.log('[ReportsModule] Carregando módulo de relatórios v2.0...');
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
    const btnRun = document.getElementById('btnSrvRunCurrent');
    if (!body) return;

    if (btnRun) {
        btnRun.disabled = true;
        btnRun.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Gerando...';
    }

    body.innerHTML = `
        <div style="text-align:center;padding:60px 20px">
            <i class="fas fa-spinner fa-spin fa-3x" style="color:var(--primary)"></i>
            <p style="margin-top:16px;color:var(--text);font-weight:600">Consultando PostgreSQL & IA GBOC System...</p>
            <p style="font-size:0.85em;color:var(--text-muted)">Extraindo métricas reais de agentes, backups, logs e resiliência.</p>
        </div>
    `;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
        const base = window.GBOC_API_BASE || '';
        const r = await fetch(base + '/api/v1/reports/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ report_id: srvSelectedReportId }),
            signal: controller.signal
        });
        clearTimeout(timeoutId);
        const data = await r.json();

        // Habilitar botões de exportação
        const btnPrint = document.getElementById('btnSrvPrint');
        const btnCsv = document.getElementById('btnSrvCsv');
        const btnJson = document.getElementById('btnSrvJson');
        if (btnPrint) btnPrint.disabled = false;
        if (btnCsv) btnCsv.disabled = false;
        if (btnJson) btnJson.disabled = false;

        // Renderizar Score se disponível
        let scoreHtml = '';
        if (data.score) {
            const sc = data.score;
            const scColor = sc.status === 'OK' ? '#10b981' : (sc.status === 'AT_RISK' ? '#f59e0b' : '#ef4444');
            scoreHtml = `
                <div style="background:var(--bg-input);border:1.5px solid var(--border);border-left:5px solid ${scColor};border-radius:8px;padding:12px 18px;margin-bottom:16px;">
                    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
                        <div style="display:flex;align-items:center;gap:16px;">
                            <div style="font-size:2em;font-weight:800;color:${scColor};">${sc.value}<span style="font-size:0.5em;color:var(--text-muted)">/100</span></div>
                            <div>
                                <div style="font-weight:700;font-size:0.95em;color:var(--text);">Protection & Operations Score</div>
                                <div style="font-size:0.78em;color:var(--text-muted);">Tendência: <strong>${sc.trend || '0'}pp</strong> vs período anterior • Status: <span class="badge" style="background:${scColor};color:#fff;font-size:0.8em;padding:2px 6px;border-radius:4px;">${sc.status}</span></div>
                            </div>
                        </div>
                        <div style="font-size:0.75em;color:var(--text-muted);text-align:right;">
                            <div>GBOC Server Enterprise</div>
                            <code>${data.schema_version || '4.0.0'}</code>
                        </div>
                    </div>
                </div>
            `;
        }

        // Renderizar Delta se disponível
        let deltaHtml = '';
        if (data.delta && data.delta.length > 0) {
            const bullets = data.delta.map(d => {
                const ic = d.icon === 'up' ? '<i class="fas fa-arrow-up" style="color:#10b981"></i>' : (d.icon === 'down' ? '<i class="fas fa-arrow-down" style="color:#ef4444"></i>' : '<i class="fas fa-minus" style="color:#0284c7"></i>');
                return `<li style="display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:0.85em;color:var(--text);">${ic} <span>${d.text}</span></li>`;
            }).join('');
            deltaHtml = `
                <div style="background:var(--bg-input);border:1px solid var(--border);border-radius:8px;padding:10px 14px;margin-bottom:18px;">
                    <div style="font-size:0.75em;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.04em;margin-bottom:6px;"><i class="fas fa-chart-line"></i> O que mudou vs período anterior:</div>
                    <ul style="list-style:none;margin:0;padding:0;">${bullets}</ul>
                </div>
            `;
        }

        // Renderizar Métricas Principais
        const kpiColors = ["#0284c7", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4"];
        const metricsHtml = (data.metrics || []).map((m, idx) => `
            <div class="srv-metric-card" style="border-left: 4px solid ${kpiColors[idx % kpiColors.length]}; text-align: left;">
                <div class="lbl" style="font-size:0.72em;">${m.label}</div>
                <div class="val" style="font-size:1.5em; text-align: left; margin-top:2px;">${m.value}</div>
                ${m.target ? `<div style="font-size:0.68em;color:var(--text-muted);margin-top:2px">Meta: ${m.target}</div>` : ''}
            </div>
        `).join('');

        // Renderizar Tabela se houver
        let tableHtml = '';
        if (data.table_headers && data.table_headers.length > 0) {
            const headers = data.table_headers.map(h => `<th>${h}</th>`).join('');
            const rows = (data.table_rows || []).map(row => 
                `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`
            ).join('');

            tableHtml = `
                <h4 style="margin:24px 0 12px;font-size:1em;color:var(--text)"><i class="fas fa-table-list" style="color:var(--primary)"></i> Detalhamento dos Dados Auditados:</h4>
                <div style="overflow-x:auto; border: 1px solid var(--border); border-radius: 8px;">
                    <table class="data-table" style="width:100%; border-collapse:collapse;">
                        <thead><tr>${headers}</tr></thead>
                        <tbody>${rows || '<tr><td colspan="100%" style="text-align:center">Nenhum registro retornado.</td></tr>'}</tbody>
                    </table>
                </div>
            `;
        }

        // Renderizar Ações Recomendadas
        let actionsHtml = '';
        if (data.recommended_actions && data.recommended_actions.length > 0) {
            const acts = data.recommended_actions.map(act => {
                const p = String(act.priority || 'MEDIUM').toUpperCase();
                return `
                    <div style="margin-bottom:8px;padding:8px 12px;border-radius:6px;border-left:3px solid ${p === 'HIGH' ? 'var(--danger)' : (p === 'MEDIUM' ? 'var(--warning)' : 'var(--success)')};background:var(--bg-input)">
                        <div style="display:flex;align-items:center;gap:8px">
                            <span class="action-badge" style="font-size:0.7em;padding:2px 6px;border-radius:4px;font-weight:700;background:${p === 'HIGH' ? 'var(--danger)' : (p === 'MEDIUM' ? 'var(--warning)' : 'var(--success)')};color:#fff">${p}</span>
                            <strong style="font-size:0.88em">${act.action}</strong>
                        </div>
                        ${act.detail ? `<div style="font-size:0.8em;color:var(--text-muted);margin-top:4px">${act.detail}</div>` : ''}
                    </div>
                `;
            }).join('');
            actionsHtml = `
                <h4 style="margin:20px 0 12px;font-size:1em;color:var(--text)"><i class="fas fa-bolt" style="color:var(--warning)"></i> Ações Recomendadas:</h4>
                <div class="actions-list">${acts}</div>
            `;
        }

        body.innerHTML = `
            <div style="border-bottom:1.5px solid var(--border);padding-bottom:14px;margin-bottom:20px;display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">
                <div>
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                        <span class="badge badge-success" style="font-size:0.7em"><i class="fas fa-shield-halved"></i> Relatório Oficial Auditável</span>
                        <span class="badge badge-info" style="font-size:0.7em">${data.category}</span>
                    </div>
                    <h2 style="color:var(--primary);margin:0 0 4px;font-size:1.4em">${data.title}</h2>
                    <div style="font-size:0.82em;color:var(--text-muted)">Código Único: <code>${data.code}</code> | Plataforma: <strong>GBOC Server Enterprise</strong></div>
                </div>
                <div style="font-size:0.8em;color:var(--text-muted);text-align:right">
                    <div>Emissão: <strong>${new Date(data.generated_at).toLocaleString()}</strong></div>
                    <div style="margin-top:4px"><span style="color:var(--success);font-weight:600"><i class="fas fa-check-circle"></i> 100% Dados Reais</span></div>
                    ${data.integrity_hash ? `<div>Hash: <code style="font-size:0.85em">${data.integrity_hash.slice(0, 19)}...</code></div>` : ''}
                </div>
            </div>

            ${scoreHtml}
            ${deltaHtml}

            <h4 style="margin-bottom:12px;font-size:1em;color:var(--text)"><i class="fas fa-chart-bar" style="color:var(--primary)"></i> Métricas do Diagnóstico:</h4>
            <div class="srv-metric-grid">${metricsHtml}</div>

            <h4 style="margin:20px 0 12px;font-size:1em;color:var(--text)"><i class="fas fa-robot" style="color:var(--warning)"></i> Parecer Executivo & Recomendação IA:</h4>
            <div style="background:var(--bg-input);padding:16px;border-radius:10px;border-left:4px solid var(--warning);font-size:0.92em;line-height:1.6;color:var(--text)">
                ${data.ai_executive_recommendation || 'Diagnóstico operacional concluído com sucesso sem divergências de integridade.'}
            </div>

            ${tableHtml}
            ${actionsHtml}
        `;
    } catch (e) {
        console.error('[ReportsModule] Erro ao gerar relatório:', e);
        clearTimeout(timeoutId);
        if (body) {
            const isAbort = e.name === 'AbortError';
            const msg = isAbort 
                ? 'Tempo limite de consulta excedido (30s). O PostgreSQL ou serviço remoto pode estar processando alto volume.'
                : `Erro ao gerar relatório: ${e.message}`;
            body.innerHTML = `
                <div style="background:rgba(239,68,68,0.08);border:1.5px solid rgba(239,68,68,0.25);border-radius:8px;padding:24px;text-align:center;margin:20px">
                    <h4 style="color:var(--danger);margin:0 0 8px;font-size:1.1em"><i class="fas fa-circle-exclamation"></i> Falha na Extração dos Dados</h4>
                    <p style="color:var(--text);font-size:0.92em;margin:0 0 16px;max-width:550px;margin-left:auto;margin-right:auto">${msg}</p>
                    <button class="btn btn-primary" onclick="runSrvSelectedReport()" style="padding:8px 20px;font-size:0.9em"><i class="fas fa-rotate"></i> Tentar Novamente</button>
                </div>
            `;
        }
    } finally {
        clearTimeout(timeoutId);
        if (btnRun) {
            btnRun.disabled = false;
            btnRun.innerHTML = '<i class="fas fa-play"></i> Gerar Agora';
        }
    }
}

function exportSrvReport(format) {
    if (!srvSelectedReportId) return;
    const base = window.GBOC_API_BASE || '';
    const url = `${base}/api/v1/reports/export/${srvSelectedReportId}?format=${format}${format === 'html' ? '&print=1' : ''}`;
    window.open(url, '_blank');
}


