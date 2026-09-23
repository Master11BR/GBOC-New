<!-- Copyright (c) 2026 Master11BR - GBOC System v14.7.0 Enterprise. Todos os direitos reservados. -->

# GBOC — Changelog de Atualizações

> Histórico completo de versões, correções e melhorias do sistema GBOC (Agente + Servidor).

---

## 14.7.0 — 2026-09-22 (Padrão Oficial de Relatórios v3.0 & Zero-Mock Intelligence)

### 📊 Padrão Oficial de Relatórios v3.0 (Contrato JSON Universal & Zero-Mock Estrito)
- **Eliminação de Mocks e Correção dos 10 Bugs Históricos (BUG-01 a BUG-10)**:
  - **`v3_reports_engine.py`**: Motor oficial normativo para o GBOC Agent implementando paridade comercial com Veeam ONE, Rubrik Radar e Datto RMM.
  - **BUG-01 Resolvido**: SLA e RPO calculados individualmente por tarefa (`QUERY_RPO_PER_TASK`), com duração e RTO reais, substituindo "15 min" e status binários por semáforo tri-estado (`CONFORME`, `EM RISCO`, `NÃO CONFORME`).
  - **BUG-02 Resolvido**: Throughput de rede e disco calculados a partir de telemetria real em `task_executions` / `backups`, eliminando taxas fixas (85/72/48 MB/s).
  - **BUG-03 Resolvido**: Poda e retenção alimentadas diretamente de `settings` (`category='retention'`) e eventos reais de `system_logs` (pruning / snapshot removido).
  - **BUG-04 Resolvido**: Dead Letter Queue (DLQ) com contagem real de retentativas e agrupamento de falhas por fingerprint de erro.
  - **BUG-05 Resolvido**: Uptime, PID e consumo de memória coletados em tempo real via `psutil.Process(os.getpid())`, eliminando "PID 4120" e "99.98%" fixos.
  - **BUG-06 Resolvido**: Testes de restauração auditados a partir de eventos reais de restore em `system_logs` e `surebackup_verifications`, eliminando caminhos fictícios `C:\Temp\RestoreTest`.
  - **BUG-07 Resolvido**: Ransomware Shield avaliado com base em canários físicos reais (`ransomware_canaries`), integridade de hash e histórico de alertas.
  - **BUG-08 Resolvido**: Predição de esgotamento de storage por regressão linear (série temporal de 30 a 90 dias) projetando crescimento diário real e data de esgotamento estimada.
  - **BUG-09 Resolvido**: Parecer executivo de IA gerado por template analítico cruzando $\ge 2$ métricas (taxa de sucesso, RTO vs RPO alvo, tendências temporais vs período anterior e ação corretiva imediata).
  - **BUG-10 Resolvido**: Resolução dinâmica e resiliente entre `backups` (SQLite) e `task_executions` (PostgreSQL), garantindo zero queries falhando silenciosamente.
  - **Tratamento de REPs Sem Sensor Local**: REPs 33, 36, 38, 41, 46, 47 retornam expressamente `status: "unavailable"` com diagnóstico e orientações de configuração em vez de números forjados.
- **Higienização de Nomes e Integridade Criptográfica**:
  - Implementação de `_clean_task_name()` para remover sufixos de identificadores automáticos (ex: `_PEZ2B4L6H7L8R9YIIWNV`).
  - Assinatura criptográfica SHA-256 (`integrity_hash`) em todos os payloads JSON gerados.
- **Interface e Visualizador Oficial (`reports.html` & `reports_api.py`)**:
  - Exibição de Scorecard com gauge e semáforo dinâmico.
  - Caixa de Delta analítico ("O que mudou vs período anterior").
  - KPI Cards enriquecidos com Meta/Target e Status Dot coloridos.
  - Seção formal de "Ações Recomendadas" categorizadas por prioridade (`ALTA`, `MÉDIA`, `BAIXA`).
  - Sincronização e extensão com os 7 Relatórios Flagship (`REP-F1` a `REP-F7`).

---

## 14.6.1 — 2026-09-22 (Arquitetura de Relatórios Flagship v2.0 & Inteligência Executiva)

### 📊 Arquitetura de Relatórios Flagship v2.0 (Zero-Mock End-to-End)
- **7 Relatórios Flagship de Mercado (`REP-F1` a `REP-F7`)**:
  - Consolidação dos 50 relatórios originais como **módulos internos de dados** que alimentam 7 relatórios flagship executivos:
    - **`REP-F1` — Data Protection & Resilience Scorecard**: Visão executiva em menos de 10 segundos da proteção da infraestrutura, RPO/RTO individuais, SLA e cobertura de tarefas.
    - **`REP-F2` — Cyber Resilience & Ransomware Threat Report**: Linha do tempo unificada de eventos de segurança, honeypots/canários ativos, proteção WORM e sandbox SureRestore.
    - **`REP-F3` — Storage Intelligence Report**: Saúde dos repositórios, esgotamento preditivo de capacidade, deduplicação FastCDC/ZSTD real e custo cloud projetado.
    - **`REP-F4` — Compliance & Governance Report**: Auditoria de SLA em minutos, políticas de retenção/descarte, requisitos LGPD/GDPR e trilha de auditoria administrativa.
    - **`REP-F5` — Operational Performance Report**: Telemetria individual de execuções (sem médias agregadas por linha), comparativo entre motores e causa raiz de falhas.
    - **`REP-F6` — FinOps & Total Cost of Ownership Report**: TCO detalhado com cotação em tempo real USD→BRL (Banco Central), oportunidades de economia e eficiência energética.
    - **`REP-F7` — Disaster Recovery Readiness Report**: Matriz de prontidão para DR, gaps reais vs metas de RTO/RPO por ativo crítico, estimativa Bare-Metal e simulação de contingência.
- **Filosofia de Design & Estrutura Universal**:
  - **Score único por tela** (0–100) com componentes ponderados.
  - **Delta ("O que mudou")**: 3 bullets automáticos comparando com período anterior (↑ melhoria, ↓ atenção, → tendência dominante).
  - **KPI Cards com Benchmark Embutido**: Valor Real, Alvo e Semáforo de Status (CONFORME, EM RISCO, NÃO CONFORME).
  - **Narrativa antes da tabela**: Frase-síntese de IA antes de cada tabela analítica.
  - **Dados reais e individuais**: Métricas individuais por tarefa/repositório, proibindo repetição de médias globais por linha e ocultando IDs brutos internos.
  - **Ações recomendadas obrigatórias priorizadas**: Bloco priorizado (`[ALTA]`, `[MÉDIA]`, `[BAIXA]`) com responsável sugerido e prazo estimado.
  - **Hash SHA-256 e Assinatura Digital**: Cabeçalho e rodapé oficiais com integridade criptográfica SHA-256 e grid formal de assinatura técnica para documentos A4.
- **Implementação Multi-Plataforma Simétrica (Server & Agent)**:
  - Backend e rotas `/api/v1/reports/flagships` e `/api/reports/flagships` em ambos os sistemas.
  - Interface visual com alternador ágil entre os 7 Flagships e os 50 módulos internos de dados em ambos os painéis.
  - 4 formatos de saída padronizados: HTML Interativo, PDF/A4 Oficial, CSV Tabular e JSON REST API.

---

## 14.6.0 — 2026-09-20 (Operational Backup, Disaster Recovery & Canonical 7-Domain Architecture Release)

