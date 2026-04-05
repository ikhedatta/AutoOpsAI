"""
Shared data models used across the entire agent.

These are *transport* models — lightweight Pydantic schemas that flow between
components.  Persistent document models live in ``agent.store.models``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ServiceState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    RESTARTING = "restarting"
    ERROR = "error"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class IncidentStatus(str, Enum):
    DETECTING = "detecting"
    DIAGNOSING = "diagnosing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    DENIED = "denied"
    DENIED_TIMEOUT = "denied_timeout"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    FAILED = "failed"
    ESCALATED = "escalated"


class ApprovalDecisionType(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    INVESTIGATE = "investigate"
    TIMEOUT = "timeout"
    AUTO = "auto"  # LOW-risk auto-execute


# ---------------------------------------------------------------------------
# Infrastructure models  (from provider-interface.md)
# ---------------------------------------------------------------------------

class ServiceInfo(BaseModel):
    name: str
    platform_id: str
    image: Optional[str] = None
    state: ServiceState
    labels: dict[str, str] = {}
    created_at: Optional[datetime] = None


class ServiceStatus(BaseModel):
    name: str
    state: ServiceState
    uptime_seconds: Optional[float] = None
    restart_count: int = 0
    last_error: Optional[str] = None


class MetricSnapshot(BaseModel):
    service_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cpu_percent: float = 0.0
    memory_used_bytes: int = 0
    memory_limit_bytes: Optional[int] = None
    memory_percent: Optional[float] = None
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0
    extra: dict[str, Any] = {}


class HealthCheckResult(BaseModel):
    service_name: str
    healthy: bool
    response_time_ms: Optional[float] = None
    status_code: Optional[int] = None
    message: Optional[str] = None


class CommandResult(BaseModel):
    success: bool
    output: str = ""
    error: str = ""
    exit_code: Optional[int] = None
    duration_seconds: Optional[float] = None


class LogEntry(BaseModel):
    timestamp: Optional[datetime] = None
    message: str
    level: Optional[str] = None
    source: Optional[str] = None


# ---------------------------------------------------------------------------
# Agent reasoning models
# ---------------------------------------------------------------------------

class Anomaly(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    service_name: str
    anomaly_type: str  # threshold, rate, log_pattern, health_check, compound
    metric: Optional[str] = None
    current_value: Optional[float] = None
    threshold: Optional[float] = None
    severity_hint: Severity = Severity.MEDIUM
    evidence: str = ""
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Diagnosis(BaseModel):
    summary: str
    explanation: str
    confidence: float = 0.0  # 0.0 – 1.0
    root_cause: Optional[str] = None
    playbook_id: Optional[str] = None
    recommended_actions: list[str] = []
    novel: bool = False  # True if no playbook matched


class Action(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    action_type: str  # restart_service, exec_command, scale_service, etc.
    target: str       # service name
    parameters: dict[str, Any] = {}
    description: str = ""
    timeout_seconds: int = 30


class ActionResult(BaseModel):
    action_id: str
    success: bool
    output: str = ""
    error: str = ""
    duration_seconds: float = 0.0


class ApprovalRequest(BaseModel):
    incident_id: str
    severity: Severity
    title: str
    diagnosis_summary: str
    proposed_actions: list[Action]
    rollback_plan: Optional[str] = None
    timeout_seconds: Optional[int] = None  # None = no timeout (HIGH risk)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApprovalDecision(BaseModel):
    incident_id: str
    decision: ApprovalDecisionType
    decided_by: str = "system"
    reason: Optional[str] = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# WebSocket event envelope
# ---------------------------------------------------------------------------

class WSEvent(BaseModel):
    event_type: str
    data: dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
