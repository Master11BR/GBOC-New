// ==============================================================================
// GBOC System v13.2.0 Enterprise Edition
// Module: Hermes Agent UI Controller
// Copyright (c) 2026 Master11BR - Todos os direitos reservados.
// ==============================================================================

'use strict';

const HermesUI = (() => {
  const API = '/api/v1/hermes';
  let _refreshTimer = null;
  const MAX_BW_MBPS = 500;

  // ─── Utilities ─────────────────────────────────────────────────────────────

  const el = id => document.getElementById(id);
  const setText = (id, val) => { const e = el(id); if (e) e.textContent = val ?? '—'; };
  const fmtNum = n => n?.toLocaleString('pt-BR') ?? '—';
  const fmtDate = s => {
    if (!s) return '—';
    try { return new Intl.DateTimeFormat('pt-BR', { dateStyle:'short', timeStyle:'medium' }).format(new Date(s)); }
    catch { return s; }
  };

  function toast(msg, type = 'info') {
    const t = document.createElement('div');
    const colors = { info: '#06b6d4', success: '#10b981', warning: '#f59e0b', error: '#ef4444' };
    t.style.cssText = `position:fixed;bottom:20px;right:20px;z-index:9999;padding:12px 20px;
      border-radius:10px;background:#111827;border:1px solid ${colors[type] || colors.info};
      color:${colors[type] || colors.info};font-size:0.82rem;font-family:'Inter',sans-serif;
      box-shadow:0 4px 20px rgba(0,0,0,0.5);animation:fadeIn .3s ease;max-width:360px;`;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4500);
  }

  function addHealLog(message, type = 'info') {
    const terminal = el('healTerminal');
    if (!terminal) return;
    const entry = document.createElement('div');
    entry.className = `heal-log-entry ${type}`;
    const now = new Date().toLocaleTimeString('pt-BR', { hour12: false });
    entry.innerHTML = `<span class="ts">[${now}]</span><span class="msg"> ${message}</span>`;
    terminal.appendChild(entry);
    // Manter máximo de 200 linhas
    while (terminal.children.length > 200) terminal.removeChild(terminal.firstChild);
    terminal.scrollTop = terminal.scrollHeight;
  }

  // ─── API Calls ─────────────────────────────────────────────────────────────

  async function apiFetch(path, opts = {}) {
    const res = await fetch(API + path, {
      headers: { 'Content-Type': 'application/json' },
      ...opts
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    return res.json();
  }

  // ─── Status Global ─────────────────────────────────────────────────────────

  async function loadStatus() {
    try {
      const data = await apiFetch('/status');
      const p = data.pillars || {};

      // Pillar 1 — Queue
      const q = p.store_and_forward_queue || {};
      setText('queuePending', fmtNum(q.pending_messages));
      setText('queueSub', 'msgs pendentes');
      setText('qStatPending', fmtNum(q.pending_messages));
      setText('qStatAcked', fmtNum(q.acked_messages));
      setText('qStatSize', `${q.queue_db_size_mb ?? '—'} MB`);
      setText('qStatOldest', fmtDate(q.oldest_pending_at));
      setText('qStatMax', fmtNum(q.max_queue_size));
      const ls = q.last_burst_sync;
      setText('qStatLastSync', ls ? `${fmtDate(ls.at)} — ${ls.messages} msgs` : 'Nenhum ainda');

      // Pillar 2 — Self-Heal
      const h = p.self_healing_watchdog || {};
      setText('healEvents', fmtNum(h.heal_events_logged));
      setText('healSub', 'eventos registrados');

      // Pillar 3 — Mesh
      const m = p.p2p_lan_mesh || {};
      setText('meshPeers', fmtNum(m.peers_online));
      setText('meshSub', 'peers online na LAN');

      // Pillar 4 — Bandwidth
      const bw = p.bandwidth_control || {};
      const throttle = bw.current_throttle_mbps ?? 0;
      setText('bwThrottle', throttle ? `${throttle.toFixed(0)} Mbps` : '—');
      setText('bwSub', bw.mode === 'manual' ? 'modo manual' : 'modo automático');
      setText('bwCurrent', `${throttle.toFixed(1)} Mbps`);
      setText('bwSamples', fmtNum(bw.total_samples_collected));
      setText('bwLearning', bw.learning_days ? `${bw.learning_days} / 7 dias` : '—');
      el('bwMode').textContent = bw.mode || '—';
      el('bwMode').className = bw.mode === 'manual' ? 'badge badge-yellow' : 'badge badge-purple';

      // Throttle bar
      const fill = Math.min(100, (throttle / MAX_BW_MBPS) * 100);
      const tb = el('throttleFill');
      if (tb) tb.style.width = `${fill}%`;

      // Live indicator
      el('liveDot').style.background = '#10b981';
      el('liveStatus').textContent = 'Conectado';

      // VSS writers from heal status
      if (h.vss_writers_total !== undefined) updateVSSFromStatus(h);

      // Mesh peers
      if (m.peers) renderMeshPeers(m.peers);

      // Heal log last events
      if (h.last_heal_events?.length) {
        h.last_heal_events.forEach(ev => {
          const typeMap = { SUCCESS: 'ok', WARN: 'warn', ERROR: 'err', OK: 'ok' };
          addHealLog(`[${ev.action}] ${ev.message}`, typeMap[ev.status] || 'info');
        });
      }

    } catch (err) {
      el('liveDot').style.background = '#ef4444';
      el('liveStatus').textContent = 'Offline';
      console.error('[Hermes UI] Erro ao carregar status:', err);
    }
  }

  function updateVSSFromStatus(h) {
    const total = h.vss_writers_total || 0;
    const failed = h.vss_writers_failed || 0;
    const list = el('vssWritersList');
    if (!list) return;

    if (total === 0) {
      list.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;text-align:center;padding:16px;">vssadmin não disponível (não-Windows)</div>';
      return;
    }

    list.innerHTML = `
      <div class="vss-item">
        <span class="vss-name">VSS Writers Total</span>
        <span class="badge badge-blue">${total}</span>
      </div>
      <div class="vss-item">
        <span class="vss-name">Writers com Falha</span>
        <span class="badge ${failed > 0 ? 'badge-red' : 'badge-green'}">${failed}</span>
      </div>
    `;
  }

  function renderMeshPeers(peers) {
    const list = el('meshPeerList');
    if (!list) return;

    if (!peers || peers.length === 0) {
      list.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;text-align:center;padding:20px;">Nenhum peer descoberto ainda. Clique em Varredura.</div>';
      return;
    }

    list.innerHTML = peers.map(p => {
      const rtt = p.rtt_ms;
      const rttClass = rtt && rtt > 10 ? 'slow' : '';
      const rttLabel = rtt != null ? `${rtt.toFixed(1)}ms` : 'N/A';
      return `
        <div class="peer-item">
          <div class="peer-dot ${p.status !== 'online' ? 'offline' : ''}"></div>
          <div class="peer-info">
            <div class="peer-hostname">${p.hostname || p.agent_id || 'Unknown'}</div>
            <div class="peer-meta">${p.ip || '?'} — GBOC v${p.version || '?'} — Visto: ${fmtDate(p.last_seen)}</div>
          </div>
          <div class="peer-rtt ${rttClass}">${rttLabel}</div>
        </div>
      `;
    }).join('');
  }

  // ─── VSS Writers ─────────────────────────────────────────────────────────

  async function loadVSSWriters() {
    try {
      const data = await apiFetch('/self-heal/log?limit=0');
      await loadStatus();
      addHealLog('Status do VSS atualizado', 'info');
    } catch (err) {
      addHealLog(`Erro ao carregar VSS: ${err.message}`, 'err');
    }
  }

  // ─── Self-Heal Actions ────────────────────────────────────────────────────

  async function healVSS() {
    const btn = event?.target;
    if (btn) btn.disabled = true;
    addHealLog('Iniciando reparo automático de VSS Writers...', 'info');
    try {
      const data = await apiFetch('/self-heal/vss', { method: 'POST', body: '{}' });
      const failedBefore = data.failed_writers_before?.length ?? 0;
      const failedAfter = data.failed_writers_after?.length ?? 0;
      if (data.success) {
        addHealLog(`✓ VSS reparado: ${failedBefore} falhos → ${failedAfter} falhos`, 'ok');
        toast('VSS Writers reparados com sucesso', 'success');
      } else {
        addHealLog(`⚠ Reparo parcial: ${failedBefore} → ${failedAfter} writers com problema`, 'warn');
        toast('Reparo parcial — verifique o terminal', 'warning');
      }
      (data.steps_executed || []).forEach(step => addHealLog(step, step.startsWith('✓') ? 'ok' : 'warn'));
    } catch (err) {
      addHealLog(`✗ Erro no reparo de VSS: ${err.message}`, 'err');
      toast('Erro ao reparar VSS', 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function healDisk() {
    addHealLog('Verificando espaço em disco...', 'info');
    try {
      const data = await apiFetch('/self-heal/disk', { method: 'POST', body: '{}' });
      const drive = data.drives_checked?.[0];
      if (drive) {
        addHealLog(`Disco ${drive.path}: ${drive.used_pct}% usado (${drive.free_gb} GB livres)`,
          drive.used_pct >= 95 ? 'warn' : 'ok');
      }
      if (data.purge_executed) {
        const freed = (data.bytes_freed / 1024 / 1024).toFixed(1);
        addHealLog(`✓ Expurgo executado: ${freed} MB liberados`, 'ok');
        toast(`Espaço liberado: ${freed} MB`, 'success');
      } else {
        addHealLog('Espaço em disco OK — sem necessidade de expurgo', 'ok');
      }
    } catch (err) {
      addHealLog(`✗ Erro no disk guard: ${err.message}`, 'err');
    }
  }

  async function healServices() {
    addHealLog('Verificando serviços críticos do Windows...', 'info');
    try {
      const data = await apiFetch('/self-heal/services', { method: 'POST', body: '{}' });
      (data.services_checked || []).forEach(svc => {
        const type = svc.state === 'running' ? 'ok' : svc.state === 'stopped' ? 'err' : 'warn';
        addHealLog(`${svc.service}: ${svc.state}`, type);
      });
      if (data.services_restarted?.length) {
        addHealLog(`✓ Reiniciados: ${data.services_restarted.join(', ')}`, 'ok');
        toast(`Serviços reiniciados: ${data.services_restarted.join(', ')}`, 'success');
      } else {
        addHealLog('Todos os serviços monitorados estão em execução', 'ok');
      }
    } catch (err) {
      addHealLog(`✗ Erro no watchdog de serviços: ${err.message}`, 'err');
    }
  }

  // ─── Queue Actions ────────────────────────────────────────────────────────

  async function flushQueue() {
    const btn = el('btnFlush');
    if (btn) { btn.disabled = true; btn.textContent = 'Sincronizando...'; }
    try {
      const data = await apiFetch('/queue/flush', { method: 'POST', body: JSON.stringify({ max_batch: 500 }) });
      toast(`Burst Sync: ${data.batch_size} mensagens prontas para entrega`, 'info');
      await loadStatus();
    } catch (err) {
      toast(`Erro no Burst Sync: ${err.message}`, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Burst Sync'; }
    }
  }

  async function gcQueue() {
    try {
      const data = await apiFetch('/queue/gc', { method: 'POST', body: '{}' });
      toast(`GC: ${data.records_removed} registros antigos removidos`, 'success');
      await loadStatus();
    } catch (err) {
      toast(`Erro no GC: ${err.message}`, 'error');
    }
  }

  // ─── Mesh Actions ─────────────────────────────────────────────────────────

  async function scanMesh() {
    const btn = el('btnScan');
    if (btn) { btn.disabled = true; btn.textContent = 'Varrendo... (5s)'; }
    addHealLog('Varredura LAN Mesh iniciada — aguardando 5s por respostas mDNS/UDP...', 'info');
    try {
      const data = await apiFetch('/mesh/discover', { method: 'POST', body: '{}' });
      const found = data.peers_found?.length ?? 0;
      addHealLog(`Varredura concluída: ${found} peer(s) encontrado(s) em ${data.scan_duration_ms}ms`, found > 0 ? 'ok' : 'warn');
      renderMeshPeers(data.peers_found || []);
      setText('meshPeers', found);
    } catch (err) {
      addHealLog(`✗ Erro na varredura mesh: ${err.message}`, 'err');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Varredura'; }
    }
  }

  // ─── Bandwidth Actions ────────────────────────────────────────────────────

  async function setThrottle() {
    const val = parseFloat(el('throttleInput')?.value);
    if (!val || val <= 0) { toast('Informe um valor válido em Mbps', 'warning'); return; }
    try {
      const data = await apiFetch('/bandwidth/throttle', {
        method: 'POST',
        body: JSON.stringify({ mbps: val })
      });
      toast(`Throttle definido: ${val} Mbps (modo manual)`, 'success');
      addHealLog(`Bandwidth throttle definido manualmente: ${val} Mbps`, 'warn');
      await loadStatus();
    } catch (err) {
      toast(`Erro ao definir throttle: ${err.message}`, 'error');
    }
  }

  async function setAutoThrottle() {
    try {
      await apiFetch('/bandwidth/throttle', { method: 'POST', body: JSON.stringify({ mbps: null }) });
      toast('Modo automático adaptativo ativado', 'success');
      addHealLog('Bandwidth voltou ao modo automático adaptativo (Edge AI)', 'ok');
      if (el('throttleInput')) el('throttleInput').value = '';
      await loadStatus();
    } catch (err) {
      toast(`Erro: ${err.message}`, 'error');
    }
  }

  async function estimateDuration() {
    const sizeMb = parseFloat(el('estimateSizeMb')?.value);
    if (!sizeMb || sizeMb <= 0) { toast('Informe o tamanho em MB', 'warning'); return; }
    try {
      const data = await apiFetch(`/bandwidth/estimate?size_mb=${sizeMb}`);
      el('estimateResult').textContent =
        `⏱ ${data.estimated_duration_human} @ ${data.current_throttle_mbps?.toFixed(0)} Mbps`;
    } catch (err) {
      el('estimateResult').textContent = `Erro: ${err.message}`;
    }
  }

  // ─── Auto-Refresh ─────────────────────────────────────────────────────────

  function startRefresh(intervalMs = 15000) {
    loadStatus();
    if (_refreshTimer) clearInterval(_refreshTimer);
    _refreshTimer = setInterval(loadStatus, intervalMs);
  }

  // ─── Init ─────────────────────────────────────────────────────────────────

  function init() {
    startRefresh(15000);
    addHealLog('Hermes Agent UI iniciado — auto-refresh a cada 15s', 'info');
  }

  document.addEventListener('DOMContentLoaded', init);

  // ─── Public API ──────────────────────────────────────────────────────────

  return {
    loadStatus,
    loadVSSWriters,
    healVSS,
    healDisk,
    healServices,
    flushQueue,
    gcQueue,
    scanMesh,
    setThrottle,
    setAutoThrottle,
    estimateDuration
  };
})();
