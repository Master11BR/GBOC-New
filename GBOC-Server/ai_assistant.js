/* GBOC 14.0.0 Enterprise Edition — Interactive GBOC Copilot AI Chatbot Floating Widget */
(function() {
    'use strict';

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', injectAiChatbotWidget);
    } else {
        injectAiChatbotWidget();
    }

    function injectAiChatbotWidget() {
        if (document.getElementById('gboc-ai-chatbot-container')) return;

        const container = document.createElement('div');
        container.id = 'gboc-ai-chatbot-container';
        container.innerHTML = `
            <!-- Drawer Chat Window -->
            <div id="gboc-ai-drawer" style="position:fixed;bottom:80px;right:24px;width:400px;max-width:calc(100vw - 32px);height:540px;max-height:calc(100vh - 110px);background:var(--bg-card,#182035);border:1px solid var(--border,#2a3f5f);border-radius:16px;box-shadow:0 16px 40px rgba(0,0,0,0.5);z-index:9999;display:none;flex-direction:column;overflow:hidden;backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);animation:aiDrawerIn 0.22s cubic-bezier(0.16, 1, 0.3, 1);">
                
                <!-- Header -->
                <div style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:14px 18px;color:#fff;display:flex;justify-content:space-between;align-items:center;box-shadow:0 2px 10px rgba(0,0,0,0.2)">
                    <div style="display:flex;align-items:center;gap:10px">
                        <div style="width:34px;height:34px;border-radius:10px;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;font-size:1.1em">
                            <i class="fas fa-brain"></i>
                        </div>
                        <div>
                            <div style="font-weight:700;font-size:0.95em;letter-spacing:-0.2px">GBOC AI Copilot</div>
                            <div style="font-size:0.75em;opacity:0.88" id="ai-active-provider">Carregando IA...</div>
                        </div>
                    </div>
                    <div style="display:flex;gap:8px">
                        <button onclick="window.GBOC_AI_Assistant.toggleConfig()" style="background:rgba(255,255,255,0.15);border:none;color:#fff;width:30px;height:30px;border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background 0.2s" title="Configurar Provedor de IA"><i class="fas fa-cog"></i></button>
                        <button onclick="window.GBOC_AI_Assistant.close()" style="background:rgba(255,255,255,0.15);border:none;color:#fff;width:30px;height:30px;border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background 0.2s" title="Fechar Chat"><i class="fas fa-times"></i></button>
                    </div>
                </div>

                <!-- Quick Presets Bar -->
                <div style="display:flex;gap:6px;padding:8px 12px;background:var(--bg-input,#111928);border-bottom:1px solid var(--border,#2a3f5f);overflow-x:auto;scrollbar-width:none">
                    <button class="ai-preset-btn" onclick="window.GBOC_AI_Assistant.sendPreset('Qual o status geral do sistema e agentes?')">📊 Status Geral</button>
                    <button class="ai-preset-btn" onclick="window.GBOC_AI_Assistant.sendPreset('Verificar jobs com falha nas últimas 24h')">🚨 Jobs Falhos</button>
                    <button class="ai-preset-btn" onclick="window.GBOC_AI_Assistant.sendPreset('Como configurar backup de repositório LTO/Tape?')">📼 Dica Backup</button>
                </div>

                <!-- Chat Messages Container -->
                <div id="ai-chat-messages" style="flex:1;padding:14px;overflow-y:auto;display:flex;flex-direction:column;gap:12px;font-size:0.85em;background:var(--bg-dark,#0e1525)">
                    <div style="background:rgba(99,102,241,0.12);border:1px solid rgba(99,102,241,0.3);padding:12px 14px;border-radius:12px;color:var(--text,#dce8f5);line-height:1.4">
                        👋 Olá! Eu sou o <strong>GBOC AI Copilot</strong>, seu assistente inteligente. Como posso ajudar com seus backups, tarefas de restauração, diagnóstico de agentes ou segurança?
                    </div>
                </div>

                <!-- Input Bar -->
                <div style="padding:12px;background:var(--bg-card,#182035);border-top:1px solid var(--border,#2a3f5f);display:flex;gap:8px;align-items:center">
                    <input type="text" id="ai-chat-input" placeholder="Pergunte ao GBOC Copilot AI..." style="flex:1;background:var(--bg-input,#111928);border:1px solid var(--border,#2a3f5f);color:var(--text,#dce8f5);padding:10px 14px;border-radius:10px;font-size:0.88em;outline:none" onkeypress="if(event.key==='Enter') window.GBOC_AI_Assistant.send()">
                    <button onclick="window.GBOC_AI_Assistant.send()" style="background:var(--primary,#4fa3e8);color:#fff;border:none;width:38px;height:38px;border-radius:10px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:opacity 0.2s"><i class="fas fa-paper-plane"></i></button>
                </div>
            </div>

            <!-- AI Config Modal -->
            <div id="gboc-ai-config-modal" style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.65);z-index:100000;display:none;align-items:center;justify-content:center;backdrop-filter:blur(4px);">
                <div style="background:var(--bg-card,#182035);width:440px;max-width:calc(100vw - 32px);padding:24px;border-radius:16px;border:1px solid var(--border,#2a3f5f);color:var(--text,#dce8f5);box-shadow:0 20px 50px rgba(0,0,0,0.6)">
                    <h3 style="margin-top:0;margin-bottom:16px;display:flex;align-items:center;gap:10px;font-size:1.1em">
                        <i class="fas fa-sliders-h" style="color:var(--primary,#4fa3e8)"></i> Provedores de IA Generativa
                    </h3>
                    
                    <div style="margin-bottom:14px">
                        <label style="font-size:0.8em;color:var(--text-muted,#7ea8cc);display:block;margin-bottom:6px">Provedor Ativo</label>
                        <select id="ai-provider-select" onchange="window.GBOC_AI_Assistant.onProviderChange()" style="width:100%;padding:10px;background:var(--bg-input,#111928);border:1px solid var(--border,#2a3f5f);color:var(--text,#dce8f5);border-radius:10px;font-size:0.88em">
                            <option value="deepseek">DeepSeek (V3 / R1 Nuvem)</option>
                            <option value="ollama_local">Ollama Local (On-Premises / Off-line - Sem limite de tokens)</option>
                            <option value="groq_free">Groq Cloud (Llama 3.3 70B Versatile)</option>
                            <option value="gemini_free">Google Gemini API (Free / Enterprise)</option>
                            <option value="openai">OpenAI (GPT-4o-mini / GPT-4o)</option>
                        </select>
                    </div>

                    <div id="ai-provider-fields"></div>

                    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:20px">
                        <button onclick="window.GBOC_AI_Assistant.toggleConfig()" style="padding:8px 16px;background:var(--bg-input,#111928);border:1px solid var(--border,#2a3f5f);color:var(--text,#dce8f5);border-radius:8px;cursor:pointer;font-size:0.88em">Cancelar</button>
                        <button onclick="window.GBOC_AI_Assistant.saveConfig()" style="padding:8px 18px;background:var(--primary,#4fa3e8);border:none;color:#fff;border-radius:8px;cursor:pointer;font-weight:600;font-size:0.88em">Salvar Provedor</button>
                    </div>
                </div>
            </div>
        `;

        // Inject inline CSS for presets
        const style = document.createElement('style');
        style.textContent = `
            @keyframes aiDrawerIn { from { opacity: 0; transform: translateY(12px) scale(0.96); } to { opacity: 1; transform: translateY(0) scale(1); } }
            .ai-preset-btn { background: var(--bg-card, #182035); border: 1px solid var(--border, #2a3f5f); color: var(--text-muted, #7ea8cc); padding: 4px 10px; border-radius: 12px; font-size: 0.76em; cursor: pointer; white-space: nowrap; transition: all 0.18s; }
            .ai-preset-btn:hover { background: var(--primary-soft, rgba(79,163,232,0.15)); color: var(--primary, #4fa3e8); border-color: var(--primary, #4fa3e8); }
        `;
        document.head.appendChild(style);
        document.body.appendChild(container);
        loadAiConfigStatus();
    }

    async function loadAiConfigStatus() {
        try {
            const r = await fetch(window.GBOC_API_BASE + '/api/v1/ai/config');
            const d = await r.json();
            if (d.config) {
                const providerNames = {
                    'deepseek': 'DeepSeek (V3 / R1 Nuvem)',
                    'ollama_local': 'Ollama Local (On-Premises)',
                    'groq_free': 'Groq (Llama 3.3 70B)',
                    'gemini_free': 'Google Gemini',
                    'openai': 'OpenAI GPT-4o'
                };
                const label = providerNames[d.config.provider] || d.config.provider;
                const badge = document.getElementById('ai-active-provider');
                if (badge) badge.textContent = label;
                const sel = document.getElementById('ai-provider-select');
                if (sel) sel.value = d.config.provider || 'deepseek';
            }
        } catch(e) {}
    }

    window.GBOC_AI_Assistant = {
        toggle() {
            const drawer = document.getElementById('gboc-ai-drawer');
            if (!drawer) {
                injectAiChatbotWidget();
                setTimeout(() => this.toggle(), 50);
                return;
            }
            const isHidden = drawer.style.display === 'none' || !drawer.style.display;
            drawer.style.display = isHidden ? 'flex' : 'none';
            if (isHidden) {
                document.getElementById('ai-chat-input')?.focus();
            }
        },
        open() {
            const drawer = document.getElementById('gboc-ai-drawer');
            if (drawer) {
                drawer.style.display = 'flex';
                document.getElementById('ai-chat-input')?.focus();
            }
        },
        close() {
            const drawer = document.getElementById('gboc-ai-drawer');
            if (drawer) drawer.style.display = 'none';
        },
        toggleConfig() {
            const modal = document.getElementById('gboc-ai-config-modal');
            if (!modal) return;
            modal.style.display = (modal.style.display === 'none' || !modal.style.display) ? 'flex' : 'none';
        },
        sendPreset(text) {
            const input = document.getElementById('ai-chat-input');
            if (input) {
                input.value = text;
                this.send();
            }
        },
        async send() {
            const input = document.getElementById('ai-chat-input');
            const msg = (input ? input.value : '').trim();
            if (!msg) return;

            const messages = document.getElementById('ai-chat-messages');
            if (!messages) return;

            messages.innerHTML += `<div style="align-self:flex-end;background:var(--primary,#4fa3e8);color:#fff;padding:9px 13px;border-radius:12px 12px 2px 12px;max-width:85%;word-break:break-word">${escapeHtml(msg)}</div>`;
            input.value = '';
            messages.scrollTop = messages.scrollHeight;

            const loadingId = 'loading-' + Date.now();
            messages.innerHTML += `<div id="${loadingId}" style="align-self:flex-start;background:var(--bg-card,#182035);border:1px solid var(--border,#2a3f5f);padding:9px 13px;border-radius:12px 12px 12px 2px;max-width:85%"><i class="fas fa-spinner fa-spin" style="color:var(--primary)"></i> Analisando...</div>`;
            messages.scrollTop = messages.scrollHeight;

            try {
                const r = await fetch(window.GBOC_API_BASE + '/api/v1/ai/query', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({prompt: msg})
                });
                const d = await r.json();
                document.getElementById(loadingId)?.remove();

                const ans = d.answer || 'Sem resposta do servidor de IA.';
                const prov = d.provider || 'GBOC AI';
                messages.innerHTML += `<div style="align-self:flex-start;background:var(--bg-card,#182035);border:1px solid var(--border,#2a3f5f);padding:11px 14px;border-radius:12px 12px 12px 2px;max-width:85%;line-height:1.45">
                    <div style="font-size:0.72em;color:var(--primary,#4fa3e8);margin-bottom:6px;font-weight:700"><i class="fas fa-robot"></i> ${escapeHtml(prov)}</div>
                    <div>${formatAiResponse(ans)}</div>
                </div>`;
                messages.scrollTop = messages.scrollHeight;
            } catch(e) {
                document.getElementById(loadingId)?.remove();
                messages.innerHTML += `<div style="align-self:flex-start;background:rgba(240,107,107,0.15);border:1px solid rgba(240,107,107,0.3);color:#f06b6b;padding:9px 13px;border-radius:12px">Erro de comunicação com o Copilot: ${escapeHtml(e.message)}</div>`;
            }
        },
        onProviderChange() {
            const val = document.getElementById('ai-provider-select')?.value;
            const fields = document.getElementById('ai-provider-fields');
            if (!fields) return;
            if (val === 'deepseek') {
                fields.innerHTML = `<div style="margin-top:10px"><label style="font-size:0.8em;color:var(--text-muted);display:block;margin-bottom:4px">DeepSeek API Key (Nuvem)</label><input type="password" id="cfg-deepseek-key" placeholder="sk-..." style="width:100%;padding:8px;background:var(--bg-input);border:1px solid var(--border);color:var(--text);border-radius:8px"><div style="margin-top:6px;font-size:0.78em"><a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener noreferrer" style="color:var(--primary,#4fa3e8);text-decoration:none;font-weight:600"><i class="fas fa-external-link-alt"></i> Obter API Key oficial do DeepSeek (platform.deepseek.com)</a></div></div>`;
            } else if (val === 'groq_free') {
                fields.innerHTML = `<div style="margin-top:10px"><label style="font-size:0.8em;color:var(--text-muted);display:block;margin-bottom:4px">Groq API Key (Gratuito)</label><input type="password" id="cfg-groq-key" placeholder="gsk_..." style="width:100%;padding:8px;background:var(--bg-input);border:1px solid var(--border);color:var(--text);border-radius:8px"><div style="margin-top:6px;font-size:0.78em"><a href="https://console.groq.com/keys" target="_blank" rel="noopener noreferrer" style="color:var(--primary,#4fa3e8);text-decoration:none;font-weight:600"><i class="fas fa-external-link-alt"></i> Obter API Key gratuita no Groq Cloud (console.groq.com)</a></div></div>`;
            } else if (val === 'gemini_free') {
                fields.innerHTML = `<div style="margin-top:10px"><label style="font-size:0.8em;color:var(--text-muted);display:block;margin-bottom:4px">Google Gemini API Key</label><input type="password" id="cfg-gemini-key" placeholder="AIzaSy..." style="width:100%;padding:8px;background:var(--bg-input);border:1px solid var(--border);color:var(--text);border-radius:8px"><div style="margin-top:6px;font-size:0.78em"><a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener noreferrer" style="color:var(--primary,#4fa3e8);text-decoration:none;font-weight:600"><i class="fas fa-external-link-alt"></i> Obter API Key gratuita no Google AI Studio (aistudio.google.com)</a></div></div>`;
            } else if (val === 'openai') {
                fields.innerHTML = `<div style="margin-top:10px"><label style="font-size:0.8em;color:var(--text-muted);display:block;margin-bottom:4px">OpenAI API Key</label><input type="password" id="cfg-openai-key" placeholder="sk-..." style="width:100%;padding:8px;background:var(--bg-input);border:1px solid var(--border);color:var(--text);border-radius:8px"><div style="margin-top:6px;font-size:0.78em"><a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer" style="color:var(--primary,#4fa3e8);text-decoration:none;font-weight:600"><i class="fas fa-external-link-alt"></i> Obter API Key na OpenAI (platform.openai.com)</a></div></div>`;
            } else {
                fields.innerHTML = `<div style="margin-top:10px"><label style="font-size:0.8em;color:var(--text-muted);display:block;margin-bottom:4px">URL Ollama Local</label><input type="text" id="cfg-ollama-url" value="http://localhost:11434" style="width:100%;padding:8px;background:var(--bg-input);border:1px solid var(--border);color:var(--text);border-radius:8px"><div style="margin-top:6px;font-size:0.78em"><a href="https://ollama.com/download" target="_blank" rel="noopener noreferrer" style="color:var(--primary,#4fa3e8);text-decoration:none;font-weight:600"><i class="fas fa-external-link-alt"></i> Baixar / Gerenciar Ollama Local (ollama.com)</a></div></div>`;
            }
        },
        async saveConfig() {
            const val = document.getElementById('ai-provider-select')?.value;
            const body = {provider: val};
            if (val === 'deepseek') {
                body.deepseek_api_key = document.getElementById('cfg-deepseek-key')?.value || '';
                body.api_key = body.deepseek_api_key;
            }
            if (val === 'groq_free') body.groq_api_key = document.getElementById('cfg-groq-key')?.value || '';
            if (val === 'gemini_free') body.gemini_api_key = document.getElementById('cfg-gemini-key')?.value || '';
            if (val === 'openai') body.openai_api_key = document.getElementById('cfg-openai-key')?.value || '';
            if (val === 'ollama_local') body.ollama_url = document.getElementById('cfg-ollama-url')?.value || 'http://localhost:11434';

            try {
                await fetch(window.GBOC_API_BASE + '/api/v1/ai/config', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body)
                });
                alert('Provedor de IA salvo com sucesso!');
                this.toggleConfig();
                loadAiConfigStatus();
            } catch(e) {
                alert('Erro ao salvar provedor de IA: ' + e.message);
            }
        }
    };

    function escapeHtml(str) {
        return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    function formatAiResponse(text) {
        let clean = escapeHtml(text);
        clean = clean.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        clean = clean.replace(/\n/g, '<br>');
        return clean;
    }
})();