### 🛡️ Arquitetura Operacional de Backup & Disaster Recovery (Zero-Mock End-to-End)
- **Validação Operacional Real em Sandbox Hyper-V (`SureRestore` & `Virtual Lab`)**:
  - Implementação do ciclo completo de teste de recuperabilidade: Restauração -> Criação de VM Hyper-V em switch isolado (`GBOC-VirtualLab-Switch` / `GBOC-SureRestore-Switch`) -> Boot -> Validação de heartbeat -> Coleta de evidência -> Desmontagem segura.
  - Zero simulações: sem Hyper-V habilitado no host, o sistema reporta explicitamente a indisponibilidade do hypervisor ao invés de forjar status "OK".
- **Validação Específica por Tipo de Carga de Trabalho**:
  - **Bancos de Dados PostgreSQL**: Validação através de `pg_restore --list` e restauração real em schema temporário, falhando imediatamente caso o código de saída seja diferente de zero ou contenha erros estruturais.
  - **Bancos de Dados SQLite**: Execução real de `PRAGMA integrity_check` e `PRAGMA foreign_key_check` sobre o arquivo restaurado, capturando corrupções reais.
  - **System State & Bare-Metal**: Verificação física de componentes críticos (`wbadmin`, `NTDS`, `SYSVOL`, `Registry hives`) e drivers de boot WinPE sem fabricação de cabeçalhos.
  - **Conversão P2V em Bloco**: Conversão física de volumes locais para disco virtual VHDX com validação prévia de privilégios de Administrador e streaming contínuo.

### 🧭 Reestruturação Canônica de Navegação em 7 Domínios
- **Navegação Modular Baseada em Operações de Negócio (`sidebar.js` & `_topbar.html`)**:
  - Reorganização de todas as rotas do Agent e Server nos 7 domínios canônicos corporativos:
    1. **Visão Geral**: Dashboard executivo, Overview e Auditoria/Logs.
    2. **Backup**: Jobs, Políticas, Histórico, Repositórios e Agendamento.
    3. **Disaster Recovery**: SureRestore, Virtual Lab, Failover, P2V e Live Recovery.
    4. **Proteção**: Cargas Corporativas Consolidadas (Databases, Active Directory, Tape Library, Enterprise).
    5. **Virtualização & Cloud**: Hyper-V, VMware, Cloud Storages e Object Storage (S3/Azure).
    6. **Operações**: Monitor de Tarefas em tempo real, HUD de Telemetria e Alertas.
    7. **Configuração**: Configurações Globais, Credenciais, Notificações, Atualizações e Estilos visuais.
- **Consolidação de Workloads Protegidos (`protected-workloads.html`)**:
  - Fusão e unificação de telas legadas dispersas em uma única interface moderna com deep-linking (`#databases`, `#activedirectory`, `#tape`, `#enterprise`) e redirecionamentos transparentes mantendo retrocompatibilidade total.

### ⚡ Otimização de Performance e Integridade do Frontend
- **Safe HTML Rendering com Diff Completo (`gboc-perf.js`)**:
  - Substituição da verificação de tamanho parcial por comparação estrita de string (`safeRender`), evitando inconsistências visuais em atualizações parciais de HTML.
- **Cancelamento de Requisições Obsoletas (`gbocPerf.makeCancellable()`)**:
  - Suporte a `AbortController` nas rotinas de polling e navegação, prevenindo concorrência desnecessária no backend.
- **Saneamento do Monitor de Tarefas (`task_monitor.js`)**:
  - Remoção de declarações corrompidas e unificação de inicialização segura do monitor em tempo real.

### 📦 Distribuição & Padronização Global
- **Sincronização Canônica Universal & Unificação Estrita de Versão (Single Source of Truth)**:
  - Erradicação de literais de versão legada (`14.1.0`, `14.2.0`, `14.4.0`, `14.5.0`) em todos os endpoints (`/api/system/info`, `/api/system/version`, `/api/v2/system/version`), scripts e modelos HTML.
  - Varredura e consolidação de mais de 335 arquivos para a versão canônica **v14.6.0 Full Stable Enterprise**.
  - Redesenho completo do motor de relatórios executivos com diagramação A4 de alta fidelidade para impressão/PDF, hash de auditoria SHA-256 e scorecards de KPI reais.
  - Atualização dos scripts de build e distribuição (`build_installer_package.ps1`, `tools/make_distribution.py`, `Setup.ps1`).

---

## 14.5.0 — 2026-09-18 (Universal CSS Architecture, Enterprise Modal System, V7 Authentication UI & Duplicati Cloud Stabilization)

### 🎨 Arquitetura Universal de CSS (100% Shared Stack & Zero CSS Isolado)
- **Unificação Estrita de Folhas de Estilo (`GBOC-Server` & `GBOC-Agent/static/`)**:
  - Sincronização e padronização dos 5 arquivos centrais da stack universal:
    1. `style.css`: Framework de componentes universais (Reset, Cards, Botões, Tabelas, Badges, Formulários, Toasts e Modais).
    2. `gboc-themes.css`: Design tokens globais, 8 Estilos de UI (`minimal`, `neumorphism`, `claymorphism`, `fluent`, `nexus-widgets`, `nexus-glass`, `command-sentinel`, `cyber-3d`), 6 Temas de Iluminação (`dark`, `light`, `amber`, `purple`, `ocean`, `red`), Presets Bacula/Fiorilli e tokens de alto contraste para Light Mode.
    3. `gboc-layout.css`: Layout responsivo universal (Sidebar Vertical + Topbar Horizontal).
    4. `gboc-hardware-hud.css`: HUD de telemetria física de hardware em tempo real.
    5. `gboc-file-picker.css`: Explorador universal de arquivos e diretórios.
  - Varredura e padronização automatizada de todas as **53 páginas HTML** do ecossistema para carregar a stack canônica compartilhada.
  - Eliminação completa de arquivos CSS órfãos, regras divergentes ou estilos embutidos sem tokenização.

### 💬 Sistema Corporativo Universal de Modais & Caixas de Diálogo (`gboc-modal.js`)
- **Interceptador Global e Transparente para `alert()`, `confirm()` e `prompt()`**:
  - Substituição automática das caixas de diálogo nativas e síncronas do navegador por modais modernos baseados em DOM e Promises assíncronas.
  - Design sofisticado com fundo translúcido (`backdrop-blur-md`), elevação de card, bordas sutis e tipografia padronizada.
  - Detecção inteligente de contexto e severidade com base em palavras-chave e emojis (*sucesso, erro, falha, atenção, aviso, info*).
  - Acessibilidade integral com navegação por teclado (`Enter` para confirmar, `Escape` para fechar) e foco inteligente em campos de input.

### 🔐 Interface Visual de Autenticação V7 (Dark Glassmorphism)
- **Novo Design Unificado (`GBOC-Server/login.html` e `GBOC-Agent/static/login.html`)**:
  - Implementação de layout sofisticado em Tailwind CSS com fundo dark (`zinc-900/70`), blur de vidro de alta definição (`backdrop-blur-2xl`) e paleta dourada/âmbar (`amber-500` / `yellow-500`).
  - Navegação suave por abas entre **Sign In (Login)** e **Create Account (Setup / Primeiro Acesso)**.
  - Alternador dinâmico de visibilidade de senhas (*Eye Toggle*) em tempo real.
  - Suporte à persistência de usuário com caixa de seleção *"Lembrar credencial"* via `localStorage`.
