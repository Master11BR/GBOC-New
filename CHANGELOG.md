# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Use commits no padrão `feat:`, `fix:`, `sec:`, `perf:`, `docs:` (commitlint já configurado).

## [Não lançado]
### Segurança
- Bancos (`*.db`, `*.sqlite`), `data/`, `logs/`, `acessos.txt`, `.idea/` e `_to_delete/` removidos do rastreamento do Git (arquivos locais preservados).
- Hooks versionados `.githooks/` (pre-commit / pre-push): bloqueiam dados protegidos, segredos, push forçado e exclusão de branch.
- Primeiro acesso (criação do admin) no Agente e no Servidor restrito à máquina local / rede privada (`GBOC_SETUP_ALLOW_ANY=1` libera).
- Agente: se o middleware de autenticação falhar ao carregar, a API passa a responder 503 (antes ficava aberta).
- Servidor: CORS `*` substituído por "mesmo host" + lista `GBOC_SERVER_CORS_ORIGINS`.
- Agente → Servidor: pinning de certificado (`GBOC_SERVER_CERT_SHA256`) ou CA (`GBOC_SERVER_CA_BUNDLE`) opcionais.
- `sql_granular_explorer`: nome de tabela SQLite escapado.
### Desempenho
- Logs do Kopia com rotação (100 arquivos / 7 dias / 50 MB por pasta; antes até 1000+5000 arquivos e 30 dias).
### Qualidade / Documentação
- CI no GitHub Actions (proteção de dados, Gitleaks, ruff, bandit, pip-audit, pytest).
- `docs/README.md` (índice), `docs/PROTECAO_DADOS_GIT.md`, `.env.example`, este CHANGELOG.
