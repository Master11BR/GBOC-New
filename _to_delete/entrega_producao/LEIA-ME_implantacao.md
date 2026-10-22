# GBOC - Roteiro de implantação em produção (cliente)

Pacote: GBOC_pacote_producao_20261022_0354.zip (código-fonte do Agente, do Server e de tools).
Cada arquivo tem SHA-256 no MANIFEST_SHA256.txt (dentro do zip), para conferir a cópia.

## O que este pacote NÃO contém (e NÃO deve sobrescrever)
- config\global_settings.json (contém a chave mestra de criptografia desta instalação de origem; cada instalação deve manter a sua)
- logs de inicialização (startup_*.log)
- data\ (banco local em arquivo, duplicati_native_config.json, network_governor_state.json, heartbeat.json, histórico de backups)
- logs\
- .repo_secrets.key  ** chave que descriptografa as credenciais de nuvem dos repositórios. Se perder, as credenciais são perdidas. **
- gboc_tls_key.pem / gboc_tls_cert.pem (certificados do próprio cliente)
- .env e qualquer configuração específica do cliente
- ambiente virtual (.venv)

## Alterações incluídas
1. Proteção contra vazamento de segredos nos logs (core\log_redact.py): chaves de S3 passadas ao kopia/restic são trocadas por *** antes de gravar.
2. Senha do Duplicati gerenciada pelo GBOC: rota só para administradores, auditada (GET /api/duplicati-native/managed-password) e bloco na tela Configurações.
3. Cópia de sombra do Windows (VSS) em todos os motores (restic, Duplicati, Kopia e motor nativo), com configuração em Rede e Carga (vss = auto | off).
4. Controle de rede e carga (engines\network_governor.py) e tela "Rede e Carga".
5. Vigia anti-travamento: core\hang_watchdog.py (Agente e Server) e serviço GBOCWatchdog (scripts\gboc_watchdog.ps1).
6. Dependência faltante corrigida: PyJWT==2.15.1 no requirements do Server (sem ela o Server não importa auth.py).
7. Scripts do instalador (Setup.ps1, gboc_prereqs.ps1, gboc_python.ps1) validados no parser do PowerShell 5.1.

## Antes de começar (obrigatório)
1. Copiar a pasta atual inteira (GBOC-Agent, GBOC-Server, data, config, logs) para um local de backup, por exemplo D:\backup_gboc_AAAAMMDD.
2. Salvar o banco: pg_dump dos bancos gboc_agent e gboc (e o banco do Server, se for separado).
3. Anotar o estado das tarefas: lista de tarefas, status e próxima execução (ou exportar a tabela tasks).
4. Copiar duplicati_native_config.json e .repo_secrets.key para o backup (já estão no item 1, confirme).
5. Avisar os usuários: os serviços vão parar por alguns minutos.

## Implantação
1. Parar os serviços (como administrador):
   sc stop GBOCWatchdog
   sc stop GBOCAgent
   sc stop GBOCServer
   Confirmar com sc query que todos estão STOPPED.
2. Copiar o conteúdo do pacote por cima da instalação atual, SEM copiar data\, logs\, .repo_secrets.key, certificados, .env nem .venv.
3. Conferir a cópia: compare os hashes dos arquivos com o MANIFEST_SHA256.txt (ex.: Get-FileHash).
4. Instalar dependências no ambiente virtual do Agente e do Server:
   <venv>\Scripts\python -m pip install -r requirements.txt
   (no Server, isto instala o PyJWT que faltava)
5. Reinstalar o serviço GBOCWatchdog com o script atualizado (scripts\gboc_prereqs.ps1, função Register-GbocService). Se o instalador oficial (Setup.ps1) for usado, ele já faz isso e para os serviços antes de atualizar.
6. Iniciar os serviços: sc start GBOCAgent, sc start GBOCServer, sc start GBOCWatchdog.
7. Acompanhar os logs na primeira inicialização. Esperado: "Database migration completed successfully" e "[VIGIA] Vigia de travamento ativo". As migrações são aditivas (novas colunas e tabelas, sem apagar dados).

## Verificação (após iniciar)
- Agente responde: GET http://127.0.0.1:9200/api/watchdog/ping  (deve retornar alive: true)
- Server responde: GET http://127.0.0.1:8000/api/watchdog/ping
- Login na interface funciona.
- Tela Rede e Carga mostra o bloco "Arquivos em uso (VSS)" com vss = auto e close_open_share_files = never.
- Tela Configurações > Duplicati: se a senha foi gerada pelo GBOC, aparece o bloco "Senha gerenciada pelo GBOC". Se foi informada manualmente, o bloco não aparece (esperado).
- Rodar uma tarefa de backup de teste (não a de produção, se possível) e confirmar que termina com sucesso e sem erro de VSS.

## Caminho de volta (se algo falhar)
1. sc stop GBOCWatchdog, sc stop GBOCAgent, sc stop GBOCServer.
2. Restaurar a pasta do backup do item "Antes de começar".
3. Restaurar o banco a partir do pg_dump, se alguma migração tiver causado problema (improvável, são migrações aditivas).
4. sc start GBOCAgent, GBOCServer, GBOCWatchdog.

## Pendências de segurança (não corrigidas neste pacote)
- Rotacionar a chave de S3/Wasabi usada na tarefa "Teste-Wasabe": ela ficou gravada em texto puro nos logs antigos (os logs já foram redigidos, mas a chave deve ser considerada exposta).
- Senha do banco de dados escrita no código (core\database_log_handler.py): mover para configuração.
- Senha do Motor registrada em nível DEBUG (api\repositories.py, linha 333): remover.
- Fechar arquivos abertos no compartilhamento: mantido em "never" (o VSS cobre os arquivos abertos).
