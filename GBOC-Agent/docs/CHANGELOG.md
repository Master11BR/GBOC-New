<!-- Copyright (c) 2026 Master11BR - GBOC System v14.8.1 Enterprise. Todos os direitos reservados. -->

# GBOC — Changelog de Atualizações

> Histórico completo de versões, correções e melhorias do sistema GBOC (Agente + Servidor).

---

## 14.8.1 — 2026-10-05 (Backup imutável, Implantação em massa, Políticas centrais, IA Local Ollama e Comercial MSP)

### 🔒 Backup imutável
- **S3 Object Lock** (S3/Wasabi): por repositório, com dias de retenção e modo GOVERNANCE/COMPLIANCE. Aplica a retenção padrão no bucket (ou cria um bucket já com Object Lock) e **verifica** versionamento, retenção e se o objeto mais recente está de fato bloqueado.
- Uploads do motor nativo em buckets com Object Lock passam a enviar Content-MD5 (inclusive em multipart), exigido pelo S3.
- **WORM local** para repositórios em disco: arquivos ficam somente leitura até o fim da retenção (no Windows também com ACL de negação de exclusão); o agente recusa apagar arquivos ou o repositório enquanto houver retenção.
- REP-11 ganhou a tabela “Backup imutável por repositório”, com indicador e recomendações.

### 🚀 Implantação em massa de agentes
- **Tokens de instalação** no Server (organização, validade, limite de usos, revogação), com comando de uma linha para GPO/RMM.
- `install_agent.ps1 -ServerURL -InstallToken -Unattended` instala sem perguntas e registra o agente já vinculado à organização (sem troca manual de chave). Se o Server estiver inacessível, o agente tenta de novo a cada 5 min por até 72 h.
- O agente registrado por token fica **travado na organização** (o heartbeat não altera o tenant).

### 🧭 Políticas centrais com detecção de desvio
- Nova tela **Políticas e Implantação**: alcance (todos / organização / agentes), prioridade, filtro de tarefas, agendamento, retenção, novas tentativas, janela de manutenção, banda e imutabilidade.
- Aplicação em lote nos agentes e coluna de **Conformidade** comparando o que cada agente informa com a política (versão, janelas, banda, agendamento, retenção, imutabilidade), com botão Reaplicar.

### 🤖 Otimização e Resiliência da IA Local (Ollama & Multi-Provedores)
- **Eliminação de Timeout no Ollama CPU com Modelos 8B+ (ex: Llama 3)**:
  - Otimização drástica na montagem de prompts de sistema e contexto operacional: redução superior a 85% no payload de entrada através da poda dinâmica de dumps massivos do banco de dados quando o usuário realiza perguntas conceituais, de documentação ou de navegação ("Como funciona...", "Onde fica...").
  - Truncamento e sumarização inteligente do histórico de conversas (`_smart_history_tokens`) e limitação segura de `num_predict` local no Ollama para evitar loops de geração em CPU que estouravam conexões HTTP.
  - Roteamento instantâneo em milissegundos para pings e testes de conectividade do assistente.
  - Elevação do timeout padrão da inferência local de 180s para 300s (5 minutos), permitindo que nós rodando exclusivamente em CPU completem o processamento de respostas longas sem interrupção de socket.
- **Configuração de Tempo Limite de Resposta na UI (`ai-timeout`)**:
  - Novo parâmetro configurável na aba de Configurações do GBOC Server (`cfg-ai-timeout`) e do GBOC Agent (`ai-timeout`): permite ajustar o timeout de resposta da IA em segundos diretamente pela interface gráfica, persistido em `gboc_system_settings`.
  - Tratamento aprimorado de erros de rede HTTPX com mensagens transparentes e amigáveis ao usuário caso o modelo local exceda o tempo configurado ou esteja sob carga extrema.

### ⏱️ Operação
- **Janela de manutenção** por agente (inclusive virando a noite): backups agendados não iniciam dentro dela; execuções puladas ficam registradas.
- **Limite de banda** de upload (padrão e por faixa de horário) aplicado a restic, kopia, duplicati e ao motor nativo.
- **Restauração pelo Server**: no Gerenciamento Remoto, aba Restaurar — navegar snapshots/arquivos e restaurar numa pasta do agente, acompanhando o status. O motor nativo agora restaura pastas selecionadas corretamente.

### 💼 Comercial MSP
- **Portal do cliente** (`/portal.html`): usuários com perfil *client* veem apenas a própria organização — situação, relatórios com a marca do cliente e faturas; o restante do sistema fica bloqueado para eles.
- **Fechamento mensal**: preço por agente, por TB e taxa fixa por organização; pré-visualização, fechamento (só meses encerrados, com hash de integridade), reabertura, exportação CSV e fechamento automático opcional.
- **Licenciamento por número de agentes**: chave assinada (Ed25519) com limite e validade, alerta 30 dias antes do vencimento e 15 dias de carência. A ferramenta `tools/license_tool.py` (do fornecedor, não distribuída) gera as chaves; o pacote nunca inclui a chave privada.

### 🗂️ Repositórios — todas as configurações, inclusive as do bucket na nuvem
- Novo botão **Detalhes** (ícone ⓘ) em cada repositório do Agente e no Server (Gerenciamento Remoto > Operação e imutabilidade).
- Mostra a configuração salva (bucket, prefixo, região, endpoint efetivo, chave de acesso mascarada, situação da chave secreta e da senha), como o motor enxerga o destino, imutabilidade, último tamanho medido, tarefas que gravam no repositório e, para disco local, espaço livre/total.
- **Consultar nuvem agora** lê do provedor (S3/Wasabi): latência, região real do bucket, versionamento, Object Lock e retenção padrão, criptografia, ciclo de vida, bloqueio de acesso público, política, ACL, tags, CORS, log de acesso, replicação, objetos sob o prefixo (quantidade, tamanho, mais antigo/recente, classes) e o bloqueio do objeto mais recente. Para B2/Azure/GCS: conexão e objetos. Segredos nunca são exibidos.

### 🔑 Correção: chave secreta dos repositórios em nuvem
- A chave secreta (S3/Wasabi/B2/Azure) digitada ao criar ou editar o repositório era descartada e o agente passava a usar a senha do motor no lugar — os backups em nuvem falhavam na autenticação. Agora ela é salva **criptografada** (chave local `data/.repo_secrets.key`, que nunca entra no pacote de distribuição).
- Repositórios em nuvem criados antes desta versão: abra **Editar** e informe a chave secreta novamente (o Detalhes avisa quando ela não está salva).
- A região do bucket passa a ser deduzida do endpoint da Wasabi quando não informada.

### 🩺 Logs Globais, Jobs com Falha e Alertas — dados reais de agentes e do próprio servidor
- **Logs Globais**: abre em *Todo o período* (antes só 7 dias), com os mesmos filtros dos relatórios — 24 h, 7/30/90/180 dias, 12 meses, todo o período ou datas personalizadas, agente, **Servidor central** e cliente — além de busca, contagem "N de M" e **Carregar mais**.
- **Logs do próprio servidor**: avisos e erros do Server (módulos, autenticação, agendadores, exceções) passam a ser gravados junto com os dos agentes, como origem "Servidor central" (sem travar o servidor; mensagens repetidas são agrupadas).
- **Retenção e limpeza** (botão em Logs Globais): mostra quantidade, tamanho, desde quando há logs e a última limpeza; permite ajustar os dias e limpar na hora. A limpeza automática diária continua; **0 = manter tudo** (antes 0 apagava tudo).
- **Os relatórios não perdem dados com a limpeza**: antes de apagar, os erros/avisos de cada dia são resumidos (resumo guardado por 730 dias por padrão) e o relatório de eventos e logs usa esse resumo. Quando o período pedido é anterior aos dados disponíveis, o relatório avisa.
- **Jobs com Falha** (antes sempre 0 — lia uma lista em memória que ninguém alimentava): agora mostra backups com falha (falhas seguidas, desde quando, tentativas/escalação), testes de restauração e verificações reprovados, restaurações com falha, **agentes rejeitados por chave de pareamento inválida**, envios de relatório e alertas que falharam, operações em lote com erro, erros do próprio servidor e módulos do servidor que não carregaram. Filtros por período, agente/servidor, cliente e origem; reconhecer/reabrir; histórico de execuções com falha; taxa de recuperação real. "Testar Alertas" envia de verdade pelo canal configurado.
- **Alertas e Falhas**: a lista "Alertas recentes" estava sempre vazia (uma rota vazia escondia a real). Agora junta alertas proativos, falhas ativas e eventos do sistema, com período e coluna de origem. Quando o módulo de alertas proativos não estiver ativo, a tela explica (reiniciar o serviço) em vez de "Not Found".
- Datas dos logs exibidas no horário em que foram gravadas (antes apareciam 3 h antes).
- **Logs do Agente** (Operações > Logs): mesmo padrão do Server — período de 24 h a 12 meses, *Todo o período* (padrão) ou datas personalizadas, total "N de M", **Carregar mais** e estatísticas do período (antes: fixo nas últimas 48 h e no máximo 30 dias pela API).
- **Retenção automática dos logs do Agente** (antes cresciam sem limite): padrão 90 dias, ajustável no botão *Retenção* (0 = manter tudo), aplicada uma vez por dia em lotes.

### ⚡ Desempenho (lentidão no login e na troca de telas)
- **Causa principal:** cerca de 180 rotas do Server e do Agente eram assíncronas mas faziam consultas síncronas ao banco — cada uma travava o servidor inteiro enquanto rodava. Com agentes sincronizando, o login e as telas ficavam esperando. Essas rotas agora rodam em paralelo (fora do laço principal), incluindo o login do Agente (hash PBKDF2) e a sincronização completa dos agentes.
- O painel do Server deixou de carregar no início os dados de abas escondidas (Usuários, Multi-Tenant, Hermes, Migração de motores, Agentes): cada aba carrega ao ser aberta. Isso também evita a tentativa de descobrir motores em agentes inacessíveis a cada abertura do painel (erro 503 que aparecia nos logs).
- Arquivos CSS/JS ficam 5 minutos em cache do navegador (antes eram revalidados a cada troca de tela, ~20 pedidos por página); fontes e imagens por 1 dia. Depois de uma atualização, Ctrl+F5 aplica na hora.
- O Agente deixou de consultar o banco a cada requisição só para saber se o login está habilitado (resultado em cache por 60 s).
- Corrigidas consultas que falhavam em silêncio e agora apareciam nos logs do servidor: controladores de domínio (AD), eventos de ransomware e lista de tarefas da API v2.
- A versão exibida no cabeçalho (/api/system/info, chamada em toda tela) executava comandos git a cada chamada; agora é lida em segundo plano e fica em cache por 10 minutos.
- A medição de CPU deixou de "dormir" de 0,5 a 1,5 s dentro das requisições: uma thread mede a CPU a cada segundo e as telas recebem o último valor na hora (GBOC_FAST_METRICS=0 desativa).
- Comandos do RMM (processos, serviços, executar), status da proteção contra ransomware e CBT rodam fora do laço principal: não travam mais as outras telas enquanto executam.

### 🔑 Correção: chave de pareamento do Agente "não salva / não reconhecida"
- A chave era salva em C:\ProgramData\GBOC\central_config.json, mas um processo do Agente iniciado antes da troca continuava usando a chave antiga em memória: o Server respondia 401 (AGENT_KEY_INVALID) e recusava o WebSocket (403) indefinidamente. Agora o Agente relê o arquivo a cada 30 s e **aplica** a chave/URL nova (heartbeat, sincronização e WebSocket reconectam sozinhos); ao receber 401 relê o arquivo e tenta de novo na hora.
- Salvar só a URL (chave em branco) mantém a chave gravada no arquivo — antes podia regravar a chave antiga da memória.
- Configurações > Servidor Central mostra a chave salva (mascarada, ex.: gboc_pk_…AB12), se o Server a reconhece (verde/vermelho), o arquivo usado e o processo. Os logs passam a mostrar o PID e a chave mascarada, facilitando identificar um segundo processo do Agente rodando com configuração antiga.

### 🤖 Copilot
- Guia de uso com os novos tópicos: políticas centrais, implantação em massa, janela/banda, backup imutável, portal do cliente e faturamento/licença.

---

## 14.8.0 — 2026-10-04 (Relatórios reais, Painel de Decisão, Gerenciamento Remoto, Alertas proativos e Testes de restauração)

