#!/bin/sh
# GBOC - funcoes compartilhadas pelos hooks de protecao (pre-commit / pre-push).
# Bloqueia: arquivos de dados/credenciais e conteudo com cara de segredo.

# Caminhos que NUNCA podem ir para o repositorio
GBOC_BLOCKED_PATHS='(^|/)acessos\.txt$|\.(db|db-wal|db-shm|db-journal|sqlite|sqlite3|sqlite-wal|sqlite-shm|pfx|p12|pem|key|kdbx)$|(^|/)\.env($|\.)|^GBOC-(Agent|Server)/data/|^GBOC-(Agent|Server)/logs/|^(data|logs)/|(^|/)[^/]*(token|secret|credentials)[^/]*\.txt$|\.log(\.[0-9]+)?$'
GBOC_ALLOWED_PATHS='(^|/)\.env\.example$'

# Padroes de segredo no conteudo (chaves AWS/Wasabi, Backblaze B2, chaves privadas, atribuicoes explicitas)
GBOC_SECRET_REGEX='(AKIA|ASIA)[A-Z0-9]{16}|K00[0-9][A-Za-z0-9+/]{27}|-----BEGIN ([A-Z]+ )?PRIVATE KEY-----|(aws_secret_access_key|secret_access_key|application_key|b2_app_key)["'"'"' ]*[:=] *["'"'"'][A-Za-z0-9+/]{20,}|(^|[^A-Za-z])(ID|Senha|Password|Secret) *: *[A-Za-z0-9+/]{20,}$'

gboc_check_paths() {
    # stdin: lista de caminhos
    _bad=$(grep -E "$GBOC_BLOCKED_PATHS" | grep -vE "$GBOC_ALLOWED_PATHS")
    if [ -n "$_bad" ]; then
        echo "" >&2
        echo "[GBOC] BLOQUEADO: arquivos protegidos (dados/credenciais/logs) nao podem ir para o Git:" >&2
        echo "$_bad" | sed 's/^/   - /' >&2
        echo "   Tire do indice com: git rm --cached <arquivo>   (o arquivo local NAO e apagado)" >&2
        return 1
    fi
    return 0
}

gboc_check_content() {
    # stdin: texto (diff); $1: descricao
    _hits=$(grep -E '^\+' | grep -vE '^\+\+\+' | grep -nE "$GBOC_SECRET_REGEX" | head -5)
    if [ -n "$_hits" ]; then
        echo "" >&2
        echo "[GBOC] BLOQUEADO: possivel segredo/credencial em $1:" >&2
        echo "$_hits" | cut -c1-90 | sed 's/^/   /' >&2
        echo "   Mova o segredo para .env / Gerenciador de Credenciais. Se for falso positivo:" >&2
        echo "   adicione 'gboc-allow-secret' na linha." >&2
        return 1
    fi
    return 0
}
