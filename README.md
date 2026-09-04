<!-- Copyright (c) 2026 Master11BR - GBOC System v13.3.0 Enterprise. Todos os direitos reservados. -->

# 🚀 GBOC - Gestão & Backup Operations Center (v13.3.0 Enterprise Edition)

[![GBOC System Version](https://img.shields.io/badge/version-13.3.0--Enterprise-blue.svg)](https://github.com/Master11BR/GBOC-New)
[![Python Version](https://img.shields.io/badge/python-3.11%2B%20%7C%203.14-green.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-16-blue.svg)](https://www.postgresql.org/)
[![Status](https://img.shields.io/badge/status-production--ready-brightgreen.svg)]()

> **GBOC (Gestão & Backup Operations Center v13.3.0 Enterprise Edition)** é a mais avançada plataforma corporativa de orquestração de backup, RMM, monitoramento preditivo e resposta cibernética a incidentes. 10x mais potente que soluções do mercado pago e open-source.

---

## 📌 Sumário
1. [Visão Geral e Arquitetura](#-visão-geral-e-arquitetura)
2. [Recursos de Destaque (v14.0.0 Enterprise)](#-recursos-de-destaque-v1300-enterprise)
3. [Cyber Security Sentinel (ClamAV, YARA, Maltrail, Wazuh, Defender)](#-cyber-security-sentinel)
4. [Assistente de Inteligência Artificial & LLMs (Ollama & Nuvem)](#-assistente-de-inteligência-artificial--llms)
5. [Disaster Recovery (DR) & Sync em Nuvem 1-Click](#-disaster-recovery-dr--sync-em-nuvem-1-click)
6. [Resiliência a Longos Intervalos (Auto-Heal & Lock Prune)](#-resiliência-a-longos-intervalos-auto-heal--lock-prune)
7. [Instalação & Configuração Rápida](#-instalação--configuração-rápida)
8. [Histórico de Mudanças (Changelog v14.0.0 Enterprise)](#-histórico-de-mudanças)

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

## ⚡ Recursos de Destaque (v14.0.0 Full Stable Enterprise)

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

---

## ⚖️ Direitos Autorais & Licença

- **Copyright (c) 2026 Master11BR - Todos os direitos reservados.**
- Todos os arquivos fonte contêm cabeçalhos legalmente registrados de Propriedade Intelectual.
