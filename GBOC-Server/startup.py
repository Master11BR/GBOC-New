"""
GBOC Server - Script de Inicialização com Melhorias
Carrega todas as mudanças implementadas
"""
import asyncio
from config import SERVER_VERSION, SERVER_NAME, LOG_LEVEL, REDIS_ENABLED
from logger import setup_logger, logger as base_logger
from database import db_manager
from cache import cache
from health import health_check, metrics_collector
from dlq import dlq
from rate_limiter import rate_limiter

# Importar o servidor principal
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

logger = setup_logger(__name__)

async def initialize_server():
    """
    Inicializa todos os componentes do servidor

    Returns:
        True se inicializado com sucesso
    """
    print("\n" + "="*60)
    print(f"🚀 GBOC Server v{SERVER_VERSION} - Inicializando...")
    print(f"📍 Nome: {SERVER_NAME}")
    print(f"📊 Log Level: {LOG_LEVEL}")
    print("="*60 + "\n")

    # 1. Inicializar banco de dados
    print("📦 Inicializando banco de dados...")
    if not db_manager.initialize():
        logger.error("Falha ao inicializar banco de dados")
        return False
    print("✓ Banco de dados inicializado\n")

    # 2. Criar índices otimizados
    print("🔍 Criando índices de otimização...")
    db_manager.create_index_if_not_exists("agents", "idx_agent_id", "(agent_id)")
    db_manager.create_index_if_not_exists("agents", "idx_agent_status", "(status)")
    db_manager.create_index_if_not_exists("agents", "idx_agent_last_heartbeat", "(last_heartbeat)")
    db_manager.create_index_if_not_exists("agent_metrics", "idx_metrics_agent_time", "(agent_id, timestamp DESC)")
    db_manager.create_index_if_not_exists("agent_logs", "idx_logs_agent_time", "(agent_id, timestamp DESC)")
    db_manager.create_index_if_not_exists("agent_task_executions", "idx_exec_agent_status", "(agent_id, status)")
    print("✓ Índices criados\n")

    # 3. Inicializar cache Redis (se habilitado)
    print("💾 Inicializando cache...")
    if REDIS_ENABLED:
        if await cache.initialize():
            print("✓ Redis cache inicializado\n")
        else:
            print("⚠️  Redis desabilitado ou indisponível\n")
    else:
        print("⚠️  Redis cache desabilitado\n")

    # 4. Inicializar Dead Letter Queue
    print("📨 Inicializando Dead Letter Queue...")
    dlq_stats = dlq.get_stats()
    print(f"✓ DLQ iniciada - Total: {dlq_stats.get('total', 0)}, "
          f"Pendentes: {dlq_stats.get('pending', 0)}\n")

    # 5. Verificar saúde do sistema
    print("🏥 Verificando saúde do sistema...")
    health_status = health_check.check_system()
    print(f"✓ Status geral: {health_status['status'].upper()}\n")

    # 6. Exibir configurações de rate limiting
    print("⚡ Rate Limiting:")
    if rate_limiter.enabled:
        print("✓ Rate limiter ativado\n")
    else:
        print("⚠️  Rate limiter desabilitado\n")

    # 7. Exibir componentes carregados
    print("📦 Componentes Carregados:")
    print("✓ Logger estruturado (JSON/Text)")
    print("✓ Autenticação JWT com refresh tokens")
    print("✓ Rate limiting por endpoint")
    print("✓ Validação de modelos (Pydantic)")
    print("✓ Cache Redis (opcional)")
    print("✓ Dead Letter Queue")
    print("✓ Retry logic com backoff exponencial")
    print("✓ Webhooks (estrutura pronta)")
    print("✓ Health checks e monitoramento")
    print("✓ Paginação de resultados")
    print("✓ Políticas de retenção de dados\n")

    print("="*60)
    print("✅ Servidor pronto para iniciar!")
    print("="*60 + "\n")

    return True

def print_startup_info():
    """Exibe informações de startup"""
    print(f"""

    ╔═══════════════════════════════════════════════════════════╗
    ║         GBOC Server v{SERVER_VERSION} - Melhorias Implementadas            ║
    ╚═══════════════════════════════════════════════════════════╝

    🔐 SEGURANÇA:
       • JWT com access e refresh tokens
       • Proteção contra força bruta (login attempts)
       • Rate limiting por IP e endpoint
       • Validação de senhas com PBKDF2
       • CORS melhorado com headers de segurança

    ⚡ PERFORMANCE:
       • Cache Redis (opcional)
       • Connection pooling otimizado
       • Índices no PostgreSQL
       • Paginação de resultados (até 100 por página)
       • Compressão de dados

    📊 OBSERVABILIDADE:
       • Logging estruturado (JSON/Text)
       • Health checks automáticos
       • Métricas de requisições
       • Rastreamento de tentativas de login
       • Monitornig de Dead Letter Queue

    🔄 CONFIABILIDADE:
       • Retry logic com backoff exponencial
       • Dead Letter Queue para mensagens falhadas
       • Reconexão automática de WebSocket
       • Tratamento de erro centralizado

    📦 ARQUITETURA:
       • API versioning (v1)
       • Modelos Pydantic validados
       • Middlewares plugáveis
       • Estrutura modular

    🔮 FUTURO (PRONTO):
       • Webhooks para notificações externas
       • Políticas de retenção automática
       • Message queue integrada
       • Distributed tracing

    📝 DIRETÓRIOS CRIADOS:
       • config.py - Configurações centralizadas
       • logger.py - Logging estruturado
       • auth.py - Autenticação JWT
       • cache.py - Cache Redis
       • rate_limiter.py - Rate limiting
       • dlq.py - Dead Letter Queue
       • retry.py - Retry logic
       • webhooks.py - Webhooks (travado)
       • health.py - Health checks
       • models.py - Modelos Pydantic
       • database.py - Database utilities
       • middleware.py - Middlewares e decoradores
       • startup.py - Este arquivo

    """)

if __name__ == "__main__":
    print_startup_info()

    # Executar inicialização
    try:
        success = asyncio.run(initialize_server())
        if not success:
            logger.error("Falha na inicialização do servidor")
            sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("Inicialização cancelada pelo usuário")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Erro durante inicialização: {e}", exc_info=True)
        sys.exit(1)
