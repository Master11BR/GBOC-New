<!-- Copyright (c) 2026 Master11BR - GBOC System v14.3.0 Enterprise. Todos os direitos reservados. -->

# 🚀 GBOC - Gestão & Backup Operations Center (v14.3.0 Enterprise Edition)

[![GBOC System Version](https://img.shields.io/badge/version-14.3.0--Enterprise-blue.svg)](https://github.com/Master11BR/GBOC-New)
[![Python Version](https://img.shields.io/badge/python-3.11%2B%20%7C%203.14-green.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-16-blue.svg)](https://www.postgresql.org/)
[![UI Model](https://img.shields.io/badge/UI__MODEL-modern%20(Official)-indigo.svg)]()
[![Status](https://img.shields.io/badge/status-production--ready-brightgreen.svg)]()

> **GBOC (Gestão & Backup Operations Center v14.3.0 Enterprise Edition)** é a mais avançada plataforma corporativa de orquestração de backup, RMM, monitoramento preditivo, telemetria 100% real (Zero-Mock Strict), modelo visual oficial **Modern UI (UnoCSS)** e resposta cibernética a incidentes.

---

## 📌 Sumário
1. [Visão Geral e Arquitetura](#-visão-geral-e-arquitetura)
2. [Recursos de Destaque (v14.1.0 Enterprise)](#-recursos-de-destaque-v1410-enterprise)
3. [Cyber Security Sentinel (ClamAV, YARA, Maltrail, Wazuh, Defender)](#-cyber-security-sentinel)
4. [Assistente de Inteligência Artificial & LLMs (Ollama & Nuvem)](#-assistente-de-inteligência-artificial--llms)
5. [Disaster Recovery (DR) & Sync em Nuvem 1-Click](#-disaster-recovery-dr--sync-em-nuvem-1-click)
6. [Resiliência a Longos Intervalos (Auto-Heal & Lock Prune)](#-resiliência-a-longos-intervalos-auto-heal--lock-prune)
7. [Instalação & Configuração Rápida](#-instalação--configuração-rápida)
8. [Histórico de Mudanças (Changelog v14.1.0 Enterprise)](#-histórico-de-mudanças)

---

## 🏗️ Visão Geral e Arquitetura

```
                  ┌────────────────────────────────────────┐
                  │             GBOC SERVER                │
                  │   - Dashboard Enterprise Unificado     │
                  │   - PostgreSQL 16 (Imunidade WAL)      │
                  │   - RMM Proxy & Espelho Web Agente     │
                  │   - SureRestore Sandbox & Multi-Tenant │
                  └───────────────────┬────────────────────┘
                                      │
                         HTTP/REST    │  WebSocket (Reboot Safe)
                         Porta 8000   │  Porta 9200 (Agente)
                                      ▼
               ┌──────────────────────────────────────────────┐
               │                 GBOC AGENT                   │
               │   - Direct-to-Cloud FastCDC Streaming        │
               │   - Cyber Security Sentinel (ClamAV/YARA)    │
               │   - AI Diagnostic Engine (Ollama/Cloud)      │
               │   - DR Backup S3 (.gbocdr 1-Click Restore)   │
               └──────┬────────────────┬───────────────┬──────┘
                      │                │               │
                      ▼                ▼               ▼
               ┌────────────┐   ┌────────────┐   ┌────────────┐
               │  FASTCDC   │   │ DUPLICATI  │   │   RESTIC   │
               │ (ENGINE 4) │   │ (NATIVO)   │   │  (CLI/API) │
               └────────────┘   └────────────┘   └────────────┘
```

---

## ⚡ Recursos de Destaque (v14.1.0 Full Stable Enterprise)

- **Motion Principles UX Engine (Kyle Zantos)**: Interface 100% dinâmica com Skeleton Loaders, Lazy Loading inteligente via Intersection Observer, animações de entrada/saída suaves e barras de progresso contínuas e fluidas.
- **Storage Usage & Growth Monitor GUI**: Módulo centralizado (`modules/storage`) para monitoramento em tempo real de volumes de armazenamento, capacidade utilizada/livre e tendência de crescimento com gráficos dinâmicos Chart.js.
- **Job Failure & Alert Monitor GUI**: Módulo centralizado (`modules/job_alert`) para consolidação de falhas de jobs ativas, fluxo de resolução com 1-clique e testes de disparo de alertas em múltiplos canais.
- **GBOC Native Engine v4**: FastCDC (Content-Defined Chunking 4KB-4MB), compressão Zstd, encriptação autenticada AES-256-GCM e WORM Immutability.
- **Direct-to-Cloud Memory Streaming**: Envio contínuo via RAM buffer (< 100MB) diretamente para repositórios Cloud (S3, MinIO, Azure, SFTP) sem criar arquivos staging no disco local.
- **RMM Proxy & Espelho Web do Agente**: Execute PowerShell/Bash remotos com o terminal interativo do servidor e controle a interface web do agente via proxy em tempo real.
- **SureRestore Sandbox**: Testes automatizados de restauração em máquinas virtuais isoladas com reporte de tempo de boot e teste de pulso de SO (*os_heartbeat*).
- **Stack de Observabilidade & APM**: Telemetria corporativa integrada com **Sentry**, **OpenTelemetry (OTel)**, **Datadog APM**, **NewRelic** e métricas Prometheus nativas.
- **Governança & Linting de Código**: Qualidade de código mantida via **Arch-contract**, **Biome Linter**, **Commitlint**, **Knip** (detector de código morto) e **Stryker** (testes de mutação).
- **Suíte de Testes & Cobertura**: Testes End-to-End automatizados com **Playwright**, testes de integração com **Pytest** e relatórios de cobertura **Codecov**.
- **Gestão Multi-Tenant MSP**: Estruturação completa por Organizações, Clientes e Quotas de armazenamento.

---

## 🛡️ Cyber Security Sentinel

Integrado com os 5 principais ecossistemas globais de segurança:

1. **Windows Defender Native Hook**: Leitura via WMI PowerShell (`Get-MpComputerStatus`) e disparo automático de varreduras (`Start-MpScan`).
2. **ClamAV Antivirus**: Varredura por assinatura de código malicioso antes e depois da execução de backups.
3. **YARA Rules Engine**: Regras heurísticas para identificação de ransomwares e notas de resgate.
4. **Maltrail Threat Feed**: Checagem de reputação de IPs e domínios C2 (Command & Control).
5. **Wazuh HIDS / SIEM**: Encaminhamento de logs de auditoria de segurança padronizados em JSON.

---

## 🤖 Assistente de Inteligência Artificial & LLMs

- **Multi-Provedor**: Integração real com Ollama Local (`http://localhost:11434`), OpenAI, Gemini e DeepSeek.
- **Assistência Integrada em Todos os Módulos**: Diagnósticos preditivos com botão de **"Solução em 1-Clique"** nas telas de Diagnóstico, Logs, Tarefas, Compliance e Alertas.

---

## 🔄 Disaster Recovery (DR) & Sync em Nuvem 1-Click

- Ao final de cada backup, o módulo [agent_dr_sync.py](file:///d:/GBOC-New/GBOC-New/GBOC-Agent/core/agent_dr_sync.py) grava e criptografa as configurações e banco local em um pacote `.gbocdr` enviado automaticamente para a Nuvem (`/_gboc_dr_metadata/{agent_id}/`).
- Após uma instalação limpa do SO, o administrador pode utilizar o assistente [dr_restore_manager.py](file:///d:/GBOC-New/GBOC-New/GBOC-Agent/core/dr_restore_manager.py) para reconstruir 100% dos repositórios, agendamentos e tarefas em 1 clique.

---

## 🛡️ Resiliência a Longos Intervalos (Auto-Heal & Lock Prune)

- **Rotina Preventiva para Falhas por Inatividade**: Quando uma tarefa fica mais de 3 dias sem executar, o GBOC executa automaticamente o Auto-Heal: higieniza travas obsoletas (`.lock`), valida o banco do repositório (`repair`) e garante a execução transparente do backup sem desincronizações.

## 📜 Histórico de Mudanças (Changelog v14.3.0 Enterprise)

- **Auto-Diagnóstico de IA com Telemetria Real e Respostas Precisas ("O Que Fazer Exatamente")**:
  - Eliminação de respostas genéricas estáticas (*"Erro detectado: 'Diagnóstico geral...'"*).
  - Coleta em tempo real de telemetria física do host operacional (`CPU`, `RAM`, `Disco`, `Status BD`, `Locks em Repositório`) via `psutil`.
  - Diagnósticos estruturados em 3 seções obrigatórias: 🔍 **Causa Raiz Técnica**, 🛠️ **O Que Fazer Exatamente (Passo a Passo numerado)** e ⚡ **Executar Correção Automática (Auto-Heal)** (botão 1-click integrado a `/api/v2/system/auto-heal`).
- **Ativação Dinâmica em Tempo Real dos 4 Estilos de Componentes UI/UX**:
  - Correção dos seletores globais em `gboc-themes.css` vinculando cards, painéis, estatísticas, inputs, botões e modais às variáveis de design tokens (`--card-radius`, `--card-border`, `--card-shadow`, `--card-backdrop`, `--card-bg`).
  - Alternância imediata no navegador entre os 4 estilos visuais: **SaaS Minimal**, **Neumorphism (Soft UI)**, **3D Claymorphism** e **Fluent Design (Microsoft Acrylic Glass)**.
- **Padronização Estrita da API v2 (`/api/v2/`)**:
  - Endpoints oficiais `/api/v2/system/ui-config`, `/api/v2/system/version`, `/api/v2/ai/diagnose` e `/api/v2/system/auto-heal` envelopados com `build_v2_response`.

## 📜 Histórico de Mudanças (Changelog v14.2.0 Enterprise)

- **Backup Agentless de Máquinas Virtuais (VMware ESXi & Hyper-V)**: Motor `vmware_hypervisor_engine.py` com integração ao vSphere REST & SOAP SDK (CBT) e Hyper-V WMI nativo (RCT), com criação de checkpoints de produção consistentes via VSS sem instalar agentes no SO convidado.
- **Instant VM Recovery Local (Boot Instantâneo < 60s)**: Motor `instant_recovery_engine.py` com exportador de Datastore SMB/NFS local e camada diferencial Copy-on-Write (CoW) para inicialização direta do storage de backup sem cópia prévia.
- **Backup Nativo Microsoft 365 e Google Workspace (SaaS)**: Motor `saas_protection_engine.py` com cliente OAuth2 Microsoft Graph API para backup de Exchange Online, OneDrive, SharePoint e Teams.
- **Restauração Granular de Itens (Item-Level Recovery)**: Motor `sql_granular_explorer.py` com inspeção de Table of Contents (TOC) em dumps PostgreSQL (`pg_restore -l`), extração cirúrgica de tabela única, e exploração de tabelas no Microsoft SQL Server e SQLite.
- **Seletor Dinâmico de Estilos UX/UI & Iluminação**: Suporte dinâmico a 2 Modos de Iluminação (Light e Dark Carbon `#121212`) e 4 Formatos de Componentes (SaaS Minimal, Neumorphism Soft UI 3D, 3D Claymorphism e Fluent Design Acrylic Glass).
- **Migrador Cross-Database Zero-Data-Loss**: Motor `database_cross_migrator.py` com sincronização bidirecional completa entre SQLite (WAL) e PostgreSQL.

## 📜 Histórico de Mudanças (Changelog v14.1.0 Enterprise)

- **Strict Zero-Mock Architecture**: Remoção de 100% de dados simulados, respostas estáticas e fallbacks fake em todos os motores e rotas API (`healer_engine.py`, `tape_robotics_engine.py`, `auto_verify_engine.py`, `cyber_cleanroom_engine.py`, `enterprise_database_connectors.py`).
- **Telemetria 100% Real do SO Host**: Detecção de hardware de fita LTO/autoloader via WMI real, medição de entropia de Shannon sobre bytes físicos de arquivos no disk, e verificação de hashes SHA-256 em blocos de dados.
- **Relatórios Preditivos com Dados Reais**: Refatoração dos relatórios de Deduplicação, Outage Cloud, Volumes Desprotegidos e Restauração Bare-Metal (BMR) para consultar o banco de dados e partições reais do SO host.
- **Sincronização de Pacote de Distribuição**: Pacote `GBOC-Distribution` atualizado com scripts de instalação rápida (`Setup.bat`, `Setup.ps1`).

---

## ⚖️ Direitos Autorais & Licença

- **Copyright (c) 2026 Master11BR - Todos os direitos reservados.**
- Todos os arquivos fonte contêm cabeçalhos legalmente registrados de Propriedade Intelectual.
