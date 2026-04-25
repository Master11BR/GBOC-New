#!/usr/bin/env python3
"""
GBOC Agent - API Engines
Rotas para validação e diagnóstico de motores de backup
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/engines", tags=["engines"])


@router.get("/validate")
async def validate_all_engines() -> Dict[str, Any]:
    """
    Valida todos os motores de backup instalados
    Retorna status detalhado de cada motor
    """
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not hasattr(core, 'repository_manager'):
            raise HTTPException(status_code=503, detail="RepositoryManager não está disponível")

        results = core.repository_manager.validate_engines()

        # Preparar resposta estruturada
        engines_status = []
        all_healthy = True

        for engine_name, status in results.items():
            engine_info = {
                'name': engine_name,
                'display_name': status.get('name', engine_name.upper()),
                'installed': status.get('installed', False),
                'available': status.get('available', False),
                'version': status.get('version'),
                'path': status.get('path'),
                'source': status.get('source'),
                'error': status.get('error'),
                'healthy': status.get('available', False)
            }
            engines_status.append(engine_info)

            if not status.get('available', False):
                all_healthy = False

        return {
            'status': 'success',
            'engines': engines_status,
            'system_healthy': all_healthy,
            'total_engines': len(engines_status),
            'healthy_engines': len([e for e in engines_status if e['healthy']])
        }

    except Exception as e:
        logger.error(f"❌ Engine validation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/validate/{engine_name}")
async def validate_engine(engine_name: str) -> Dict[str, Any]:
    """
    Valida um motor específico
    """
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not hasattr(core, 'repository_manager'):
            raise HTTPException(status_code=503, detail="RepositoryManager não está disponível")

        status = core.repository_manager.validate_engine(engine_name)

        return {
            'status': 'success',
            'engine': engine_name,
            'validation': {
                'name': status.get('name', engine_name.upper()),
                'installed': status.get('installed', False),
                'available': status.get('available', False),
                'version': status.get('version'),
                'path': status.get('path'),
                'source': status.get('source'),
                'error': status.get('error'),
                'healthy': status.get('available', False)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Engine validation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report")
async def get_engine_validation_report() -> Dict[str, Any]:
    """
    Retorna relatório completo de validação dos motores em formato texto
    """
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not hasattr(core, 'repository_manager'):
            raise HTTPException(status_code=503, detail="RepositoryManager não está disponível")

        report = core.repository_manager.get_engine_validation_report()

        return {
            'status': 'success',
            'report': report,
            'format': 'text'
        }

    except Exception as e:
        logger.error(f"❌ Engine report error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-connection")
async def test_repository_connection(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Testa conexão com um repositório antes de criá-lo
    """
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not hasattr(core, 'repository_manager'):
            raise HTTPException(status_code=503, detail="RepositoryManager não está disponível")

        # Validar dados obrigatórios
        required_fields = ['engine', 'type']
        for field in required_fields:
            if field not in data:
                raise HTTPException(status_code=400, detail=f"Campo obrigatório faltando: {field}")

        # Validar engine
        engine = data.get('engine', '').lower()

        # Validar tipo
        repo_type = data.get('type', '').lower()
        if repo_type not in ['local', 'b2', 's3', 'azure']:
            raise HTTPException(status_code=400, detail=f"Tipo de repositório '{repo_type}' não suportado")

        logger.info(f"🔍 Testando conexão do repositório: {engine} ({repo_type})")

        result = core.repository_manager.validate_repository_connection(data)

        return {
            'status': 'success',
            'connection_test': {
                'engine': result.get('engine'),
                'repo_type': result.get('repo_type'),
                'tested': result.get('connection_tested', False),
                'successful': result.get('connection_ok', False),
                'error': result.get('error'),
                'details': result.get('details', {})
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Connection test error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def get_engine_health() -> Dict[str, Any]:
    """
    Retorna status de saúde geral dos motores (endpoint simples para dashboards)
    """
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        if not hasattr(core, 'repository_manager'):
            return {
                'status': 'error',
                'message': 'RepositoryManager não disponível',
                'healthy': False
            }

        results = core.repository_manager.validate_engines()

        healthy_count = sum(1 for status in results.values() if status.get('available', False))
        total_count = len(results)

        health_status = {
            'healthy': healthy_count == total_count,
            'total_engines': total_count,
            'healthy_engines': healthy_count,
            'unhealthy_engines': total_count - healthy_count,
            'engines': {}
        }

        # Detalhes por engine
        for engine_name, status in results.items():
            health_status['engines'][engine_name] = {
                'healthy': status.get('available', False),
                'version': status.get('version'),
                'error': status.get('error') if not status.get('available', False) else None
            }

        return {
            'status': 'success',
            'health': health_status
        }

    except Exception as e:
        logger.error(f"❌ Engine health check error: {e}", exc_info=True)
        return {
            'status': 'error',
            'message': str(e),
            'healthy': False
        }


@router.get("/status")
async def get_engine_status() -> Dict[str, Any]:
    """
    Alias para /health - compatibilidade
    """
    return await get_engine_health()


@router.post("/rescan")
async def rescan_engines() -> Dict[str, Any]:
    """Força rescan completo dos motores e atualiza cache persistente."""
    try:
        from engines.engine_paths import rescan_all_engines
        engines = rescan_all_engines()
        return {
            "status": "success",
            "engines": engines,
            "message": "Rescan completo de motores concluído"
        }
    except Exception as e:
        logger.error(f"❌ Engine rescan error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
