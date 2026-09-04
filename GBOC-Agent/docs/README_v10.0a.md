<!-- Copyright (c) 2026 Master11BR - GBOC System v14.0.0 Enterprise. Todos os direitos reservados. -->

# GBOC v14.0.0 - Sistema de Backup e Monitoramento

## 📋 Visão Geral

O GBOC (Generic Backup Operations Center) v14.0.0 é um sistema completo de gerenciamento de backups com recursos avançados de diagnóstico, monitoramento e análise estatística, inspirado no Duplicati.

### ✨ Novidades da v14.0.0

- ✅ **Versão Unificada**: Agente e Servidor sincronizados na versão 14.0.0
- ✅ **Diagnóstico Completo**: Sistema de diagnóstico preemptivo e preventivo
- ✅ **Estatísticas Avançadas**: Análise detalhada com previsões e tendências
- ✅ **Detecção de Órfãos**: Identificação e integração de arquivos não utilizados
- ✅ **Inspiração Duplicati**: Recursos avançados de backup inspirados no Duplicati
- ✅ **WebSocket Real-time**: Comunicação em tempo real entre agente e servidor
- ✅ **PostgreSQL**: Suporte robusto para banco de dados empresarial

## 🏗️ Arquitetura

```
GBOC-New/
├── gboc_v8/                    # Agente (v14.0.0)
│   ├── agent_server.py         # Servidor principal do agente
│   ├── start_server.py         # Script de inicialização
│   ├── server_client.py        # Cliente para servidor central
│   ├── server_config.py        # Configurações do servidor
│   │
│   ├── api/                    # APIs REST
│   │   ├── overview.py
│   │   ├── repositories.py
│   │   ├── tasks.py
│   │   ├── diagnostics.py
│   │   ├── statistics.py
│   │   ├── advanced_stats_api.py    # ✨ Nova API v14.0.0
│   │   ├── preemptive_api.py        # ✨ Nova API v14.0.0
│   │   └── system_api.py            # ✨ Nova API v14.0.0
│   │
│   ├── engines/                # Motores de processamento
│   │   ├── backup_engine.py
│   │   ├── scheduler.py
│   │   ├── diagnostic_system.py
│   │   ├── advanced_statistics.py   # ✨ Novo v14.0.0
│   │   └── preemptive_diagnostic.py # ✨ Novo v14.0.0
│   │
│   ├── storage_backends/       # Backends de armazenamento
│   │   ├── local.py
│   │   └── cloud.py
│   │
│   ├── data/                   # Banco de dados SQLite
│   ├── logs/                   # Logs do sistema
│   └── static/                 # Frontend web
│
└── GBOC-Server/               # Servidor Central (v14.0.0)
    ├── gboc_server.py         # Servidor principal PostgreSQL
    └── index.html             # Dashboard web

```

## 🚀 Instalação e Configuração

### Requisitos

- Python 3.8+
- PostgreSQL 12+ (para servidor central)
- pip

### Instalação do Agente

```bash
cd gboc_v8

# Instalar dependências
pip install -r requirements.txt

# Iniciar o agente
python start_server.py
```

O agente estará disponível em: `http://localhost:9200`

### Instalação do Servidor Central

```bash
cd GBOC-Server

# Configurar PostgreSQL
# Editar conexão no gboc_server.py se necessário

# Instalar dependências
pip install fastapi uvicorn psycopg2-binary

# Iniciar o servidor
python gboc_server.py
```

O servidor estará disponível em: `http://localhost:8000`

## 🔧 Funcionalidades Principais

### 1. Diagnóstico Completo do Sistema

Execute um diagnóstico completo do sistema:

```bash
cd gboc_v8
python run_complete_diagnostic.py
```

**O que é verificado:**
- ✅ Informações do sistema operacional
- ✅ Status do agente e servidor
- ✅ Integridade do banco de dados
- ✅ Estrutura de arquivos
- ✅ Arquivos órfãos
- ✅ Consistência de versões
- ✅ Performance do sistema

