# PROJECT_CONTEXT - GBOC System v14.0.0 Enterprise

## 🎯 OBJETIVO
Sistema corporativo de gerenciamento de backups, monitoramento e diagnóstico preemptivo. O projeto garante alta performance utilizando sempre as tecnologias em suas últimas versões.

## 🏗️ ARQUITETURA E STACK
Duas frentes independentes integradas via WebSocket/REST:

### 1. Agente (`\GBOC-Agent` - Porta 9200)
- **Stack**: FastAPI (Python 3.11+).
- **Responsabilidade**: Roda os motores de backup (Kopia, Restic, Native), Ransomware Shield e coletores.

### 2. Servidor (`\GBOC-Server` - Porta 8000)
- **Stack**: FastAPI (Python 3.11+).
- **Banco de Dados**: PostgreSQL (com índices otimizados e Connection Pooling). Consultas booleanas devem obrigatoriamente usar `= true` ou `= false` (nunca `1` ou `0`).
- **Cache**: Redis Assíncrono (aioredis).
- **Segurança**: Autenticação JWT (Access/Refresh Tokens), hash de senha via PBKDF2 (100k iterações), Rate Limiting.
- **Confiabilidade**: Implementa Dead Letter Queue (DLQ) para mensagens falhadas e Retry Logic com backoff exponencial. Webhooks existem na estrutura, mas estão desabilitados (`WEBHOOKS_ENABLED = False`).

## 📁 ESTRUTURA DE FRONTEND (`/static/`)
- **Obrigatório**: Todo o HTML deve usar Bootstrap (última versão) para grids e componentes, HTML5, CSS3. JavaScript deve ser ES6+ mantendo compatibilidade com Babel.
- **Padrão Visual**: Respeite o sistema de temas (`[data-theme="dark"]`) e reuso de funções do `gboc-global.js`. A interface não deve quebrar o `auth_interceptor.js`.

## 📌 REGRAS DE ESTADO ZERO MOCKS
- Todo o ecossistema já está integrado. Interfaces e serviços devem consumir dados reais (PostgreSQL, APIs ou motores).
- É ESTRITAMENTE PROIBIDO gerar código com dados mockados (falsos, estáticos ou arrays hardcoded) para simular entregas.