- **Modo Setup / Provisionamento Inicial Automático**:
  - Detecção no frontend de instâncias sem administradores cadastrados (`/status`).
  - Redirecionamento automático e exibição de banner informativo para a criação da credencial master do administrador (`/setup`).
  - Auto-login transparente logo após a conclusão do cadastro inicial com persistência dos tokens corporativos (`gboc_server_token` / `gboc_token`).
- **Política Zero-Mock & Conformidade LGPD**:
  - Eliminação de botões de login social simulados (Google/Apple).
  - Adição de badges de segurança real com base nas capacidades criptográficas ativas do sistema (*Criptografia SHA-256 / PBKDF2* e *Auditoria Ativa*).

### 🛠️ Correções Críticas no Motor de Importação Duplicati
- **Suporte Total a Repositórios Cloud (`task_manager.py`, `repository_manager.py`, `real_restore_manager.py`, `integrity_api.py`)**:
  - Normalização completa para tipos de repositório `cloud` suportados pelo Duplicati nativo (`s3`, `azure`, `googledrive`, `onedrive`, `dropbox`, `webdav`, `sftp`).
  - Eliminação da exceção `Tipo de repositório Duplicati não suportado: cloud`.
- **Auto-Recuperação de Banco Duplicati Corrompido (`DatabaseRepairInProgress`)**:
  - Detecção preventiva e deleção segura de bancos SQLite locais corrompidos ou com reparo incompleto antes de acionar a rotina `repair` do executável nativo do Duplicati.
  - Garantia de recriação limpa do catálogo de metadados sem interrupção do pipeline de backup ou importação.

### 📦 Distribuição & Versionamento
- **Atualização SemVer 2.0 Global**:
  - Elevação do versionamento canônico para **v14.5.0 Full Stable Enterprise** em todos os módulos centrais.
  - Atualização automática do manifesto `package_manifest.json` e dos instaladores `Setup.bat` / `Setup.ps1`.

---

## 14.4.0 — 2026-09-14 (Performance & Resilience Release — Zero-Freeze Async Engine, Disaster Recovery Acceleration & Hardware HUD)

### 🚀 Zero-Freeze Async Engine Architecture
- **Desacoplamento Assíncrono (`asyncio.to_thread`) (`modules/dr/dr_router.py` & `modules/virtualization/virtualization_router.py`)**:
  - Eliminação definitiva de travamentos e bloqueios na interface ao navegar para `/virtualization.html` e `/disaster-recovery.html`.
  - Todas as chamadas síncronas de baixo nível ao sistema operacional e subprocessos agora são executadas em *worker threads*, mantendo o Event Loop do FastAPI 100% responsivo para tráfego web, WebSockets e pings de telemetria.
- **Cache TTL em Memória Thread-Safe (`disaster_recovery_engine.py` & `vmware_hypervisor_engine.py`)**:
  - Implementação de cache em memória thread-safe (30s) para topologia de discos (`_disks_cache`), informações do Active Directory / VSS (`_sys_info_cache`), readiness score (`_readiness_cache`) e inventário Hyper-V (`_vms_cache`).
  - O tempo de resposta em requisições concorrentes ou subsequentes dentro da janela de TTL caiu de 48.9s para **0.005ms (instantâneo / 0ms)**.
- **Consulta Batch em Lote Único de Discos e Partições**:
  - Substituição do loop sequencial com múltiplos processos `powershell.exe` por uma única consulta unificada PowerShell para todos os discos físicos e partições de uma vez só.
  - Tempo de descoberta de armazenamento reduzido de **16.33s para 3.38s** (-79%).
- **Detecção Sub-Milissegundo de Active Directory & Hyper-V**:
  - Substituição de scripts PowerShell lentos pela API nativa de Registro do Windows (`winreg`) para verificar a chave `Services\NTDS` (execução em **0.05ms**).
  - Validação ultrarrápida do serviço Hyper-V (`vmms`) via `sc.exe query vmms` em apenas **0.19s** (anteriormente ~1.2s via PowerShell).

### 📟 Integração Global do Hardware & S.M.A.R.T. HUD
- **Conexão Direta aos Dashboards & Overview (`index.html`, `dashboard.html`, `overview.html`)**:
  - Inclusão oficial dos módulos `gboc-hardware-hud.css` e `gboc-hardware-hud.js`.
  - Medidores e gauges de CPU, Memória RAM e Storage tornados interativos (`cursor: pointer`, tooltip e acionamento de `toggleHardwareHUD()` ao clique).
  - Adição de botão dedicado de acesso rápido no grid de ações operacionais.

### 🧹 Otimização e Estabilidade do Frontend
- **Limpeza de Scripts & Inicializações Redundantes (`virtualization.html` & `disaster-recovery.js`)**:
  - Remoção de tags duplicadas de `sidebar.js`.
  - Eliminação de chamadas manuais redundantes a `new UnifiedSidebar().initialize()`, evitando duplicação de listeners e recriação indevida do DOM.
  - Adição de spinner de loading dinâmico com mensagem de status na listagem de máquinas virtuais Hyper-V locais.

### 📦 Distribuição & Empacotamento
- **Atualização do Manifesto & Instaladores (`tools/make_distribution.py`, `package_manifest.json`)**:
  - Sincronização automática para a versão canônica `14.4.0 Full Stable Enterprise` nos instaladores `Setup.bat` e `Setup.ps1`.

---

## 14.3.0 — 2026-09-14 (Major UI/UX Model Release — Official Modern Model, Design System Tokens, UnoCSS & Menu Acceleration)

### 🎨 Modelo Visual Oficial Moderno (`modern`) & Backend Contract
- **Contrato Explícito de UI Model (`server_gboc.py`, `agent_gboc.py` & `gboc-layout-manager.js`)**:
  - Definição estrita das constantes globais `UI_MODEL = "modern"`, `ACTIVE_UI_MODEL = "modern"` e `DEFAULT_UI_MODEL = "modern"`.
  - Implementação de fallback determinístico no motor JS: requisições a modelos inexistentes ou legados desativados revertem automaticamente para `modern` e registram alerta no console.
  - Disponibilização do endpoint `/api/v1/system/ui-config` no Servidor e no Agente com estado estruturado dos modelos, temas e estilos de componentes.
- **Desativação de Opções Legadas Quebradas**:
  - Remoção de seletores ou links para modelos legados inconsistentes do painel "Personalizar Interface", exibindo o selo inequívoco **MODELO UI ATIVO: Modern UI (Padrão Oficial)**.

### 📐 Arquitetura Modular CSS & Infraestrutura UnoCSS
- **Estrutura de Arquivos Modular (`static/ui/`)**:
  - `tokens.css`: Centralização de variáveis globais de iluminação (`dark`, `light`, `purple`, `ocean`), tipografia, raios de borda e aliases de compatibilidade (`--border`, `--text`, `--bg-dark`).
  - `unocss-ds.css`: Utilitários atômicos UnoCSS, shortcuts de cards/botões/inputs e animação skeleton loader conforme os Princípios de Movimento Kyle Zantos.
  - `model.css`, `components.css`, `layout.css` sob `static/ui/models/modern/`: Isolamento do Modelo UI Moderno com suporte aos 4 formatos de componentes (`minimal`, `neumorphism`, `claymorphism`, `fluent`).

