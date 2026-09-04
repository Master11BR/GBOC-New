#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GBOC Source Code Watermarking & Verification Tool
=================================================
Utiliza técnicas de esteganografia Unicode (Zero-Width Steganography)
e geração de tokens canário para proteger e comprovar a autoria
dos fontes do sistema GBOC.

Uso:
  python tools/watermark_tool.py --embed --path GBOC-Server/ --payload "GBOC-AUTHOR-DEV-2026-KEY:OFFICIAL"
  python tools/watermark_tool.py --scan --path GBOC-Server/
  python tools/watermark_tool.py --generate-canary --dev-id "DEV_KEY_2026"
"""

import argparse
import hashlib
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

# Caracteres de Largura Zero (Zero-Width Characters)
ZW_PREFIX = "\uFEFF\u200D"  # BOM + Zero-Width Joiner (Início da marca)
ZW_SUFFIX = "\u200D\uFEFF"  # Zero-Width Joiner + BOM (Fim da marca)
ZW_ZERO = "\u200B"         # Zero-Width Space ('0')
ZW_ONE = "\u200C"          # Zero-Width Non-Joiner ('1')

# Regex para detectar a sequência completa de marca d'água invisível
ZW_REGEX = re.compile(
    re.escape(ZW_PREFIX) + r"([" + re.escape(ZW_ZERO) + re.escape(ZW_ONE) + r"]+)" + re.escape(ZW_SUFFIX)
)

SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".html": "html",
    ".css": "css",
    ".md": "markdown",
    ".json": "json",
    ".ps1": "powershell",
    ".bat": "batch",
}


def encode_watermark(payload: str) -> str:
    """Codifica um texto em uma sequência de caracteres de largura zero (invisíveis)."""
    if not payload:
        raise ValueError("Payload não pode ser vazio.")
    
    # Converte payload string em bytes UTF-8 e depois em bits
    payload_bytes = payload.encode("utf-8")
    bits = "".join(f"{b:08b}" for b in payload_bytes)
    
    # Mapeia 0 -> ZW_ZERO e 1 -> ZW_ONE
    zw_bits = "".join(ZW_ZERO if bit == "0" else ZW_ONE for bit in bits)
    
    return f"{ZW_PREFIX}{zw_bits}{ZW_SUFFIX}"


def decode_watermark(zw_sequence: str) -> str:
    """Decodifica uma sequência de caracteres de largura zero para a string original."""
    # Extrai apenas os bits internos
    match = ZW_REGEX.search(zw_sequence)
    if match:
        bits_str = match.group(1)
    else:
        # Se recebemos diretamente os bits internos
        bits_str = zw_sequence
    
    bits = "".join("0" if char == ZW_ZERO else "1" for char in bits_str if char in (ZW_ZERO, ZW_ONE))
    
    if len(bits) % 8 != 0:
        raise ValueError("Sequência de bits de largura zero inválida (tamanho não alinhado em bytes).")
    
    byte_chunks = [int(bits[i:i+8], 2) for i in range(0, len(bits), 8)]
    return bytes(byte_chunks).decode("utf-8", errors="replace")


def find_watermarks_in_text(text: str) -> List[Tuple[str, str]]:
    """
    Varre o texto procurando por todas as marcas d'água invisíveis.
    Retorna uma lista de tuplas (sequência_bruta_zw, payload_decodificado).
    """
    results = []
    for match in ZW_REGEX.finditer(text):
        full_match = match.group(0)
        bits_matched = match.group(1)
        try:
            decoded = decode_watermark(bits_matched)
            results.append((full_match, decoded))
        except Exception as e:
            results.append((full_match, f"[Erro na decodificação: {e}]"))
    return results


def strip_watermarks_from_text(text: str) -> str:
    """Remove todas as marcas d'água invisíveis do texto."""
    return ZW_REGEX.sub("", text)


