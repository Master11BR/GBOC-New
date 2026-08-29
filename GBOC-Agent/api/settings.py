#!/usr/bin/env python3
"""
⚙️ GBOC Agent 13.2.0 - API SETTINGS
Responsável por: Rotas para configuração do sistema
"""

from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any, List
import json
import os
from datetime import datetime
import logging

from shared_core import get_shared_core

logger = logging.getLogger("API-Settings")
router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.post("/reset-install")
async def reset_install() -> Dict[str, Any]:
    """Reseta o sistema para estado de instalação limpa — apaga repositórios, tarefas, execuções e configurações"""
    try:
        core = get_shared_core()

        with core.get_db_connection() as conn:
            cursor = conn.cursor()

            # Contar antes de apagar
            counts = {}
            count_tables = [
                'task_executions', 'tasks', 'repositories', 'alerts',
                'ransomware_scans', 'ransomware_canaries', 'ransomware_incidents',
                'notification_history', 'notification_channels',
                'audit_log', 'backup_statistics', 'report_history',
                'replication_history', 'config_snapshots',
                'error_log', 'daily_metrics', 'engine_metrics', 'task_metrics',
                'performance_metrics', 'backup_patterns', 'user_suggestions',
                'integrity_checks',
            ]
            for tbl in count_tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
                    counts[tbl] = cursor.fetchone()[0]
                except Exception:
                    conn.rollback()
                    counts[tbl] = 0

            # Apagar na ordem correta (respeitando FKs)
            delete_order = [
                'task_executions', 'replication_history', 'notification_history',
                'report_history', 'config_snapshots', 'audit_log',
                'ransomware_incidents', 'ransomware_scans', 'ransomware_canaries',
                'integrity_checks', 'error_log',
                'daily_metrics', 'engine_metrics', 'task_metrics',
                'performance_metrics', 'backup_patterns', 'user_suggestions',
                'backup_statistics', 'alerts',
                'tasks', 'repositories',
            ]
            deleted = {}
            for tbl in delete_order:
                try:
                    cursor.execute(f"DELETE FROM {tbl}")
                    deleted[tbl] = counts.get(tbl, 0)
                except Exception:
                    conn.rollback()
                    deleted[tbl] = 0

            # Resetar configurações para defaults
            defaults = _get_default_settings()
            settings_reset = 0
            for category, cat_settings in defaults.items():
                for key, config in cat_settings.items():
                    serialized = _serialize_value(config["default"])
                    cursor.execute("""
                        UPDATE settings 
                        SET value = %s, updated_at = %s
                        WHERE category = %s AND key = %s
                    """, (serialized, datetime.now().isoformat(), category, key))
                    settings_reset += cursor.rowcount

            # Limpar logs antigos (manter últimos 100)
            cursor.execute("""
                DELETE FROM system_logs 
                WHERE id NOT IN (
                    SELECT id FROM system_logs ORDER BY timestamp DESC LIMIT 100
                )
            """)

            conn.commit()

        total_deleted = sum(deleted.values())
        core.log_system_event("WARNING", "settings", 
            f"RESET INSTALL executado: {total_deleted} registros removidos de {len([v for v in deleted.values() if v > 0])} tabelas")

        return {
            "status": "success",
            "message": "Sistema resetado para estado de instalação limpa",
            "deleted": deleted,
            "settings_reset": settings_reset,
            "total_records_deleted": total_deleted
        }

    except Exception as e:
        logger.error(f"Error in reset install: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/")