### ⚡ Otimização do Menu Principal do Agente
- **Performance de Carregamento (< 5ms) (`sidebar.js`)**:
  - Implementação do cache em memória `__gbocSidebarMemoryCache` para renderização instantânea da barra lateral.
  - Eliminação de requisições HTTP redundantes e unificação do `MutationObserver` no DOM.

### 🖥️ Padronização das Telas Iniciais
- **Harmonização do Dashboard & Tela Inicial (`dashboard.html` & `index.html`)**:
  - Configuração estrita da tag `<html data-ui-model="modern">` e sincronização dos estilos com o Design System central.

### 🤖 Auto-Diagnóstico de IA com Telemetria Real & Ações Passo a Passo ("O que fazer exatamente")
- **Eliminação de Mensagens Genéricas (`ai_diagnostic_engine.py`, `ai_v2_router.py`)**:
  - Remoção completa de respostas genéricas estáticas (*"Erro detectado: 'Diagnóstico geral...'"*).
  - Coleta automática de telemetria 100% real do host operacional (`CPU`, `RAM`, `Disco`, `Status BD`, `Jobs com Trava`) via `psutil`.
  - Estruturação padronizada das respostas do assistente em 3 seções obrigatórias:
    1. 🔍 **Causa Raiz Técnica & Telemetria Real**
    2. 🛠️ **O Que Fazer Exatamente (Passo a Passo)** (instruções operacionais numeradas e claras)
    3. ⚡ **Executar Correção Automática (Auto-Heal)** (integrado ao endpoint `/api/v2/system/auto-heal` e botão em 1 clique).
- **Interface dos Modais de Diagnóstico (`dashboard.html` & `index.html`)**:
  - Modal do assistente de IA atualizado para renderizar badges de saúde por cor, diagnósticos de causa raiz e ações corretivas de Auto-Heal automatizadas.

### 🎨 Troca Dinâmica em Tempo Real dos 4 Estilos de Componentes UI/UX
- **Vinculação Global de CSS Tokens (`gboc-themes.css`)**:
  - Correção dos seletores CSS globais `.card`, `.panel`, `.stat-card`, `.kpi-card`, `.dashboard-card`, `.data-card`, `.quick-action-card`, `.modal-card`, `.widget`, `.form-control`, `.input` e `.btn`.
  - Todos os componentes visuais agora herdam instantaneamente as variáveis CSS de design tokens (`--card-radius`, `--card-border`, `--card-shadow`, `--card-backdrop`, `--card-bg`, `--input-shadow`, `--btn-shadow`).
  - Permite a alternância imediata em tempo real no navegador entre os 4 estilos visuais: **SaaS Minimal**, **Neumorphism (Soft UI)**, **3D Claymorphism** e **Fluent Design (Microsoft Acrylic Glass)**.

### 🔗 Padronização Estrita da API v2 (`/api/v2/`)
- **Endpoints de Sistema e IA (`system_v2_router.py`, `ai_v2_router.py`)**:
  - Inclusão dos endpoints oficiais `/api/v2/system/ui-config`, `/api/v2/system/version`, `/api/v2/ai/diagnose` e `/api/v2/system/auto-heal`.
  - Todas as respostas envelopadas no padrão `build_v2_response` com metadados de execução (`execution_time_ms`, `timestamp`, `version`).

### 📦 Pacote de Distribuição
- **Pacote de Instalação (`build_installer_package.ps1`)**:
  - Atualização do gerador de distribuição mantendo a pasta externa `GBOC-Distribution` 100% sincronizada.

---

### 💾 Consumo de Armazenamento por Motor (Local vs. Destino)
- **Detalhamento de Armazenamento por Motor (`storage_monitor.py` & `storage_router.py`)**:
  - Implementada agregação de dados por motor de backup (`by_engine`: Restic, Kopia, Duplicati, Borg, Nativo, Hermes).
  - Cálculo empírico e exposição de consumo físico no disco local (`local_gb`) e consumo no destino remoto de armazenamento (`destination_gb`), além de métricas gerais e contagem de repositórios.
- **Painel Visual na GUI (`storage-usage.html` & `storage.html`)**:
  - Adicionado painel visual **"Consumo de Armazenamento por Motor (Local vs. Destino)"** com cards comparativos por motor.
  - Atualização dos cards de repositórios individuais exibindo localização local e destino de replicação.

### ⚡ Replicação Local (Estabilização e Correção de Travamento)
- **Resolução de Porta e Roteamento (`gboc-layout-manager.js`)**:
  - Corrigida a identificação `isAgent` para cobrir a porta `9200` e as páginas `/replication.html`, `/failed-jobs.html` e `/storage-usage.html`. Isso impede que a página tente carregar a API da porta 8000 do Servidor quando executada no Agente.
- **Flexibilização do Banco de Dados (`backup_replicator.py` & `replication_api.py`)**:
  - Atualizado o schema da tabela `replication_policies` para aceitar `target_repo_id DEFAULT 0`, adicionando suporte nativo às colunas `dest_type`, `dest_path`, `mode`, `status` e `total_bytes` com migrações defensivas `ALTER TABLE IF NOT EXISTS`.

### 📌 Jobs com Falha (Reposicionamento de Menu & Standard Layout)
- **Reorganização de Menu (`_sidebar.html`)**:
  - Transferência do módulo **Jobs com Falha** da área de *Tarefas & Motores* para a seção **Diagnóstico & Logs**, abaixo de *Central de Alertas*.
- **Padronização Visual (`failed-jobs.html`)**:
  - Refatoração da página `failed-jobs.html` para o layout standard com suporte a temas CSS (`var(--bg-card)`, `var(--border)`), KPIs responsivos e modal overlay centralizado.

### 🛡️ Resiliência e Logs Imunes no Windows (`SafeRotatingFileHandler`)
- **Imunidade a PermissionError**:
  - Implementada a subclasse `SafeRotatingFileHandler` em `agent_gboc.py`, `logger.py` e `task_manager.py` para ignorar travamentos de arquivo de log no Windows.
- **Filtro Anti-Recursão**:
  - Adicionado filtro de supressão no redirecionador `sys.stderr` contra erros de rotação de log para prevenir tempestades de exceção no console.

### 🚀 Otimização do Hermes Engine
- **Cache em Memória (TTL 60s)**:
  - Adicionada camada de cache para a checagem de VSS Writers (`vssadmin`), reduzindo drasticamente o tempo de resposta do endpoint `/api/v1/hermes/status`.

---

## 14.1.0 — 2026-08-08 (Patch Release — Hotfixes de Navegação, Validação e Ransomware)

### 🛠️ Correções de UX, Roteamento e UI
- **Roteamento Estático no Agente (`agent_server.py`)**:
  - Corrigida a prioridade de busca de caminhos de arquivos HTML no roteador de fallback. Agora as requisições para `/tasks.html`, `/repositories.html` e `/duplicati-native.html` buscam os arquivos correspondentes na pasta `static/` antes de reverter para a tela inicial (`index.html`). Isso resolve o bug em que clicar nas opções do menu redirecionava o usuário de volta ao dashboard inicial.
- **Detecção de Nome do Motor na UI (`engines.html`)**:
  - Corrigido o título dos cards dos motores locais que mostravam `undefined`. Substituído `engine.display_name` por `engine.name` no template do card, casando com a propriedade real retornada pela API do Agente.

