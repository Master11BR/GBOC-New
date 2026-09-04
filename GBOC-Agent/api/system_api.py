#!/usr/bin/env python3
"""
GBOC 14.0.0 - API de Sistema Completo
Endpoint para diagnóstico completo do sistema
"""

from fastapi import APIRouter, HTTPException
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/system", tags=["System Management"])

@router.get("/info")
@router.get("/version")
async def get_system_version_info():
    """Retorna a versão oficial dinâmica e dados de versão do Agente GBOC."""
    return {
        "status": "success",
        "version": "14.0.0",
        "gboc_version": "14.0.0",
        "app_name": "GBOC Agent Enterprise",
        "build_date": "2026-09-02"
    }

@router.get("/diagnostic")
async def run_full_diagnostic():
    """Executa diagnóstico completo do sistema"""
    try:
        from utils.diagnostic_report import SystemDiagnostic
        
        diagnostic = SystemDiagnostic()
        report = diagnostic.run_complete_diagnostic()
        
        return {"status": "success", "data": report}
        
    except Exception as e:
        logger.error(f"Error running diagnostic: {e}")
        raise HTTPException(500, str(e))

@router.get("/orphan-files")
async def scan_orphan_files():
    """Escaneia arquivos órfãos"""
    try:
        from utils.orphan_file_detector import OrphanFileDetector
        
        detector = OrphanFileDetector()
        report = detector.scan_system()
        
        return {"status": "success", "data": report}
        
    except Exception as e:
        logger.error(f"Error scanning orphan files: {e}")
        raise HTTPException(500, str(e))

@router.post("/version/unify")
async def unify_versions():
    """Unifica versões do sistema para 14.0.0"""
    try:
        from utils.version_unifier import VersionUnifier
        
        unifier = VersionUnifier()
        success = unifier.unify_versions()
        
        return {
            "status": "success" if success else "error",
            "updated_files": unifier.updated_files,
            "failed_updates": unifier.failed_updates
        }
        
    except Exception as e:
        logger.error(f"Error unifying versions: {e}")
        raise HTTPException(500, str(e))

@router.get("/info")
async def get_system_info():
    """Obtém informações do sistema"""
    try:
        import platform
        import psutil
        import os as _os
        from shared_core import GBOC_VERSION, DATA_DIR

        # Usar o diretório de dados como referência de disco (funciona no Windows e Linux)
        _data_dir = DATA_DIR if _os.path.exists(DATA_DIR) else (_os.path.splitdrive(DATA_DIR)[0] + "\\" if platform.system() == 'Windows' else '/')
        try:
            _disk = psutil.disk_usage(_data_dir)
            disk_total_gb = round(_disk.total / (1024**3), 2)
            disk_used_gb = round(_disk.used / (1024**3), 2)
            disk_percent = _disk.percent
        except Exception:
            disk_total_gb = disk_used_gb = disk_percent = 0

        # CPU count: logical + physical
        cpu_logical = psutil.cpu_count(logical=True)
        cpu_physical = psutil.cpu_count(logical=False)

        return {
            "status": "success",
            "system": {
                "platform": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "hostname": platform.node(),
                "python_version": platform.python_version()
            },
            "resources": {
                "cpu_count": cpu_logical,
                "cpu_physical": cpu_physical,
                "cpu_percent": psutil.cpu_percent(interval=1),
                "cpu_per_core": psutil.cpu_percent(interval=0.5, percpu=True),
                "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
                "memory_used_gb": round(psutil.virtual_memory().used / (1024**3), 2),
                "memory_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_total_gb": disk_total_gb,
                "disk_used_gb": disk_used_gb,
                "disk_percent": disk_percent
            },
            "gboc_version": GBOC_VERSION
        }

    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        raise HTTPException(500, str(e))

