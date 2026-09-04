# PROJECT_CONTEXT - GBOC System v14.0.0 Enterprise

## 🎯 OBJETIVO
Sistema corporativo de gerenciamento de backups, monitoramento e diagnóstico preemptivo. O projeto garante alta performance utilizando sempre as tecnologias em suas últimas versões.

## 🏗️ ARQUITETURA
Duas frentes independentes integradas via WebSocket/REST:
- **Agente (`\GBOC-Agent`)**: Endpoint local (FastAPI, porta 9200). Roda os motores de backup (Kopia, Restic, Native), Ransomware Shield e coletores.
- **Servidor (`\GBOC-Server`)**: Central de monitoramento (FastAPI, porta 8000) e banco PostgreSQL unificado.

## 📁 ESTRUTURA DE DIRETÓRIOS PRINCIPAL (Agente em `\GBOC-Agent`)
- `/api/`: Controladores REST isolados por domínio.
- `/engines/`: Lógica de negócios pesada, workers e rotinas autônomas.
- `/core/`: Infraestrutura crítica (DB migrator, logs, HTTP clients).
- `/static/`: Interface Web (Views estruturadas com Bootstrap, HTML5, CSS3).
- `/scripts/`: Automações (PowerShell, Batch).

## 📌 ESTADO ATUAL E REGRAS DE CONTEXTO
- **Zero Mocks**: Todo o ecossistema já está integrado. Interfaces e serviços devem consumir dados reais. O uso de arrays estáticos ou simulações para acelerar entregas não é tolerado.
- **Padrão Visual**: Qualquer nova view ou componente adicionado em `/static/` deve herdar as classes nativas do Bootstrap.
- **Regra de Banco**: Consultas booleanas no PostgreSQL devem obrigatoriamente usar `= true` ou `= false` (nunca `1` ou `0`).
- **Segurança**: A interface não deve quebrar o `auth_interceptor.js`. Operações críticas no backend devem ser idempotentes e seguras.