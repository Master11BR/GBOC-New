<!-- Copyright (c) 2026 Master11BR - GBOC System v14.6.0 Enterprise. Todos os direitos reservados. -->

# 🚀 GBOC - Gestão & Backup Operations Center (v14.6.0 Enterprise Edition)

[![GBOC System Version](https://img.shields.io/badge/version-14.6.0--Enterprise-blue.svg)](https://github.com/Master11BR/GBOC-New)
[![Python Version](https://img.shields.io/badge/python-3.11%2B%20%7C%203.14-green.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-16-blue.svg)](https://www.postgresql.org/)
[![UI Model](https://img.shields.io/badge/UI__MODEL-modern%20(Official)-indigo.svg)]()
[![Status](https://img.shields.io/badge/status-production--ready-brightgreen.svg)]()

> **GBOC (Gestão & Backup Operations Center v14.6.0 Enterprise Edition)** é a mais avançada plataforma corporativa de orquestração de backup, Disaster Recovery (DR) 100% verificável ponta a ponta, RMM, telemetria real (Zero-Mock Strict), modelo visual universal **Modern UI (UnoCSS)** e resposta cibernética a incidentes.

---

## 📌 Sumário
1. [Visão Geral e Arquitetura Operacional](#-visão-geral-e-arquitetura-operacional)
2. [Estrutura Canônica de Navegação (7 Domínios de Negócio)](#-estrutura-canônica-de-navegação)
3. [Recursos de Destaque (v14.6.0 Enterprise)](#-recursos-de-destaque-v1460-enterprise)
4. [Disaster Recovery & SureRestore Sandbox Zero-Mock](#-disaster-recovery--surerestore-sandbox-zero-mock)
5. [Cyber Security Sentinel (ClamAV, YARA, Maltrail, Wazuh, Defender)](#-cyber-security-sentinel)
6. [Assistente de Inteligência Artificial & LLMs (Ollama & Nuvem)](#-assistente-de-inteligência-artificial--llms)
7. [Histórico de Mudanças (Changelog v14.6.0 Enterprise)](#-histórico-de-mudanças)
8. [Instalação & Configuração Rápida](#-instalação--configuração-rápida)

---

## 🏗️ Visão Geral e Arquitetura Operacional

O GBOC v14.6.0 opera sob o ciclo de vida completo e verificável de proteção contínua:

```text
Política → Backup consistente → Armazenamento → Integridade →
Teste de recuperação → Recuperação → Validação operacional → Evidência
```

```text
                  ┌────────────────────────────────────────┐
                  │             GBOC SERVER                │
                  │   - Dashboard Enterprise Canônico      │
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
               │   - Virtual Lab Sandbox (Switch Isolado)     │
               └──────┬────────────────┬───────────────┬──────┘
                      │                │               │
                      ▼                ▼               ▼
               ┌────────────┐   ┌────────────┐   ┌────────────┐
               │  FASTCDC   │   │ DUPLICATI  │   │   RESTIC   │
               │ (ENGINE 4) │   │ (NATIVO)   │   │  (CLI/API) │
               └────────────┘   └────────────┘   └────────────┘
```

---

## 🗺️ Estrutura Canônica de Navegação

A interface e as APIs do Servidor e Agente são organizadas estritamente em **7 Domínios Canônicos de Negócio**:

```text
Visão Geral
└── Dashboard Principal (/index.html / tab:overview)

Backup
├── Jobs e Políticas (/tasks.html / tab:backups)
├── Cargas Protegidas (/protected-workloads.html / tab:workloads — Bancos, AD, LTO, Oracle, SAP)
├── Repositórios (/repositories.html / tab:storage)
└── Restaurar e Validar (/restore.html / tab:surerestore — Assistente, Integridade, Sandbox)

Disaster Recovery
├── Prontidão e Plano (/disaster-recovery.html?tab=readiness / tab:dr-readiness)
├── Recuperação Instantânea (/disaster-recovery.html?tab=instant-vm / tab:instant-vm)
├── Bare Metal, P2V e Mídia (/disaster-recovery.html?tab=p2v / tab:p2v)
└── Laboratório e Validação (/disaster-recovery.html?tab=virtual-lab / tab:virtual-lab)

Proteção
├── Ransomware Guardian (/ransomware.html / tab:ransomware)
├── Conformidade (/compliance.html / tab:compliance)
└── Auditoria (/audit.html / tab:audit)

Virtualização e Cloud
├── VMware, Hyper-V e Proxmox (/virtualization.html / tab:virtualization)
├── Microsoft 365 e Exchange (/m365-exchange.html / tab:m365)
├── SaaS, Kubernetes e Cloud (/saas-cloud-enterprise.html / tab:saas-cloud)
└── Replicação (/replication.html / tab:replication)

Operações
├── Alertas e Falhas (/alerts.html / tab:alerts)
├── Logs Globais (/logs.html / tab:logs)
├── Diagnóstico (/diagnostic.html / tab:diagnostic)
└── Relatórios (/reports.html / tab:reports)

Configuração
├── Usuários e Permissões (/users.html / tab:users)
├── Notificações (/notification-channels.html / tab:notifications)
├── Armazenamento (/storage-usage.html / tab:storage)
├── Motores e Integrações (/engines.html / tab:engines)
└── Configurações Gerais (/settings.html / tab:config)
```

---

## ⚡ Recursos de Destaque (v14.6.0 Full Stable Enterprise)

- **Arquitetura Operacional de DR & SureRestore Zero-Mock**:
  - Eliminação definitiva de declarações ou retornos simulados. Um ponto de restauração só recebe o status de *Aprovado* após boot real em VM isolada com validação de heartbeat e consistência de carga.
  - Estados padronizados: `Protegido`, `Em risco`, `Atenção`, `Falhou`, `Não protegido`.
  - Estados de validação: `Aprovado`, `Reprovado`, `Inconclusivo`, `Expirado`.
- **Restauração de Banco de Dados com Validação Estrita**:
  - PostgreSQL: Invocação de `pg_restore` em banco temporário com captura de `stderr` e falha explícita imediata se o código de saída for diferente de 0.
  - SQLite: Execução do `PRAGMA integrity_check;` e verificação da estrutura de tabelas.
- **Clonagem P2V & Streaming de Blocos**:
  - Criação de imagem VHDX com streaming direto de dados a partir de snapshot VSS consistente, validação de privilégios de Administrador e geração de manifesto de hardware VM (`.vmconfig.json`).
- **Backup de System State & Active Directory**:
  - Integração nativa com `wbadmin start systemstatebackup` e catálogo completo de consistência NTDS/SYSVOL, registro e manifesto criptográfico SHA-256 (`dr_manifest.json`).
- **Mídia de Boot WinPE / ISO Real**:
  - Extração automática de drivers de armazenamento, rede e RAID do host operacional via `Export-WindowsDriver`, scripts de recuperação autônoma e compilação de ISO bootável real via `oscdimg` (Windows ADK).
- **Virtual Lab Sandbox**:
  - Provisionamento e isolamento de rede em switch virtual privado (`GBOC-Isolated-Lab`), prevenindo qualquer colisão com o ambiente de produção.
- **Universal CSS & Cancelamento Real de Requisições**:
  - 100% de sincronização bidirecional de CSS e JS compartilhados (`gboc-perf.js`, `gboc-modal.js`, `gboc-layout-manager.js`, `gboc-hardware-hud.js`, `gboc-motion.js`).
  - Utilização de `gbocPerf.makeCancellable()` para abortar requisições pendentes em trocas de tela e buscas ativas.
  - Fallback resiliente no startup do servidor e agente para `httptools` e `uvloop`.

---

## 📜 Histórico de Mudanças (Changelog v14.6.0 Enterprise)

- **Reestruturação Canônica de Navegação (7 Domínios de Negócio)**:
  - Alinhamento completo da Sidebar e Topbar no Server e no Agent com os domínios: *Visão Geral, Backup, Disaster Recovery, Proteção, Virtualização & Cloud, Operações e Configuração*.
  - Criação do módulo consolidado de **Cargas Protegidas** ([`protected-workloads.html`](file:///d:/GBOC-New/GBOC-New/GBOC-Agent/static/protected-workloads.html) e [`protected-workloads.js`](file:///d:/GBOC-New/GBOC-New/GBOC-Agent/static/protected-workloads.js)).
  - Adição de sub-abas consolidadas em `restore.html`, `alerts.html`, `diagnostic.html`, `engines.html` e `disaster-recovery.html`.
  - Mapeamento de aliases e suporte a deep linking via URL params com preservação de retrocompatibilidade de URLs legadas.
- **Eliminação de Simulações & Zero-Mock Strict Policy**:
  - SureRestore Sandbox reescrito para validação real no hypervisor (`surerestore_router.py`).
  - Falha explícita garantida em `_test_restore_pg()` para retornos com código != 0 e SQLite integrity check.
  - P2V atualizado com leitura real de blocos, checagem de privilégios de Administrador e geração de descritor de VM.
  - Backup de System State e AD com suporte a `wbadmin` e manifesto SHA-256.
  - Staging de Mídia de Boot WinPE com exportação real de drivers via PowerShell e compilação de ISO.
  - Virtual Lab Sandbox com ciclo de vida completo de VM isolada e verificação de heartbeat WMI.
- **Estabilidade do Frontend & Pipeline de Build**:
  - Correção da classe inacabada no [`task_monitor.js`](file:///d:/GBOC-New/GBOC-New/GBOC-Agent/static/task_monitor.js).
  - Correção da função `safeRender` em [`gboc-perf.js`](file:///d:/GBOC-New/GBOC-New/shared-css/gboc-perf.js) com comparação completa `_gbocLastHtml`.
  - Inclusão de `gboc-perf.js` e scripts compartilhados na fonte canônica `shared-css/` e no sincronizador `sync_css.py`.
  - Execução obrigatória do gatekeeper `python tools/sync_css.py --verify` antes da geração do pacote de distribuição no `make_distribution.py`.
  - Implementação de fallback dinâmico para `httptools` e `uvloop` em `agent_gboc.py`, `agent_server.py`, `server_gboc.py` e `gboc_server.py`.
  - Aplicação de `gbocPerf.makeCancellable()` nas telas de alta frequência.
  - Incremento global de versão para **v14.6.0 Full Stable Enterprise**.

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

## ⚙️ Instalação & Configuração Rápida

### Pré-requisitos
- **Windows Server 2016+ / Windows 10/11** ou **Linux Ubuntu 22.04+ / Debian 12+**
- **Python 3.11+ / 3.14**
- **PostgreSQL 14+ / 16** (para o Servidor Central)

### Iniciar Servidor Central
```powershell
cd GBOC-Server
python server_gboc.py
```
Acesse: `http://localhost:8000`

### Iniciar Agente Local
```powershell
cd GBOC-Agent
python agent_gboc.py
```
Acesse: `http://localhost:9200`
