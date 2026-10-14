"""
GBOC Native — formato 4: armazenamento por conteúdo (deduplicado), em blocos e compactado.

Antes (formato 3): cada arquivo alterado virava um .zip dentro da pasta do snapshot e os inalterados apontavam
para o snapshot anterior em cadeia; todo backup lia e calculava o hash de TODOS os arquivos; envio um a um.

Agora:
  * objects/<aa>/<sha256>  — blocos de até 4 MiB identificados pelo hash do conteúdo. Um bloco igual (mesmo
    arquivo em outra pasta, outra tarefa, outro snapshot, trecho que não mudou de um arquivo grande) é enviado
    UMA vez só;
  * cada bloco é compactado (zstd quando disponível, senão zlib; LZMA2 opcional para arquivamento) e guardado sem
    compactar quando não vale a pena (zip, jpg, mp4, pst…). 1º byte do objeto = codec (R=sem, Z=zlib, S=zstd, L=LZMA2);
  * detecção rápida: arquivo com mesmo tamanho e data de modificação do backup anterior não é relido;
  * envio e download em paralelo (várias conexões) quando o repositório permite;
  * restauração confere o hash de cada bloco e do arquivo inteiro e devolve a data de modificação original.
  * <snapshot>/manifest.json (version 4): lista de arquivos → blocos; o histórico de versões vem dos manifestos.
  * pacotes (arquivos pequenos): blocos pequenos são agrupados em packs/<aa>/<id> (~8 MiB) em vez de um objeto
    por bloco. Na nuvem cada objeto custa uma requisição (100–200 ms de latência): milhares de arquivos pequenos
    viram dezenas de envios. index/<execução>.json diz em que pacote/posição está cada bloco; o fim de cada pacote
    também traz o próprio índice (recuperação se o index/ se perder). Repositórios só com objects/ continuam
    válidos: os dois formatos convivem.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import secrets
import shutil
import struct
import tempfile
import lzma
import threading
import zlib
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger("gboc.native.v4")

FORMAT = 4
CHUNK_SIZE = 4 * 1024 * 1024
OBJ_DIR = "objects"
PACK_DIR = "packs"
INDEX_DIR = "index"
PACK_TARGET_SIZE = 8 * 1024 * 1024       # pacote fechado e enviado ao atingir ~8 MiB
PACK_BLOB_MAX = 512 * 1024               # blocos (já compactados) até 512 KiB vão para pacote; maiores, objeto próprio
PACK_MAGIC = b"GBP1"                     # rodapé do pacote: <índice compactado><tamanho u32 LE><GBP1>
PACK_CACHE_SLOTS = 6                     # pacotes mantidos em memória na leitura (restauração/verificação)

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


def pack_name(pack_id: str) -> str:
    return f"{PACK_DIR}/{pack_id[:2]}/{pack_id}"


def build_pack(blobs: List[Tuple[str, bytes]]) -> Tuple[str, bytes, List[List[Any]]]:
    """Concatena os blocos e acrescenta o índice no rodapé. Retorna (id do pacote, conteúdo, [[hash, início, tamanho]])."""
    buf = io.BytesIO()
    entries: List[List[Any]] = []
    for h, blob in blobs:
        entries.append([h, buf.tell(), len(blob)])
        buf.write(blob)
    trailer = compress(json.dumps(entries, separators=(",", ":")).encode("utf-8"), "zlib")
    buf.write(trailer)
    buf.write(struct.pack("<I", len(trailer)))
    buf.write(PACK_MAGIC)
    data = buf.getvalue()
    return sha256_bytes(data), data, entries


def read_pack_trailer(data: bytes) -> List[List[Any]]:
    """Índice gravado no fim do pacote (para reconstruir o index/ se ele se perder)."""
    if len(data) < 8 or data[-4:] != PACK_MAGIC:
        raise ValueError("Pacote sem rodapé GBOC")
    (n,) = struct.unpack("<I", data[-8:-4])
    return json.loads(decompress(data[-8 - n:-8]).decode("utf-8"))


def _backend_put(be, remote: str, data: bytes) -> Dict[str, Any]:
    """Envio em memória quando o backend permite (nuvem); senão via arquivo temporário."""
    put = getattr(be, "put_bytes", None)
    if callable(put):
        return put(remote, data)
    fd, tmp = tempfile.mkstemp(prefix="gboc_obj_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return be.upload_file(tmp, remote)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _backend_get(be, remote: str) -> bytes:
    get = getattr(be, "get_bytes", None)
    if callable(get):
        return get(remote)
    fd, tmp = tempfile.mkstemp(prefix="gboc_obj_")
    os.close(fd)
    try:
        r = be.download_file(remote, tmp)
        if not r.get("success", False):
            raise RuntimeError(f"Objeto {remote} ausente no repositório")
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def load_index(backend, names: Optional[Iterable[str]] = None,
               existing_packs: Optional[Set[str]] = None) -> Tuple[Dict[str, Tuple[str, int, int]], Dict[str, Dict[str, Any]]]:
    """Lê index/*.json. Retorna ({hash: (pacote, início, tamanho)}, {arquivo de índice: conteúdo}).
    existing_packs: só aceita localizações em pacotes que existem (um bloco reenviado depois de perder o pacote
    aparece em dois índices: vale o pacote presente)."""
    if names is None:
        names = backend.list_files(sub_path=INDEX_DIR) or []
    files = sorted(n for n in (str(x).replace("\\", "/") for x in names) if n.startswith(INDEX_DIR + "/") and n.endswith(".json"))
    located: Dict[str, Tuple[str, int, int]] = {}
    docs: Dict[str, Dict[str, Any]] = {}
    for name in files:
        doc = json.loads(decompress(_backend_get(backend, name)).decode("utf-8"))
        docs[name] = doc
        for pid, entries in (doc.get("packs") or {}).items():
            if existing_packs is not None and pid not in existing_packs:
                continue
            for h, off, ln in entries:
                located.setdefault(h, (pid, int(off), int(ln)))
    return located, docs


def _encode_index(packs: Dict[str, List[List[Any]]]) -> bytes:
    return compress(json.dumps({"version": 1, "packs": packs}, separators=(",", ":")).encode("utf-8"), "zlib")


def resolve_codec(name: Optional[str]) -> str:
    """auto → zstd se instalado, senão zlib. Valores: zstd | zlib | lzma2 | none."""
    n = (name or "auto").lower()
    if n in ("none", "off", "store", "stored"):
        return "none"
    if n == "zstd":
        return "zstd" if _zstd else "zlib"
    # LZMA2 (mesmo algoritmo do 7-Zip/.xz; módulo lzma da biblioteca padrão). Antes "lzma" virava zlib sem aviso.
    if n in ("lzma2", "lzma", "xz", "7z"):
        return "lzma2"
    if n in ("zlib", "deflate", "bzip2"):
        return "zlib"
    return "zstd" if _zstd else "zlib"


def compress(data: bytes, codec: str, level: Optional[int] = None) -> bytes:
    if codec == "none" or len(data) < 64:
        return b"R" + data
    if codec == "zstd" and _zstd:
        out = b"S" + _zstd.ZstdCompressor(level=level or 6).compress(data)
    elif codec == "lzma2":
        # .xz com filtro LZMA2. Preset limitado a 7: acima disso o dicionário passa de 16 MiB (inútil para blocos
        # de 4 MiB) e cada thread chegaria a ~680 MiB de RAM no preset 9. CHECK_NONE: o bloco já é validado pelo SHA-256.
        preset = max(0, min(int(level if level is not None else 6), 7))
        out = b"L" + lzma.compress(data, format=lzma.FORMAT_XZ, check=lzma.CHECK_NONE,
                                   filters=[{"id": lzma.FILTER_LZMA2, "preset": preset}])
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
    if tag == b"L":
        return lzma.decompress(body, format=lzma.FORMAT_XZ)
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
    """Envio/download de blocos com paralelismo. backend_factory() cria uma conexão por thread (nuvem).

    Envio: submit() coloca o bloco numa fila global com no máximo ~2 envios por conexão em andamento (antes cada
    arquivo esperava o próprio envio terminar e, com arquivos pequenos, as conexões trabalhavam uma de cada vez).
    Blocos pequenos vão para pacotes. flush() envia o último pacote, espera tudo e grava o índice desta execução;
    o manifesto só pode ser gravado depois dele."""

    def __init__(self, backend, backend_factory: Optional[Callable[[], Any]] = None, workers: int = 1,
                 use_packs: bool = True):
        self.backend = backend
        self.factory = backend_factory
        self.workers = max(1, int(workers or 1)) if backend_factory else 1
        self.use_packs = use_packs
        self._local = threading.local()
        self._known: Optional[Set[str]] = None
        self._located: Dict[str, Tuple[str, int, int]] = {}      # bloco em pacote → (pacote, início, tamanho)
        self._pending: Set[str] = set()
        self._lock = threading.Lock()
        self._futures: Deque[Future] = deque()
        self._pack_blobs: List[Tuple[str, bytes]] = []
        self._pack_bytes = 0
        self._run_index: Dict[str, List[List[Any]]] = {}          # pacotes enviados nesta execução
        self._cache: "OrderedDict[str, bytes]" = OrderedDict()
        self._cache_locks: Dict[str, threading.Lock] = {}
        self.uploaded_bytes = 0
        self.uploaded_objects = 0
        self.packs_uploaded = 0

    def _be(self):
        if not self.factory or self.workers == 1:
            return self.backend
        be = getattr(self._local, "be", None)
        if be is None:
            be = self.factory()
            self._local.be = be
        return be

    def known(self, names: Optional[Iterable[str]] = None) -> Set[str]:
        """Blocos já guardados (objetos soltos + pacotes). names: listagem do repositório já feita (evita listar de novo)."""
        if self._known is None:
            names = list(names) if names is not None else None
            objs = [n for n in names if str(n).replace("\\", "/").startswith(OBJ_DIR + "/")] if names is not None \
                else (self.backend.list_files(sub_path=OBJ_DIR) or [])
            known = {str(n).replace("\\", "/").rsplit("/", 1)[-1] for n in objs}
            pack_names = [n for n in names if str(n).replace("\\", "/").startswith(PACK_DIR + "/")] if names is not None \
                else (self.backend.list_files(sub_path=PACK_DIR) or [])
            packs = {str(n).replace("\\", "/").rsplit("/", 1)[-1] for n in pack_names}
            # Pacote citado no índice mas ausente no repositório: os blocos dele NÃO contam como existentes —
            # o backup os envia de novo (em vez de deduplicar contra um bloco perdido) e a verificação acusa a falta.
            self._located, docs = load_index(self.backend, names, existing_packs=packs)
            lost = {pid for d in docs.values() for pid in (d.get("packs") or {}) if pid not in packs}
            if lost:
                logger.warning(f"{len(lost)} pacote(s) citado(s) no índice não existem no repositório: "
                               "os blocos afetados serão reenviados no próximo backup")
            known.update(self._located)
            self._known = known
        return self._known

    # ── envio ──────────────────────────────────────────────────────────────────────────────────────────────
    def _wait_window(self) -> None:
        # memória limitada: no máximo 2 envios por conexão aguardando; erro de envio aparece aqui
        while len(self._futures) > self.workers * 2:
            self._futures.popleft().result()

    def submit(self, pool: ThreadPoolExecutor, h: str, blob: bytes) -> None:
        if self.use_packs and len(blob) <= PACK_BLOB_MAX:
            sealed = None
            with self._lock:
                self._pack_blobs.append((h, blob))
                self._pack_bytes += len(blob)
                if self._pack_bytes >= PACK_TARGET_SIZE:
                    sealed, self._pack_blobs, self._pack_bytes = self._pack_blobs, [], 0
            if sealed:
                self._futures.append(pool.submit(self._put_pack, sealed))
        else:
            self._futures.append(pool.submit(self.put, h, blob))
        self._wait_window()

    def flush(self, pool: ThreadPoolExecutor) -> None:
        with self._lock:
            sealed, self._pack_blobs, self._pack_bytes = self._pack_blobs, [], 0
        if sealed:
            self._futures.append(pool.submit(self._put_pack, sealed))
        while self._futures:
            self._futures.popleft().result()
        if self._run_index:
            # índice desta execução: nome único (duas tarefas no mesmo repositório não se sobrescrevem)
            name = f"{INDEX_DIR}/{secrets.token_hex(8)}.json"
            r = _backend_put(self.backend, name, _encode_index(self._run_index))
            if not r.get("success", False):
                raise RuntimeError(f"Gravação do índice de pacotes falhou: {r.get('error') or r.get('message')}")
            self._run_index = {}

    def _put_pack(self, blobs: List[Tuple[str, bytes]]) -> None:
        pid, data, entries = build_pack(blobs)
        r = _backend_put(self._be(), pack_name(pid), data)
        if not r.get("success", False):
            raise RuntimeError(f"Envio do pacote {pid[:12]} falhou: {r.get('error') or r.get('message')}")
        with self._lock:
            self._run_index[pid] = entries
            for h, off, ln in entries:
                self._located[h] = (pid, off, ln)
                self._known.add(h)
                self._pending.discard(h)
            self.uploaded_bytes += len(data)
            self.uploaded_objects += 1
            self.packs_uploaded += 1

    def put(self, h: str, blob: bytes) -> None:
        with self._lock:
            if h in self.known():
                return
        r = _backend_put(self._be(), object_name(h), blob)
        if not r.get("success", False):
            raise RuntimeError(f"Envio do bloco {h[:12]} falhou: {r.get('error') or r.get('message')}")
        with self._lock:
            self._known.add(h)
            self._pending.discard(h)
            self.uploaded_bytes += len(blob)
            self.uploaded_objects += 1

    # ── leitura ────────────────────────────────────────────────────────────────────────────────────────────
    def _pack_data(self, pid: str) -> bytes:
        """Pacote inteiro com cache LRU: arquivos pequenos vizinhos saem do mesmo download."""
        with self._lock:
            data = self._cache.get(pid)
            if data is not None:
                self._cache.move_to_end(pid)
                return data
            plock = self._cache_locks.setdefault(pid, threading.Lock())
        with plock:                                   # duas threads no mesmo pacote: um download só
            with self._lock:
                data = self._cache.get(pid)
            if data is None:
                data = _backend_get(self._be(), pack_name(pid))
                if sha256_bytes(data) != pid:
                    raise RuntimeError(f"Pacote {pid[:12]} corrompido (hash não confere)")
                with self._lock:
                    self._cache[pid] = data
                    while len(self._cache) > max(PACK_CACHE_SLOTS, self.workers + 2):
                        self._cache.popitem(last=False)
        return data

    def get(self, h: str) -> bytes:
        self.known()
        loc = self._located.get(h)
        if loc:
            pid, off, ln = loc
            blob = self._pack_data(pid)[off:off + ln]
        else:
            try:
                blob = _backend_get(self._be(), object_name(h))
            except Exception as e:
                raise RuntimeError(f"Bloco {h[:12]} ausente no repositório") from e
        data = decompress(blob)
        if sha256_bytes(data) != h:
            raise RuntimeError(f"Bloco {h[:12]} corrompido (hash não confere)")
        return data

    def pool(self) -> ThreadPoolExecutor:
        return ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="gboc-native")


def store_file(store: ObjectStore, pool: ThreadPoolExecutor, path: str, codec: str,
               level: Optional[int] = None) -> Tuple[str, List[str], int, int]:
    """Lê o arquivo em blocos e enfileira os que ainda não existem (não espera o envio: ver ObjectStore.flush).
    Retorna (hash_arquivo, blocos, novos, bytes_novos)."""
    ext = os.path.splitext(path)[1].lower()
    c = "none" if ext in INCOMPRESSIBLE else codec
    fh = hashlib.sha256()
    chunks: List[str] = []
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
            store.submit(pool, h, blob)
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


def prune_packs(backend, referenced: Set[str]) -> Dict[str, int]:
    """Apaga pacotes em que NENHUM bloco é usado pelos snapshots restantes. O índice é regravado ANTES de apagar o
    pacote: se o processo cair no meio sobra só um pacote órfão (espaço), nunca um índice apontando para o vazio
    (o que faria um backup futuro deduplicar contra um bloco inexistente). Pacotes com parte em uso ficam inteiros."""
    _located, docs = load_index(backend)
    deleted = blocked = 0
    for name, doc in docs.items():
        packs = doc.get("packs") or {}
        dead = [pid for pid, entries in packs.items() if not any(e[0] in referenced for e in entries)]
        if not dead:
            continue
        alive = {pid: e for pid, e in packs.items() if pid not in dead}
        r = _backend_put(backend, name, _encode_index(alive)) if alive else backend.delete_file(name)
        if isinstance(r, dict) and not r.get("success", True):
            blocked += len(dead)
            continue
        for pid in dead:
            r = backend.delete_file(pack_name(pid))
            if isinstance(r, dict) and not r.get("success", True):
                blocked += 1
            else:
                deleted += 1
    return {"packs_deleted": deleted, "packs_blocked": blocked}
