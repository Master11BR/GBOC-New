# ==============================================================================
# GBOC System v14.8.2 Enterprise Edition
# Module: Anti-Bitrot & Reed-Solomon Parity Auto-Healing Engine
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import os
import sys
import time
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("gboc_bitrot_scrub")


class BitrotScrubEngine:
    """
    Motor de Detecção de Corrupção Silenciosa (Bitrot) e Verificação de Integridade de Blocos.
    Varre blocos arquivados reais, calcula e valida hashes SHA-256 de dados reais no disco host.
    Zero-Mock: 100% de leitura de blocos reais do sistema de arquivos.
    """

    def run_bitrot_scrub(self, target_repository_path: str = "") -> Dict[str, Any]:
        if not target_repository_path:
            from core.gboc_paths import REPOSITORIES_DIR
            target_repository_path = str(REPOSITORIES_DIR)       # antes: C:\\GBOC-Backups
        start_time = time.time()
        logs: List[str] = [f"Iniciando varredura de integridade física e lógica (Scrub) em: {target_repository_path}"]

        if not target_repository_path or not os.path.exists(target_repository_path):
            logs.append(f"⚠️ Diretório de repositório '{target_repository_path}' não encontrado no host.")
            return {
                "success": False,
                "target_path": target_repository_path,
                "blocks_scanned": 0,
                "corrupted_blocks_found": 0,
                "auto_healed_blocks": 0,
                "integrity_health_percent": 0.0,
                "parity_type": "SHA-256 Block Verification",
                "error": f"Caminho '{target_repository_path}' não existe no sistema de arquivos.",
                "timestamp": datetime.now().isoformat(),
                "logs": logs
            }

        target = Path(target_repository_path)
        blocks_scanned = 0
        corrupted_blocks = 0
        total_bytes = 0
        files_scanned = 0
        block_size = 64 * 1024  # 64 KB por bloco

        try:
            # Buscar arquivos reais no repositório
            candidate_files = []
            if target.is_file():
                candidate_files.append(target)
            else:
                for root, _, files in os.walk(target):
                    for f in files:
                        candidate_files.append(Path(root) / f)
                        if len(candidate_files) >= 50:
                            break
                    if len(candidate_files) >= 50:
                        break

            if not candidate_files:
                logs.append("Repositório vazio. Nenhum arquivo ou bloco encontrado para análise.")
                return {
                    "success": True,
                    "target_path": str(target),
                    "blocks_scanned": 0,
                    "corrupted_blocks_found": 0,
                    "auto_healed_blocks": 0,
                    "integrity_health_percent": None,
                    "parity_type": "SHA-256 por arquivo comparado com referência",
                    "timestamp": datetime.now().isoformat(),
                    "logs": logs
                }

            logs.append(f"Localizados {len(candidate_files)} arquivos para amostragem de integridade.")

            # Referencia por arquivo (tamanho, mtime, SHA-256) gravada na 1a varredura. Corrupcao silenciosa =
            # arquivo com mesmo tamanho e mtime (nao foi reescrito) mas conteudo/hash diferente.
            import json as _json
            from core.gboc_paths import data_dir as _gboc_data_dir
            base_dir = _gboc_data_dir("bitrot_baseline", create=False)
            base_dir.mkdir(parents=True, exist_ok=True)
            base_file = base_dir / (hashlib.sha1(str(target).lower().encode("utf-8")).hexdigest() + ".json")
            try:
                baseline = _json.loads(base_file.read_text(encoding="utf-8")) if base_file.exists() else {}
            except Exception:
                baseline = {}
            new_refs = changed = silent = 0
            bytes_cap = block_size * 5000

            for fpath in candidate_files:
                if total_bytes >= bytes_cap:
                    break
                key = str(fpath)
                try:
                    st = fpath.stat()
                    h = hashlib.sha256()
                    with open(fpath, "rb") as f:
                        while True:
                            chunk = f.read(block_size)
                            if not chunk:
                                break
                            h.update(chunk)
                            blocks_scanned += 1
                            total_bytes += len(chunk)
                    files_scanned += 1
                    digest = h.hexdigest()
                    ref = baseline.get(key)
                    if not ref:
                        new_refs += 1
                    elif ref.get("size") == st.st_size and ref.get("mtime") == int(st.st_mtime):
                        if ref.get("sha256") != digest:
                            silent += 1
                            corrupted_blocks += 1
                            logs.append(f"❌ Corrupção silenciosa: '{fpath.name}' mudou de conteúdo sem ser reescrito (tamanho e data iguais).")
                            continue  # mantem a referencia boa para nao mascarar o problema
                    else:
                        changed += 1
                    baseline[key] = {"size": st.st_size, "mtime": int(st.st_mtime), "sha256": digest}
                except OSError as io_err:
                    corrupted_blocks += 1
                    logs.append(f"⚠️ Erro de leitura física no arquivo '{fpath.name}': {io_err}")

            try:
                base_file.write_text(_json.dumps(baseline), encoding="utf-8")
            except Exception as e_b:
                logs.append(f"⚠️ Não foi possível gravar a referência de hashes: {e_b}")

            duration = round(time.time() - start_time, 2)
            total_mb = round(total_bytes / (1024 * 1024), 2)
            logs.append(f"Varredura concluída: {files_scanned} arquivo(s), {total_mb} MB lidos (amostra limitada a {len(candidate_files)} arquivo(s)).")
            if new_refs:
                logs.append(f"ℹ️ {new_refs} arquivo(s) verificados pela primeira vez: referência registrada; a comparação ocorre a partir da próxima varredura.")
            if changed:
                logs.append(f"ℹ️ {changed} arquivo(s) foram reescritos desde a última varredura (referência atualizada).")
            if corrupted_blocks == 0:
                compared = files_scanned - new_refs - changed
                logs.append(f"✅ Nenhuma corrupção encontrada: {compared} arquivo(s) comparados com a referência, sem erro de leitura." if compared
                            else "✅ Nenhum erro de leitura. Ainda não há arquivos comparáveis com a referência.")
            else:
                logs.append(f"⚠️ {corrupted_blocks} problema(s): {silent} corrupção(ões) silenciosa(s), {corrupted_blocks - silent} erro(s) de leitura.")

            health = None if files_scanned == 0 else round((1.0 - (corrupted_blocks / max(files_scanned, 1))) * 100.0, 1)

            return {
                "success": corrupted_blocks == 0,
                "target_path": str(target),
                "blocks_scanned": blocks_scanned,
                "files_scanned": files_scanned,
                "files_compared": files_scanned - new_refs - changed,
                "files_new_reference": new_refs,
                "corrupted_blocks_found": corrupted_blocks,
                "silent_corruptions": silent,
                "auto_healed_blocks": 0,
                "integrity_health_percent": health,
                "parity_type": "SHA-256 por arquivo comparado com referência",
                "bytes_scanned_mb": total_mb,
                "duration_seconds": duration,
                "timestamp": datetime.now().isoformat(),
                "logs": logs
            }

        except Exception as e:
            logger.error(f"Erro no scrub bitrot: {e}", exc_info=True)
            logs.append(f"❌ Erro durante a varredura: {e}")
            return {
                "success": False,
                "target_path": str(target),
                "blocks_scanned": blocks_scanned,
                "corrupted_blocks_found": corrupted_blocks,
                "auto_healed_blocks": 0,
                "integrity_health_percent": 0.0,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
                "logs": logs
            }


# Singleton global
bitrot_scrub_engine = BitrotScrubEngine()
