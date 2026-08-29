"""
GBOC Server - Modelos Pydantic para Validação
Modelos compartilhados para validação de dados
"""
from pydantic import BaseModel, Field, validator, EmailStr, HttpUrl
from typing import Optional, List, Any, Dict
from datetime import datetime

# ===========================
# AUTENTICAÇÃO
# ===========================

class LoginRequest(BaseModel):
    """Requisição de login"""
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=255)

class RefreshTokenRequest(BaseModel):
    """Requisição para renovar access token"""
    refresh_token: str

class AuthResponse(BaseModel):
    """Resposta de autenticação"""
    status: str
    access_token: str
    refresh_token: Optional[str] = None
    user: Optional[Dict[str, Any]] = None
    expires_in: Optional[int] = None

class SetupUserRequest(BaseModel):
    """Requisição para criar primeiro usuário"""
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=255)
    display_name: Optional[str] = Field(None, max_length=255)

# ===========================
# AGENTES
# ===========================

class AgentRegisterRequest(BaseModel):
    """Requisição de registro de agente"""
    agent_id: str = Field(..., min_length=1, max_length=100)
    hostname: str = Field(..., min_length=1, max_length=255)
    ip_address: Optional[str] = None
    os_info: Optional[str] = None
    agent_version: Optional[str] = None
    available_tools: Optional[List[Any]] = []

class AgentHeartbeatRequest(BaseModel):
    """Requisição de heartbeat do agente"""
    agent_id: str = Field(..., min_length=1, max_length=100)
    hostname: str
    status: str
    cpu_usage: Optional[float] = Field(0.0, ge=0, le=100)
    ram_usage: Optional[float] = Field(0.0, ge=0, le=100)
    disk_usage: Optional[float] = Field(0.0, ge=0, le=100)
    timestamp: Optional[str] = None
    jobs_count: Optional[int] = 0
    jobs_summary: Optional[Dict] = None

class AgentMetricsRequest(BaseModel):
    """Requisição de métricas do agente"""
    agent_id: str
    cpu_usage: float = Field(ge=0, le=100)
    ram_usage: float = Field(ge=0, le=100)
    disk_usage: float = Field(ge=0, le=100)
    timestamp: Optional[datetime] = None

# ===========================
# BACKUP & RELATÓRIOS
# ===========================

class BackupReportRequest(BaseModel):
    """Requisição de relatório de backup"""
    agent_id: str = Field(..., min_length=1, max_length=100)
    job_name: Optional[str] = None
    source_path: Optional[str] = None
    backup_type: Optional[str] = "Automated"
    start_time: str
    end_time: str
    duration_seconds: float = Field(ge=0)
    status: str = Field(..., pattern="^(success|failed|partial)$")
    files_new: Optional[int] = 0
    files_changed: Optional[int] = 0
    data_added: Optional[int] = 0
    total_bytes: Optional[int] = 0
    snapshot_id: Optional[str] = None
    error: Optional[str] = None

# ===========================
# WEBHOOKS (ESTRUTURA PRONTA)
# ===========================

class WebhookRegisterRequest(BaseModel):
    """Requisição para registrar webhook"""
    webhook_id: str = Field(..., min_length=1, max_length=100)
    url: HttpUrl
    events: List[str] = Field(..., min_items=1)
    headers: Optional[Dict[str, str]] = None
    active: bool = True

class WebhookEvent(BaseModel):
    """Evento de webhook"""
    event_type: str
    payload: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None

# ===========================
# PAGINAÇÃO
# ===========================

class PaginationParams(BaseModel):
    """Parâmetros de paginação"""
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size

class PaginatedResponse(BaseModel):
    """Resposta paginada genérica"""
    data: List[Dict[str, Any]]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool

# ===========================
# SINCRONIZAÇÃO
# ===========================

class FullSyncRequest(BaseModel):
    """Requisição de sincronização completa"""
    agent_id: str
    repositories: Optional[List[Dict]] = []
    tasks: Optional[List[Dict]] = []
    task_executions: Optional[List[Dict]] = []
    system_events: Optional[List[Dict]] = []
    alerts: Optional[List[Dict]] = []
    timestamp: Optional[str] = None

class ManualSyncRequest(BaseModel):
    """Requisição de sincronização manual"""
    agent_id: str
    sync_type: str = Field(..., pattern="^(full|repositories|tasks|metrics)$")
    since_timestamp: Optional[str] = None

# ===========================
# HEALTH CHECK & MONITORAMENTO
# ===========================

class HealthCheckResponse(BaseModel):
    """Resposta de health check"""
    status: str = Field(..., pattern="^(healthy|degraded|unhealthy)$")
    timestamp: str
    checks: Optional[Dict[str, Any]] = None

class MetricsResponse(BaseModel):
    """Resposta com métricas"""
    uptime_seconds: float
    requests: Dict[str, Any]
    websocket_connections: int
    timestamp: str

# ===========================
# CONFIGURAÇÕES
# ===========================

class SettingUpdateRequest(BaseModel):
    """Requisição para atualizar configuração"""
    category: str = Field(..., min_length=1, max_length=50)
    key: str = Field(..., min_length=1, max_length=100)
    value: str
    type: Optional[str] = "text"

# ===========================
# RESPOSTA PADRÃO
# ===========================

class StandardResponse(BaseModel):
    """Resposta padrão da API"""
    status: str = Field(..., pattern="^(success|error|warning)$")
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None

class ErrorResponse(BaseModel):
    """Resposta de erro"""
    status: str = "error"
    error: str
    error_code: Optional[str] = None
    timestamp: str
