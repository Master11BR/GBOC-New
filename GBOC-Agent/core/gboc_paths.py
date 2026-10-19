"""
GBOC Agent - pastas do sistema (tudo dentro da pasta do Agente).

Antes o Agente criava pastas fora da propria area: C:\\ProgramData\\GBOC (identidade do agente e configuracao
do Servidor central), C:\\GBOC-Config, C:\\GBOC-DR, C:\\GBOC-SaaS-Backups, C:\\GBOC-K8s-Backups,
C:\\GBOC-Enterprise-DB, C:\\GBOC-CDP-Journal (criadas a cada inicializacao, mesmo sem uso), %USERPROFILE%\\.kopia\\...
(configuracoes temporarias do Kopia, uma por verificacao), caches do restic/Kopia no perfil do usuario e arquivos
temporarios na pasta TEMP do Windows.

Agora:
  * data/central/          identidade do agente (agent_id), central_config.json, resultado da inscricao
  * data/<modulo>/         pastas de trabalho dos modulos (dr_exports, saas_backups, k8s_backups, ...)
  * data/kopia/            configuracoes do Kopia criadas pelo GBOC
  * data/cache/restic|kopia, logs/kopia
  * data/tmp/              arquivos temporarios do Agente e dos programas que ele executa (TEMP/TMP do processo)

relocate_legacy() roda na inicializacao do Agente: copia a identidade/configuracao do local antigo (conferindo o
conteudo) e so entao apaga o original; remove as pastas antigas que estiverem vazias; pastas antigas com dados
NAO sao mexidas (aviso no log para mover manualmente).
O arquivo de semente enroll.json (colocado por GPO/Intune) continua aceito em C:\\ProgramData\\GBOC.
"""
from __future__ import annotations

import filecmp
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import List

logger = logging.getLogger("gboc_paths")

AGENT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = AGENT_ROOT / "data"
LOGS_DIR = AGENT_ROOT / "logs"
REPOSITORIES_DIR = AGENT_ROOT / "repositorios"

# Locais antigos (fora da area do sistema)
LEGACY_CENTRAL_DIR = Path("C:/ProgramData/GBOC") if os.name == "nt" else Path.home() / ".gboc"
_LEGACY_MODULE_DIRS = {          # pasta antiga -> pasta nova (relativa a data/)
    "C:/GBOC-Config": "config",
    "C:/GBOC-DR": "dr_exports",
    "C:/GBOC-SaaS-Backups": "saas_backups",
    "C:/GBOC-K8s-Backups": "k8s_backups",
    "C:/GBOC-Enterprise-DB": "enterprise_db",
    "C:/GBOC-CDP-Journal": "cdp_journal",
    "C:/GBOC-CDP-Rollback-Target": "cdp_rollback",
    "C:/GBOC-AD-Backups": "ad_backups",
}
_CENTRAL_FILES = ("agent_id", "central_config.json", "enroll.done.json", "enroll.failed.json")


def data_dir(*parts: str, create: bool = True) -> Path:
    """Pasta dentro de data/ do Agente (criada se preciso)."""
    p = DATA_DIR.joinpath(*parts)
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def central_dir() -> Path:
    """Identidade do agente e configuracao do Servidor central."""
    return data_dir("central")


def central_file(name: str) -> Path:
    """Arquivo em data/central/; se ainda so existir no local antigo, e copiado para ca antes."""
    new = central_dir() / name
    if not new.exists():
        old = LEGACY_CENTRAL_DIR / name
        try:
            if old.is_file():
                shutil.copy2(old, new)
                logger.info(f"[PASTAS] {name} copiado de {old} para {new}")
        except OSError as e:
            logger.warning(f"[PASTAS] Nao foi possivel copiar {old}: {e} (usando o local antigo)")
            return old
    return new


def enroll_seed_files() -> List[Path]:
    """enroll.json aceitos: data/central/ (instalador) e C:\\ProgramData\\GBOC (GPO/Intune)."""
    return [central_dir() / "enroll.json", LEGACY_CENTRAL_DIR / "enroll.json"]


