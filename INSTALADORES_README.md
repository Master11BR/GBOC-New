# 🚀 Instaladores GBOC - Agent & Server

## 📋 Visão Geral

Os instaladores automáticos foram criados para facilitar a instalação completa do **GBOC Agent** e **GBOC Server** em ambientes Windows, incluindo todas as dependências necessárias.

---

## 📦 O que cada instalador faz?

### **install_agent.ps1** (GBOC Agent)
Instala automaticamente:
- ✅ **Python 3.11.9** (ambiente dedicado)
- ✅ **PostgreSQL 16** (banco de dados)
- ✅ **Restic** (motor de backup) — **INSTALAÇÃO GLOBAL**
- ✅ **Kopia** (motor de backup) — **INSTALAÇÃO GLOBAL**
- ✅ **Duplicati** (motor de backup, requer .NET 6) — **INSTALAÇÃO GLOBAL**
- ✅ **Dependências Python** do Agent
- ✅ **Configuração automática** do banco de dados
- ✅ **PATH do Sistema** (não apenas usuário)
- ✅ **Permissões para LocalSystem** (acesso total ao sistema)
- ✅ **Variáveis de ambiente do sistema**
- ✅ **Serviço Windows** (opcional) configurado como **LocalSystem**

> **⚠️ IMPORTANTE**: Os motores são instalados de forma **GLOBAL** para funcionar como **serviço em segundo plano**, independente de login de usuário. Isso permite que backups agendados rodem mesmo sem ninguém logado no Windows.

### **install_server.ps1** (GBOC Server)
Instala automaticamente:
- ✅ **Python 3.11.9** (ambiente dedicado)
- ✅ **PostgreSQL 16** (banco de dados)
- ✅ **Dependências Python** do Server
- ✅ **Configuração automática** do banco de dados
- ✅ **Serviço Windows** (opcional)

---

## 🔧 Como usar os instaladores

### **Pré-requisitos**
- Windows 10/11 ou Windows Server 2016+
- **Executar como Administrador**
- Conexão com a internet (para download dos componentes)

### **Passos para instalação do Agent**

1. Abra o PowerShell **como Administrador**
2. Navegue até o diretório do Agent:
   ```powershell
   cd D:\GBOC\GBOC-New\GBOC-Agent
   ```
3. Execute o instalador:
   ```powershell
   .\install_agent.ps1
   ```
4. Aguarde a instalação (pode levar 10-15 minutos)
5. Escolha se deseja instalar como serviço Windows
6. Acesse: **http://localhost:9200**

### **Passos para instalação do Server**

1. Abra o PowerShell **como Administrador**
2. Navegue até o diretório do Server:
   ```powershell
   cd D:\GBOC\GBOC-New\GBOC-Server
   ```
3. Execute o instalador:
   ```powershell
   Set-ExecutionPolicy Bypass -Scope Process -Force
   .\install_server.ps1
   ```
4. Aguarde a instalação
5. Escolha se deseja instalar como serviço Windows
6. Acesse: **http://localhost:8000**

---

## 📂 Estrutura de instalação

Todos os componentes são instalados em `C:\GBOC`:

```
C:\GBOC\
├── Agent\                    # Arquivos do Agent
│   ├── agent_server.py
│   ├── start_agent.bat
│   └── .env
├── Server\                   # Arquivos do Server
│   ├── gboc_server.py
│   ├── start_server.bat
│   └── .env
└── Tools\                    # Ferramentas compartilhadas
	├── Python\               # Python 3.11.9
	├── PostgreSQL\           # PostgreSQL 16
	├── Restic\               # Restic (Agent)
	├── Kopia\                # Kopia (Agent)
	├── Duplicati\            # Duplicati (Agent)
	└── nssm\                 # NSSM (se instalado como serviço)
```

---

## 🔐 Credenciais padrão

### PostgreSQL (criado automaticamente)
- **Superusuário**: `postgres` / `postgres`
- **Usuário do banco**: `gboc` / `[senha gerada aleatoriamente]`
- **Banco Agent**: `gboc_agent`
- **Banco Server**: `gboc_server`

> ⚠️ **As senhas geradas são exibidas no final da instalação!**

### Aplicação (Agent e Server)
Configuradas em cada projeto separadamente.

---

## 🛠️ Comandos úteis

### Verificar configuração dos motores como serviço

Execute este script para verificar se tudo está configurado corretamente:

```powershell
cd C:\GBOC\Agent
.\test_motors_service.ps1
```

Ele verificará:
- ✅ Se os motores estão no PATH do sistema
- ✅ Se as variáveis de ambiente estão corretas
- ✅ Se os motores são acessíveis
- ✅ Se o serviço está rodando como LocalSystem
- ✅ Se as permissões estão corretas

### Iniciar manualmente (sem serviço)

**Agent:**
```powershell
cd C:\GBOC\Agent
.\start_agent.bat
```

**Server:**
```powershell
cd C:\GBOC\Server
.\start_server.bat
```

### Gerenciar serviços Windows