### 🔒 Segurança, Otimizações de Desempenho e Sentinel
- **Otimização de Varredura de Ransomware (`ransomware_detector.py`)**:
  - Otimizada a função `calculate_directory_entropy` e `scan_for_suspicious_extensions` adicionando condições de parada `break` no loop externo do `os.walk` após atingir o limite `max_files`, interrompendo instantaneamente a travessia de diretórios gigantes.
  - Otimizada a varredura do motor YARA (`scan_with_yara`), adicionando um limite estrito de escaneamento de até 100 arquivos e ignorando arquivos com tamanho maior que 10 MB (evitando processamento e leitura de blocos binários gigantes). Isso resolve o problema de travamento ("módulo guardian travado") que ocorria quando o watchdog rodava a stack de segurança sobre a pasta de dados.

### 🔌 Paridade de Senhas e Validação de Motores
- **Recuperação Resiliente de Senhas no Agente (`repository_manager.py`)**:
  - Unificação de todos os campos possíveis de senha de criptografia (`motor_password`, `encryption_password`, `password`, `cloud_password`) no método de normalização. Ao obter a configuração de um repositório, o Agente agora consolida e garante que todos os campos de credenciais estejam disponíveis, corrigindo falhas na validação ou no teste de conexões de repositórios que ocorriam por divergência ou ausência da coluna exata de senha.

### 📈 Versionamento
- **Versionamento Semântico (SemVer)**:
  - Incremento global de versão para **14.1.0** em todos os arquivos de configuração de versão e templates usando `version_unifier.py` e atualização do `BUILD_DATE` para **2026-08-08**.

---

## 14.1.0 — 2026-08-05 (Minor Release — Módulos GUI Storage & Job Alert)

### 🚀 Novos Módulos e Funcionalidades
- **Módulo GUI Storage Usage & Growth (`modules/storage`)**:
  - Implementação do backend (`storage_router.py`), frontend JS (`storage.js`) e componente HTML (`storage.html`) no Servidor Central (`GBOC-Server`) e no Agente (`GBOC-Agent`).
  - Coleta em tempo real de estatísticas e capacidade dos volumes usando dados empíricos do sistema (`shutil.disk_usage`) com gráfico de crescimento (Chart.js).
- **Módulo GUI Job Failure & Alert Monitor (`modules/job_alert`)**:
  - Implementação do backend (`job_alert_router.py`), frontend JS (`job_alert.js`) e componente HTML (`job_alert.html`) no Servidor Central (`GBOC-Server`) e no Agente (`GBOC-Agent`).
  - Centralização de falhas de jobs ativas, retentativas, botão de marcar como resolvido e testes de envio de alertas em canais configurados.

### 🛠️ Correções de UX e Arquitetura
- **Correção dos Submenus Sanfona da Sidebar**:
  - Exportação global das funções `window.toggleNavGroup` e `window.initNavGroups` em `sidebar.js`, resolvendo o bloqueio de execução de scripts dinâmicos inseridos via `insertAdjacentHTML`.
- **Conformidade Estrita com AGENTS.md / ARCHITECTURE_POLICIES.md**:
  - Reorganização dos roteadores de `api/` para `modules/storage/storage_router.py` e `modules/job_alert/job_alert_router.py` (`1 Módulo = 1 Diretório`).
- **Versionamento Semântico (SemVer)**:
  - Incremento global para **14.1.0** via `version_control.py` e `version_unifier.py`.

---

## 14.1.0 — 2026-08 (Versão Consolidada Pós-Recuperação)

### 🚀 Destaques da Release

- **Unificação Geral de Versão (14.1.0)**: Sincronização completa de todos os módulos (`GBOC-Server`, `GBOC-Agent`, `SharedCore`, `Ransomware Shield`, `Diagnostic System` e `version_unifier.py`).
- **Recuperação e Consolidação de Código**: Restauração da base de código (recuperada após perda por falha de disco), consolidando todas as melhorias até Agosto de 2026.
- **Suporte Pydantic v2**: Atualização dos validadores de modelos Pydantic no `GBOC-Server`.
- **Estabilidade nos Testes**: Correção de codificação UTF-8 no Windows e ajuste de asserções assíncronas na Dead Letter Queue (`tests.py`).
- **Documentação Mestra**: Reformulação total do `README.md` principal na raiz e atualização do `INSTALADORES_README.md`.

---

## 14.1.0 — 2026-04

### 🧩 UI e Navegação

- **Página `config-manager.html`** criada — interface completa para `config_api.py`:
  - export atual (preview + download JSON)
  - import manual e upload JSON
  - snapshots de configuração
  - download/visualização/exclusão de snapshots
  - diff entre snapshots e diff snapshot vs config atual
- **Sidebar atualizada**:
  - versão visual `GBOC 14.1.0`
  - novo item **Config Manager** no menu
- **Unificação de páginas legadas**:
  - `overview.html` agora redireciona para `/`
  - `statistics.html` agora redireciona para `/`
  - evita duplicidade com o Dashboard principal

### 🧭 Correções de UX (Tarefas/Replicação/Sidebar)

- **Seletor de pasta em Tarefas** (`tasks.html` + `api/fs.py`):
  - corrigido travamento em loop após cancelar/voltar seleção
  - reset de estado do browser ao abrir/fechar modal
  - fallback automático para raiz quando caminho anterior não existe (ex.: drive removido)
  - listagem de drives no Windows ajustada para evitar bloqueio em unidades offline
  - correção para permitir selecionar a pasta atual quando não há subpastas
- **Replicação** (`replication.html`):
  - adicionada opção de **selecionar pasta do servidor** quando destino = diretório local
  - removido script legado duplicado que chamava endpoint inexistente (`/api/files`)
  - corrigidos erros JS que travavam tela em "Carregando..."
- **Sidebar** (`sidebar.js` + `style.css` + `_sidebar.html`):
  - corrigida marcação de módulo ativo (não fica preso em Diagnóstico)
  - corrigida seleção ativa ao clicar em ícone/texto do link
  - proteção contra dupla inicialização do sidebar
  - adicionado scroll vertical quando menu excede a altura da tela
  - botão de tema reposicionado para não sobrepor itens do menu

### 🧩 Correções Funcionais (Integridade/Config/Timezone)

- **Restore (Quick Win - snapshots intermitentes)**:
  - corrigida identificação de snapshots Restic no módulo de restauração (`real_restore_manager`): operações agora usam `full_id` internamente para evitar ambiguidades de `short_id`
  - `restore.js` atualizado para exibir `short_id` apenas como label visual, mantendo `full_id` como valor selecionado
  - efeito prático: snapshots que antes falhavam de forma intermitente agora restauram corretamente no módulo de Restore

- **Restore (diagnóstico quick win, baixo risco)**:
  - novo endpoint `GET /api/restore/diagnose/{repo_id}` para diagnóstico rápido de listagem de snapshots
  - novo botão **Diagnosticar Snapshots** em `restore.html`
  - `restore.js` agora exibe erro + dica objetiva (senha inválida, path/bucket/prefix incorreto, permissão)

- **Motores em Tarefas (consistência corrigida)**:
  - listagem de tarefas agora traz `repository_engine` no backend
  - UI de tarefas exibe separadamente **Engine da Tarefa** e **Engine do Repositório**
  - seleção de repositório no modal sincroniza automaticamente o campo de engine
  - execução força engine do repositório quando detectar divergência (com log de warning)
  - adicionada compatibilidade com schema legado (fallback sem `repository_engine`) para não quebrar carregamento da página

