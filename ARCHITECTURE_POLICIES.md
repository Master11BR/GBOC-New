# 📐 GBOC System v13.2.0 — Diretrizes e Políticas de Arquitetura Modular

<!-- Copyright (c) 2026 Master11BR - GBOC System v13.2.0 Enterprise. Todos os direitos reservados. -->

Este documento estabelece as **Políticas de Arquitetura Obrigatórias** para o desenvolvimento e manutenção do **GBOC Server** e do **GBOC Agent**.

---

## 🎯 Princípios Fundamentais

1. **Separação Modular Estrita (1 Item de Menu = 1 Módulo Próprio):**
   - É estritamente proibido adicionar novas rotas ou lógicas extensas diretamente nos arquivos de entrada (`server_gboc.py`, `agent_gboc.py`, `dashboard.html`).
   - Cada funcionalidade ou item de menu do painel DEVE residir em seu próprio diretório dentro da pasta `modules/<nome_modulo>/`.

2. **Composição Obrigatória de um Módulo:**
   Cada módulo no `GBOC-Server` deve conter:
   - `<nome_modulo>_router.py`: `APIRouter` FastAPI contendo os endpoints HTTP e lógicas backend daquele domínio.
   - `<nome_modulo>.js`: Arquivo JavaScript contendo exclusivamente as funções e eventos de interface daquela tela.
   - `<nome_modulo>.html`: Fragmento/Template HTML com a estrutura visual da aba ou funcionalidade.

3. **Papel dos Arquivos de Entrada (Entrypoints):**
   - **`server_gboc.py` e `agent_gboc.py`**: Devem atuar apenas como configuradores da aplicação, importando e incluindo os roteadores (`app.include_router(...)`) e montando arquivos estáticos.
   - **`dashboard.html`**: Deve atuar como um Shell Portal (layout principal com sidebar e header), delegando o conteúdo das abas para os fragmentos dos módulos.

4. **Zero Downtime & Preservação de Contratos de API:**
   - Qualquer refatoração ou adição de módulo deve manter a compatibilidade total com os contratos de API existentes (`/api/v1/...`).
   - Respostas de API devem ser sempre JSON válido estruturado, com tratamento de exceções adequado para evitar erros 500 sem tratamento.

---

## 📁 Estrutura de Módulos (GBOC-Server)

```
GBOC-Server/
├── modules/
│   ├── overview/        (overview_router.py, overview.js, overview.html)
│   ├── rmm/             (rmm_router.py, rmm.js, rmm.html)
│   ├── agents/          (agents_router.py, agents.js, agents.html)
│   ├── backups/         (backups_router.py, backups.js, backups.html)
│   ├── surerestore/     (surerestore_router.py, surerestore.js, surerestore.html)
│   ├── multitenant/     (multitenant_router.py, multitenant.js, multitenant.html)
│   ├── analytics/       (analytics_router.py, analytics.js, analytics.html)
│   ├── ransomware/      (ransomware_router.py, ransomware.js, ransomware.html)
│   ├── compliance/      (compliance_router.py, compliance.js, compliance.html)
│   ├── alerts/          (alerts_router.py, alerts.js, alerts.html)
│   ├── job_alert/       (job_alert_router.py, job_alert.js, job_alert.html)
│   ├── storage/         (storage_router.py, storage.js, storage.html)
│   ├── replication/     (replication_router.py, replication.js, replication.html)
│   ├── logs/            (logs_router.py, logs.js, logs.html)
│   ├── reports/         (reports_router.py, reports.js, reports.html)
│   ├── users/           (users_router.py, users.js, users.html)
│   └── config/          (config_router.py, config.js, config.html)
```

---

## 📁 Estrutura de Módulos (GBOC-Agent)

```
GBOC-Agent/
├── modules/
│   ├── rmm/             (rmm_router.py)
│   ├── cbt/             (cbt_router.py)
│   ├── dr/              (dr_router.py)
│   ├── security/        (security_router.py)
│   ├── job_alert/       (job_alert_router.py)
│   ├── storage/         (storage_router.py)
│   ├── logs/            (logs_router.py)
│   └── config/          (config_router.py)
```

---

## ⚠️ Regra para Assistentes de IA e Desenvolvedores
Sempre que for criar uma nova funcionalidade ou ajustar uma existente, identifique o módulo correspondente em `modules/<nome_modulo>/` e faça as alterações nele. Nunca adicione blocos gigantes de código diretamente em `server_gboc.py` ou `dashboard.html`.
