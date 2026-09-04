#!/usr/bin/env python3
"""
GBOC Agent 14.0.0 - API Repositories
✅ Aceita payload flexível do frontend
✅ Integra com RepositoryManager
✅ Inicialização em background
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, ConfigDict
import logging
import psycopg2
import json

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/repositories", tags=["repositories"])


# ==============================================================================
# Modelos Pydantic Locais (flexíveis)
# ==============================================================================

class RepositoryCreateRequest(BaseModel):
    """Modelo flexível para criação - aceita o que o frontend envia"""
    name: str
    engine: str = "restic"
    motor_password: Optional[str] = None
    cloud_password: Optional[str] = None
    
    # Aceita 'type' ou 'repo_type'
    type: Optional[str] = None
    repo_type: Optional[str] = None
    
    # Campos opcionais
    bucket: Optional[str] = None
    path: Optional[str] = None
    region: Optional[str] = None
    endpoint: Optional[str] = None
    prefix: Optional[str] = None
    access_key: Optional[str] = None
    secret_key: Optional[str] = None

    model_config = ConfigDict(extra="allow")
    
    def get_type(self) -> str:
        return self.type or self.repo_type or "local"

    def get_password(self) -> str:
        return self.motor_password  # Sempre retorna a senha do motor


class RepositoryUpdateRequest(BaseModel):
    """Modelo flexível para atualização - todos campos opcionais"""
    name: Optional[str] = None
    motor_password: Optional[str] = None
    cloud_password: Optional[str] = None
    bucket: Optional[str] = None
    path: Optional[str] = None
    region: Optional[str] = None
    endpoint: Optional[str] = None
    prefix: Optional[str] = None
    access_key: Optional[str] = None
    secret_key: Optional[str] = None

    # Campos específicos de providers
    b2_account_id: Optional[str] = None
    b2_account_key: Optional[str] = None
    aws_access_key: Optional[str] = None
    aws_secret_key: Optional[str] = None
    azure_account_name: Optional[str] = None
    azure_account_key: Optional[str] = None
    
    model_config = ConfigDict(extra="allow")


class SuccessResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[Dict[str, Any]] = None


def _build_connection_summary(result: Dict[str, Any]) -> str:
    diagnostics = result.get('diagnostics') or {}
    local = diagnostics.get('local') or {}
    secondary = diagnostics.get('secondary') or {}
    auth = diagnostics.get('auth') or {}
    total_ms = diagnostics.get('total_elapsed_ms', 0)

    def _line(title: str, info: Dict[str, Any]) -> str:
        if not info.get('checked', False):
            return f"- {title}: N/A"
        status = "OK" if info.get('ok') else "FALHA"
        elapsed = info.get('elapsed_ms', 0)
        msg = info.get('message') or ''
        return f"- {title}: {status} ({elapsed} ms) {msg}".strip()

    repo_name = str(result.get('repository_name') or result.get('name') or '').strip()
    engine = str(result.get('engine') or result.get('repository_engine') or 'desconhecido').upper()
    repo_type = str(result.get('repo_type') or result.get('type') or 'desconhecido').upper()

    lines = []
    if repo_name:
        lines.append(f"Repositório: {repo_name}")
    lines.extend([
        f"Engine: {engine}",
        f"Tipo: {repo_type}",
        _line("Conexão local/engine", local),
        _line("Conexão secundária", secondary),
        _line("Autenticação", auth),
        f"Tempo total: {total_ms} ms"
    ])
    return "\n".join(lines)


# ==============================================================================
# Endpoints
# ==============================================================================

@router.get("/")
async def list_repositories():
    """
    Lista todos os repositórios configurados.
    Retorna lista de dicts com dados seguros (sem senhas).
    """
    try:
        logger.info("🔍 Iniciando listagem de repositórios...")

        from shared_core import get_shared_core
        core = get_shared_core()

        if not core.repository_manager:
            logger.error("RepositoryManager não disponível")
            raise HTTPException(status_code=503, detail="RepositoryManager não disponível")

        logger.info("📊 Consultando repositórios no banco...")
        repos = core.repository_manager.list_repositories()
        logger.info(f"📊 Encontrados {len(repos)} repositórios")

        # Converter para lista de dicts seguros
        result = []
        for i, repo in enumerate(repos):
            logger.info(f"🔄 Processando repositório {i+1}/{len(repos)}: {repo.get('name', 'N/A')}")

            if hasattr(repo, 'dict'):
                repo_dict = repo.dict()
            elif isinstance(repo, dict):
                repo_dict = repo
            else:
                repo_dict = dict(repo)

            # Remover senhas sensíveis
            for sensitive_field in ['encryption_password', 'secret_key', 'password',
                                   'b2_account_key', 'aws_secret_key', 'azure_account_key',
                                   'cloud_password', 'motor_password']:
                repo_dict.pop(sensitive_field, None)

            result.append(repo_dict)

        logger.info(f"✅ Retornando {len(result)} repositórios processados")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao listar repositórios: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=SuccessResponse)
async def create_repository(repo: RepositoryCreateRequest, background_tasks: BackgroundTasks):
    """
    Cria novo repositório e agenda inicialização em background.
    """
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        
        if not core.repository_manager:
            raise HTTPException(status_code=503, detail="RepositoryManager não disponível")
        
        # Validação: motor_password é obrigatória para todos os tipos de repositório.
        # É a senha de criptografia usada pelo motor (Restic/Kopia/Duplicati) — local ou cloud.
        # As credenciais de acesso ao provedor cloud (access_key/secret_key) são campos separados.
        if not repo.motor_password:
            raise HTTPException(status_code=400, detail="motor_password é obrigatória (senha de criptografia do repositório)")

        # Montar dados para o manager
        repo_data = {
            'name': repo.name,
            'type': repo.get_type(),
            'engine': repo.engine,
            'motor_password': repo.motor_password,
            'cloud_password': repo.motor_password,  # coluna legada — mantém motor_password
            'bucket': repo.bucket or repo.path,
            'region': repo.region,
            'endpoint': repo.endpoint,
            'prefix': repo.prefix,
            'access_key': repo.access_key,
            'secret_key': repo.secret_key,
        }
        
        logger.info(f"Criando repositório: {repo.name} (tipo: {repo_data['type']})")
        
        # Criar no banco
        result = core.repository_manager.create_repository(repo_data)
        repo_id = result.get("id")
        
        if not repo_id:
            raise HTTPException(status_code=500, detail="Falha ao obter ID do repositório criado")

        logger.info(f"Repositório {repo_id} criado com sucesso.")

        return SuccessResponse(
            message="Repositório criado com sucesso.",
            data={"id": repo_id}
        )
        
    except HTTPException:
        raise
    except ImportError as ie:
        logger.warning(f"Dependência ausente ao criar repositório: {ie}")
        raise HTTPException(status_code=400, detail=str(ie))
    except psycopg2.IntegrityError as e:
        # Erro de constraint UNIQUE
        if "unique" in str(e).lower() or "duplicate key" in str(e).lower():
            logger.warning(f"Conflito de nome: {e}")
            raise HTTPException(status_code=409, detail=f"Já existe um repositório com o nome '{repo.name}'")
        # Outros erros de integridade
        logger.error(f"Erro de integridade: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except ConnectionError as ce:
        logger.warning(f"Falha de conexão ao criar repositório: {ce}")
        raise HTTPException(status_code=422, detail=str(ce))
    except ValueError as ve:
        logger.warning(f"Erro de validação: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        # Outros erros
        logger.error(f"Erro ao criar repositório: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{repo_id}")
async def get_repository(repo_id: int, show_sensitive: bool = False):
    """
    Retorna dados de um repositório específico.
    Mascara senha de criptografia por padrão.
    Se show_sensitive=true (para testes), retorna as senhas reais.
    """
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        
        if not core.repository_manager:
            raise HTTPException(status_code=503, detail="RepositoryManager não disponível")
        
        repo = core.repository_manager.get_repository(repo_id)
        
        if not repo:
            raise HTTPException(status_code=404, detail="Repositório não encontrado")
        
        # Converter para dict se necessário
        if hasattr(repo, 'dict'):
            repo_dict = repo.dict()
        elif isinstance(repo, dict):
            repo_dict = dict(repo)
        else:
            repo_dict = dict(repo)
        
        # Converter datetime para string
        from datetime import datetime
        for key in ['created_at', 'updated_at']:
            if key in repo_dict and isinstance(repo_dict[key], datetime):
                repo_dict[key] = repo_dict[key].isoformat()
        
        # Desserializar config JSON se for string
        if 'config' in repo_dict and isinstance(repo_dict['config'], str):
            try:
                repo_dict['config'] = json.loads(repo_dict['config'])
            except:
                pass
        
        # Extrair campos do config para o nível superior (compatibilidade frontend)
        if 'config' in repo_dict and isinstance(repo_dict['config'], dict):
            config = repo_dict['config']
            # Copiar campos importantes para o nível superior
            for field in ['bucket', 'region', 'endpoint', 'prefix', 'access_key', 'secret_key',
                          'aws_access_key', 'aws_secret_key', 'b2_account_id', 'b2_account_key',
                          'azure_account_name', 'azure_account_key']:
                if field in config and field not in repo_dict:
                    repo_dict[field] = config[field]
        
        # Se não estiver em modo de teste, mascarar senhas
        if not show_sensitive:
            # Mascarar senha de criptografia (não remover, frontend precisa saber que existe)
            if 'encryption_password' in repo_dict and repo_dict['encryption_password']:
                repo_dict['encryption_password'] = '********'
            if 'motor_password' in repo_dict and repo_dict['motor_password']:
                repo_dict['motor_password'] = '********'
            
            # Remover outras senhas sensíveis - NOTA: não remover, apenas mascarar
            sensitive_fields = ['password', 'b2_account_key', 'aws_secret_key', 'azure_account_key', 'cloud_password']
            for sensitive_field in sensitive_fields:
                if sensitive_field in repo_dict and repo_dict[sensitive_field]:
                    repo_dict[sensitive_field] = '********'
            
            # Mascarar secret_key por último, se existir
            if 'secret_key' in repo_dict and repo_dict['secret_key']:
                repo_dict['secret_key'] = '********'
        else:
            # Em modo de teste, registrar aviso no log
            logger.warning(f"⚠️ MODO TESTE: Retornando senhas visíveis para repositório {repo_id}. NÃO use em produção!")
            # As senhas já estão em texto plano, apenas registrar
            if 'motor_password' in repo_dict:
                logger.debug(f"📋 Motor password para repo {repo_id}: {repo_dict.get('motor_password', 'N/A')}")
        
        logger.info(f"📦 Retornando repositório {repo_id}: {list(repo_dict.keys())}")
        return repo_dict
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao buscar repositório {repo_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{repo_id}", response_model=SuccessResponse)
async def update_repository(repo_id: int, repo_data: RepositoryUpdateRequest):
    """
    Atualiza repositório existente.
    Apenas campos fornecidos são atualizados.
    """
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        
        if not core.repository_manager:
            raise HTTPException(status_code=503, detail="RepositoryManager não disponível")
        
        # Verificar se existe
        existing = core.repository_manager.get_repository(repo_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Repositório não encontrado")
        
        # Converter para dict excluindo campos não definidos (compatível com Pydantic v1 e v2)
        update_dict = (
            repo_data.model_dump(exclude_unset=True)
            if hasattr(repo_data, "model_dump")
            else repo_data.dict(exclude_unset=True)
        )

        # Nunca sobrescrever senhas com vazio na edição
        for pwd_field in ['motor_password', 'cloud_password']:
            if pwd_field in update_dict and (update_dict[pwd_field] is None or str(update_dict[pwd_field]).strip() == ''):
                del update_dict[pwd_field]

        # Remover campos None; permitir string vazia para campos cloud (limpa o valor)
        cloud_fields = {'bucket', 'region', 'endpoint', 'prefix', 'access_key', 'secret_key',
                        'aws_access_key', 'aws_secret_key', 'b2_account_id', 'b2_account_key',
                        'azure_account_name', 'azure_account_key'}
        update_dict = {k: v for k, v in update_dict.items()
                       if v is not None and (k in cloud_fields or v != '')}
        
        # Remover campos mascarados (não devem ser salvos)
        if update_dict.get('encryption_password') == '********':
            del update_dict['encryption_password']
        for field in ['secret_key', 'b2_account_key', 'aws_secret_key', 'azure_account_key']:
            if update_dict.get(field) == '********':
                del update_dict[field]
        
        if not update_dict:
            return SuccessResponse(message="Nenhuma alteração fornecida.")
        
        logger.info(f"Atualizando repositório {repo_id}: {list(update_dict.keys())}")
        
        success = core.repository_manager.update_repository(repo_id, update_dict)
        
        if not success:
            raise HTTPException(status_code=400, detail="Falha ao atualizar repositório")
        
        return SuccessResponse(message="Repositório atualizado com sucesso.")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao atualizar repositório {repo_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{repo_id}", response_model=SuccessResponse)
async def delete_repository(repo_id: int, keep_folder: bool = False):
    """
    Exclui repositório e tarefas associadas.
    """
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        
        if not core.repository_manager:
            raise HTTPException(status_code=503, detail="RepositoryManager não disponível")
        
        core.repository_manager.delete_repository(repo_id, keep_folder)
        
        return SuccessResponse(message="Repositório excluído com sucesso.")
        
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Erro ao excluir repositório {repo_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{repo_id}/initialize", response_model=SuccessResponse)
async def initialize_repository(repo_id: int):
    """Inicializa explicitamente um repositório (restic init / kopia repository create)."""
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not core.repository_manager:
            raise HTTPException(status_code=503, detail="RepositoryManager não disponível")

        existing = core.repository_manager.get_repository(repo_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Repositório não encontrado")

        engine = str(existing.get('engine', 'restic')).lower()
        repo_config = core.repository_manager._normalize_repository_config(existing)

        if engine == 'restic':
            result = core.repository_manager._validate_restic_auth(repo_config, allow_init=True)
        elif engine == 'kopia':
            result = core.repository_manager._validate_kopia_connection(repo_config, allow_init=True)
        else:
            result = core.repository_manager.validate_connection(repo_id)

        if not result.get('valid'):
            raise HTTPException(status_code=422, detail=result.get('message', 'Falha ao inicializar repositório'))

        with core.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE repositories SET initialized = TRUE, status = 'active', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (repo_id,)
            )
            conn.commit()

        return SuccessResponse(
            message=result.get('message', 'Repositório inicializado com sucesso'),
            data={"id": repo_id, "initialized": True, "status": "active"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao inicializar repositório {repo_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-connection", response_model=SuccessResponse)
async def test_repository_connection_before_creation(request: RepositoryCreateRequest):
    """Testa conexão com repositório antes da criação"""
    try:
        logger.info(f"🧪 Testando conexão para repositório: {request.name}")

        # Converter para dicionário e marcar como teste
        repo_data = request.dict()
        repo_data['test_only'] = True

        from shared_core import get_shared_core
        core = get_shared_core()

        if not core.repository_manager:
            raise HTTPException(status_code=503, detail="RepositoryManager não disponível")

        test_result = core.repository_manager.validate_repository_connection(repo_data)

        if test_result.get('connection_ok') and test_result.get('auth_ok', True):
            return SuccessResponse(
                message="Conexão testada com sucesso",
                data={
                    "connection_status": "success",
                    "connection_ok": True,
                    "auth_ok": True,
                    "engine": test_result.get('engine'),
                    "repo_type": test_result.get('repo_type'),
                    "diagnostics": test_result.get('diagnostics', {}),
                    "summary": _build_connection_summary(test_result)
                }
            )

        detail = _build_connection_summary(test_result)
        raise HTTPException(status_code=400, detail=detail)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao testar conexão: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{repo_id}/test")
async def test_repository_connection(repo_id: int):
    """
    Testa conexão/acessibilidade do repositório usando testes específicos por tipo.
    """
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        
        if not core.repository_manager:
            raise HTTPException(status_code=503, detail="RepositoryManager não disponível")
        
        # Verificar se existe
        repo = core.repository_manager.get_repository(repo_id)
        if not repo:
            raise HTTPException(status_code=404, detail="Repositório não encontrado")
        
        logger.info(f"🧪 Testando conexão do repositório {repo_id}")

        # Diagnóstico completo (não só bool)
        result = core.repository_manager.validate_connection(repo_id)

        if result.get("valid"):
            logger.info(f"✅ Conexão válida para repositório {repo_id}")
            return SuccessResponse(
                message="Conexão testada com sucesso!",
                data={
                    "connection_status": "valid",
                    "repo_id": repo_id,
                    "connection_ok": result.get("connection_ok", True),
                    "auth_ok": result.get("auth_ok", True),
                    "engine": result.get("engine"),
                    "repo_type": result.get("repo_type"),
                    "diagnostics": result.get("diagnostics", {}),
                    "summary": _build_connection_summary(result)
                }
            )

        detail = _build_connection_summary(result)

        logger.warning(f"❌ Conexão inválida para repositório {repo_id}: {detail}")
        raise HTTPException(status_code=400, detail=detail)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao testar conexão {repo_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{repo_id}/validate")
async def validate_repository_connection(repo_id: int):
    """
    Valida conexão e retorna detalhes (snapshots, etc).
    """
    try:
        from shared_core import get_shared_core
        core = get_shared_core()
        
        if not core.repository_manager:
            raise HTTPException(status_code=503, detail="RepositoryManager não disponível")
        
        # Verificar se existe
        repo = core.repository_manager.get_repository(repo_id)
        if not repo:
            raise HTTPException(status_code=404, detail="Repositório não encontrado")
        
        logger.info(f"📊 Validando repositório {repo_id}")
        
        # Validar conexão com detalhes
        result = core.repository_manager.validate_connection(repo_id)
        if not result.get("engine"):
            result["engine"] = repo.get("engine")
        if not result.get("repo_type"):
            result["repo_type"] = repo.get("type")
        if not result.get("repository_name"):
            result["repository_name"] = repo.get("name")

        result["summary"] = _build_connection_summary(result)
        if result.get("valid"):
            return result

        # Em caso de falha, devolver detalhe técnico completo para o frontend
        reason = result.get("message") or "Falha ao validar conexão"
        detail = f"{result['summary']}\nMotivo: {reason}"
        raise HTTPException(status_code=400, detail=detail)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao validar repositório {repo_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fix-stuck")
async def fix_stuck_repositories():
    """
    Corrige repositórios travados em inicialização.
    Útil quando repositórios ficam presos no status "inicializando" devido a erros.
    """
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not core.repository_manager:
            raise HTTPException(status_code=503, detail="RepositoryManager não disponível")

        # Listar repositórios travados
        repositories = core.repository_manager.list_repositories()
        stuck_repos = []

        for repo in repositories:
            status = repo.get('status', '').lower()
            initialized = repo.get('initialized', False)

            # Considerar travado se:
            # - Status indica inicialização pendente
            # - Não está inicializado mas deveria estar
            if (status in ['pending_initialization', 'initializing'] or
                (not initialized and status in ['ready', 'active'])):
                stuck_repos.append(repo)

        if not stuck_repos:
            return SuccessResponse(
                message="Nenhum repositório travado encontrado",
                data={"fixed_count": 0, "total_stuck": 0}
            )

        logger.info(f"Corrigindo {len(stuck_repos)} repositório(s) travado(s)")

        fixed_count = 0
        results = []

        for repo in stuck_repos:
            repo_id = repo['id']
            repo_name = repo['name']

            try:
                # Resetar status
                reset_success = core.repository_manager.update_repository(repo_id, {
                    'status': 'ready',
                    'initialized': False
                })

                if not reset_success:
                    results.append({
                        "id": repo_id,
                        "name": repo_name,
                        "success": False,
                        "error": "Falha ao resetar status"
                    })
                    continue

                # Tentar revalidar conexão
                conn_result = core.repository_manager.validate_connection(repo_id)
                init_success = conn_result.get('valid', False)

                if init_success:
                    fixed_count += 1
                    results.append({
                        "id": repo_id,
                        "name": repo_name,
                        "success": True,
                        "message": "Corrigido e revalidado"
                    })
                else:
                    results.append({
                        "id": repo_id,
                        "name": repo_name,
                        "success": False,
                        "error": conn_result.get('message', 'Falha na revalidação')
                    })

            except Exception as e:
                results.append({
                    "id": repo_id,
                    "name": repo_name,
                    "success": False,
                    "error": str(e)
                })

        message = f"{fixed_count}/{len(stuck_repos)} repositório(s) corrigido(s)"
        logger.info(f"Correção concluída: {message}")

        return SuccessResponse(
            message=message,
            data={
                "fixed_count": fixed_count,
                "total_stuck": len(stuck_repos),
                "results": results
            }
        )

    except Exception as e:
        logger.error(f"Erro ao corrigir repositórios travados: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

