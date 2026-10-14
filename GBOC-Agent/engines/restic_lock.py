"""
Execução de comandos restic com tratamento de trava abandonada (stale lock).

Quando um processo restic morre no meio (queda de energia, Agente encerrado), a trava dele fica no
repositório e todo forget/prune/check seguinte falha com "repository is already locked". O comando
`restic unlock` (sem --remove-all) remove SOMENTE travas abandonadas: de processo que não existe mais
neste computador ou sem atualização há mais de 30 min. A trava de um backup em andamento é atualizada
a cada 5 min e nunca é removida.
"""
import logging
import subprocess
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

LOCKED_MARKER = "repository is already locked"
UNLOCK_TIMEOUT_S = 300


def is_locked_error(output: str) -> bool:
    return LOCKED_MARKER in (output or "").lower()


def unlock_stale(restic: str, env: Dict[str, str], repo_args: Optional[List[str]] = None) -> bool:
    """Remove travas abandonadas. True se o comando terminou com sucesso."""
    r = subprocess.run([restic, "unlock", *(repo_args or [])], env=env, capture_output=True, text=True,
                       timeout=UNLOCK_TIMEOUT_S)
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode == 0:
        logger.info(f"[RESTIC] trava abandonada removida (restic unlock): {out[:200] or 'ok'}")
        return True
    logger.warning(f"[RESTIC] restic unlock falhou: {out[:300]}")
    return False


def run_with_stale_unlock(cmd: List[str], env: Dict[str, str], timeout: int,
                          repo_args: Optional[List[str]] = None) -> subprocess.CompletedProcess:
    """Executa o comando; se falhar por trava, remove travas abandonadas e tenta UMA vez de novo."""
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 and is_locked_error((r.stdout or "") + (r.stderr or "")):
        if unlock_stale(cmd[0], env, repo_args):
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    return r
