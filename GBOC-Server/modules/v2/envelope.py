# ==============================================================================
# GBOC System v14.0.0 Enterprise Edition
# Module: API v2 Standard Response Envelope
# ==============================================================================

from typing import Generic, TypeVar, Optional, Dict, Any, List
from datetime import datetime, timezone
import uuid
from pydantic import BaseModel, Field, ConfigDict

T = TypeVar("T")

class PaginationMeta(BaseModel):
    model_config = ConfigDict(extra="allow")
    
    total: int = Field(..., description="Total de itens disponíveis")
    page: int = Field(default=1, ge=1, description="Página atual")
    per_page: int = Field(default=20, ge=1, le=500, description="Itens por página")
    total_pages: int = Field(default=1, ge=0, description="Total de páginas calculadas")
    has_next: bool = Field(default=False, description="Existe próxima página")
    has_prev: bool = Field(default=False, description="Existe página anterior")
    sort: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None

class ResponseEnvelope(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="allow")
    
    success: bool = True
    api_version: str = "v2"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation_id: str = Field(default_factory=lambda: f"req-{uuid.uuid4().hex[:10]}")
    execution_time_ms: Optional[float] = None
    data: Optional[T] = None
    meta: Optional[PaginationMeta] = None
    error: Optional[Dict[str, Any]] = None

def build_v2_response(
    data: Any = None,
    meta: Optional[PaginationMeta] = None,
    execution_time_ms: Optional[float] = None,
    correlation_id: Optional[str] = None,
    success: bool = True,
    error: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Helper para construir payloads de resposta v2 serializáveis rapidamente."""
    resp = {
        "success": success,
        "api_version": "v2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id or f"req-{uuid.uuid4().hex[:10]}",
        "data": data
    }
    if execution_time_ms is not None:
        resp["execution_time_ms"] = round(execution_time_ms, 2)
    if meta is not None:
        resp["meta"] = meta.model_dump() if hasattr(meta, "model_dump") else meta
    if error is not None:
        resp["error"] = error
    return resp
