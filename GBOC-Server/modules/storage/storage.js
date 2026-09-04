/**
 * GBOC Server v14.0.0 — Storage Module UI Script
 */

let serverStorageChartInstance = null;

async function loadServerStorageData() {
    try {
        const res = await fetch(window.GBOC_API_BASE + '/api/v1/server/storage/overview');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        if (data.status === 'success') {
            const summary = data.summary || {};
            document.getElementById('srv-storage-total').textContent = (summary.total_capacity_gb || 0) + ' GB';
            document.getElementById('srv-storage-used').textContent = (summary.total_used_gb || 0) + ' GB';
            document.getElementById('srv-storage-free').textContent = (summary.total_free_gb || 0) + ' GB';
            document.getElementById('srv-storage-percent').textContent = (summary.used_percent || 0) + '% utilizado';

            // Renderizar consumo por motor
            const engineGrid = document.getElementById('srv-engine-storage-grid');
            if (engineGrid && data.by_engine) {
                if (data.by_engine.length === 0) {
                    engineGrid.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);grid-column:1/-1">Nenhum motor registrado.</div>';
                } else {
                    engineGrid.innerHTML = data.by_engine.map(eng => `
                        <div style="background:var(--bg-input);border:1px solid var(--border);border-radius:10px;padding:14px">
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                                <strong style="font-size:0.95em"><i class="fas fa-microchip" style="color:var(--primary)"></i> ${eng.display_name}</strong>
                                <span class="badge badge-info">${eng.repo_count} Repo(s)</span>
                            </div>
                            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:0.85em;background:var(--bg-card);padding:10px;border-radius:6px;border:1px solid var(--border)">
                                <div>
                                    <div style="color:var(--text-muted);font-size:0.75em"><i class="fas fa-folder"></i> Disco Local</div>
                                    <div style="font-weight:700;color:var(--text);font-size:1.1em">${(eng.local_gb || 0).toFixed(2)} GB</div>
                                </div>
                                <div>
                                    <div style="color:var(--text-muted);font-size:0.75em"><i class="fas fa-cloud" style="color:var(--accent)"></i> Gasto Nuvem</div>
                                    <div style="font-weight:700;color:var(--accent);font-size:1.1em">${(eng.cloud_gb || 0).toFixed(2)} GB</div>
                                </div>
                                <div style="grid-column:1/-1;border-top:1px solid var(--border);padding-top:4px;display:flex;justify-content:space-between">
                                    <span style="font-size:0.75em;color:var(--text-muted)">Repo Local: ${(eng.local_repo_gb || 0).toFixed(2)} GB</span>
                                    <span style="font-size:0.75em;color:var(--primary);font-weight:600">Total: ${(eng.destination_gb || 0).toFixed(2)} GB</span>
                                </div>
                            </div>
                        </div>
                    `).join('');
                }
            }

            const tbody = document.getElementById('table-server-storage');
            if (tbody) {
                if (!data.repositories || data.repositories.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">Nenhum repositório de armazenamento encontrado.</td></tr>';
                } else {
                    tbody.innerHTML = data.repositories.map(r => `
                        <tr>
                            <td><strong>${r.name}</strong></td>
                            <td><code>${r.path}</code></td>
                            <td>${r.total_gb} GB</td>
                            <td>${r.used_gb} GB</td>
                            <td>${r.free_gb} GB</td>
                            <td>
                                <div style="display:flex;align-items:center;gap:8px">
                                    <div style="flex:1;background:var(--bg-input);height:8px;border-radius:4px;overflow:hidden">
                                        <div style="width:${r.used_percent}%;background:${r.used_percent > 85 ? 'var(--danger)' : 'var(--primary)'};height:100%"></div>
                                    </div>
                                    <span>${r.used_percent}%</span>
                                </div>
                            </td>
                            <td><span class="badge ${r.status === 'healthy' ? 'badge-success' : 'badge-warning'}">${r.status.toUpperCase()}</span></td>
                        </tr>
                    `).join('');
                }
            }
        }

        loadServerStorageHistory();
    } catch (e) {
        console.error('Erro ao carregar dados de armazenamento do servidor:', e);
    }
}

async function loadServerStorageHistory() {
    try {
        const res = await fetch(window.GBOC_API_BASE + '/api/v1/server/storage/history?days=30');
        if (!res.ok) return;
        const data = await res.json();
        if (data.status === 'success' && data.history) {
            renderServerStorageChart(data.history);
        }
    } catch (e) {
        console.error('Erro ao carregar histórico de armazenamento:', e);
    }
}

function renderServerStorageChart(history) {
    const ctx = document.getElementById('server-storage-chart');
    if (!ctx) return;

    const labels = history.map(h => h.timestamp);
    const dataset = history.map(h => h.used_gb);

    if (serverStorageChartInstance) {
        serverStorageChartInstance.destroy();
    }

    serverStorageChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Uso de Armazenamento (GB)',
                data: dataset,
                borderColor: '#4fa3e8',
                backgroundColor: 'rgba(79, 163, 232, 0.15)',
                fill: true,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: false, grid: { color: 'rgba(255,255,255,0.05)' } },
                x: { grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });
}

async function rescanServerStorage() {
    try {
        const res = await fetch(window.GBOC_API_BASE + '/api/v1/server/storage/scan', { method: 'POST' });
        if (res.ok) {
            await loadServerStorageData();
        }
    } catch (e) {
        console.error('Erro ao executar scan de armazenamento:', e);
    }
}

window.loadServerStorageData = loadServerStorageData;
window.rescanServerStorage = rescanServerStorage;
