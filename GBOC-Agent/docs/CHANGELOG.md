<!-- Copyright (c) 2026 Master11BR - GBOC System v13.2.0 Enterprise. Todos os direitos reservados. -->

# GBOC — Changelog de Atualizações

> Histórico completo de versões, correções e melhorias do sistema GBOC (Agente + Servidor).

---

## 13.2.0 — 2026-08-08 (Patch Release — Hotfixes de Navegação, Validação e Ransomware)

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
  - Incremento global de versão para **13.2.0** em todos os arquivos de configuração de versão e templates usando `version_unifier.py` e atualização do `BUILD_DATE` para **2026-08-08**.

---

## 13.2.0 — 2026-08-05 (Minor Release — Módulos GUI Storage & Job Alert)

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
  - Incremento global para **13.2.0** via `version_control.py` e `version_unifier.py`.

---

## 13.2.0 — 2026-08 (Versão Consolidada Pós-Recuperação)

### 🚀 Destaques da Release

- **Unificação Geral de Versão (13.2.0)**: Sincronização completa de todos os módulos (`GBOC-Server`, `GBOC-Agent`, `SharedCore`, `Ransomware Shield`, `Diagnostic System` e `version_unifier.py`).
- **Recuperação e Consolidação de Código**: Restauração da base de código (recuperada após perda por falha de disco), consolidando todas as melhorias até Agosto de 2026.
- **Suporte Pydantic v2**: Atualização dos validadores de modelos Pydantic no `GBOC-Server`.
- **Estabilidade nos Testes**: Correção de codificação UTF-8 no Windows e ajuste de asserções assíncronas na Dead Letter Queue (`tests.py`).
- **Documentação Mestra**: Reformulação total do `README.md` principal na raiz e atualização do `INSTALADORES_README.md`.

---

## 13.2.0 — 2026-04

### 🧩 UI e Navegação

- **Página `config-manager.html`** criada — interface completa para `config_api.py`:
  - export atual (preview + download JSON)
  - import manual e upload JSON
  - snapshots de configuração
  - download/visualização/exclusão de snapshots
  - diff entre snapshots e diff snapshot vs config atual
- **Sidebar atualizada**:
  - versão visual `GBOC 13.2.0`
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
  - `start_agent.bat` e `start_agent.ps1`: v13.2.0 → **13.2.0**
  - scripts de instalação/diagnóstico em `scripts/`: padronizados para **13.2.0**

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
- **Versão Server**: 13.2.0 → **13.2.0**

### 🐛 Correções

- **11 endpoints 404 corrigidos** — compliance (4), advanced-stats (3), replication (2), ransomware/shield (2)
- **`ransomware_shield.py`** — 6 bugs críticos (ver acima)
- **Módulos registrados**: 27 APIs (era 25)

### 📈 Métricas

| Métrica | 13.2.0 | 13.2.0 |
|---------|--------|--------|
| APIs registradas (agente) | 25 | **27** |
| Endpoints REST (agente) | ~150 | **~175** |
| Endpoints REST (servidor) | 25 | **35** |
| Tabelas banco (servidor) | 9 | **10** |

---

## 13.2.0 — 2025-03

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

## v13.2.0 — 2025-02

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

## v13.2.0 — 2024-12

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

## v9.0 → v13.2.0 — Migração

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

