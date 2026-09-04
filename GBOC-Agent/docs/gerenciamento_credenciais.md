<!-- Copyright (c) 2026 Master11BR - GBOC System v14.0.0 Enterprise. Todos os direitos reservados. -->

# Gerenciamento de Credenciais - GBOC Agent

## Visão Geral

O módulo de gerenciamento de credenciais do GBOC Agent oferece uma maneira segura de armazenar e recuperar credenciais sensíveis, como senhas, tokens de API e chaves de acesso. Todas as credenciais são criptografadas antes de serem armazenadas no banco de dados.

## Tabela de Conteúdos

1. [Funcionalidades Principais](#funcionalidades-principais)
2. [Uso Básico](#uso-básico)
3. [Referência da API](#referência-da-api)
4. [Boas Práticas](#boas-práticas)
5. [Solução de Problemas](#solução-de-problemas)
6. [Exemplos Avançados](#exemplos-avançados)

## Funcionalidades Principais

- **Armazenamento seguro** de credenciais com criptografia AES-256
- **Recuperação segura** de credenciais quando necessário
- **Listagem** de todas as credenciais armazenadas (apenas metadados)
- **Remoção segura** de credenciais
- **Atualização** de credenciais existentes
- **Metadados** adicionais para cada credencial

## Uso Básico

### Inicialização

O gerenciador de credenciais é inicializado automaticamente pelo `SharedCore`. Para usá-lo:

```python
from shared_core import get_shared_core

# Obtém a instância do core
core = get_shared_core()

# Acessa o gerenciador de credenciais
cred_manager = core.credential_manager
```

### Armazenando uma Credencial

```python
# Dados da credencial
credencial = {
    "username": "usuario_api",
    "password": "senha_segura_123",
    "url": "https://api.exemplo.com",
    "api_key": "12345-abcde-67890-fghij"
}

# Armazena a credencial
sucesso = cred_manager.store_credential(
    "minha_api",  # Nome único para a credencial
    credencial    # Dados da credencial
)

if sucesso:
    print("Credencial armazenada com sucesso!")
```

### Recuperando uma Credencial

```python
# Recupera a credencial
credencial = cred_manager.get_credential("minha_api")

if credencial:
    print(f"Conectando a {credencial['url']} como {credencial['username']}")
else:
    print("Credencial não encontrada")
```

### Listando Todas as Credenciais

```python
# Lista todas as credenciais
for cred in cred_manager.list_credentials():
    print(f"{cred['name']} - Última atualização: {cred['updated_at']}")
```

### Removendo uma Credencial

```python
# Remove uma credencial
if cred_manager.delete_credential("minha_api"):
    print("Credencial removida com sucesso")
else:
    print("Falha ao remover credencial")
```

## Referência da API

### `store_credential(name: str, data: Dict[str, Any], password: Optional[str] = None) -> bool`

Armazena uma nova credencial ou atualiza uma existente.

**Parâmetros:**
- `name`: Nome único para identificar a credencial
- `data`: Dicionário com os dados da credencial
- `password`: Senha opcional para criptografia adicional (não obrigatória)

**Retorna:**
- `True` se a operação foi bem-sucedida, `False` caso contrário

### `get_credential(name: str, password: Optional[str] = None) -> Optional[Dict[str, Any]]`

Recupera uma credencial armazenada.

**Parâmetros:**
- `name`: Nome da credencial a ser recuperada
- `password`: Senha usada para criptografia adicional (se aplicável)

**Retorna:**
- Dicionário com os dados da credencial ou `None` se não encontrada

### `list_credentials() -> List[Dict[str, Any]]`

Lista todas as credenciais armazenadas (apenas metadados).

**Retorna:**
- Lista de dicionários com informações básicas de cada credencial

### `delete_credential(name: str) -> bool`

Remove uma credencial do armazenamento.

**Parâmetros:**
- `name`: Nome da credencial a ser removida

**Retorna:**
- `True` se a remoção foi bem-sucedida, `False` caso contrário

## Boas Práticas

1. **Nomes Descritivos**: Use nomes descritivos para suas credenciais
   - Ruim: `api1`, `credencial2`
   - Bom: `prod_api_pagamento`, `homolog_banco_dados`

2. **Metadados Úteis**: Use o campo de metadados para informações adicionais
   ```python
   cred_manager.store_credential(
       "prod_api_pagamento",
       {"token": "abc123"},
       metadata={
           "responsavel": "time.pagamentos@empresa.com",
           "ambiente": "produção",
           "data_expiracao": "2024-12-31"
       }
   )
   ```

3. **Nunca armazene senhas em texto claro** no código ou em arquivos de configuração.

4. **Gere senhas fortes** usando o utilitário integrado:
   ```python
   from security_utils import security_manager
   senha_forte = security_manager.generate_secure_token(32)
   ```

5. **Atualize credenciais** regularmente, especialmente após incidentes de segurança.

## Solução de Problemas

### "Gerenciador de credenciais não inicializado"
Verifique se o `SharedCore` foi inicializado corretamente antes de acessar o gerenciador de credenciais.

### "Credencial não encontrada"
- Verifique se o nome da credencial está correto
- Use `list_credentials()` para ver todas as credenciais disponíveis

### Erros de criptografia
- Se estiver usando uma senha para criptografia adicional, certifique-se de fornecê-la ao recuperar a credencial
- Verifique se a variável de ambiente `GBOC_ENCRYPTION_KEY` está configurada corretamente

## Exemplos Avançados

### Usando com uma API REST

```python
import requests
from shared_core import get_shared_core

def fazer_chamada_api(endpoint):
    core = get_shared_core()
    credencial = core.credential_manager.get_credential("api_producao")
    
    if not credencial:
        raise ValueError("Credenciais da API não encontradas")
    
    headers = {
        "Authorization": f"Bearer {credencial['token']}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(
        f"{credencial['url_base']}/{endpoint}",
        headers=headers
    )
    
    response.raise_for_status()
    return response.json()

# Uso
dados = fazer_chamada_api("clientes/123")
```

### Rotação de Credenciais

```python
def rotacionar_credencial(nome_antigo: str, nova_senha: str):
    core = get_shared_core()
    cred_manager = core.credential_manager
    
    # Recupera a credencial antiga
    credencial = cred_manager.get_credential(nome_antigo)
    if not credencial:
        raise ValueError(f"Credencial {nome_antigo} não encontrada")
    
    # Cria uma nova versão com a nova senha
    novo_nome = f"{nome_antigo}_v{int(time.time())}"
    cred_manager.store_credential(novo_nome, credencial, password=nova_senha)
    
    # Remove a versão antiga
    cred_manager.delete_credential(nome_antigo)
    
    return novo_nome
```

### Backup de Credenciais

```python
import json
from datetime import datetime

def fazer_backup_credenciais(arquivo_saida: str):
    core = get_shared_core()
    credenciais = core.credential_manager.list_credentials()
    
    backup = {
        "data_backup": datetime.now().isoformat(),
        "versao": "1.0",
        "credenciais": []
    }
    
    for cred in credenciais:
        dados = core.credential_manager.get_credential(cred["name"])
        if dados:
            backup["credenciais"].append({
                "nome": cred["name"],
                "dados": dados,
                "metadados": cred.get("metadata")
            })
    
    with open(arquivo_saida, 'w') as f:
        json.dump(backup, f, indent=2)
    
    return len(backup["credenciais"])

# Uso
total = fazer_backup_credenciais("backup_credenciais.json")
print(f"Backup concluído para {total} credenciais")
```

## Segurança

- Todas as credenciais são criptografadas antes de serem armazenadas
- A chave de criptografia padrão é armazenada na variável de ambiente `GBOC_ENCRYPTION_KEY`
- Para maior segurança, use uma senha adicional ao armazenar credenciais críticas
- As operações de criptografia usam salt aleatório para cada credencial
- A comparação de hashes é feita em tempo constante para evitar ataques de temporização
