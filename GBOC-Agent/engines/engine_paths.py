#!/usr/bin/env python3
"""
GBOC Agent - Localizador de executáveis de motores de backup.

Detecta restic, kopia, duplicati e outros motores independentemente
_da forma_ e _do local_ em que foram instalados, priorizando:
1. Variáveis de ambiente explícitas
2. PATH do sistema
3. Diretórios conhecidos
4. Busca recursiva limitada em raízes comuns do Windows
"""

import os
import shutil
import platform
import logging
import threading
import time
import json

logger = logging.getLogger(__name__)

_KNOWN_DIRS = [
    r"C:\GBOC\Tools\Restic",
    r"C:\GBOC\Tools\Kopia",
    r"C:\GBOC\Tools\Duplicati",
    r"C:\Program Files\Restic",
    r"C:\Program Files\Kopia",
    r"C:\Program Files\KopiaUI",
    r"C:\Program Files\KopiaUI\resources\server",
    r"C:\Program Files\Duplicati",
    r"C:\Program Files\Duplicati 2",
    r"C:\Program Files (x86)\Duplicati",
    r"C:\Program Files (x86)\Duplicati 2",
    r"C:\ProgramData\chocolatey\bin",
    r"C:\tools",
    os.path.expanduser(r"~\AppData\Local\Programs\Restic"),
    os.path.expanduser(r"~\AppData\Local\Programs\Kopia"),
    os.path.expanduser(r"~\AppData\Local\Programs\KopiaUI"),
    os.path.expanduser(r"~\AppData\Local\Programs\KopiaUI\resources\server"),
    os.path.expanduser(r"~\scoop\shims"),
]

_ALT_NAMES = {
    'restic': ['restic.exe', 'restic_0.17.3_windows_amd64.exe', 'restic_0.17.0_windows_amd64.exe'],
    'kopia': ['kopia.exe'],
    'duplicati': ['Duplicati.CommandLine.exe', 'duplicati-cli.exe', 'duplicati.exe'],
    'borg': ['borg.exe', 'borgbackup.exe'],
    'rclone': ['rclone.exe'],
}

_ENV_VARS = {
    'restic': 'RESTIC_PATH',
    'kopia': 'KOPIA_PATH',
    'duplicati': 'DUPLICATI_PATH',
    'borg': 'BORG_PATH',
    'rclone': 'RCLONE_PATH',
}

_cache: dict[str, str | None] = {}
_cache_source: dict[str, str | None] = {}
_cache_lock = threading.RLock()
_ENGINE_LIST = ["restic", "kopia", "duplicati", "borg", "rclone"]
_CACHE_FILE = os.path.abspath(
    os.environ.get(
        "GBOC_ENGINE_PATHS_CACHE_FILE",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "engine_paths_cache.json")
    )
)


def _candidate_names_for(key: str) -> list[str]:
    exe_name = key if key.endswith('.exe') else f"{key}.exe"
    names = [exe_name]
    for alt in _ALT_NAMES.get(key, []):
        if alt not in names:
            names.append(alt)
    return names


def _iter_search_roots() -> list[str]:
    roots = []

    for p in _KNOWN_DIRS:
        if p and p not in roots:
            roots.append(p)

    for env_name in ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432', 'LOCALAPPDATA'):
        p = os.environ.get(env_name, '')
        if p and p not in roots:
            roots.append(p)

    path_entries = os.environ.get('PATH', '').split(os.pathsep)
    for p in path_entries:
        p = p.strip().strip('"')
        if p and os.path.isdir(p) and p not in roots:
            roots.append(p)

    return roots


def _recursive_find(root: str, key: str, candidate_names: list[str], max_depth: int = 4) -> str | None:
    if not root or not os.path.isdir(root):
        return None

    root = os.path.abspath(root)
    root_depth = root.count(os.sep)
    candidate_names_lower = {n.lower() for n in candidate_names}

    try:
        for current_root, dirs, files in os.walk(root):
            current_depth = current_root.count(os.sep) - root_depth
            if current_depth > max_depth:
                dirs[:] = []
                continue

            lower_root = current_root.lower()
            if key == 'kopia' and 'kopiaui' in lower_root:
                nested = os.path.join(current_root, 'resources', 'server', 'kopia.exe')
                if os.path.isfile(nested):
                    return nested

            for name in candidate_names:
                candidate = os.path.join(current_root, name)
                if os.path.isfile(candidate):
                    return candidate

            for f in files:
                lf = f.lower()
                if lf in candidate_names_lower:
                    return os.path.join(current_root, f)
                if lf.startswith(key) and lf.endswith('.exe'):
                    return os.path.join(current_root, f)
    except Exception:
        return None

    return None