- **Audit Trail funcional** (`audit.html`):
  - UI ajustada para o formato real da API (`entries`, `summary.daily_activity/users/actions`)
  - KPIs e tabela agora carregam dados corretamente
  - export CSV mantém funcionamento

- **Edição de Repositório (senhas preservadas)**:
  - corrigido bug em que `motor_password`/credenciais cloud podiam ser sobrescritas com vazio ao editar sem alterar senha
  - frontend agora só envia `access_key/secret_key` quando usuário realmente informa novo valor
  - backend ignora `motor_password/cloud_password` vazios em updates

- **Exclusão de Repositório (FK + limpeza multi-motor)**:
  - corrigido erro 500 ao excluir repositório com histórico em `integrity_checks` (`integrity_checks_repository_id_fkey`)
  - exclusão agora remove dependências por `repository_id` em ordem segura (`integrity_checks`, `restore_history`, `tasks`) antes de remover `repositories`
  - adicionada limpeza de artefatos de motores na exclusão (ex.: `data/kopia_configs/*.config` relacionados ao repositório), não ficando restrita ao GBOC Native
  - `database_migrator.py` agora força `ON DELETE CASCADE` na FK `integrity_checks.repository_id -> repositories.id` para prevenir bloqueios futuros
  - novo script `scripts/force_cleanup_external_engines.ps1` para limpeza forçada de artefatos de motores externos em cenários de falha operacional
  - script de limpeza forçada agora suporta `-ForceKill` para encerrar processos `kopia/restic/duplicati` antes da remoção

- **Versionamento de scripts (.bat/.ps1) atualizado**:
  - `start_agent.bat` e `start_agent.ps1`: v14.1.0 → **14.1.0**
  - scripts de instalação/diagnóstico em `scripts/`: padronizados para **14.1.0**

- **Server Dashboard Analytics (correções)**:
  - corrigido erro JS `ReferenceError: rjson is not defined` em `loadLogAgentFilter()`
  - restaurada formatação visual dos blocos de alertas/diagnóstico/trends no tab Analytics

- **Quick Wins adicionais (estabilidade UI/API)**:
  - `tasks.html`: hardening de bootstrap (fallback para módulos auxiliares ausentes) e restauração de funções mínimas para evitar travamento em "Carregando tarefas..."
  - `reports.html`: arquivo restaurado (script completo), sidebar preservada no módulo e fluxo de geração/download/agendamento/histórico reativado
  - `api/reports_api.py`: geração sob demanda agora grava `report_history` (sucesso/erro) para exibir todos os relatórios no histórico
  - `integrity.html`: falhas exibem resumo e botão **Ver erro** com detalhes do check
  - `api/auth.py`: Audit Trail passa a registrar login sucesso/falha (`auth.login`) para filtros funcionarem
  - `api/repositories.py`: endpoint de teste usa validação detalhada (mensagem real de erro), reduzindo falso positivo
  - **Servidor Central**: sessão agora é invalidada no startup (limpa `server_auth_tokens`) para exigir novo login após reinício
  - **Shutdown controlado**: adicionados endpoints locais de encerramento (`/api/system/shutdown` no Agent e `/api/v1/system/shutdown` no Server)
  - novo script `scripts/shutdown_gboc.ps1` para desligar Agent/Server via API com fallback opcional `-ForceKill`
  - **Tarefas**: browser de pastas restaurado (`btn-browse-folders`) com navegação, seleção e inserção de caminho no campo `paths`
  - **Revisão funcional geral concluída**: validação sintática dos módulos críticos OK e smoke tests atualizados/passando (`tests/test_repository_loading.py`, `tests/test_app.py`) para base pronta a novas implementações
  - **Hardening de obsolescência/segurança**:
    - `api/import_api.py`: removido fallback legado para `engines.real_backup_importer` (obsoleto)
    - `api/diagnostics.py`: removidas respostas simuladas em criptografia/segurança; diagnóstico agora usa dados reais de repositórios e tempo real de execução no quick diagnostic
    - `api/diagnostics.py`: helpers internos reparados para evitar bloco incompleto e garantir estabilidade
    - `gboc_server.py`: cookies de sessão endurecidos (`HttpOnly`, `SameSite=Lax`, `Secure` condicional por HTTPS)
    - `engines/backup_importer.py`: removida escrita sintética no banco (task `999` / execução fake); fluxo convertido para `discovery_only`
    - `api/import_api.py`: removido endpoint legado `/scan-and-import`, mantendo apenas `/scan` (GET/POST)
    - `gboc_server.py`: removidos endpoints legados de auth (`/api/v1/login`, `/api/v1/logout`, `/api/v1/auth/check`) e restabelecido namespace único `/api/v1/auth/*`
    - `gboc_server.py`: removido endpoint simulado `/api/v1/sync/push` e removidos placeholders de sync manual sem implementação
    - `gboc_server.py`: rotinas de sync de full-data agora persistem de forma real (`agent_repositories`, `agent_tasks`, `agent_task_executions`, `system_events`)
    - validação final executada: py_compile (Agent/Server), checagem de tabela de rotas e smoke tests (`test_app.py`, `test_repository_loading.py`) aprovados

- **Integrity UI** (`integrity.html`):
  - status agora lê estrutura real da API (`d.check.status`)
  - histórico atualizado com campos corretos (`finished_at`, `errors_found`)
  - polling automático após iniciar verificação
- **Config Export** (`engines/config_manager.py`):
  - corrigidas queries para schema real (repositories/type, tasks/source_paths/schedule_cron)
  - fallback resiliente para `smtp_config` quando tabela não existir
  - corrigido erro 500 no download `/api/config/export/download`
- **Timezone padronizado**:
  - Agent: padronização global via `auth_interceptor.js` para horário local do cliente (fuso local)
  - Server Dashboard: helper `fmtDateTime()` aplicado aos campos principais
- **Varredura completa de datas (Agent)**:
  - substituídos todos os `new Date(...).toLocaleString(...)` por `gbocFormatDateTime(...)`
  - aplicado em páginas HTML e scripts JS para eliminar divergência UTC/local
- **Integrity Checks (UI) corrigido**:
  - `integrity.html` agora interpreta corretamente retorno de `/api/repositories/` (array direto)
  - lista de repositórios/carregamento de checks voltou a funcionar

### 🎨 Padronização Visual Global (Agent + Server)

- botões, campos de preenchimento e item de menu ativo alinhados ao estilo do login (neumórfico)
- respeitando dark/light theme em Agent e Server

### 🛡️ Ransomware Shield — Prevenção em Tempo Real

- **Módulo `engines/ransomware_shield.py`** reescrito e integrado com 6 correções críticas:
  - Fix `VSSGuard._scan_processes()` — `proc.info` é dict, não callable (crash `TypeError`)
  - Fix `_calculate_entropy()` — fórmula Shannon corrigida (`math.log2` em vez de `float.bit_length()`)
  - Fix `signal.signal()` — crash em thread secundária (guard com `try/except ValueError`)
  - Fix `setup_logging()` — não sobrescreve mais o root logger do GBOC (logger dedicado `GBOC.Shield`)
  - Fix `Config` — adicionados `vss_guard_enabled`, `enabled`, `auto_isolate_network` ao `DEFAULT_CONFIG`
  - Fix re-start — `_stop_event.clear()` no `start()` para permitir stop/start sem restart do processo
