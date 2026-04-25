#!/usr/bin/env python3
"""GBOC Agent - API Errors"""
from fastapi import APIRouter
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/errors", tags=["errors"])

@router.get("/")
async def get_errors(limit: int = 50):
    try:
        from shared_core import get_shared_core
        core = get_shared_core()

        with core.get_db_connection() as conn:
            query = "SELECT * FROM error_log"
            params = []

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, params)
            errors = [dict(row) for row in cursor.fetchall()]

        return {"status": "success", "errors": errors, "count": len(errors)}
    except Exception as e:
        return {"status": "success", "errors": [], "count": 0}
