# Proteção de dados no Git (GBOC)

## O que fica fora do Git
| Categoria | Exemplos |
|---|---|
| Credenciais | `acessos.txt`, `.env*` (exceto `.env.example`), `*token*.txt`, `*secret*.txt`, `*.pem`, `*.key`, `*.pfx` |
| Bancos locais | `*.db`, `*.sqlite`, `*-wal`, `*-shm` |
| Dados de runtime | `GBOC-Agent/data/`, `GBOC-Server/data/` (config do Servidor Central, caches do Kopia/restic, exports do Duplicati) |
| Logs | `GBOC-*/logs/`, `*.log`, `*.log.N` |

Esses arquivos continuam **no disco**; o Git apenas não os rastreia.

## Três camadas de proteção
1. **`.gitignore`** — o Git nem oferece esses arquivos para commit.
2. **Hooks versionados (`.githooks/`)**
   - `pre-commit`: recusa commit com arquivo protegido ou conteúdo com cara de segredo (chaves AWS/Wasabi, B2, chaves privadas, `ID:`/`Senha:` longas).
   - `pre-push`: reexamina os commits enviados (pega quem usou `--no-verify`) e **bloqueia push forçado e exclusão de branch remota**, que apagariam histórico no GitHub. Para uma reescrita intencional: `set GBOC_ALLOW_FORCE=1`.
   - Ative em cada clone: `powershell -ExecutionPolicy Bypass -File tools\instalar_protecao_git.ps1`
3. **CI (`.github/workflows/ci.yml`)** — repete a verificação no GitHub e roda o Gitleaks.

Falso positivo de segredo: inclua `gboc-allow-secret` na linha.

## Como evitar que o Git APAGUE seus dados
- **Nunca use `git clean -x` / `-X`** — é o único comando comum que apaga arquivos ignorados. `git clean -fd` (sem `x`) os preserva.
- **Outra máquina com clone antigo:** os bancos e o `data/` saíram do rastreamento neste commit. Ao dar `git pull` num clone que ainda os tinha rastreados, o Git **remove** essas cópias. Antes do pull nessa máquina, copie `GBOC-Agent\data`, `GBOC-Server\data` e `acessos.txt` para fora da pasta e devolva depois.
- `git reset --hard` / `git checkout .` não tocam em arquivos ignorados.
- Faça backup de `data/` com o próprio GBOC — o Git não é backup de dados de runtime.

## No GitHub (configuração manual, 2 minutos)
- *Settings → Code security*: ativar **Secret scanning** e **Push protection**.
- *Settings → Branches → Add rule* para `main`: marcar **Do not allow force pushes** e **Do not allow deletions**.
- Manter o repositório **privado**.

## Chaves que já estiveram no histórico
O `acessos.txt` (Wasabi e Backblaze B2) foi commitado no passado. Tirar do rastreamento **não** o remove do histórico:
1. Revogue as chaves no Wasabi e no B2 e gere novas (passo obrigatório).
2. Opcional: limpar o histórico com `git filter-repo --path acessos.txt --invert-paths` e `git push --force` (exige `GBOC_ALLOW_FORCE=1`; todos os clones precisam ser refeitos).
