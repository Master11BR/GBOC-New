"""
GBOC Native — formato 4: armazenamento por conteúdo (deduplicado), em blocos e compactado.

Antes (formato 3): cada arquivo alterado virava um .zip dentro da pasta do snapshot e os inalterados apontavam
para o snapshot anterior em cadeia; todo backup lia e calculava o hash de TODOS os arquivos; envio um a um.

Agora:
  * objects/<aa>/<sha256>  — blocos de até 4 MiB identificados pelo hash do conteúdo. Um bloco igual (mesmo
    arquivo em outra pasta, outra tarefa, outro snapshot, trecho que não mudou de um arquivo grande) é enviado
    UMA vez só;
  * cada bloco é compactado (zstd quando disponível, senão zlib) e guardado sem compactar quando não vale a pena
    (arquivos já compactados: zip, jpg, mp4, pst…). 1º byte do objeto = codec (R=sem, Z=zlib, S=zstd);
  * detecção rápida: arquivo com mesmo tamanho e data de modificação do backup anterior não é relido;
  * envio e download em paralelo (várias conexões) quando o repositório permite;
  * restauração confere o hash de cada bloco e do arquivo inteiro e devolve a data de modificação original.
  * <snapshot>/manifest.json (version 4): lista de arquivos → blocos; o histórico de versões vem dos manifestos.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import shutil
import tempfile
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger("gboc.native.v4")

FORMAT = 4
CHUNK_SIZE = 4 * 1024 * 1024
OBJ_DIR = "objects"

try:
    import zstandard as _zstd          # opcional (requirements.txt); sem ele usa zlib
except Exception:                        # pragma: no cover
    _zstd = None

# extensões que já vêm compactadas: comprimir de novo só gasta CPU
INCOMPRESSIBLE = {
    ".zip", ".7z", ".rar", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".lz4", ".cab", ".jpg", ".jpeg", ".png", ".gif",
    ".webp", ".heic", ".mp3", ".mp4", ".m4a", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".flac", ".ogg", ".pdf",
    ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".jar", ".apk", ".msi", ".iso", ".vhdx", ".bak.gz", ".pst",
}


def object_name(h: str) -> str:
    return f"{OBJ_DIR}/{h[:2]}/{h}"


def resolve_codec(name: Optional[str]) -> str:
    """auto → zstd se instalado, senão zlib. Valores: zstd | zlib | none."""
    n = (name or "auto").lower()
    if n in ("none", "off", "store", "stored"):
        return "none"
    if n == "zstd":
        return "zstd" if _zstd else "zlib"
    if n in ("zlib", "deflate", "lzma", "bzip2"):
        return "zlib"
    return "zstd" if _zstd else "zlib"


def compress(data: bytes, codec: str, level: Optional[int] = None) -> bytes:
    if codec == "none" or len(data) < 64:
        return b"R" + data
    if codec == "zstd" and _zstd:
        out = b"S" + _zstd.ZstdCompressor(level=level or 6).compress(data)
    else:
        out = b"Z" + zlib.compress(data, min(int(level or 6), 9))
    # não compensou (já compactado): guarda como está
    return out if len(out) < len(data) * 0.97 else b"R" + data


def decompress(blob: bytes) -> bytes:
    tag, body = blob[:1], blob[1:]
    if tag == b"R":
        return body
    if tag == b"Z":
        return zlib.decompress(body)
    if tag == b"S":
        if not _zstd:
            raise RuntimeError("Este backup usa compressão zstd: instale o pacote Python 'zstandard' no agente")
        return _zstd.ZstdDecompressor().decompress(body)
    raise ValueError("Objeto de backup com formato desconhecido")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def iter_chunks(path: str, size: int = CHUNK_SIZE) -> Iterable[bytes]:
    with open(path, "rb") as f:
        while True:
            b = f.read(size)
            if not b:
                break
            yield b


class ObjectStore:
    """Envio/download de blocos com paralelismo. backend_factory() cria uma conexão por thread (nuvem)."""

    def __init__(self, backend, backend_factory: Optional[Callable[[], Any]] = None, workers: int = 1):
        self.backend = backend
        self.factory = backend_factory
        self.workers = max(1, int(workers or 1)) if backend_factory else 1
        self._local = threading.local()
        self._known: Optional[Set[str]] = None
        self._pending: Set[str] = set()
        self._lock = threading.Lock()
        self.uploaded_bytes = 0
        self.uploaded_objects = 0

    def _be(self):
        if not self.factory or self.workers == 1:
            return self.backend
        be = getattr(self._local, "be", None)
        if be is None:
            be = self.factory()
            self._local.be = be
        return be

    def known(self) -> Set[str]:
        if self._known is None:
            names = self.backend.list_files(sub_path=OBJ_DIR) or []
            self._known = {str(n).replace("\\", "/").rsplit("/", 1)[-1] for n in names}
        return self._known

    def put(self, h: str, blob: bytes) -> None:
        with self._lock:
            if h in self.known():
                return
        fd, tmp = tempfile.mkstemp(prefix="gboc_obj_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
            r = self._be().upload_file(tmp, object_name(h))
            if not r.get("success", False):
                raise RuntimeError(f"Envio do bloco {h[:12]} falhou: {r.get('error') or r.get('message')}")
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        with self._lock:
            self._known.add(h)
            self._pending.discard(h)
            self.uploaded_bytes += len(blob)
            self.uploaded_objects += 1

    def get(self, h: str) -> bytes:
        fd, tmp = tempfile.mkstemp(prefix="gboc_obj_")
        os.close(fd)
        try:
            r = self._be().download_file(object_name(h), tmp)
            if not r.get("success", False):
                raise RuntimeError(f"Bloco {h[:12]} ausente no repositório")
            with open(tmp, "rb") as f:
                data = decompress(f.read())
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if sha256_bytes(data) != h:
            raise RuntimeError(f"Bloco {h[:12]} corrompido (hash não confere)")
        return data

    def pool(self) -> ThreadPoolExecutor:
        return ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="gboc-native")


def store_file(store: ObjectStore, pool: ThreadPoolExecutor, path: str, codec: str,
               level: Optional[int] = None) -> Tuple[str, List[str], int, int]:
    """Lê o arquivo em blocos, envia os que ainda não existem. Retorna (hash_arquivo, blocos, novos, bytes_novos)."""
    ext = os.path.splitext(path)[1].lower()
    c = "none" if ext in INCOMPRESSIBLE else codec
    fh = hashlib.sha256()
    chunks: List[str] = []
    futures = []
    new_count = new_bytes = 0
    for data in iter_chunks(path):
        fh.update(data)
        h = sha256_bytes(data)
        chunks.append(h)
        with store._lock:
            exists = h in store.known() or h in store._pending
            if not exists:
                store._pending.add(h)
        if not exists:
            blob = compress(data, c, level)
            new_count += 1
            new_bytes += len(blob)
            futures.append(pool.submit(store.put, h, blob))
            # memória limitada: no máximo 2 blocos por conexão aguardando envio
            while len(futures) > store.workers * 2:
                futures.pop(0).result()
    for f in futures:
        f.result()
    return fh.hexdigest(), chunks, new_count, new_bytes


def restore_entry(store: ObjectStore, entry: Dict[str, Any], dest_file: str, cache: Optional[Dict[str, bytes]] = None) -> None:
    os.makedirs(os.path.dirname(dest_file) or ".", exist_ok=True)
    tmp = dest_file + ".gboc-part"
    fh = hashlib.sha256()
    with open(tmp, "wb") as out:
        for h in entry.get("chunks") or []:
            data = cache.get(h) if cache is not None else None
            if data is None:
                data = store.get(h)
            fh.update(data)
            out.write(data)
    if entry.get("hash") and fh.hexdigest() != entry["hash"]:
        os.remove(tmp)
        raise RuntimeError(f"Arquivo {entry.get('path')} não confere com o backup (hash diferente)")
    os.replace(tmp, dest_file)
    if entry.get("mtime"):
        try:
            os.utime(dest_file, (entry["mtime"], entry["mtime"]))
        except OSError:
            pass


def referenced_objects(manifests: Iterable[Dict[str, Any]]) -> Set[str]:
    out: Set[str] = set()
    for m in manifests:
        for e in (m or {}).get("entries") or []:
            out.update(e.get("chunks") or [])
    return out