async def get_all_settings() -> Dict[str, Any]:
    """Obtém todas as configurações"""
    try:
        core = get_shared_core()
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT category, key, value, type, description, updated_at
                FROM settings 
                ORDER BY category, key
            """)
            
            settings_by_category = {}
            for row in cursor.fetchall():
                category = row[0]
                if category not in settings_by_category:
                    settings_by_category[category] = {}
                
                settings_by_category[category][row[1]] = {
                    "value": _deserialize_value(row[2], row[3]),
                    "type": row[3],
                    "description": row[4],
                    "updated_at": row[5]
                }
        
        return {
            "settings": settings_by_category,
            "categories": list(settings_by_category.keys()),
            "total_settings": sum(len(cat) for cat in settings_by_category.values())
        }
        
    except Exception as e:
        logger.error(f"Error getting settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{category}")
async def get_category_settings(category: str) -> Dict[str, Any]:
    """Obtém configurações de uma categoria específica"""
    try:
        core = get_shared_core()
        
        valid_categories = ["general", "backup", "reports", "notifications", "performance", "security"]
        if category not in valid_categories:
            raise HTTPException(status_code=400, detail=f"Categoria inválida. Use: {', '.join(valid_categories)}")
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT key, value, type, description, updated_at
                FROM settings 
                WHERE category = %s
                ORDER BY key
            """, (category,))
            
            settings = {}
            for row in cursor.fetchall():
                settings[row[0]] = {
                    "value": _deserialize_value(row[1], row[2]),
                    "type": row[2],
                    "description": row[3],
                    "updated_at": row[4]
                }
        
        return {
            "category": category,
            "settings": settings,
            "total": len(settings)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting category settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{category}/{key}")
async def update_setting(category: str, key: str, request: Request) -> Dict[str, Any]:
    """Atualiza configuração específica"""
    try:
        data = await request.json()
        core = get_shared_core()
        
        if "value" not in data:
            raise HTTPException(status_code=400, detail="Campo 'value' é obrigatório")
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT type, value FROM settings 
                WHERE category = %s AND key = %s
            """, (category, key))
            
            existing = cursor.fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Configuração não encontrada")
            
            setting_type = existing[0]
            
            validated_value = _validate_setting_value(data["value"], setting_type)
            serialized_value = _serialize_value(validated_value)
            
            cursor.execute("""
                UPDATE settings 
                SET value = %s, updated_at = %s
                WHERE category = %s AND key = %s
            """, (serialized_value, datetime.now().isoformat(), category, key))
            conn.commit()
        
            if hasattr(core, 'update_agent_setting'):
                core.update_agent_setting(category, key, validated_value)
            elif hasattr(core, 'agent_settings'):
                if category not in core.agent_settings:
                    core.agent_settings[category] = {}
                core.agent_settings[category][key] = validated_value
        
        core.log_system_event("INFO", "settings", f"Setting updated: {category}.{key}")
        
        return {
            "success": True,
            "message": f"Configuração {category}.{key} atualizada com sucesso",
            "old_value": _deserialize_value(existing[1], setting_type) if len(existing) > 1 else None,
            "new_value": validated_value
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating setting {category}.{key}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/bulk-update")
async def bulk_update_settings(request: Request) -> Dict[str, Any]:
    """Atualiza múltiplas configurações"""
    try:
        data = await request.json()
        core = get_shared_core()
        
        settings_data = data.get("settings", {})
        if not settings_data:
            raise HTTPException(status_code=400, detail="Campo 'settings' é obrigatório")
        
        updated_count = 0
        errors = []
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            for category, category_settings in settings_data.items():
                for key, value_data in category_settings.items():
                    try:
                        cursor.execute("""
                            SELECT type FROM settings 
                            WHERE category = %s AND key = %s
                        """, (category, key))
                        
                        existing = cursor.fetchone()
                        if not existing:
                            errors.append(f"Setting not found: {category}.{key}")
                            continue
                        
                        setting_type = existing[0]
                        value = value_data if not isinstance(value_data, dict) else value_data.get("value")
                        
                        validated_value = _validate_setting_value(value, setting_type)
                        serialized_value = _serialize_value(validated_value)
                        
                        cursor.execute("""
                            UPDATE settings 
                            SET value = %s, updated_at = %s
                            WHERE category = %s AND key = %s
                        """, (serialized_value, datetime.now().isoformat(), category, key))
                        
                        if hasattr(core, 'update_agent_setting'):
                            core.update_agent_setting(category, key, validated_value)
                        elif hasattr(core, 'agent_settings'):
                            if category not in core.agent_settings:
                                core.agent_settings[category] = {}
                            core.agent_settings[category][key] = validated_value
                        
                        updated_count += 1
                        
                    except Exception as e:
                        errors.append(f"Error updating {category}.{key}: {str(e)}")
            
            conn.commit()
        
        core.log_system_event("INFO", "settings", f"Bulk update: {updated_count} settings updated")
        
        return {
            "success": True,
            "updated_count": updated_count,
            "errors": errors,
            "message": f"{updated_count} configurações atualizadas com sucesso"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk settings update: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reset/{category}")
async def reset_category_settings(category: str) -> Dict[str, Any]:
    """Reseta configurações de uma categoria para valores padrão"""
    try:
        core = get_shared_core()
        
        defaults = _get_default_settings()
        
        if category not in defaults:
            raise HTTPException(status_code=400, detail=f"Categoria inválida: {category}")
        
        updated_count = 0
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            for key, config in defaults[category].items():
                serialized_value = _serialize_value(config["default"])
                
                cursor.execute("""
                    UPDATE settings 
                    SET value = %s, updated_at = %s
                    WHERE category = %s AND key = %s
                """, (serialized_value, datetime.now().isoformat(), category, key))
                
                if hasattr(core, 'update_agent_setting'):
                    core.update_agent_setting(category, key, config["default"])
                elif hasattr(core, 'agent_settings'):
                    if category not in core.agent_settings:
                        core.agent_settings[category] = {}
                    core.agent_settings[category][key] = config["default"]
                
                updated_count += 1
            
            conn.commit()
        
        core.log_system_event("INFO", "settings", f"Category reset: {category} ({updated_count} settings)")
        
        return {
            "success": True,
            "updated_count": updated_count,
            "message": f"Configurações da categoria '{category}' resetadas para valores padrão"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting category {category}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/schema")
async def get_settings_schema() -> Dict[str, Any]:
    """Obtém esquema das configurações disponíveis"""
    try:
        defaults = _get_default_settings()
        
        schema = {}
        for category, settings in defaults.items():
            schema[category] = {
                "title": _get_category_title(category),
                "description": _get_category_description(category),
                "settings": {}
            }
            
            for key, config in settings.items():
                schema[category]["settings"][key] = {
                    "type": config["type"],
                    "description": config["description"],
                    "default": config["default"],
                    "required": config.get("required", False),
                    "options": config.get("options"),
                    "min": config.get("min"),
                    "max": config.get("max")
                }
        
        return {
            "schema": schema,
            "categories": list(schema.keys())
        }
        
    except Exception as e:
        logger.error(f"Error getting settings schema: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/export")
async def export_settings() -> Dict[str, Any]:
    """Exporta configurações atuais"""
    try:
        core = get_shared_core()
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT category, key, value, type
                FROM settings 
                ORDER BY category, key
            """)
            
            export_data = {
                "metadata": {
                    "exported_at": datetime.now().isoformat(),
                    "agent_version": "7.5a.0",
                    "export_version": "1.0"
                },
                "settings": {}
            }
            
            for row in cursor.fetchall():
                category = row[0]
                if category not in export_data["settings"]:
                    export_data["settings"][category] = {}
                
                export_data["settings"][category][row[1]] = _deserialize_value(row[2], row[3])
        
        return export_data
        
    except Exception as e:
        logger.error(f"Error exporting settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import")
