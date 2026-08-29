/*
==============================================================================
GBOC System v13.2.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
// ===================================
// MODAL DE PROGRESSO COM LOGS
// ===================================

class ProgressModal {
    constructor() {
        this.modal = null;
        this.logContainer = null;
        this.createModal();
    }
    
    createModal() {
        const modal = document.createElement('div');
        modal.id = 'progress-modal';
        modal.style.cssText = `
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.8);
            z-index: 9999;
            justify-content: center;
            align-items: center;
        `;
        
        modal.innerHTML = `
            <div style="
                background: #2d3748;
                border-radius: 12px;
                padding: 30px;
                max-width: 600px;
                width: 90%;
                max-height: 80vh;
                display: flex;
                flex-direction: column;
            ">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                    <h2 style="color: white; margin: 0; font-size: 20px;">
                        <span id="modal-icon">⏳</span>
                        <span id="modal-title">Processando...</span>
                    </h2>
                    <button id="modal-close" style="
                        background: none;
                        border: none;
                        color: white;
                        font-size: 24px;
                        cursor: pointer;
                        padding: 0;
                        width: 30px;
                        height: 30px;
                        display: none;
                    ">×</button>
                </div>
                
                <div id="progress-bar-container" style="
                    background: #1a202c;
                    border-radius: 8px;
                    height: 8px;
                    margin-bottom: 15px;
                    overflow: hidden;
                ">
                    <div id="progress-bar" style="
                        background: linear-gradient(90deg, #4299e1, #9f7aea);
                        height: 100%;
                        width: 0%;
                        transition: width 0.3s ease;
                    "></div>
                </div>
                
                <div style="
                    color: #a0aec0;
                    font-size: 14px;
                    margin-bottom: 15px;
                    text-align: center;
                " id="progress-text">Iniciando...</div>
                
                <div id="log-container" style="
                    background: #1a202c;
                    border-radius: 8px;
                    padding: 15px;
                    max-height: 300px;
                    overflow-y: auto;
                    font-family: 'Courier New', monospace;
                    font-size: 12px;
                    color: #cbd5e0;
                    flex: 1;
                ">
                    <div style="color: #4299e1;">[SYNC] Aguardando início...</div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        this.modal = modal;
        this.logContainer = modal.querySelector('#log-container');
        
        modal.querySelector('#modal-close').onclick = () => this.hide();
    }
    
    show(title = 'Processando...') {
        this.modal.style.display = 'flex';
        this.modal.querySelector('#modal-title').textContent = title;
        this.modal.querySelector('#modal-icon').textContent = '⏳';
        this.modal.querySelector('#progress-bar').style.width = '0%';
        this.modal.querySelector('#progress-text').textContent = 'Iniciando...';
        this.modal.querySelector('#modal-close').style.display = 'none';
        this.logContainer.innerHTML = '<div style="color: #4299e1;">[SYNC] Aguardando início...</div>';
    }
    
    hide() {
        this.modal.style.display = 'none';
    }
    
    setProgress(percent, text = '') {
        this.modal.querySelector('#progress-bar').style.width = percent + '%';
        if (text) {
            this.modal.querySelector('#progress-text').textContent = text;
        }
    }
    
    addLog(message, type = 'info') {
        const colors = {
            success: '#48bb78',
            error: '#f56565',
            warning: '#ed8936',
            info: '#4299e1'
        };
        
        const icons = {
            success: '✅',
            error: '❌',
            warning: '⚠️',
            info: 'ℹ️'
        };
        
        const log = document.createElement('div');
        log.style.cssText = `
            color: ${colors[type] || colors.info};
            margin-bottom: 5px;
            padding: 3px 0;
            border-bottom: 1px solid #2d3748;
        `;
        log.textContent = `${icons[type] || icons.info} ${message}`;
        
        this.logContainer.appendChild(log);
        this.logContainer.scrollTop = this.logContainer.scrollHeight;
    }
    
    complete(success = true, message = '') {
        const icon = success ? '✅' : '❌';
        const title = success ? 'Concluído!' : 'Erro';
        
        this.modal.querySelector('#modal-icon').textContent = icon;
        this.modal.querySelector('#modal-title').textContent = title;
        this.modal.querySelector('#progress-bar').style.width = '100%';
        this.modal.querySelector('#progress-text').textContent = message || (success ? 'Processo concluído com sucesso' : 'Processo finalizado com erros');
        this.modal.querySelector('#modal-close').style.display = 'block';
        
        if (success) {
            this.modal.querySelector('#progress-bar').style.background = '#48bb78';
        } else {
            this.modal.querySelector('#progress-bar').style.background = '#f56565';
        }
    }
}

// Instanciar globalmente
window.progressModal = new ProgressModal();

// ===================================
// EXEMPLO DE USO: Importação
// ===================================

async function scanAndImportWithProgress() {
    if (!confirm('Importar dados dos engines pode demorar alguns minutos.\n\nDeseja continuar?')) {
        return false;
    }
    
    // Mostrar modal
    progressModal.show('Importando Dados');
    progressModal.setProgress(10, 'Conectando ao servidor...');
    progressModal.addLog('Iniciando processo de importação...', 'info');
    
    try {
        progressModal.setProgress(20, 'Escaneando repositórios...');
        progressModal.addLog('Buscando repositórios configurados...', 'info');
        
        const response = await fetch('/api/import/scan-and-import', {
            method: 'POST',
            headers: { 'Accept': 'application/json' }
        });
        
        progressModal.setProgress(50, 'Processando dados...');
        
        if (response.ok) {
            const data = await response.json();
            
            progressModal.setProgress(80, 'Finalizando...');
            progressModal.addLog(`Repositórios: ${data.results?.repositories_imported || 0}`, 'success');
            progressModal.addLog(`Snapshots: ${data.results?.snapshots_imported || 0}`, 'success');
            
            progressModal.setProgress(100, 'Importação concluída!');
            progressModal.complete(true, `${data.results?.repositories_imported || 0} repositórios importados`);
            
            // Recarregar dados após 2 segundos
            setTimeout(() => {
                if (window.app) window.app.loadInitialData();
                progressModal.hide();
            }, 2000);
        } else {
            throw new Error(`HTTP ${response.status}`);
        }
    } catch (error) {
        progressModal.addLog(`Erro: ${error.message}`, 'error');
        progressModal.complete(false, 'Falha na importação');
        console.error('❌ Erro ao importar:', error);
    }
    
    return false;
}
