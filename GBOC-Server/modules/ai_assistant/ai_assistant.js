// Module: AI Assistant Controller (ai_assistant.js)
async function sendAIChatQuery() {
    const input = document.getElementById('ai-chat-input');
    const out = document.getElementById('ai-chat-output');
    if (!input || !input.value.trim()) return;
    const prompt = input.value.trim();
    input.value = '';

    const userDiv = document.createElement('div');
    userDiv.style.margin = '10px 0';
    userDiv.style.textAlign = 'right';
    userDiv.innerHTML = `<strong>Você:</strong> ${prompt}`;
    out.appendChild(userDiv);

    const botDiv = document.createElement('div');
    botDiv.style.margin = '10px 0';
    botDiv.innerHTML = `🤖 <strong>GBOC Copilot:</strong> <i class="fas fa-spinner fa-spin"></i> Pensando...`;
    out.appendChild(botDiv);
    out.scrollTop = out.scrollHeight;

    try {
        const r = await fetch(window.GBOC_API_BASE + '/api/v1/ai/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: prompt })
        });
        const data = await r.json();
        botDiv.innerHTML = `🤖 <strong>GBOC Copilot (${data.provider || 'AI'}):</strong> ${data.answer || data.message}`;
    } catch (e) {
        botDiv.innerHTML = `🤖 <strong>GBOC Copilot:</strong> Desculpe, ocorreu um erro ao consultar a IA: ${e.message}`;
    }
    out.scrollTop = out.scrollHeight;
}
