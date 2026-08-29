#!/usr/bin/env python3
"""
==============================================================================
GBOC System v13.2.0 Enterprise Edition
Autonomous Scheduler Agent & Background Task Runner
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
==============================================================================
Serviço autônomo em background responsável por executar rotinas agendadas
de backup, restauração, SureRestore e retenção independente de usuário logado.
"""

import os
import sys
import time
import signal
import logging
from datetime import datetime

# Configuração de encoding UTF-8 no Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Garante inclusão do diretório do agente no PATH
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

# Configuração de logging
LOGS_DIR = os.path.join(AGENT_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOGS_DIR, "gboc_scheduler.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a")
    ]
)
logger = logging.getLogger("gboc_scheduler_daemon")

_RUNNING = True

def _handle_signal(signum, frame):
    global _RUNNING
    sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
    logger.info(f"🛑 Sinal de finalização recebido ({sig_name}). Encerrando GBOC Scheduler Agent de forma segura...")
    _RUNNING = False

def print_banner():
    banner = r"""
======================================================================
  GBOC System v13.2.0 - Agente de Inicializacao do Scheduler
  Servico Autonomo de Backup & Restore Agendados (Zero-Mock)
======================================================================
    """
    print(banner)
    logger.info("🚀 Iniciando GBOC Scheduler Agent (System Context)...")
    logger.info(f"📁 Diretório Base: {AGENT_DIR}")
    logger.info(f"📝 Arquivo de Log: {LOG_FILE}")

def main():
    global _RUNNING

    # Registrar tratadores de sinal
    try:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
    except Exception as e:
        logger.warning(f"Aviso ao registrar sinais do SO: {e}")

    print_banner()

    # 1. Carregar SharedCore e Banco de Dados com auto-recuperação
    core = None
    retry_count = 0
    max_retries = 30

    while _RUNNING and not core:
        try:
            from shared_core import get_shared_core
            core = get_shared_core()
            if not core:
                raise RuntimeError("SharedCore retornou instância nula.")
            logger.info("✅ SharedCore e Banco de Dados inicializados com sucesso.")
        except Exception as e:
            retry_count += 1
            logger.error(f"❌ Falha ao conectar ao banco/SharedCore (Tentativa {retry_count}/{max_retries}): {e}")
            if retry_count >= max_retries:
                logger.critical("💥 Limite de tentativas atingido. Verifique o PostgreSQL.")
                sys.exit(1)
            time.sleep(3)

    if not _RUNNING:
        return

    # 2. Verificar e inicializar os módulos do Scheduler e TaskManager
    scheduler = getattr(core, 'scheduler', None)
    task_manager = getattr(core, 'task_manager', None)

    if not scheduler:
        logger.error("❌ Módulo Scheduler não encontrado no SharedCore.")
        sys.exit(1)

    if not task_manager:
        logger.error("❌ Módulo TaskManager não encontrado no SharedCore.")
        sys.exit(1)

    # Iniciar agendador caso não esteja rodando
    if not scheduler.running:
        scheduler.start()
        logger.info("🔄 Engine de agendamento (Scheduler) iniciado.")

    # 3. Loop de monitoramento do Agente de Inicialização
    logger.info("🟢 GBOC Scheduler Agent em execução. Monitorando tarefas agendadas a cada minuto...")
    
    last_status_report = 0

    while _RUNNING:
        try:
            now = time.time()
            # A cada 60 segundos, logar heartbeat e resumo de tarefas ativas
            if now - last_status_report >= 60:
                last_status_report = now
                try:
                    with core.get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT COUNT(*) FROM tasks 
                            WHERE enabled = TRUE AND schedule_enabled = TRUE AND schedule_cron IS NOT NULL
                        """)
                        scheduled_count = cursor.fetchone()[0]

                        cursor.execute("""
                            SELECT COUNT(*) FROM task_executions WHERE status = 'running'
                        """)
                        running_count = cursor.fetchone()[0]

                    logger.info(
                        f"💓 [HEARTBEAT] Scheduler Ativo | Tarefas com Cron Ativo: {scheduled_count} | "
                        f"Execuções em Andamento: {running_count} | Fila: {task_manager._task_queue.qsize()}"
                    )
                except Exception as db_err:
                    logger.warning(f"⚠️ Erro ao obter métricas do heartbeat (tentando reconectar): {db_err}")

            time.sleep(1)

        except Exception as e:
            logger.error(f"❌ Erro no loop principal do Scheduler Daemon: {e}")
            time.sleep(5)

    # 4. Encerramento gracioso
    logger.info("⏹️ Parando componentes do Scheduler Agent...")
    try:
        if scheduler and scheduler.running:
            scheduler.stop()
        if task_manager:
            task_manager.stop()
    except Exception as e:
        logger.warning(f"Aviso no encerramento: {e}")

    logger.info("🏁 GBOC Scheduler Agent finalizado com sucesso.")

if __name__ == "__main__":
    main()
