# 📐 GBOC System v14.6.0 Enterprise — Diretrizes e Políticas de Arquitetura Modular

<!-- Copyright (c) 2026 Master11BR - GBOC System v14.6.0 Enterprise. Todos os direitos reservados. -->

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

## 🗺️ 5. Estrutura Canônica de Navegação (7 Domínios de Negócio)

A interface e as APIs do sistema devem obrigatoriamente refletir a taxonomia de negócio consolidada:

1. **Visão Geral**: Dashboard executivo e telemetria operacional.
2. **Backup**: Jobs e Políticas (`tasks.html`), Cargas Protegidas (`protected-workloads.html` - Bancos, AD, LTO, Enterprise), Repositórios (`repositories.html`), Restaurar e Validar (`restore.html`).
3. **Disaster Recovery**: Prontidão e Plano, Recuperação Instantânea (Instant VM Boot), Bare Metal / P2V e Mídia WinPE (`disaster-recovery.html`), Laboratório Isolado (`virtual-lab`).
4. **Proteção**: Ransomware Guardian (`ransomware.html`), Conformidade (`compliance.html`), Trilha de Auditoria (`audit.html`).
5. **Virtualização e Cloud**: VMware, Hyper-V e Proxmox (`virtualization.html`), Microsoft 365 e Exchange (`m365-exchange.html`), SaaS, Kubernetes e Cloud (`saas-cloud-enterprise.html`), Replicação (`replication.html`).
6. **Operações**: Alertas e Falhas (`alerts.html`, `failed-jobs.html`), Logs Globais (`logs.html`), Diagnóstico Unificado (`diagnostic.html`), Relatórios (`reports.html`).
7. **Configuração**: Usuários e Permissões (`users.html`), Notificações (`notification-channels.html`), Armazenamento (`storage-usage.html`), Motores e Integrações (`engines.html`), Configurações Gerais (`settings.html`).

---

## 🛡️ 6. Política Zero-Mock de Recuperação e Validação Operacional

> ⚠️ **REGRA ZERO-MOCK IMPERATIVA:**
> É estritamente proibido simular estados de saúde, recuperação ou boot de máquinas virtuais. Um ponto de backup só pode ser rotulado como "Recuperável" após validação real na sua respectiva carga:
> 
> 1. **SureRestore & Virtual Lab**: Execução em VM de teste temporária em switch isolado (`GBOC-Isolated-Lab`) com verificação real de heartbeat WMI / Guest Service e teardown seguro. Estados permitidos: `Aprovado`, `Reprovado`, `Inconclusivo`, `Expirado`.
> 2. **Bancos de Dados**: Restauração real em banco temporário isolado. `_test_restore_pg` DEVE falhar explicitamente caso `pg_restore` retorne código != 0; SQLite DEVE executar `PRAGMA integrity_check;`.
> 3. **P2V (Physical-to-Virtual)**: Streaming real de blocos do disco físico ou snapshot VSS para contêiner VHDX com geração de manifesto `.vmconfig.json`.
> 4. **System State & AD**: Execução de `wbadmin start systemstatebackup` e catálogo de consistência NTDS.dit/SYSVOL com manifesto SHA-256 (`dr_manifest.json`).
> 5. **Mídia de Boot**: Extração real de drivers com `Export-WindowsDriver` e compilação de ISO bootável autêntica (proibida a geração de arquivos vazios ou cabeçalhos fictícios).

---

## 🔄 7. Atualização Obrigatória dos Módulos de Distribuição

> ⚠️ **REGRA IMPERATIVA DE BUILD:**
> A cada novo arquivo, módulo ou funcionalidade criada, alterada ou refatorada no código-fonte do sistema (`GBOC-Server` ou `GBOC-Agent`), o script de empacotamento (`build_installer_package.ps1` / `tools/make_distribution.py`) **DEVE ser obrigatoriamente executado**.
> O build executa o gatekeeper `python tools/sync_css.py --verify` e falha imediatamente caso haja qualquer divergência de CSS ou JS compartilhado.

---

## 🎨 8. Arquitetura Universal de CSS & Política Zero CSS Isolado

> 💎 **UNIVERSALIZAÇÃO TOTAL DE CSS EM TODO O ECOSSISTEMA:**
> Todos os estilos visuais, tokens de design, layouts e temas do GBOC System são rigorosamente universalizados e compartilhados entre `GBOC-Server` e `GBOC-Agent`.
> 
> **Stack Padrão Universal de CSS:**
> 1. **`style.css`**: Framework base de componentes universais (Reset, Cards, Botões, Tabelas, Badges, Formulários, Toasts, Loaders e Modais).
> 2. **`gboc-themes.css`**: Design Tokens universais, 8 Estilos de UI (`minimal`, `neumorphism`, `claymorphism`, `fluent`, `nexus-widgets`, `nexus-glass`, `command-sentinel`, `cyber-3d`), 6 Temas de Iluminação (`dark`, `light`, `amber`, `purple`, `ocean`, `red`), Presets Bacula/Fiorilli e Alto Contraste.
> 3. **`gboc-layout.css`**: Motor de Layout Universal (Sidebar Vertical, Topbar Horizontal, Collapse Responsivo e Zero-Overflow em 4K/FHD/HD/Mobile).
> 4. **`gboc-hardware-hud.css`**: HUD Universal de Telemetria de Hardware em Tempo Real.
> 5. **`gboc-file-picker.css`**: Componente Universal de Navegação de Árvore de Diretórios e Arquivos.

---

## 🎬 9. Diretrizes de Motion Principles & UX Engine (Kyle Zantos)

> Toda nova tela ou componente DEVE implementar:
> 1. **Skeleton Screens**: Efeito shimmer durante carregamento assíncrono.
> 2. **Lazy Loading**: `GBOCMotion.initLazyLoading()` para carregamento sob demanda via Intersection Observer.
> 3. **Smooth Animations**: Transições de entrada/saída suaves (`.motion-slide-up`, `.motion-fade-in`).
> 4. **Cancelamento de Requisições**: Utilização de `gbocPerf.makeCancellable()` para abortar requisições em polling ou trocas de contexto.

---

## 📡 10. Observabilidade, Governança & Testes

> - **Sentry & OpenTelemetry**: Rastreamento distribuído e telemetria contínua.
> - **Pytest**: Testes unitários e de integração obrigatórios (Zero-Mock test suite).
> - **Playwright E2E**: Testes End-to-End em navegadores reais.
