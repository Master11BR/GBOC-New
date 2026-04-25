# TODO: Migração de Repositórios e Criação de Módulo de Recuperação

## Status: Em Andamento

### 1. Migração do Modelo de Repositório ✅ COMPLETED
- [x] Criar modelos separados LocalRepository e CloudRepository em models.py
- [x] Atualizar RepositoryCreate/Update/Response para lidar com ambos os tipos
- [x] Atualizar validações dos modelos
- [x] Verificar necessidade de atualização do schema do banco
- [x] Adicionar suporte para motor 'native' nos modelos locais
- [x] Criar script de migração para repositórios existentes
- [x] Executar migração com sucesso (nenhum repositório existente precisou migração)

### 2. Refatoração do RepositoryManager
- [ ] Dividir repository_manager.py em gerenciadores locais e cloud separados
- [ ] Atualizar métodos factory get_backend
- [ ] Manter compatibilidade backward
- [ ] Testar operações CRUD com novo modelo

### 3. Atualizações do Modelo de Tarefas
- [ ] Modificar modelos de tarefa para referenciar nova estrutura de repositório
- [ ] Atualizar criação/edição de tarefas para funcionar com repositórios separados
- [ ] Adicionar operações de tarefa: create, edit, history, pause, stop, delete
- [ ] Testar compatibilidade de tarefas existentes

### 4. Criação do Módulo de Recuperação
- [x] Criar novo módulo recovery.py do zero
- [x] Implementar restauração de arquivos de repositórios locais
- [x] Implementar restauração de arquivos de repositórios cloud
- [x] Adicionar endpoints da API de recuperação
- [x] Integrar com TaskManager existente

### 5. Testes e Validação
- [ ] Testar todas as operações de repositório (create, edit, test, delete)
- [ ] Testar operações de tarefa com novo modelo de repositório
- [ ] Testar funcionalidade de recuperação
- [ ] Validar compatibilidade backward

### 6. Documentação
- [ ] Atualizar documentação dos módulos modificados
- [ ] Documentar novo modelo de repositórios
- [ ] Documentar módulo de recuperação
