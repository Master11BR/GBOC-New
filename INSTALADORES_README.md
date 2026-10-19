<!-- Copyright (c) 2026 Master11BR - GBOC System v14.8.1 Enterprise. Todos os direitos reservados. -->

# 📦 GBOC System v14.8.1 Enterprise — Guia Oficial de Instaladores & Implantação

Este guia detalha a instalação e implantação do **GBOC Server (Servidor Central)** e do **GBOC Agent (Agente Local e Remoto LAN)**.

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
4. Acesse o painel pelo navegador: **`http://localhost:8000`**

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

### 3.1 Implantação em Massa Não Assistida via Token (GPO / Script / RMM)
Para implantação em dezenas ou centenas de máquinas sem intervenção humana:
1. Gere um Token de Instalação na aba **Políticas e Implantação** do GBOC Server.
2. Execute o comando com parâmetros de linha de comando:
```powershell
powershell -ExecutionPolicy Bypass -File .\GBOC-Agent\install_agent.ps1 -ServerURL "https://seu-servidor:8000" -InstallToken "SEU_TOKEN_AQUI" -Unattended
```

---

## 🎁 4. Instalador Unificado Enterprise & Pacote de Distribuição

Para gerar uma pasta externa de distribuição limpa contendo o **Server**, o **Agent** e o **Instalador Unificado**, execute `build_installer_package.bat` (pergunta o tipo de pacote e se gera o `.zip`) ou, sem perguntas:

```powershell
.\build_installer_package.bat -Mode Completo -Zip                         # código + programas (instala sem internet)
.\build_installer_package.bat -Mode Codigo -NoZip -OutputDir "D:\GBOC-Distribution"   # só código
```

| Tipo | Conteúdo | Instalação |
|---|---|---|
| **Completo** (~600 MB) | Código + `Prereqs\`: Python (última versão que já tem todas as bibliotecas do GBOC prontas para Windows) com as bibliotecas em wheels, PostgreSQL, restic, Kopia, Duplicati, NSSM. Versões e SHA-256 em `Prereqs\prereqs.json`. | Sem internet. |
| **Só código** (~30 MB) | Código. | Baixa os programas na hora (última versão). |

O gerador precisa de internet e de um Python na máquina onde roda. O `.zip` fica ao lado da pasta: `GBOC-Instalador_<versão>_<tipo>_<data>.zip`.

No servidor/estação de destino, abra a pasta (ou descompacte o `.zip`) e execute:
- **`Setup.bat`** (Interface interativa visual para instalar Server, Agent ou Ambos).

Antes de instalar, o `Setup.bat` mostra uma tabela com o que a máquina já tem, o que veio no pacote e a ação para cada programa. Regra para cada programa:
1. **Já instalado na máquina** (inclusive fora da pasta do GBOC, ex.: Duplicati em *Program Files*, PostgreSQL existente) → **mantido**;
2. senão → **instalado do pacote** (arquivo conferido por SHA-256; corrompido é ignorado);
3. não está no pacote (pacote "só código" ou item que falhou ao gerar) → **baixado da internet**.

Bibliotecas Python: instaladas das wheels do pacote sem internet; se faltar alguma, o restante vem da internet. O `install_agent.ps1` executado de dentro do pacote (`Agent\install_agent.ps1`) também usa o `Prereqs\` automaticamente.

> ⚠️ **DIRETRIZ OBRIGATÓRIA DE DESENVOLVIMENTO:**
> A cada novo arquivo, módulo ou funcionalidade criada ou modificada no código-fonte (`GBOC-Server` ou `GBOC-Agent`), o script `build_installer_package.ps1` **DEVE ser executado obrigatoriamente** para sincronizar e atualizar a pasta externa de distribuição (`GBOC-Distribution`).
