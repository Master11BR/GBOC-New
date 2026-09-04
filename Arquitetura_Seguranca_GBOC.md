# Arquitetura de Defesa e Segurança: Sistema de Backup GBOC (v14.0.0)

Este documento estabelece a arquitetura oficial de segurança, detecção de ameaças e resposta a incidentes para o ecossistema de backup **GBOC (Servidor Central & Agente Local)**. A arquitetura combina uma stack de **7 ferramentas open source de classe mundial** para proteção antivírus, detecção de ransomware e integridade com a automação acelerada por **IA CLI de Codificação (Aider)**.

---

## 1. Stack de Ferramentas Open Source de Defesa

O ecossistema GBOC utiliza uma abordagem de **Defesa em Profundidade (Defense-in-Depth)** composta por 7 soluções open source complementares:

### 1.1. Antivírus Tradicionais e Interfaces
1. **ClamAV:** Motor de verificação antivírus de alto desempenho rodando no servidor e nos nós de backup. Utilizado em rotinas pós-backup para escanear deltas de dados em busca de assinaturas maliciosas conhecidas em repouso.
2. **Armadito Antivirus:** Solução antivírus de endpoint multiplataforma (Windows e Linux) com proteção em tempo real baseada em regras de assinatura e análise heurística comportamental para binários executáveis e documentos PDF.
3. **ClamWin / ClamTk:** Interfaces gráficas e integradores sob demanda do motor ClamAV. O ClamWin provê integração no Windows Explorer para auditorias manuais em discos locais, e o ClamTk atua em ambientes desktop Linux.
4. **Hypatia:** Scanner de malware open source offline voltado para dispositivos móveis e coletores Android. Garante a higienização de uploads oriundos de coletores móveis conectados ao GBOC.

### 1.2. Detecção Avançada, HIDS e Análise Comportamental
5. **Wazuh / OSSEC (HIDS & XDR):** Sistema de Detecção de Intrusão Baseado em Host (HIDS) e plataforma XDR corporativa. Monitora em tempo real a integridade de arquivos do sistema (FIM - File Integrity Monitoring), alterações de chaves de registro no Windows, logs de auditoria e comportamentos de criptografia em massa (Ransomware Shield).
6. **YARA:** O "canivete suíço" da caça de ameaças (Threat Hunting). Permite escrever regras avançadas de identificação de padrões hexadecimais, strings e comportamentos específicos de famílias modernas de ransomware (LockBit, BlackCat, Akira), executando varreduras profundas nos blocos de backup.
7. **Rkhunter (Rootkit Hunter):** Ferramenta especializada em escanear a infraestrutura de servidores de armazenamento e agentes em busca de rootkits, backdoors, trojans de kernel e adulterações em binários vitais do sistema.

---

## 2. Automação e Codificação com IA CLI (Aider)

Para orquestrar estas ferramentas, gerar regras de resposta ativa (Active Responses) e automatizar varreduras no pipeline do GBOC, a IA CLI recomendada é o **Aider** ([aider.chat](https://aider.chat)).

O **Aider** é uma ferramenta de linha de comando baseada em Inteligência Artificial (compatível com Claude 3.5 Sonnet, GPT-4o e modelos locais via Ollama) que se conecta diretamente ao repositório Git do projeto e edita o código em tempo real diretamente no seu terminal.

### 2.1. Vantagens do Aider no GBOC
* **Automação In-Place de Scripts:** Cria e modifica scripts em Python, PowerShell e Bash diretamente na árvore do projeto GBOC sem necessidade de cópia manual de código.
* **Geração Dinâmica de Regras YARA e Decodificadores Wazuh:** Gera regras YARA personalizadas para novas variantes de ransomware e integra decodificadores do Wazuh com as APIs de alerta do GBOC.
* **Manutenção de Integridade:** Mantém histórico de alterações no Git, garantindo que qualquer alteração nos scripts de segurança possa ser revertida em caso de falso positivo.

### 2.2. Workflow Prático no Terminal com Aider

```bash
# Iniciar o Aider no repositório do GBOC selecionando os arquivos do motor de ransomware
$ aider GBOC-Agent/engines/ransomware_detector.py GBOC-Agent/engines/ransomware_guardian.py

# Prompt executado na CLI da IA:
Aider> "Crie um módulo em Python para integrar o YARA e o ClamAV no pipeline pós-backup do GBOC-Agent. Se o YARA identificar um padrão de ransomware em um arquivo processado, o módulo deve:
1. Bloquear o snapshot imutável (WORM lock).
2. Notificar o agente local do Wazuh via syslog / socket local.
3. Registrar um evento crítico no banco de dados SQLite local (tabela alerts)."
```

---

## 3. Topologia e Fluxo de Execução Pós-Backup / Pré-Backup

```
 ┌────────────────────────┐      ┌────────────────────────┐      ┌────────────────────────┐
 │   1. PRÉ-BACKUP        │      │   2. EM TRÂNSITO       │      │   3. PÓS-BACKUP        │
 │   (Nó de Origem)       │─────►│   (Canal Seguro)       │─────►│   (Storage Target)     │
 │ • Wazuh Agent (FIM)    │      │ • Criptografia TLS 1.3 │      │ • ClamAV Engine        │
 │ • Armadito Antivirus   │      │ • Token M2M / mTLS     │      │ • Varredura YARA       │
 └────────────────────────┘      └────────────────────────┘      └────────────────────────┘
                                                                              │
                                                                              ▼
                                                                 ┌────────────────────────┐
                                                                 │ 4. AUDITORIA INFRA     │
                                                                 │ • Rkhunter Cron Job    │
                                                                 │ • Auto-Healing IA      │
                                                                 └────────────────────────┘
```

### 3.1. Fases Operacionais de Defesa

1. **Pré-Backup (Origem - Endpoint Client):**
   * O **Wazuh Agent** monitora modificações de arquivos via FIM e intercepta processos que apresentem comportamento de escrita com alta entropia (típico de ransomware).
   * O **Armadito Antivirus** realiza a varredura preventiva de arquivos e executáveis no sistema de arquivos local antes que a engine de backup empacote os dados.

2. **Transferência (In-Flight):**
   * Os dados trafegam cifrados via TLS 1.3 / HTTPS com autenticação mTLS (mutuamente autenticada por certificados X.509) isolados em VLANs de backup dedicada.

3. **Pós-Backup (Destino - Repositório / Server):**
   * Scripts automatizados gerados via **Aider** acionam varreduras isoladas em Sandbox utilizando o **ClamAV** para vírus conhecidos e o **YARA** para regras comportamentais avançadas.
   * Se um snapshot for identificado como infectado, o GBOC isola o ponto de restauração e impede a replicação offsite.

4. **Auditoria de Infraestrutura:**
   * O **Rkhunter** roda em tarefas agendadas (Cron / Task Scheduler) no servidor de storage para garantir que o kernel, módulos do sistema operacional e binários do GBOC não sofreram tampering ou invasão.