**Iniciar serviço:**
```powershell
Start-Service GBOCAgent
Start-Service GBOCServer
```

**Parar serviço:**
```powershell
Stop-Service GBOCAgent
Stop-Service GBOCServer
```

**Verificar status:**
```powershell
Get-Service GBOC*
```

**Remover serviço:**
```powershell
C:\GBOC\Tools\nssm\nssm.exe remove GBOCAgent confirm
C:\GBOC\Tools\nssm\nssm.exe remove GBOCServer confirm
```

---

## 🐛 Solução de problemas

### ❌ "Não foi possível baixar o Python/PostgreSQL"
- Verifique sua conexão com a internet
- Desabilite temporariamente antivírus/firewall
- Baixe manualmente e coloque em `C:\GBOC\Tools\`

### ❌ "Falha ao criar banco de dados"
- Verifique se o PostgreSQL está rodando:
  ```powershell
  Get-Service postgresql-*
  ```
- Reinicie o serviço PostgreSQL:
  ```powershell
  Restart-Service postgresql-x64-16
  ```

### ❌ "Duplicati não foi instalado"
- Instale o **.NET 6 Runtime**: https://dotnet.microsoft.com/download/dotnet/6.0
- Execute o instalador novamente

### ❌ "Porta 9200/8000 já está em uso"
- Verifique se outro processo está usando a porta:
  ```powershell
  netstat -ano | findstr :9200
  netstat -ano | findstr :8000
  ```
- Pare o processo conflitante ou altere a porta no arquivo `.env`

---

## 🔄 Atualização

Para atualizar o Agent ou Server:

1. Pare o serviço (se estiver rodando):
   ```powershell
   Stop-Service GBOCAgent
   ```
2. Faça backup do arquivo `.env`
3. Substitua os arquivos em `C:\GBOC\Agent` ou `C:\GBOC\Server`
4. Restaure o arquivo `.env`
5. Reinicie o serviço:
   ```powershell
   Start-Service GBOCAgent
   ```

---

## 🗑️ Desinstalação

### Remover serviços
```powershell
C:\GBOC\Tools\nssm\nssm.exe remove GBOCAgent confirm
C:\GBOC\Tools\nssm\nssm.exe remove GBOCServer confirm
```

### Remover PostgreSQL
```powershell
Stop-Service postgresql-x64-16
& "C:\GBOC\Tools\PostgreSQL\uninstall-postgresql.exe"
```

### Remover tudo
```powershell
Remove-Item -Recurse -Force C:\GBOC
```

---

## 📞 Suporte

- **GitHub**: [issues/GBOC](https://github.com/seu-usuario/GBOC/issues)
- **Documentação completa**: Ver `docs/` em cada projeto
- **Logs**:
  - Agent: `C:\GBOC\Agent\logs\gboc_agent.log`
  - Server: `C:\GBOC\Server\logs\gboc_server.log`

---

## ⚙️ Instalação manual (alternativa)

Se preferir instalar manualmente:

### 1. Instalar Python 3.11+
https://www.python.org/downloads/

### 2. Instalar PostgreSQL 16
https://www.postgresql.org/download/windows/

### 3. Instalar motores de backup (Agent)
- **Restic**: https://github.com/restic/restic/releases
- **Kopia**: https://github.com/kopia/kopia/releases
- **Duplicati**: https://github.com/duplicati/duplicati/releases

### 4. Clonar o projeto
```bash
git clone https://github.com/seu-usuario/GBOC.git
cd GBOC
```

### 5. Instalar dependências Python

**Agent:**
```bash
cd GBOC-Agent
pip install -r requirements.txt
```

**Server:**
```bash
cd GBOC-Server
pip install -r requirements.txt
```

### 6. Configurar banco de dados

```sql
CREATE DATABASE gboc_agent;
CREATE USER gboc WITH PASSWORD 'sua_senha';
GRANT ALL PRIVILEGES ON DATABASE gboc_agent TO gboc;
```

### 7. Criar arquivo .env

**Agent (.env):**
```ini
DATABASE_URL=postgresql://gboc:sua_senha@localhost:5432/gboc_agent
AGENT_PORT=9200
RESTIC_PATH=C:\Tools\restic.exe
KOPIA_PATH=C:\Tools\kopia.exe
DUPLICATI_PATH=C:\Tools\Duplicati.CommandLine.exe
```

**Server (.env):**
```ini
DATABASE_URL=postgresql://gboc:sua_senha@localhost:5432/gboc_server
SERVER_PORT=8000
```

### 8. Executar

**Agent:**
```bash
python agent_server.py
```

**Server:**
```bash
python gboc_server.py
```

---

## ✅ Checklist pós-instalação

- [ ] Agent responde em http://localhost:9200
- [ ] Server responde em http://localhost:8000
- [ ] PostgreSQL está rodando
- [ ] Restic, Kopia e Duplicati estão no PATH
- [ ] Logs não apresentam erros críticos
- [ ] Primeiro login funciona corretamente

---

**Última atualização:** Abril 2026  
**Versão dos instaladores:** 1.0
