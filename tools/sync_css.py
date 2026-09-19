"""
tools/sync_css.py
======================

Sincronizador canonico de CSS para o GBOC.

Principio: Agent (GBOC-Agent/static/) e Server (GBOC-Server/static/) sao
deployments independentes em maquinas diferentes. Precisam de copias PROPRIAS,
mas IDENTICAS.

    shared-css/  ->  1 fonte da verdade (canonica, editavel)
         |
         +--sync-->  GBOC-Agent/static/  (arquivos servidos pelo Agent FastAPI)
         +--sync-->  GBOC-Server/static/ (arquivos servidos pelo Server FastAPI)

Uso:
    python tools/sync_css.py                  # sincroniza (sobrescreve alvos)
    python tools/sync_css.py --verify         # so reporta divergencias (dry-run)
    python tools/sync_css.py --init-from-agent   # 1a vez: popula shared-css/ a partir do Agent (ja eh o default se shared-css estiver vazio)
"""
import os
import sys
import shutil
import filecmp
import hashlib

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SHARED = os.path.join(REPO_ROOT, "shared-css")
AGENT_STATIC = os.path.join(REPO_ROOT, "GBOC-Agent", "static")
SERVER_STATIC = os.path.join(REPO_ROOT, "GBOC-Server", "static")

# ------------------------------------------------------------------------------
# Lista de arquivos CSS e JS compartilhados sincronizados.
# Sub-arvores inteiras sao copiadas recursivamente se listadas como pastas.
# ------------------------------------------------------------------------------
CSS_FILES = [
    "style.css",
    "gboc-layout.css",
    "gboc-themes.css",
    "gboc-hardware-hud.css",
    "gboc-file-picker.css",
]
JS_FILES = [
    "gboc-perf.js",
    "gboc-modal.js",
    "gboc-layout-manager.js",
    "gboc-hardware-hud.js",
    "gboc-motion.js",
]
CSS_DIRS = [
    os.path.join("ui", "design-system"),
    os.path.join("ui", "models", "modern"),
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def list_canonical_paths():
    """Retorna lista (relative_path, absolute_in_shared) de todos os arquivos sincronizados."""
    rels = []
    for f in CSS_FILES + JS_FILES:
        rels.append(f)
    for d in CSS_DIRS:
        d_abs = os.path.join(SHARED, d)
        if not os.path.isdir(d_abs):
            continue
        for root, _, files in os.walk(d_abs):
            for f in files:
                if f.endswith((".css", ".js")):
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, SHARED).replace(os.sep, "/")
                    rels.append(rel)
    return rels


def init_shared_from_agent(force=False):
    """Se a pasta canonica estiver vazia ou faltando arquivos, popula copiando do Agent/static."""
    ensure_dir(SHARED)
    copied = 0
    for f in CSS_FILES + JS_FILES:
        src = os.path.join(AGENT_STATIC, f)
        dst = os.path.join(SHARED, f)
        if os.path.isfile(src) and (force or not os.path.isfile(dst)):
            ensure_dir(os.path.dirname(dst))
            shutil.copy2(src, dst)
            copied += 1
    for d in CSS_DIRS:
        src_dir = os.path.join(AGENT_STATIC, d)
        dst_dir = os.path.join(SHARED, d)
        if os.path.isdir(src_dir):
            shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
            for root, _, files in os.walk(dst_dir):
                copied += sum(1 for f in files if f.endswith((".css", ".js")))
    print(f"[init] shared-css/ inicializado a partir de GBOC-Agent/static/: {copied} arquivos.")
    return True


def sync_one(target_name, target_root, verify_only=False):
    rels = list_canonical_paths()
    diverged = 0
    copied = 0
    missing_target = 0
    for rel in rels:
        src = os.path.join(SHARED, rel)
        dst = os.path.join(target_root, rel.replace("/", os.sep))
        if not os.path.isfile(src):
            continue
        if not os.path.isfile(dst):
            missing_target += 1
            action = "FALTANDO"
            if not verify_only:
                ensure_dir(os.path.dirname(dst))
                shutil.copy2(src, dst)
                copied += 1
                action = "COPIADO"
            print(f"  [{target_name}] {rel}: {action}")
            continue
        same = filecmp.cmp(src, dst, shallow=False)
        if not same:
            diverged += 1
            action = "DIVERGE"
            if not verify_only:
                shutil.copy2(src, dst)
                copied += 1
                action = "ATUALIZADO"
            print(f"  [{target_name}] {rel}: {action}  (src={sha256(src)[:12]} dst={sha256(dst)[:12]})")
    return diverged, missing_target, copied


def main():
    args = set(sys.argv[1:])
    verify_only = "--verify" in args or "--dry-run" in args
    force_init = "--init-from-agent" in args

    if not os.path.isdir(AGENT_STATIC):
        print(f"[ERRO] Pasta do Agent nao encontrada: {AGENT_STATIC}")
        sys.exit(2)

    init_shared_from_agent(force=force_init)

    if not os.listdir(SHARED):
        print("[ERRO] shared-css/ esta vazia e nao foi possivel inicializar.")
        sys.exit(3)

    total_files = len(list_canonical_paths())
    print(f"=== Sync CSS Canonico  (verificando {total_files} arquivos) ===")
    print(f"  Canonica : {SHARED}")
    print(f"  Agent    : {AGENT_STATIC}")
    print(f"  Server   : {SERVER_STATIC}")
    print(f"  Modo     : {'VERIFICACAO (dry-run)' if verify_only else 'SINCRONIZACAO (sobrescreve alvos)'}")
    print()

    div_ag, miss_ag, cp_ag = sync_one("Agent", AGENT_STATIC, verify_only)
    div_sv, miss_sv, cp_sv = sync_one("Server", SERVER_STATIC, verify_only)
    print()
    print("=== Resumo ===")
    print(f"  Agent:  divergentes={div_ag}, faltantes={miss_ag}, copiados/atualizados={cp_ag}")
    print(f"  Server: divergentes={div_sv}, faltantes={miss_sv}, copiados/atualizados={cp_sv}")
    if verify_only:
        total_issues = div_ag + miss_ag + div_sv + miss_sv
        if total_issues == 0:
            print("\n[OK] Agent e Server estao 100% sincronizados com a canonica.")
            sys.exit(0)
        print(f"\n[WARN] {total_issues} problemas encontrados. Rode sem --verify para corrigir.")
        sys.exit(1)
    else:
        print("\n[OK] Sincronizacao concluida.")


if __name__ == "__main__":
    main()
