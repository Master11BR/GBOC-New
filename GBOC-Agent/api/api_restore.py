#!/usr/bin/env python3
"""
🔄 GBOC Agent 11.7c - API de Restauração REAL
Gerencia restauração de arquivos de snapshots reais
"""

from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel
import logging
import psycopg2.extras

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/restore", tags=["restore"])


class RestoreRequest(BaseModel):
    """Schema para requisição de restauração"""
    repository_id: int
    snapshot_id: str
    files: List[str]
    target_path: str
    options: Optional[dict] = None


@router.get("/snapshots/{repo_id}")
async def get_snapshots(repo_id: int):
    """
    Lista snapshots REAIS de um repositório
    
    Args:
        repo_id: ID do repositório
        
    Returns:
        Lista de snapshots com metadata real
    """
    try:
        from shared_core import get_shared_core
        
        logger.info(f"📋 Listando snapshots - Repository {repo_id}")
        
        core = get_shared_core()
        
        # Verificar se restore_manager existe
        if not core.restore_manager:
            logger.error("❌ RestoreManager não disponível")
            raise HTTPException(status_code=503, detail="RestoreManager não está disponível. Verifique os logs de inicialização.")
        
        snapshots = core.restore_manager.list_snapshots(repo_id)
        
        logger.info(f"✅ {len(snapshots)} snapshots encontrados")
        
        return {
            "status": "success",
            "repository_id": repo_id,
            "count": len(snapshots),
            "snapshots": snapshots
        }
        
    except ValueError as e:
        message = str(e)
        msg_low = message.lower()
        if "não encontrado" in msg_low or "not found" in msg_low:
            logger.error(f"❌ Repositório não encontrado: {e}", exc_info=True)
            raise HTTPException(status_code=404, detail=f"Repositório {repo_id} não encontrado: {message}")

        # Erros de validação de credenciais/conexão/snapshot devem retornar 400
        if any(x in msg_low for x in ["senha", "password", "credencial", "acesso negado", "não está inicializado", "repositório", "snapshot"]):
            logger.error(f"❌ Erro de validação ao listar snapshots: {e}", exc_info=True)
            raise HTTPException(status_code=400, detail=message)

        logger.error(f"❌ Erro de acesso ao repositório: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erro ao listar snapshots: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao listar snapshots: {str(e)}")


@router.get("/files/{repo_id}/{snapshot_id}")
async def get_files(
    repo_id: int,
    snapshot_id: str,
    path: str = "/"
):
    """
    Lista arquivos REAIS dentro de um snapshot
    
    Args:
        repo_id: ID do repositório
        snapshot_id: ID do snapshot
        path: Caminho dentro do snapshot (default: "/")
        
    Returns:
        Lista de arquivos e diretórios
    """
    try:
        from shared_core import get_shared_core
        
        logger.info(f"📂 Listando arquivos - Snapshot {snapshot_id}: {path}")
        
        core = get_shared_core()
        files = core.restore_manager.list_files(repo_id, snapshot_id, path)
        
        logger.info(f"✅ {len(files)} items encontrados")
        
        return {
            "status": "success",
            "snapshot_id": snapshot_id,
            "path": path,
            "count": len(files),
            "files": files
        }
        
    except ValueError as e:
        logger.error(f"❌ Snapshot não encontrado: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Erro ao listar arquivos: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/")
async def restore_files(request: RestoreRequest):
    """
    Inicia restauração assíncrona de arquivos
    
    Args:
        request: Dados da restauração (repo_id, snapshot_id, files, target_path)
        
    Returns:
        ID da restauração iniciada
    """
    try:
        from shared_core import get_shared_core
        
        logger.info(
            f"🔄 Restaurando {len(request.files)} arquivos "
            f"do snapshot {request.snapshot_id} "
            f"para {request.target_path}"
        )
        
        core = get_shared_core()
        # Usar start_restore para execução assíncrona
        result = core.restore_manager.start_restore(
            repository_id=request.repository_id,
            snapshot_id=request.snapshot_id,
            files=request.files,
            target_path=request.target_path,
            options=request.options
        )
        
        
        return result
        
    except ValueError as e:
        logger.error(f"❌ Dados inválidos: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Erro ao restaurar: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{restore_id}")
