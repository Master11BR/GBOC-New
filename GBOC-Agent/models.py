#!/usr/bin/env python3
"""
📋 GBOC Agent 13.2.0 - MODELS
Estrutura de dados e validação Pydantic
✅ CORRIGIDO: Modelos de repositório flexíveis para criação/edição
"""

from pydantic import BaseModel, Field, validator, ConfigDict
from typing import Dict, Any, List, Optional, Union, Literal
from datetime import datetime
from enum import Enum


class RepositoryType(str, Enum):
    LOCAL = "local"  # Para motores locais: kopia, restic, duplicati
    CLOUD = "cloud"  # Para provedores nuvem: b2, s3, azure, wasabi


class LocalRepository(BaseModel):
    """Modelo específico para repositórios locais"""
    type: Literal["local"] = "local"
    name: str = Field(..., min_length=1, max_length=100)
    engine: str = Field(..., description="Motor de backup: kopia, restic, duplicati, native")
    motor_password: str = Field(..., min_length=1, alias="encryption_password")
    path: Optional[str] = Field(None, description="Caminho local do repositório")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class CloudRepository(BaseModel):
    """Modelo específico para repositórios cloud"""
    type: Literal["cloud"] = "cloud"
    name: str = Field(..., min_length=1, max_length=100)
    engine: str = Field(default="s3", description="Provedor cloud: b2, s3, azure, wasabi")
    motor_password: str = Field(..., min_length=1, alias="encryption_password")

    # Campos específicos de cloud
    bucket: Optional[str] = None
    region: Optional[str] = None
    endpoint: Optional[str] = None
    access_key: Optional[str] = None
    cloud_password: Optional[str] = None

    # Campos específicos de providers
    b2_account_id: Optional[str] = None
    b2_account_key: Optional[str] = None
    aws_access_key: Optional[str] = None
    aws_secret_key: Optional[str] = None
    azure_account_name: Optional[str] = None
    azure_account_key: Optional[str] = None
    gcs_project_id: Optional[str] = None
    gcs_credentials: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class TaskType(str, Enum):
    BACKUP = "backup"
    RESTORE = "restore"
    SYNC = "sync"
    CLEANUP = "cleanup"
    VERIFY = "verify"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SCHEDULED = "scheduled"
    INTERRUPTED = "interrupted"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    ERROR = "error"


# ==============================================================================
# Repository Models - CORRIGIDOS
# ==============================================================================

class RepositoryCreate(BaseModel):
    """
    Modelo para criação de repositório usando discriminated union.
    Suporta tanto repositórios locais quanto cloud.
    """
    repository: Union[LocalRepository, CloudRepository] = Field(..., discriminator='type')

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    @property
    def type(self) -> str:
        """Retorna o tipo do repositório"""
        if isinstance(self.repository, LocalRepository):
            return "local"
        elif isinstance(self.repository, CloudRepository):
            return "cloud"
        return "unknown"

    @property
    def name(self) -> str:
        return self.repository.name

    @property
    def engine(self) -> str:
        return self.repository.engine

    @property
    def motor_password(self) -> str:
        return self.repository.motor_password

    def get_type(self) -> str:
        """Compatibilidade backward"""
        return self.type


