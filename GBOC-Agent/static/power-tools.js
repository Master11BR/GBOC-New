/**
 * GBOC System v14.0.0 Enterprise Edition
 * Module: Freemium & Open-Source Power Tools Controller
 * Copyright (c) 2026 Master11BR - Todos os direitos reservados.
 */

document.addEventListener('DOMContentLoaded', () => {
    if (typeof UnifiedSidebar === 'function') {
        new UnifiedSidebar().initialize();
    }
    loadVfsDrives();
    loadLinuxSnapshots();
    loadUsbDrives();
    runVisualDiffComparison();
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
    const left = document.getElementById('diff-left-path')?.value || 'C:\\Dados\\Producao';
    const right = document.getElementById('diff-right-path')?.value || 'D:\\Backup\\Mirror';
    const tbody = document.getElementById('visual-diff-table-body');

    if (tbody) tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:16px;">Comparando pastas e gerando árvore de diferenças...</td></tr>';

    try {
        const res = await fetch('/api/v1/power-tools/visual-diff/compare', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ left_path: left, right_path: right })
        });
        const data = await res.json();
        const tree = data.data?.diff_tree || [];
        const sum = data.data?.summary || {};

        const sumEl = document.getElementById('diff-summary-badges');
        if (sumEl) {
            sumEl.innerHTML = `
                <span class="badge badge-primary">${sum.total_files || tree.length} Itens</span>
                <span class="badge badge-success">${sum.left_only || 0} Novos (Origem)</span>
                <span class="badge badge-warning">${sum.different || 0} Modificados</span>
                <span class="badge badge-info">${sum.identical || 0} Idênticos</span>
            `;
        }

        if (tbody) {
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
    }
}

async function executeSyncAction() {
    const left = document.getElementById('diff-left-path')?.value || 'C:\\Dados\\Producao';
    const right = document.getElementById('diff-right-path')?.value || 'D:\\Backup\\Mirror';

    try {
        const res = await fetch('/api/v1/power-tools/visual-diff/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ left_path: left, right_path: right, sync_mode: 'MIRROR' })
        });
        const data = await res.json();
        if (data.success) {
            alert(`🎉 Sincronização em Espelho concluída com sucesso!\n${data.items_copied} arquivos copiados (${data.bytes_transferred_mb} MB).`);
            runVisualDiffComparison();
        }
    } catch (e) {
        alert('Erro ao sincronizar: ' + e.message);
    }
}

// ── 2. Bitrot & Reed-Solomon Scrub ──────────────────────────────────────────
async function runBitrotScrubAction() {
    const consoleEl = document.getElementById('bitrot-console');
    if (consoleEl) consoleEl.textContent = 'Iniciando varredura profunda de blocos e cálculo de paridade Reed-Solomon...';

    try {
        const res = await fetch('/api/v1/power-tools/bitrot/scrub', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_path: 'C:\\GBOC-Backups' })
        });
        const data = await res.json();
        if (consoleEl && Array.isArray(data.logs)) {
            consoleEl.textContent = data.logs.join('\n');
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
                            <div style="font-size:0.78em; color:var(--text-muted);">Repositório: ${d.repository_url} (Capacidade Virtual: ${d.virtual_size_tb} TB)</div>
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
    const url = document.getElementById('vfs-repo-url')?.value || 's3://wasabi/gboc-prod-backups';
    const letter = document.getElementById('vfs-drive-letter')?.value || 'Z:';

    try {
        const res = await fetch('/api/v1/power-tools/vfs/mount', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repository_url: url, drive_letter: letter })
        });
        const data = await res.json();
        if (data.success) {
            alert(`🎉 Drive Virtual '${letter}' montado com sucesso no Windows Explorer!`);
            loadVfsDrives();
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
    const consoleEl = document.getElementById('rapid-delta-console');
    if (consoleEl) consoleEl.textContent = 'Lendo $Bitmap do NTFS e calculando setores delta...';

    try {
        const res = await fetch('/api/v1/power-tools/rapid-delta/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_image: 'C:\\GBOC-Backups\\System_Image_20260829.vhdx', target_disk: 0 })
        });
        const data = await res.json();
        if (consoleEl && Array.isArray(data.logs)) {
            consoleEl.textContent = data.logs.join('\n');
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
        const snaps = data.data?.snapshots || [];
        const tbody = document.getElementById('linux-snapshots-tbody');

        if (tbody) {
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
    try {
        const res = await fetch('/api/v1/power-tools/linux-snapshots/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dataset_name: 'rpool/ROOT/pve-1' })
        });
        const data = await res.json();
        if (data.success) {
            alert(`✅ Snapshot ZFS/BTRFS criado em ${data.duration_seconds}s!`);
            loadLinuxSnapshots();
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
            select.innerHTML = drives.map(d => `
                <option value="${d.drive_letter}">${d.drive_letter} [${d.label}] - ${d.model} (${d.size_gb} GB)</option>
            `).join('');
        }
    } catch (e) {
        console.error('Erro nos pendrives USB:', e);
    }
}

async function createUsbRescueAction() {
    const letter = document.getElementById('usb-drives-select')?.value || 'E:';
    if (!confirm(`AVISO: A unidade ${letter} será formatada e gravada com o GBOC WinPE Offline Recovery Environment.\n\nDeseja continuar?`)) return;

    const consoleEl = document.getElementById('usb-creator-console');
    if (consoleEl) consoleEl.textContent = 'Formatando partição EFI e gravando imagem WinPE...';

    try {
        const res = await fetch('/api/v1/power-tools/usb-rescue/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ drive_letter: letter })
        });
        const data = await res.json();
        if (consoleEl && Array.isArray(data.logs)) {
            consoleEl.textContent = data.logs.join('\n');
        }
    } catch (e) {
        if (consoleEl) consoleEl.textContent = 'Erro na criação do pendrive USB: ' + e.message;
    }
}
