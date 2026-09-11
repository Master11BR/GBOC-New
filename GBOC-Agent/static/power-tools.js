/**
 * GBOC System v14.1.0 Enterprise Edition
 * Module: Freemium & Open-Source Power Tools Controller
 * Copyright (c) 2026 Master11BR - Todos os direitos reservados.
 * Zero-Mock: 100% de integração com APIs reais e dados do sistema host.
 */

document.addEventListener('DOMContentLoaded', () => {
    if (typeof UnifiedSidebar === 'function') {
        new UnifiedSidebar().initialize();
    }
    loadVfsDrives();
    loadLinuxSnapshots();
    loadUsbDrives();
});

function switchPowerTab(tabId) {
    document.querySelectorAll('.pow-tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.pow-tab-content').forEach(content => content.classList.remove('active'));

    const activeBtn = document.getElementById(`tab-btn-${tabId}`);
    const activeContent = document.getElementById(`tab-content-${tabId}`);
    if (activeBtn) activeBtn.classList.add('active');
    if (activeContent) activeContent.classList.add('active');
}

// ── 1. Visual Diff & RealTimeSync ───────────────────────────────────────────
async function runVisualDiffComparison() {
    const left = document.getElementById('diff-left-path')?.value?.trim();
    const right = document.getElementById('diff-right-path')?.value?.trim();
    const tbody = document.getElementById('visual-diff-table-body');
    const sumEl = document.getElementById('diff-summary-badges');

    if (!left) {
        alert('Por favor, informe a Pasta de Origem (Left) para realizar a comparação.');
        return;
    }

    if (tbody) tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:16px;">Comparando pastas no disco e gerando árvore de diferenças...</td></tr>';

    try {
        const res = await fetch('/api/v1/power-tools/visual-diff/compare', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ left_path: left, right_path: right || '' })
        });
        const data = await res.json();
        const tree = data.data?.diff_tree || [];
        const sum = data.data?.summary || {};
        const errorMsg = data.data?.error;

        if (sumEl) {
            sumEl.innerHTML = `
                <span class="badge badge-primary">${sum.total_files || tree.length} Itens</span>
                <span class="badge badge-success">${sum.left_only || 0} Novos (Origem)</span>
                <span class="badge badge-warning">${sum.different || 0} Modificados</span>
                <span class="badge badge-info">${sum.identical || 0} Idênticos</span>
            `;
        }

        if (tbody) {
            if (errorMsg) {
                tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:16px; color:#e53e3e;">⚠️ ${errorMsg}</td></tr>`;
                return;
            }

            if (tree.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:16px; color:var(--text-muted);">Nenhum arquivo encontrado nas pastas especificadas.</td></tr>';
                return;
            }

            tbody.innerHTML = tree.map(item => `
                <tr>
                    <td><strong>${item.relative_path}</strong></td>
                    <td>${item.left_size} <span style="font-size:0.75em; color:var(--text-muted);">(${item.left_date})</span></td>
                    <td style="text-align:center; color:var(--primary); font-weight:700;">
                        ${item.action === 'COPY_TO_RIGHT' ? '➔' : (item.action === 'UPDATE_RIGHT' ? '➔ (Modificado)' : (item.action === 'EQUAL' ? '=' : '⤶'))}
                    </td>
                    <td>${item.right_size} <span style="font-size:0.75em; color:var(--text-muted);">(${item.right_date})</span></td>
                    <td><span class="badge badge-${item.status.includes('LEFT') ? 'success' : (item.status.includes('MODIFIED') ? 'warning' : (item.status === 'IDENTICAL' ? 'info' : 'danger'))}">${item.status}</span></td>
                </tr>
            `).join('');
        }
    } catch (e) {
        console.error('Erro no visual diff:', e);
        if (tbody) tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:16px; color:#e53e3e;">Erro de comunicação: ${e.message}</td></tr>`;
    }
}

async function executeSyncAction() {
    const left = document.getElementById('diff-left-path')?.value?.trim();
    const right = document.getElementById('diff-right-path')?.value?.trim();

    if (!left || !right) {
        alert('Informe as pastas de Origem e Destino para executar a sincronização espelho.');
        return;
    }

    if (!confirm(`Confirmar sincronização espelho de:\n${left}\npara:\n${right}\n\nArquivos modificados ou ausentes serão copiados.`)) {
        return;
    }

    try {
        const res = await fetch('/api/v1/power-tools/visual-diff/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ left_path: left, right_path: right, sync_mode: 'MIRROR' })
        });
        const data = await res.json();
        if (data.success) {
            alert(`🎉 Sincronização concluída com sucesso!\n${data.items_copied} arquivos copiados (${data.bytes_transferred_mb} MB transferidos).`);
            runVisualDiffComparison();
        } else {
            alert(`❌ Falha na sincronização: ${data.error || 'Erro desconhecido'}`);
        }
    } catch (e) {
        alert('Erro ao sincronizar: ' + e.message);
    }
}

