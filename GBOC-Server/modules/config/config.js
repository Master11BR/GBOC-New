// ==============================================================================
// GBOC System v14.0.0 Enterprise Edition
// Module: Config & IA & LLMs Controller (config.js)
// ==============================================================================

document.addEventListener('DOMContentLoaded', () => {
    loadServerAIConfigUI();
});

function switchConfigSubTab(sub, btn) {
    document.querySelectorAll('.cfg-subtab-pane').forEach(p => p.style.display = 'none');
    document.querySelectorAll('#srv-config-subtabs .tab-btn').forEach(b => b.classList.remove('active'));
    const target = document.getElementById('cfg-subtab-' + sub);
    if (target) target.style.display = 'block';
    if (btn) btn.classList.add('active');
    if (sub === 'ai') loadServerAIConfigUI();
}

async function loadServerAIConfigUI() {
    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/ai/config');
        if (!r.ok) return;
        const data = await r.json();
        const cfg = data.config || {};
        
        if (document.getElementById('ai-provider')) document.getElementById('ai-provider').value = cfg.provider || 'ollama';
        if (document.getElementById('ai-ollama-host')) document.getElementById('ai-ollama-host').value = cfg.ollama_url || cfg.ollama_host || 'http://localhost:11434';
        if (document.getElementById('ai-model')) document.getElementById('ai-model').value = cfg.model || cfg.ollama_model || 'llama3';
        if (document.getElementById('ai-api-key')) document.getElementById('ai-api-key').value = cfg.api_key || cfg.openai_api_key || cfg.groq_api_key || cfg.gemini_api_key || '';
        if (document.getElementById('task-history-limit')) document.getElementById('task-history-limit').value = cfg.task_history_limit || 10;
        
        toggleAiFields();
        detectOllamaModels();
    } catch (e) {
        console.error('loadServerAIConfigUI error:', e);
    }
}

function toggleAiFields() {
    const provider = document.getElementById('ai-provider').value;
    const ollamaGroup = document.getElementById('group-ollama-host');
    const apiKeyGroup = document.getElementById('group-api-key');
    const modelInput = document.getElementById('ai-model');
    const apiKeyLinkDiv = document.getElementById('ai-api-key-link');

    const defaultModels = {
        ollama: 'llama3',
        kimi: 'moonshot-v1-8k',
        grok: 'grok-2',
        openai: 'gpt-4o-mini',
        gemini: 'gemini-1.5-flash',
        deepseek: 'deepseek-chat',
        claude: 'claude-3-5-sonnet-20241022',
        qwen: 'qwen2.5',
        mistral: 'mistral-large-latest',
        llama3: 'llama3.3:70b',
        cohere: 'command-r-plus'
    };

    const providerKeyLinks = {
        deepseek: { url: 'https://platform.deepseek.com/api_keys', label: '🔗 Clique aqui para gerar sua API Key no portal DeepSeek (platform.deepseek.com/api_keys)' },
        openai: { url: 'https://platform.openai.com/api-keys', label: '🔗 Clique aqui para gerar sua API Key na OpenAI (platform.openai.com/api-keys)' },
        gemini: { url: 'https://aistudio.google.com/app/apikey', label: '🔗 Clique aqui para gerar sua API Key gratuita no Google AI Studio (aistudio.google.com)' },
        groq_free: { url: 'https://console.groq.com/keys', label: '🔗 Clique aqui para gerar sua API Key gratuita no Groq Cloud (console.groq.com/keys)' },
        claude: { url: 'https://console.anthropic.com/settings/keys', label: '🔗 Clique aqui para gerar sua API Key no Anthropic Claude (console.anthropic.com)' },
        kimi: { url: 'https://platform.moonshot.cn/console/api-keys', label: '🔗 Clique aqui para gerar sua API Key no Kimi Moonshot (platform.moonshot.cn)' },
        grok: { url: 'https://console.x.ai/', label: '🔗 Clique aqui para gerar sua API Key no Grok xAI (console.x.ai)' },
        mistral: { url: 'https://console.mistral.ai/api-keys/', label: '🔗 Clique aqui para gerar sua API Key no Mistral AI (console.mistral.ai)' },
        cohere: { url: 'https://dashboard.cohere.com/api-keys', label: '🔗 Clique aqui para gerar sua API Key no Cohere (dashboard.cohere.com)' }
    };

    if (modelInput && defaultModels[provider]) {
        modelInput.placeholder = `Ex: ${defaultModels[provider]}`;
    }

    if (apiKeyLinkDiv) {
        const linkInfo = providerKeyLinks[provider];
        if (linkInfo) {
            apiKeyLinkDiv.innerHTML = `<a href="${linkInfo.url}" target="_blank" rel="noopener noreferrer" style="color:var(--primary,#4fa3e8);text-decoration:none;font-weight:600"><i class="fas fa-external-link-alt" style="margin-right:4px"></i> ${linkInfo.label}</a>`;
        } else {
            apiKeyLinkDiv.innerHTML = '';
        }
    }

    if (provider === 'ollama' || provider === 'qwen' || provider === 'llama3') {
        if (ollamaGroup) ollamaGroup.style.display = 'block';
        if (apiKeyGroup) apiKeyGroup.style.display = 'none';
    } else {
        if (ollamaGroup) ollamaGroup.style.display = 'none';
        if (apiKeyGroup) apiKeyGroup.style.display = 'block';
    }
}

