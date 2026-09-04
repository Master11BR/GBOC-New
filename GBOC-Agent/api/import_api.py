#!/usr/bin/env python3
"""
📥 GBOC Agent 14.0.0 - API de Importação
Mantém a lógica do RealBackupImporter, adicionando apenas suporte ao botão do Dashboard.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import logging
from datetime import datetime
from shared_core import get_shared_core

# Importação explícita do engine ativo
try:
    from engines.backup_importer import RealBackupImporter
except ImportError:
    RealBackupImporter = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/import", tags=["import"])

async def _run_scan_logic() -> Dict[str, Any]:
    """Lógica original de scan centralizada"""
    if not RealBackupImporter:
        raise HTTPException(status_code=503, detail="Motor de importação (engines/backup_importer.py) não encontrado")

    try:
        core = get_shared_core()
        importer = RealBackupImporter(core)
        
        logger.info("🔍 Iniciando scan do sistema (Lógica Original)...")
        scan_results = importer.scan_system()
        
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "scan_results": scan_results,
            # Campos extras para compatibilidade com Dashboard novo
            "repositories_found": len(scan_results.get("repositories_found", [])),
            "engines_detected": scan_results.get("engines_detected", {})
        }
    except Exception as e:
        logger.error(f"Erro no scan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/scan")
async def scan_get() -> Dict[str, Any]:
    """Rota original GET"""
    return await _run_scan_logic()

@router.post("/scan")
async def scan_post() -> Dict[str, Any]:
    """Rota POST para compatibilidade com botão do Dashboard"""
    return await _run_scan_logic()

@router.post("/execute")
@router.post("/duplicati")
@router.post("/native")
async def execute_import_to_native() -> Dict[str, Any]:
    """Executa a conversão/importação de todos os motores e do Duplicati para o Motor Nativo do GBOC."""
    if not RealBackupImporter:
        raise HTTPException(status_code=503, detail="Motor de importação não encontrado")

    try:
        core = get_shared_core()
        importer = RealBackupImporter(core)
        res = importer.import_all_to_native()
        return res
    except Exception as e:
        logger.error(f"Erro na execução da importação: {e}")
        raise HTTPException(status_code=500, detail=str(e))
