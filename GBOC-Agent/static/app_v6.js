/*
==============================================================================
GBOC System v14.0.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
// ====================================================================
// GBOC Agent 14.0.0 - JavaScript DEFINITIVO
// Detecta página automaticamente e evita erros
// ====================================================================

console.log('🚀 GBOC Agent 14.0.0 - JavaScript carregando...');

// ====================================================================
// DETECTAR PÁGINA ATUAL
// ====================================================================

const PAGINA_ATUAL = (() => {
    const path = window.location.pathname;
    if (path.includes('repositories')) return 'repositories';
    if (path.includes('tasks')) return 'tasks';
    if (path.includes('logs')) return 'logs';
    return 'dashboard';
})();

console.log(`📄 Página detectada: ${PAGINA_ATUAL}`);

// ====================================================================
// CLASSE PRINCIPAL
// ====================================================================

class GBOCApp {
    constructor() {
        this.isInitialized = false;
        this.retryCount = 0;
        this.maxRetries = 3;
        this.pagina = PAGINA_ATUAL;
        
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.init());
        } else {
            this.init();
        }
    }
    
    init() {
        console.log(`📄 Inicializando GBOC App (${this.pagina})...`);
        
        try {
            // Carregar dados específicos da página
            if (this.pagina === 'dashboard') {
                this.loadDashboardData();
                this.startAutoRefresh();
            }
            
            this.startClock();
            this.isInitialized = true;
            console.log('✅ GBOC App inicializado com sucesso');
            
        } catch (error) {
            console.error('❌ Erro na inicialização:', error);
        }
    }
    
    // ====================================================================
    // DASHBOARD
    // ====================================================================
    
    async loadDashboardData() {
        if (this.pagina !== 'dashboard') return;
        
        console.log('📊 Carregando dados do dashboard...');
        
        try {
            const response = await fetch('/api/overview/');
            const data = await response.json();
            
            console.log('📦 Dados recebidos:', data);
            
            // Métricas do sistema
            this.safeUpdate('cpuUsage', data.metrics?.cpu_percent ? data.metrics.cpu_percent.toFixed(0) + '%' : '-');
            this.safeUpdate('memoryUsage', data.metrics?.memory_percent ? data.metrics.memory_percent.toFixed(0) + '%' : '-');
            this.safeUpdate('diskUsage', data.metrics?.disk_percent ? data.metrics.disk_percent.toFixed(0) + '%' : '-');
            this.safeUpdate('diskDetail', data.metrics?.disk_free_gb ? `${data.metrics.disk_free_gb} GB livres` : '');
            this.safeUpdate('systemHealth', data.metrics?.health_score ?? '-');
            
            // Contadores
            this.safeUpdate('repositoryCount', data.counters?.repositories ?? 0);
            this.safeUpdate('taskCount', data.counters?.tasks ?? 0);
            this.safeUpdate('totalBackups', data.counters?.executions_today ?? 0);
            
            // Dados de backup
            const backupSize = data.counters?.total_backup_size_gb;
            this.safeUpdate('backupDataTotal', backupSize ? `${backupSize} GB` : '0 GB');
            
            // Engines
            this.safeUpdate('engineCount', data.engines_status?.installed ?? 0);
            
            // Sistema
            this.safeUpdate('localIp', data.system?.hostname || '-');
            this.safeUpdate('sys-plat', data.system?.platform || data.system?.os || '-');
            
            // Server sync - converter objeto para string
            const syncStatus = data.server_sync?.connected ? 'Online' : 'Offline';
            this.safeUpdate('serverSync', syncStatus);
            
            // Atualizar status do backup
            this.safeUpdate('backupStatus', 'Aguardando');
            
        } catch (error) {
            console.error('❌ Erro ao carregar dashboard:', error);
        }
    }
    
    // ====================================================================
    // HELPER: Atualizar elemento com segurança
    // ====================================================================
    
    safeUpdate(elementId, value) {
        const element = document.getElementById(elementId);
        
        if (!element) {
            // NÃO exibir erro, apenas ignorar silenciosamente
            return;
        }
        
        if (value === undefined || value === null) {
            element.textContent = '-';
            return;
        }
        
        element.textContent = value;
    }
    
    // ====================================================================
    // AUTO-REFRESH (APENAS DASHBOARD)
    // ====================================================================
    
    startAutoRefresh() {
        if (this.pagina !== 'dashboard') return;
        
        console.log('[SYNC] Auto-refresh iniciado (30s)...');
        
        setInterval(() => {
            this.loadDashboardData();
        }, 30000); // 30 segundos
    }
    
    // ====================================================================
    // RELÓGIO
    // ====================================================================
    
    startClock() {
        const updateClock = () => {
            const now = new Date();
            const timeStr = now.toLocaleTimeString('pt-BR');
            this.safeUpdate('currentTime', timeStr);
        };
        
        updateClock();
        setInterval(updateClock, 1000);
    }
}

// ====================================================================
// INICIALIZAR
// ====================================================================

const gbocApp = new GBOCApp();

// ====================================================================
// FUNÇÕES GLOBAIS PARA COMPATIBILIDADE
// ====================================================================

// Função para recarregar dados (chamada por botões)
window.reloadData = function() {
    if (gbocApp.pagina === 'dashboard') {
        gbocApp.loadDashboardData();
    }
};

// Função para executar backup (exemplo)
window.runBackup = function(taskId) {
    console.log(`▶️ Executando backup da tarefa ${taskId}...`);
    // TODO: Implementar chamada à API
};

console.log('✅ GBOC Agent 14.0.0 JavaScript carregado com sucesso');

// === CHECK PASSWORD STRENGTH (moved from repositories.html) ===
window.checkPasswordStrength = function(password) {
    const strengthBar = document.getElementById('password_strength');
    if (!strengthBar) return;

    let strength = 0;
    if (password.length >= 8) strength++;
    if (password.length >= 12) strength++;
    if (/[a-z]/.test(password) && /[A-Z]/.test(password)) strength++;
    if (/[0-9]/.test(password)) strength++;
    if (/[^a-zA-Z0-9]/.test(password)) strength++;

    strengthBar.className = 'password-strength';
    if (strength <= 2) {
        strengthBar.classList.add('weak');
    } else if (strength <= 4) {
        strengthBar.classList.add('medium');
    } else {
        strengthBar.classList.add('strong');
    }
};

// Attach input listener to the create password field if present
document.addEventListener('DOMContentLoaded', async function() {
    const pwd = document.getElementById('create_password');
    if (pwd) {
        pwd.addEventListener('input', function(e) {
            try { window.checkPasswordStrength(e.target.value); } catch (err) { /* noop */ }
        });
    }
});

