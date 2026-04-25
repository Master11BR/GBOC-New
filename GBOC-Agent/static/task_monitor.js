// ====================================================================
// DETECTAR PÁGINA ATUAL
// ====================================================================

const PAGINA_ATUAL = (() => {
    const path = window.location.pathname;

    if (path.includes('repositories')) return 'repositories';
    if (path.includes('tasks')) return 'tasks';
    if (path.includes('restore')) return 'restore';
    if (path.includes('logs')) return 'logs';
    if (path.includes('overview')) return 'overview';
    if (path.includes('statistics')) return 'statistics';
    if (path.includes('settings')) return 'settings';

    return 'dashboard';
})();

// ===================================
// MONITOR DE TAREFAS EM EXECUÇÃO
// ===================================

class TaskMonitor {
    constructor() {
        this.runningTasks = new Map();
        this.checkInterval = null;
        this.ws = null;
        this.wsReconnectTimer = null;
        this.useWebSocket = false;
    }
    
    async startTask(taskId, taskName) {
        // Registrar tarefa
        this.runningTasks.set(taskId, {
            name: taskName,
            startTime: Date.now(),
            toastId: null,
            executionId: null,
            lastProgress: -1
        });
        
        // Mostrar notificação
        const toastId = toast.show(
            `Executando: ${taskName}`,
            'loading',
            0 // Sem auto-close
        );
        
        this.runningTasks.get(taskId).toastId = toastId;
        
        // Iniciar monitoramento se ainda não estiver rodando
        if (!this.checkInterval && !this.useWebSocket) {
            this.startMonitoring();
        }
        this.connectWebSocket();
        
        // Fazer requisição para executar tarefa
        try {
            const response = await fetch(`/api/tasks/${taskId}/run`, {
                method: 'POST'
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const result = await response.json();
            if (result && result.execution_id && this.runningTasks.has(taskId)) {
                this.runningTasks.get(taskId).executionId = result.execution_id;
            }
            return result;
            
        } catch (error) {
            this.taskFailed(taskId, error.message);
            throw error;
        }
    }

    connectWebSocket() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        try {
            const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            this.ws = new WebSocket(`${wsProto}//${window.location.host}/ws`);

            this.ws.onopen = () => {
                this.useWebSocket = true;
                if (this.checkInterval) {
                    clearInterval(this.checkInterval);
                    this.checkInterval = null;
                }
            };

            this.ws.onmessage = (evt) => {
                try {
                    const msg = JSON.parse(evt.data || '{}');
                    const event = msg.event;
                    const data = msg.data || {};
                    if (!event) return;

                    if (event === 'backup_progress') {
                        const task = this.runningTasks.get(data.task_id);
                        if (task && typeof data.progress === 'number' && data.progress !== task.lastProgress) {
                            task.lastProgress = data.progress;
                            if (task.toastId) {
                                toast.update(task.toastId, `⏳ ${task.name}: ${data.progress}% ${data.current_file || ''}`, 'loading');
                            }
                        }
                    }

                    if (event === 'backup_completed') {
                        const taskId = data.task_id;
                        if (data.success) {
                            this.taskCompleted(taskId, data);
                        } else {
                            this.taskFailed(taskId, data.error || 'Falha no backup');
                        }
                    }
                } catch (_) {}
            };

            this.ws.onclose = () => {
                this.useWebSocket = false;
                if (!this.checkInterval) {
                    this.startMonitoring();
                }
                if (this.wsReconnectTimer) clearTimeout(this.wsReconnectTimer);
                this.wsReconnectTimer = setTimeout(() => this.connectWebSocket(), 3000);
            };

            this.ws.onerror = () => {
                this.useWebSocket = false;
            };
        } catch (_) {
            this.useWebSocket = false;
            if (!this.checkInterval) this.startMonitoring();
        }
    }
    
    startMonitoring() {
        // Poll único e leve: evita N chamadas por tarefa
        this.checkInterval = setInterval(() => {
            this.checkRunningTasks();
        }, 2500);
    }
    
    async checkRunningTasks() {
        if (this.runningTasks.size === 0) {
            if (this.checkInterval) {
                clearInterval(this.checkInterval);
                this.checkInterval = null;
            }
            return false;
        }

        try {
            const response = await fetch('/api/tasks/running/detailed');
            if (!response.ok) return true;

            const data = await response.json();
            const executions = Array.isArray(data.executions) ? data.executions : [];
            const activeByTask = new Map(executions.map(e => [e.task_id, e]));

            for (const [taskId, task] of this.runningTasks) {
                const live = activeByTask.get(taskId);
                if (live) {
                    const progress = Number(live.progress || 0);
                    if (task.toastId && progress !== task.lastProgress) {
                        task.lastProgress = progress;
                        toast.update(task.toastId, `⏳ ${task.name}: ${progress}% ${live.current_file || ''}`, 'loading');
                    }
                    continue;
                }

                // Não está mais em execução: consultar status final uma vez
                if (task.executionId) {
                    try {
                        const statusResp = await fetch(`/api/tasks/execution/${task.executionId}`);
                        const statusData = await statusResp.json();
                        if (statusData.status === 'completed') {
                            this.taskCompleted(taskId, statusData);
                        } else if (statusData.status === 'failed') {
                            this.taskFailed(taskId, statusData.error_message || statusData.message || 'Falha');
                        }
                    } catch (_) {}
                }
            }
        } catch (error) {
            console.error('Erro no monitoramento de tarefas:', error);
        }

        return this.runningTasks.size > 0;
    }
}

// Instanciar globalmente
window.taskMonitor = new TaskMonitor();

// ===================================
// EXEMPLO DE USO: Executar Tarefa
// ===================================

async function executeTask(taskId, taskName) {
    try {
        console.log(`[SYNC] Executando tarefa: ${taskName} (ID: ${taskId})`);
        
        // Iniciar monitoramento
        const result = await taskMonitor.startTask(taskId, taskName);
        
        console.log('✅ Tarefa iniciada:', result);
        return result;
        
    } catch (error) {
        console.error('❌ Erro ao executar tarefa:', error);
        toast.show(`Erro ao executar ${taskName}`, 'error');
    }
}

// ===================================
// INTEGRAÇÃO COM BOTÃO "EXECUTAR"
// ===================================

// Na página tasks.html, modificar botão de executar:
/*
<button onclick="executeTask(123, 'Backup Diário'); return false;">
    Executar Backup
</button>
*/

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
