/* GBOC System v14.0.0 Enterprise Edition */
/* Module: Reports JavaScript Controller (Server) */

let srvAllReports = [];
let srvSelectedReportId = null;
let srvCurrentCategory = 'ALL';

async function loadReportsTab() {
    console.log('[ReportsModule] Carregando módulo de relatórios...');
    const container = document.getElementById('srvReportsList');
    if (!container) return;

    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/reports/catalog');
        const d = await r.json();
        srvAllReports = d.reports || [];
        renderSrvReportsList();
    } catch (e) {
        console.error('[ReportsModule] Erro ao carregar catálogo:', e);
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
    srvCurrentCategory = cat;
    document.querySelectorAll('.srv-cat-chip').forEach(el => el.classList.remove('active'));
    if (element) element.classList.add('active');
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
    body.innerHTML = `
        <div style="text-align:center;padding:60px 20px">
            <i class="fas fa-spinner fa-spin fa-3x" style="color:var(--primary)"></i>
            <p style="margin-top:16px;color:var(--text);font-weight:600">Consultando PostgreSQL & IA GBOC System...</p>
            <p style="font-size:0.85em;color:var(--text-muted)">Extraindo métricas reais de agentes, backups, logs e resiliência.</p>
        </div>
    `;

    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/reports/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ report_id: srvSelectedReportId })
        });
        const data = await r.json();

        // Habilitar botões de exportação
        document.getElementById('btnSrvPrint').disabled = false;
        document.getElementById('btnSrvCsv').disabled = false;
        document.getElementById('btnSrvJson').disabled = false;

        // Renderizar Métricas Principais
        const metricsHtml = (data.metrics || []).map(m => `
            <div class="srv-metric-card">
                <div class="lbl">${m.label}</div>
                <div class="val">${m.value}</div>
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
                <h4 style="margin:24px 0 12px;font-size:1em;color:var(--text)"><i class="fas fa-table" style="color:var(--primary)"></i> Detalhamento dos Dados Auditados:</h4>
                <div style="overflow-x:auto">
                    <table class="data-table">
                        <thead><tr>${headers}</tr></thead>
                        <tbody>${rows || '<tr><td colspan="100%" style="text-align:center">Nenhum registro retornado.</td></tr>'}</tbody>
                    </table>
                </div>
            `;
        }

        body.innerHTML = `
            <div style="border-bottom:1px solid var(--border);padding-bottom:12px;margin-bottom:20px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
                <div>
                    <h2 style="color:var(--primary);margin:0 0 4px;font-size:1.4em">${data.title}</h2>
                    <div style="font-size:0.8em;color:var(--text-muted)">Código: <code>${data.code}</code> | Categoria: <strong>${data.category}</strong></div>
                </div>
                <div style="font-size:0.8em;color:var(--text-muted);text-align:right">
                    Gerado em: <strong>${new Date(data.generated_at).toLocaleString()}</strong><br>
                    Engine: <span>GBOC Server 14.0.0</span>
                </div>
            </div>

            <h4 style="margin-bottom:12px;font-size:1em;color:var(--text)"><i class="fas fa-chart-bar" style="color:var(--primary)"></i> Métricas do Diagnóstico:</h4>
            <div class="srv-metric-grid">${metricsHtml}</div>

            <h4 style="margin:20px 0 12px;font-size:1em;color:var(--text)"><i class="fas fa-robot" style="color:var(--warning)"></i> Parecer Executivo & Recomendação IA:</h4>
            <div style="background:var(--bg-input);padding:16px;border-radius:10px;border-left:4px solid var(--warning);font-size:0.92em;line-height:1.6;color:var(--text)">
                ${data.ai_executive_recommendation || 'Diagnóstico operacional concluído com sucesso sem divergências de integridade.'}
            </div>

            ${tableHtml}
        `;
    } catch (e) {
        console.error('[ReportsModule] Erro ao gerar relatório:', e);
        body.innerHTML = `<div style="padding:20px;color:var(--danger)">Erro ao gerar relatório: ${e.message}</div>`;
    }
}

function exportSrvReport(format) {
    if (!srvSelectedReportId) return;
    const url = `/api/v1/reports/export/${srvSelectedReportId}?format=${format}${format === 'html' ? '&print=1' : ''}`;
    window.open(url, '_blank');
}