@router.get("/health")
async def get_system_health():
    """Obtém saúde geral do sistema"""
    try:
        import psutil
        import os as _os
        import platform
        from shared_core import get_shared_core, USE_POSTGRESQL, DATA_DIR

        # Disco: usar diretório de dados como referência (Windows-safe)
        _data_dir = DATA_DIR if _os.path.exists(DATA_DIR) else (_os.path.splitdrive(DATA_DIR)[0] + "\\" if platform.system() == 'Windows' else '/')
        try:
            _disk = psutil.disk_usage(_data_dir)
            disk_percent = _disk.percent
        except Exception:
            disk_percent = 0

        cpu_percent = psutil.cpu_percent(interval=1)
        memory_percent = psutil.virtual_memory().percent

        # Verificar banco de dados (PostgreSQL ou SQLite)
        db_ok = False
        db_type = "postgresql" if USE_POSTGRESQL else "sqlite"
        db_detail = ""
        try:
            core = get_shared_core()
            with core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.close()
            db_ok = True
        except Exception as db_err:
            db_detail = str(db_err)[:120]

        # Calcular health score
        health_score = 100
        if cpu_percent > 80:
            health_score -= 20
        elif cpu_percent > 60:
            health_score -= 10

        if memory_percent > 85:
            health_score -= 20
        elif memory_percent > 70:
            health_score -= 10

        if disk_percent > 90:
            health_score -= 30
        elif disk_percent > 80:
            health_score -= 15

        if not db_ok:
            health_score -= 50

        health_status = "healthy"
        if health_score < 50:
            health_status = "critical"
        elif health_score < 70:
            health_status = "warning"
        elif health_score < 85:
            health_status = "good"

        return {
            "status": "success",
            "health_score": max(0, health_score),
            "health_status": health_status,
            "metrics": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "disk_percent": disk_percent,
                "database_ok": db_ok,
                "database_type": db_type,
                "database_error": db_detail if not db_ok else None
            }
        }

    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        raise HTTPException(500, str(e))

@router.get("/health/schema")
async def get_schema_health():
    """Valida presença de tabelas/colunas críticas do schema do agente."""
    try:
        from shared_core import get_shared_core, USE_POSTGRESQL
        core = get_shared_core()

        required_tables = [
            "repositories", "tasks", "task_executions", "backup_statistics", "settings", "system_logs"
        ]

        required_columns = {
            "repositories": ["id", "name", "type", "engine", "path", "motor_password", "encryption_password"],
            "tasks": ["id", "name", "repository_id", "source_paths", "engine", "type", "schedule_enabled", "schedule_cron", "updated_at"],
            "task_executions": ["id", "task_id", "status", "started_at", "completed_at", "bytes_processed", "files_processed"],
            "settings": ["key", "value", "category", "type", "description"],
            "system_logs": ["timestamp", "level", "source", "message"]
        }

        missing_tables = []
        missing_columns = {}

        with core.get_db_connection() as conn:
            cur = conn.cursor()

            if USE_POSTGRESQL:
                # Tabelas
                cur.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                """)
                existing_tables = {row[0] for row in cur.fetchall()}

                for table in required_tables:
                    if table not in existing_tables:
                        missing_tables.append(table)

                # Colunas
                for table, cols in required_columns.items():
                    if table in existing_tables:
                        cur.execute("""
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = %s
                        """, (table,))
                        existing_cols = {row[0] for row in cur.fetchall()}
                        table_missing = [c for c in cols if c not in existing_cols]
                        if table_missing:
                            missing_columns[table] = table_missing
            else:
                # SQLite fallback
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                existing_tables = {row[0] for row in cur.fetchall()}

                for table in required_tables:
                    if table not in existing_tables:
                        missing_tables.append(table)

                for table, cols in required_columns.items():
                    if table in existing_tables:
                        cur.execute(f"PRAGMA table_info({table})")
                        existing_cols = {row[1] for row in cur.fetchall()}
                        table_missing = [c for c in cols if c not in existing_cols]
                        if table_missing:
                            missing_columns[table] = table_missing

            try:
                cur.close()
            except Exception:
                pass

        is_ok = len(missing_tables) == 0 and len(missing_columns) == 0

        return {
            "status": "success",
            "schema_ok": is_ok,
            "database": "postgresql" if USE_POSTGRESQL else "sqlite",
            "missing_tables": missing_tables,
            "missing_columns": missing_columns
        }

    except Exception as e:
        logger.error(f"Error checking schema health: {e}")
        raise HTTPException(500, str(e))


@router.get("/changelog")
async def get_changelog():
    """Retorna o conteúdo do CHANGELOG.md"""
    import os
    from datetime import datetime

    base_dir = Path(__file__).resolve().parent.parent
    changelog_path = base_dir / "docs" / "CHANGELOG.md"

    if not changelog_path.exists():
        raise HTTPException(404, "CHANGELOG.md não encontrado")

    try:
        content = changelog_path.read_text(encoding="utf-8")
        stat = changelog_path.stat()
        last_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()

        return {
            "status": "success",
            "content": content,
            "last_modified": last_modified,
            "size": stat.st_size
        }
    except Exception as e:
        logger.error(f"Erro ao ler CHANGELOG.md: {e}")
        raise HTTPException(500, str(e))