def setup_process_dirs() -> None:
    """Temporarios, caches e logs dos motores dentro da pasta do Agente (vale para os programas que o Agente
    executa: restic, Kopia, pip...). GBOC_USE_SYSTEM_TEMP=1 mantem a pasta TEMP do Windows."""
    try:
        if os.environ.get("GBOC_USE_SYSTEM_TEMP", "").strip() != "1":
            tmp = str(data_dir("tmp"))
            for var in ("TEMP", "TMP", "TMPDIR"):
                os.environ[var] = tmp
            tempfile.tempdir = None          # recalcula com a nova pasta
        os.environ.setdefault("RESTIC_CACHE_DIR", str(data_dir("cache", "restic")))
        os.environ.setdefault("KOPIA_CACHE_DIRECTORY", str(data_dir("cache", "kopia")))
        kl = LOGS_DIR / "kopia"
        kl.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("KOPIA_LOG_DIR", str(kl))
    except OSError as e:
        logger.warning(f"[PASTAS] Pastas de trabalho nao configuradas: {e}")


def _same(a: Path, b: Path) -> bool:
    try:
        return a.is_file() and b.is_file() and filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _remove_if_empty(d: Path) -> bool:
    try:
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            return True
    except OSError:
        pass
    return False


def relocate_legacy() -> List[str]:
    """Traz para dentro da pasta do Agente o que versoes anteriores criaram fora. Retorna avisos."""
    notes: List[str] = []
    # 1) C:\ProgramData\GBOC: identidade/configuracao (copia conferida e so entao apaga o original)
    if LEGACY_CENTRAL_DIR.is_dir():
        for name in _CENTRAL_FILES:
            old = LEGACY_CENTRAL_DIR / name
            if not old.is_file():
                continue
            new = central_file(name)
            if _same(old, new):
                try:
                    old.unlink()
                except OSError as e:
                    notes.append(f"{old}: copiado, mas o original nao foi apagado ({e})")
            elif new != old:
                notes.append(f"{old} difere de {new} (mantido o de {new.parent}); o antigo pode ser apagado")
        if _remove_if_empty(LEGACY_CENTRAL_DIR):
            logger.info(f"[PASTAS] Pasta antiga removida: {LEGACY_CENTRAL_DIR}")
        elif (LEGACY_CENTRAL_DIR / "enroll.json").exists():
            pass                                   # semente de GPO/Intune ainda nao processada: fica
    # 2) Pastas de modulos: vazias sao removidas; com dados ficam (podem ser grandes, ex.: VHDX do DR)
    if os.name == "nt":
        for old_s, new_name in _LEGACY_MODULE_DIRS.items():
            old = Path(old_s)
            if not old.is_dir():
                continue
            if new_name == "config":               # configuracoes pequenas: copia o que faltar e apaga o conferido
                dst = data_dir(new_name)
                for f in list(old.iterdir()):
                    if f.is_file():
                        t = dst / f.name
                        try:
                            if not t.exists():
                                shutil.copy2(f, t)
                            if _same(f, t):
                                f.unlink()
                        except OSError:
                            pass
            if _remove_if_empty(old):
                logger.info(f"[PASTAS] Pasta antiga vazia removida: {old}")
            else:
                notes.append(f"{old} tem arquivos de uma versao anterior; o GBOC agora usa {DATA_DIR / new_name}. "
                             f"Mova o conteudo para la (se ainda for util) e apague a pasta antiga")
    # 3) Configuracoes do Kopia criadas no perfil do usuario
    kopia_home = Path.home() / ".kopia"
    if kopia_home.is_dir():
        for d in kopia_home.glob("diag_*"):
            shutil.rmtree(d, ignore_errors=True)
        for d in kopia_home.glob("gboc_config_*"):
            shutil.rmtree(d, ignore_errors=True)   # recriada em data/kopia na proxima importacao
        _remove_if_empty(kopia_home)
    for n in notes:
        logger.warning(f"[PASTAS] {n}")
    return notes
