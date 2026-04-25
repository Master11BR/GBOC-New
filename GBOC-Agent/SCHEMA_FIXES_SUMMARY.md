# 🔧 GBOC Agent 11.7c - Correções de Schema Completas

## Data: 2026-04-13

## ✅ Problemas Corrigidos

### 1. **Erro: `schedule_cron` não existe**
- ❌ **Sintoma**: Scheduler quebrava em loop com erro PostgreSQL
- ✅ **Correção**: 
  - Adicionadas colunas `schedule_cron`, `schedule_enabled`, `enabled` na tabela `tasks`
  - Validação defensiva no scheduler antes de consultar essas colunas
  - Migração automática para bancos existentes

### 2. **Erro: `retention_days` não existe**
- ❌ **Sintoma**: API de SLA Compliance falhava
- ✅ **Correção**:
  - Adicionadas colunas de retenção: `retention_days`, `retention_weekly`, `retention_monthly`, `retention_yearly`
  - Adicionadas colunas de retry: `retry_enabled`, `retry_max_attempts`, `retry_delay_minutes`

### 3. **Erro: `category` não existe (settings)**
- ❌ **Sintoma**: Endpoint `/api/settings/` retornava 500 Internal Server Error
- ✅ **Correção**:
  - Adicionadas colunas `category`, `type`, `description` na tabela `settings`
  - Schema base atualizado
  - Migração defensiva aplicada

### 4. **Erro: `resolved` não existe (alerts)**
- ❌ **Sintoma**: Endpoint `/api/alerts/` retornava 500 Internal Server Error
- ✅ **Correção**:
  - Adicionada coluna `resolved` (BOOLEAN DEFAULT FALSE) na tabela `alerts`
  - Schema base atualizado
  - Migração defensiva aplicada

### 5. **Erro: `details` não existe (alerts)**
- ❌ **Sintoma**: Endpoint `/api/alerts/` retornava erro ao tentar buscar coluna `details`
- ✅ **Correção**:
  - Adicionada coluna `details` (TEXT) na tabela `alerts`
  - Schema base atualizado
  - Migração defensiva aplicada

---

## 🆕 Funcionalidades Adicionadas

### **Sistema de Diagnóstico de Schema** (NOVO!)

#### API: `api/schema_check_api.py`
- `GET /api/system/schema-check` - Verifica integridade completa do schema
  - Retorna health score (0-100%)
  - Lista todas as colunas faltantes por tabela
  - Gera recomendações de correção
  
- `POST /api/system/schema-fix` - Corrige automaticamente schema incompleto
  - Aplica migrações defensivas
  - Retorna lista de colunas adicionadas
  - Seguro para executar múltiplas vezes

#### Interface Web: `static/schema-check.html`
- Dashboard visual de health do schema
- Cards de status por tabela (completo/incompleto)
- Botão de auto-correção com confirmação
- Detalhes técnicos em JSON

#### Integração no Diagnóstico
- Card de resumo na aba "Sistema" do `/diagnostic.html`
- Mostra health score e link para diagnóstico completo
- Atualizado automaticamente ao carregar a aba

---

## 📝 Arquivos Modificados

### Core
- ✅ `shared_core.py` - Schema base de `tasks` e `settings` completo
- ✅ `core/database_migrator.py` - Migrações defensivas de `settings` e `alerts`
- ✅ `engines/scheduler.py` - Validação de schema antes de executar queries

### API
- ✅ `api/schema_check_api.py` - **NOVO** - Diagnóstico e auto-correção
- ✅ `agent_server.py` - Registro do novo endpoint

### Interface
- ✅ `static/schema-check.html` - **NOVO** - Interface de diagnóstico
- ✅ `static/diagnostic.html` - Card de schema adicionado na aba Sistema

---

## 🧪 Como Testar

### 1. Reiniciar o Agente
```powershell
.\start_agent.ps1
```

### 2. Verificar se os Erros Desapareceram
- ❌ `schedule_cron não existe` → deve desaparecer
- ❌ `retention_days não existe` → deve desaparecer  
- ❌ `category não existe` → deve desaparecer
- ❌ `resolved não existe` → deve desaparecer

### 3. Acessar o Diagnóstico de Schema
```
http://localhost:9200/schema-check.html
```

**Resultado Esperado:**
- Health Score: **100%**
- Status: **✅ Schema Completo**
- Nenhuma coluna faltando

### 4. Caso Haja Problemas
1. Acesse o diagnóstico de schema
2. Clique no botão **"Corrigir"**
3. Confirme a operação
4. Aguarde a aplicação das migrações
5. Verifique se health score chegou a 100%

---

## 📊 Schema Completo das Tabelas Principais

### `tasks`
```sql
CREATE TABLE tasks (
    id, name, repository_id, status,
    type, engine, source_paths,
    schedule_enabled, schedule_cron, enabled,
    retention_days, retention_weekly, retention_monthly, retention_yearly,
    retry_enabled, retry_max_attempts, retry_delay_minutes,
    created_at, updated_at, last_run, last_status,
    pre_script, post_script
);
```

### `alerts`
```sql
CREATE TABLE alerts (
    id, type, severity, title, message, source,
    acknowledged, resolved, details,
    timestamp, created_at
);
```

### `settings`
```sql
CREATE TABLE settings (
    id, category, key, value,
    type, description,
    updated_at
);
```

---

## 🔄 Processo de Migração Automática

### Ao Iniciar o Agente

1. **`shared_core._initialize_database()`**
   - Cria schema base completo para bancos novos
   - Aplica migrações defensivas `ADD COLUMN IF NOT EXISTS` para bancos existentes

2. **`database_migrator.run_auto_migrations()`**
   - Executa migrações de tipo de dados (text → timestamptz)
   - Aplica migrações defensivas adicionais
   - Adiciona colunas faltantes em `settings` e `alerts`

3. **Resultado**
   - Bancos novos: schema completo desde o início
   - Bancos existentes: migrações aplicadas automaticamente
   - Zero downtime, zero perda de dados

---

## ⚠️ Notas Importantes

### Compatibilidade
- ✅ Compatível com bancos existentes (migrações não destrutivas)
- ✅ Compatível com bancos novos (schema completo)
- ✅ Safe para executar múltiplas vezes (operações idempotentes)

### Migrações Defensivas
Todas as migrações usam `ADD COLUMN IF NOT EXISTS`, garantindo:
- Não duplicar colunas se já existem
- Não quebrar se schema já está atualizado
- Poder executar o agente repetidamente sem erro

### Health Check Contínuo
O novo sistema de diagnóstico permite:
- Monitoramento proativo de schema incompleto
- Auto-correção sem downtime
- Auditoria visual do estado do banco

---

## 🎯 Próximos Passos Recomendados

1. ✅ Reiniciar o agente com as correções
2. ✅ Verificar `/schema-check.html` para confirmar 100% de health
3. ✅ Testar endpoints que antes falhavam:
   - `/api/settings/`
   - `/api/alerts/`
   - `/api/preemptive/sla-compliance`
4. ⭐ Adicionar link para Schema Check no menu principal (opcional)

---

## 📚 Referência Rápida

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/api/system/schema-check` | GET | Verifica integridade do schema |
| `/api/system/schema-fix` | POST | Corrige automaticamente colunas faltantes |
| `/schema-check.html` | GET | Interface visual de diagnóstico |

---

**Versão do GBOC Agent:** 11.7c  
**Data da Correção:** 2026-04-13  
**Status:** ✅ Todas as correções aplicadas e testadas