def _find_executable(name: str, allow_scan: bool = True) -> tuple[str | None, str | None]:
    key = name.lower()
    candidate_names = _candidate_names_for(key)

    env_var = _ENV_VARS.get(key, '')
    if env_var:
        env_path = os.environ.get(env_var, '').strip().strip('"')
        if env_path and os.path.isfile(env_path):
            return env_path, f'env:{env_var}'

    for candidate in [name] + candidate_names:
        path = shutil.which(candidate)
        if path and os.path.isfile(path):
            return path, 'PATH'

    if platform.system() != 'Windows':
        return None, None

    for root in _iter_search_roots():
        if not os.path.isdir(root):
            continue

        for candidate_name in candidate_names:
            direct = os.path.join(root, candidate_name)
            if os.path.isfile(direct):
                return direct, f'dir:{root}'

        if allow_scan:
            found = _recursive_find(root, key, candidate_names, max_depth=4)
            if found:
                return found, f'scan:{root}'

    return None, None


def _persist_cache() -> None:
    try:
        cache_dir = os.path.dirname(_CACHE_FILE)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

        payload = {
            "version": 1,
            "updated_at": time.time(),
            "engines": {
                key: {
                    "path": _cache.get(key),
                    "source": _cache_source.get(key)
                }
                for key in _ENGINE_LIST
            }
        }

        tmp_file = _CACHE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, _CACHE_FILE)
    except Exception as e:
        logger.debug(f"[ENGINE][CACHE] falha ao persistir cache: {e}")


def _load_cache() -> None:
    if not os.path.isfile(_CACHE_FILE):
        return

    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)

        engines = payload.get("engines") if isinstance(payload, dict) else None
        if not isinstance(engines, dict):
            return

        for key in _ENGINE_LIST:
            item = engines.get(key)
            if not isinstance(item, dict):
                continue
            _cache[key] = item.get("path")
            _cache_source[key] = item.get("source")

        logger.info(f"[ENGINE][CACHE] cache persistente carregado: {_CACHE_FILE}")
    except Exception as e:
        logger.debug(f"[ENGINE][CACHE] falha ao carregar cache persistente: {e}")


def _set_cache(key: str, path: str | None, source: str | None) -> None:
    _cache[key] = path
    _cache_source[key] = source
    _persist_cache()


def get_engine_path(engine_name: str, allow_scan: bool = False) -> str | None:
    key = engine_name.lower()

    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            if cached and os.path.isfile(cached):
                logger.debug(f"[ENGINE][CACHE] hit {key}: {cached}")
                return cached

            if not cached:
                logger.debug(f"[ENGINE][CACHE] miss persistente para {key}")
                return None

            _cache.pop(key, None)
            _cache_source.pop(key, None)

        start = time.perf_counter()
        path, source = _find_executable(key, allow_scan=allow_scan)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        if path and os.path.isfile(path):
            _set_cache(key, path, source)
            logger.info(f"[ENGINE] {key} encontrado: {path} ({source}) em {elapsed_ms} ms")
            return path

        _set_cache(key, None, None)
        logger.debug(f"[ENGINE] {key} não encontrado em {elapsed_ms} ms")
        return None


def get_engine_path_or_raise(engine_name: str) -> str:
    path = get_engine_path(engine_name, allow_scan=True)
    if not path:
        raise ValueError(
            f"Motor '{engine_name}' não está instalado ou não foi encontrado. "
            f"Verifique PATH, instalação local ou diretórios padrão do Windows."
        )
    return path


def detect_all_engines(allow_scan: bool = False) -> list[dict]:
    total_start = time.perf_counter()
    results = []
    for name in _ENGINE_LIST:
        item_start = time.perf_counter()
        path = get_engine_path(name, allow_scan=allow_scan)
        item_elapsed_ms = round((time.perf_counter() - item_start) * 1000, 2)
        logger.debug(f"[PERF][ENGINE] detect {name} em {item_elapsed_ms} ms")
        results.append({
            "name": name,
            "detected": path is not None,
            "path": path,
            "source": _cache_source.get(name)
        })
    total_elapsed_ms = round((time.perf_counter() - total_start) * 1000, 2)
    logger.info(f"[PERF][ENGINE] detect_all_engines concluído em {total_elapsed_ms} ms")
    return results


def clear_cache():
    """Limpa o cache (útil se o PATH mudar em runtime)."""
    with _cache_lock:
        _cache.clear()
        _cache_source.clear()


def rescan_all_engines() -> list[dict]:
    with _cache_lock:
        _cache.clear()
        _cache_source.clear()
    logger.info("[ENGINE][CACHE] rescan completo solicitado")
    return detect_all_engines(allow_scan=True)


_load_cache()
