// Module: AI Assistant Controller (ai_assistant.js) — página dedicada do Copilot no GBOC Server
// IDs próprios (ai-page-*) para não colidir com o widget flutuante (/static/ai_assistant.js).
(() => {
    'use strict';

    const readToken = () => {
        try { return localStorage.getItem('gboc_server_token') || ''; } catch { return ''; }
    };

    const escapeHtml = (s) => String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
    const formatAiResponse = (t) => escapeHtml(t).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+?)`/g, '<code>$1</code>').replace(/\n/g, '<br>');

    function addMsg(out, cls, html) {
        const p = document.createElement('p');
        p.className = `ai-page-msg ${cls}`;
        p.innerHTML = html;
        out.append(p);
        out.scrollTop = out.scrollHeight;
        return p;
    }

    async function sendAIChatQuery() {
        const input = document.getElementById('ai-page-input');
        const out = document.getElementById('ai-page-output');
        const btn = document.getElementById('ai-page-send');
        const prompt = input?.value.trim();
        if (!prompt || !out || btn?.disabled) return;
        input.value = '';
        btn.disabled = true;
        addMsg(out, 'ai-page-user', `<strong>Você:</strong> ${escapeHtml(prompt)}`);
        const bot = addMsg(out, 'ai-page-bot', '🤖 <strong>GBOC Copilot:</strong> <i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Pensando...');
        try {
            const headers = { 'Content-Type': 'application/json' };
            const token = readToken();
            if (token) headers.Authorization = `Bearer ${token}`;
            const r = await fetch(`${window.GBOC_API_BASE ?? ''}/api/v1/ai/query`, {
                method: 'POST', headers, credentials: 'same-origin', body: JSON.stringify({ prompt }),
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok || data.status !== 'success') {
                throw new Error(data.message ?? data.detail ?? `HTTP ${r.status}`);
            }
            const tag = data.is_llm_real === false ? ' — sem LLM' : '';
            bot.innerHTML = `🤖 <strong>GBOC Copilot (${escapeHtml(data.provider ?? 'AI')}${tag}):</strong><br>${formatAiResponse(data.answer)}`;
        } catch (e) {
            bot.className = 'ai-page-msg ai-page-err';
            bot.textContent = `Erro ao consultar a IA: ${e.message}`;
        } finally {
            btn.disabled = false;
        }
    }

    // Compatibilidade com chamadas antigas (onclick="sendAIChatQuery()")
    window.sendAIChatQuery = sendAIChatQuery;

    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('ai-page-form')?.addEventListener('submit', (ev) => {
            ev.preventDefault();
            sendAIChatQuery();
        });
    });
})();
