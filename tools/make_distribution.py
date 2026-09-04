# ==============================================================================
# GBOC System v13.3.0 Enterprise Edition
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# Propriedade Intelectual & Direitos Autorais Registrados.
# ==============================================================================

"""
make_distribution.py
Script de empacotamento para gerar o pacote de instalação do GBOC System.
Copia de forma limpa os componentes Server, Agent, manifestos e instalador
para uma pasta de distribuição externa.
"""

import os
import sys
import shutil
import json
import argparse
from pathlib import Path

# Diretórios e arquivos a ignorar durante a cópia
IGNORE_PATTERNS = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".pytest_cache",
    ".git",
    ".github",
    ".vs",
    ".vscode",
    "*.log",
    "logs",
    "startup_*.log",
    "*.tmp",
    "*.swp"
)

def create_unified_requirements(server_req_path: Path, agent_req_path: Path, output_path: Path):
    """Combina dependências únicas do Server e Agent em um arquivo consolidado."""
    dependencies = set()
    
    for req_file in [server_req_path, agent_req_path]:
        if req_file.exists():
            with open(req_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        dependencies.add(line)
                        
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# GBOC System v14.0.0 - Dependencias Consolidadas (Server + Agent)\n")
        for dep in sorted(dependencies):
            f.write(f"{dep}\n")
    print(f"  [OK] Dependencias consolidadas criadas em: {output_path}")

def copy_component(source_dir: Path, target_dir: Path, component_name: str):
    """Copia uma árvore de diretórios aplicando filtro de exclusão."""
    if not source_dir.exists():
        print(f"  [ERRO] Diretorio de origem nao encontrado: {source_dir}")
        return False
        
    print(f"  -> Copiando {component_name} de {source_dir} para {target_dir}...")
    if target_dir.exists():
        shutil.rmtree(target_dir)
        
    shutil.copytree(source_dir, target_dir, ignore=IGNORE_PATTERNS)
    print(f"  [OK] {component_name} copiado com sucesso!")
    return True

def generate_manifest(output_dir: Path, version: str = "14.0.0 Full Stable Enterprise"):
    """Gera um arquivo de manifesto com metadados do pacote gerado."""
    manifest = {
        "system": "GBOC System",
        "version": version,
        "release_date": "2026",
        "author": "Master11BR",
        "components": {
            "GBOC-Server": {
                "installed": (output_dir / "Server").exists(),
                "default_port": 8000
            },
            "GBOC-Agent": {
                "installed": (output_dir / "Agent").exists(),
                "default_port": 9200
            }
        },
        "installer_version": "2.0.0"
    }
    
    manifest_path = output_dir / "package_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4, ensure_ascii=False)
    print(f"  [OK] Manifesto de versao gerado em: {manifest_path}")

def build_package(source_root: Path, output_dir: Path, clean: bool = False):
    """Executa a criacao do pacote de distribuicao."""
    print("=" * 70)
    print("  GBOC System - Gerador de Pacote de Distribuicao & Instalador")
    print("=" * 70)
    print(f"Origem do Codigo: {source_root}")
    print(f"Destino do Pacote: {output_dir}\n")

    if clean and output_dir.exists():
        print(f"Limpando diretorio de saida existente: {output_dir}")
        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass

    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Copiar GBOC-Server
    server_src = source_root / "GBOC-Server"
    server_dst = output_dir / "Server"
    copy_component(server_src, server_dst, "GBOC-Server")

    # 2. Copiar GBOC-Agent
    agent_src = source_root / "GBOC-Agent"
    agent_dst = output_dir / "Agent"
    copy_component(agent_src, agent_dst, "GBOC-Agent")

    # 3. Criar pasta Dependencies
    deps_dir = output_dir / "Dependencies"
    deps_dir.mkdir(exist_ok=True)
    
    # Copiar requirements individuais
    if (server_src / "requirements.txt").exists():
        shutil.copy2(server_src / "requirements.txt", deps_dir / "requirements-server.txt")
    if (agent_src / "requirements.txt").exists():
        shutil.copy2(agent_src / "requirements.txt", deps_dir / "requirements-agent.txt")
        
    # Gerar requirements unificado
    create_unified_requirements(
        server_src / "requirements.txt",
        agent_src / "requirements.txt",
        deps_dir / "requirements-all.txt"
    )

    # 4. Gerar manifesto
    generate_manifest(output_dir)

    # 5. Gerar LEIAME_INSTALACAO.md
    readme_content = """# GBOC System v14.0.0 Enterprise — Pacote de Instalacao

Este pacote contem todos os arquivos e dependencias para instalar o GBOC Server, o GBOC Agent ou Ambos.

## Como Instalar:
1. Clique duas vezes em Setup.bat (Executar como Administrador).
2. Escolha no menu:
   - [1] GBOC Agent (Agente de backup local, porta 9200)
   - [2] GBOC Server (Painel central e API, porta 8000)
   - [3] GBOC Enterprise Completo (Servidor e Agente juntos no mesmo host)
   - [4] Apenas Dependencias e Motores (Restic, Kopia, pacotes Python)

3. O instalador configura automaticamente:
   - Ambiente virtual Python isolado (venv)
   - Todas as bibliotecas Python necessarias
   - Motores de backup Restic e Kopia
   - Scripts de inicializacao rapida (start_all.bat, stop_all.bat, uninstall.bat)
   - Atalhos na Area de Trabalho

## Instalacao Silenciosa via Linha de Comando (PowerShell):
```powershell
powershell -ExecutionPolicy Bypass -File .\\Setup.ps1 -InstallMode Agent -TargetDir "C:\\GBOC"
powershell -ExecutionPolicy Bypass -File .\\Setup.ps1 -InstallMode Server -TargetDir "C:\\GBOC"
powershell -ExecutionPolicy Bypass -File .\\Setup.ps1 -InstallMode Both -TargetDir "C:\\GBOC"
```
"""
    with open(output_dir / "LEIAME_INSTALACAO.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print(f"  [OK] Guia LEIAME_INSTALACAO.md gerado em: {output_dir / 'LEIAME_INSTALACAO.md'}")

    print("\n" + "=" * 70)
    print("  [OK] Pacote de distribuicao gerado com sucesso!")
    print(f"  Localizacao: {output_dir}")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="Gerador de Pacote de Distribuicao GBOC")
    parser.add_argument("--source", type=str, default=str(Path(__file__).resolve().parent.parent),
                        help="Diretorio raiz do projeto GBOC")
    parser.add_argument("--output", type=str, required=True,
                        help="Diretorio de destino do pacote (fora dos fontes atuais)")
    parser.add_argument("--clean", action="store_true",
                        help="Limpar diretorio de destino antes de copiar")
    
    args = parser.parse_args()
    source_path = Path(args.source).resolve()
    output_path = Path(args.output).resolve()

    build_package(source_path, output_path, clean=args.clean)

if __name__ == "__main__":
    main()
