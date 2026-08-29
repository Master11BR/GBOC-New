<!-- Copyright (c) 2026 Master11BR - GBOC System v13.2.0 Enterprise. Todos os direitos reservados. -->

# 📦 GBOC System v13.2.0 Enterprise — Guia Oficial de Instaladores & Implantação

Este guia detalha a instalação do **GBOC Server (Servidor Central)** e do **GBOC Agent (Agente Local e Remoto LAN)**.

---

## 🚀 1. Instalação do GBOC Server (Servidor Central)

### Pré-requisitos:
- Python 3.11+ ou Python 3.14
- PostgreSQL 16+ (Recomendado para imunidade a corrupções via WAL logging)

### Passo a Passo Windows:
1. Abra o PowerShell como Administrador.
2. Execute o instalador automático:
   ```powershell
   .\GBOC-Server\install_server_new.ps1
   ```
3. Inicie o servidor central:
   ```powershell
   .\GBOC-Server\start_server.ps1
   ```
4. Acesse o painel pelo navegador: **`https://localhost:8000`**

---

## 💻 2. Instalação do GBOC Agent (Agente Local)

### Passo a Passo Windows:
1. Execute o script de instalação do agente:
   ```powershell
   .\GBOC-Agent\install_agent.ps1
   ```
2. Inicialize o serviço do agente:
   ```powershell
   .\GBOC-Agent\start_agent.ps1
   ```
3. Interface Web do Agente local: **`http://localhost:9200`**

---

## 🌐 3. Implantação Remota de Agente em Máquinas da Rede (LAN / VPN)

Para instalar o GBOC Agent em outros servidores ou estações de trabalho sem precisar acessar fisicamente a máquina:

```powershell
.\GBOC-Agent\scripts\install_agent_remote.ps1 -ComputerName "SRV-FINANCEIRO" -ServerURL "http://192.168.1.100:8000"
```

---

## 🔄 4. Disaster Recovery (Restauração 1-Click pós Formatação)

Caso um servidor seja formatado ou sofra desastre total:
1. Instale um novo GBOC Agent.
2. Na tela de restauração, clique em **"Restaurar Agente da Nuvem"** ou selecione o arquivo `.gbocdr`.
3. Todas as tarefas, repositórios e agendamentos serão reconstruídos instantaneamente.