// ── 2. Bitrot & Reed-Solomon Scrub ──────────────────────────────────────────
async function runBitrotScrubAction() {
    const targetPath = document.getElementById('bitrot-path-input')?.value?.trim();
    if (!targetPath) {
        alert('Informe o caminho da pasta ou repositório a ser verificado.');
        return;
    }

    const consoleEl = document.getElementById('bitrot-console');
    if (consoleEl) consoleEl.textContent = `Iniciando varredura física de integridade de blocos em: ${targetPath}...`;

    try {
        const res = await fetch('/api/v1/power-tools/bitrot/scrub', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_path: targetPath })
        });
        const data = await res.json();
        if (consoleEl && Array.isArray(data.logs)) {
            consoleEl.textContent = data.logs.join('\n');
        } else if (consoleEl) {
            consoleEl.textContent = data.error || 'Operação concluída.';
        }
    } catch (e) {
        if (consoleEl) consoleEl.textContent = 'Erro na varredura bitrot: ' + e.message;
    }
}

// ── 3. Virtual Cloud Drive Mount (Z:\) ──────────────────────────────────────
async function loadVfsDrives() {
    try {
        const res = await fetch('/api/v1/power-tools/vfs/drives');
        if (!res.ok) return;
        const data = await res.json();
        const drives = data.drives || [];
        const box = document.getElementById('vfs-drives-box');

        if (box) {
            if (!drives.length) {
                box.innerHTML = '<div style="color:var(--text-muted); font-size:0.85em;">Nenhum drive virtual montado no momento.</div>';
            } else {
                box.innerHTML = drives.map(d => `
                    <div style="background:var(--bg-input); padding:12px; border-radius:8px; border:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                        <div>
                            <strong style="color:var(--text);"><i class="fas fa-hdd" style="color:var(--primary); margin-right:6px;"></i> Drive ${d.drive_letter}</strong>
                            <div style="font-size:0.78em; color:var(--text-muted);">Repositório: ${d.repository_url} (Processo PID: ${d.pid || 'Ativo'})</div>
                        </div>
                        <button class="btn btn-sm btn-danger" onclick="unmountVfsAction('${d.drive_letter}')"><i class="fas fa-eject"></i> Desmontar</button>
                    </div>
                `).join('');
            }
        }
    } catch (e) {
        console.error('Erro nos drives VFS:', e);
    }
}

async function mountVfsAction() {
    const url = document.getElementById('vfs-repo-url')?.value?.trim();
    const letter = document.getElementById('vfs-drive-letter')?.value || 'Z:';

    if (!url) {
        alert('Informe a URL do repositório (ex: s3://meu-bucket/backups).');
        return;
    }

    try {
        const res = await fetch('/api/v1/power-tools/vfs/mount', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repository_url: url, drive_letter: letter })
        });
        const data = await res.json();
        if (data.success) {
            alert(`🎉 Drive Virtual '${letter}' montado com sucesso!`);
            loadVfsDrives();
        } else {
            alert(`❌ Não foi possível montar o drive virtual:\n${data.error}`);
        }
    } catch (e) {
        alert('Erro ao montar drive virtual: ' + e.message);
    }
}

async function unmountVfsAction(letter) {
    try {
        await fetch(`/api/v1/power-tools/vfs/unmount?drive_letter=${letter}`, { method: 'POST' });
        loadVfsDrives();
    } catch (e) {
        alert('Erro ao desmontar: ' + e.message);
    }
}

// ── 4. Rapid Delta Restore (RDR) ────────────────────────────────────────────
async function runRapidDeltaAction() {
    const imgPath = document.getElementById('rapid-delta-image-path')?.value?.trim();
    const diskNum = parseInt(document.getElementById('rapid-delta-disk-number')?.value || '0', 10);
    const consoleEl = document.getElementById('rapid-delta-console');

    if (!imgPath) {
        alert('Informe o caminho do arquivo de imagem VHDX.');
        return;
    }

    if (consoleEl) consoleEl.textContent = `Validando imagem ${imgPath} e Disco #${diskNum}...`;

    try {
        const res = await fetch('/api/v1/power-tools/rapid-delta/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_image: imgPath, target_disk: diskNum })
        });
        const data = await res.json();
        if (consoleEl && Array.isArray(data.logs)) {
            consoleEl.textContent = data.logs.join('\n');
        } else if (consoleEl) {
            consoleEl.textContent = data.error || 'Operação concluída.';
        }
    } catch (e) {
        if (consoleEl) consoleEl.textContent = 'Erro no Rapid Delta Restore: ' + e.message;
    }
}

