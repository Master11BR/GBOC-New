# PROJECT_CONTEXT - GBOC System v14.6.0 Enterprise

## 🎯 OBJETIVO
Sistema corporativo de gerenciamento de backups, monitoramento e diagnóstico preemptivo. O projeto garante alta performance utilizando sempre as tecnologias em suas últimas versões.

## 🏗️ ARQUITETURA
Duas frentes independentes integradas via WebSocket/REST:
- **Agente (`\GBOC-Agent`)**: Endpoint local (FastAPI, porta 9200). Roda os motores de backup (Duplicati, Kopia, Restic, Native FastCDC v4), Ransomware Shield, Cyber Security Sentinel e coletores.
- **Servidor (`\GBOC-Server`)**: Central de monitoramento (FastAPI, porta 8000) e banco PostgreSQL unificado.

## 📁 ESTRUTURA DE DIRETÓRIOS PRINCIPAL (Agente em `\GBOC-Agent`)
- `/api/`: Controladores REST isolados por domínio.
- `/modules/`: Módulos de domínio (`rmm`, `cbt`, `dr`, `security`, `job_alert`, `storage`, `logs`, `config`).
- `/engines/`: Lógica de negócios pesada, workers e rotinas autônomas.
- `/core/`: Infraestrutura crítica (DB migrator, logs, HTTP clients, DR Sync).
- `/static/`: Interface Web e arquivos estáticos padronizados com a **Universal CSS Architecture** (`style.css`, `gboc-themes.css`, `gboc-layout.css`, `gboc-hardware-hud.css`, `gboc-file-picker.css`) e `gboc-modal.js`.
- `/scripts/`: Automações (PowerShell, Batch).

## 📌 ESTADO ATUAL E REGRAS DE CONTEXTO
- **Zero Mocks**: Todo o ecossistema já está integrado. Interfaces e serviços devem consumir dados reais. O uso de arrays estáticos ou simulações para acelerar entregas não é tolerado.
- **Universal CSS Architecture**: Todas as telas consomem rigorosamente a stack canônica de 5 CSS universais compartilhados com o Servidor e o interceptor global `gboc-modal.js`.
- **Regra de Banco**: Consultas booleanas no PostgreSQL devem obrigatoriamente usar `= true` ou `= false` (nunca `1` ou `0`).
- **Segurança**: A interface não deve quebrar o `auth_interceptor.js`. Operações críticas no backend devem ser idempotentes e seguras.