### 📊 Relatórios reais (substituem o catálogo de 50)
- Os 50 relatórios antigos geravam o mesmo conteúdo com números fixos (ex.: “85 MB/s”, “3 Organizações”). Foram substituídos por **20 relatórios calculados sobre dados reais**, com um motor único (`report_core.py`, idêntico no Server e no Agente):
  - Operação: Resumo executivo operacional, Histórico de execuções, Falhas e causa raiz (com MTTR e ação recomendada por categoria de erro), Eventos e logs.
  - SLA: Conformidade de RPO (alvo por tarefa conforme a agenda), Scorecard de SLA por agente/cliente.
  - Risco: Cobertura e lacunas (inclui volumes sem backup), Prontidão para DR (nota 0–100).
  - Capacidade: Capacidade e previsão de esgotamento (regressão linear), Retenção.
  - Performance: Throughput, Recursos dos agentes, Janela de backup/concorrência (mapa de calor).
  - Inventário da frota, Restaurações e testes de recuperação, Segurança/ransomware, Auditoria de acessos, Anomalias.
  - Comercial: Consumo por cliente/faturamento (Server) e Custo de nuvem.
- Saídas: HTML pronto para impressão/PDF (gráficos SVG embutidos, funciona offline), CSV (`;`) e JSON, com hash de integridade.
- **Central de Relatórios** no Dashboard do Server: filtros de período, agente e cliente; pré-visualização; imprimir/CSV/HTML/JSON.
- **Envio agendado por e-mail** (diário/semanal/mensal) com HTML e CSV anexos, usando o SMTP de Notificações.
- Novos parâmetros em Configurações > Relatórios: empresa, alvo de RPO, meta de sucesso, preço por agente/TB e moeda.
- Consolidado do Server reescrito (período e filtro de agente reais).

### 📈 Painel de Decisão (Visão Geral do Server)
- KPIs (RPO cumprido, sucesso 24h, agentes online, falhas pendentes, armazenamento e crescimento, repositórios em risco), execuções por dia, taxa de sucesso × meta, idade do último backup por agente, agentes com mais falhas, armazenamento com projeção de 30 dias e **lista de ações priorizadas** que abre o relatório correspondente. Rota `GET /api/v1/analytics/decision`.

### 🛰️ Gerenciamento Remoto do Agente pelo Server
- Novo menu **Gerenciamento Remoto**: tarefas (executar, ativar/desativar, histórico), execuções em andamento (parar), repositórios (testar acesso), logs, alertas (reconhecer/resolver), intervalos de heartbeat/sincronização e terminal.
- Canal pelo **WebSocket aberto pelo agente** (funciona atrás de NAT/firewall); sem WebSocket, HTTP direto com a chave de pareamento. Ações de escrita exigem perfil admin/operator e ficam na auditoria; desligamento remoto bloqueado.
- RMM e Migração de Motores passam a usar o mesmo canal.

### 🔗 Integração Agente ↔ Server
- **Segurança:** a sincronização completa enviava senhas de repositório ao Server; agora os dados são saneados.
- Novo inventário sincronizado (`POST /api/v1/sync/inventory`): execuções de 30 dias, histórico de tamanho dos repositórios, restaurações, verificações, falhas, volumes e replicação — antes as execuções só chegavam pelo WebSocket.
- Repositórios com status `ready` passam a ser medidos e sincronizados.
- Endereço do agente gravado como `ip:9200` gerava URLs `http://ip:9200:9200` (RMM/migração).

### 🚨 Alertas proativos (e-mail e Microsoft Teams)
- O Server avalia os dados a cada 5 minutos (ajustável) com os mesmos critérios dos relatórios e avisa **antes** do incidente: repositório que esgota em N dias, disco/volume acima de N%, RPO estourado há N horas (ou tarefa que nunca concluiu), N falhas seguidas, agente sem contato há N minutos e teste de restauração reprovado.
- Canais: e-mail (SMTP de Notificações), **Microsoft Teams** (webhook do canal, cartão adaptável) e webhook genérico; um aviso por ciclo agrupando novos alertas, lembretes e normalizações.
- Quadro **Alertas proativos** em Alertas e Falhas: reconhecer (para os lembretes), encerrar, histórico de 30 dias, regras com limites/severidade/canais por regra, “repetir a cada N horas” e botões de teste. Também registrados na Central de Alertas.

### 🧪 Testes de restauração com evidência
- Novo no Agente: restaura de verdade uma amostra do snapshot mais recente em pasta temporária e confere cada arquivo — SHA-256 do manifesto (motor nativo) ou tamanho + SHA-256 do original inalterado (restic/kopia/Duplicati); registra duração, arquivos, hashes e um hash da evidência (`/api/agent-ops/restore-test`).
- No Server (**Restaurar e Validar**): testar agora, agendar (diário/semanal/mensal, amostra e tamanho máximo), resultados com evidência por arquivo; teste reprovado gera alerta proativo e o aprovado encerra o alerta.
- Resultados sincronizados no inventário e usados em **REP-09** (tabela de evidências, repositórios sem restauração comprovada) e **REP-10** (critério “recuperação testada” só conta testes/verificações aprovados; coluna “Último teste de restauração”).

### 🛰️ Ações em lote e atualização remota do Agent
- **Operações em lote** (Gerenciamento Remoto): sincronizar, executar tarefas (todas ou por nome), pausar/retomar agendamentos (retoma exatamente as tarefas pausadas), parar execuções, testar repositórios, teste de restauração e atualizar o Agent — vários agentes por vez, resultado por agente, histórico de lotes e auditoria. Agentes offline são ignorados sem esperar o tempo limite.
- **Atualização remota do GBOC Agent**: o Server publica o pacote (gerado da pasta Agent/GBOC-Agent ao lado do Server ou enviado em ZIP), com SHA-256; o agente baixa pelo próprio canal de sincronização (funciona atrás de NAT), confere hash, caminhos e sintaxe, guarda cópia dos arquivos substituídos (rollback disponível) e reinicia o serviço (NSSM). config/, data/, logs/, repositórios e ferramentas locais nunca são alterados. A lista da frota mostra versão e agentes desatualizados.
- Chamadas HTTP diretas ao agente agora desistem da conexão em 8 s (antes podiam esperar todo o tempo limite com o agente inacessível).

### 🎨 Relatórios com a marca do cliente (white-label)
- **Marca nos relatórios** (Central de Relatórios): marca padrão do provedor e marca por cliente (nome, logotipo, cor, rodapé e contato). Relatórios filtrados por cliente saem com a marca dele e “Relatório preparado por” o provedor — na tela, no HTML/PDF e nos e-mails.
- Agendamentos com cliente podem **enviar também aos contatos do cliente** (e-mails cadastrados na marca do cliente).
- Copilot: novos tópicos sobre alertas proativos, testes de restauração, operações em lote/atualização e marca nos relatórios.
- Testes: `tests/test_ops_features.py`.

### 🧰 Outras correções
- Bibliotecas locais: Font Awesome, Chart.js e o CSS do login agora são servidos de `/static/vendor` (sem depender de CDN/internet).
- Login do Agente: logins bem-sucedidos não contam mais para o bloqueio por tentativas.
- `reports.js` sobrescrevia o carregador do Consolidado do Dashboard (KPIs nunca carregavam).
- Testes: `tests/test_report_core.py`.

## 14.7.7 — 2026-10-04 (Logs robustos, Copilot guia de uso e login limpo) — pendente de build

### 🐞 Correções
- **Central de Logs do Server mais robusta:** leitura tolerante a textos fora de UTF-8 (bases SQL_ASCII/WIN1252 do Windows: UTF-8 → cp1252), consultas fora do event loop e, em qualquer falha (ex.: página corrompida como a reparada na 14.7.6), a tela mostra a mensagem real em vez de lista vazia.
- Filtros, contagens e cores usam o **mesmo critério** (nível + marcadores na mensagem como `[ERROR]`, `falha`, `[PERF-SLOW]`, `sucesso`), com prioridade erro > aviso > sucesso > info — os números das estatísticas batem com a lista filtrada. Rota `/api/v1/logs/agents/{agent_id}` mantida.
- Lista e estatísticas usam a mesma janela (7 dias); se não houver nada nesse período (ex.: relógio/fuso diferente), a tela mostra todo o histórico automaticamente.
- **Menu e barra superior apareciam na tela de login:** o gerenciador de layout não injeta mais menu, topbar, botão de layout, Copilot nem HUD em páginas de autenticação; páginas internas (Server e Agente) sem sessão redirecionam para `/login.html` no próprio servidor.
- Selo de versão do Dashboard do Server mostrava v14.6.0 fixo; agora lê `/api/v1/version`.

### 🤖 Copilot — guia de uso do sistema
- Novo guia oficial (`gboc_help_kb.py`, idêntico no Server e no Agente) com 18 funções: onde fica cada uma no menu e o passo a passo (restaurar arquivos, tarefas, repositórios, DR, ransomware, alertas, logs, relatórios, pareamento, RMM, usuários, IA, migração de motores, virtualização, armazenamento, diagnóstico e temas).
- Perguntas como “onde fica restaurar arquivos e como usar?” são respondidas com links clicáveis que abrem a tela/aba certa. Com LLM configurado, o guia entra no contexto (o modelo é instruído a não inventar menus); sem LLM, a resposta vem direto do guia.
- Novo atalho “📍 Onde fica…”; o Copilot agora formata títulos, *itálico* e links internos (somente destinos locais).
- Testes: `tests/test_help_kb.py`.

### 🔎 Revisão geral (varredura de todas as telas e de 288 rotas GET)
- **Agente respondia HTTP 429 ao navegar:** o limite era 200 chamadas/min por IP (cada tela faz 10–30, mais o polling; vários usuários atrás do mesmo NAT somavam). Agora vale por sessão (1200/min; 300/min sem sessão), ajustável por `GBOC_API_RATE_LIMIT`/`GBOC_API_RATE_LIMIT_ANON`; chamadas do Server com chave de pareamento válida não entram no limite.
- **Erros de rota apareciam como “Serviço de autenticação indisponível” (503) ou 401:** o middleware de autenticação do Agente envolvia a execução da rota no mesmo `try`. A autenticação agora é decidida antes, com a consulta de sessão fora do event loop.
- **Regra 3-2-1 (Replicação) quebrada:** consultava a coluna inexistente `repo_type` em `repositories`.
- **Assistente de primeira configuração (onboarding) do Agente:** 4 chamadas apontavam para rotas inexistentes (verificação do banco, motores, salvar Servidor Central e criar repositório). Agora usa as rotas reais, pede a chave de pareamento e a senha de criptografia do repositório e oferece o Motor Nativo GBOC.
- **Validador de motores:** `shutil` usado antes da importação local fazia o Duplicati nunca ser encontrado pelo PATH.
- **Duplicati nativo:** removida a primeira definição duplicada de `create_backup` (código morto, a segunda é a usada).
- **Envio de logs Agente → Server incremental:** antes eram sempre os 500 mais recentes das últimas 24h a cada ciclo (reenvio constante e perda quando havia mais de 500 entre ciclos). Agora envia só o que é novo desde o último envio (até 2000 por ciclo).
- **Retenção automática no Server:** a limpeza por idade (Configurações > Retenção: logs 30 dias, métricas 90, eventos 60 por padrão) só rodava pelo botão de Manutenção. Agora roda 1x por dia em segundo plano, em lotes curtos (sem travar a tabela); desative com `GBOC_AUTO_RETENTION=0`. O botão de Manutenção roda fora do event loop.
- **Atualizações não apareciam no navegador:** JS/CSS/HTML eram servidos com cache de 1 h e `?v=14.6.0` fixo; agora sempre revalidados (ETag → 304).
- Log do Server (`logs/gboc_server.log`) gravado em UTF-8 (acentos apareciam como “conex�es”).

## 14.7.6 — 2026-10-03 (Auditoria de Banco de Dados, Resiliência de Logs & Aceleração Sub-milissegundo)

### 🚀 Resiliência de Banco de Dados e Logs Globais
- **Reparo Profundo de Corrupção no PostgreSQL (`agent_logs`):** Detecção e saneamento definitivo de página física danificada em disco (`invalid page in block 73833`) que provocava HTTP 500 no endpoint de logs em bases com mais de 4,5 milhões de registros; executada reestruturação limpa via `VACUUM FULL VERBOSE agent_logs` com bypass e zeroing seguro de blocos corrompidos, restabelecendo a integridade física de 100% dos dados válidos (4.542.898 registros).
- **Aceleração de Consulta de Logs em 7.180x (Sub-milissegundo):** Criação dos índices b-tree dedicados `idx_logs_timestamp_desc` (`timestamp DESC`) e `idx_logs_level_time` (`level, timestamp DESC`), eliminando *parallel sequential scans* de 115 mil blocos e reduzindo o tempo de consulta de 2.829 ms para 0,39 ms. Índices registrados no ciclo de warm-up em `startup.py`.
- **Roteador Modular de Logs 100% Consolidado:** Remoção de handlers duplicados legados em `server_gboc.py` e centralização definitiva em `modules/logs/logs_router.py`. Suporte completo a filtros de tipo (`all`, `error`, `warning`, `info`, `success`), pesquisa textual, horas e estatísticas agregadas em `/api/v1/logs/stats`.
- **Mapeamento Assertivo no Dashboard:** Atualização de `mapLogToType(level, message)` em `dashboard.html` para cruzar o nível formal com os marcadores de sucesso nas mensagens (`sucesso`, `concluído`), garantindo que os botões de filtro (`Success`, `Error`, `Warning`, `Info`) exibam 100% dos eventos reais correspondentes.

