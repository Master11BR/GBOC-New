import logging
from typing import Dict, Any, List, Optional

from .base import StorageBackend

# Try to import libcloud, handle gracefully if not available
try:
    from libcloud.storage.types import Provider, ContainerDoesNotExistError
    from libcloud.storage.providers import get_driver
    LIBCLOUD_AVAILABLE = True
except ImportError:
    LIBCLOUD_AVAILABLE = False

logger = logging.getLogger(__name__)

if not LIBCLOUD_AVAILABLE:
    logger.warning("⚠️ Apache Libcloud não está instalado. Funcionalidades de nuvem estarão limitadas.")
    logger.warning("Para instalar: pip install apache-libcloud")

def s3_addressing_style(cfg: Dict[str, Any], endpoint: Optional[str]) -> str:
    """Endpoint próprio (MinIO, Ceph, Garage, SeaweedFS...): por caminho, aceito por todos eles.
    AWS/Wasabi: automático. 'path_style': false no repositório força o estilo virtual-host."""
    if cfg.get('path_style') is False:
        return 'virtual'
    ep = str(endpoint or '').lower()
    return 'path' if ep and 'amazonaws.com' not in ep and 'wasabisys.com' not in ep else 'auto'


def _is_s3_compatible(config: Optional[Dict[str, Any]]) -> bool:
    """Usa boto3: tipo s3 com endpoint próprio (MinIO, Ceph RGW, SeaweedFS, Garage, RustFS...) e Wasabi.
    Wasabi pela Libcloud assinava sempre com a região us-east-1: fora dela (ex.: eu-central-2) toda requisição
    falhava com SignatureDoesNotMatch."""
    cfg = config or {}
    rtype = str(cfg.get('type') or '').lower()
    if rtype == 'wasabi':
        return True
    endpoint = str(cfg.get('endpoint') or '').strip().lower()
    return rtype == 's3' and bool(endpoint) and 'amazonaws.com' not in endpoint


def s3_region(cfg: Dict[str, Any]) -> str:
    """Região da assinatura AWS4. Endpoint s3.<região>.wasabisys.com manda: a requisição vai para ele, então a
    assinatura tem de usar a mesma região (um campo região divergente gerava SignatureDoesNotMatch)."""
    import re
    m = re.search(r's3\.([a-z0-9-]+)\.wasabisys\.com', str(cfg.get('endpoint') or '').lower())
    if m:
        return m.group(1)
    return str(cfg.get('region') or '').strip() or 'us-east-1'