// Nota: Sidebar management foi movido para sidebar.js dedicado
// Removidas as funções antigas: loadUnifiedSidebar, updateActiveSidebarLink, initializeUnifiedSidebar

// ====================================================================
// THEME TOGGLE FUNCTIONALITY
// ====================================================================

function toggleTheme() {
    const body = document.body;
    const themeIcon = document.querySelector('#themeToggle i');

    if (body.classList.contains('dark-mode')) {
        body.classList.remove('dark-mode');
        themeIcon.classList.remove('fa-sun');
        themeIcon.classList.add('fa-moon');
        localStorage.setItem('theme', 'light');
    } else {
        body.classList.add('dark-mode');
        themeIcon.classList.remove('fa-moon');
        themeIcon.classList.add('fa-sun');
        localStorage.setItem('theme', 'dark');
    }
}

// Load saved theme on page load
document.addEventListener('DOMContentLoaded', function() {
    const savedTheme = localStorage.getItem('theme');
    const themeIcon = document.querySelector('#themeToggle i');

    if (savedTheme === 'dark') {
        document.body.classList.add('dark-mode');
        if (themeIcon) {
            themeIcon.classList.remove('fa-moon');
            themeIcon.classList.add('fa-sun');
        }
    }
});

// ====================================================================
// PROGRESS INDICATORS
// ====================================================================

class ProgressIndicator {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.progressBar = null;
        this.progressText = null;
        this.createProgressElement();
    }

    createProgressElement() {
        if (!this.container) return;

        // Create progress container
        const progressContainer = document.createElement('div');
        progressContainer.className = 'progress-container';

        // Create progress bar
        const progressBar = document.createElement('div');
        progressBar.className = 'progress-bar';

        const progressFill = document.createElement('div');
        progressFill.className = 'progress-fill';
        progressFill.style.width = '0%';

        progressBar.appendChild(progressFill);

        // Create progress text
        const progressText = document.createElement('div');
        progressText.className = 'progress-text';
        progressText.textContent = '0%';

        progressContainer.appendChild(progressBar);
        progressContainer.appendChild(progressText);

        this.container.appendChild(progressContainer);
        this.progressBar = progressFill;
        this.progressText = progressText;
    }

    updateProgress(percent, text = null) {
        if (!this.progressBar || !this.progressText) return;

        const clampedPercent = Math.max(0, Math.min(100, percent));
        this.progressBar.style.width = `${clampedPercent}%`;
        this.progressText.textContent = text || `${clampedPercent}%`;
    }

    show() {
        if (this.container) {
            this.container.style.display = 'block';
        }
    }

    hide() {
        if (this.container) {
            this.container.style.display = 'none';
        }
    }

    complete() {
        this.updateProgress(100, 'Concluído');
        setTimeout(() => this.hide(), 2000);
    }
}

// Global progress indicator for operations
let globalProgressIndicator = null;

function createGlobalProgressIndicator() {
    // Create a global progress container
    const progressContainer = document.createElement('div');
    progressContainer.id = 'global-progress';
    progressContainer.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 1000;
        min-width: 300px;
        display: none;
    `;

    document.body.appendChild(progressContainer);
    globalProgressIndicator = new ProgressIndicator('global-progress');
}

function showGlobalProgress(percent, text) {
    if (!globalProgressIndicator) {
        createGlobalProgressIndicator();
    }
    globalProgressIndicator.updateProgress(percent, text);
    globalProgressIndicator.show();
}

function hideGlobalProgress() {
    if (globalProgressIndicator) {
        globalProgressIndicator.hide();
    }
}

// Initialize global progress on page load
document.addEventListener('DOMContentLoaded', function() {
    createGlobalProgressIndicator();
});