class RepositoryUpdate(BaseModel):
    """
    Modelo para atualização de repositório.
    Todos os campos são opcionais.
    NOTA: encryption_password NÃO pode ser alterado.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    bucket: Optional[str] = None
    path: Optional[str] = None
    region: Optional[str] = None
    endpoint: Optional[str] = None
    access_key: Optional[str] = None
    cloud_password: Optional[str] = None
    
    # Campos específicos de providers
    b2_account_id: Optional[str] = None
    b2_account_key: Optional[str] = None
    aws_access_key: Optional[str] = None
    aws_secret_key: Optional[str] = None
    azure_account_name: Optional[str] = None
    azure_account_key: Optional[str] = None
    
    model_config = ConfigDict(extra="allow")


class RepositoryResponse(BaseModel):
    """Modelo para listagem (seguro, sem senhas sensíveis)"""
    id: int
    name: str
    type: str
    engine: str
    status: Optional[str] = "unknown"
    path: Optional[str] = None
    bucket: Optional[str] = None
    region: Optional[str] = None
    endpoint: Optional[str] = None
    initialized: Optional[bool] = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True, extra="allow")


# ==============================================================================
# Task Models
# ==============================================================================

class TaskBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: Optional[str] = "backup"
    description: Optional[str] = Field(None, max_length=500)
    repository_id: Optional[int] = None
    source_paths: Optional[str] = None  # String com paths separados por newline
    exclude_patterns: Optional[str] = None
    priority: Optional[str] = "normal"
    pre_script: Optional[str] = None
    post_script: Optional[str] = None


class TaskCreate(TaskBase):
    engine: Optional[str] = "restic"
    schedule_cron: Optional[str] = None
    schedule_enabled: bool = Field(default=False)
    config: Optional[Dict[str, Any]] = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    source_paths: Optional[str] = None
    exclude_patterns: Optional[str] = None
    schedule_cron: Optional[str] = None
    schedule_enabled: Optional[bool] = None
    enabled: Optional[bool] = None
    priority: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    pre_script: Optional[str] = None
    post_script: Optional[str] = None


class TaskResponse(BaseModel):
    id: int
    name: str
    type: Optional[str] = "backup"
    status: Optional[str] = "idle"
    repository_id: Optional[int] = None
    repository_name: Optional[str] = None
    source_paths: Optional[str] = None
    engine: Optional[str] = "restic"
    schedule_enabled: Optional[bool] = False
    schedule_cron: Optional[str] = None
    enabled: Optional[bool] = True
    pre_script: Optional[str] = None
    post_script: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_run: Optional[str] = None
    last_status: Optional[str] = None
    run_count: Optional[int] = 0
    success_count: Optional[int] = 0
    
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Task Execution Models
# ==============================================================================

class TaskExecutionResponse(BaseModel):
    id: int
    task_id: int
    task_name: Optional[str] = None
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    bytes_processed: int = 0
    files_processed: int = 0
    progress: int = 0
    current_file: Optional[str] = None
    error_message: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Alert Models
# ==============================================================================

class AlertCreate(BaseModel):
    type: str = Field(..., min_length=1)
    severity: AlertSeverity
    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=1000)
    source: str = Field(default="system")
    details: Optional[str] = Field(None, max_length=5000)


class AlertResponse(BaseModel):
    id: int
    timestamp: Optional[str] = None
    type: str
    severity: str
    title: str
    message: str
    source: str
    acknowledged: bool = False
    resolved: bool = False
    details: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Settings Models
# ==============================================================================

class SettingsCategory(str, Enum):
    GENERAL = "general"
    BACKUP = "backup"
    NOTIFICATIONS = "notifications"
    PERFORMANCE = "performance"
    SECURITY = "security"


class SettingUpdate(BaseModel):
    category: Optional[str] = None
    key: str = Field(..., min_length=1)
    value: Any


class SettingsResponse(BaseModel):
    category: Optional[str] = None
    key: str
    value: Any
    updated_at: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Diagnostic Models
# ==============================================================================

class SystemMetrics(BaseModel):
    cpu_usage: float = Field(..., ge=0, le=100)
    memory_usage: float = Field(..., ge=0, le=100)
    disk_usage: float = Field(..., ge=0, le=100)
    system_health: int = Field(..., ge=0, le=100)
    details: Optional[Dict[str, Any]] = Field(default_factory=dict)


class DiagnosticResponse(BaseModel):
    timestamp: Optional[str] = None
    category: str
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    disk_usage: Optional[float] = None
    system_health: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Overview Models
# ==============================================================================

class OverviewResponse(BaseModel):
    timestamp: Optional[str] = None
    agent_info: Dict[str, Any]
    system_metrics: Dict[str, Any]
    health_score: Dict[str, Any]
    summary: Dict[str, Any]
    recent_alerts: List[AlertResponse]
    quick_actions: List[Dict[str, str]]


# ==============================================================================
# Log Models
# ==============================================================================

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogEntry(BaseModel):
    timestamp: Optional[str] = None
    level: str
    module: Optional[str] = None
    message: str
    details: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Generic Response Models
# ==============================================================================

class SuccessResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    details: Optional[str] = None


class ListResponse(BaseModel):
    items: List[Any]
    total: int
    page: int = 1
    per_page: int = 50


# ==============================================================================
# Health Check Models
# ==============================================================================

class HealthCheck(BaseModel):
    healthy: bool
    message: str
    details: Optional[Dict[str, Any]] = None


class SystemHealth(BaseModel):
    timestamp: Optional[str] = None
    overall_healthy: bool
    status: str
    uptime_seconds: float
    checks: Dict[str, HealthCheck]

