<!-- Copyright (c) 2026 Master11BR - GBOC System v14.8.1 Enterprise. Todos os direitos reservados. -->

# 📘 GBOC System v14.8.1 — Guia Master de Configurações, Parâmetros e Controle de IA

[![GBOC Version](https://img.shields.io/badge/GBOC%20Version-14.8.1-blue.svg)](file:///d:/GBOC-New/GBOC-New/README.md)
[![UI Model](https://img.shields.io/badge/UI__MODEL-modern%20(Official)-indigo.svg)]()
[![Status](https://img.shields.io/badge/status-active-brightgreen.svg)]()

> **Manual Técnico Central de Configuração, Parâmetros e Diretrizes de IA do GBOC (Gestão & Backup Operations Center)**. Este documento serve como o guia oficial e autoritativo de parâmetros para administradores de sistemas, engenheiros de DevOps e agentes de IA.

---

## 📌 Sumário
1. [Visão Geral de Arquitetura e Parâmetros](#1-visão-geral-de-arquitetura-e-parâmetros)
2. [Variáveis de Ambiente Globais (.env)](#2-variáveis-de-ambiente-globais-env)
3. [Configuração da Engine de Inteligência Artificial (Local & Nuvem)](#3-configuração-da-engine-de-inteligência-artificial-local--nuvem)
4. [Configuração do GBOC Server](#4-configuração-do-gboc-server)
5. [Configuração do GBOC Agent & SharedCore](#5-configuração-do-gboc-agent--sharedcore)
6. [Backup Imutável (WORM / S3 Object Lock)](#6-backup-imutável-worm--s3-object-lock)
7. [Políticas Centrais & Tokens de Instalação em Massa](#7-políticas-centrais--tokens-de-instalação-em-massa)
8. [Parâmetros de Disaster Recovery, SureRestore Sandbox & Virtual Lab](#8-parâmetros-de-disaster-recovery-surerestore-sandbox--virtual-lab)
9. [Instaladores, Serviços Windows e Desinstalação](#9-instaladores-serviços-windows-e-desinstalação)

---

## 1. 🏗️ Visão Geral de Arquitetura e Parâmetros

O GBOC opera em uma estrutura distribuída e modular composta por:
- **GBOC Server**: Controladora central em FastAPI + PostgreSQL 16 + Redis + DLQ com taxonomia canônica de 7 domínios de negócio.
- **GBOC Agent**: Agente nativo executado como serviço Windows (`LocalSystem`) que orquestra motores de backup (FastCDC Native, Duplicati, Restic, Kopia), Disaster Recovery e Virtual Lab Sandbox.
- **AI Diagnostic Engine**: Engine de inteligência artificial de modo duplo (IA Local via Ollama/LocalAI ou IA em Nuvem via OpenAI/Claude/Gemini/DeepSeek).

---

## 2. 🔑 Variáveis de Ambiente Globais (.env)

Tanto o Servidor quanto o Agente utilizam arquivos `.env` ou variáveis de ambiente de sistema:

### 2.1 GBOC Server (`GBOC-Server/.env`)

```ini
# Informações Gerais
SERVER_NAME="GBOC Central Server"
SERVER_ENV="production"
LOG_LEVEL="INFO"
SERVER_PORT=8000

# Banco de Dados PostgreSQL
POSTGRES_HOST="localhost"
POSTGRES_PORT=5432
POSTGRES_DB="gboc"
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="SuaSenhaSegura"
DB_POOL_MIN=2
DB_POOL_MAX=20

# Segurança & JWT
SECRET_KEY="gboc-super-secret-jwt-key-replace-in-production"
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# Rate Limiting & DLQ
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
DEAD_LETTER_QUEUE_ENABLED=true
DLQ_FILE="data/dead_letter_queue.jsonl"

# Engine de IA (Local & Nuvem — Camada Unificada ai_providers.py)
AI_PROVIDER="auto"                                   # Opções: 'auto', 'ollama', 'openai', 'groq', 'gemini', 'claude', 'deepseek', 'grok', 'kimi', 'mistral', 'cohere'
AI_TIMEOUT=300                                       # Timeout de resposta em segundos (padrão 300s para nós CPU)
OLLAMA_URL="http://localhost:11434"                 # Endpoint raiz Ollama (/api/chat)
OPENAI_API_KEY=""                                    # Opcional (sk-...)
GROQ_API_KEY=""                                      # Opcional (gsk_...)
GEMINI_API_KEY=""                                    # Opcional (AIzaSy...)
ANTHROPIC_API_KEY=""                                 # Opcional (sk-ant-...)
DEEPSEEK_API_KEY=""                                  # Opcional (sk-...)
GROK_API_KEY=""                                      # Opcional (xai-...)
KIMI_API_KEY=""                                      # Opcional (sk-...)
MISTRAL_API_KEY=""                                   # Opcional
COHERE_API_KEY=""                                    # Opcional
AI_DIAGNOSTIC_FREQ=30                                # Minutos
AI_AUTO_REMEDIATION=true
AI_THREAT_SENSITIVITY="HIGH"
```

### 2.2 GBOC Agent (`GBOC-Agent/.env`)

```ini
AGENT_NAME="GBOC Agent Node"
AGENT_PORT=9200
SERVER_URL="http://localhost:8000"
SHARED_CORE_LOG_LEVEL="INFO"

# Motores de Backup Nativos (Paths Globais)
RESTIC_PATH="C:\GBOC\Tools\Restic\restic.exe"
KOPIA_PATH="C:\GBOC\Tools\Kopia\kopia.exe"
DUPLICATI_PATH="C:\GBOC\Tools\Duplicati\Duplicati.CommandLine.exe"

# Disaster Recovery, P2V & Virtual Lab Sandbox
DR_EXPORTS_DIR="C:\GBOC-DR"
VIRTUAL_LAB_SWITCH_NAME="GBOC-Isolated-Lab"
VIRTUAL_LAB_TIMEOUT_SECONDS=120
P2V_DEFAULT_FORMAT="VHDX"
P2V_DYNAMIC_EXPANDABLE=true

# Ransomware Shield & IA Local
SHIELD_ENABLED=true
SHIELD_CANARY_DIR="C:\GBOC\Canaries"
AGENT_AI_AUTO_HEALING=true
```

---

## 3. 🤖 Configuração da Engine de Inteligência Artificial (Local & Nuvem)

A Engine de IA do GBOC opera sob a camada unificada e simétrica `ai_providers.py` compartilhada entre Server e Agent, suportando 10 provedores com isolamento estrito de chaves/modelos, timeouts realistas e política Zero-Mock estrita:

| Parâmetro | Valor Padrão | Descrição / Opções |
| :--- | :--- | :--- |
| `AI_PROVIDER` | `auto` | `auto` (prioriza provedor em nuvem configurado com chave válida; fallback para Ollama Local), `ollama` (on-premises), `openai`, `groq`, `gemini`, `claude`, `deepseek`, `grok`, `kimi`, `mistral`, `cohere`. |
| `AI_TIMEOUT` | `300` | Tempo limite de resposta da inferência em segundos (configurável na UI via `ai-timeout` / `cfg-ai-timeout`). Padrão de 300s para suportar inferências em CPU com modelos 8B+. |
| `OLLAMA_URL` | `http://localhost:11434` | Endpoint base do Ollama (utiliza API nativa `/api/chat` com streaming estruturado e prompts sumarizados via `_smart_history_tokens`). |
| `OPENAI_API_KEY` | `""` | Chave de API para OpenAI (`gpt-4o`, `gpt-4o-mini`). |
| `GROQ_API_KEY` | `""` | Chave de API para Groq Cloud (`openai/gpt-oss-120b`). |
| `GEMINI_API_KEY` | `""` | Chave Google Gemini (`gemini-flash-latest`, header `x-goog-api-key`). |
| `ANTHROPIC_API_KEY` | `""` | Chave Anthropic Claude (`claude-sonnet-5-5`). |
| `DEEPSEEK_API_KEY` | `""` | Chave DeepSeek (`deepseek-flash`, endpoint oficial compatível). |
| `GROK_API_KEY` | `""` | Chave xAI Grok (`grok-4.7`). |
| `KIMI_API_KEY` | `""` | Chave Moonshot Kimi (`kimi-k2.6`). |
| `MISTRAL_API_KEY` | `""` | Chave Mistral AI (`mistral-large-latest`). |
| `COHERE_API_KEY` | `""` | Chave Cohere API v2 (`command-a-plus-05-2026`). |
| `AI_AUTO_REMEDIATION` | `true` | Habilita rotinas de manutenção autônoma reais (limpeza, reparo de catálogos SQLite) retornando 501 com guia manual se a ação exigir intervenção humana. |
| `AI_THREAT_SENSITIVITY` | `HIGH` | Sensibilidade de análise do Ransomware Shield (`LOW`, `MEDIUM`, `HIGH`, `MAX`). |

---

## 4. 🎛️ Configuração do GBOC Server

As configurações do servidor são gerenciadas pela API REST `/api/v1/server/settings` e persistidas na tabela PostgreSQL `settings`.

### Categorias de Configuração da API:
- `general`: Nome do servidor, ambiente e nível de logs.
- `backup`: Motor padrão, nível de compressão (1-9), criptografia padrão, uploads paralelos.
- `notifications`: Canais de notificação (Webhook, E-mail, Notificações do Windows).
- `performance`: Limite de uso de CPU (%), limite de RAM (GB), tarefas concorrentes máximas.
- `security`: Exigência de autenticação, timeout de sessão JWT, IPs permitidos.
- `ai`: Configurações do modelo de linguagem, frequência de diagnóstico e autorrecuperação.

---

## 5. 🛡️ Configuração do GBOC Agent & SharedCore

O `SharedCore` é o orquestrador nativo do Agente.

### Recursos Configuráveis:
1. **Ransomware Shield v14.6.0**:
   - Cria arquivos canário estratégicos (`.gboc_canary_repos`).
   - Bloqueia automaticamente processos suspeitos que tentem modificar canários em massa.
2. **Duplicati Native Engine**:
   - Suporta autenticação dupla: **JWT Bearer** para Duplicati v2.3+ e **XSRF** para versões legadas v2.0+.
3. **Módulo de Recovery & Cargas Protegidas**:
   - Orquestração de Bancos de Dados (PostgreSQL, MySQL, SQLite, SQL Server), Active Directory NTDS/SYSVOL, Fita LTO e Workloads Enterprise.

---

## 6. 🔬 Parâmetros de Disaster Recovery, SureRestore Sandbox & Virtual Lab

| Parâmetro | Padrão | Descrição |
| :--- | :--- | :--- |
| `VIRTUAL_LAB_SWITCH_NAME` | `GBOC-Isolated-Lab` | Nome do switch virtual privado Hyper-V sem acesso à placa física (Zero-Collision). |
| `VIRTUAL_LAB_TIMEOUT_SECONDS` | `120` | Tempo limite de espera para detecção de heartbeat WMI do Guest SO em sandbox. |
| `P2V_DEFAULT_FORMAT` | `VHDX` | Formato padrão de saída na conversão físico-para-virtual (`VHDX` para Hyper-V/Proxmox QEMU). |
| `P2V_DYNAMIC_EXPANDABLE` | `true` | Alocação dinâmica de espaço em disco no contêiner VHDX. |

---

## 6. 🔒 Backup Imutável (WORM / S3 Object Lock)

O GBOC implementa proteção imutável rigorosa contra ransomware e operadores mal-intencionados:

| Parâmetro / Recurso | Tipo | Descrição |
| :--- | :--- | :--- |
| `S3 Object Lock` | Nuvem | Retenção imutável em buckets S3/Wasabi nos modos `GOVERNANCE` ou `COMPLIANCE`. Uploads validam obrigatoriamente hash `Content-MD5`. |
| `WORM Local` | Disco | Bloqueio de arquivos locais de snapshot como somente leitura e inserção de ACL explícita do Windows (`icacls /deny Everyone:(DE)`). |
| `Retention Days` | Número | Número de dias de imutabilidade obrigatória durante os quais o agente e o storage recusam exclusão ou modificação. |

---

## 7. 🚀 Políticas Centrais & Tokens de Instalação em Massa

| Recurso | Descrição |
| :--- | :--- |
| `Tokens de Instalação` | Gerados na central com vínculo por tenant/organização, validade e limite de usos (`POST /api/v1/fleet/install-tokens`). |
| `Instalação Unattended` | `install_agent.ps1 -ServerURL <URL> -InstallToken <TOKEN> -Unattended` para implantação automática via GPO, scripts de inicialização ou RMM. |
| `Políticas de Backup Centrais` | Definição de regras de agenda, retenção, limites de upload, janela de manutenção e imutabilidade aplicadas em massa na frota. |
| `Detecção de Desvio (Drift)` | Auditoria contínua comparando o estado real reportado pelo agente com a política central homologada, com reaplicação imediata. |

---

## 8. 🛡️ Parâmetros de Disaster Recovery, SureRestore Sandbox & Virtual Lab

| Parâmetro | Valor Padrão | Descrição |
| :--- | :--- | :--- |
| `VIRTUAL_LAB_SWITCH_NAME` | `GBOC-Isolated-Lab` | Nome do switch virtual privado Hyper-V sem acesso à placa física (Zero-Collision). |
| `VIRTUAL_LAB_TIMEOUT_SECONDS` | `120` | Tempo limite de espera para detecção de heartbeat WMI do Guest SO em sandbox. |
| `P2V_DEFAULT_FORMAT` | `VHDX` | Formato padrão de saída na conversão físico-para-virtual (`VHDX` para Hyper-V/Proxmox QEMU). |
| `P2V_DYNAMIC_EXPANDABLE` | `true` | Alocação dinâmica de espaço em disco no contêiner VHDX. |

---

## 9. ⚙️ Instaladores, Serviços Windows e Desinstalação

### Instalação via PowerShell (Como Administrador)
```powershell
# Agente (Instalação Normal)
cd d:\GBOC-New\GBOC-New\GBOC-Agent
.\install_agent.ps1

# Agente (Instalação em Massa via Token)
.\install_agent.ps1 -ServerURL "https://seu-servidor:8000" -InstallToken "SEU_TOKEN" -Unattended

# Servidor
cd d:\GBOC-New\GBOC-New\GBOC-Server
Set-ExecutionPolicy Bypass -Scope Process -Force
.\install_server.ps1
```

### Gerenciamento de Serviços Windows (NSSM)
```powershell
# Iniciar / Parar Serviços
Start-Service GBOCAgent
Start-Service GBOCServer
Stop-Service GBOCAgent
Stop-Service GBOCServer

# Desinstalação Limpa
cd d:\GBOC-New\GBOC-New\GBOC-Agent
.\uninstall_agent.bat

cd d:\GBOC-New\GBOC-New\GBOC-Server
.\uninstall_server.bat
```

---

**GBOC System v14.8.1** — Guia Oficial de Parâmetros e Configuração.
