# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: Main Aggregator for API v2 (Agent)
# ==============================================================================

from fastapi import APIRouter
from modules.v2.telemetry_v2_router import router as telemetry_router
from modules.v2.repositories_v2_router import router as repositories_router
from modules.v2.tasks_v2_router import router as tasks_router

v2_router = APIRouter(prefix="/api/v2")
v2_router.include_router(telemetry_router)
v2_router.include_router(repositories_router)
v2_router.include_router(tasks_router)
