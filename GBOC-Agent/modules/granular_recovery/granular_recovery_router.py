# ==============================================================================
# GBOC System v14.1.0 Enterprise Edition
# Module: Granular Item-Level Recovery Router (SQL, AD, Databases)
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================

import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import JSONResponse

from engines.sql_granular_explorer import sql_granular_explorer
from engines.ad_granular_explorer import ad_granular_explorer

logger = logging.getLogger("gboc_granular_recovery_router")
router = APIRouter(prefix="/api/v1/granular-recovery", tags=["Granular Item-Level Recovery"])


class InspectPgDumpRequest(BaseModel):
    dump_file_path: str


class RestorePgTableRequest(BaseModel):
    dump_file_path: str
    table_name: str
    target_db: str
    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"


class InspectSqliteRequest(BaseModel):
    database_file: str


class ExtractSqliteTableRequest(BaseModel):
    source_database: str
    table_name: str
    destination_database: str


class MssqlListTablesRequest(BaseModel):
    server: str = "localhost"
    database: str = "master"
    user: Optional[str] = None
    password: Optional[str] = None
    trusted_connection: bool = True


class AdRestoreObjectRequest(BaseModel):
    object_dn: str
    object_type: str = "User"
    password_reset: Optional[str] = None


# ── PostgreSQL Granular ───────────────────────────────────────────────────────

@router.post("/postgres/inspect")
async def inspect_postgres_dump(req: InspectPgDumpRequest):
    """Lê o Table of Contents (TOC) de um arquivo dump do PostgreSQL sem restaurar a base."""
    try:
        res = sql_granular_explorer.inspect_postgres_dump(req.dump_file_path)
        return JSONResponse(res)
    except FileNotFoundError as fnf:
        return JSONResponse(status_code=404, content={"status": "error", "error": str(fnf)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})


@router.post("/postgres/restore-table")
async def restore_postgres_table(req: RestorePgTableRequest):
    """Restaura cirurgicamente apenas UMA tabela a partir de um dump PostgreSQL."""
    try:
        res = sql_granular_explorer.restore_postgres_single_table(
            dump_file_path=req.dump_file_path,
            table_name=req.table_name,
            target_db=req.target_db,
            host=req.host,
            port=req.port,
            user=req.user
        )
        if res.get("status") != "success":
            return JSONResponse(status_code=400, content=res)
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})


# ── SQLite Granular ───────────────────────────────────────────────────────────

@router.post("/sqlite/inspect")
async def inspect_sqlite_tables(req: InspectSqliteRequest):
    """Lista todas as tabelas e contagem de linhas reais em arquivo SQLite."""
    try:
        res = sql_granular_explorer.inspect_sqlite_tables(req.database_file)
        return JSONResponse(res)
    except FileNotFoundError as fnf:
        return JSONResponse(status_code=404, content={"status": "error", "error": str(fnf)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})


@router.post("/sqlite/extract-table")
async def extract_sqlite_table(req: ExtractSqliteTableRequest):
    """Extrai cirurgicamente uma tabela de banco SQLite para um novo arquivo."""
    try:
        res = sql_granular_explorer.extract_sqlite_table_to_new_db(
            source_db=req.source_database,
            table_name=req.table_name,
            destination_db=req.destination_database
        )
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})


# ── Microsoft SQL Server Granular ─────────────────────────────────────────────

@router.post("/mssql/tables")
async def list_mssql_tables(req: MssqlListTablesRequest):
    """Consulta schemas e contagem de linhas reais em banco Microsoft SQL Server."""
    res = sql_granular_explorer.list_mssql_tables(
        server=req.server,
        database=req.database,
        user=req.user,
        password=req.password,
        trusted_connection=req.trusted_connection
    )
    return JSONResponse(res)


# ── Active Directory Granular ─────────────────────────────────────────────────

@router.get("/ad/objects")
async def list_ad_objects(filter: str = Query("all"), search: str = Query("")):
    """Pesquisa objetos granulares do Active Directory (Usuários, Grupos, GPOs)."""
    res = ad_granular_explorer.list_ad_objects_from_live_or_snapshot(
        filter_type=filter,
        search_query=search
    )
    return JSONResponse(res)


@router.post("/ad/restore-object")
async def restore_ad_object(req: AdRestoreObjectRequest):
    """Restaura granularmente um objeto no Active Directory a partir do Recycle Bin ou NTDS."""
    res = ad_granular_explorer.restore_granular_ad_object(
        object_dn=req.object_dn,
        object_type=req.object_type,
        password_reset=req.password_reset
    )
    return JSONResponse(res)