// ── 5. Linux BTRFS & ZFS Snapshots ──────────────────────────────────────────
async function loadLinuxSnapshots() {
    try {
        const res = await fetch('/api/v1/power-tools/linux-snapshots/list');
        if (!res.ok) return;
        const data = await res.json();
        const payload = data.data || {};
        const snaps = payload.snapshots || [];
        const tbody = document.getElementById('linux-snapshots-tbody');

        if (tbody) {
            if (!payload.supported) {
                tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:16px; color:var(--text-muted);"><i class="fab fa-windows" style="margin-right:6px;"></i> ${payload.message}</td></tr>`;
                return;
            }

            if (snaps.length === 0) {
                tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:16px; color:var(--text-muted);">${payload.message || 'Nenhum snapshot de subvolume ZFS/BTRFS encontrado.'}</td></tr>`;
                return;
            }

            tbody.innerHTML = snaps.map(s => `
                <tr>
                    <td><strong>${s.id}</strong></td>
                    <td style="font-family:monospace; font-size:0.85em;">${s.dataset}</td>
                    <td>${s.created_at}</td>
                    <td><span class="badge badge-info">${s.size}</span></td>
                </tr>
            `).join('');
        }
    } catch (e) {
        console.error('Erro nos snapshots Linux:', e);
    }
}

async function createLinuxSnapshotAction() {
    const dataset = prompt('Informe o nome do dataset/subvolume ZFS ou BTRFS (ex: tank/dados):');
    if (!dataset) return;

    try {
        const res = await fetch('/api/v1/power-tools/linux-snapshots/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dataset_name: dataset })
        });
        const data = await res.json();
        if (data.success) {
            alert(`✅ Snapshot criado com sucesso!`);
            loadLinuxSnapshots();
        } else {
            alert(`❌ Falha: ${data.error}`);
        }
    } catch (e) {
        alert('Erro ao criar snapshot: ' + e.message);
    }
}

// ── 6. USB Rescue Media Creator ─────────────────────────────────────────────
async function loadUsbDrives() {
    try {
        const res = await fetch('/api/v1/power-tools/usb-rescue/drives');
        if (!res.ok) return;
        const data = await res.json();
        const drives = data.drives || [];
        const select = document.getElementById('usb-drives-select');

        if (select) {
            if (drives.length === 0) {
                select.innerHTML = '<option value="" disabled selected>Nenhum pendrive USB detectado no sistema</option>';
            } else {
                select.innerHTML = drives.map(d => `
                    <option value="${d.drive_letter}">${d.drive_letter} [${d.label}] - ${d.model} (${d.size_gb} GB)</option>
                `).join('');
            }
        }
    } catch (e) {
        console.error('Erro nos pendrives USB:', e);
    }
}

async function createUsbRescueAction() {
    const letter = document.getElementById('usb-drives-select')?.value;
    if (!letter) {
        alert('Selecione uma unidade USB válida conectada ao computador.');
        return;
    }

    if (!confirm(`AVISO CRÍTICO DE FORMATAÇÃO:\n\nA unidade ${letter} será utilizada para criar o GBOC WinPE Offline Recovery Environment.\n\nDeseja continuar?`)) return;

    const consoleEl = document.getElementById('usb-creator-console');
    if (consoleEl) consoleEl.textContent = `Iniciando gravação na unidade ${letter}...`;

    try {
        const res = await fetch('/api/v1/power-tools/usb-rescue/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ drive_letter: letter })
        });
        const data = await res.json();
        if (consoleEl && Array.isArray(data.logs)) {
            consoleEl.textContent = data.logs.join('\n');
        } else if (consoleEl) {
            consoleEl.textContent = data.error || 'Operação finalizada.';
        }
        if (!data.success && data.error) {
            alert(`Aviso: ${data.error}`);
        }
    } catch (e) {
        if (consoleEl) consoleEl.textContent = 'Erro na criação do pendrive USB: ' + e.message;
    }
}