**Relatórios gerados:**
- `logs/diagnostic_report_YYYYMMDD_HHMMSS.json`
- `logs/complete_diagnostic_YYYYMMDD_HHMMSS.json`

### 2. Estatísticas Avançadas

Acesse estatísticas detalhadas via API:

```bash
# Estatísticas abrangentes (30 dias)
GET http://localhost:9200/api/advanced-stats/comprehensive?days=30

# Health Score do sistema
GET http://localhost:9200/api/advanced-stats/health-score

# Previsões
GET http://localhost:9200/api/advanced-stats/predictions

# Análise de tendências
GET http://localhost:9200/api/advanced-stats/trends?days=30
```

**Métricas disponíveis:**
- Taxa de sucesso de backups
- Performance (velocidade, duração)
- Crescimento de armazenamento
- Confiabilidade (MTBF, uptime)
- Previsões de capacidade

### 3. Diagnóstico Preemptivo

Detecte problemas antes que aconteçam:

```bash
# Executar verificação preemptiva
GET http://localhost:9200/api/preemptive/check

# Obter apenas alertas
GET http://localhost:9200/api/preemptive/alerts

# Obter recomendações
GET http://localhost:9200/api/preemptive/recommendations

# Previsão de armazenamento
GET http://localhost:9200/api/preemptive/storage-forecast
```

**O que é verificado:**
- ⚠️ Capacidade de armazenamento (previsão de quando ficará cheio)
- ⚠️ Padrões de falhas de backup
- ⚠️ Degradação de performance
- ⚠️ Saúde do banco de dados
- ⚠️ Recursos do sistema
- ⚠️ Conflitos de agendamento
- ⚠️ Política de retenção
- ⚠️ Problemas de rede

### 4. Detecção de Arquivos Órfãos

Encontre e integre arquivos não utilizados:

```bash
cd gboc_v8
python orphan_file_detector.py
```

ou via API:

```bash
GET http://localhost:9200/api/system/orphan-files
```

**Funcionalidades:**
- Identifica arquivos Python não importados
- Analisa propósito de cada arquivo
- Gera sugestões de integração
- Cria relatórios detalhados

### 5. Unificação de Versões

Unifica todas as versões para 14.0.0:

```bash
cd gboc_v8
python version_unifier.py
```

ou via API:

```bash
POST http://localhost:9200/api/system/version/unify
```

### 6. Sistema de Informações

```bash
# Informações do sistema
GET http://localhost:9200/api/system/info

# Health Score geral
GET http://localhost:9200/api/system/health
```

## 📊 APIs Disponíveis

### APIs v14.0.0 (Novas)

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/api/advanced-stats/comprehensive` | GET | Estatísticas abrangentes |
| `/api/advanced-stats/health-score` | GET | Score de saúde |
| `/api/advanced-stats/predictions` | GET | Previsões do sistema |
| `/api/advanced-stats/trends` | GET | Análise de tendências |
| `/api/preemptive/check` | GET | Verificação preemptiva |
| `/api/preemptive/alerts` | GET | Alertas do sistema |
| `/api/preemptive/recommendations` | GET | Recomendações |
| `/api/preemptive/storage-forecast` | GET | Previsão de armazenamento |
| `/api/system/diagnostic` | GET | Diagnóstico completo |
| `/api/system/orphan-files` | GET | Arquivos órfãos |
| `/api/system/version/unify` | POST | Unificar versões |
| `/api/system/info` | GET | Informações do sistema |
| `/api/system/health` | GET | Saúde geral |

### APIs Existentes

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/api/overview` | GET | Visão geral |
| `/api/repositories` | GET/POST | Gerenciar repositórios |
| `/api/tasks` | GET/POST | Gerenciar tarefas |
| `/api/diagnostics` | GET | Diagnósticos básicos |
| `/api/statistics` | GET | Estatísticas básicas |
| `/api/logs` | GET | Logs do sistema |
| `/api/settings` | GET/POST | Configurações |

