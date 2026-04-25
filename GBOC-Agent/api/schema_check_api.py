#!/usr/bin/env python3
"""
API de diagnóstico de schema do banco de dados
"""

from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
import logging

from shared_core import get_shared_core

router = APIRouter(prefix="/api/system", tags=["system"])
logger = logging.getLogger(__name__)


@router.get("/schema-check")
async def check_schema() -> Dict[str, Any]:
    """
    Verifica se todas as colunas esperadas existem nas tabelas principais.
    Útil para diagnosticar erros de schema incompleto.
    """
    try:
        core = get_shared_core()
        
        # Definir schema esperado para cada tabela
        expected_schema = {
            "tasks": [
                "id", "name", "repository_id", "status", "type", "engine",
                "source_paths", "schedule_enabled", "schedule_cron", "enabled",
                "retention_days", "retention_weekly", "retention_monthly", "retention_yearly",
                "retry_enabled", "retry_max_attempts", "retry_delay_minutes",
                "created_at", "updated_at", "last_run", "last_status",
                "pre_script", "post_script"
            ],
            "repositories": [
                "id", "name", "type", "path", "engine", "password",
                "motor_password", "cloud_password", "encryption_password",
                "config", "status", "enabled", "initialized",
                "created_at", "updated_at"
            ],
            "task_executions": [
                "id", "task_id", "status", "started_at", "completed_at",
                "duration_seconds", "bytes_processed", "files_processed",
                "error_message", "progress", "snapshot_id", "current_file",
                "files_total", "bytes_total", "avg_speed_bytes_per_sec",
                "compression_ratio", "files_new", "files_changed",
                "files_unmodified", "bytes_added", "created_at"
            ],
            "alerts": [
                "id", "type", "severity", "title", "message", "source",
                "acknowledged", "resolved", "details", "timestamp", "created_at"
            ],
            "settings": [
                "id", "category", "key", "value", "type", "description", "updated_at"
            ],
        }
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            
            results = {}
            missing_columns = {}
            
            for table_name, expected_cols in expected_schema.items():
                # Buscar colunas existentes na tabela
                cursor.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = %s
                    ORDER BY ordinal_position
                """, (table_name,))
                
                existing_cols = [row[0] for row in cursor.fetchall()]
                
                # Encontrar colunas faltantes
                missing = [col for col in expected_cols if col not in existing_cols]
                
                results[table_name] = {
                    "exists": len(existing_cols) > 0,
                    "total_columns": len(existing_cols),
                    "expected_columns": len(expected_cols),
                    "missing_count": len(missing),
                    "existing_columns": existing_cols,
                }
                
                if missing:
                    missing_columns[table_name] = missing
            
            # Calcular health score
            total_expected = sum(len(cols) for cols in expected_schema.values())
            total_missing = sum(len(cols) for cols in missing_columns.values())
            schema_health = round((1 - total_missing / total_expected) * 100, 1) if total_expected > 0 else 100
            
            return {
                "status": "success",
                "schema_health": schema_health,
                "health_status": "complete" if schema_health == 100 else "incomplete",
                "tables": results,
                "missing_columns": missing_columns,
                "recommendations": _generate_recommendations(missing_columns)
            }
            
    except Exception as e:
        logger.error(f"Erro ao verificar schema: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _generate_recommendations(missing_columns: Dict[str, List[str]]) -> List[str]:
    """Gera recomendações baseadas nas colunas faltantes"""
    recommendations = []
    
    if not missing_columns:
        recommendations.append("✅ Schema completo - todas as colunas esperadas estão presentes")
        return recommendations
    
    recommendations.append("⚠️ Schema incompleto detectado")
    
    for table_name, cols in missing_columns.items():
        if cols:
            recommendations.append(
                f"Tabela '{table_name}' faltando {len(cols)} coluna(s): {', '.join(cols[:5])}"
                + ("..." if len(cols) > 5 else "")
            )
    
    recommendations.append("🔧 Solução: Reinicie o agente para executar migrações automáticas")
    recommendations.append("🔧 Alternativa: Execute manualmente o database_migrator.py")
    
    return recommendations


@router.post("/schema-fix")
async def fix_schema() -> Dict[str, Any]:
    """
    Tenta corrigir schema executando migrações defensivas manualmente.
    """
    try:
        core = get_shared_core()
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            
            fixes_applied = []
            
            # Aplicar migrações defensivas
            migrations = [
                ("tasks", "retention_days", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retention_days INTEGER DEFAULT 30"),
                ("tasks", "retention_weekly", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retention_weekly INTEGER DEFAULT 4"),
                ("tasks", "retention_monthly", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retention_monthly INTEGER DEFAULT 6"),
                ("tasks", "retention_yearly", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retention_yearly INTEGER DEFAULT 1"),
                ("tasks", "retry_enabled", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retry_enabled BOOLEAN DEFAULT FALSE"),
                ("tasks", "retry_max_attempts", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retry_max_attempts INTEGER DEFAULT 3"),
                ("tasks", "retry_delay_minutes", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retry_delay_minutes INTEGER DEFAULT 5"),
                ("tasks", "schedule_enabled", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS schedule_enabled BOOLEAN DEFAULT FALSE"),
                ("tasks", "schedule_cron", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS schedule_cron TEXT"),
                ("tasks", "enabled", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE"),
                ("tasks", "type", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'backup'"),
                ("tasks", "engine", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS engine TEXT DEFAULT 'restic'"),
                ("tasks", "source_paths", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source_paths TEXT"),
                ("repositories", "encryption_password", "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS encryption_password TEXT"),
                ("settings", "category", "ALTER TABLE settings ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'general'"),
                ("settings", "type", "ALTER TABLE settings ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'string'"),
                ("settings", "description", "ALTER TABLE settings ADD COLUMN IF NOT EXISTS description TEXT"),
                ("alerts", "resolved", "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS resolved BOOLEAN DEFAULT FALSE"),
                ("alerts", "details", "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS details TEXT"),
            ]
            
            for table, column, sql in migrations:
                try:
                    cursor.execute(sql)
                    fixes_applied.append(f"{table}.{column}")
                except Exception as e:
                    logger.warning(f"Falha ao aplicar migração {table}.{column}: {e}")
            
            conn.commit()
            
            return {
                "status": "success",
                "message": "Migrações defensivas aplicadas",
                "fixes_applied": fixes_applied,
                "total_fixes": len(fixes_applied)
            }
            
    except Exception as e:
        logger.error(f"Erro ao corrigir schema: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
