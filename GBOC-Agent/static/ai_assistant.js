/* GBOC 14.7.3 Enterprise Edition — GBOC Copilot AI (widget flutuante compartilhado Server/Agent)
 * Arquivo idêntico em GBOC-Server/ai_assistant.js e GBOC-Agent/static/ai_assistant.js.
 * - Autenticação: envia o token da sessão (Bearer) — Server: gboc_server_token / Agent: gboc_token.
 * - Segurança: todo conteúdo dinâmico é inserido via textContent / HTML escapado (sem XSS).
 * - Zero-Mock: exibe exatamente o que a API retornou, inclusive erros.
 */
(() => {
    'use strict';

    const PROVIDERS = [
        { id: 'ollama_local', label: 'Ollama Local (On-Premises / Off-line)', key: null, link: 'https://ollama.com/download' },
        { id: 'deepseek', label: 'DeepSeek', key: 'deepseek_api_key', model: 'deepseek_model', link: 'https://platform.deepseek.com/api_keys' },
        { id: 'groq', label: 'Groq Cloud', key: 'groq_api_key', model: 'groq_model', link: 'https://console.groq.com/keys' },
        { id: 'gemini', label: 'Google Gemini', key: 'gemini_api_key', model: 'gemini_model', link: 'https://aistudio.google.com/app/apikey' },
        { id: 'openai', label: 'OpenAI', key: 'openai_api_key', model: 'openai_model', link: 'https://platform.openai.com/api-keys' },
        { id: 'claude', label: 'Anthropic Claude', key: 'claude_api_key', model: 'claude_model', link: 'https://platform.claude.com/settings/keys' },
        { id: 'grok', label: 'xAI Grok', key: 'grok_api_key', model: 'grok_model', link: 'https://console.x.ai' },
        { id: 'mistral', label: 'Mistral AI', key: 'mistral_api_key', model: 'mistral_model', link: 'https://console.mistral.ai/api-keys' },
        { id: 'kimi', label: 'Moonshot Kimi', key: 'kimi_api_key', model: 'kimi_model', link: 'https://platform.kimi.ai' },
        { id: 'cohere', label: 'Cohere', key: 'cohere_api_key', model: 'cohere_model', link: 'https://dashboard.cohere.com/api-keys' },
    ];

    const PROVIDER_ALIASES = [
        ['deepseek', ['deepseek']], ['groq', ['groq']], ['grok', ['grok', 'xai']], ['openai', ['openai', 'gpt']],
        ['gemini', ['gemini', 'google']], ['claude', ['claude', 'anthropic']], ['kimi', ['kimi', 'moonshot']],
        ['mistral', ['mistral']], ['cohere', ['cohere']], ['ollama_local', ['ollama', 'local', 'llama', 'qwen', 'gemma']],
    ];

    let currentConfig = {};
    let defaultModels = {};

    const normalizeProvider = (raw) => {
        const v = String(raw ?? '').toLowerCase();
        for (const [id, words] of PROVIDER_ALIASES) {
            if (words.some((w) => v.includes(w))) return id;
        }
        return 'ollama_local';
    };

    const readToken = () => {
        try {
            return localStorage.getItem('gboc_server_token') || localStorage.getItem('gboc_token') || '';
        } catch {
            return '';
        }
    };

    /** fetch autenticado com validação de resposta. Lança Error com mensagem legível. */
    async function apiFetch(path, options = {}) {
        const headers = new Headers(options.headers ?? {});
        const token = readToken();
        if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`);
        if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
        const resp = await fetch(`${window.GBOC_API_BASE ?? ''}${path}`, { ...options, headers, credentials: 'same-origin' });
        let data = null;
        try {
            data = await resp.json();
        } catch {
            data = null;
        }
        if (!resp.ok) {
            const msg = data?.message ?? data?.detail ?? data?.error?.message ?? `HTTP ${resp.status}`;
            const err = new Error(resp.status === 401 ? 'Sessão expirada ou não autenticada. Faça login novamente.' : String(msg));
            err.status = resp.status;
            throw err;
        }
        if (!data || typeof data !== 'object') throw new Error('Resposta inválida do servidor de IA.');
        return data;
    }

    const el = (tag, props = {}, children = []) => {
        const node = document.createElement(tag);
        for (const [k, v] of Object.entries(props)) {
            if (k === 'class') node.className = v;
            else if (k === 'text') node.textContent = v;
            else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
            else if (v !== undefined && v !== null) node.setAttribute(k, v);
        }
        for (const c of [].concat(children)) if (c) node.append(c);
        return node;
    };

    const escapeHtml = (str) => String(str ?? '')
        .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;').replaceAll("'", '&#39;');

    /** Markdown mínimo e seguro: escapa tudo e só então aplica **negrito**, `código` e quebras de linha. */
    const formatAiResponse = (text) => escapeHtml(text)
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+?)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');

    function injectStyles() {
        if (document.getElementById('gboc-ai-styles')) return;
        const style = el('style', { id: 'gboc-ai-styles' });
        style.textContent = `
            @keyframes aiDrawerIn { from { opacity: 0; transform: translateY(12px) scale(0.96); } to { opacity: 1; transform: none; } }
            #gboc-ai-drawer { position: fixed; inset-block-end: 80px; inset-inline-end: 24px; inline-size: 400px; max-inline-size: calc(100vw - 32px);
                block-size: 540px; max-block-size: calc(100vh - 110px); background: var(--bg-card, #182035); border: 1px solid var(--border, #2a3f5f);
                border-radius: 16px; box-shadow: 0 16px 40px rgb(0 0 0 / 0.5); z-index: 9999; display: flex; flex-direction: column; overflow: hidden;
                animation: aiDrawerIn 0.22s cubic-bezier(0.16, 1, 0.3, 1); }
            #gboc-ai-drawer[hidden], #gboc-ai-config-modal:not([open]) { display: none; }
            .ai-head { background: linear-gradient(135deg, #4f46e5, #7c3aed); padding: 14px 18px; color: #fff; display: flex; justify-content: space-between; align-items: center; }
            .ai-head-title { font-weight: 700; font-size: 0.95em; }
            .ai-head-sub { font-size: 0.75em; opacity: 0.88; }
            .ai-icon-btn { background: rgb(255 255 255 / 0.15); border: none; color: #fff; inline-size: 30px; block-size: 30px; border-radius: 8px; cursor: pointer; }
            .ai-icon-btn:focus-visible, .ai-preset-btn:focus-visible, .ai-send-btn:focus-visible { outline: 2px solid var(--primary, #4fa3e8); outline-offset: 2px; }
            .ai-presets { display: flex; gap: 6px; padding: 8px 12px; background: var(--bg-input, #111928); border-block-end: 1px solid var(--border, #2a3f5f); overflow-x: auto; scrollbar-width: none; }
            .ai-preset-btn { background: var(--bg-card, #182035); border: 1px solid var(--border, #2a3f5f); color: var(--text-muted, #7ea8cc); padding: 4px 10px; border-radius: 12px; font-size: 0.76em; cursor: pointer; white-space: nowrap; }
            .ai-preset-btn:hover { color: var(--primary, #4fa3e8); border-color: var(--primary, #4fa3e8); }
            #ai-chat-messages { flex: 1; padding: 14px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; font-size: 0.85em; background: var(--bg-dark, #0e1525); }
            .ai-msg { padding: 9px 13px; border-radius: 12px; max-inline-size: 85%; word-break: break-word; line-height: 1.45; color: var(--text, #dce8f5); }
            .ai-msg-user { align-self: flex-end; background: var(--primary, #4fa3e8); color: #fff; border-end-end-radius: 2px; }
            .ai-msg-bot { align-self: flex-start; background: var(--bg-card, #182035); border: 1px solid var(--border, #2a3f5f); border-end-start-radius: 2px; }
            .ai-msg-err { align-self: flex-start; background: rgb(240 107 107 / 0.15); border: 1px solid rgb(240 107 107 / 0.3); color: var(--danger, #f06b6b); }
            .ai-msg-meta { font-size: 0.72em; color: var(--primary, #4fa3e8); margin-block-end: 6px; font-weight: 700; }
            .ai-msg-meta.ai-no-llm { color: var(--warning, #f59e0b); }
            .ai-input-bar { padding: 12px; background: var(--bg-card, #182035); border-block-start: 1px solid var(--border, #2a3f5f); display: flex; gap: 8px; }
            .ai-input, .ai-field { flex: 1; background: var(--bg-input, #111928); border: 1px solid var(--border, #2a3f5f); color: var(--text, #dce8f5); padding: 10px 14px; border-radius: 10px; font-size: 0.88em; inline-size: 100%; box-sizing: border-box; }
            .ai-send-btn { background: var(--primary, #4fa3e8); color: #fff; border: none; inline-size: 38px; block-size: 38px; border-radius: 10px; cursor: pointer; }
            .ai-send-btn:disabled { opacity: 0.5; cursor: progress; }
            #gboc-ai-config-modal { border: 1px solid var(--border, #2a3f5f); border-radius: 16px; background: var(--bg-card, #182035); color: var(--text, #dce8f5);
                inline-size: 460px; max-inline-size: calc(100vw - 32px); padding: 24px; box-shadow: 0 20px 50px rgb(0 0 0 / 0.6); }
            #gboc-ai-config-modal::backdrop { background: rgb(0 0 0 / 0.65); backdrop-filter: blur(4px); }
            .ai-label { font-size: 0.8em; color: var(--text-muted, #7ea8cc); display: block; margin-block: 10px 4px; }
            .ai-hint { font-size: 0.76em; color: var(--text-muted, #7ea8cc); margin-block-start: 4px; }
            .ai-hint a { color: var(--primary, #4fa3e8); }
            .ai-actions { display: flex; justify-content: flex-end; gap: 10px; margin-block-start: 20px; }
            .ai-btn { padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 0.88em; border: 1px solid var(--border, #2a3f5f); background: var(--bg-input, #111928); color: var(--text, #dce8f5); }
            .ai-btn-primary { background: var(--primary, #4fa3e8); border-color: transparent; color: #fff; font-weight: 600; }
            .ai-status { margin-block-start: 12px; font-size: 0.82em; min-block-size: 1em; }
            .ai-status.ok { color: var(--success, #10b981); } .ai-status.err { color: var(--danger, #ef4444); }
        `;
        document.head.append(style);
    }

    function addMessage(kind, text, meta) {
        const box = document.getElementById('ai-chat-messages');
        if (!box) return null;
        const msg = el('div', { class: `ai-msg ai-msg-${kind}` });
        if (meta) msg.append(el('div', { class: `ai-msg-meta${meta.noLlm ? ' ai-no-llm' : ''}`, text: meta.label }));
        const body = el('div');
        if (kind === 'bot') body.innerHTML = formatAiResponse(text);
        else body.textContent = text;
        msg.append(body);
        box.append(msg);
        box.scrollTop = box.scrollHeight;
        return msg;
    }

    function buildWidget() {
        const drawer = el('section', { id: 'gboc-ai-drawer', hidden: '', 'aria-label': 'GBOC AI Copilot', role: 'dialog' }, [
            el('header', { class: 'ai-head' }, [
                el('div', {}, [
                    el('div', { class: 'ai-head-title', text: 'GBOC AI Copilot' }),
                    el('div', { class: 'ai-head-sub', id: 'ai-active-provider', text: 'Carregando IA...' }),
                ]),
                el('div', { class: 'ai-head-actions' }, [
                    el('button', { type: 'button', class: 'ai-icon-btn', title: 'Configurar Provedor de IA', 'aria-label': 'Configurar Provedor de IA',
                        onclick: () => window.GBOC_AI_Assistant.toggleConfig() }, [el('i', { class: 'fas fa-cog', 'aria-hidden': 'true' })]),
                    el('button', { type: 'button', class: 'ai-icon-btn', title: 'Fechar Chat', 'aria-label': 'Fechar Chat',
                        onclick: () => window.GBOC_AI_Assistant.close() }, [el('i', { class: 'fas fa-times', 'aria-hidden': 'true' })]),
                ]),
            ]),
            el('nav', { class: 'ai-presets', 'aria-label': 'Perguntas rápidas' }, [
                ['📊 Status Geral', 'Qual o status geral do sistema e agentes?'],
                ['🚨 Jobs Falhos', 'Quais jobs falharam nas últimas 24h e por quê?'],
                ['📼 Dica Backup', 'Como configurar backup de repositório LTO/Tape?'],
            ].map(([label, prompt]) => el('button', { type: 'button', class: 'ai-preset-btn', text: label,
                onclick: () => window.GBOC_AI_Assistant.sendPreset(prompt) }))),
            el('div', { id: 'ai-chat-messages', 'aria-live': 'polite' }),
            el('form', { class: 'ai-input-bar', onsubmit: (ev) => { ev.preventDefault(); window.GBOC_AI_Assistant.send(); } }, [
                el('input', { type: 'text', id: 'ai-chat-input', class: 'ai-input', maxlength: '8000', autocomplete: 'off',
                    placeholder: 'Pergunte ao GBOC Copilot AI...', 'aria-label': 'Pergunta para o Copilot' }),
                el('button', { type: 'submit', id: 'ai-send-btn', class: 'ai-send-btn', 'aria-label': 'Enviar' },
                    [el('i', { class: 'fas fa-paper-plane', 'aria-hidden': 'true' })]),
            ]),
        ]);

        const select = el('select', { id: 'ai-provider-select', class: 'ai-field', onchange: () => window.GBOC_AI_Assistant.onProviderChange() },
            PROVIDERS.map((p) => el('option', { value: p.id, text: p.label })));
        const modal = el('dialog', { id: 'gboc-ai-config-modal', 'aria-labelledby': 'ai-cfg-title' }, [
            el('h3', { id: 'ai-cfg-title', text: 'Provedores de IA Generativa' }),
            el('label', { class: 'ai-label', for: 'ai-provider-select', text: 'Provedor Ativo' }),
            select,
            el('div', { id: 'ai-provider-fields' }),
            el('div', { id: 'ai-cfg-status', class: 'ai-status', role: 'status' }),
            el('div', { class: 'ai-actions' }, [
                el('button', { type: 'button', class: 'ai-btn', text: 'Cancelar', onclick: () => window.GBOC_AI_Assistant.toggleConfig() }),
                el('button', { type: 'button', class: 'ai-btn ai-btn-primary', id: 'ai-cfg-save', text: 'Salvar Provedor',
                    onclick: () => window.GBOC_AI_Assistant.saveConfig() }),
            ]),
        ]);

        const container = el('div', { id: 'gboc-ai-chatbot-container' }, [drawer, modal]);
        document.body.append(container);
        addMessage('bot', '👋 Olá! Eu sou o **GBOC AI Copilot**. Pergunte sobre backups, restaurações, agentes ou segurança — respondo com os dados reais do sistema.');
    }

    function injectAiChatbotWidget() {
        if (document.getElementById('gboc-ai-chatbot-container')) return;
        injectStyles();
        buildWidget();
        loadAiConfigStatus();
    }

    async function loadAiConfigStatus() {
        const badge = document.getElementById('ai-active-provider');
        try {
            const d = await apiFetch('/api/v1/ai/config');
            currentConfig = d.config ?? {};
            defaultModels = d.default_models ?? {};
            const id = normalizeProvider(currentConfig.provider);
            const prov = PROVIDERS.find((p) => p.id === id);
            if (badge) badge.textContent = prov?.label ?? String(currentConfig.provider ?? '');
            const sel = document.getElementById('ai-provider-select');
            if (sel) sel.value = id;
            window.GBOC_AI_Assistant.onProviderChange();
        } catch (e) {
            if (badge) badge.textContent = `IA indisponível: ${e.message}`;
            console.warn('[GBOC AI] Falha ao carregar configuração de IA:', e);
        }
    }

    window.GBOC_AI_Assistant = {
        toggle() {
            if (!document.getElementById('gboc-ai-drawer')) injectAiChatbotWidget();
            const drawer = document.getElementById('gboc-ai-drawer');
            drawer.hidden = !drawer.hidden;
            if (!drawer.hidden) document.getElementById('ai-chat-input')?.focus();
        },
        open() {
            if (!document.getElementById('gboc-ai-drawer')) injectAiChatbotWidget();
            document.getElementById('gboc-ai-drawer').hidden = false;
            document.getElementById('ai-chat-input')?.focus();
        },
        close() {
            const drawer = document.getElementById('gboc-ai-drawer');
            if (drawer) drawer.hidden = true;
        },
        toggleConfig() {
            const modal = document.getElementById('gboc-ai-config-modal');
            if (!modal) return;
            if (modal.open) {
                modal.close();
            } else {
                document.getElementById('ai-cfg-status').textContent = '';
                this.onProviderChange();
                modal.showModal();
            }
        },
        sendPreset(text) {
            const input = document.getElementById('ai-chat-input');
            if (!input) return;
            input.value = text;
            this.send();
        },
        async send() {
            const input = document.getElementById('ai-chat-input');
            const btn = document.getElementById('ai-send-btn');
            const msg = (input?.value ?? '').trim();
            if (!msg || btn?.disabled) return;
            addMessage('user', msg);
            input.value = '';
            if (btn) btn.disabled = true;
            const loading = addMessage('bot', '⏳ Analisando...');
            try {
                const d = await apiFetch('/api/v1/ai/query', { method: 'POST', body: JSON.stringify({ prompt: msg }) });
                loading?.remove();
                if (d.status !== 'success' || typeof d.answer !== 'string') throw new Error(d.message ?? 'Resposta inválida do Copilot.');
                const noLlm = d.is_llm_real === false;
                addMessage('bot', d.answer, { label: `🤖 ${d.provider ?? 'GBOC AI'}${noLlm ? ' — sem LLM' : ''}`, noLlm });
            } catch (e) {
                loading?.remove();
                addMessage('err', `Erro de comunicação com o Copilot: ${e.message}`);
            } finally {
                if (btn) btn.disabled = false;
            }
        },
        onProviderChange() {
            const id = document.getElementById('ai-provider-select')?.value ?? 'ollama_local';
            const fields = document.getElementById('ai-provider-fields');
            if (!fields) return;
            const prov = PROVIDERS.find((p) => p.id === id) ?? PROVIDERS[0];
            fields.replaceChildren();
            if (!prov.key) {
                fields.append(
                    el('label', { class: 'ai-label', for: 'cfg-ollama-url', text: 'URL do Ollama' }),
                    el('input', { type: 'url', id: 'cfg-ollama-url', class: 'ai-field', value: currentConfig.ollama_url ?? currentConfig.ollama_host ?? 'http://localhost:11434' }),
                    el('label', { class: 'ai-label', for: 'cfg-model', text: 'Modelo Ollama' }),
                    el('input', { type: 'text', id: 'cfg-model', class: 'ai-field', value: currentConfig.ollama_model ?? '', placeholder: defaultModels.ollama ?? 'llama3' }),
                );
            } else {
                const configured = (currentConfig.configured_keys ?? []).includes(id);
                const modelField = prov.model;
                const shortId = id === 'ollama_local' ? 'ollama' : id;
                fields.append(
                    el('label', { class: 'ai-label', for: 'cfg-api-key', text: `Chave de API — ${prov.label}` }),
                    el('input', { type: 'password', id: 'cfg-api-key', class: 'ai-field', autocomplete: 'off',
                        placeholder: configured ? 'Chave já configurada — deixe em branco para manter' : 'Cole a chave de API' }),
                    el('label', { class: 'ai-label', for: 'cfg-model', text: 'Modelo (opcional)' }),
                    el('input', { type: 'text', id: 'cfg-model', class: 'ai-field', value: currentConfig[modelField] ?? '',
                        placeholder: defaultModels[shortId] ?? '' }),
                );
            }
            const hint = el('div', { class: 'ai-hint' });
            hint.append(el('a', { href: prov.link, target: '_blank', rel: 'noopener noreferrer', text: `Obter / gerenciar: ${new URL(prov.link).hostname}` }));
            fields.append(hint);
        },
        async saveConfig() {
            const id = document.getElementById('ai-provider-select')?.value ?? 'ollama_local';
            const prov = PROVIDERS.find((p) => p.id === id) ?? PROVIDERS[0];
            const status = document.getElementById('ai-cfg-status');
            const saveBtn = document.getElementById('ai-cfg-save');
            const body = { provider: id };
            const model = document.getElementById('cfg-model')?.value.trim();
            if (prov.key) {
                const key = document.getElementById('cfg-api-key')?.value.trim();
                if (key) body[prov.key] = key;
                if (model) body[prov.model] = model;
            } else {
                body.ollama_url = document.getElementById('cfg-ollama-url')?.value.trim() || 'http://localhost:11434';
                if (model) body.ollama_model = model;
            }
            status.className = 'ai-status';
            status.textContent = 'Salvando...';
            saveBtn.disabled = true;
            try {
                await apiFetch('/api/v1/ai/config', { method: 'POST', body: JSON.stringify(body) });
                status.className = 'ai-status ok';
                status.textContent = 'Provedor de IA salvo.';
                await loadAiConfigStatus();
                setTimeout(() => document.getElementById('gboc-ai-config-modal')?.close(), 600);
            } catch (e) {
                status.className = 'ai-status err';
                status.textContent = `Erro ao salvar: ${e.message}`;
            } finally {
                saveBtn.disabled = false;
            }
        },
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', injectAiChatbotWidget, { once: true });
    } else {
        injectAiChatbotWidget();
    }
})();