class CloudStorageBackend(StorageBackend):
    def __new__(cls, config: Optional[Dict[str, Any]] = None, *args, **kwargs):
        # S3 compatível com endpoint próprio usa boto3 (S3CompatibleBackend). Pela Libcloud o endpoint era
        # ignorado (ia para a AWS) e servidores sem o namespace XML da AWS quebravam a listagem.
        if cls is CloudStorageBackend and _is_s3_compatible(config):
            return super().__new__(S3CompatibleBackend)
        return super().__new__(cls)

    """
    Backend de armazenamento para provedores de nuvem usando Apache Libcloud.
    Suporta provedores compatíveis com S3 (AWS S3, Wasabi) e Backblaze B2.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.driver = self._get_driver()
        # logger.info(f"Driver da nuvem inicializado: {self.driver}")
        self.container_name = self.config.get('bucket') or self.config.get('path')
        self.container = None

    def _get_driver(self):
        """
        Instancia e retorna o driver Libcloud correto com base na configuração.
        """
        if not LIBCLOUD_AVAILABLE:
            raise ImportError("Apache Libcloud não está instalado. Instale com: pip install apache-libcloud")
        
        repo_type = self.config.get('type', '').lower()
        access_key = self.config.get('access_key') or self.config.get('aws_access_key') or self.config.get('b2_account_id')
        secret_key = self.config.get('secret_key') or self.config.get('aws_secret_key') or self.config.get('b2_account_key')
        
        if not access_key or not secret_key:
            raise ValueError("Credenciais de nuvem (access_key/secret_key) não fornecidas.")

        if repo_type == 's3':
            driver_cls = get_driver(Provider.S3)
            return driver_cls(access_key, secret_key, region=self.config.get('region', 'us-east-1'))
        
        elif repo_type == 'wasabi':
            # Wasabi é compatível com S3, mas precisa de um endpoint customizado.
            # NÃO passar region ao driver — libcloud só reconhece regiões AWS.
            driver_cls = get_driver(Provider.S3)
            region = self.config.get('region', 'us-east-1')
            endpoint = self.config.get('endpoint') or f"s3.{region}.wasabisys.com"
            return driver_cls(
                access_key, 
                secret_key, 
                host=endpoint
            )

        elif repo_type == 'b2':
            driver_cls = get_driver(Provider.BACKBLAZE_B2)
            return driver_cls(access_key, secret_key)

        elif repo_type == 'azure':
            # Azure Blob Storage
            driver_cls = get_driver(Provider.AZURE_BLOBS)
            return driver_cls(access_key, secret_key)

        elif repo_type == 'gcs':
            # Google Cloud Storage
            driver_cls = get_driver(Provider.GOOGLE_STORAGE)
            return driver_cls(access_key, secret_key)

        else:
            raise ValueError(f"Tipo de repositório em nuvem não suportado pela Libcloud: {repo_type}")

    def check_connection(self) -> Dict[str, Any]:
        """
        Verifica a conexão tentando listar os contêineres/buckets.
        Também verifica se o bucket especificado existe.
        
        Returns:
            Dict com {"success": bool, "message": str, "error": str}
        """
        try:
            if not LIBCLOUD_AVAILABLE:
                return {
                    "success": False,
                    "message": "Libcloud não disponível",
                    "error": "libcloud_not_installed"
                }
            
            self.logger.info(f"Verificando conexão com {self.config.get('type')} bucket '{self.container_name}'...")
            
            # Tenta obter o contêiner (bucket)
            self.container = self.driver.get_container(container_name=self.container_name)
            self.logger.info(f"✅ Conexão bem-sucedida. Bucket encontrado.")
            
            return {"success": True, "message": f"Conectado ao bucket '{self.container_name}'"}
            
        except ContainerDoesNotExistError:
            error_msg = f"Bucket '{self.container_name}' não existe."
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": "bucket_not_found"}
            
        except Exception as e:
            error_msg = f"Falha ao conectar com nuvem: {e}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "message": error_msg, "error": "connection_failed"}

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """
        Lista objetos no bucket que podem ser snapshots.
        
        Returns:
            Lista de objetos encontrados
        """
        try:
            if not self.container:
                self.container = self.driver.get_container(container_name=self.container_name)
            
            snapshots = []
            objects = self.container.list_objects()
            
            for obj in objects:
                snapshots.append({
                    'id': obj.name,
                    'name': obj.name,
                    'size': obj.size or 0,
                    'date': getattr(obj, 'extra', {}).get('last-modified', 'unknown')
                })
            
            return sorted(snapshots, key=lambda x: x['date'], reverse=True)
            
        except Exception as e:
            self.logger.error(f"Erro ao listar snapshots: {e}")
            return []

    def test_credentials(self) -> bool:
        """
        Testa se as credenciais são válidas.
        
        Returns:
            True se credenciais OK
        """
        result = self.check_connection()
        return result.get('success', False)

    def upload_file(self, local_path: str, remote_name: str) -> Dict[str, Any]:
        """
        Faz o upload de um arquivo para o bucket na nuvem.

        Args:
            local_path: Caminho do arquivo local
            remote_name: Nome no bucket

        Returns:
            Dict com status
        """
        # Bucket com Object Lock (backup imutável): envio com Content-MD5 em cada requisição, exigido pelo S3/Wasabi
        if self.config.get('object_lock') and str(self.config.get('type', '')).lower() in ('s3', 'wasabi'):
            return self._upload_md5(local_path, remote_name)
        try:
            if not self.container:
                self.container = self.driver.get_container(container_name=self.container_name)

            with open(local_path, 'rb') as f:
                # Limite de banda de upload (janela/horário do agente ou política central)
                limit = float(getattr(self, 'upload_limit_bps', 0) or 0)
                if limit > 0:
                    from engines.operation_settings import ThrottledReader
                    stream = iter(ThrottledReader(f, limit))
                else:
                    stream = f
                obj = self.driver.upload_object_via_stream(
                    iterator=stream,
                    container=self.container,
                    object_name=remote_name
                )

            return {"success": True, "message": f"Arquivo enviado como {remote_name}"}

        except Exception as e:
            error_msg = f"Falha ao fazer upload: {e}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": "upload_failed"}

    PART_SIZE = 64 * 1024 * 1024

    def _s3_client(self):
        import boto3
        cfg = self.config
        region = s3_region(cfg)
        endpoint = cfg.get('endpoint') or (f"s3.{region}.wasabisys.com" if str(cfg.get('type')).lower() == 'wasabi' else None)
        if endpoint and not endpoint.startswith('http'):
            endpoint = 'https://' + endpoint
        from botocore.config import Config
        return boto3.client('s3', aws_access_key_id=cfg.get('access_key') or cfg.get('aws_access_key'),
                            aws_secret_access_key=cfg.get('secret_key') or cfg.get('aws_secret_key'),
                            region_name=region, endpoint_url=endpoint,
                            config=Config(s3={'addressing_style': s3_addressing_style(cfg, endpoint)},
                                          retries={'max_attempts': 5, 'mode': 'standard'},
                                          connect_timeout=15, read_timeout=120))

    def _upload_md5(self, local_path: str, remote_name: str) -> Dict[str, Any]:
        """Upload com Content-MD5 (objeto único até 64 MB; acima, multipart com MD5 por parte)."""
        import base64
        import hashlib
        import os
        import time
        md5b64 = lambda b: base64.b64encode(hashlib.md5(b).digest()).decode('ascii')
        limit = float(getattr(self, 'upload_limit_bps', 0) or 0)
        t0, sent = time.monotonic(), 0

        def throttle(n):
            nonlocal sent
            sent += n
            if limit > 0:
                wait = sent / limit - (time.monotonic() - t0)
                if wait > 0:
                    time.sleep(wait)
        try:
            s3 = self._s3_client()
            bucket = self.container_name
            size = os.path.getsize(local_path)
            with open(local_path, 'rb') as f:
                if size <= self.PART_SIZE:
                    data = f.read()
                    throttle(len(data))
                    s3.put_object(Bucket=bucket, Key=remote_name, Body=data, ContentMD5=md5b64(data))
                else:
                    up = s3.create_multipart_upload(Bucket=bucket, Key=remote_name)
                    parts = []
                    try:
                        n = 1
                        while True:
                            chunk = f.read(self.PART_SIZE)
                            if not chunk:
                                break
                            throttle(len(chunk))
                            r = s3.upload_part(Bucket=bucket, Key=remote_name, UploadId=up['UploadId'], PartNumber=n,
                                               Body=chunk, ContentMD5=md5b64(chunk))
                            parts.append({'ETag': r['ETag'], 'PartNumber': n})
                            n += 1
                        s3.complete_multipart_upload(Bucket=bucket, Key=remote_name, UploadId=up['UploadId'],
                                                     MultipartUpload={'Parts': parts})
                    except Exception:
                        s3.abort_multipart_upload(Bucket=bucket, Key=remote_name, UploadId=up['UploadId'])
                        raise
            return {"success": True, "message": f"Arquivo enviado como {remote_name} (Object Lock)"}
        except Exception as e:
            error_msg = f"Falha ao fazer upload (Object Lock): {e}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": "upload_failed"}

    def download_file(self, remote_name: str, local_path: str) -> Dict[str, Any]:
        """
        Baixa um arquivo do bucket na nuvem para o disco local.

        Args:
            remote_name: Nome do objeto no bucket
            local_path: Caminho local de destino

        Returns:
            Dict com status
        """
        try:
            if not self.container:
                self.container = self.driver.get_container(container_name=self.container_name)

            import os
            os.makedirs(os.path.dirname(local_path) or '.', exist_ok=True)

            obj = self.container.get_object(remote_name)
            self.driver.download_object(obj, local_path, overwrite_existing=True)

            return {"success": True, "message": f"Arquivo baixado: {remote_name}"}

        except Exception as e:
            error_msg = f"Falha ao baixar arquivo '{remote_name}': {e}"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}

    def list_files(self, sub_path: Optional[str] = None) -> List[str]:
        """
        Lista objetos no bucket, opcionalmente filtrados por prefixo.

        Args:
            sub_path: Prefixo para filtrar objetos (ex: snapshot_id)

        Returns:
            Lista de nomes de objetos
        """
        try:
            if not self.container:
                self.container = self.driver.get_container(container_name=self.container_name)

            prefix = f"{sub_path}/" if sub_path else None
            # Filtro no servidor (antes listava o bucket inteiro e filtrava aqui: lento com muitos objetos)
            objects = self.container.list_objects(prefix=prefix) if prefix else self.container.list_objects()

            files = []
            for obj in objects:
                name = obj.name
                if prefix and not name.startswith(prefix):
                    continue
                files.append(name)

            return files

        except Exception as e:
            self.logger.error(f"Falha ao listar arquivos: {e}")
            return []

    def delete_file(self, remote_name: str) -> Dict[str, Any]:
        """
        Deleta um objeto do bucket na nuvem.

        Args:
            remote_name: Nome do objeto a deletar

        Returns:
            Dict com status
        """
        try:
            if not self.container:
                self.container = self.driver.get_container(container_name=self.container_name)

            obj = self.container.get_object(remote_name)
            self.driver.delete_object(obj)

            return {"success": True, "message": f"Arquivo deletado: {remote_name}"}

        except Exception as e:
            error_msg = f"Falha ao deletar '{remote_name}': {e}"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}

    def get_object_size(self, remote_name: str) -> int:
        """
        Obtém o tamanho de um objeto no bucket.

        Args:
            remote_name: Nome do objeto

        Returns:
            Tamanho em bytes, 0 se não encontrado
        """
        try:
            if not self.container:
                self.container = self.driver.get_container(container_name=self.container_name)

            obj = self.container.get_object(remote_name)
            return obj.size or 0

        except Exception as e:
            self.logger.debug(f"Não foi possível obter tamanho de '{remote_name}': {e}")
            return 0

    # ── Envio/leitura direto em memória (motor nativo: pacotes e leitura parcial, sem arquivo temporário) ──

    def _throttle(self, nbytes: int) -> None:
        """Limite de banda de upload (upload_limit_bps) para envios em memória."""
        import time
        limit = float(getattr(self, 'upload_limit_bps', 0) or 0)
        if limit <= 0:
            return
        if not hasattr(self, '_tb_t0'):
            self._tb_t0, self._tb_sent = time.monotonic(), 0
        self._tb_sent += nbytes
        wait = self._tb_sent / limit - (time.monotonic() - self._tb_t0)
        if wait > 0:
            time.sleep(wait)

    def put_bytes(self, remote_name: str, data: bytes) -> Dict[str, Any]:
        if self.config.get('object_lock') and str(self.config.get('type', '')).lower() in ('s3', 'wasabi'):
            return self._put_bytes_md5(remote_name, data)
        try:
            if not self.container:
                self.container = self.driver.get_container(container_name=self.container_name)
            self._throttle(len(data))
            self.driver.upload_object_via_stream(iterator=iter([data]), container=self.container, object_name=remote_name)
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Falha ao enviar '{remote_name}': {e}")
            return {"success": False, "error": str(e)}

    def _put_bytes_md5(self, remote_name: str, data: bytes) -> Dict[str, Any]:
        """PUT com Content-MD5 (exigido em bucket com Object Lock). Objetos do motor nativo ficam bem abaixo de 64 MB."""
        import base64
        import hashlib
        try:
            self._throttle(len(data))
            self._s3_client().put_object(Bucket=self.container_name, Key=remote_name, Body=data,
                                         ContentMD5=base64.b64encode(hashlib.md5(data).digest()).decode('ascii'))
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Falha ao enviar '{remote_name}' (Object Lock): {e}")
            return {"success": False, "error": str(e)}

    def get_bytes(self, remote_name: str, start: int = 0, length: Optional[int] = None) -> bytes:
        """Lê o objeto inteiro ou um trecho (Range). Exceção se não existir."""
        if not self.container:
            self.container = self.driver.get_container(container_name=self.container_name)
        obj = self.container.get_object(remote_name)
        end = None if length is None else start + length       # libcloud: fim exclusivo
        if start or end is not None:
            stream = self.driver.download_object_range_as_stream(obj, start_bytes=start, end_bytes=end)
        else:
            stream = self.driver.download_object_as_stream(obj)
        return b"".join(stream)


class S3CompatibleBackend(CloudStorageBackend):
    """Wasabi e armazenamento S3 compatível com endpoint próprio via boto3: http ou https, porta, endereçamento por
    caminho (path-style), prefixo dentro do bucket e Object Lock (Content-MD5 em cada envio)."""

    def __init__(self, config: Dict[str, Any]):
        StorageBackend.__init__(self, config)
        bucket = str(config.get('bucket') or config.get('path') or '').replace('s3:', '').strip('/')
        prefix = str(config.get('prefix') or '').strip('/')
        if '/' in bucket:                                    # "bucket/pasta"
            bucket, rest = bucket.split('/', 1)
            prefix = '/'.join(p for p in (rest.strip('/'), prefix) if p)
        if not bucket:
            raise ValueError("Bucket não informado no repositório S3 compatível")
        if not (config.get('access_key') or config.get('aws_access_key')) or \
                not (config.get('secret_key') or config.get('aws_secret_key')):
            raise ValueError("Credenciais de nuvem (access_key/secret_key) não fornecidas.")
        self.container_name = bucket
        # Wasabi: sem prefixo, como a Libcloud gravava — repositórios Wasabi existentes continuam no mesmo lugar
        if str(config.get('type') or '').lower() == 'wasabi':
            prefix = ''
        self.key_prefix = prefix + '/' if prefix else ''
        self.container = None
        self.driver = None
        self._client = None

    def _c(self):
        if self._client is None:
            self._client = self._s3_client()
        return self._client

    def _key(self, name: str) -> str:
        return self.key_prefix + str(name).replace('\\', '/').lstrip('/')

    def _is_missing(self, e: Exception) -> bool:
        code = str(getattr(e, 'response', {}).get('Error', {}).get('Code', ''))
        return code in ('404', 'NoSuchKey', 'NotFound', 'NoSuchBucket')

    def check_connection(self) -> Dict[str, Any]:
        try:
            self._c().head_bucket(Bucket=self.container_name)
            return {"success": True, "message": f"Conectado ao bucket '{self.container_name}'"}
        except Exception as e:
            if self._is_missing(e):
                return {"success": False, "message": f"Bucket '{self.container_name}' não existe.", "error": "bucket_not_found"}
            self.logger.error(f"Falha ao conectar com S3 compatível: {e}")
            return {"success": False, "message": f"Falha ao conectar com nuvem: {e}", "error": "connection_failed"}

    def test_credentials(self) -> bool:
        return bool(self.check_connection().get('success'))

    def _iter_objects(self, sub_path: Optional[str] = None):
        prefix = self._key(f"{sub_path}/" if sub_path else '')
        for page in self._c().get_paginator('list_objects_v2').paginate(Bucket=self.container_name, Prefix=prefix):
            for o in page.get('Contents') or []:
                yield o

    def list_files(self, sub_path: Optional[str] = None) -> List[str]:
        try:
            n = len(self.key_prefix)
            return [o['Key'][n:] for o in self._iter_objects(sub_path)]
        except Exception as e:
            self.logger.error(f"Falha ao listar arquivos: {e}")
            return []

    def list_snapshots(self) -> List[Dict[str, Any]]:
        try:
            n = len(self.key_prefix)
            out = [{'id': o['Key'][n:], 'name': o['Key'][n:], 'size': o.get('Size') or 0,
                    'date': o['LastModified'].isoformat() if o.get('LastModified') else 'unknown'}
                   for o in self._iter_objects()]
            return sorted(out, key=lambda x: x['date'], reverse=True)
        except Exception as e:
            self.logger.error(f"Erro ao listar snapshots: {e}")
            return []

    def upload_file(self, local_path: str, remote_name: str) -> Dict[str, Any]:
        # Content-MD5 em todo envio: obrigatório com Object Lock e uma checagem de integridade a mais sem ele
        return self._upload_md5(local_path, self._key(remote_name))

    def put_bytes(self, remote_name: str, data: bytes) -> Dict[str, Any]:
        return self._put_bytes_md5(self._key(remote_name), data)

    def _put_bytes_md5(self, key: str, data: bytes) -> Dict[str, Any]:
        import base64
        import hashlib
        try:
            self._throttle(len(data))
            self._c().put_object(Bucket=self.container_name, Key=key, Body=data,
                                 ContentMD5=base64.b64encode(hashlib.md5(data).digest()).decode('ascii'))
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Falha ao enviar '{key}': {e}")
            return {"success": False, "error": str(e)}

    def get_bytes(self, remote_name: str, start: int = 0, length: Optional[int] = None) -> bytes:
        kw = {}
        if start or length is not None:
            kw['Range'] = f"bytes={start}-" + ("" if length is None else str(start + length - 1))
        return self._c().get_object(Bucket=self.container_name, Key=self._key(remote_name), **kw)['Body'].read()

    def download_file(self, remote_name: str, local_path: str) -> Dict[str, Any]:
        import os
        try:
            os.makedirs(os.path.dirname(local_path) or '.', exist_ok=True)
            self._c().download_file(self.container_name, self._key(remote_name), local_path)
            return {"success": True, "message": f"Arquivo baixado: {remote_name}"}
        except Exception as e:
            msg = f"Falha ao baixar arquivo '{remote_name}': {e}"
            self.logger.error(msg)
            return {"success": False, "error": msg}

    def delete_file(self, remote_name: str) -> Dict[str, Any]:
        try:
            self._c().delete_object(Bucket=self.container_name, Key=self._key(remote_name))
            return {"success": True, "message": f"Arquivo deletado: {remote_name}"}
        except Exception as e:
            msg = f"Falha ao deletar '{remote_name}': {e}"
            self.logger.error(msg)
            return {"success": False, "error": msg}

    def get_object_size(self, remote_name: str) -> int:
        try:
            return int(self._c().head_object(Bucket=self.container_name, Key=self._key(remote_name)).get('ContentLength') or 0)
        except Exception as e:
            self.logger.debug(f"Não foi possível obter tamanho de '{remote_name}': {e}")
            return 0