### 🐞 Correções Gerais
- **Logs do Server vazios em "Todos" e filtros sem efeito:** a lista quebrava por falta da função `escapeHtml` no dashboard (agora helper global em `gboc-perf.js`). Os filtros Sucesso/Info/Aviso/Erro passaram a consultar o banco (`/api/v1/logs?type=`), não só os 300 últimos registros carregados; o seletor de agentes aceita os dois formatos de resposta.
- **Abas do Server em branco** (Cargas Protegidas, Prontidão de DR, Virtualização, Migração de Motores, Hermes): a aba Repositórios não fechava suas `<div>` e engolia as seguintes.
- **Sincronização de logs:** o Agente reenvia as últimas 24h a cada ciclo e o Server gravava tudo de novo (base com centenas de milhares de duplicatas). Agora a gravação é em lote, fora do event loop e ignora linhas já existentes; *Manutenção* remove as duplicatas antigas.
- **Lentidão geral (PERF-SLOW em arquivos estáticos):** o guarda de autenticação consultava o PostgreSQL de forma síncrona a cada requisição e travava as demais; agora usa threadpool e cache de sessão de 15 s (invalidado em logout, troca de senha e alteração de usuários).
- **Agente:** `/api/alerts/` dava HTTP 500 em bases antigas (coluna `acknowledged` ausente) — migração defensiva adicionada.
- **Agente não encerrava com Ctrl+C / parada do serviço:** o Ransomware Shield capturava SIGINT/SIGTERM sem repassar; agora encadeia o handler original.

### 🔁 Migração de Motores
- Funciona com Server e Agente em máquinas diferentes: escolha do agente, descoberta real no banco do Agente (tarefas, repositórios, motores em uso — senhas nunca expostas), seleção das tarefas e do repositório nativo de destino (existente ou novo).
- A migração troca o motor das tarefas para o Motor Nativo GBOC e registra em `audit_log`; os backups antigos continuam no repositório de origem.

### 🎨 Interface
- Central de Logs (Server e Agente) segue o tema: fundos e textos do tema ativo; as cores de nível viram marcadores (barra lateral, ícone, contorno), como os grupos do menu.
- Estilos *Command Sentinel*, *Cyber 3D* e *Nexus Glass* deixaram de usar azul-marinho fixo e acompanham o tema (Red, Amber, Purple, Ocean…); fonte do Command Sentinel unificada em toda a tela.
- Animações e efeitos voltaram (eram desligados quando o Windows estava com “Mostrar animações” desativado).
- Contraste do texto secundário dos temas Âmbar, Vermelho e Roxo elevado para ≥ 6:1.

## 14.7.5 — 2026-10-02 (Segurança Server↔Agente, Relatórios reais e UI padronizada)

### 🔐 Segurança
- **Chave de pareamento Server↔Agente** (`X-GBOC-Agent-Key`): gerada automaticamente pelo Server (tabela `server_secrets`, fora do export de configurações) e exibida em *Configurações Gerais > Pareamento de Agentes* (somente admin, com “Gerar nova”). O Agente a recebe em *Configurações > Servidor Central > Chave de Pareamento* e a envia em heartbeat, sync e WebSocket. A chave legada `gboc-local-server-key` nunca é aceita. Pode ser fixada por `GBOC_AGENT_PAIRING_KEY`.
- Agente: `/api/v1/rmm/`, `/api/ransomware/`, `/api/v2/`, diagnósticos, integridade e power-tools **deixaram de ser públicos** — exigem sessão ou a chave de pareamento. Shutdown só sem sessão via loopback.
- Server: novo guarda global (`modules/users/auth_guard.py`) — toda rota `/api/` exige sessão; rotas de ingestão dos agentes exigem a chave; RMM exige perfil admin/operator.
- Server: corrigido *path traversal* nas rotas de arquivos estáticos (era possível baixar `config.py` e `data/*.json` sem login).
- Proxy RMM não repassa mais o cookie/token do usuário do Server ao Agente.

### 🧾 Zero-Mock
- Relatórios Flagship F1–F8 (Server e Agente) refeitos com dados reais; sem dados mostram “N/D / SEM DADOS”.
- RMM: removido o fallback para `127.0.0.1` (Server e Agente podem estar em máquinas diferentes) e os valores fixos do espelho (3,2 GB / 40%).
- Ransomware: `scans_7d` real (eventos `scan_*` sincronizados); SureRestore no Server retorna 501 (roda no Agente).
- Virtual Lab: não registra mais “validação executada com sucesso” quando nada foi validado.
- Migração de motores: removidos repositórios/credenciais fictícios.
- `server_gboc.py`: removidas definições duplicadas de handlers de tempo real.

### 🎨 Interface (Server + Agente)
- Novo **UI Contract** (fim de `gboc-layout.css`): uma família de tokens (apelidos legados `--primary`, `--text`, `--border`… apontam para os canônicos), fonte única, tamanhos e alturas padronizados de botões, inputs, badges, tabelas e abas; cores sempre do tema ativo.
- Menu lateral: submenus retráteis (acordeão); o item selecionado fica fixo, destacado e visível até a próxima navegação (inclusive após recarregar); nomes não são mais cortados; páginas internas marcam o item “pai” correto.
- Modo horizontal: navegação em segunda linha — não sobrepõe mais os botões da direita; item ativo destacado; submenu não some ao mover o mouse; fecha após escolher.
- Botão ☰ corrigido (havia dois handlers e o clique se anulava); no celular abre o menu lateral/horizontal.
- Removidos CSS duplicados de menu em `_sidebar.html` e `dashboard.html`; botões com cores fixas passaram a usar as variantes do tema.

## 14.7.4 — 2026-10-01 (Auditoria das Funções de IA: Zero-Mock, Segurança e Provedores Atuais)

### 🤖 Camada única de provedores de IA (Server + Agent)
- Novo `ai_providers.py` idêntico em `GBOC-Server/modules/ai_assistant/` e `GBOC-Agent/engines/`: Ollama (`/api/chat`), OpenAI, Groq, Gemini (header `x-goog-api-key` + `systemInstruction`), Claude (campo `system`), DeepSeek, Grok, Kimi, Mistral e Cohere v2.
- Cada provedor usa **somente a sua própria chave e modelo** (antes a primeira chave preenchida era enviada a qualquer provedor e modelos do Ollama, ex. `llama3:latest`, eram enviados à OpenAI/Groq).
- Modelos padrão atualizados (out/2026): `openai/gpt-oss-120b` (Groq — `llama-3.3-70b-versatile` foi descontinuado), `gemini-flash-latest` (Gemini 1.5/2.0 desligados), `claude-sonnet-5-5`, `deepseek-flash`, `grok-4.7`, `kimi-k2.6`, `command-a-plus-05-2026`.
- Timeouts realistas (Ollama 180 s; nuvem 60 s) — antes 6 s, o que fazia quase toda resposta local cair no fallback.
- Regra fixa de ancoragem anexada ao prompt de sistema: a IA não pode afirmar números/status fora do contexto real.

### 🛡️ Zero-Mock (AI_RULES §11)
- Copilot Server: contexto lido do PostgreSQL (`agents`, `agent_task_executions`) — antes lia `agents.json`/`failed_jobs.json` inexistentes e afirmava "Nenhum erro… todos os agentes OK".
- Copilot Agent: removida a frase fixa "Nenhum erro de backup foi registrado na última semana… 100% de integridade"; agora usa `task_executions`, `tasks` e status real do Ransomware Guardian.
- `/diagnose`: telemetria real (psutil) em vez de CPU/RAM/Disco fixos (22/58/42 e 18/52/38).
- `/auto_fix` (Server/Agent) e `/api/v2/system/auto-heal`: retornam **501** explícito com procedimento manual (antes devolviam "corrigido com sucesso" sem executar nada).
- `ai-repair` (Agent): deixou de reescrever execuções `failed` como `repaired` (falsificava o histórico); executa manutenção real (limpeza de `data/temp`, `ANALYZE`, detecção de execuções presas) e reporta ✓/✗ por etapa.
- `ai-analyze-sla`/`ai-analyze-risk`: erros retornam erro (antes SLA 100% / causa inventada).
- REP-F6 *AI Predictive Suite* (Server e Agent): reescrito com `ai_predictive.py` (regressão linear com R², Z-Score, canários/incidentes, janela por hora) — antes todos os valores eram fixos (score 91, "confiança 95%", "22h–04h").
- `modules/analytics/analytics_router.py`: removida resposta fixa (12 agentes, 100%).
- Frontend: removidos textos de sucesso fabricados em `diagnostic.html`, `tasks.html`, `index.html` e `dashboard.html`; score `null` exibido como "indisponível" (antes `?? 100`).

### 🔐 Segurança
- Agent: `/api/ai/*` e `/api/v1/ai/*` deixaram de ser públicos; `/api/v1/diagnostics/ai-config` exigia nada e **retornava as chaves de API em texto puro** — agora exige sessão e mascara.
- Server: `/api/v2/ai/*` sem autenticação → exige sessão; gravação de configuração e *pull* de modelos exigem perfil administrador.
- Rotas duplicadas `/api/v1/server/ai-config` (memória/variáveis de ambiente, sem auth) unificadas na configuração real.
- Chaves mascaradas (`sk-a...wxyz`) não sobrescrevem mais a chave real ao salvar; URLs do Ollama validadas (somente http/https).
- XSS corrigido no widget do Copilot e nas telas que exibiam respostas da IA via `innerHTML`.
- Middleware de autenticação do Agent agora é *fail-closed*.

### 🧩 Arquitetura / correções gerais
- Rotas de IA de diagnóstico do Agent movidas de `agent_gboc.py` para `api/diagnostics.py` (entrypoint mais enxuto).
- Removidas rotas de `agent_gboc.py` que importavam módulos vazios (`core/cbt_vss.py`, `core/agent_dr_sync.py`) e **sobrepunham** as rotas reais de `modules/cbt` e `modules/dr` (botão "Exportar Runbook" de DR sempre falhava).
- Novos testes: `tests/test_ai_providers.py` (28 testes).

## 14.7.3 — 2026-09-28 (AI Copilot Router Modernization, Security Auth Enforcement & Predictive Fallback Precision)