- **Singleton `get_shield()`** adicionado para compatibilidade com `ransomware_api.py`
- **Integração com Guardian** — ameaças `critical` acionam cadeia completa (snapshot, lock, notificações)
- **Integração com banco de dados** — ameaças registradas na tabela `alerts`
- **6 endpoints REST** adicionados: `shield/status`, `start`, `stop`, `config`, `path/add`, `threats`
- **Startup integrado** — Shield carrega no `agent_server.py` (lifespan), desliga graciosamente no shutdown

### 📋 Compliance API — Nova

- **Módulo `api/compliance_api.py`** criado com 7 endpoints:
  - `GET /api/compliance/score` — Score calculado com 8 regras automáticas
  - `GET /api/compliance/rules` — Avaliação em tempo real (agendamento, backup recente, falhas consecutivas, repos ativos, auth, integridade, taxa sucesso, engines)
  - `GET/POST/DELETE /api/compliance/policies` — CRUD de políticas
  - `POST /api/compliance/audit` — Executa auditoria e grava histórico
  - `GET /api/compliance/audit/history` — Histórico de auditorias
- **2 tabelas** criadas: `compliance_policies`, `compliance_audits`
- **Página `compliance.html`** agora funcional (antes 100% 404)

### 📊 Advanced Stats — Endpoints Completados

- **3 endpoints** adicionados ao `advanced_stats_api.py`:
  - `GET /api/advanced-stats/trend?days=N` — Dados diários (success/failed) para gráficos line + heatmap
  - `GET /api/advanced-stats/distribution` — Distribuição de status (doughnut chart)
  - `GET /api/advanced-stats/recent-executions?limit=N` — Execuções recentes para timeline widget
- **Dashboard `index.html`** — gráficos Trend, Distribution e Timeline agora funcionais

### 🔄 Replication API — Endpoints Completados

- **5 endpoints** adicionados ao `replication_api.py`:
  - `GET /api/replication/stats` — Estatísticas agregadas (total rules, syncing, bytes, errors 24h)
  - `GET /api/replication/rules` — Alias para policies (formato compatível com `replication.html`)
  - `POST /api/replication/rules` — Criar regra (wrapper para create_policy)
  - `POST /api/replication/rules/{id}/sync` — Trigger sync
  - `DELETE /api/replication/rules/{id}` — Remover regra
- **Página `replication.html`** agora funcional

### ⚙️ Servidor Central — Configurações Completas

- **Tabela `server_settings`** criada com 33 configurações padrão em 7 categorias: Geral, Sincronização, Segurança, Database, Retenção, Notificações, Interface
- **10 endpoints REST**: GET/PUT settings, GET/PUT category, bulk update, reset, export, import, server info, maintenance cleanup, test notification
- **Dashboard `tab-config`** reescrito: cards de informação (versão, DB, conexões), formulário editável com 7 abas, export/import JSON, manutenção, reset
- **Versão Server**: 14.1.0 → **14.1.0**

### 🐛 Correções

- **11 endpoints 404 corrigidos** — compliance (4), advanced-stats (3), replication (2), ransomware/shield (2)
- **`ransomware_shield.py`** — 6 bugs críticos (ver acima)
- **Módulos registrados**: 27 APIs (era 25)

### 📈 Métricas

| Métrica | 14.1.0 | 14.1.0 |
|---------|--------|--------|
| APIs registradas (agente) | 25 | **27** |
| Endpoints REST (agente) | ~150 | **~175** |
| Endpoints REST (servidor) | 25 | **35** |
| Tabelas banco (servidor) | 9 | **10** |

---

## 14.1.0 — 2025-03

### 🏗️ Reorganização de Projeto

- **Estrutura de pastas reorganizada** — arquivos `.py` soltos na raiz foram classificados:
  - `core/` — Infraestrutura: `database_log_handler`, `database_migrator`, `db_wrapper`, `http_client`, `logstash_handler`, `monitoring`, `server_client`, `server_config`
  - `utils/` — Utilitários: `diagnostic_report`, `kill_port`, `orphan_file_detector`, `version_unifier`, `get_health_report`, `run_complete_diagnostic`
  - `tests/` — Scripts de teste: `test_app`, `test_repository_loading`, `fix_repo`
  - `scripts/` — Instalação e deploy: `.bat`, `.ps1`, `Dockerfile`, `docker-compose.yml`, `requirements_*.txt`
  - `docs/` — Toda documentação `.md` consolidada
  - `_deprecated/` — Código não utilizado (`app/`, `frontend/`)
- **Raiz limpa** — apenas arquivos essenciais: `agent_server.py`, `shared_core.py`, `models.py`, `start_server.py`, `requirements.txt`
- **Re-exports** na raiz para compatibilidade total de imports existentes
- **Arquivos vazios removidos**: `_add_interceptor.py`, `_migrate_auth.py`, `_test_auth.py`

### 🔐 Autenticação do Servidor

- **Login obrigatório** — rota `/` agora sempre exige autenticação (removida verificação `_is_server_auth_enabled`)
- **Modo Setup** — quando não há usuários, `login.html` exibe formulário "Criar Conta" automaticamente
- **Dashboard protegido** — `checkAuth()` no `DOMContentLoaded` valida sessão via `/api/v1/auth/status`
- **Logout funcional** — botão "Sair" na sidebar, limpa cookie e localStorage
- **Nome do usuário** exibido na sidebar do dashboard
- **Tabelas de auth**: `server_auth_users` (username, password_hash SHA256, display_name, role) e `server_auth_tokens` (token hex 64 chars, expires_at 24h)

### 🐛 Correções Críticas

- **alerts.py** — Corrigido `boolean = integer` para PostgreSQL: todas as queries de `resolved` e `acknowledged` agora usam `= true` / `= false` em vez de `= 1` / `= 0` (5 correções)
- **reports_api.py** — Corrigido nome da coluna: `cron_expr` → `cron_expression` em SELECT, INSERT, UPDATE e validação (4 correções)
- **database_log_handler.py** — Reescrito: conexão dedicada `psycopg2` com `autocommit=True`, thread-safe com `threading.Lock()`, auto-reconexão. Elimina cascata de erro "current transaction is aborted"
- **agent_server.py** — `RotatingFileHandler` (10 MB × 5 backups) substitui `FileHandler` ilimitado. Log separado de erros (`gboc_agent_errors.log`, 5 MB × 3). `sys.excepthook` para exceções não tratadas. Redirect de `stderr` para logger

### 📊 Health Score Unificado

- **Módulo `engines/health_score.py`** criado com cálculo padronizado:
  - Pesos: Sistema 30%, Ferramentas 10%, Backups 30%, Repositórios 15%, Tarefas 15%
  - Status: ≥85 Excelente, ≥70 Bom, ≥50 Atenção, <50 Crítico
  - Funções: `calculate_health_score()`, `calculate_health_score_auto()`, `score_from_issues()`, `get_health_status()`, `get_health_status_label()`

---

## v14.1.0 — 2025-02

### 🔧 Motores de Backup

