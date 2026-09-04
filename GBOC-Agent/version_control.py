# ==============================================================================
# GBOC System v14.0.0 Full Stable Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# A cópia, distribuição ou modificação não autorizada é estritamente proibida.
# ==============================================================================

"""
GBOC Semantic Versioning 2.0 (SemVer) Control Module (Agent)
Padronização Internacional de Versionamento: MAJOR.MINOR.PATCH-PRERELEASE+BUILD
Atualização e Rastreamento Dinâmico e Automático de Build / Revisão
"""

import os
import json
import subprocess
import datetime
from typing import Dict, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(BASE_DIR, "data", "version_info.json")

# Configuração Base SemVer
MAJOR = 14
MINOR = 0
PATCH = 0
PRERELEASE = "full-stable"

def _get_git_info() -> Dict[str, str]:
    """Obtém informações em tempo real do repositório Git."""
    info = {
        "commit": "a8f2e91",
        "commit_count": "1",
        "branch": "main",
        "is_dirty": False
    }
    try:
        # Commit curto
        res = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=BASE_DIR, capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip():
            info["commit"] = res.stdout.strip()
        
        # Contagem de commits (revisão)
        res_count = subprocess.run(["git", "rev-list", "--count", "HEAD"],
                                   cwd=BASE_DIR, capture_output=True, text=True, timeout=3)
        if res_count.returncode == 0 and res_count.stdout.strip():
            info["commit_count"] = res_count.stdout.strip()
            
        # Branch
        res_branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                    cwd=BASE_DIR, capture_output=True, text=True, timeout=3)
        if res_branch.returncode == 0 and res_branch.stdout.strip():
            info["branch"] = res_branch.stdout.strip()

        # Status modificado / dirty
        res_status = subprocess.run(["git", "status", "--porcelain"],
                                    cwd=BASE_DIR, capture_output=True, text=True, timeout=3)
        if res_status.returncode == 0 and res_status.stdout.strip():
            info["is_dirty"] = True
    except Exception:
        pass
    return info

def _load_or_create_build_meta() -> Dict[str, Any]:
    """Carrega ou cria o estado persistente do build counter."""
    os.makedirs(os.path.dirname(VERSION_FILE), exist_ok=True)
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    data = {
        "build_number": 1,
        "last_build_date": today_str,
        "last_updated": datetime.datetime.now().isoformat()
    }
    
    if os.path.exists(VERSION_FILE):
        try:
            with open(VERSION_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    data.update(loaded)
        except Exception:
            pass
            
    return data

def auto_increment_build() -> int:
    """Incrementa o build counter persistente a cada nova alteração / inicialização."""
    meta = _load_or_create_build_meta()
    meta["build_number"] = int(meta.get("build_number", 0)) + 1
    meta["last_build_date"] = datetime.date.today().strftime("%Y-%m-%d")
    meta["last_updated"] = datetime.datetime.now().isoformat()
    try:
        with open(VERSION_FILE, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except Exception:
        pass
    return meta["build_number"]

def bump_version(part: str = "patch") -> str:
    """Incrementa programaticamente partes da versão (major, minor, patch, build)."""
    global MAJOR, MINOR, PATCH
    if part == "major":
        MAJOR += 1
        MINOR = 0
        PATCH = 0
    elif part == "minor":
        MINOR += 1
        PATCH = 0
    elif part == "patch":
        PATCH += 1
    auto_increment_build()
    return f"{MAJOR}.{MINOR}.{PATCH}"

def get_version_info() -> Dict[str, Any]:
    """Retorna informações detalhadas e dinâmicas do versionamento semântico 2.0."""
    git_info = _get_git_info()
    meta = _load_or_create_build_meta()
    
    build_num = meta.get("build_number", 1)
    build_date = meta.get("last_build_date", datetime.date.today().strftime("%Y-%m-%d"))
    git_sha = git_info["commit"]
    rev_count = git_info["commit_count"]
    dirty_tag = ".dirty" if git_info["is_dirty"] else ""
    
    raw_version = f"{MAJOR}.{MINOR}.{PATCH}"
    semver_str = f"{raw_version}-{PRERELEASE}+build.{build_date}.rev{rev_count}.b{build_num}.git.{git_sha}{dirty_tag}"
    
    return {
        "raw_version": raw_version,
        "semver": semver_str,
        "major": MAJOR,
        "minor": MINOR,
        "patch": PATCH,
        "prerelease": PRERELEASE,
        "build_number": build_num,
        "build_date": build_date,
        "git_commit": git_sha,
        "git_branch": git_info["branch"],
        "git_revision": rev_count,
        "is_dirty": git_info["is_dirty"],
        "last_updated": meta.get("last_updated"),
        "release_channel": "Enterprise Stable",
        "compatibility": {
            "min_server_version": "14.0.0",
            "recommended_server_version": raw_version,
            "protocol_version": "2.1"
        }
    }

__version__ = f"{MAJOR}.{MINOR}.{PATCH}"