def format_comment_with_watermark(extension: str, watermark_zw: str, payload_summary: str = "GBOC Module Source") -> str:
    """Gera a linha de cabeçalho formatada adequadamente para a extensão do arquivo."""
    ext = extension.lower()
    
    if ext == ".py":
        return f"# -*- coding: utf-8 -*-\n# {payload_summary} {watermark_zw}\n"
    elif ext in (".js", ".css"):
        return f"/* {payload_summary} {watermark_zw} */\n"
    elif ext in (".html", ".md"):
        return f"<!-- {payload_summary} {watermark_zw} -->\n"
    elif ext == ".ps1":
        return f"# {payload_summary} {watermark_zw}\n"
    else:
        return f"# {payload_summary} {watermark_zw}\n"


def embed_watermark_in_file(file_path: str, payload: str, overwrite: bool = True) -> bool:
    """
    Insere a marca d'água no cabeçalho do arquivo especificado.
    Retorna True em caso de sucesso.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")
    
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    # Remove marcas d'água existentes se overwrite for True
    clean_content = strip_watermarks_from_text(content) if overwrite else content
    
    watermark_zw = encode_watermark(payload)
    comment_header = format_comment_with_watermark(ext, watermark_zw)
    
    # Se o arquivo já começa com shebang (#!) ou codificação, insere logo após
    lines = clean_content.splitlines(keepends=True)
    new_lines = []
    
    if lines and (lines[0].startswith("#!") or "coding:" in lines[0]):
        new_lines.append(lines[0])
        new_lines.append(comment_header)
        new_lines.extend(lines[1:])
    else:
        new_lines.append(comment_header)
        new_lines.extend(lines)
    
    new_content = "".join(new_lines)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
        
    return True


def scan_path(path: str) -> List[Dict[str, str]]:
    """
    Escaneia recursivamente um arquivo ou diretório em busca de marcas d'água.
    Retorna uma lista de dicionários com os achados.
    """
    report = []
    
    if os.path.isfile(path):
        files_to_scan = [path]
    elif os.path.isdir(path):
        files_to_scan = []
        for root, dirs, files in os.walk(path):
            # Ignorar diretórios virtuais e caches
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules", ".pytest_cache", "GBOC-Distribution")]
            for file in files:
                _, ext = os.path.splitext(file)
                if ext.lower() in SUPPORTED_EXTENSIONS:
                    files_to_scan.append(os.path.join(root, file))
    else:
        raise FileNotFoundError(f"Caminho inválido: {path}")

    for file_path in files_to_scan:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            
            watermarks = find_watermarks_in_text(content)
            if watermarks:
                for _, payload in watermarks:
                    report.append({
                        "file": file_path,
                        "status": "WATERMARKED",
                        "payload": payload
                    })
            else:
                report.append({
                    "file": file_path,
                    "status": "CLEAN",
                    "payload": ""
                })
        except Exception as e:
            report.append({
                "file": file_path,
                "status": "ERROR",
                "payload": str(e)
            })
            
    return report


def generate_canary_code(dev_id: str, secret_key: str = "GBOC_KEY_2026") -> Dict[str, str]:
    """Gerador de constantes canário (Honeytokens) para embutir em código Python/JS."""
    raw_sig = f"{dev_id}:{secret_key}".encode("utf-8")
    sha256_hash = hashlib.sha256(raw_sig).hexdigest()
    hex_constant = f"0x{sha256_hash[:16].upper()}"
    
    python_snippet = f"""# --- CANARY HONEYTOKEN FOR DEV AUTHOR PROOF ---
# Dev Identity: {dev_id}
GBOC_DEV_AUTH_SIGNATURE = "{hex_constant}"
GBOC_SECURITY_CHECKSUM = "{sha256_hash}"
"""

    js_snippet = f"""// --- CANARY HONEYTOKEN FOR DEV AUTHOR PROOF ---
