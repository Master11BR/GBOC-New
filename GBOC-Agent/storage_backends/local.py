import os
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from .base import StorageBackend

logger = logging.getLogger(__name__)

class LocalStorageBackend(StorageBackend):
    """
    Backend de armazenamento para o sistema de arquivos local.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_path = Path(self.get_path())
        # Garante que o diretório base exista
        os.makedirs(self.base_path, exist_ok=True)
        self.logger.info(f"LocalStorageBackend pronto em {self.base_path}")

    def get_path(self) -> str:
        """Obtém o caminho base do repositório."""
        return self.config.get('path', '')

    def check_connection(self) -> Dict[str, Any]:
        """
        Verifica se o caminho base existe e é gravável.
        
        Returns:
            Dict com {"success": bool, "message": str}
        """
        try:
            path = self.get_path()
            
            if not path:
                return {"success": False, "message": "Caminho não configurado", "error": "no_path"}
            
            if not os.path.exists(path):
                return {"success": False, "message": f"Caminho não existe: {path}", "error": "not_exists"}
            
            if not os.path.isdir(path):
                return {"success": False, "message": f"Não é um diretório: {path}", "error": "not_directory"}
            
            if not os.access(path, os.W_OK):
                return {"success": False, "message": f"Sem permissão de escrita: {path}", "error": "no_write_permission"}
            
            return {"success": True, "message": f"Conectado ao repositório local em {path}"}
            
        except Exception as e:
            self.logger.error(f"Erro ao verificar conexão local: {e}")
            return {"success": False, "message": str(e), "error": "exception"}

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """
        Lista snapshots (subdiretórios) no repositório local.
        
        Returns:
            Lista de snapshots encontrados
        """
        try:
            path = self.get_path()
            if not os.path.exists(path):
                return []
            
            snapshots = []
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    try:
                        stat = os.stat(item_path)
                        size = sum(f.stat().st_size for f in Path(item_path).rglob('*') if f.is_file())
                        snapshots.append({
                            'id': item,
                            'name': item,
                            'date': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            'size': size,
                            'files': sum(1 for f in Path(item_path).rglob('*') if f.is_file())
                        })
                    except Exception as e:
                        self.logger.debug(f"Erro ao processar {item}: {e}")
            
            return sorted(snapshots, key=lambda x: x['date'], reverse=True)
            
        except Exception as e:
            self.logger.error(f"Erro ao listar snapshots: {e}")
            return []

    def test_credentials(self) -> bool:
        """
        Testa se as credenciais (acesso ao diretório) são válidas.
        
        Returns:
            True se acesso OK
        """
        result = self.check_connection()
        return result.get('success', False)

    def upload_file(self, local_path: str, remote_name: str) -> Dict[str, Any]:
        """
        "Faz upload" de um arquivo, que neste caso é uma cópia para o diretório de destino.
        
        Args:
            local_path: Caminho do arquivo local
            remote_name: Nome no destino
            
        Returns:
            Dict com status
        """
        try:
            source = Path(local_path)
            destination = self.base_path / remote_name
            
            self.logger.debug(f"Copiando de '{source}' para '{destination}'")
            
            # Garante que o subdiretório de destino exista
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            
            return {"success": True, "message": f"Arquivo copiado para {destination}"}
            
        except Exception as e:
            error_msg = f"Falha ao copiar arquivo: {e}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": "copy_failed"}

    def download_file(self, remote_name: str, local_path: str) -> Dict[str, Any]:
        """
        "Baixa" um arquivo, que neste caso é uma cópia do diretório do repositório.
        """
        source = self.base_path / remote_name
        destination = Path(local_path)
        
        self.logger.debug(f"Copiando de '{source}' para '{destination}'")
        try:
            if not source.exists():
                 return {"success": False, "error": f"Arquivo não encontrado no repositório: {remote_name}"}
            
            # Garante que o diretório de destino local exista
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            return {"success": True}
        except Exception as e:
            error_msg = f"Falha ao 'baixar' arquivo: {e}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}

    def list_files(self, sub_path: Optional[str] = None) -> List[str]:
        """
        Lista os arquivos no repositório local.
        """
        target_path = self.base_path
        if sub_path:
            target_path = self.base_path / sub_path
        
        self.logger.debug(f"Listando arquivos em: {target_path}")
        try:
            if not target_path.exists():
                return []
            
            files = []
            for entry in target_path.rglob('*'):
                if entry.is_file():
                    # Retorna o caminho relativo ao diretório base
                    files.append(str(entry.relative_to(self.base_path)))
            return files
        except Exception as e:
            self.logger.error(f"Falha ao listar arquivos: {e}", exc_info=True)
            return []

    def delete_file(self, remote_name: str) -> Dict[str, Any]:
        """
        Deleta um arquivo do repositório local.
        """
        file_to_delete = self.base_path / remote_name
        self.logger.debug(f"Deletando arquivo: {file_to_delete}")

        try:
            if not file_to_delete.exists():
                return {"success": False, "error": "Arquivo não encontrado"}
            
            os.remove(file_to_delete)
            return {"success": True}
        except Exception as e:
            error_msg = f"Falha ao deletar arquivo: {e}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}
