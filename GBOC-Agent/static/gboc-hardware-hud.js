/**
 * GBOC System v14.0.0 Enterprise Edition
 * Widget: Hardware, CPU, Disks, Ambient Weather & S.M.A.R.T. Telemetry HUD (Agent)
 */

(function() {
    let _hudTimer = null;
    let _isHudOpen = false;

    function _getApiBase() {
        if (window.GBOC_API_BASE) return window.GBOC_API_BASE;
        return '';
    }

    function _createHudDOM() {
        if (document.getElementById('gboc-hw-hud-backdrop')) return;

        if (!document.getElementById('gboc-hw-hud-style')) {
            const link = document.createElement('link');
            link.id = 'gboc-hw-hud-style';
            link.rel = 'stylesheet';
            link.href = '/static/gboc-hardware-hud.css';
            document.head.appendChild(link);
        }

        const backdrop = document.createElement('div');
        backdrop.id = 'gboc-hw-hud-backdrop';
        backdrop.className = 'gboc-hw-hud-backdrop';
        backdrop.onclick = function(e) {
            if (e.target === backdrop) closeHardwareHUD();
        };

        backdrop.innerHTML = `
            <div class="gboc-hw-hud-card" onclick="event.stopPropagation()">
                <div class="gboc-hw-hud-header">
                    <div class="gboc-hw-hud-title">
                        <i class="fas fa-microchip"></i>
                        <span>Hardware & S.M.A.R.T. Monitor</span>
                    </div>
                    <div class="gboc-hw-hud-actions">
                        <button class="gboc-hw-btn-icon" onclick="refreshHardwareHUD()" title="Atualizar dados agora">
                            <i class="fas fa-sync-alt" id="gboc-hw-refresh-icon"></i>
                        </button>
                        <button class="gboc-hw-btn-icon" onclick="closeHardwareHUD()" title="Fechar (ESC)">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                </div>

                <div class="gboc-hw-hud-body" id="gboc-hw-hud-content">
                    <div style="text-align:center; padding:30px; color:#94a3b8;">
                        <i class="fas fa-spinner fa-spin" style="font-size:1.8rem; color:#38bdf8; margin-bottom:12px;"></i>
                        <div>Lendo sensores reais e clima do host...</div>
                    </div>
                </div>

                <div class="gboc-hw-hud-footer">
                    <span id="gboc-hw-footer-status">🟢 Telemetria 100% Real (Zero-Mock)</span>
                    <span id="gboc-hw-footer-time">--:--:--</span>
                </div>
            </div>
        `;

        document.body.appendChild(backdrop);

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && _isHudOpen) {
                closeHardwareHUD();
            }
        });
    }

    async function _fetchHardwareData() {
        const url = _getApiBase() + '/api/v2/system/hardware';
        try {
            const resp = await fetch(url);
            if (!resp.ok) {
                const resp1 = await fetch(_getApiBase() + '/api/system/hardware');
                return await resp1.json();
            }
            const payload = await resp.json();
            return payload.data || payload;
        } catch (err) {
            console.error('[Hardware HUD] Falha ao carregar dados:', err);
            return null;
        }
    }

    function _renderHardwareData(d) {
        const container = document.getElementById('gboc-hw-hud-content');
        if (!container || !d) return;

        const cpu = d.cpu || {};
        const mem = d.memory || {};
        const disks = d.disks || [];
        const partitions = d.partitions || [];
        const ambient = d.ambient || {};
        const comp = d.thermal_comparison || {};

        // CPU Temp
        let tempHtml = `<span class="gboc-hw-temp-badge" style="background:rgba(100,116,139,0.15);color:#94a3b8;border-color:rgba(100,116,139,0.3)"><i class="fas fa-thermometer-half"></i> N/A</span>`;
        if (cpu.temperature_c !== null && cpu.temperature_c !== undefined) {
            const tClass = cpu.temperature_status === 'critical' ? 'critical' : cpu.temperature_status === 'high' ? 'high' : '';
            tempHtml = `<span class="gboc-hw-temp-badge ${tClass}"><i class="fas fa-fire"></i> ${cpu.temperature_c}°C</span>`;
        }

        // CPU Load Bar
        const cpuLoad = Math.round(cpu.load_percent || 0);
        const cpuLoadClass = cpuLoad > 85 ? 'danger' : cpuLoad > 65 ? 'warning' : '';

        // Ambient Weather Display
        const ambientCity = ambient.city ? `${ambient.city}${ambient.region ? ', ' + ambient.region : ''}` : 'Local Host';
        const ambientTemp = ambient.temperature_c !== null && ambient.temperature_c !== undefined ? `${ambient.temperature_c}°C` : '--°C';
        const ambientCond = ambient.condition || 'Clima Atual';

        // Disks HTML
        let disksHtml = '';
        if (disks.length > 0) {
            disksHtml = disks.map(disk => {
                const isHealthy = (disk.smart_status || '').toUpperCase() === 'HEALTHY';
                const smartClass = isHealthy ? '' : 'warning';
                const smartIcon = isHealthy ? 'fa-check-circle' : 'fa-exclamation-triangle';
                const smartText = isHealthy ? 'S.M.A.R.T. OK' : (disk.smart_status || 'ALERTA');
                const busMedia = `${disk.media_type || 'Disk'} · ${disk.bus_type || 'SATA'} · ${disk.size_gb || 0} GB`;
                
                let diskTempBadge = '';
                if (disk.temperature_c !== null && disk.temperature_c !== undefined) {
                    const dtClass = disk.temperature_c > 55 ? 'critical' : disk.temperature_c > 45 ? 'high' : '';
                    diskTempBadge = `<span class="gboc-hw-temp-badge ${dtClass}" style="font-size:0.78rem; padding:3px 8px;"><i class="fas fa-thermometer-half"></i> ${disk.temperature_c}°C</span>`;
                }

                return `
                    <div class="gboc-hw-disk-item">
                        <div class="gboc-hw-disk-info">
                            <div class="gboc-hw-disk-name"><i class="fas fa-hdd" style="color:#38bdf8;margin-right:6px"></i>${disk.name}</div>
                            <div class="gboc-hw-disk-spec">${busMedia}</div>
                        </div>
                        <div class="gboc-hw-disk-badges">
                            ${diskTempBadge}
                            <span class="gboc-hw-smart-badge ${smartClass}">
                                <i class="fas ${smartIcon}"></i> ${smartText}
                            </span>
                        </div>
                    </div>
                `;
            }).join('');
        } else {
            disksHtml = `<div style="color:#64748b;font-size:0.85rem">Nenhum disco físico listado via WMI/OS.</div>`;
        }

        // Partitions HTML
        let partsHtml = '';
        if (partitions.length > 0) {
            partsHtml = partitions.map(p => {
                const pct = Math.round(p.percent || 0);
                const pClass = pct > 90 ? 'danger' : pct > 75 ? 'warning' : '';
                return `
                    <div class="gboc-hw-progress-wrap" style="margin-top:6px">
                        <div class="gboc-hw-progress-meta">
                            <span><strong>${p.mountpoint}</strong> (${p.fstype || 'NTFS'})</span>
                            <span>${p.used_gb} GB / ${p.total_gb} GB (${pct}%)</span>
                        </div>
                        <div class="gboc-hw-progress-track">
                            <div class="gboc-hw-progress-bar ${pClass}" style="width:${pct}%"></div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        // RAM Load
        const ramPct = Math.round(mem.percent || 0);
        const ramClass = ramPct > 90 ? 'danger' : ramPct > 75 ? 'warning' : '';

        // Thermal Comparison Values
        const avgDisksTempStr = comp.disks_avg_c !== null && comp.disks_avg_c !== undefined ? `${comp.disks_avg_c}°C` : '--';
        const deltaDiskStr = comp.delta_disk_ambient !== null && comp.delta_disk_ambient !== undefined ? `(Δ +${comp.delta_disk_ambient}°C)` : '';

        container.innerHTML = `
            <div class="gboc-hw-host-meta">
                <div>Host: <strong>${d.hostname || 'Host'}</strong></div>
                <div>SO: <strong>${d.os || 'Windows/Linux'}</strong></div>
            </div>

            <!-- Thermal Comparison Hero Box -->
            <div class="gboc-hw-thermal-hero">
                <div class="gboc-hw-thermal-hero-title">
                    <span><i class="fas fa-temperature-high" style="margin-right:6px"></i>Comparativo Térmico (Ambiente vs Hardware)</span>
                    <span style="font-size:0.75rem; color:#4ade80; font-weight:700;">${comp.status || 'NORMAL'}</span>
                </div>
                <div class="gboc-hw-thermal-grid">
                    <div class="gboc-hw-thermal-cell">
                        <div class="gboc-hw-thermal-cell-label"><i class="fas fa-cloud-sun" style="color:#38bdf8"></i> Ambiente Externo</div>
                        <div class="gboc-hw-thermal-cell-value" style="color:#38bdf8">${ambientTemp}</div>
                        <div class="gboc-hw-thermal-cell-sub" title="${ambientCity}">${ambientCity}</div>
                    </div>
                    <div class="gboc-hw-thermal-cell">
                        <div class="gboc-hw-thermal-cell-label"><i class="fas fa-microchip" style="color:#60a5fa"></i> Processador</div>
                        <div class="gboc-hw-thermal-cell-value" style="color:#60a5fa">${cpu.temperature_c ? cpu.temperature_c + '°C' : 'Normal'}</div>
                        <div class="gboc-hw-thermal-cell-sub">Carga: ${cpuLoad}%</div>
                    </div>
                    <div class="gboc-hw-thermal-cell">
                        <div class="gboc-hw-thermal-cell-label"><i class="fas fa-hdd" style="color:#4ade80"></i> Discos (S.M.A.R.T.)</div>
                        <div class="gboc-hw-thermal-cell-value" style="color:#4ade80">${avgDisksTempStr}</div>
                        <div class="gboc-hw-thermal-cell-sub">${disks.length} Unidades ${deltaDiskStr}</div>
                    </div>
                </div>
            </div>

            <!-- CPU Section -->
            <div class="gboc-hw-section">
                <div class="gboc-hw-section-title">
                    <span><i class="fas fa-microchip" style="color:#60a5fa;margin-right:6px"></i>Processador</span>
                    ${tempHtml}
                </div>
                <div class="gboc-hw-cpu-grid">
                    <div>
                        <div class="gboc-hw-cpu-name">${cpu.model}</div>
                        <div class="gboc-hw-cpu-sub">${cpu.cores_physical} Cores · ${cpu.threads_logical} Threads ${cpu.clock_mhz ? '· ' + cpu.clock_mhz + ' MHz' : ''}</div>
                    </div>
                    <div style="font-size:1.2rem;font-weight:700;color:#38bdf8">${cpuLoad}%</div>
                </div>
                <div class="gboc-hw-progress-wrap">
                    <div class="gboc-hw-progress-track">
                        <div class="gboc-hw-progress-bar ${cpuLoadClass}" style="width:${cpuLoad}%"></div>
                    </div>
                </div>
            </div>

            <!-- Disks & S.M.A.R.T. -->
            <div class="gboc-hw-section">
                <div class="gboc-hw-section-title">
                    <span><i class="fas fa-shield-alt" style="color:#4ade80;margin-right:6px"></i>Discos Físicos & S.M.A.R.T.</span>
                    <span style="font-size:0.75rem;color:#94a3b8">${disks.length} Unidades Monitoradas</span>
                </div>
                <div class="gboc-hw-disks-list">
                    ${disksHtml}
                </div>
            </div>

            <!-- Storage Volumes -->
            <div class="gboc-hw-section">
                <div class="gboc-hw-section-title">
                    <span><i class="fas fa-database" style="color:#a78bfa;margin-right:6px"></i>Partições de Armazenamento</span>
                </div>
                ${partsHtml}
            </div>

            <!-- RAM Memory -->
            <div class="gboc-hw-section">
                <div class="gboc-hw-section-title">
                    <span><i class="fas fa-memory" style="color:#f472b6;margin-right:6px"></i>Memória RAM</span>
                    <span style="font-size:0.8rem;color:#f1f5f9">${mem.used_gb || 0} GB / ${mem.total_gb || 0} GB (${ramPct}%)</span>
                </div>
                <div class="gboc-hw-progress-wrap">
                    <div class="gboc-hw-progress-track">
                        <div class="gboc-hw-progress-bar ${ramClass}" style="width:${ramPct}%"></div>
                    </div>
                </div>
            </div>
        `;

        const timeEl = document.getElementById('gboc-hw-footer-time');
        if (timeEl) {
            timeEl.textContent = 'Atualizado às ' + new Date().toLocaleTimeString();
        }
    }

    window.openHardwareHUD = async function() {
        _createHudDOM();
        const backdrop = document.getElementById('gboc-hw-hud-backdrop');
        if (backdrop) {
            backdrop.classList.add('show');
            _isHudOpen = true;
            await refreshHardwareHUD();
            
            if (_hudTimer) clearInterval(_hudTimer);
            _hudTimer = setInterval(refreshHardwareHUD, 5000);
        }
    };

    window.closeHardwareHUD = function() {
        const backdrop = document.getElementById('gboc-hw-hud-backdrop');
        if (backdrop) {
            backdrop.classList.remove('show');
            _isHudOpen = false;
            if (_hudTimer) {
                clearInterval(_hudTimer);
                _hudTimer = null;
            }
        }
    };

    window.refreshHardwareHUD = async function() {
        const icon = document.getElementById('gboc-hw-refresh-icon');
        if (icon) icon.classList.add('fa-spin');

        try {
            const data = await _fetchHardwareData();
            if (data) {
                _renderHardwareData(data);
            }
        } finally {
            if (icon) icon.classList.remove('fa-spin');
        }
    };
})();