let gInstalledModels = [];
let gRecommendedModels = [
    "llama3:latest", "llama3.2:latest", "llama3.3:70b", "mistral:latest",
    "deepseek-r1:latest", "deepseek-r1:1.5b", "qwen2.5:latest", "gemma2:latest",
    "codellama:latest", "phi3:latest"
];

function updateModelDropdownUI(installed, recommended, currentVal) {
    const select = document.getElementById('ai-model-select');
    if (!select) return;
    gInstalledModels = installed || [];
    const recs = recommended || gRecommendedModels;

    let html = '';

    if (gInstalledModels.length > 0) {
        html += `<optgroup label="🟢 Modelos Instalados Localmente (Prontos para Diagnóstico)">`;
        gInstalledModels.forEach(m => {
            html += `<option value="${m}">🟢 ${m} (Instalado - Pronto)</option>`;
        });
        html += `</optgroup>`;
    }

    const availableNotInstalled = recs.filter(m => !gInstalledModels.includes(m));
    if (availableNotInstalled.length > 0) {
        html += `<optgroup label="☁️ Modelos Disponíveis na Nuvem / Library (Requer 'ollama pull')">`;
        availableNotInstalled.forEach(m => {
            html += `<option value="${m}">☁️ ${m} (Não Instalado - Requer 'ollama pull')</option>`;
        });
        html += `</optgroup>`;
    }

    select.innerHTML = html;

    const valToSet = currentVal || (gInstalledModels.length > 0 ? gInstalledModels[0] : recs[0]);
    select.value = valToSet;
    document.getElementById('ai-model').value = valToSet;
    onModelSelectChanged(valToSet);
}

function onModelSelectChanged(val) {
    document.getElementById('ai-model').value = val;
    const badge = document.getElementById('model-status-badge');
    if (!badge) return;

    if (gInstalledModels.includes(val)) {
        badge.style.cssText = 'font-size:0.83em;padding:6px 10px;border-radius:6px;background:rgba(72,187,120,0.15);color:#48bb78;border:1px solid rgba(72,187,120,0.3);margin-top:4px';
        badge.innerHTML = `<i class="fas fa-check-circle"></i> Modelo <strong>${val}</strong> está INSTALADO no Ollama e pronto para uso imediato!`;
    } else {
        badge.style.cssText = 'font-size:0.83em;padding:6px 10px;border-radius:6px;background:rgba(240,169,64,0.15);color:var(--warning);border:1px solid rgba(240,169,64,0.3);margin-top:4px';
        badge.innerHTML = `<i class="fas fa-exclamation-triangle"></i> Modelo <strong>${val}</strong> NÃO ESTÁ INSTALADO.<br>` +
            `<button type="button" class="btn btn-sm btn-primary" style="margin-top:6px;padding:4px 8px;font-size:0.85em" onclick="pullOllamaModel('${val}')"><i class="fas fa-download"></i> Instalar Modelo Automaticamente</button>`;
    }
}

async function pullOllamaModel(modelName) {
    const host = document.getElementById('ai-ollama-host').value || 'http://localhost:11434';
    if(!confirm(`Deseja iniciar o download do modelo "${modelName}" no Ollama do Servidor?\nIsso será feito em segundo plano pelo servidor central.`)) return;
    
    const btn = document.querySelector(`button[onclick="pullOllamaModel('${modelName}')"]`);
    if(btn) {
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Iniciando Instalação...';
        btn.disabled = true;
    }
    
    try {
        const res = await fetch(window.GBOC_API_BASE + '/api/v1/ai/ollama/models/pull', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({host: host, model: modelName})
        });
        const data = await res.json();
        if(data.status === 'downloading' || data.status === 'success') {
            alert(`✅ Instalação iniciada em segundo plano no servidor!\n\nClique em "Detectar IA Local" em alguns instantes para conferir se a instalação terminou.`);
        } else {
            alert(`❌ Erro ao baixar o modelo: ${data.message || 'Erro desconhecido'}`);
        }
    } catch(e) {
        alert(`❌ Falha na comunicação com o servidor: ${e.message}`);
    } finally {
        if(btn) {
            btn.innerHTML = '<i class="fas fa-download"></i> Instalar Modelo Automaticamente';
            btn.disabled = false;
        }
    }
}

