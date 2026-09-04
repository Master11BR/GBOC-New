<!-- Copyright (c) 2026 Master11BR - GBOC System v14.0.0 Enterprise. Todos os direitos reservados. -->

# 📘 GBOC System v14.0.0 — Guia Master de Configurações, Parâmetros e Controle de IA

[![GBOC Version](https://img.shields.io/badge/GBOC%20Version-14.0.0-blue.svg)](file:///d:/GBOC-New/GBOC-New/README.md)
[![Status](https://img.shields.io/badge/status-active-brightgreen.svg)]()

> **Manual Técnico Central de Configuração, Parâmetros e Diretrizes de IA do GBOC (Gestão & Backup Operations Center)**. Este documento serve como o guia oficial e autoritativo de parâmetros para administradores de sistemas, engenheiros de DevOps e agentes de IA.

---

## 📌 Sumário
1. [Visão Geral de Arquitetura e Parâmetros](#1-visão-geral-de-arquitetura-e-parâmetros)
2. [Variáveis de Ambiente Globais (.env)](#2-variáveis-de-ambiente-globais-env)
3. [Configuração da Engine de Inteligência Artificial (Local & Nuvem)](#3-configuração-da-engine-de-inteligência-artificial-local--nuvem)
4. [Configuração do GBOC Server](#4-configuração-do-gboc-server)
5. [Configuração do GBOC Agent & SharedCore](#5-configuração-do-gboc-agent--sharedcore)
6. [Catálogo e Parâmetros dos 50 Relatórios Avançados](#6-catálogo-e-parâmetros-dos-50-relatórios-avançados)
7. [Instaladores, Serviços Windows e Desinstalação](#7-instaladores-serviços-windows-e-desinstalação)

---

## 1. 🏗️ Visão Geral de Arquitetura e Parâmetros

O GBOC opera em uma estrutura distribuída e modular composta por:
- **GBOC Server**: Controladora central em FastAPI + PostgreSQL 16 + Redis + DLQ.
- **GBOC Agent**: Agente nativo executado como serviço Windows (`LocalSystem`) que orquestra motores de backup (Duplicati, Restic, Kopia e Native).
- **AI Diagnostic Engine**: Engine de inteligência artificial de modo duplo (IA Local via Ollama/LocalAI ou IA em Nuvem via OpenAI/Claude).

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

# Engine de IA (Local & Nuvem)
AI_PROVIDER="auto"                                   # Opções: 'auto', 'local', 'openai', 'anthropic'
LOCAL_LLM_URL="http://localhost:11434/api/generate" # Ollama / LocalAI
OPENAI_API_KEY=""                                    # Opcional (sk-...)
ANTHROPIC_API_KEY=""                                 # Opcional (sk-ant-...)
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

# Ransomware Shield & IA Local
SHIELD_ENABLED=true
SHIELD_CANARY_DIR="C:\GBOC\Canaries"
AGENT_AI_AUTO_HEALING=true
```

---

## 3. 🤖 Configuração da Engine de Inteligência Artificial (Local & Nuvem)

A Engine de IA do GBOC (`ai_diagnostic.py`) oferece análise preditiva de integridade, diagnósticos de causa raiz e sugestões executivas.

| Parâmetro | Valor Padrão | Descrição / Opções |
| :--- | :--- | :--- |
| `AI_PROVIDER` | `auto` | `local` (apenas LLM local), `openai` (nuvem OpenAI), `anthropic` (nuvem Anthropic), `auto` (prioriza nuvem, fallback local/heurístico). |
| `LOCAL_LLM_URL` | `http://localhost:11434/api/generate` | Endpoint REST para LLMs locais executando via Ollama ou LocalAI. |
| `OPENAI_API_KEY` | `""` | Chave de API para integração com GPT-4o / GPT-4o-mini. |
| `AI_AUTO_REMEDIATION` | `true` | Habilita autorrecuperação autônoma orientada por IA para serviços e tarefas estagnadas. |
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
1. **Ransomware Shield v14.0.0**:
   - Cria arquivos canário estratégicos (`.gboc_canary_repos`).
   - Bloqueia automaticamente processos suspeitos que tentem modificar canários em massa.
2. **Duplicati Native Engine**:
   - Suporta autenticação dupla: **JWT Bearer** para Duplicati v2.3+ e **XSRF** para versões legadas v2.0+.
3. **Módulo de Recovery**:
   - Restauração pontual granulada diretamente para pastas locais ou alvos remotos.

---

## 6. 📊 Catálogo e Parâmetros dos 50 Relatórios Avançados

O GBOC expõe 50 relatórios executivos via `/api/v1/reports/catalog` e `/api/v1/reports/generate`:

### Relatórios Principais (IDs 1 a 50):
- **IDs 1 a 30 (Padrão de Mercado)**: Performance de Jobs, Capacidade, Deduplicação, Disponibilidade, Causa Raiz de Falhas, Retenção de Snapshots, Ransomware Shield, Auditoria, SLA RPO/RTO, Custos Cloud, retentativas, DLQ, etc.
- **IDs 31 a 50 (Exclusivos & IA)**: Esgotamento Preditivo de Armazenamento (31), Score Ransomware (32), Custo por GB DR (33), Gap em CDP (34), ROI Synthetic Full (35), Isolamento Multi-tenant (36), Air-Gap Verifier (37), Rotação de Chaves (38), Matriz de Janela de Backup (39), Log de Autorrecuperação (40), Green Backup Efficiency (41), Potencial de Deduplicação (42), Matriz LGPD/GDPR (43), Ativos Críticos (44), Volumes Desprotegidos (45), Impacto de Latência (46), Resiliência Cloud Outage (47), Log de Remediação Preditiva (48), Simulador Bare-Metal (49), ROI & TCO Executivo (50).

---

## 7. ⚙️ Instaladores, Serviços Windows e Desinstalação

### Instalação via PowerShell (Como Administrador)
```powershell
# Agente
cd d:\GBOC-New\GBOC-New\GBOC-Agent
.\install_agent.ps1

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

**GBOC System v14.0.0** — Guia Oficial de Parâmetros e Configuração.
