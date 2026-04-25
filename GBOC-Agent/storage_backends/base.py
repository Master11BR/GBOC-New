import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class StorageBackend(ABC):
    """
    Classe base abstrata para todos os backends de armazenamento.
    Define a interface comum para interagir com diferentes tipos de armazenamento
    (local, S3, B2, Azure, GCS, etc.).
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o backend de armazenamento.

        Args:
            config (Dict[str, Any]): A configuração do repositório, contendo
                                     tudo o que é necessário para a conexão
                                     (path, bucket, credenciais, etc.).
        """
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug(f"Backend '{self.__class__.__name__}' inicializado.")

    @abstractmethod
    def check_connection(self) -> Dict[str, Any]:
        """
        Verifica se a conexão com o armazenamento é possível e válida.

        Returns:
            Dict[str, Any]: {
                "success": bool,
                "message": str,
                "error": str (opcional)
            }
        """
        pass

    @abstractmethod
    def list_snapshots(self) -> List[Dict[str, Any]]:
        """
        Lista snapshots/backups disponíveis no storage.

        Returns:
            Lista de snapshots com metadados
        """
        pass

    @abstractmethod
    def test_credentials(self) -> bool:
        """
        Testa se as credenciais são válidas.

        Returns:
            bool: True se válido, False caso contrário
        """
        pass

    def validate_connection(self) -> bool:
        """
        Validação rápida - wrapper para check_connection.

        Returns:
            bool: True se válido
        """
        try:
            result = self.check_connection()
            return result.get('success', False)
        except Exception as e:
            self.logger.error(f"Erro na validação: {e}")
            return False

    def upload_file(self, local_path: str, remote_name: str) -> Dict[str, Any]:
        """
        Faz o upload de um arquivo local para o armazenamento (opcional).

        Args:
            local_path (str): O caminho do arquivo local a ser enviado.
            remote_name (str): O nome (caminho) do arquivo no destino.

        Returns:
            Dict[str, Any]: Dicionário com {"success": True/False, "error": "mensagem"}
        """
        return {"success": False, "error": "Not implemented"}

    def get_info(self) -> Dict[str, Any]:
        """
        Retorna informações sobre este backend.

        Returns:
            Dict com metadados do backend
        """
        return {
            "type": self.config.get('type', 'unknown'),
            "name": self.config.get('name', 'Unknown'),
            "connected": self.validate_connection(),
            "snapshots": len(self.list_snapshots() or [])
        }