## 🎯 Recursos Inspirados no Duplicati

### Implementados na v14.0.0

1. **Sistema de Estatísticas Avançadas**
   - Métricas detalhadas de backup
   - Análise de performance
   - Previsões de crescimento

2. **Diagnóstico Preemptivo**
   - Detecção antecipada de problemas
   - Alertas inteligentes
   - Recomendações automáticas

3. **Análise de Tendências**
   - Histórico de sucesso
   - Padrões de falha
   - Degradação de performance

4. **WebSocket Real-time**
   - Comunicação bidirecional
   - Atualizações em tempo real
   - Sincronização instantânea

### Planejados para Futuras Versões

- [ ] Compressão de dados (como Duplicati)
- [ ] Deduplicação
- [ ] Criptografia de backups
- [ ] Backup incremental avançado
- [ ] Verificação automática de backups
- [ ] Auto-throttling de rede
- [ ] Políticas de retenção avançadas
- [ ] Gerenciamento de cadeia de backups

## 📈 Monitoramento e Alertas

### Níveis de Risco

- **Minimal**: Sistema saudável
- **Low**: Poucos warnings, sem issues críticos
- **Medium**: Vários warnings detectados
- **High**: Issues críticos encontrados
- **Critical**: Problemas urgentes que requerem ação imediata

### Tipos de Alertas

1. **Armazenamento**
   - Disco próximo da capacidade
   - Previsão de espaço esgotado
   - Necessidade de expansão

2. **Performance**
   - Degradação detectada
   - CPU/memória alta
   - Backups lentos

3. **Confiabilidade**
   - Taxa de falha elevada
   - Falhas recorrentes
   - Problemas de rede

4. **Manutenção**
   - Banco de dados grande
   - Fragmentação
   - Dados antigos

## 🔍 Troubleshooting

### Problema: Agente não inicia

```bash
# Verificar porta 9200
netstat -ano | findstr :9200

# Matar processo se necessário
python kill_port.py 9200

# Reiniciar
python start_server.py
```

### Problema: Servidor não conecta ao PostgreSQL

1. Verificar se PostgreSQL está rodando
2. Verificar credenciais em `gboc_server.py`
3. Verificar firewall/conexão de rede

### Problema: Diagnóstico falha

```bash
# Executar com debug
python run_complete_diagnostic.py 2>&1 | tee diagnostic.log

# Verificar logs
cat logs/diagnostic_report_*.json
```

## 📝 Logs

### Localização dos Logs

- **Agente**: `gboc_v8/logs/`
- **Servidor**: logs do PostgreSQL ou console
- **Diagnósticos**: `gboc_v8/logs/diagnostic_*`
- **Órfãos**: `gboc_v8/logs/orphan_files_*`

### Tipos de Logs

- `gboc_agent.log`: Log principal do agente
- `diagnostic_report_*.json`: Relatórios de diagnóstico
- `orphan_files_report_*.json`: Relatórios de órfãos
- `complete_diagnostic_*.json`: Diagnóstico consolidado

## 🤝 Contribuindo

Para contribuir com o projeto:

1. Faça fork do repositório
2. Crie uma branch para sua feature (`git checkout -b feature/NovaFeature`)
3. Commit suas mudanças (`git commit -am 'Add NovaFeature'`)
4. Push para a branch (`git push origin feature/NovaFeature`)
5. Abra um Pull Request

## 📄 Licença

[Adicionar informações de licença]

## 🔗 Links Úteis

- Documentação do Duplicati: https://duplicati.com/
- FastAPI: https://fastapi.tiangolo.com/
- PostgreSQL: https://www.postgresql.org/

## 📞 Suporte

Para suporte e questões:
- Abra uma issue no GitHub
- [Adicionar informações de contato]

---

**GBOC v14.0.0** - Sistema Completo de Backup e Monitoramento
Desenvolvido com ❤️ inspirado no Duplicati
