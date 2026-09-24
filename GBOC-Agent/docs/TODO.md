<!-- Copyright (c) 2026 Master11BR - GBOC System v14.7.0 Enterprise. Todos os direitos reservados. -->

# TODO: Consolidação do Sistema GBOC (v14.7.0)

## Status: ✅ Concluído (Release v14.7.0)

### 1. Migração do Modelo de Repositório ✅ COMPLETED
- [x] Criar modelos separados LocalRepository e CloudRepository em models.py
- [x] Atualizar RepositoryCreate/Update/Response para lidar com ambos os tipos
- [x] Atualizar validações dos modelos
- [x] Verificar necessidade de atualização do schema do banco
- [x] Adicionar suporte para motor 'native' nos modelos locais
- [x] Criar script de migração para repositórios existentes
- [x] Executar migração com sucesso (nenhum repositório existente precisou migração)

### 2. Refatoração do RepositoryManager ✅ COMPLETED
- [x] Suporte unificado no `repository_manager.py` para gerenciadores locais e cloud
- [x] Métodos factory `get_backend` alinhados com Restic, Kopia e Duplicati Native
- [x] Manter compatibilidade backward total
- [x] Operações CRUD validadas com novo modelo

### 3. Atualizações do Modelo de Tarefas ✅ COMPLETED
- [x] Modelos de tarefa referenciando estrutura de repositórios unificada
- [x] Operações de tarefa: criação, edição, histórico, pausa, parada e remoção
- [x] Testes de compatibilidade com tarefas existentes

### 4. Módulo de Recuperação (Recovery) ✅ COMPLETED
- [x] Módulo `recovery.py` integrado ao Agent
- [x] Restauração de arquivos de repositórios locais e cloud
- [x] Endpoints da API de recuperação expostos
- [x] Integração completa com `TaskManager` e `SharedCore`

### 5. Padrão Oficial de Relatórios v3.0 & Zero-Mock Intelligence (v14.7.0) ✅ COMPLETED
- [x] Implementação de `v3_reports_engine.py` (Contrato JSON Universal v3.0.0 com integridade SHA-256)
- [x] Correção integral dos 10 bugs de telemetria (BUG-01 a BUG-10) em `reports_api.py`
- [x] SLA individual por task (`collect_sla_per_task`), RTO/RPO reais e semáforo tri-estado
- [x] Throughput dinâmico em MB/s a partir de telemetria real de banco
- [x] Poda e retenção auditadas a partir de `settings` e `system_logs`
- [x] Predição de esgotamento de storage por regressão linear em séries temporais
- [x] Parecer analítico de IA cruzando $\ge 2$ métricas, tendência e ações
- [x] Tratamento transparente de relatórios sem sensor local (`status: "unavailable"`)
- [x] Sanitização de identificadores via `_clean_task_name()`
- [x] Atualização de `reports.html` com badges semafóricos, dots, targets e ações recomendadas
- [x] Sincronização simétrica de `flagship_reports.py` no Server e Agent (`schema_version: "3.0.0"`)

### 6. Documentação & Empacotamento ✅ COMPLETED
- [x] Atualização do `README.md` principal na raiz para v14.7.0
- [x] Atualização do `INSTALADORES_README.md` para v14.7.0
- [x] Atualização de `DOCUMENTACAO_SISTEMA_ISO.md` e `SYSTEM_CONFIG_GUIDE.md` para v14.7.0
- [x] Registro detalhado no `CHANGELOG.md`
- [x] Verificação Universal CSS (`tools/sync_css.py --verify`) 100% aprovada
- [x] Geração do pacote de distribuição oficial sincronizado em `GBOC-Distribution` via `build_installer_package.ps1`