async function detectOllamaModels() {
    const host = document.getElementById('ai-ollama-host').value || 'http://localhost:11434';
    const currentModel = document.getElementById('ai-model').value;
    const select = document.getElementById('ai-model-select');
    if (select) {
        select.innerHTML = '<option value="">Buscando no host...</option>';
    }

    try {
        const r = await fetch(window.GBOC_API_BASE + `/api/v1/ai/ollama/models?host=${encodeURIComponent(host)}`);
        const data = await r.json();
        
        if (data.connected && data.installed_models) {
            updateModelDropdownUI(data.installed_models, gRecommendedModels, currentModel);
        } else {
            updateModelDropdownUI([], gRecommendedModels, currentModel);
        }
    } catch (e) {
        console.error('Falha ao detectar modelos:', e);
        updateModelDropdownUI([], gRecommendedModels, currentModel);
    }
}

async function testAiConnection() {
    const btn = document.getElementById('btn-test-ai');
    const ogHtml = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Testando...';
    btn.disabled = true;

    // Remove old message
    const oldMsg = document.getElementById('cfg-ai-msg-toast');
    if(oldMsg) oldMsg.remove();

    try {
        const provider = document.getElementById('ai-provider').value;
        const host = document.getElementById('ai-ollama-host').value;
        const api_key = document.getElementById('ai-api-key').value;
        const model = document.getElementById('ai-model').value;

        // Save temporarily to backend config to test
        await saveAiSettings(true); 

        const r = await fetch(window.GBOC_API_BASE + '/api/v1/ai/diagnose', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({error_context: 'Teste de conexão configurada.', provider: provider})
        });
        
        const data = await r.json();
        const msgDiv = document.createElement('div');
        msgDiv.id = 'cfg-ai-msg-toast';
        msgDiv.style.marginTop = '15px';
        msgDiv.style.padding = '12px 16px';
        msgDiv.style.borderRadius = '8px';
        msgDiv.style.fontSize = '0.9em';

        if (data.result && data.result.is_llm_real) {
            msgDiv.style.backgroundColor = 'rgba(72,187,120,0.15)';
            msgDiv.style.color = '#48bb78';
            msgDiv.style.border = '1px solid rgba(72,187,120,0.3)';
            msgDiv.innerHTML = `<i class="fas fa-check-circle"></i> Conexão bem sucedida com <strong>${provider}</strong>!<br><span style="font-size:0.85em;opacity:0.8;display:block;margin-top:6px">${data.result.analysis}</span>`;
        } else {
            msgDiv.style.backgroundColor = 'rgba(245,101,101,0.15)';
            msgDiv.style.color = 'var(--danger)';
            msgDiv.style.border = '1px solid rgba(245,101,101,0.3)';
            msgDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> Falha na conexão.<br><span style="font-size:0.85em;opacity:0.8;display:block;margin-top:6px">${data.result?.analysis || data.message || 'Erro desconhecido.'}</span>`;
        }
        document.getElementById('cfg-subtab-ai').querySelector('.panel').appendChild(msgDiv);
    } catch(e) {
        alert('Erro ao testar IA: ' + e.message);
    } finally {
        btn.innerHTML = ogHtml;
        btn.disabled = false;
    }
}

async function saveAiSettings(silent=false) {
    const btn = document.getElementById('btn-save-ai');
    const ogHtml = btn.innerHTML;
    if(!silent) {
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Salvando...';
        btn.disabled = true;
    }

    const cfg = {
        provider: document.getElementById('ai-provider').value,
        ollama_url: document.getElementById('ai-ollama-host').value,
        ollama_host: document.getElementById('ai-ollama-host').value,
        model: document.getElementById('ai-model').value,
        ollama_model: document.getElementById('ai-model').value,
        api_key: document.getElementById('ai-api-key').value,
        deepseek_api_key: document.getElementById('ai-api-key').value,
        groq_api_key: document.getElementById('ai-api-key').value,
        openai_api_key: document.getElementById('ai-api-key').value,
        gemini_api_key: document.getElementById('ai-api-key').value,
        task_history_limit: parseInt(document.getElementById('task-history-limit').value || '10')
    };

    try {
        await fetch(window.GBOC_API_BASE + '/api/v1/ai/config', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify(cfg)
        });
        if(!silent) {
            alert('Configuração de IA salva com sucesso!');
        }
    } catch(e) {
        if(!silent) alert('Erro ao salvar IA: ' + e.message);
    } finally {
        if(!silent) {
            btn.innerHTML = ogHtml;
            btn.disabled = false;
        }
    }
}
