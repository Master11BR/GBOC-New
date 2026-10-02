# GBOC System v14.7.3 Enterprise Edition
# Module: Analytics Router
#
# GET /api/v1/analytics/comprehensive é implementado em server_gboc.py com dados reais do
# PostgreSQL (agents, agent_task_executions). A versão anterior deste módulo retornava valores
# fixos (12 agentes, 100% de sucesso) — removida por violar a Política Zero-Mock (AI_RULES.md §11).
# Este roteador permanece registrado para futuras rotas de analytics modularizadas.

import logging
from fastapi import APIRouter

logger = logging.getLogger("gboc_analytics_module")
router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])
