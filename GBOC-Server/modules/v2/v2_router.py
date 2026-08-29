# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Module: Main Aggregator for API v2 (Server)
# ==============================================================================

from fastapi import APIRouter
from modules.v2.system_v2_router import router as system_router
from modules.v2.agents_v2_router import router as agents_router
from modules.v2.tasks_v2_router import router as tasks_router

v2_router = APIRouter(prefix="/api/v2")
v2_router.include_router(system_router)
v2_router.include_router(agents_router)
v2_router.include_router(tasks_router)