async def import_settings(request: Request) -> Dict[str, Any]:
    """Importa configurações"""
    try:
        data = await request.json()
        core = get_shared_core()
        
        if "settings" not in data:
            raise HTTPException(status_code=400, detail="Campo 'settings' é obrigatório")
        
        settings_data = data["settings"]
        imported_count = 0
        errors = []
        
        with core.get_db_connection() as conn:
            cursor = conn.cursor()
            for category, category_settings in settings_data.items():
                for key, value in category_settings.items():
                    try:
                        cursor.execute("""
                            SELECT type FROM settings 
                            WHERE category = %s AND key = %s
                        """, (category, key))
                        
                        existing = cursor.fetchone()
                        if not existing:
                            errors.append(f"Setting not found: {category}.{key}")
                            continue
                        
                        setting_type = existing[0]
                        
                        validated_value = _validate_setting_value(value, setting_type)
                        serialized_value = _serialize_value(validated_value)
                        
                        cursor.execute("""
                            UPDATE settings 
                            SET value = %s, updated_at = %s
                            WHERE category = %s AND key = %s
                        """, (serialized_value, datetime.now().isoformat(), category, key))
                        
                        if hasattr(core, 'update_agent_setting'):
                            core.update_agent_setting(category, key, validated_value)
                        elif hasattr(core, 'agent_settings'):
                            if category not in core.agent_settings:
                                core.agent_settings[category] = {}
                            core.agent_settings[category][key] = validated_value
                        
                        imported_count += 1
                        
                    except Exception as e:
                        errors.append(f"Error importing {category}.{key}: {str(e)}")
            
            conn.commit()
        
        core.log_system_event("INFO", "settings", f"Settings imported: {imported_count} settings")
        
        return {
            "success": True,
            "imported_count": imported_count,
            "errors": errors,
            "message": f"{imported_count} configurações importadas com sucesso"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importing settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Funções auxiliares
def _get_default_settings() -> Dict[str, Dict[str, Any]]:
    """Retorna configurações padrão"""
    return {
        "general": {
            "agent_name": {
                "type": "string",
                "default": "GBOC Agent",
                "description": "Nome do agente"
            },
            "log_level": {
                "type": "string", 
                "default": "INFO",
                "description": "Nível de log",
                "options": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            },
            "max_log_files": {
                "type": "integer",
                "default": 10,
                "description": "Máximo de arquivos de log",
                "min": 1,
                "max": 100
            },
            "auto_start_scheduler": {
                "type": "boolean",
                "default": True,
                "description": "Iniciar scheduler automaticamente"
            }
        },
        "backup": {
            "default_engine": {
                "type": "string",
                "default": "restic",
                "description": "Motor de backup padrão",
                "options": ["restic", "kopia", "duplicati"]
            },
            "compression_level": {
                "type": "integer",
                "default": 6,
                "description": "Nível de compressão (1-9)",
                "min": 1,
                "max": 9
            },
            "encryption_enabled": {
                "type": "boolean",
                "default": True,
                "description": "Habilitar criptografia por padrão"
            },
            "parallel_uploads": {
                "type": "integer",
                "default": 4,
                "description": "Uploads paralelos",
                "min": 1,
                "max": 16
            },
            "retry_attempts": {
                "type": "integer",
                "default": 3,
                "description": "Tentativas em caso de falha",
                "min": 1,
                "max": 10
            },
            "timeout_minutes": {
                "type": "integer",
                "default": 120,
                "description": "Timeout em minutos",
                "min": 5,
                "max": 1440
            }
        },
        "reports": {
            "cloud_storage_cost_usd_per_tb": {
                "type": "number",
                "default": 7.99,
                "description": "Tarifa Base Cloud Storage ($ USD / TB / mês)",
                "min": 0.01,
                "max": 999.0
            },
            "auto_currency_conversion": {
                "type": "boolean",
                "default": True,
                "description": "Conversão Automática de Câmbio (USD -> BRL)"
            }
        },
        "notifications": {
            "enabled": {
                "type": "boolean",
                "default": False,
                "description": "Habilitar notificações"
            },
            "notify_success": {
                "type": "boolean", 
                "default": False,
                "description": "Notificar em caso de sucesso"
            },
            "notify_failure": {
                "type": "boolean",
                "default": True,
                "description": "Notificar em caso de falha"
            },
            "notify_warning": {
                "type": "boolean",
                "default": True,
                "description": "Notificar avisos"
            },
            "webhook_enabled": {
                "type": "boolean",
                "default": False,
                "description": "Habilitar webhook"
            },
            "webhook_url": {
                "type": "string",
                "default": "",
                "description": "URL do webhook"
            },
            "email_enabled": {
                "type": "boolean",
                "default": False,
                "description": "Habilitar email"
            }
        },
        "performance": {
            "max_concurrent_tasks": {
                "type": "integer",
                "default": 3,
                "description": "Máximo de tarefas simultâneas",
                "min": 1,
                "max": 10
            },
            "cpu_limit_percent": {
                "type": "integer",
                "default": 80,
                "description": "Limite de uso de CPU (%)",
                "min": 10,
                "max": 100
            },
            "memory_limit_gb": {
                "type": "number",
                "default": 2.0,
                "description": "Limite de memória (GB)",
                "min": 0.5,
                "max": 32.0
            },
            "disk_check_interval": {
                "type": "integer",
                "default": 300,
                "description": "Intervalo de verificação de disco (segundos)",
                "min": 60,
                "max": 3600
            }
        },
        "security": {
            "require_auth": {
                "type": "boolean",
                "default": False,
                "description": "Requerer autenticação"
            },
            "session_timeout": {
                "type": "integer",
                "default": 3600,
                "description": "Timeout da sessão (segundos)",
                "min": 300,
                "max": 86400
            },
            "allowed_ips": {
                "type": "string",
                "default": "127.0.0.1,::1",
                "description": "IPs permitidos (separados por vírgula)"
            },
            "audit_enabled": {
                "type": "boolean",
                "default": True,
                "description": "Habilitar auditoria"
            }
        }
    }

def _get_category_title(category: str) -> str:
    """Título da categoria"""
    titles = {
        "general": "Configurações Gerais",
        "backup": "Backup e Restauração", 
        "reports": "Relatórios",
        "notifications": "Notificações",
        "performance": "Performance",
        "security": "Segurança"
    }
    return titles.get(category, category.title())

def _get_category_description(category: str) -> str:
    """Descrição da categoria"""
    descriptions = {
        "general": "Configurações básicas do agente",
        "backup": "Configurações de backup e restauração",
        "notifications": "Sistema de notificações e alertas",
        "performance": "Configurações de performance e recursos",
        "security": "Configurações de segurança e acesso"
    }
    return descriptions.get(category, f"Configurações de {category}")

def _serialize_value(value) -> str:
    """Serializa valor para armazenamento"""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)

def _deserialize_value(value: str, value_type: str):
    """Deserializa valor do armazenamento"""
    try:
        if value_type == "boolean":
            return value.lower() in ("true", "1", "yes", "on")
        elif value_type == "integer":
            return int(value)
        elif value_type == "number":
            return float(value)
        elif value_type in ("dict", "list"):
            return json.loads(value)
        else:  # string
            return value
    except (ValueError, json.JSONDecodeError):
        return value

def _validate_setting_value(value, setting_type: str):
    """Valida tipo do valor"""
    if setting_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)
    
    elif setting_type == "integer":
        return int(value)
    
    elif setting_type == "number":
        return float(value)
    
    elif setting_type in ("dict", "list"):
        if isinstance(value, str):
            return json.loads(value)
        return value
    
    else:  # string
        return str(value)
