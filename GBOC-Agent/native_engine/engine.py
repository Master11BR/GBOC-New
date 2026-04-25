#!/usr/bin/env python3
"""
GBOC Native Engine v3 - Motor proprietario de backup
Suporta: SHA-256 dedup, manifest JSON, compressao configuravel,
restauracao granular, browsing de arquivos via manifest.
Funciona com qualquer StorageBackend (local ou cloud).
"""

import os
import hashlib
import json
import zipfile
import tempfile
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

COMPRESSION_MAP = {
    'none': zipfile.ZIP_STORED,
    'deflate': zipfile.ZIP_DEFLATED,
    'bzip2': zipfile.ZIP_BZIP2,
    'lzma': zipfile.ZIP_LZMA,
}


class GBOCNativeEngine:
    """
    Motor proprietario GBOC v3.
    Usa StorageBackend para armazenamento (local ou cloud).
    Cada snapshot e um diretorio com timestamp contendo:
      - manifest.json: metadados completos (hashes, tamanhos, caminhos)
      - *.zip: arquivos compactados (apenas os que mudaram desde o ultimo backup)
    """

    def __init__(self, task_config: Dict[str, Any], storage_backend):
        self.task_config = task_config
        self.backend = storage_backend
        self.logger = logging.getLogger(self.__class__.__name__)
        self.compression = task_config.get('compression', 'deflate')
        self.zip_mode = COMPRESSION_MAP.get(self.compression, zipfile.ZIP_DEFLATED)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sha256(file_path: str) -> str:
        h = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def run_backup(self) -> Dict[str, Any]:
        """Executa backup incremental com deduplicacao SHA-256."""
        try:
            source_paths = self.task_config.get('source_paths') or self.task_config.get('sources', [])
            if isinstance(source_paths, str):
                source_paths = [p.strip() for p in source_paths.split(',') if p.strip()]

            if not source_paths:
                return {"success": False, "error": "Nenhum caminho de origem definido"}

            snapshot_id = datetime.now().strftime('%Y%m%d%H%M%S')
            self.logger.info(f"Iniciando backup nativo v3 - snapshot {snapshot_id}")

            previous_hashes = self._load_previous_hashes()

            manifest_entries = []
            files_processed = 0
            bytes_processed = 0
            files_new = 0
            files_unchanged = 0

            for source in source_paths:
                source = source.strip()
                if not os.path.exists(source):
                    self.logger.warning(f"Origem nao encontrada: {source}")
                    continue

                if os.path.isfile(source):
                    file_list = [source]
                    base_dir = os.path.dirname(source)
                else:
                    base_dir = source
                    file_list = []
                    for root, dirs, files in os.walk(source):
                        for fname in files:
                            file_list.append(os.path.join(root, fname))

                for fpath in file_list:
                    try:
                        result = self._process_file(
                            fpath, base_dir, snapshot_id, previous_hashes
                        )
                        if result:
                            manifest_entries.append(result['entry'])
                            files_processed += 1
                            bytes_processed += result['entry']['size']
                            if result['uploaded']:
                                files_new += 1
                            else:
                                files_unchanged += 1
                    except Exception as e:
                        self.logger.error(f"Erro ao processar {fpath}: {e}")

            manifest = {
                'version': 3,
                'snapshot_id': snapshot_id,
                'timestamp': datetime.now().isoformat(),
                'compression': self.compression,
                'files_total': files_processed,
                'files_new': files_new,
                'files_unchanged': files_unchanged,
                'bytes_total': bytes_processed,
                'source_paths': source_paths,
                'entries': manifest_entries,
            }

            manifest_path = self._upload_manifest(snapshot_id, manifest)
            self.logger.info(
                f"Backup nativo v3 concluido: {files_processed} arquivos "
                f"({files_new} novos, {files_unchanged} inalterados), "
                f"{bytes_processed} bytes"
            )

            return {
                "success": True,
                "snapshot_id": snapshot_id,
                "files": files_processed,
                "bytes": bytes_processed,
                "files_new": files_new,
                "files_unchanged": files_unchanged,
            }

        except Exception as e:
            self.logger.error(f"Erro no backup nativo v3: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _process_file(
        self, file_path: str, base_dir: str, snapshot_id: str,
        previous_hashes: Dict[str, str]
    ) -> Optional[Dict]:
        rel_path = os.path.relpath(file_path, base_dir)
        stat = os.stat(file_path)
        file_hash = self._sha256(file_path)
        size = stat.st_size

        entry = {
            'path': rel_path,
            'hash': file_hash,
            'size': size,
            'mtime': stat.st_mtime,
        }

        if previous_hashes.get(rel_path) == file_hash:
            entry['ref_snapshot'] = previous_hashes.get('__snapshot_id__', '')
            return {'entry': entry, 'uploaded': False}

        zip_name = rel_path.replace('\\', '/').replace('/', '__') + '.zip'
        remote_name = f"{snapshot_id}/{zip_name}"

        tmp_dir = tempfile.mkdtemp(prefix='gboc_native_')
        try:
            tmp_zip = os.path.join(tmp_dir, zip_name)
            with zipfile.ZipFile(tmp_zip, 'w', self.zip_mode) as zf:
                zf.write(file_path, rel_path)

            result = self.backend.upload_file(tmp_zip, remote_name)
            if not result.get('success', False):
                raise RuntimeError(f"Upload falhou: {result.get('error', 'desconhecido')}")

            entry['archive'] = remote_name
            return {'entry': entry, 'uploaded': True}
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _load_previous_hashes(self) -> Dict[str, str]:
        try:
            all_files = self.backend.list_files()
            manifests = [f for f in all_files if f.endswith('/manifest.json')]
            if not manifests:
                return {}

            manifests.sort(reverse=True)
            latest = manifests[0]

            tmp_dir = tempfile.mkdtemp(prefix='gboc_manifest_')
            try:
                local_manifest = os.path.join(tmp_dir, 'manifest.json')
                dl = self.backend.download_file(latest, local_manifest)
                if not dl.get('success', False):
                    return {}

                with open(local_manifest, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)

                snapshot_id = manifest.get('snapshot_id', '')
                hashes = {'__snapshot_id__': snapshot_id}
                for entry in manifest.get('entries', []):
                    hashes[entry['path']] = entry['hash']
                return hashes
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        except Exception as e:
            self.logger.warning(f"Nao foi possivel carregar hashes anteriores: {e}")
            return {}

    def _upload_manifest(self, snapshot_id: str, manifest: Dict) -> str:
        tmp_dir = tempfile.mkdtemp(prefix='gboc_manifest_')
        try:
            manifest_path = os.path.join(tmp_dir, 'manifest.json')
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

            remote_name = f"{snapshot_id}/manifest.json"
            result = self.backend.upload_file(manifest_path, remote_name)
            if not result.get('success', False):
                raise RuntimeError(f"Upload do manifest falhou: {result.get('error')}")
            return remote_name
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Snapshots / File listing
    # ------------------------------------------------------------------

    def list_snapshots(self) -> List[Dict[str, Any]]:
        all_files = self.backend.list_files()
        manifests = [f for f in all_files if f.endswith('/manifest.json')]

        snapshots = []
        for mf in manifests:
            sid = mf.split('/')[0]
            manifest = self._load_manifest(sid)
            if manifest:
                snapshots.append({
                    'id': sid,
                    'full_id': sid,
                    'time': manifest.get('timestamp', ''),
                    'files_total': manifest.get('files_total', 0),
                    'bytes_total': manifest.get('bytes_total', 0),
                    'engine': 'gboc_native',
                    'version': manifest.get('version', 1),
                })

        return sorted(snapshots, key=lambda x: x['id'], reverse=True)

    def list_files(self, snapshot_id: str, path: str = '/') -> List[Dict[str, Any]]:
        manifest = self._load_manifest(snapshot_id)
        if not manifest:
            return []

        path = path.strip('/').replace('\\', '/')
        entries = manifest.get('entries', [])

        dirs_seen = set()
        result = []

        for entry in entries:
            entry_path = entry['path'].replace('\\', '/')

            if path:
                if not entry_path.startswith(path + '/') and entry_path != path:
                    continue
                remainder = entry_path[len(path):].lstrip('/')
            else:
                remainder = entry_path

            parts = remainder.split('/')
            if len(parts) == 1:
                result.append({
                    'name': parts[0],
                    'path': '/' + entry_path,
                    'type': 'file',
                    'size': entry.get('size', 0),
                    'hash': entry.get('hash', ''),
                })
            else:
                dir_name = parts[0]
                if dir_name not in dirs_seen:
                    dirs_seen.add(dir_name)
                    dir_full = (path + '/' + dir_name) if path else dir_name
                    result.append({
                        'name': dir_name,
                        'path': '/' + dir_full,
                        'type': 'dir',
                        'size': 0,
                    })

        result.sort(key=lambda x: (x['type'] != 'dir', x['name'].lower()))
        return result

    def _load_manifest(self, snapshot_id: str) -> Optional[Dict]:
        try:
            tmp_dir = tempfile.mkdtemp(prefix='gboc_manifest_')
            try:
                local_path = os.path.join(tmp_dir, 'manifest.json')
                remote_name = f"{snapshot_id}/manifest.json"
                dl = self.backend.download_file(remote_name, local_path)
                if not dl.get('success', False):
                    return None
                with open(local_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception as e:
            self.logger.error(f"Erro ao carregar manifest {snapshot_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def run_restore(self, restore_config: Dict[str, Any]) -> Dict[str, Any]:
        try:
            snapshot_id = restore_config.get('snapshot_id')
            dest = restore_config.get('destination_path')
            selected_files = restore_config.get('files', [])

            if not snapshot_id or not dest:
                return {"success": False, "error": "snapshot_id e destination_path sao obrigatorios"}

            os.makedirs(dest, exist_ok=True)

            manifest = self._load_manifest(snapshot_id)
            if not manifest:
                self.logger.info(f"Manifest nao encontrado para {snapshot_id}, tentando restauracao legada")
                return self._restore_legacy(snapshot_id, dest)

            entries = manifest.get('entries', [])
            if selected_files:
                entries = [e for e in entries if e['path'] in selected_files]

            restored = 0
            errors = 0

            for entry in entries:
                try:
                    archive = entry.get('archive')
                    ref_snapshot = entry.get('ref_snapshot')
                    rel_path = entry['path']

                    if archive:
                        ok = self._restore_from_archive(archive, rel_path, dest)
                    elif ref_snapshot:
                        ok = self._find_and_restore_file(
                            rel_path, entry['hash'], ref_snapshot, dest
                        )
                    else:
                        self.logger.warning(f"Sem fonte para restaurar: {rel_path}")
                        ok = False

                    if ok:
                        restored += 1
                    else:
                        errors += 1
                except Exception as e:
                    self.logger.error(f"Erro ao restaurar {entry.get('path')}: {e}")
                    errors += 1

            return {
                "success": errors == 0,
                "restored": restored,
                "errors": errors,
                "destination": dest,
            }
        except Exception as e:
            self.logger.error(f"Erro na restauracao nativa v3: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _restore_from_archive(self, archive: str, rel_path: str, dest: str) -> bool:
        tmp_dir = tempfile.mkdtemp(prefix='gboc_restore_')
        try:
            local_zip = os.path.join(tmp_dir, 'archive.zip')
            dl = self.backend.download_file(archive, local_zip)
            if not dl.get('success', False):
                return False

            with zipfile.ZipFile(local_zip, 'r') as zf:
                zf.extract(rel_path, dest)
            return True
        except Exception as e:
            self.logger.error(f"Erro ao extrair {archive}: {e}")
            return False
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _find_and_restore_file(
        self, rel_path: str, file_hash: str, ref_snapshot: str, dest: str
    ) -> bool:
        visited = set()
        current_snapshot = ref_snapshot

        while current_snapshot and current_snapshot not in visited:
            visited.add(current_snapshot)
            manifest = self._load_manifest(current_snapshot)
            if not manifest:
                break

            for entry in manifest.get('entries', []):
                if entry['path'] == rel_path and entry.get('hash') == file_hash:
                    if entry.get('archive'):
                        return self._restore_from_archive(entry['archive'], rel_path, dest)
                    elif entry.get('ref_snapshot'):
                        current_snapshot = entry['ref_snapshot']
                        break
            else:
                break

        self.logger.error(f"Nao foi possivel encontrar arquivo {rel_path} (hash={file_hash})")
        return False

    def _restore_legacy(self, snapshot_id: str, dest: str) -> Dict[str, Any]:
        try:
            files = self.backend.list_files(sub_path=snapshot_id)
            zip_files = [f for f in files if f.endswith('.zip')]

            if not zip_files:
                return {"success": False, "error": f"Nenhum arquivo encontrado no snapshot {snapshot_id}"}

            restored = 0
            for remote in zip_files:
                tmp_dir = tempfile.mkdtemp(prefix='gboc_legacy_')
                try:
                    local_zip = os.path.join(tmp_dir, 'archive.zip')
                    dl = self.backend.download_file(remote, local_zip)
                    if not dl.get('success', False):
                        continue
                    with zipfile.ZipFile(local_zip, 'r') as zf:
                        zf.extractall(dest)
                    restored += 1
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)

            return {"success": restored > 0, "restored": restored, "destination": dest}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Repository management
    # ------------------------------------------------------------------

    def check_repository(self) -> Dict[str, Any]:
        return self.backend.check_connection()

    def prune_repository(self, keep_last: int = 5) -> Dict[str, Any]:
        try:
            all_files = self.backend.list_files()
            manifests = sorted(
                [f for f in all_files if f.endswith('/manifest.json')]
            )

            if len(manifests) <= keep_last:
                return {
                    "success": True,
                    "pruned": 0,
                    "remaining": len(manifests),
                    "message": "Nada a limpar",
                }

            to_delete = manifests[:-keep_last]
            deleted_snapshots = 0

            for mf in to_delete:
                sid = mf.split('/')[0]
                snapshot_files = [f for f in all_files if f.startswith(f"{sid}/")]
                for sf in snapshot_files:
                    self.backend.delete_file(sf)
                deleted_snapshots += 1

            return {
                "success": True,
                "pruned": deleted_snapshots,
                "remaining": len(manifests) - deleted_snapshots,
            }
        except Exception as e:
            self.logger.error(f"Erro ao fazer prune: {e}", exc_info=True)
            return {"success": False, "error": str(e)}