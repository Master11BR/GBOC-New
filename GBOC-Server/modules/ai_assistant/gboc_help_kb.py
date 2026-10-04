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
        "title": "Relatórios executivos e técnicos",
        "keywords": ["relatorio", "relatorios", "report", "pdf", "csv", "exportar", "sla", "compliance report",
                     "finops", "custo", "flagship"],
        "agent": {"menu": "Operações > Relatórios", "url": "/reports.html"},
        "server": {"menu": "Operações > Central de Relatórios", "tab": "reports"},
        "steps": [
            "Abra **Operações > Relatórios** (Agente) ou **Central de Relatórios** (Server).",
            "Escolha um relatório Flagship (proteção, operacional, armazenamento, segurança, conformidade, IA preditiva, FinOps, DR) "
            "ou um dos relatórios de dados.",
            "Clique em **Gerar Agora** e exporte em *Imprimir / PDF*, *CSV* ou *JSON*.",
        ],
        "tips": ["Custo por TB e câmbio usados no FinOps ficam em Configurações > Relatórios."],
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