async def get_restore_status(restore_id: int):
    """Obtém status de uma restauração em andamento ou concluída."""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        status = core.restore_manager.get_recovery_status(restore_id)
        if not status:
            raise HTTPException(status_code=404, detail="Restauração não encontrada")

        return {
            "status": "success",
            "data": status
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erro ao obter status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_restore_history(limit: int = 50):
    """
    Lista histórico de restaurações
    
    Args:
        limit: Número máximo de registros (default: 50)
        
    Returns:
        Lista de restaurações anteriores
    """
    try:
        from shared_core import get_shared_core
        import psycopg2.extras
        
        logger.info(f"📋 Listando histórico de restaurações (limit={limit})")
        
        core = get_shared_core()
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT 
                    id,
                    repository_id,
                    snapshot_id,
                    status,
                    files_restored,
                    bytes_restored,
                    duration_seconds,
                    target_path,
                    error_message,
                    created_at
                FROM restore_history
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            
            history = []
            for row in cursor.fetchall():
                history.append({
                    'id': row['id'],
                    'repository_id': row['repository_id'],
                    'snapshot_id': row['snapshot_id'],
                    'status': row['status'],
                    'files_restored': row['files_restored'],
                    'bytes_restored': row['bytes_restored'],
                    'duration_seconds': row['duration_seconds'],
                    'target_path': row['target_path'],
                    'error_message': row.get('error_message'),
                    'created_at': row['created_at']
                })
        
        return {
            "status": "success",
            "count": len(history),
            "history": history
        }
        
    except Exception as e:
        logger.error(f"❌ Erro ao listar histórico: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Verifica se o módulo de restauração está funcionando"""
    try:
        from shared_core import get_shared_core
        
        core = get_shared_core()
        
        # Verificar se restore_manager está disponível
        if not hasattr(core, 'restore_manager'):
            return {
                "status": "error",
                "message": "RestoreManager não inicializado"
            }
        
        return {
            "status": "healthy",
            "message": "Módulo de restauração operacional"
        }
        
    except Exception as e:
        logger.error(f"❌ Health check falhou: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/diagnose/{repo_id}")
async def diagnose_restore_snapshots(repo_id: int):
    """Diagnóstico rápido para falhas em listagem de snapshots."""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not getattr(core, 'repository_manager', None):
            raise HTTPException(status_code=503, detail="RepositoryManager não está disponível")
        if not getattr(core, 'restore_manager', None):
            raise HTTPException(status_code=503, detail="RestoreManager não está disponível")

        repo = core.repository_manager.get_repository(repo_id)
        if not repo:
            raise HTTPException(status_code=404, detail=f"Repositório {repo_id} não encontrado")

        engine = (repo.get('engine') or 'restic').lower()
        repo_type = (repo.get('type') or 'local').lower()

        try:
            snaps = core.restore_manager.list_snapshots(repo_id)
            return {
                "status": "success",
                "repository": {
                    "id": repo_id,
                    "name": repo.get('name'),
                    "engine": engine,
                    "type": repo_type,
                    "path": repo.get('path')
                },
                "snapshots_count": len(snaps or []),
                "message": "Listagem de snapshots OK"
            }
        except Exception as e:
            msg = str(e)
            msg_l = msg.lower()
            hint = "Verifique credenciais e path do repositório"
            if 'senha' in msg_l or 'password' in msg_l:
                hint = "Senha do motor inválida. Revise motor_password/cloud_password"
            elif 'não encontrado' in msg_l or 'not found' in msg_l or 'repository does not exist' in msg_l:
                hint = "Repositório/path/bucket/prefix inválido ou inexistente"
            elif 'access denied' in msg_l or 'permission denied' in msg_l:
                hint = "Credenciais sem permissão para listar snapshots"

            return {
                "status": "error",
                "repository": {
                    "id": repo_id,
                    "name": repo.get('name'),
                    "engine": engine,
                    "type": repo_type,
                    "path": repo.get('path')
                },
                "message": msg,
                "hint": hint
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erro no diagnóstico de snapshots: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

