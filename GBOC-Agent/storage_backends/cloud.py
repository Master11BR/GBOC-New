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

class CloudStorageBackend(StorageBackend):
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
        try:
            if not self.container:
                self.container = self.driver.get_container(container_name=self.container_name)

            with open(local_path, 'rb') as f:
                obj = self.driver.upload_object_via_stream(
                    iterator=f,
                    container=self.container,
                    object_name=remote_name
                )

            return {"success": True, "message": f"Arquivo enviado como {remote_name}"}

        except Exception as e:
            error_msg = f"Falha ao fazer upload: {e}"
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
            objects = self.container.list_objects()

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
