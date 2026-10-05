"""
GBOC — Base de conhecimento de uso do sistema para o Copilot (Server + Agent).

Arquivo IDÊNTICO em:
  GBOC-Server/modules/ai_assistant/gboc_help_kb.py
  GBOC-Agent/engines/gboc_help_kb.py

Responde perguntas do tipo "onde fica a restauração de arquivos e como usar?".
Cada tópico descreve onde a função fica no menu (Server e/ou Agente), o link para
abrir a tela e o passo a passo — tudo conferido com as telas reais do sistema.

  * ``find_topics(pergunta, produto)`` → tópicos mais relevantes (busca por palavras-chave,
    sem acento, com sinônimos).
  * ``format_for_prompt(topicos, produto)`` → texto de contexto para o LLM.
  * ``answer_from_kb(pergunta, produto)`` → resposta pronta (usada quando não há LLM).

Links internos usam o formato ``[texto](/pagina.html)`` (Agente) ou
``[texto](gboc:tab:<id>)`` (abas do Server); o widget do Copilot os torna clicáveis.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional

TOPICS: List[Dict] = [
    {
        "id": "restore",
        "title": "Restaurar arquivos (Assistente de Restauração)",
        "keywords": ["restaurar", "restauracao", "restore", "recuperar", "recuperacao", "voltar arquivo",
                     "arquivo apagado", "arquivo deletado", "snapshot", "ponto no tempo", "versao anterior"],
        "agent": {"menu": "Backup > Restaurar e Validar", "url": "/restore.html"},
        "server": {"menu": "Backup > Restaurar e Validar", "tab": "surerestore",
                   "note": "A restauração de arquivos é executada no Agente que fez o backup. No Server você "
                           "acompanha os testes de restauração; para restaurar, abra o painel do Agente "
                           "(porta 9200) ou use Visão Geral > RMM & Terminal."},
        "steps": [
            "Abra **Backup > Restaurar e Validar** no Agente.",
            "**Passo 1 — Repositório:** escolha o repositório onde o backup foi gravado e clique em *Próximo: Escolher Snapshot*.",
            "**Passo 2 — Snapshot:** selecione o ponto no tempo (data/hora do backup) que contém a versão desejada.",
            "**Passo 3 — Destino e opções:** escolha restaurar no local original ou em outra pasta (*Caminho de Destino na Máquina*), "
            "marque *Preservar permissões e datas originais* se precisar e, opcionalmente, use o *Filtro de Arquivos* "
            "para restaurar só alguns arquivos/pastas.",
            "**Passo 4 — Revisão:** confira e clique em *Iniciar Processo de Restauração*; o progresso aparece na tela "
            "e o resultado fica em *Histórico de Restaurações*.",
        ],
        "tips": ["Prefira restaurar em uma pasta alternativa e conferir antes de sobrescrever os originais.",
                 "O teste automático de restauração (SureRestore) também fica nesta tela."],
    },
    {
        "id": "tasks",
        "title": "Criar e agendar tarefas de backup (Jobs e Políticas)",
        "keywords": ["tarefa", "tarefas", "job", "jobs", "agendar", "agendamento", "criar backup", "novo backup",
                     "politica", "politicas", "backup diario", "backup semanal", "retencao", "executar backup"],
        "agent": {"menu": "Backup > Jobs e Políticas", "url": "/tasks.html"},
        "server": {"menu": "Backup > Jobs e Políticas", "tab": "backups",
                   "note": "As tarefas são criadas e executadas em cada Agente; o Server consolida o status de todos."},
        "steps": [
            "Abra **Backup > Jobs e Políticas** e clique em **Nova Tarefa**.",
            "Informe o *Nome da Tarefa*, o *Repositório de Destino* e as *Pastas de Origem* (uma por linha ou pelo *Explorador Visual de Pastas*).",
            "Escolha o *Motor de Backup* (GBOC Nativo, Restic, Kopia ou Duplicati).",
            "Em *Agendamento*, selecione Manual, Diário, Semanal ou Intervalo e o horário/dias.",
            "Defina a retenção (diários, semanais, mensais, anuais) e, se quiser, *Tentar novamente automaticamente em caso de falha*.",
            "Salve. Para rodar na hora, use o botão de executar no cartão da tarefa; o andamento aparece em *Backups Ativos*.",
        ],
        "tips": ["Crie antes o repositório de destino (Backup > Repositórios)."],
    },
    {
        "id": "repositories",
        "title": "Repositórios (onde os backups são gravados)",
        "keywords": ["repositorio", "repositorios", "destino", "bucket", "s3", "wasabi", "b2", "azure", "gcs",
                     "nuvem", "cloud", "disco", "nas", "criptografia", "senha do repositorio"],
        "agent": {"menu": "Backup > Repositórios", "url": "/repositories.html"},
        "server": {"menu": "Backup > Repositórios", "tab": "storage"},
        "steps": [
            "Abra **Backup > Repositórios** e clique em **Novo Repositório**.",
            "Dê um nome, escolha o *Motor de Backup* e o *Tipo de Repositório* (Local, S3, Wasabi, B2, Azure, GCS).",
            "Local: informe o caminho. Nuvem: *Chave de Acesso*, *Chave Secreta*, *Bucket* e, se necessário, Região/Endpoint.",
            "Defina a *Senha de Criptografia do Repositório* (mínimo 8 caracteres) — guarde-a: sem ela não há restauração.",
            "Use *Testar no Modal* e depois **Criar Repositório**.",
        ],
        "tips": ["No Server, a aba Repositórios mostra o uso e o crescimento de armazenamento de todos os agentes."],
    },
    {
        "id": "workloads",
        "title": "Cargas protegidas: bancos de dados, Active Directory, fita LTO e Enterprise",
        "keywords": ["banco de dados", "sql server", "postgres", "mysql", "oracle", "sap", "active directory", "ad ds",
                     "fita", "lto", "tape", "ltfs", "rdx", "cargas protegidas", "workload"],
        "agent": {"menu": "Backup > Cargas Protegidas", "url": "/protected-workloads.html"},
        "server": {"menu": "Backup > Cargas Protegidas", "tab": "workloads"},
        "steps": [
            "Abra **Backup > Cargas Protegidas** e escolha a aba: Bancos de Dados, Active Directory, Fita LTO ou Enterprise.",
            "Bancos de dados: [Backup de Banco de Dados](/database-backup.html) → *Nova Conexão* (tipo, host, porta, usuário, senha) → *Salvar*.",
            "Active Directory: [Backup do AD DS](/active-directory.html) → *Executar Backup a Quente do AD DS*.",
            "Fita: [Backup em Fita](/tape-backup.html) → *Re-escanear Barramento SCSI/SAS*, escolha o dispositivo e o formato.",
        ],
        "tips": [],
    },
    {
        "id": "dr",
        "title": "Disaster Recovery: prontidão, P2V, Instant VM, mídia de boot e laboratório",
        "keywords": ["disaster recovery", "dr", "desastre", "p2v", "vhdx", "instant vm", "maquina virtual de emergencia",
                     "bare metal", "winpe", "midia de boot", "virtual lab", "laboratorio", "runbook", "prontidao"],
        "agent": {"menu": "Disaster Recovery", "url": "/disaster-recovery.html?tab=readiness"},
        "server": {"menu": "Disaster Recovery > Prontidão e Plano", "tab": "dr-readiness"},
        "steps": [
            "Abra **Disaster Recovery** no Agente; as abas cobrem Backup a Quente & AD, Clonagem P2V (VHDX), Instant VM Boot, "
            "Universal Restore, Mídia de Boot (WinPE), Virtual Lab e Auditoria de DR.",
            "Para um plano escrito, use **Exportar Runbook de DR**.",
            "O **Virtual Lab** só valida o boot quando existe um VHDX de recuperação exportado (aba Clonagem P2V).",
        ],
        "tips": ["No Server, o relatório REP-F8 (Prontidão de DR) mostra a situação de todos os agentes."],
    },
    {
        "id": "ransomware",
        "title": "Proteção contra ransomware (Guardian, varreduras e arquivos-isca)",
        "keywords": ["ransomware", "guardian", "canary", "isca", "varredura", "scan", "ameaca", "virus", "malware",
                     "criptografado", "incidente", "shield"],
        "agent": {"menu": "Proteção > Ransomware Guardian", "url": "/ransomware.html"},
        "server": {"menu": "Proteção > Ransomware Guardian", "tab": "ransomware"},
        "steps": [
            "Abra **Proteção > Ransomware Guardian**.",
            "Crie arquivos-isca em **Criar Canary** (informe o caminho); qualquer alteração neles gera incidente.",
            "Use **Nova Varredura** para analisar uma pasta com as ferramentas integradas.",
            "Acompanhe *Incidentes de Ransomware* e *Histórico de Varreduras*; no Server você vê todos os agentes.",
        ],
        "tips": [],
    },
    {
        "id": "alerts",
        "title": "Alertas, jobs com falha e notificações (e-mail, Telegram, webhook)",
        "keywords": ["alerta", "alertas", "notificacao", "notificacoes", "email", "e-mail", "smtp", "telegram",
                     "webhook", "teams", "slack", "falha", "falhou", "jobs com falha", "retry", "aviso"],
        "agent": {"menu": "Operações > Alertas e Falhas / Jobs com Falha", "url": "/alerts.html"},
        "server": {"menu": "Operações > Alertas e Falhas", "tab": "alerts"},
        "steps": [
            "Alertas: **Operações > Alertas e Falhas** → *Nova Regra* (evento + canal).",
            "Canais: [Canais de Notificação](/notification-channels.html) → *Novo Canal* (e-mail, Telegram, webhook).",
            "Falhas e reexecução automática: [Jobs com Falha](/failed-jobs.html) → *Configurar Canais* define SMTP/Telegram/Webhook, "
            "número de tentativas e intervalo; *Enviar Alerta de Teste* confirma a configuração.",
        ],
        "tips": ["No Server, a aba Jobs com Falha consolida as falhas de todos os agentes."],
    },
    {
        "id": "logs",
        "title": "Logs do sistema",
        "keywords": ["log", "logs", "registro", "registros", "evento", "eventos", "erro no log", "historico"],
        "agent": {"menu": "Operações > Logs", "url": "/logs.html"},
        "server": {"menu": "Operações > Logs Globais", "tab": "logs"},
        "steps": [
            "Abra **Operações > Logs** (Agente) ou **Operações > Logs Globais** (Server).",
            "Filtre por nível (Sucesso, Info, Aviso, Erro), por agente e pela busca de texto.",
            "No Agente, cada erro tem o botão *IA Diagnóstico* para explicar a causa provável.",
        ],
        "tips": ["O Server mostra os logs enviados pelos agentes nos últimos 7 dias."],
    },
    {
        "id": "reports",
        "title": "Relatórios (operação, SLA, risco, capacidade, segurança e comercial)",
        "keywords": ["relatorio", "relatorios", "report", "pdf", "csv", "exportar", "sla", "rpo", "compliance report",
                     "finops", "custo", "flagship", "faturamento", "cliente", "agendar relatorio", "enviar relatorio", "email",
                     "relatorio por email", "envio de relatorio", "relatorios agendados"],
        "agent": {"menu": "Operações > Relatórios", "url": "/reports.html"},
        "server": {"menu": "Operações > Central de Relatórios", "tab": "reports"},
        "steps": [
            "Abra **Central de Relatórios** (Server) ou **Operações > Relatórios** (Agente).",
            "Escolha o período, o agente e, no Server, o cliente; filtre por categoria (Operação, SLA, Risco, Capacidade, "
            "Desempenho, Recuperação, Segurança, Comercial) ou use os relatórios Executivos.",
            "Clique em **Visualizar**: o relatório abre com indicadores, constatações, recomendações, gráficos e detalhamento.",
            "Exporte em **Imprimir / PDF**, **CSV**, **HTML** ou **JSON**.",
            "Para receber por e-mail, clique em **Agendar envio** (diário, semanal ou mensal) — usa o SMTP de Configurações > Notificações.",
        ],
        "tips": ["RPO alvo, meta de sucesso, nome da empresa e preços por agente/TB (faturamento MSP) ficam em "
                 "Configurações > Relatórios. Todos os números vêm dos dados sincronizados pelos agentes."],
    },
    {
        "id": "remote_management",
        "title": "Gerenciamento remoto de agentes",
        "keywords": ["gerenciamento remoto", "gerenciar agente", "remoto", "executar tarefa remota", "executar backup agora",
                     "parar backup", "habilitar tarefa", "logs do agente", "sincronizar agente", "intervalo de sincronizacao",
                     "remotamente", "gerencio", "backup remoto", "controlar agente", "administrar agente"],
        "agent": None,
        "server": {"menu": "Visão Geral > Gerenciamento Remoto", "tab": "remote"},
        "steps": [
            "No Server, abra **Visão Geral > Gerenciamento Remoto** e escolha o agente.",
            "Veja conexão, versão, recursos e execuções das últimas 24 h; use **Sincronizar agora** para atualizar os dados no Server.",
            "Na aba **Tarefas**: executar agora, habilitar/desabilitar e ver o histórico; **Em execução**: acompanhar e parar.",
            "Use também as abas **Repositórios** (testar acesso), **Logs**, **Alertas** (reconhecer/resolver) e **Sincronização** (intervalos).",
        ],
        "tips": ["Funciona pelo WebSocket aberto pelo próprio agente — inclusive atrás de NAT/firewall. Ações exigem perfil "
                 "admin ou operator e ficam registradas na auditoria."],
    },
    {
        "id": "decision_panel",
        "title": "Painel de decisão (gráficos do Dashboard Central)",
        "keywords": ["painel de decisao", "graficos", "dashboard", "tendencia", "previsao de armazenamento", "acoes prioritarias"],
        "agent": None,
        "server": {"menu": "Visão Geral > Dashboard Central", "tab": "overview"},
        "steps": [
            "Abra **Dashboard Central**: o Painel de Decisão mostra proteção dentro do RPO, sucesso em 24 h, agentes online, "
            "falhas pendentes e armazenamento.",
            "Escolha o período (7, 14, 30 ou 90 dias) e passe o mouse nos gráficos para ver os valores.",
            "Em **Ações prioritárias**, clique no código do relatório para abrir o detalhamento correspondente.",
        ],
        "tips": [],
    },
    {
        "id": "proactive_alerts",
        "title": "Alertas proativos por e-mail e Microsoft Teams",
        "keywords": ["alerta proativo", "alertas proativos", "teams", "microsoft teams", "avisar", "notificacao", "notificar",
                     "disco cheio", "disco vai encher", "rpo estourado", "falhas seguidas", "agente offline", "lembrete",
                     "reconhecer alerta", "webhook do teams"],
        "agent": None,
        "server": {"menu": "Operações > Alertas e Falhas > Alertas proativos", "tab": "alerts"},
        "steps": [
            "Abra **Alertas e Falhas**: o quadro **Alertas proativos** mostra o que está aberto (crítico/aviso) e o relatório de apoio.",
            "Em **Regras e canais**, informe os e-mails e o webhook do Teams (Workflows → postar em um canal quando receber webhook) e use **Testar**.",
            "Ajuste os limites: repositório que esgota em N dias, disco/volume acima de N%, RPO estourado há N horas, "
            "N falhas seguidas, agente sem contato há N minutos e teste de restauração reprovado.",
            "**Reconhecer** para os lembretes; o alerta é encerrado sozinho quando a situação normaliza (aviso de normalização opcional).",
        ],
        "tips": ["A avaliação roda a cada 5 minutos (ajustável) com os mesmos critérios dos relatórios. "
                 "Os alertas também aparecem na Central de Alertas."],
    },
    {
        "id": "restore_tests",
        "title": "Teste de restauração agendado (evidência de recuperação)",
        "keywords": ["teste de restauracao", "testar restauracao", "testar restore", "validar backup", "comprovar backup",
                     "evidencia", "auditoria de backup", "restore test", "recuperabilidade", "rto"],
        "agent": None,
        "server": {"menu": "Backup > Restaurar e Validar > Testes de restauração", "tab": "surerestore"},
        "steps": [
            "Abra **Restaurar e Validar**, escolha o agente e clique **Testar agora**, ou **Agendar** (diário, semanal ou mensal).",
            "O agente restaura de verdade uma amostra do último snapshot numa pasta temporária, confere tamanho e SHA-256 e apaga a cópia.",
            "Clique no ícone de **Evidência** para ver cada arquivo conferido e o hash da evidência.",
            "Os resultados entram nos relatórios **REP-09** (Restaurações e Testes) e **REP-10** (Prontidão para DR); reprovação gera alerta proativo.",
        ],
        "tips": ["Também dá para testar um repositório específico em Gerenciamento Remoto > Repositórios > Testar restauração. "
                 "Requer o GBOC Agent atualizado."],
    },
    {
        "id": "fleet_operations",
        "title": "Ações em lote e atualização remota do GBOC Agent",
        "keywords": ["lote", "em massa", "varios agentes", "todos os agentes", "atualizar agente", "atualizacao do agente",
                     "versao do agente", "agente desatualizado", "pausar agendamentos", "manutencao", "update agent", "frota"],
        "agent": None,
        "server": {"menu": "Visão Geral > Gerenciamento Remoto > Operações em lote", "tab": "remote"},
        "steps": [
            "Abra **Gerenciamento Remoto** e expanda **Operações em lote e atualização da frota**.",
            "Selecione os agentes (atalhos: Online, Desatualizados, Todos), escolha a ação e clique **Executar** — "
            "sincronizar, executar tarefas, pausar/retomar agendamentos, parar execuções, testar repositórios ou teste de restauração.",
            "Para atualizar: **Gerar da pasta do Agent** (ou **Enviar ZIP**) publica o pacote; depois use a ação **Atualizar GBOC Agent**.",
            "Acompanhe o resultado por agente no lote e no histórico; tudo fica na auditoria.",
        ],
        "tips": ["O agente baixa o pacote do próprio Server (funciona atrás de NAT), confere o SHA-256, guarda cópia dos arquivos "
                 "substituídos e reinicia o serviço; configurações, banco e repositórios locais não são alterados."],
    },
    {
        "id": "report_branding",
        "title": "Relatórios com a marca do cliente (white-label) e envio ao cliente",
        "keywords": ["marca", "logo", "logotipo", "white label", "whitelabel", "personalizar relatorio", "cor do relatorio",
                     "relatorio do cliente", "enviar ao cliente", "contatos do cliente"],
        "agent": None,
        "server": {"menu": "Operações > Central de Relatórios > Marca nos relatórios", "tab": "reports"},
        "steps": [
            "Na **Central de Relatórios**, vá a **Marca nos relatórios**: em *Padrão* cadastre a sua empresa; em cada *Cliente* "
            "o nome, logotipo, cor, rodapé e os e-mails do cliente.",
            "Filtre um relatório pelo cliente: ele sai com a marca do cliente e “Relatório preparado por” a sua empresa.",
            "Em **Novo agendamento** com um cliente selecionado, marque **Enviar também aos contatos do cliente**.",
        ],
        "tips": ["Logotipo: PNG, JPG, SVG ou WEBP de até 300 KB."],
    },
    {
        "id": "agents_pairing",
        "title": "Conectar um Agente ao Servidor Central (chave de pareamento)",
        "keywords": ["conectar agente", "parear", "pareamento", "chave", "servidor central", "registrar agente",
                     "agente offline", "agente nao aparece", "heartbeat", "sincronizar"],
        "agent": {"menu": "Configuração > Configurações Gerais > Servidor Central", "url": "/settings.html"},
        "server": {"menu": "Configuração > Configurações Gerais > Pareamento de Agentes", "tab": "config"},
        "steps": [
            "No **Server**: Configuração > Configurações Gerais > **Pareamento de Agentes** → *Mostrar* → *Copiar* a chave (somente admin).",
            "No **Agente**: Configuração > Configurações Gerais > aba **Servidor Central** → informe a *URL do Servidor Central* "
            "(ex.: https://IP-DO-SERVER:8000) e cole a *Chave de Pareamento* → salvar.",
            "O Agente testa a conexão e a chave na hora; em seguida ele aparece em **Visão Geral > Agentes & MSP** no Server.",
        ],
        "tips": ["Liberar a porta 8000 (Server) e 9200 (Agente) no firewall quando estiverem em máquinas diferentes.",
                 "Se gerar uma nova chave no Server, atualize-a em todos os agentes."],
    },
    {
        "id": "rmm",
        "title": "RMM e terminal remoto",
        "keywords": ["rmm", "terminal", "comando remoto", "powershell", "processos", "servicos", "acesso remoto"],
        "agent": None,
        "server": {"menu": "Visão Geral > RMM & Terminal", "tab": "rmm"},
        "steps": [
            "No Server, abra **Visão Geral > RMM & Terminal** e selecione o agente.",
            "Execute comandos (PowerShell/CMD), veja processos e serviços do agente remoto.",
            "Requer perfil **admin** ou **operator** e o agente pareado e online.",
        ],
        "tips": [],
    },
    {
        "id": "users",
        "title": "Usuários, perfis de acesso e senha",
        "keywords": ["usuario", "usuarios", "senha", "trocar senha", "perfil", "permissao", "permissoes", "acesso",
                     "admin", "operador", "role"],
        "agent": {"menu": "Configuração > Usuários e Permissões", "url": "/users.html"},
        "server": {"menu": "Configuração > Usuários & Permissões", "tab": "users"},
        "steps": [
            "Abra **Configuração > Usuários e Permissões**.",
            "*Novo Usuário*: nome, login, senha e *Nível de Acesso*.",
            "Para trocar a própria senha: *Senha Atual*, *Nova Senha*, *Confirmar* → *Alterar Senha*.",
        ],
        "tips": [],
    },
    {
        "id": "ai_config",
        "title": "Configurar a IA do Copilot (Ollama local ou provedores em nuvem)",
        "keywords": ["ia", "copilot", "llm", "ollama", "openai", "gemini", "claude", "groq", "deepseek", "chave de api",
                     "configurar ia", "modelo"],
        "agent": {"menu": "Configuração > Configurações Gerais > IA & LLMs", "url": "/settings.html"},
        "server": {"menu": "Configuração > Configurações Gerais > IA & LLMs", "tab": "config"},
        "steps": [
            "Clique na engrenagem do Copilot (ou vá em Configurações Gerais > IA & LLMs).",
            "Escolha o provedor: **Ollama Local** (sem internet, informe a URL e o modelo) ou um provedor em nuvem com a chave de API.",
            "Salve. Sem provedor disponível, o Copilot responde com o motor nativo (dados reais e este guia de uso).",
        ],
        "tips": [],
    },
    {
        "id": "engine_migration",
        "title": "Migrar tarefas para o Motor Nativo GBOC",
        "keywords": ["migrar", "migracao", "motor nativo", "trocar motor", "restic para", "duplicati para", "kopia para"],
        "agent": None,
        "server": {"menu": "Configuração > Migração de Motores", "tab": "engine-migration"},
        "steps": [
            "No Server, abra **Configuração > Migração de Motores** e selecione o agente.",
            "Marque as tarefas que usam Restic/Kopia/Duplicati e escolha o repositório nativo de destino (ou crie um).",
            "Clique em *Migrar tarefas selecionadas*: a partir da próxima execução elas usam o Motor Nativo; os backups antigos continuam no repositório de origem.",
        ],
        "tips": [],
    },
    {
        "id": "virtualization",
        "title": "Backup de máquinas virtuais (VMware, Hyper-V, Proxmox) e nuvem/SaaS",
        "keywords": ["vmware", "hyper-v", "hyperv", "proxmox", "vm", "maquina virtual", "vcenter", "m365", "microsoft 365",
                     "exchange", "google workspace", "kubernetes", "saas"],
        "agent": {"menu": "Virtualização e Cloud", "url": "/virtualization.html"},
        "server": {"menu": "Virtualização e Cloud", "tab": "virtualization"},
        "steps": [
            "VMs: **Virtualização e Cloud > VMware, Hyper-V e Proxmox** → conecte o vCenter/host/API e liste as VMs.",
            "Microsoft 365 / Exchange: [Microsoft 365 e Exchange](/m365-exchange.html) → IDs do tenant e do app → *Autenticar Microsoft Graph*.",
            "SaaS e Kubernetes: [SaaS, Kubernetes e Cloud](/saas-cloud-enterprise.html).",
        ],
        "tips": [],
    },
    {
        "id": "storage_usage",
        "title": "Uso e crescimento de armazenamento",
        "keywords": ["espaco", "armazenamento", "disco cheio", "crescimento", "quanto ocupa", "capacidade", "storage"],
        "agent": {"menu": "Configuração > Armazenamento", "url": "/storage-usage.html"},
        "server": {"menu": "Backup > Repositórios", "tab": "storage"},
        "steps": [
            "Abra **Armazenamento** (Agente) ou **Backup > Repositórios** (Server).",
            "*Scan Agora* atualiza o uso; *Configurar Alertas* define limites em GB e crescimento semanal.",
        ],
        "tips": ["O relatório de IA Preditiva estima em quantos dias o disco esgota, com base no crescimento real."],
    },
    {
        "id": "diagnostic",
        "title": "Diagnóstico, saúde e estatísticas",
        "keywords": ["diagnostico", "saude", "lento", "problema", "estatistica", "estatisticas", "performance", "sla"],
        "agent": {"menu": "Operações > Diagnóstico", "url": "/diagnostic.html"},
        "server": {"menu": "Operações > Diagnóstico & Analytics", "tab": "analytics"},
        "steps": [
            "Abra **Operações > Diagnóstico**: saúde, SLA, erros recentes, tarefas mais lentas e com mais falhas.",
            "*Executar Diagnóstico IA Completo* gera recomendações a partir dos dados reais.",
        ],
        "tips": [],
    },
    {
        "id": "central_policies",
        "title": "Políticas centrais e detecção de desvio (drift)",
        "keywords": ["politica central", "politicas centrais", "drift", "desvio", "conformidade", "padronizar",
                     "aplicar politica", "compliance", "politica de backup"],
        "server": {"menu": "Visão Geral > Políticas e Implantação", "tab": "policies"},
        "agent": {"menu": "Definido no Servidor Central (Políticas e Implantação)",
                  "note": "O Agente recebe e aplica a política; não edite manualmente os itens controlados por ela."},
        "steps": [
            "No Server abra **Visão Geral > Políticas e Implantação** e clique em **Nova política**.",
            "Defina o alcance (todos os agentes, uma organização ou agentes específicos), a prioridade e o *filtro de tarefas* (parte do nome).",
            "Configure agendamento, retenção, novas tentativas, janela de manutenção, limite de banda e imutabilidade.",
            "Clique em **Aplicar** para enviar aos agentes; a coluna *Conformidade* mostra quem está em desvio e permite **Reaplicar**.",
        ],
        "tips": ["Quando várias políticas atingem o mesmo agente, vale a de maior prioridade.",
                 "Cada alteração aumenta a versão da política; agentes com versão antiga aparecem como desvio."],
    },
    {
        "id": "mass_install",
        "title": "Implantação em massa de agentes (token de instalação)",
        "keywords": ["implantacao", "instalar agentes", "instalacao em massa", "token de instalacao", "enroll",
                     "enrollment", "gpo", "rmm", "implantar", "provisionar agente"],
        "server": {"menu": "Visão Geral > Políticas e Implantação", "tab": "policies"},
        "agent": {"menu": "install_agent.ps1 -ServerURL <url> -InstallToken <token> -Unattended"},
        "steps": [
            "Publique o pacote do agente em **Atualização de Agentes** (o mesmo pacote é usado na instalação).",
            "Em **Políticas e Implantação > Tokens de instalação** crie um token (organização, validade, limite de usos) e informe a URL pública do Server.",
            "Copie o comando de uma linha e execute como Administrador nas máquinas (ou via GPO/RMM).",
            "O agente instala sem perguntas, registra-se no Server já vinculado à organização e aparece em *Agentes & MSP*.",
        ],
        "tips": ["Revogue o token ao terminar a implantação.",
                 "Se o Server estiver inacessível na hora, o agente tenta de novo a cada 5 minutos por até 72 horas."],
    },
    {
        "id": "maintenance_bandwidth",
        "title": "Janela de manutenção e limite de banda por agente",
        "keywords": ["janela de manutencao", "manutencao", "banda", "largura de banda", "limite de upload",
                     "throttle", "horario comercial", "limitar velocidade"],
        "server": {"menu": "Visão Geral > Gerenciamento Remoto > Operação e imutabilidade", "tab": "remote"},
        "agent": {"menu": "Gerenciado pelo Servidor Central (Gerenciamento Remoto ou Política central)"},
        "steps": [
            "No Server abra **Gerenciamento Remoto**, escolha o agente e a aba **Operação e imutabilidade**.",
            "Adicione janelas de manutenção (dias e horário, inclusive virando a noite): nelas os backups agendados não iniciam.",
            "Defina o limite de upload padrão em Mbps e, se quiser, faixas de horário com limites diferentes.",
            "Salve; os próximos backups já respeitam as regras (execuções puladas ficam registradas).",
        ],
        "tips": ["Execuções manuais não são bloqueadas pela janela de manutenção."],
    },
    {
        "id": "immutable_backup",
        "title": "Backup imutável (S3 Object Lock / WORM local)",
        "keywords": ["imutavel", "imutabilidade", "object lock", "worm", "ransomware", "bloqueio de objeto",
                     "nao apagar backup", "retencao imutavel"],
        "server": {"menu": "Visão Geral > Gerenciamento Remoto > Operação e imutabilidade", "tab": "remote"},
        "agent": {"menu": "Gerenciado pelo Servidor Central (Gerenciamento Remoto ou Política central)"},
        "steps": [
            "Para S3/Wasabi use um bucket criado com Object Lock habilitado (ou crie um pelo botão de aplicar com *criar bucket*).",
            "No repositório escolha o modo **Object Lock**, os dias de retenção e o modo (GOVERNANCE ou COMPLIANCE) e salve.",
            "Clique em **Aplicar** e depois em **Verificar**: o resultado confirma a retenção padrão e se o objeto mais recente está bloqueado.",
            "Para repositórios locais existe o modo **WORM local** (arquivos somente leitura até o fim da retenção).",
        ],
        "tips": ["O WORM local é uma proteção mais fraca que o Object Lock: um administrador da máquina pode removê-la.",
                 "O relatório REP-11 mostra a situação de imutabilidade de todos os repositórios."],
    },
    {
        "id": "client_portal",
        "title": "Portal do cliente",
        "keywords": ["portal", "portal do cliente", "cliente final", "acesso do cliente", "usuario cliente"],
        "server": {"menu": "Configuração > Usuários (perfil Cliente) e /portal.html"},
        "steps": [
            "Crie um usuário com perfil **client** e vincule-o à organização do cliente.",
            "Ao entrar, o cliente é levado ao **/portal.html** com a marca da organização: situação dos backups, relatórios e faturas.",
            "Administradores podem pré-visualizar o portal de uma organização informando ?tenant_id= na URL.",
        ],
        "tips": ["O cliente só enxerga os dados da própria organização e não acessa o painel administrativo."],
    },
    {
        "id": "billing_license",
        "title": "Faturamento mensal e licença",
        "keywords": ["faturamento", "fatura", "cobranca", "fechamento", "fechamento mensal", "preco por agente",
                     "licenca", "license", "chave de licenca", "limite de agentes"],
        "server": {"menu": "Visão Geral > Multi-Tenant MSP (Comercial)", "tab": "multitenant"},
        "steps": [
            "Em **Multi-Tenant MSP**, seção *Comercial*, informe o preço por agente, por TB e a taxa fixa de cada organização.",
            "Use **Pré-visualizar** para conferir o mês e **Fechar mês** (somente meses encerrados); o fechamento pode ser exportado em CSV.",
            "Instale a chave de licença na mesma seção; ela define o número máximo de agentes e a validade.",
        ],
        "tips": ["Um alerta proativo avisa 30 dias antes do vencimento da licença; depois há 15 dias de carência."],
    },
    {
        "id": "themes",
        "title": "Aparência: tema, estilo e layout do menu",
        "keywords": ["tema", "cor", "cores", "escuro", "claro", "layout", "menu horizontal", "menu vertical", "estilo",
                     "aparencia"],
        "agent": {"menu": "Configuração > Estilos & Temas UI", "url": "/ui-style-selector.html"},
        "server": {"menu": "Configuração > Estilos & Temas UI", "url": "/ui-style-selector.html"},
        "steps": [
            "Clique no botão de paleta (canto inferior direito) para trocar tema de cor, estilo e layout (menu vertical ou horizontal).",
            "O botão ☰ recolhe o menu lateral; as preferências ficam salvas no navegador.",
        ],
        "tips": [],
    },
]

_SYNONYMS = {
    "recuperar": "restaurar", "recuperacao": "restaurar", "restore": "restaurar", "restauracao": "restaurar",
    "job": "tarefa", "jobs": "tarefa", "tarefas": "tarefa", "agendar": "agendamento",
    "notificacao": "alerta", "notificacoes": "alerta", "alertas": "alerta",
}

_HOW_WHERE = ("onde", "como", "aonde", "qual menu", "o que e", "o que faz", "para que serve", "passo a passo",
              "tutorial", "ajuda", "explique", "explicar", "configurar", "usar", "utilizar", "fica", "encontro", "acho")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\- ]+", " ", text)


def is_howto_question(question: str) -> bool:
    q = f" {_norm(question)} "
    return any(f" {w} " in q or q.strip().startswith(w) for w in _HOW_WHERE)


def find_topics(question: str, product: str = "server", limit: int = 3) -> List[Dict]:
    return [t for _, t in _scored_topics(question, product)[:limit]]


def _scored_topics(question: str, product: str) -> List:
    q = _norm(question)
    words = set(q.split())
    words |= {_SYNONYMS[w] for w in list(words) if w in _SYNONYMS}
    scored = []
    for t in TOPICS:
        if not t.get(product) and not t.get("agent" if product == "server" else "server"):
            continue
        score = 0
        for kw in t["keywords"]:
            k = _norm(kw).strip()
            if " " in k:
                score += 3 if k in q else 0
            elif k in words:
                score += 2
            elif any(w.startswith(k) or k.startswith(w) for w in words if len(w) >= 5 and len(k) >= 5):
                score += 1
        if _norm(t["title"]).strip() and any(w in _norm(t["title"]).split() for w in words if len(w) >= 5):
            score += 1
        if score:
            scored.append((score, t))
    scored.sort(key=lambda x: -x[0])
    return scored


def _location(topic: Dict, product: str) -> str:
    loc = topic.get(product) or {}
    other = "agent" if product == "server" else "server"
    lines = []
    if loc:
        if loc.get("tab"):
            link = f"[{loc['menu']}](gboc:tab:{loc['tab']})"
        elif loc.get("url"):
            link = f"[{loc['menu']}]({loc['url']})"
        else:
            link = loc["menu"]
        lines.append(f"📍 **Onde fica:** {link}")
        if loc.get("note"):
            lines.append(f"ℹ️ {loc['note']}")
    else:
        o = topic.get(other) or {}
        where = "no Servidor Central" if other == "server" else "no painel do Agente"
        lines.append(f"📍 **Onde fica:** {o.get('menu', '—')} ({where}).")
    return "\n".join(lines)


def format_topic(topic: Dict, product: str) -> str:
    parts = [f"### {topic['title']}", _location(topic, product), "**Como usar:**"]
    parts += [f"{i}. {s}" for i, s in enumerate(topic["steps"], 1)]
    if topic.get("tips"):
        parts.append("💡 " + " ".join(topic["tips"]))
    return "\n".join(parts)


def format_for_prompt(topics: List[Dict], product: str) -> str:
    if not topics:
        return ""
    body = "\n\n".join(format_topic(t, product) for t in topics)
    return ("[GUIA DE USO OFICIAL DO GBOC — use estas localizações e passos exatamente como estão; "
            "não invente menus ou botões. Preserve os links no formato [texto](destino).]\n" + body)


def answer_from_kb(question: str, product: str = "server") -> Optional[str]:
    scored = _scored_topics(question, product)
    if not scored:
        return None
    best = scored[0][0]
    # Segundo tópico só quando a pergunta casa igualmente bem com ele (evita respostas longas demais)
    chosen = [t for s, t in scored[:2] if s >= best]
    return "📘 **Guia de uso do GBOC**\n\n" + "\n\n".join(format_topic(t, product) for t in chosen)


def menu_map(product: str = "server") -> str:
    """Lista curta de todas as funções e onde ficam (para perguntas genéricas de navegação)."""
    out = []
    for t in TOPICS:
        loc = t.get(product)
        if loc:
            out.append(f"• {t['title']}: {loc['menu']}")
    return "\n".join(out)
