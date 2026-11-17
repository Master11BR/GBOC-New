// GBOC System v15.0.0 Enterprise Edition
// Module: Backups JavaScript Module

async function loadBackupsTab() {
    const tbody = document.getElementById('table-backups');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center"><i class="fas fa-spinner fa-spin"></i> Carregando backups...</td></tr>';
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/backups/recent');
        const d = await r.json();
        const reports = d.reports || [];
        const liveBox = document.getElementById('server-live-backups');
        const runningList = reports.filter(b => ['running', 'preparing'].includes(String(b.status || '').toLowerCase()));
        if (liveBox) {
            if (runningList.length > 0) {
                const fmtB = v => { v = Number(v) || 0; if (v < 1024) return v + ' B'; const u = ['KB','MB','GB','TB']; let i = -1; do { v /= 1024; i++; } while (v >= 1024 && i < u.length - 1); return v.toFixed(1) + ' ' + u[i]; };
                liveBox.hidden = false;
                liveBox.innerHTML = `<div class="gl-title-row"><span class="gl-dot"></span>Em execução nos agentes (${runningList.length})</div>` + runningList.map(b => {
                    const pct = Math.min(100, Math.max(0, Number(b.progress) || 0));
                    return `<div class="gl-card">
                        <div class="gl-icon"><i class="fas fa-wave-square"></i></div>
                        <div style="min-width:0">
                            <div class="gl-name">${b.job_name || 'Backup'} <span class="gl-badge">COPY</span></div>
                            <div class="gl-route">${b.agent_id || 'Agente'} → ${b.repository_name || 'Repositório'}</div>
                            <div class="gl-meta"><span><i class="fas fa-gear"></i> 32 threads</span><span>•</span><span><i class="far fa-clock"></i> ${b.duration_seconds || 0}s</span></div>
                        </div>
                        <div class="gl-prog">
                            <div class="gl-top"><span>Varrendo o disco e enviando...</span><span class="gl-pct">${pct}%</span></div>
                            <div class="gl-bar"><div class="gl-fill" style="width:${pct}%"></div></div>
                            <div class="gl-kpi-grid">
                                <div class="gl-kpi-box"><div class="gl-kpi-lbl">LIDOS NO DISCO</div><div class="gl-kpi-val">${Number(b.files_processed || 0).toLocaleString('pt-BR')}</div></div>
                                <div class="gl-kpi-box"><div class="gl-kpi-lbl">NO FILTRO</div><div class="gl-kpi-val">${Number(b.files_processed || 0).toLocaleString('pt-BR')}</div></div>
                                <div class="gl-kpi-box"><div class="gl-kpi-lbl">COPIADOS</div><div class="gl-kpi-val gl-val-green">${Number(b.files_new || 0).toLocaleString('pt-BR')}</div></div>
                                <div class="gl-kpi-box"><div class="gl-kpi-lbl">ATUALIZADOS</div><div class="gl-kpi-val gl-val-cyan">${Number(b.files_changed || 0).toLocaleString('pt-BR')}</div></div>
                                <div class="gl-kpi-box"><div class="gl-kpi-lbl">JÁ NA NUVEM</div><div class="gl-kpi-val">${Number(b.files_unmodified || 0).toLocaleString('pt-BR')}</div></div>
                                <div class="gl-kpi-box"><div class="gl-kpi-lbl">NÃO ENCONTRADOS</div><div class="gl-kpi-val">0</div></div>
                                <div class="gl-kpi-box"><div class="gl-kpi-lbl">FALHAS</div><div class="gl-kpi-val">0</div></div>
                            </div>
                            <div class="gl-timing-row">
                                <span>Decorrido <strong>${b.duration_seconds || 0}s</strong></span>
                                <span>Em pausa <strong>0s</strong></span>
                                <span>Trabalhando <strong>${b.duration_seconds || 0}s</strong></span>
                                <span>Volume <strong>${fmtB(b.size_bytes)}</strong></span>
                            </div>
                        </div>
                    </div>`;
                }).join('');
            } else {
                liveBox.hidden = true;
                liveBox.innerHTML = '';
            }
        }
        if (reports.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Nenhum backup registrado.</td></tr>';
            return;
        }
        tbody.innerHTML = reports.map(b => `
            <tr>
                <td><span class="badge badge-${b.status === 'success' ? 'success' : 'danger'}">${b.status.toUpperCase()}</span></td>
                <td><strong>${b.agent_id}</strong></td>
                <td>${b.job_name}</td>
                <td>${b.duration_seconds}s</td>
                <td>${(b.size_bytes / (1024*1024*1024)).toFixed(2)} GB</td>
                <td>${b.timestamp}</td>
            </tr>
        `).join('');
    } catch(e) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger)">Erro: ${e.message}</td></tr>`;
    }
}