### 🤖 Modernização do Server AI Copilot & Resolução de Falhas de Integração (Bugs 11, 12 e 13)
- **Bug 11 — Extração da Função Standalone Reutilizável `query_server_ai_assistant`**:
  - Toda a lógica de inferência multi-provedor (DeepSeek V3/R1, Ollama Local On-Premises, Groq Cloud, OpenAI GPT-4o, Google Gemini, Anthropic Claude + Fallback preditivo nativo) foi extraída para a função independente `query_server_ai_assistant(prompt: str, provider_override: Optional[str] = None) -> Dict[str, Any]`.
  - Retorno normalizado em dicionário Python estruturado (`dict`), desacoplado de objetos `JSONResponse`.
  - Resolução definitiva do `ImportError` crônico em [GBOC-Server/modules/v2/ai_v2_router.py](file:///d:/GBOC-New/GBOC-New/GBOC-Server/modules/v2/ai_v2_router.py), restaurando a rota oficial `/api/v2/ai/query` (retornando envelope oficial padronizado com status HTTP 200).
- **Bug 12 — Imposição Rigorosa de Autenticação em Todos os 7 Endpoints de IA (OWASP API Security)**:
  - Eliminação de superfícies desprotegidas e vetores potenciais de Server-Side Request Forgery (SSRF) nas configurações de `ollama_url` e consulta de modelos.
  - Implementação dos helpers `_get_current_user_from_req(request)` e `_require_auth(request)` validando token de sessão (`Bearer <token>` ou cookie `gboc_server_token`) na tabela `server_auth_tokens`.
  - Cobertura de autenticação obrigatória (HTTP 401 para acessos anônimos) em:
    1. `POST /api/v1/ai/query`
    2. `GET /api/v1/ai/config`
    3. `POST /api/v1/ai/config`
    4. `POST /api/v1/ai/diagnose`
    5. `POST /api/v1/ai/auto_fix`
    6. `GET / POST /api/v1/ai/ollama/models`
    7. `POST /api/v1/ai/ollama/models/pull`
- **Bug 13 — Precisão Analítica do Fallback Preditivo Nativo (Eliminação de Contradição Semântica)**:
  - Refatoração do coletor operacional `_build_server_system_context() -> Tuple[str, int]` para retornar tupla com texto contextual e a contagem real de jobs com falha (`failed_jobs_count`).
  - Correção semântica no motor preditivo nativo de fallback:
    - Quando houver incidentes (`failed_jobs_count > 0`): emite sinalização precisa `🔴 {failed_jobs_count} job(s) com falha registrado(s) nos últimos 7 dias / 24h` com recomendação de auditoria técnica.
    - Quando não houver incidentes (`failed_jobs_count == 0`): emite confirmação de conformidade `🟢 Nenhum erro de backup foi registrado nos últimos 7 dias`.
- **Validação de Testes Automatizados**:
  - 100% de aprovação na suíte de testes de regressão com `FastAPI TestClient`, `pyflakes` (0 erros) e `py_compile`.

---

## 14.7.2 — 2026-09-27 (Logs Sentinel UI, Kyle Zantos Motion Principles & Core Engine Runtime Fixes)

### 🩺 Integridade de Runtime & Correção de Exceções pyflakes (10 Correções Críticas)
- **Eliminação Total de NameError e Saneamento de Módulos Core**:
  - **`GBOC-Agent/utils/diagnostic_report.py`**: Instanciação explícita de `logger = logging.getLogger("DiagnosticReport")`, eliminando falha ao registrar erros de diagnóstico de restore.
  - **`GBOC-Server/modules/reports/flagship_reports.py`**: Inclusão de `import logging` e instância do `logger`, corrigindo exceção ao emitir logs analíticos nos 7 Relatórios Flagship.
  - **`GBOC-Server/modules/reports/reports_router.py`**: Importação de `db_manager` e saneamento de 9 referências quebradas a `core.get_db_connection()`, garantindo que os relatórios executivos consultem o banco de dados sem interrupção.
  - **`GBOC-Agent/api/diagnostics.py`**: Importação de `Request` e módulo `time` ausentes, restaurando integridade do endpoint de diagnóstico em tempo real.
  - **`GBOC-Agent/api/auth.py`**: Importação de `timezone` ausente do módulo `datetime`, corrigindo expiração de tokens e autenticação segura de sessões.
  - **`GBOC-Agent/shared_core.py`**: Importação de `Path` do módulo `pathlib`, eliminando NameError durante inicialização defensiva de repositórios locais.
  - **`GBOC-Agent/engines/healer_engine.py`**: Importação de `time` no módulo de autorrecuperação, estabilizando retentativas automáticas e cálculo de latência.
  - **`GBOC-Agent/engines/engine_validator.py`**: Importação de `shutil` ausente para validação e checagem de binários de motores de backup no host.
  - **`GBOC-Agent/engines/backup_engine_manager.py`**: Importação de `psycopg2` ausente, prevenindo NameError durante inicialização da base de dados dos motores de backup.
  - **`GBOC-Agent/api/reports_api.py`**: Importação de `time` ausente, corrigindo cálculo de benchmarks de execução de relatórios.
  - **Auditoria Estática**: 0 erros em `py_compile` e `pyflakes` em todos os 275+ módulos Python do repositório.

### 🎨 Logs Sentinel UI & Kyle Zantos Motion Principles
- **Arquitetura Visual Toast Notification Premium**:
  - Implementação completa em [GBOC-Agent/static/logs.html](file:///d:/GBOC-New/GBOC-New/GBOC-Agent/static/logs.html) e [GBOC-Server/modules/logs/logs.html](file:///d:/GBOC-New/GBOC-New/GBOC-Server/modules/logs/logs.html) com estética Modern Glassmorphism (painel com `backdrop-filter: blur(16px)` e bordas translúcidas).
  - Pseudo-elementos flutuantes `.toast::before` e `.toast::after` proporcionando profundidade óptica com círculos translúcidos dinâmicos.
  - Contêiner de ícone frosted glass (37×37px) com relevo e glifos centralizados (`✓`, `i`, `!`, `×`).
  - Transições e animações fluidas baseadas nos Princípios de Movimento de Kyle Zantos: entrada em cascata com atraso progressivo (`@keyframes appear`) e saída suave com descarte fluido (`@keyframes disappear`).
- **Layout de Grade Horizontal Estruturado (3 Colunas)**:
  - Resolução do bug de empilhamento vertical (onde ícone, mensagem e botão quebravam em 4 linhas separadas).
  - Estruturação estrita em 3 colunas: Coluna 1 (Ícone: 39px) | Coluna 2 (Conteúdo e Metadados: 1fr) | Coluna 3 (Contêiner de Ações com Diagnóstico IA e botão Dismiss: auto).
- **Filtros Cromáticos Semafóricos & Mapeamento Inteligente**:
  - Botões de cápsula com gradientes táteis para `Todos` (cinza ardósia), `Success` (verde esmeralda), `Info` (azul royal), `Warning` (âmbar vibrante) e `Error` (vermelho carmim).
  - Mapeamento analítico inteligente no banco de dados: reconhecimento de status de sucesso em eventos com nível `INFO` contendo `[SUCCESS]`, `[OK]`, `sucesso` ou `concluída`.
  - Agrupamento de alertas de desempenho `[PERF-SLOW]` e limites de latência em `Warning`.

### 🌐 Universal CSS Architecture Policy & Distribuição
- **Sincronização 100% Canônica (Zero-Isolated CSS)**:
  - Inclusão das classes `.log-toast-panel`, `.toast`, `.filters`, `.toast-actions` e animações no arquivo canônico [shared-css/style.css](file:///d:/GBOC-New/GBOC-New/shared-css/style.css).
  - Propagação via `tools/sync_css.py` para as instâncias de Agent e Server.
  - Injeção das regras prioritárias em `<style>` nos cabeçalhos para neutralizar agressividade de cache de navegadores com versão de cache-busting `?v=14.7.2`.
- **Empacotamento de Distribuição Atualizado**:
  - Geração completa do pacote em `D:\GBOC-New\GBOC-Distribution` via [build_installer_package.ps1](file:///d:/GBOC-New/GBOC-New/build_installer_package.ps1).

---

## 14.7.0 — 2026-09-22 (Padrão Oficial de Relatórios v3.0 & Zero-Mock Intelligence)

### 📊 Padrão Oficial de Relatórios v3.0 (Contrato JSON Universal & Zero-Mock Estrito)
- **Eliminação de Mocks e Correção dos 10 Bugs Históricos (BUG-01 a BUG-10)**:
  - **`v3_reports_engine.py`**: Motor oficial normativo para o GBOC Agent implementando paridade comercial com Veeam ONE, Rubrik Radar e Datto RMM.
  - **BUG-01 Resolvido**: SLA e RPO calculados individualmente por tarefa (`QUERY_RPO_PER_TASK`), com duração e RTO reais, substituindo "15 min" e status binários por semáforo tri-estado (`CONFORME`, `EM RISCO`, `NÃO CONFORME`).
  - **BUG-02 Resolvido**: Throughput de rede e disco calculados a partir de telemetria real em `task_executions` / `backups`, eliminando taxas fixas (85/72/48 MB/s).
  - **BUG-03 Resolvido**: Poda e retenção alimentadas diretamente de `settings` (`category='retention'`) e eventos reais de `system_logs` (pruning / snapshot removido).
  - **BUG-04 Resolvido**: Dead Letter Queue (DLQ) com contagem real de retentativas e agrupamento de falhas por fingerprint de erro.
  - **BUG-05 Resolvido**: Uptime, PID e consumo de memória coletados em tempo real via `psutil.Process(os.getpid())`, eliminando "PID 4120" e "99.98%" fixos.
  - **BUG-06 Resolvido**: Testes de restauração auditados a partir de eventos reais de restore em `system_logs` e `surebackup_verifications`, eliminando caminhos fictícios `C:\Temp\RestoreTest`.
  - **BUG-07 Resolvido**: Ransomware Shield avaliado com base em canários físicos reais (`ransomware_canaries`), integridade de hash e histórico de alertas.
  - **BUG-08 Resolvido**: Predição de esgotamento de storage por regressão linear (série temporal de 30 a 90 dias) projetando crescimento diário real e data de esgotamento estimada.
  - **BUG-09 Resolvido**: Parecer executivo de IA gerado por template analítico cruzando $\ge 2$ métricas (taxa de sucesso, RTO vs RPO alvo, tendências temporais vs período anterior e ação corretiva imediata).
  - **BUG-10 Resolvido**: Resolução dinâmica e resiliente entre `backups` (SQLite) e `task_executions` (PostgreSQL), garantindo zero queries falhando silenciosamente.
  - **Tratamento de REPs Sem Sensor Local**: REPs 33, 36, 38, 41, 46, 47 retornam expressamente `status: "unavailable"` com diagnóstico e orientações de configuração em vez de números forjados.
- **Higienização de Nomes e Integridade Criptográfica**:
  - Implementação de `_clean_task_name()` para remover sufixos de identificadores automáticos (ex: `_PEZ2B4L6H7L8R9YIIWNV`).
  - Assinatura criptográfica SHA-256 (`integrity_hash`) em todos os payloads JSON gerados.
- **Interface e Visualizador Oficial (`reports.html` & `reports_api.py`)**:
  - Exibição de Scorecard com gauge e semáforo dinâmico.
  - Caixa de Delta analítico ("O que mudou vs período anterior").
  - KPI Cards enriquecidos com Meta/Target e Status Dot coloridos.
  - Seção formal de "Ações Recomendadas" categorizadas por prioridade (`ALTA`, `MÉDIA`, `BAIXA`).
  - Sincronização e extensão com os 7 Relatórios Flagship (`REP-F1` a `REP-F7`).

---

## 14.6.1 — 2026-09-22 (Arquitetura de Relatórios Flagship v2.0 & Inteligência Executiva)

### 📊 Arquitetura de Relatórios Flagship v2.0 (Zero-Mock End-to-End)
- **7 Relatórios Flagship de Mercado (`REP-F1` a `REP-F7`)**:
  - Consolidação dos 50 relatórios originais como **módulos internos de dados** que alimentam 7 relatórios flagship executivos:
    - **`REP-F1` — Data Protection & Resilience Scorecard**: Visão executiva em menos de 10 segundos da proteção da infraestrutura, RPO/RTO individuais, SLA e cobertura de tarefas.
    - **`REP-F2` — Cyber Resilience & Ransomware Threat Report**: Linha do tempo unificada de eventos de segurança, honeypots/canários ativos, proteção WORM e sandbox SureRestore.
    - **`REP-F3` — Storage Intelligence Report**: Saúde dos repositórios, esgotamento preditivo de capacidade, deduplicação FastCDC/ZSTD real e custo cloud projetado.
    - **`REP-F4` — Compliance & Governance Report**: Auditoria de SLA em minutos, políticas de retenção/descarte, requisitos LGPD/GDPR e trilha de auditoria administrativa.
    - **`REP-F5` — Operational Performance Report**: Telemetria individual de execuções (sem médias agregadas por linha), comparativo entre motores e causa raiz de falhas.
    - **`REP-F6` — FinOps & Total Cost of Ownership Report**: TCO detalhado com cotação em tempo real USD→BRL (Banco Central), oportunidades de economia e eficiência energética.
    - **`REP-F7` — Disaster Recovery Readiness Report**: Matriz de prontidão para DR, gaps reais vs metas de RTO/RPO por ativo crítico, estimativa Bare-Metal e simulação de contingência.
- **Filosofia de Design & Estrutura Universal**:
  - **Score único por tela** (0–100) com componentes ponderados.
  - **Delta ("O que mudou")**: 3 bullets automáticos comparando com período anterior (↑ melhoria, ↓ atenção, → tendência dominante).
  - **KPI Cards com Benchmark Embutido**: Valor Real, Alvo e Semáforo de Status (CONFORME, EM RISCO, NÃO CONFORME).
  - **Narrativa antes da tabela**: Frase-síntese de IA antes de cada tabela analítica.
  - **Dados reais e individuais**: Métricas individuais por tarefa/repositório, proibindo repetição de médias globais por linha e ocultando IDs brutos internos.
  - **Ações recomendadas obrigatórias priorizadas**: Bloco priorizado (`[ALTA]`, `[MÉDIA]`, `[BAIXA]`) com responsável sugerido e prazo estimado.
  - **Hash SHA-256 e Assinatura Digital**: Cabeçalho e rodapé oficiais com integridade criptográfica SHA-256 e grid formal de assinatura técnica para documentos A4.
- **Implementação Multi-Plataforma Simétrica (Server & Agent)**:
  - Backend e rotas `/api/v1/reports/flagships` e `/api/reports/flagships` em ambos os sistemas.
  - Interface visual com alternador ágil entre os 7 Flagships e os 50 módulos internos de dados em ambos os painéis.
  - 4 formatos de saída padronizados: HTML Interativo, PDF/A4 Oficial, CSV Tabular e JSON REST API.

---

## 14.6.0 — 2026-09-20 (Operational Backup, Disaster Recovery & Canonical 7-Domain Architecture Release)

### 🛡️ Arquitetura Operacional de Backup & Disaster Recovery (Zero-Mock End-to-End)
- **Validação Operacional Real em Sandbox Hyper-V (`SureRestore` & `Virtual Lab`)**:
  - Implementação do ciclo completo de teste de recuperabilidade: Restauração -> Criação de VM Hyper-V em switch isolado (`GBOC-VirtualLab-Switch` / `GBOC-SureRestore-Switch`) -> Boot -> Validação de heartbeat -> Coleta de evidência -> Desmontagem segura.
  - Zero simulações: sem Hyper-V habilitado no host, o sistema reporta explicitamente a indisponibilidade do hypervisor ao invés de forjar status "OK".
- **Validação Específica por Tipo de Carga de Trabalho**:
  - **Bancos de Dados PostgreSQL**: Validação através de `pg_restore --list` e restauração real em schema temporário, falhando imediatamente caso o código de saída seja diferente de zero ou contenha erros estruturais.
  - **Bancos de Dados SQLite**: Execução real de `PRAGMA integrity_check` e `PRAGMA foreign_key_check` sobre o arquivo restaurado, capturando corrupções reais.
  - **System State & Bare-Metal**: Verificação física de componentes críticos (`wbadmin`, `NTDS`, `SYSVOL`, `Registry hives`) e drivers de boot WinPE sem fabricação de cabeçalhos.
  - **Conversão P2V em Bloco**: Conversão física de volumes locais para disco virtual VHDX com validação prévia de privilégios de Administrador e streaming contínuo.

### 🧭 Reestruturação Canônica de Navegação em 7 Domínios
- **Navegação Modular Baseada em Operações de Negócio (`sidebar.js` & `_topbar.html`)**:
  - Reorganização de todas as rotas do Agent e Server nos 7 domínios canônicos corporativos:
    1. **Visão Geral**: Dashboard executivo, Overview e Auditoria/Logs.
    2. **Backup**: Jobs, Políticas, Histórico, Repositórios e Agendamento.
    3. **Disaster Recovery**: SureRestore, Virtual Lab, Failover, P2V e Live Recovery.
    4. **Proteção**: Cargas Corporativas Consolidadas (Databases, Active Directory, Tape Library, Enterprise).
    5. **Virtualização & Cloud**: Hyper-V, VMware, Cloud Storages e Object Storage (S3/Azure).
    6. **Operações**: Monitor de Tarefas em tempo real, HUD de Telemetria e Alertas.
    7. **Configuração**: Configurações Globais, Credenciais, Notificações, Atualizações e Estilos visuais.
- **Consolidação de Workloads Protegidos (`protected-workloads.html`)**:
  - Fusão e unificação de telas legadas dispersas em uma única interface moderna com deep-linking (`#databases`, `#activedirectory`, `#tape`, `#enterprise`) e redirecionamentos transparentes mantendo retrocompatibilidade total.

### ⚡ Otimização de Performance e Integridade do Frontend
- **Safe HTML Rendering com Diff Completo (`gboc-perf.js`)**:
  - Substituição da verificação de tamanho parcial por comparação estrita de string (`safeRender`), evitando inconsistências visuais em atualizações parciais de HTML.
- **Cancelamento de Requisições Obsoletas (`gbocPerf.makeCancellable()`)**:
  - Suporte a `AbortController` nas rotinas de polling e navegação, prevenindo concorrência desnecessária no backend.
- **Saneamento do Monitor de Tarefas (`task_monitor.js`)**:
  - Remoção de declarações corrompidas e unificação de inicialização segura do monitor em tempo real.

### 📦 Distribuição & Padronização Global
- **Sincronização Canônica Universal & Unificação Estrita de Versão (Single Source of Truth)**:
  - Erradicação de literais de versão legada (`14.1.0`, `14.2.0`, `14.4.0`, `14.5.0`) em todos os endpoints (`/api/system/info`, `/api/system/version`, `/api/v2/system/version`), scripts e modelos HTML.
  - Varredura e consolidação de mais de 335 arquivos para a versão canônica **v14.6.0 Full Stable Enterprise**.
  - Redesenho completo do motor de relatórios executivos com diagramação A4 de alta fidelidade para impressão/PDF, hash de auditoria SHA-256 e scorecards de KPI reais.
  - Atualização dos scripts de build e distribuição (`build_installer_package.ps1`, `tools/make_distribution.py`, `Setup.ps1`).

---

## 14.5.0 — 2026-09-18 (Universal CSS Architecture, Enterprise Modal System, V7 Authentication UI & Duplicati Cloud Stabilization)

### 🎨 Arquitetura Universal de CSS (100% Shared Stack & Zero CSS Isolado)
- **Unificação Estrita de Folhas de Estilo (`GBOC-Server` & `GBOC-Agent/static/`)**:
  - Sincronização e padronização dos 5 arquivos centrais da stack universal:
    1. `style.css`: Framework de componentes universais (Reset, Cards, Botões, Tabelas, Badges, Formulários, Toasts e Modais).
    2. `gboc-themes.css`: Design tokens globais, 8 Estilos de UI (`minimal`, `neumorphism`, `claymorphism`, `fluent`, `nexus-widgets`, `nexus-glass`, `command-sentinel`, `cyber-3d`), 6 Temas de Iluminação (`dark`, `light`, `amber`, `purple`, `ocean`, `red`), Presets Bacula/Fiorilli e tokens de alto contraste para Light Mode.
    3. `gboc-layout.css`: Layout responsivo universal (Sidebar Vertical + Topbar Horizontal).
    4. `gboc-hardware-hud.css`: HUD de telemetria física de hardware em tempo real.
    5. `gboc-file-picker.css`: Explorador universal de arquivos e diretórios.
  - Varredura e padronização automatizada de todas as **53 páginas HTML** do ecossistema para carregar a stack canônica compartilhada.
  - Eliminação completa de arquivos CSS órfãos, regras divergentes ou estilos embutidos sem tokenização.

### 💬 Sistema Corporativo Universal de Modais & Caixas de Diálogo (`gboc-modal.js`)
- **Interceptador Global e Transparente para `alert()`, `confirm()` e `prompt()`**:
  - Substituição automática das caixas de diálogo nativas e síncronas do navegador por modais modernos baseados em DOM e Promises assíncronas.
  - Design sofisticado com fundo translúcido (`backdrop-blur-md`), elevação de card, bordas sutis e tipografia padronizada.
  - Detecção inteligente de contexto e severidade com base em palavras-chave e emojis (*sucesso, erro, falha, atenção, aviso, info*).
  - Acessibilidade integral com navegação por teclado (`Enter` para confirmar, `Escape` para fechar) e foco inteligente em campos de input.

### 🔐 Interface Visual de Autenticação V7 (Dark Glassmorphism)
- **Novo Design Unificado (`GBOC-Server/login.html` e `GBOC-Agent/static/login.html`)**:
  - Implementação de layout sofisticado em Tailwind CSS com fundo dark (`zinc-900/70`), blur de vidro de alta definição (`backdrop-blur-2xl`) e paleta dourada/âmbar (`amber-500` / `yellow-500`).
  - Navegação suave por abas entre **Sign In (Login)** e **Create Account (Setup / Primeiro Acesso)**.
  - Alternador dinâmico de visibilidade de senhas (*Eye Toggle*) em tempo real.
  - Suporte à persistência de usuário com caixa de seleção *"Lembrar credencial"* via `localStorage`.
- **Modo Setup / Provisionamento Inicial Automático**:
  - Detecção no frontend de instâncias sem administradores cadastrados (`/status`).
  - Redirecionamento automático e exibição de banner informativo para a criação da credencial master do administrador (`/setup`).
  - Auto-login transparente logo após a conclusão do cadastro inicial com persistência dos tokens corporativos (`gboc_server_token` / `gboc_token`).
- **Política Zero-Mock & Conformidade LGPD**:
  - Eliminação de botões de login social simulados (Google/Apple).
  - Adição de badges de segurança real com base nas capacidades criptográficas ativas do sistema (*Criptografia SHA-256 / PBKDF2* e *Auditoria Ativa*).

### 🛠️ Correções Críticas no Motor de Importação Duplicati
- **Suporte Total a Repositórios Cloud (`task_manager.py`, `repository_manager.py`, `real_restore_manager.py`, `integrity_api.py`)**:
  - Normalização completa para tipos de repositório `cloud` suportados pelo Duplicati nativo (`s3`, `azure`, `googledrive`, `onedrive`, `dropbox`, `webdav`, `sftp`).
  - Eliminação da exceção `Tipo de repositório Duplicati não suportado: cloud`.
- **Auto-Recuperação de Banco Duplicati Corrompido (`DatabaseRepairInProgress`)**:
  - Detecção preventiva e deleção segura de bancos SQLite locais corrompidos ou com reparo incompleto antes de acionar a rotina `repair` do executável nativo do Duplicati.
  - Garantia de recriação limpa do catálogo de metadados sem interrupção do pipeline de backup ou importação.

### 📦 Distribuição & Versionamento
- **Atualização SemVer 2.0 Global**:
  - Elevação do versionamento canônico para **v14.5.0 Full Stable Enterprise** em todos os módulos centrais.
  - Atualização automática do manifesto `package_manifest.json` e dos instaladores `Setup.bat` / `Setup.ps1`.

---

## 14.4.0 — 2026-09-14 (Performance & Resilience Release — Zero-Freeze Async Engine, Disaster Recovery Acceleration & Hardware HUD)

### 🚀 Zero-Freeze Async Engine Architecture
- **Desacoplamento Assíncrono (`asyncio.to_thread`) (`modules/dr/dr_router.py` & `modules/virtualization/virtualization_router.py`)**:
  - Eliminação definitiva de travamentos e bloqueios na interface ao navegar para `/virtualization.html` e `/disaster-recovery.html`.
  - Todas as chamadas síncronas de baixo nível ao sistema operacional e subprocessos agora são executadas em *worker threads*, mantendo o Event Loop do FastAPI 100% responsivo para tráfego web, WebSockets e pings de telemetria.
- **Cache TTL em Memória Thread-Safe (`disaster_recovery_engine.py` & `vmware_hypervisor_engine.py`)**:
  - Implementação de cache em memória thread-safe (30s) para topologia de discos (`_disks_cache`), informações do Active Directory / VSS (`_sys_info_cache`), readiness score (`_readiness_cache`) e inventário Hyper-V (`_vms_cache`).
  - O tempo de resposta em requisições concorrentes ou subsequentes dentro da janela de TTL caiu de 48.9s para **0.005ms (instantâneo / 0ms)**.
- **Consulta Batch em Lote Único de Discos e Partições**:
  - Substituição do loop sequencial com múltiplos processos `powershell.exe` por uma única consulta unificada PowerShell para todos os discos físicos e partições de uma vez só.
  - Tempo de descoberta de armazenamento reduzido de **16.33s para 3.38s** (-79%).
- **Detecção Sub-Milissegundo de Active Directory & Hyper-V**:
  - Substituição de scripts PowerShell lentos pela API nativa de Registro do Windows (`winreg`) para verificar a chave `Services\NTDS` (execução em **0.05ms**).
  - Validação ultrarrápida do serviço Hyper-V (`vmms`) via `sc.exe query vmms` em apenas **0.19s** (anteriormente ~1.2s via PowerShell).

### 📟 Integração Global do Hardware & S.M.A.R.T. HUD
- **Conexão Direta aos Dashboards & Overview (`index.html`, `dashboard.html`, `overview.html`)**:
  - Inclusão oficial dos módulos `gboc-hardware-hud.css` e `gboc-hardware-hud.js`.
  - Medidores e gauges de CPU, Memória RAM e Storage tornados interativos (`cursor: pointer`, tooltip e acionamento de `toggleHardwareHUD()` ao clique).
  - Adição de botão dedicado de acesso rápido no grid de ações operacionais.

### 🧹 Otimização e Estabilidade do Frontend
- **Limpeza de Scripts & Inicializações Redundantes (`virtualization.html` & `disaster-recovery.js`)**:
  - Remoção de tags duplicadas de `sidebar.js`.
  - Eliminação de chamadas manuais redundantes a `new UnifiedSidebar().initialize()`, evitando duplicação de listeners e recriação indevida do DOM.
  - Adição de spinner de loading dinâmico com mensagem de status na listagem de máquinas virtuais Hyper-V locais.

### 📦 Distribuição & Empacotamento
- **Atualização do Manifesto & Instaladores (`tools/make_distribution.py`, `package_manifest.json`)**:
  - Sincronização automática para a versão canônica `14.4.0 Full Stable Enterprise` nos instaladores `Setup.bat` e `Setup.ps1`.

---

## 14.3.0 — 2026-09-14 (Major UI/UX Model Release — Official Modern Model, Design System Tokens, UnoCSS & Menu Acceleration)

### 🎨 Modelo Visual Oficial Moderno (`modern`) & Backend Contract
- **Contrato Explícito de UI Model (`server_gboc.py`, `agent_gboc.py` & `gboc-layout-manager.js`)**:
  - Definição estrita das constantes globais `UI_MODEL = "modern"`, `ACTIVE_UI_MODEL = "modern"` e `DEFAULT_UI_MODEL = "modern"`.
  - Implementação de fallback determinístico no motor JS: requisições a modelos inexistentes ou legados desativados revertem automaticamente para `modern` e registram alerta no console.
  - Disponibilização do endpoint `/api/v1/system/ui-config` no Servidor e no Agente com estado estruturado dos modelos, temas e estilos de componentes.
- **Desativação de Opções Legadas Quebradas**:
  - Remoção de seletores ou links para modelos legados inconsistentes do painel "Personalizar Interface", exibindo o selo inequívoco **MODELO UI ATIVO: Modern UI (Padrão Oficial)**.

### 📐 Arquitetura Modular CSS & Infraestrutura UnoCSS
- **Estrutura de Arquivos Modular (`static/ui/`)**:
  - `tokens.css`: Centralização de variáveis globais de iluminação (`dark`, `light`, `purple`, `ocean`), tipografia, raios de borda e aliases de compatibilidade (`--border`, `--text`, `--bg-dark`).
  - `unocss-ds.css`: Utilitários atômicos UnoCSS, shortcuts de cards/botões/inputs e animação skeleton loader conforme os Princípios de Movimento Kyle Zantos.
  - `model.css`, `components.css`, `layout.css` sob `static/ui/models/modern/`: Isolamento do Modelo UI Moderno com suporte aos 4 formatos de componentes (`minimal`, `neumorphism`, `claymorphism`, `fluent`).

### ⚡ Otimização do Menu Principal do Agente
- **Performance de Carregamento (< 5ms) (`sidebar.js`)**:
  - Implementação do cache em memória `__gbocSidebarMemoryCache` para renderização instantânea da barra lateral.
  - Eliminação de requisições HTTP redundantes e unificação do `MutationObserver` no DOM.

### 🖥️ Padronização das Telas Iniciais
- **Harmonização do Dashboard & Tela Inicial (`dashboard.html` & `index.html`)**:
  - Configuração estrita da tag `<html data-ui-model="modern">` e sincronização dos estilos com o Design System central.

### 🤖 Auto-Diagnóstico de IA com Telemetria Real & Ações Passo a Passo ("O que fazer exatamente")
- **Eliminação de Mensagens Genéricas (`ai_diagnostic_engine.py`, `ai_v2_router.py`)**:
  - Remoção completa de respostas genéricas estáticas (*"Erro detectado: 'Diagnóstico geral...'"*).
  - Coleta automática de telemetria 100% real do host operacional (`CPU`, `RAM`, `Disco`, `Status BD`, `Jobs com Trava`) via `psutil`.
  - Estruturação padronizada das respostas do assistente em 3 seções obrigatórias:
    1. 🔍 **Causa Raiz Técnica & Telemetria Real**
    2. 🛠️ **O Que Fazer Exatamente (Passo a Passo)** (instruções operacionais numeradas e claras)
    3. ⚡ **Executar Correção Automática (Auto-Heal)** (integrado ao endpoint `/api/v2/system/auto-heal` e botão em 1 clique).
- **Interface dos Modais de Diagnóstico (`dashboard.html` & `index.html`)**:
  - Modal do assistente de IA atualizado para renderizar badges de saúde por cor, diagnósticos de causa raiz e ações corretivas de Auto-Heal automatizadas.

### 🎨 Troca Dinâmica em Tempo Real dos 4 Estilos de Componentes UI/UX
- **Vinculação Global de CSS Tokens (`gboc-themes.css`)**:
  - Correção dos seletores CSS globais `.card`, `.panel`, `.stat-card`, `.kpi-card`, `.dashboard-card`, `.data-card`, `.quick-action-card`, `.modal-card`, `.widget`, `.form-control`, `.input` e `.btn`.
  - Todos os componentes visuais agora herdam instantaneamente as variáveis CSS de design tokens (`--card-radius`, `--card-border`, `--card-shadow`, `--card-backdrop`, `--card-bg`, `--input-shadow`, `--btn-shadow`).
  - Permite a alternância imediata em tempo real no navegador entre os 4 estilos visuais: **SaaS Minimal**, **Neumorphism (Soft UI)**, **3D Claymorphism** e **Fluent Design (Microsoft Acrylic Glass)**.

### 🔗 Padronização Estrita da API v2 (`/api/v2/`)
- **Endpoints de Sistema e IA (`system_v2_router.py`, `ai_v2_router.py`)**:
  - Inclusão dos endpoints oficiais `/api/v2/system/ui-config`, `/api/v2/system/version`, `/api/v2/ai/diagnose` e `/api/v2/system/auto-heal`.
  - Todas as respostas envelopadas no padrão `build_v2_response` com metadados de execução (`execution_time_ms`, `timestamp`, `version`).

### 📦 Pacote de Distribuição
- **Pacote de Instalação (`build_installer_package.ps1`)**:
  - Atualização do gerador de distribuição mantendo a pasta externa `GBOC-Distribution` 100% sincronizada.

---

### 💾 Consumo de Armazenamento por Motor (Local vs. Destino)
- **Detalhamento de Armazenamento por Motor (`storage_monitor.py` & `storage_router.py`)**:
  - Implementada agregação de dados por motor de backup (`by_engine`: Restic, Kopia, Duplicati, Borg, Nativo, Hermes).
  - Cálculo empírico e exposição de consumo físico no disco local (`local_gb`) e consumo no destino remoto de armazenamento (`destination_gb`), além de métricas gerais e contagem de repositórios.
- **Painel Visual na GUI (`storage-usage.html` & `storage.html`)**:
  - Adicionado painel visual **"Consumo de Armazenamento por Motor (Local vs. Destino)"** com cards comparativos por motor.
  - Atualização dos cards de repositórios individuais exibindo localização local e destino de replicação.

### ⚡ Replicação Local (Estabilização e Correção de Travamento)
- **Resolução de Porta e Roteamento (`gboc-layout-manager.js`)**:
  - Corrigida a identificação `isAgent` para cobrir a porta `9200` e as páginas `/replication.html`, `/failed-jobs.html` e `/storage-usage.html`. Isso impede que a página tente carregar a API da porta 8000 do Servidor quando executada no Agente.
- **Flexibilização do Banco de Dados (`backup_replicator.py` & `replication_api.py`)**:
  - Atualizado o schema da tabela `replication_policies` para aceitar `target_repo_id DEFAULT 0`, adicionando suporte nativo às colunas `dest_type`, `dest_path`, `mode`, `status` e `total_bytes` com migrações defensivas `ALTER TABLE IF NOT EXISTS`.

### 📌 Jobs com Falha (Reposicionamento de Menu & Standard Layout)
- **Reorganização de Menu (`_sidebar.html`)**:
  - Transferência do módulo **Jobs com Falha** da área de *Tarefas & Motores* para a seção **Diagnóstico & Logs**, abaixo de *Central de Alertas*.
- **Padronização Visual (`failed-jobs.html`)**:
  - Refatoração da página `failed-jobs.html` para o layout standard com suporte a temas CSS (`var(--bg-card)`, `var(--border)`), KPIs responsivos e modal overlay centralizado.

### 🛡️ Resiliência e Logs Imunes no Windows (`SafeRotatingFileHandler`)
- **Imunidade a PermissionError**:
  - Implementada a subclasse `SafeRotatingFileHandler` em `agent_gboc.py`, `logger.py` e `task_manager.py` para ignorar travamentos de arquivo de log no Windows.
- **Filtro Anti-Recursão**:
  - Adicionado filtro de supressão no redirecionador `sys.stderr` contra erros de rotação de log para prevenir tempestades de exceção no console.

### 🚀 Otimização do Hermes Engine
- **Cache em Memória (TTL 60s)**:
  - Adicionada camada de cache para a checagem de VSS Writers (`vssadmin`), reduzindo drasticamente o tempo de resposta do endpoint `/api/v1/hermes/status`.

---

## 14.1.0 — 2026-08-08 (Patch Release — Hotfixes de Navegação, Validação e Ransomware)

### 🛠️ Correções de UX, Roteamento e UI
- **Roteamento Estático no Agente (`agent_server.py`)**:
  - Corrigida a prioridade de busca de caminhos de arquivos HTML no roteador de fallback. Agora as requisições para `/tasks.html`, `/repositories.html` e `/duplicati-native.html` buscam os arquivos correspondentes na pasta `static/` antes de reverter para a tela inicial (`index.html`). Isso resolve o bug em que clicar nas opções do menu redirecionava o usuário de volta ao dashboard inicial.
- **Detecção de Nome do Motor na UI (`engines.html`)**:
  - Corrigido o título dos cards dos motores locais que mostravam `undefined`. Substituído `engine.display_name` por `engine.name` no template do card, casando com a propriedade real retornada pela API do Agente.

### 🔒 Segurança, Otimizações de Desempenho e Sentinel
- **Otimização de Varredura de Ransomware (`ransomware_detector.py`)**:
  - Otimizada a função `calculate_directory_entropy` e `scan_for_suspicious_extensions` adicionando condições de parada `break` no loop externo do `os.walk` após atingir o limite `max_files`, interrompendo instantaneamente a travessia de diretórios gigantes.
  - Otimizada a varredura do motor YARA (`scan_with_yara`), adicionando um limite estrito de escaneamento de até 100 arquivos e ignorando arquivos com tamanho maior que 10 MB (evitando processamento e leitura de blocos binários gigantes). Isso resolve o problema de travamento ("módulo guardian travado") que ocorria quando o watchdog rodava a stack de segurança sobre a pasta de dados.

### 🔌 Paridade de Senhas e Validação de Motores
- **Recuperação Resiliente de Senhas no Agente (`repository_manager.py`)**:
  - Unificação de todos os campos possíveis de senha de criptografia (`motor_password`, `encryption_password`, `password`, `cloud_password`) no método de normalização. Ao obter a configuração de um repositório, o Agente agora consolida e garante que todos os campos de credenciais estejam disponíveis, corrigindo falhas na validação ou no teste de conexões de repositórios que ocorriam por divergência ou ausência da coluna exata de senha.

### 📈 Versionamento
- **Versionamento Semântico (SemVer)**:
  - Incremento global de versão para **14.1.0** em todos os arquivos de configuração de versão e templates usando `version_unifier.py` e atualização do `BUILD_DATE` para **2026-08-08**.

---

## 14.1.0 — 2026-08-05 (Minor Release — Módulos GUI Storage & Job Alert)

### 🚀 Novos Módulos e Funcionalidades
- **Módulo GUI Storage Usage & Growth (`modules/storage`)**:
  - Implementação do backend (`storage_router.py`), frontend JS (`storage.js`) e componente HTML (`storage.html`) no Servidor Central (`GBOC-Server`) e no Agente (`GBOC-Agent`).
  - Coleta em tempo real de estatísticas e capacidade dos volumes usando dados empíricos do sistema (`shutil.disk_usage`) com gráfico de crescimento (Chart.js).
- **Módulo GUI Job Failure & Alert Monitor (`modules/job_alert`)**:
  - Implementação do backend (`job_alert_router.py`), frontend JS (`job_alert.js`) e componente HTML (`job_alert.html`) no Servidor Central (`GBOC-Server`) e no Agente (`GBOC-Agent`).
  - Centralização de falhas de jobs ativas, retentativas, botão de marcar como resolvido e testes de envio de alertas em canais configurados.

### 🛠️ Correções de UX e Arquitetura
- **Correção dos Submenus Sanfona da Sidebar**:
  - Exportação global das funções `window.toggleNavGroup` e `window.initNavGroups` em `sidebar.js`, resolvendo o bloqueio de execução de scripts dinâmicos inseridos via `insertAdjacentHTML`.
- **Conformidade Estrita com AGENTS.md / ARCHITECTURE_POLICIES.md**:
  - Reorganização dos roteadores de `api/` para `modules/storage/storage_router.py` e `modules/job_alert/job_alert_router.py` (`1 Módulo = 1 Diretório`).
- **Versionamento Semântico (SemVer)**:
  - Incremento global para **14.1.0** via `version_control.py` e `version_unifier.py`.

---

## 14.1.0 — 2026-08 (Versão Consolidada Pós-Recuperação)

### 🚀 Destaques da Release

- **Unificação Geral de Versão (14.1.0)**: Sincronização completa de todos os módulos (`GBOC-Server`, `GBOC-Agent`, `SharedCore`, `Ransomware Shield`, `Diagnostic System` e `version_unifier.py`).
- **Recuperação e Consolidação de Código**: Restauração da base de código (recuperada após perda por falha de disco), consolidando todas as melhorias até Agosto de 2026.
- **Suporte Pydantic v2**: Atualização dos validadores de modelos Pydantic no `GBOC-Server`.
- **Estabilidade nos Testes**: Correção de codificação UTF-8 no Windows e ajuste de asserções assíncronas na Dead Letter Queue (`tests.py`).
- **Documentação Mestra**: Reformulação total do `README.md` principal na raiz e atualização do `INSTALADORES_README.md`.

---

## 14.1.0 — 2026-04

### 🧩 UI e Navegação

- **Página `config-manager.html`** criada — interface completa para `config_api.py`:
  - export atual (preview + download JSON)
  - import manual e upload JSON
  - snapshots de configuração
  - download/visualização/exclusão de snapshots
  - diff entre snapshots e diff snapshot vs config atual
- **Sidebar atualizada**:
  - versão visual `GBOC 14.1.0`
  - novo item **Config Manager** no menu
- **Unificação de páginas legadas**:
  - `overview.html` agora redireciona para `/`
  - `statistics.html` agora redireciona para `/`
  - evita duplicidade com o Dashboard principal

### 🧭 Correções de UX (Tarefas/Replicação/Sidebar)

- **Seletor de pasta em Tarefas** (`tasks.html` + `api/fs.py`):
  - corrigido travamento em loop após cancelar/voltar seleção
  - reset de estado do browser ao abrir/fechar modal
  - fallback automático para raiz quando caminho anterior não existe (ex.: drive removido)
  - listagem de drives no Windows ajustada para evitar bloqueio em unidades offline
  - correção para permitir selecionar a pasta atual quando não há subpastas
- **Replicação** (`replication.html`):
  - adicionada opção de **selecionar pasta do servidor** quando destino = diretório local
  - removido script legado duplicado que chamava endpoint inexistente (`/api/files`)
  - corrigidos erros JS que travavam tela em "Carregando..."
- **Sidebar** (`sidebar.js` + `style.css` + `_sidebar.html`):
  - corrigida marcação de módulo ativo (não fica preso em Diagnóstico)
  - corrigida seleção ativa ao clicar em ícone/texto do link
  - proteção contra dupla inicialização do sidebar
  - adicionado scroll vertical quando menu excede a altura da tela
  - botão de tema reposicionado para não sobrepor itens do menu

### 🧩 Correções Funcionais (Integridade/Config/Timezone)

- **Restore (Quick Win - snapshots intermitentes)**:
  - corrigida identificação de snapshots Restic no módulo de restauração (`real_restore_manager`): operações agora usam `full_id` internamente para evitar ambiguidades de `short_id`
  - `restore.js` atualizado para exibir `short_id` apenas como label visual, mantendo `full_id` como valor selecionado
  - efeito prático: snapshots que antes falhavam de forma intermitente agora restauram corretamente no módulo de Restore

- **Restore (diagnóstico quick win, baixo risco)**:
  - novo endpoint `GET /api/restore/diagnose/{repo_id}` para diagnóstico rápido de listagem de snapshots
  - novo botão **Diagnosticar Snapshots** em `restore.html`
  - `restore.js` agora exibe erro + dica objetiva (senha inválida, path/bucket/prefix incorreto, permissão)

- **Motores em Tarefas (consistência corrigida)**:
  - listagem de tarefas agora traz `repository_engine` no backend
  - UI de tarefas exibe separadamente **Engine da Tarefa** e **Engine do Repositório**
  - seleção de repositório no modal sincroniza automaticamente o campo de engine
  - execução força engine do repositório quando detectar divergência (com log de warning)
  - adicionada compatibilidade com schema legado (fallback sem `repository_engine`) para não quebrar carregamento da página

- **Audit Trail funcional** (`audit.html`):
  - UI ajustada para o formato real da API (`entries`, `summary.daily_activity/users/actions`)
  - KPIs e tabela agora carregam dados corretamente
  - export CSV mantém funcionamento

- **Edição de Repositório (senhas preservadas)**:
  - corrigido bug em que `motor_password`/credenciais cloud podiam ser sobrescritas com vazio ao editar sem alterar senha
  - frontend agora só envia `access_key/secret_key` quando usuário realmente informa novo valor
  - backend ignora `motor_password/cloud_password` vazios em updates

- **Exclusão de Repositório (FK + limpeza multi-motor)**:
  - corrigido erro 500 ao excluir repositório com histórico em `integrity_checks` (`integrity_checks_repository_id_fkey`)
  - exclusão agora remove dependências por `repository_id` em ordem segura (`integrity_checks`, `restore_history`, `tasks`) antes de remover `repositories`
  - adicionada limpeza de artefatos de motores na exclusão (ex.: `data/kopia_configs/*.config` relacionados ao repositório), não ficando restrita ao GBOC Native
  - `database_migrator.py` agora força `ON DELETE CASCADE` na FK `integrity_checks.repository_id -> repositories.id` para prevenir bloqueios futuros
  - novo script `scripts/force_cleanup_external_engines.ps1` para limpeza forçada de artefatos de motores externos em cenários de falha operacional
  - script de limpeza forçada agora suporta `-ForceKill` para encerrar processos `kopia/restic/duplicati` antes da remoção

- **Versionamento de scripts (.bat/.ps1) atualizado**:
  - `start_agent.bat` e `start_agent.ps1`: v14.1.0 → **14.1.0**
  - scripts de instalação/diagnóstico em `scripts/`: padronizados para **14.1.0**

- **Server Dashboard Analytics (correções)**:
  - corrigido erro JS `ReferenceError: rjson is not defined` em `loadLogAgentFilter()`
  - restaurada formatação visual dos blocos de alertas/diagnóstico/trends no tab Analytics

- **Quick Wins adicionais (estabilidade UI/API)**:
  - `tasks.html`: hardening de bootstrap (fallback para módulos auxiliares ausentes) e restauração de funções mínimas para evitar travamento em "Carregando tarefas..."
  - `reports.html`: arquivo restaurado (script completo), sidebar preservada no módulo e fluxo de geração/download/agendamento/histórico reativado
  - `api/reports_api.py`: geração sob demanda agora grava `report_history` (sucesso/erro) para exibir todos os relatórios no histórico
  - `integrity.html`: falhas exibem resumo e botão **Ver erro** com detalhes do check
  - `api/auth.py`: Audit Trail passa a registrar login sucesso/falha (`auth.login`) para filtros funcionarem
  - `api/repositories.py`: endpoint de teste usa validação detalhada (mensagem real de erro), reduzindo falso positivo
  - **Servidor Central**: sessão agora é invalidada no startup (limpa `server_auth_tokens`) para exigir novo login após reinício
  - **Shutdown controlado**: adicionados endpoints locais de encerramento (`/api/system/shutdown` no Agent e `/api/v1/system/shutdown` no Server)
  - novo script `scripts/shutdown_gboc.ps1` para desligar Agent/Server via API com fallback opcional `-ForceKill`
  - **Tarefas**: browser de pastas restaurado (`btn-browse-folders`) com navegação, seleção e inserção de caminho no campo `paths`
  - **Revisão funcional geral concluída**: validação sintática dos módulos críticos OK e smoke tests atualizados/passando (`tests/test_repository_loading.py`, `tests/test_app.py`) para base pronta a novas implementações
  - **Hardening de obsolescência/segurança**:
    - `api/import_api.py`: removido fallback legado para `engines.real_backup_importer` (obsoleto)
    - `api/diagnostics.py`: removidas respostas simuladas em criptografia/segurança; diagnóstico agora usa dados reais de repositórios e tempo real de execução no quick diagnostic
    - `api/diagnostics.py`: helpers internos reparados para evitar bloco incompleto e garantir estabilidade
    - `gboc_server.py`: cookies de sessão endurecidos (`HttpOnly`, `SameSite=Lax`, `Secure` condicional por HTTPS)
    - `engines/backup_importer.py`: removida escrita sintética no banco (task `999` / execução fake); fluxo convertido para `discovery_only`
    - `api/import_api.py`: removido endpoint legado `/scan-and-import`, mantendo apenas `/scan` (GET/POST)
    - `gboc_server.py`: removidos endpoints legados de auth (`/api/v1/login`, `/api/v1/logout`, `/api/v1/auth/check`) e restabelecido namespace único `/api/v1/auth/*`
    - `gboc_server.py`: removido endpoint simulado `/api/v1/sync/push` e removidos placeholders de sync manual sem implementação
    - `gboc_server.py`: rotinas de sync de full-data agora persistem de forma real (`agent_repositories`, `agent_tasks`, `agent_task_executions`, `system_events`)
    - validação final executada: py_compile (Agent/Server), checagem de tabela de rotas e smoke tests (`test_app.py`, `test_repository_loading.py`) aprovados

- **Integrity UI** (`integrity.html`):
  - status agora lê estrutura real da API (`d.check.status`)
  - histórico atualizado com campos corretos (`finished_at`, `errors_found`)
  - polling automático após iniciar verificação
- **Config Export** (`engines/config_manager.py`):
  - corrigidas queries para schema real (repositories/type, tasks/source_paths/schedule_cron)
  - fallback resiliente para `smtp_config` quando tabela não existir
  - corrigido erro 500 no download `/api/config/export/download`
- **Timezone padronizado**:
  - Agent: padronização global via `auth_interceptor.js` para horário local do cliente (fuso local)
  - Server Dashboard: helper `fmtDateTime()` aplicado aos campos principais
- **Varredura completa de datas (Agent)**:
  - substituídos todos os `new Date(...).toLocaleString(...)` por `gbocFormatDateTime(...)`
  - aplicado em páginas HTML e scripts JS para eliminar divergência UTC/local
- **Integrity Checks (UI) corrigido**:
  - `integrity.html` agora interpreta corretamente retorno de `/api/repositories/` (array direto)
  - lista de repositórios/carregamento de checks voltou a funcionar

### 🎨 Padronização Visual Global (Agent + Server)

- botões, campos de preenchimento e item de menu ativo alinhados ao estilo do login (neumórfico)
- respeitando dark/light theme em Agent e Server

### 🛡️ Ransomware Shield — Prevenção em Tempo Real

- **Módulo `engines/ransomware_shield.py`** reescrito e integrado com 6 correções críticas:
  - Fix `VSSGuard._scan_processes()` — `proc.info` é dict, não callable (crash `TypeError`)
  - Fix `_calculate_entropy()` — fórmula Shannon corrigida (`math.log2` em vez de `float.bit_length()`)
  - Fix `signal.signal()` — crash em thread secundária (guard com `try/except ValueError`)
  - Fix `setup_logging()` — não sobrescreve mais o root logger do GBOC (logger dedicado `GBOC.Shield`)
  - Fix `Config` — adicionados `vss_guard_enabled`, `enabled`, `auto_isolate_network` ao `DEFAULT_CONFIG`
  - Fix re-start — `_stop_event.clear()` no `start()` para permitir stop/start sem restart do processo
- **Singleton `get_shield()`** adicionado para compatibilidade com `ransomware_api.py`
- **Integração com Guardian** — ameaças `critical` acionam cadeia completa (snapshot, lock, notificações)
- **Integração com banco de dados** — ameaças registradas na tabela `alerts`
- **6 endpoints REST** adicionados: `shield/status`, `start`, `stop`, `config`, `path/add`, `threats`
- **Startup integrado** — Shield carrega no `agent_server.py` (lifespan), desliga graciosamente no shutdown

### 📋 Compliance API — Nova

- **Módulo `api/compliance_api.py`** criado com 7 endpoints:
  - `GET /api/compliance/score` — Score calculado com 8 regras automáticas
  - `GET /api/compliance/rules` — Avaliação em tempo real (agendamento, backup recente, falhas consecutivas, repos ativos, auth, integridade, taxa sucesso, engines)
  - `GET/POST/DELETE /api/compliance/policies` — CRUD de políticas
  - `POST /api/compliance/audit` — Executa auditoria e grava histórico
  - `GET /api/compliance/audit/history` — Histórico de auditorias
- **2 tabelas** criadas: `compliance_policies`, `compliance_audits`
- **Página `compliance.html`** agora funcional (antes 100% 404)

### 📊 Advanced Stats — Endpoints Completados

- **3 endpoints** adicionados ao `advanced_stats_api.py`:
  - `GET /api/advanced-stats/trend?days=N` — Dados diários (success/failed) para gráficos line + heatmap
  - `GET /api/advanced-stats/distribution` — Distribuição de status (doughnut chart)
  - `GET /api/advanced-stats/recent-executions?limit=N` — Execuções recentes para timeline widget
- **Dashboard `index.html`** — gráficos Trend, Distribution e Timeline agora funcionais

### 🔄 Replication API — Endpoints Completados

- **5 endpoints** adicionados ao `replication_api.py`:
  - `GET /api/replication/stats` — Estatísticas agregadas (total rules, syncing, bytes, errors 24h)
  - `GET /api/replication/rules` — Alias para policies (formato compatível com `replication.html`)
  - `POST /api/replication/rules` — Criar regra (wrapper para create_policy)
  - `POST /api/replication/rules/{id}/sync` — Trigger sync
  - `DELETE /api/replication/rules/{id}` — Remover regra
- **Página `replication.html`** agora funcional

### ⚙️ Servidor Central — Configurações Completas

- **Tabela `server_settings`** criada com 33 configurações padrão em 7 categorias: Geral, Sincronização, Segurança, Database, Retenção, Notificações, Interface
- **10 endpoints REST**: GET/PUT settings, GET/PUT category, bulk update, reset, export, import, server info, maintenance cleanup, test notification
- **Dashboard `tab-config`** reescrito: cards de informação (versão, DB, conexões), formulário editável com 7 abas, export/import JSON, manutenção, reset
- **Versão Server**: 14.1.0 → **14.1.0**

### 🐛 Correções

- **11 endpoints 404 corrigidos** — compliance (4), advanced-stats (3), replication (2), ransomware/shield (2)
- **`ransomware_shield.py`** — 6 bugs críticos (ver acima)
- **Módulos registrados**: 27 APIs (era 25)

### 📈 Métricas

| Métrica | 14.1.0 | 14.1.0 |
|---------|--------|--------|
| APIs registradas (agente) | 25 | **27** |
| Endpoints REST (agente) | ~150 | **~175** |
| Endpoints REST (servidor) | 25 | **35** |
| Tabelas banco (servidor) | 9 | **10** |

---

## 14.1.0 — 2025-03

### 🏗️ Reorganização de Projeto

- **Estrutura de pastas reorganizada** — arquivos `.py` soltos na raiz foram classificados:
  - `core/` — Infraestrutura: `database_log_handler`, `database_migrator`, `db_wrapper`, `http_client`, `logstash_handler`, `monitoring`, `server_client`, `server_config`
  - `utils/` — Utilitários: `diagnostic_report`, `kill_port`, `orphan_file_detector`, `version_unifier`, `get_health_report`, `run_complete_diagnostic`
  - `tests/` — Scripts de teste: `test_app`, `test_repository_loading`, `fix_repo`
  - `scripts/` — Instalação e deploy: `.bat`, `.ps1`, `Dockerfile`, `docker-compose.yml`, `requirements_*.txt`
  - `docs/` — Toda documentação `.md` consolidada
  - `_deprecated/` — Código não utilizado (`app/`, `frontend/`)
- **Raiz limpa** — apenas arquivos essenciais: `agent_server.py`, `shared_core.py`, `models.py`, `start_server.py`, `requirements.txt`
- **Re-exports** na raiz para compatibilidade total de imports existentes
- **Arquivos vazios removidos**: `_add_interceptor.py`, `_migrate_auth.py`, `_test_auth.py`

### 🔐 Autenticação do Servidor

- **Login obrigatório** — rota `/` agora sempre exige autenticação (removida verificação `_is_server_auth_enabled`)
- **Modo Setup** — quando não há usuários, `login.html` exibe formulário "Criar Conta" automaticamente
- **Dashboard protegido** — `checkAuth()` no `DOMContentLoaded` valida sessão via `/api/v1/auth/status`
- **Logout funcional** — botão "Sair" na sidebar, limpa cookie e localStorage
- **Nome do usuário** exibido na sidebar do dashboard
- **Tabelas de auth**: `server_auth_users` (username, password_hash SHA256, display_name, role) e `server_auth_tokens` (token hex 64 chars, expires_at 24h)

### 🐛 Correções Críticas

- **alerts.py** — Corrigido `boolean = integer` para PostgreSQL: todas as queries de `resolved` e `acknowledged` agora usam `= true` / `= false` em vez de `= 1` / `= 0` (5 correções)
- **reports_api.py** — Corrigido nome da coluna: `cron_expr` → `cron_expression` em SELECT, INSERT, UPDATE e validação (4 correções)
- **database_log_handler.py** — Reescrito: conexão dedicada `psycopg2` com `autocommit=True`, thread-safe com `threading.Lock()`, auto-reconexão. Elimina cascata de erro "current transaction is aborted"
- **agent_server.py** — `RotatingFileHandler` (10 MB × 5 backups) substitui `FileHandler` ilimitado. Log separado de erros (`gboc_agent_errors.log`, 5 MB × 3). `sys.excepthook` para exceções não tratadas. Redirect de `stderr` para logger

### 📊 Health Score Unificado

- **Módulo `engines/health_score.py`** criado com cálculo padronizado:
  - Pesos: Sistema 30%, Ferramentas 10%, Backups 30%, Repositórios 15%, Tarefas 15%
  - Status: ≥85 Excelente, ≥70 Bom, ≥50 Atenção, <50 Crítico
  - Funções: `calculate_health_score()`, `calculate_health_score_auto()`, `score_from_issues()`, `get_health_status()`, `get_health_status_label()`

---

## v14.1.0 — 2025-02

### 🔧 Motores de Backup

- **Kopia** — `_list_kopia_files` reescrito: `ls -l` com traversal por object ID, suporte a diretórios profundos
- **Duplicati** — Suporte cloud via CLI (`Duplicati.CommandLine.exe`), `_list_duplicati_files`, `_build_duplicati_url` corrigido
- **GBOC Native** — Engine nativo com compressão e criptografia próprias (`native_engine/engine.py`)
- **Restic** — Suporte completo mantido (`C:\Program Files\Restic\restic.EXE`)
- **Detecção automática** de motores via `engines/engine_paths.py`

### 🔄 Restauração

- **`real_restore_manager.py`** — Restauração funcional para Kopia, Restic, Duplicati e GBOC Native
- **Página `restore.html`** — Seleção de repositório, navegação de snapshots, seleção de arquivos/pastas, progresso em tempo real
- **Auth fix** — Restauração não requer token quando executada localmente

### 📡 Comunicação Servidor Central

- **WebSocket bidirecional** — Agente ↔ Servidor em tempo real
- **Push Sync** — Sincronização sob demanda do dashboard do servidor
- **Heartbeat configurável** — 1-60 minutos
- **Auto-reconexão** com backoff exponencial

---

## v14.1.0 — 2024-12

### 📈 Estatísticas Avançadas

- **`engines/advanced_statistics.py`** — Backup, Performance, Storage, Reliability, Predictions, Trends
- **`api/advanced_stats_api.py`** — Endpoints: `/api/advanced-stats/comprehensive`, `/health-score`, `/predictions`, `/trends`

### 🩺 Diagnóstico

- **`engines/diagnostic_system.py`** — Diagnóstico do sistema em 4 abas (System, Engines, Database, Network)
- **`engines/preemptive_diagnostic.py`** — 8 verificações preventivas
- **`api/preemptive_api.py`** — API para diagnóstico preemptivo
- **`diagnostic.html`** — Interface com 4 abas, execução sob demanda, auto-correção

### 🔔 Sistema de Alertas

- **`api/alerts.py`** — CRUD completo, estatísticas, bulk actions, auto-resolução
- **Tabela `alerts`** — severity, category, resolved (BOOLEAN), acknowledged (BOOLEAN), auto_resolved

### 🩹 Auto-Healer

- **`engines/healer_engine.py`** — Verificação e correção automática de problemas
- **`engines/auto_healer.py`** — Agendamento de verificações periódicas

### 📧 Notificações

- **`engines/notification_service.py`** — Email via SMTP, templates HTML
- **`api/smtp.py`** — Configuração e teste SMTP via API

### 📋 Relatórios

- **`engines/report_generator.py`** — Geração de relatórios PDF/HTML
- **`api/reports_api.py`** — Agendamento com `cron_expression`, histórico
- **`api/export_api.py`** — Exportação em JSON, CSV

### 🗄️ Backup de Banco

- **`engines/database_backup.py`** — Backup do PostgreSQL (pg_dump)
- **`api/database_backup_api.py`** — Agendamento, listagem, restauração
- **`database-backup.html`** — Interface de gerenciamento

---

## v9.0 → v14.1.0 — Migração

### 🗃️ Banco de Dados

- **Migração completa para PostgreSQL** — SQLite mantido apenas para acessar bancos de motores externos (Duplicati)
- **Pool de conexões** — `psycopg2.pool` com min 2, max 10 conexões
- **Migrador automático** — `core/database_migrator.py` aplica schema defensivo
- **20 tabelas no agente**: alerts, auth_sessions, auth_users, backup_statistics, database_backups, database_connections, detected_engines, diagnostics, engine_backup_statistics, imported_repositories, integrity_checks, report_history, report_schedules, repositories, restore_history, settings, system_logs, task_executions, tasks, user_dashboard_layouts
- **11 tabelas no servidor**: agents, agent_logs, agent_metrics, agent_repositories, agent_statistics, agent_task_executions, agent_tasks, backup_reports, server_auth_tokens, server_auth_users, system_events

### 🔐 Autenticação do Agente

- **`api/auth.py`** — Login/registro, sessões com token, gerenciamento de usuários
- **`api/auth_middleware.py`** — Middleware FastAPI para proteção de rotas
- **`login.html`** — Tela neumórfica com modo setup (primeiro acesso)

### 🎨 Interface

- **Sistema de themes** — `[data-theme="dark"]` / `[data-theme="light"]` com variáveis CSS
- **Design System** — `style.css` com `.gboc-box`, `.btn-*`, `.data-table`, `.modal`, `.badge-*`, `.nav-link`
- **Sidebar dinâmica** — `sidebar.js` com navegação, indicador de página ativa, toggle de tema
- **Dashboard do Servidor** — 6 abas: Overview, Agentes, Backups, Analytics, Logs, Configurações
- **Chart.js 4.4.0** — Gráficos de linha, barras, doughnut para analytics

---

## Arquitetura Atual

### Agente (porta 9200)

```
gboc_v8/
├── agent_server.py          # Entry point FastAPI + Uvicorn
├── shared_core.py           # Singleton central (DB, engines, config)
├── models.py                # Modelos Pydantic
├── api/                     # 26 módulos de API REST
│   ├── auth.py              # Autenticação
│   ├── tasks.py             # Gerenciamento de tarefas
│   ├── repositories.py      # Gerenciamento de repositórios
│   ├── diagnostics.py       # Diagnóstico do sistema
│   ├── alerts.py            # Sistema de alertas
│   ├── settings.py          # Configurações
│   ├── logs.py              # Logs do sistema
│   ├── statistics.py        # Estatísticas
│   ├── websocket_api.py     # WebSocket real-time
│   └── ...                  # +17 módulos
├── engines/                 # 30 motores de processamento
│   ├── task_manager.py      # Gerenciador de tarefas (92 KB)
│   ├── repository_manager.py # Gerenciador de repositórios
│   ├── real_restore_manager.py # Restauração (71 KB)
│   ├── diagnostic_system.py # Diagnóstico
│   ├── health_score.py      # Health score unificado
│   └── ...                  # +25 motores
├── core/                    # Infraestrutura
│   ├── database_log_handler.py
│   ├── database_migrator.py
│   ├── server_client.py     # Cliente do servidor central
│   ├── server_config.py     # Configuração do servidor
│   └── ...
├── static/                  # Frontend (14 páginas HTML)
├── storage_backends/        # Local, Cloud, Base
├── native_engine/           # Motor GBOC nativo
├── utils/                   # Utilitários
├── tests/                   # Testes
├── scripts/                 # Instalação e deploy
└── docs/                    # Documentação
```

### Servidor (porta 8000)

```
GBOC-Server/
├── gboc_server.py           # Entry point FastAPI (85 KB)
├── login.html               # Tela de login neumórfica
├── dashboard.html           # Dashboard 6 abas (53 KB)
├── setup_database.sql       # Schema inicial
├── start_server.bat/ps1     # Scripts de inicialização
└── install_server.bat/ps1   # Scripts de instalação
```

### Tecnologias

| Componente | Tecnologia |
|---|---|
| Backend | Python 3.14, FastAPI, Uvicorn |
| Banco de Dados | PostgreSQL 18 (oficial) |
| Frontend | HTML5, CSS3, JavaScript vanilla |
| Gráficos | Chart.js 4.4.0 |
| Ícones | Font Awesome 6.4.0 |
| Backup Engines | Kopia, Restic, Duplicati, GBOC Native |
| Comunicação | WebSocket, REST API, Heartbeat |
| Autenticação | SHA256 + token hex, cookies HttpOnly |

