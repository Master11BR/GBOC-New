<!-- Copyright (c) 2026 Master11BR - GBOC System v13.3.0 Enterprise. Todos os direitos reservados. -->

# 📦 GBOC System v13.3.0 Enterprise — Guia Oficial de Instaladores & Implantação

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

---

## 🎁 5. Instalador Unificado Enterprise & Pacote de Distribuição

Para gerar uma pasta externa de distribuição limpa contendo o **Server**, o **Agent** e o **Instalador Unificado**:

```powershell
.\build_installer_package.ps1 -OutputDir "D:\GBOC-Distribution"
```

No servidor/estação de destino, abra a pasta `GBOC-Distribution` e execute:
- **`Setup.bat`** (Interface interativa visual para instalar Server, Agent ou Ambos).

> ⚠️ **DIRETRIZ OBRIGATÓRIA DE DESENVOLVIMENTO:**
> A cada novo arquivo, módulo ou funcionalidade criada ou modificada no código-fonte (`GBOC-Server` ou `GBOC-Agent`), o script `build_installer_package.ps1` **DEVE ser executado obrigatoriamente** para sincronizar e atualizar a pasta externa de distribuição (`GBOC-Distribution`).