// Dev Identity: {dev_id}
const GBOC_DEV_AUTH_SIGNATURE = "{hex_constant}";
const GBOC_SECURITY_CHECKSUM = "{sha256_hash}";
"""

    return {
        "hex_constant": hex_constant,
        "sha256_hash": sha256_hash,
        "python": python_snippet,
        "javascript": js_snippet
    }


def main():
    parser = argparse.ArgumentParser(
        description="GBOC Source Code Watermarking & Verification Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--embed", action="store_true", help="Inserir marca d'água em arquivo ou diretório")
    group.add_argument("--scan", action="store_true", help="Escanear e verificar marca d'água em arquivo ou diretório")
    group.add_argument("--generate-canary", action="store_true", help="Gerar constantes canário (Honeytokens) para código")
    
    parser.add_argument("--path", type=str, help="Caminho do arquivo ou diretório para --embed ou --scan")
    parser.add_argument("--payload", type=str, default="GBOC-DEV-AUTHOR-2026", help="Texto da assinatura da marca d'água")
    parser.add_argument("--dev-id", type=str, default="DEV_MASTER_2026", help="ID do desenvolvedor para --generate-canary")

    args = parser.parse_args()

    if args.generate_canary:
        canary = generate_canary_code(args.dev_id)
        print("==================================================")
        print("  GBOC DEV CANARY HONEYTOKEN GENERATOR")
        print("==================================================")
        print(f"Dev ID: {args.dev_id}")
        print(f"Hex Signature: {canary['hex_constant']}")
        print(f"SHA256 Hash:   {canary['sha256_hash']}\n")
        print("--- Python Snippet ---")
        print(canary["python"])
        print("--- JavaScript Snippet ---")
        print(canary["javascript"])
        return

    if not args.path:
        print("Erro: O argumento --path é obrigatório para --embed e --scan.", file=sys.stderr)
        sys.exit(1)

    if args.embed:
        abs_path = os.path.abspath(args.path)
        print(f"Iniciando inserção de marca d'água em: {abs_path}")
        print(f"Assinatura (Payload): '{args.payload}'")
        
        if os.path.isfile(abs_path):
            embed_watermark_in_file(abs_path, args.payload)
            print(f"[SUCESSO] Marca d'água inserida em: {abs_path}")
        elif os.path.isdir(abs_path):
            report = scan_path(abs_path)
            count = 0
            for item in report:
                if item["status"] != "ERROR":
                    embed_watermark_in_file(item["file"], args.payload)
                    count += 1
            print(f"[SUCESSO] Marca d'água inserida em {count} arquivo(s).")
        else:
            print(f"Erro: Caminho não encontrado: {abs_path}", file=sys.stderr)
            sys.exit(1)

    elif args.scan:
        abs_path = os.path.abspath(args.path)
        print(f"Escaneando marcas d'água em: {abs_path}\n")
        report = scan_path(abs_path)
        
        watermarked_files = [item for item in report if item["status"] == "WATERMARKED"]
        clean_files = [item for item in report if item["status"] == "CLEAN"]
        error_files = [item for item in report if item["status"] == "ERROR"]

        print(f"--- RELATÓRIO DE AUDITORIA DE AUTORIA ---")
        print(f"Total de arquivos analisados: {len(report)}")
        print(f"Arquivos com Marca d'Água:  {len(watermarked_files)}")
        print(f"Arquivos Limpos (Sem Marca): {len(clean_files)}")
        if error_files:
            print(f"Arquivos com Erro de Leitura: {len(error_files)}")
        print("-----------------------------------------\n")

        if watermarked_files:
            print("DETALHES DOS ARQUIVOS MARCADOS:")
            for item in watermarked_files:
                rel_path = os.path.relpath(item["file"], os.getcwd())
                print(f"  [MARCADO] {rel_path} -> Payload: \"{item['payload']}\"")
        else:
            print("Nenhuma marca d'água invisível foi encontrada nos arquivos analisados.")


if __name__ == "__main__":
    main()