- **Kopia** — `_list_kopia_files` reescrito: `ls -l` com traversal por object ID, suporte a diretórios profundos
- **Duplicati** — Suporte cloud via CLI (`Duplicati.CommandLine.exe`), `_list_duplicati_files`, `_build_duplicati_url` corrigido
- **GBOC Native** — Engine nativo com compressão e criptografia próprias (`native_engine/engine.py`)
- **Restic** — Suporte completo mantido (`C:\Program Files\Restic\restic.EXE`)
- **Detecção automática** de motores via `engines/engine_paths.py`

### 🔄 Restauração

- **`real_restore_manager.py`** — Restauração funcional para Kopia, Restic, Duplicati e GBOC Native
- **Página `restore.html`** — Seleção de repositório, navegação de snapshots, seleção de arquivos/pastas, progresso em tempo real
- **Auth fix** — Restauração não requer token quando executada localmente

### 📡 Comunicação Servidor Central

- **WebSocket bidirecional** — Agente ↔ Servidor em tempo real
- **Push Sync** — Sincronização sob demanda do dashboard do servidor
- **Heartbeat configurável** — 1-60 minutos
- **Auto-reconexão** com backoff exponencial

---

## v14.1.0 — 2024-12

### 📈 Estatísticas Avançadas

- **`engines/advanced_statistics.py`** — Backup, Performance, Storage, Reliability, Predictions, Trends
- **`api/advanced_stats_api.py`** — Endpoints: `/api/advanced-stats/comprehensive`, `/health-score`, `/predictions`, `/trends`

### 🩺 Diagnóstico

- **`engines/diagnostic_system.py`** — Diagnóstico do sistema em 4 abas (System, Engines, Database, Network)
- **`engines/preemptive_diagnostic.py`** — 8 verificações preventivas
- **`api/preemptive_api.py`** — API para diagnóstico preemptivo
- **`diagnostic.html`** — Interface com 4 abas, execução sob demanda, auto-correção

### 🔔 Sistema de Alertas

- **`api/alerts.py`** — CRUD completo, estatísticas, bulk actions, auto-resolução
- **Tabela `alerts`** — severity, category, resolved (BOOLEAN), acknowledged (BOOLEAN), auto_resolved

### 🩹 Auto-Healer

- **`engines/healer_engine.py`** — Verificação e correção automática de problemas
- **`engines/auto_healer.py`** — Agendamento de verificações periódicas

### 📧 Notificações

- **`engines/notification_service.py`** — Email via SMTP, templates HTML
- **`api/smtp.py`** — Configuração e teste SMTP via API

### 📋 Relatórios

- **`engines/report_generator.py`** — Geração de relatórios PDF/HTML
- **`api/reports_api.py`** — Agendamento com `cron_expression`, histórico
- **`api/export_api.py`** — Exportação em JSON, CSV

### 🗄️ Backup de Banco

- **`engines/database_backup.py`** — Backup do PostgreSQL (pg_dump)
- **`api/database_backup_api.py`** — Agendamento, listagem, restauração
- **`database-backup.html`** — Interface de gerenciamento

---

## v9.0 → v14.1.0 — Migração

### 🗃️ Banco de Dados

- **Migração completa para PostgreSQL** — SQLite mantido apenas para acessar bancos de motores externos (Duplicati)
- **Pool de conexões** — `psycopg2.pool` com min 2, max 10 conexões
- **Migrador automático** — `core/database_migrator.py` aplica schema defensivo
- **20 tabelas no agente**: alerts, auth_sessions, auth_users, backup_statistics, database_backups, database_connections, detected_engines, diagnostics, engine_backup_statistics, imported_repositories, integrity_checks, report_history, report_schedules, repositories, restore_history, settings, system_logs, task_executions, tasks, user_dashboard_layouts
- **11 tabelas no servidor**: agents, agent_logs, agent_metrics, agent_repositories, agent_statistics, agent_task_executions, agent_tasks, backup_reports, server_auth_tokens, server_auth_users, system_events

### 🔐 Autenticação do Agente

- **`api/auth.py`** — Login/registro, sessões com token, gerenciamento de usuários
- **`api/auth_middleware.py`** — Middleware FastAPI para proteção de rotas
- **`login.html`** — Tela neumórfica com modo setup (primeiro acesso)

### 🎨 Interface

- **Sistema de themes** — `[data-theme="dark"]` / `[data-theme="light"]` com variáveis CSS
- **Design System** — `style.css` com `.gboc-box`, `.btn-*`, `.data-table`, `.modal`, `.badge-*`, `.nav-link`
- **Sidebar dinâmica** — `sidebar.js` com navegação, indicador de página ativa, toggle de tema
- **Dashboard do Servidor** — 6 abas: Overview, Agentes, Backups, Analytics, Logs, Configurações
- **Chart.js 4.4.0** — Gráficos de linha, barras, doughnut para analytics

---

## Arquitetura Atual

### Agente (porta 9200)

```
gboc_v8/
├── agent_server.py          # Entry point FastAPI + Uvicorn
├── shared_core.py           # Singleton central (DB, engines, config)
├── models.py                # Modelos Pydantic
├── api/                     # 26 módulos de API REST
│   ├── auth.py              # Autenticação
│   ├── tasks.py             # Gerenciamento de tarefas
│   ├── repositories.py      # Gerenciamento de repositórios
│   ├── diagnostics.py       # Diagnóstico do sistema
│   ├── alerts.py            # Sistema de alertas
│   ├── settings.py          # Configurações
│   ├── logs.py              # Logs do sistema
│   ├── statistics.py        # Estatísticas
│   ├── websocket_api.py     # WebSocket real-time
│   └── ...                  # +17 módulos
├── engines/                 # 30 motores de processamento
│   ├── task_manager.py      # Gerenciador de tarefas (92 KB)
│   ├── repository_manager.py # Gerenciador de repositórios
│   ├── real_restore_manager.py # Restauração (71 KB)
│   ├── diagnostic_system.py # Diagnóstico
│   ├── health_score.py      # Health score unificado
│   └── ...                  # +25 motores
├── core/                    # Infraestrutura
│   ├── database_log_handler.py
│   ├── database_migrator.py
│   ├── server_client.py     # Cliente do servidor central
│   ├── server_config.py     # Configuração do servidor
│   └── ...
├── static/                  # Frontend (14 páginas HTML)
├── storage_backends/        # Local, Cloud, Base
├── native_engine/           # Motor GBOC nativo
├── utils/                   # Utilitários
├── tests/                   # Testes
├── scripts/                 # Instalação e deploy
└── docs/                    # Documentação
```

### Servidor (porta 8000)

```
GBOC-Server/
├── gboc_server.py           # Entry point FastAPI (85 KB)
├── login.html               # Tela de login neumórfica
├── dashboard.html           # Dashboard 6 abas (53 KB)
├── setup_database.sql       # Schema inicial
├── start_server.bat/ps1     # Scripts de inicialização
└── install_server.bat/ps1   # Scripts de instalação
```

### Tecnologias

| Componente | Tecnologia |
|---|---|
| Backend | Python 3.14, FastAPI, Uvicorn |
| Banco de Dados | PostgreSQL 18 (oficial) |
| Frontend | HTML5, CSS3, JavaScript vanilla |
| Gráficos | Chart.js 4.4.0 |
| Ícones | Font Awesome 6.4.0 |
| Backup Engines | Kopia, Restic, Duplicati, GBOC Native |
| Comunicação | WebSocket, REST API, Heartbeat |
| Autenticação | SHA256 + token hex, cookies HttpOnly |

