# [Step 02] — Core Pydantic Models

## Context

Step 01 has been completed. The following exist:
- `pyproject.toml` with all dependencies
- `agent/config.py` with `AgentSettings` and `get_settings()`
- All `__init__.py` package files
- `agent/tasks/__init__.py` with Celery app

## Objective

Produce `agent/models.py` containing all shared Pydantic models used throughout the system — service state, metrics, health, commands, logs, anomalies, diagnoses, actions, and approval decisions. No database document models (those are in step 08).

## Files to Create

- `agent/models.py` — All shared Pydantic models and enums.

## Files to Modify

None.

## Key Requirements

All models live in a single file `agent/models.py`. Import order: stdlib, then pydantic. Use `from __future__ import annotations` at the top.

**Enums (all `str, Enum`):**

```python
class ServiceState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    RESTARTING = "restarting"
    ERROR = "error"
    UNKNOWN = "unknown"

class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMED_OUT = "timed_out"
    INVESTIGATING = "investigating"

class IncidentStatus(str, Enum):
    ACTIVE = "active"
    APPROVED = "approved"
    REMEDIATING = "remediating"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    DENIED = "denied"
```

**Infrastructure models (exact field names and types as listed — do not add or remove fields):**

```python
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
    timestamp: datetime
    cpu_percent: float
    memory_used_bytes: int
    memory_limit_bytes: Optional[int] = None
    memory_percent: Optional[float] = None
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0
    extra: dict = {}

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
```

**Reasoning and incident models:**

```python
class Anomaly(BaseModel):
    service_name: str
    anomaly_type: str           # e.g. "container_down", "high_cpu", "log_pattern"
    severity: RiskLevel
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    message: str
    evidence: list[str] = []   # log lines, metric values, etc.
    detected_at: datetime

class Diagnosis(BaseModel):
    summary: str                # Plain-language explanation
    confidence: float           # 0.0 to 1.0
    llm_reasoning: Optional[str] = None
    matched_playbook: Optional[str] = None   # playbook id
    root_cause: Optional[str] = None
    recommended_actions: list[str] = []

class Action(BaseModel):
    action_type: str            # "restart_service", "exec_command", "scale_service", etc.
    target: str                 # service name
    parameters: dict = {}       # action-specific params (command, replicas, etc.)
    risk_level: RiskLevel
    description: str            # Human-readable description for approval cards
    rollback_plan: Optional[str] = None

class ActionResult(BaseModel):
    action: Action
    success: bool
    output: str = ""
    error: str = ""
    duration_seconds: Optional[float] = None
    executed_at: datetime

class ApprovalDecision(BaseModel):
    incident_id: str
    status: ApprovalStatus
    decided_by: Optional[str] = None   # username or Teams UPN
    decided_at: Optional[datetime] = None
    reason: Optional[str] = None
    timeout_at: Optional[datetime] = None
```

**Validator rules:**
- `Anomaly.detected_at` should default to `datetime.utcnow()` using `default_factory`.
- `MetricSnapshot.memory_percent` should be auto-computed from `memory_used_bytes / memory_limit_bytes * 100` if `memory_limit_bytes > 0`, using a `model_validator(mode="after")`. Leave as `None` if `memory_limit_bytes` is `None` or 0.
- `Diagnosis.confidence` must be clamped between 0.0 and 1.0 using a `field_validator`.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
python -c "
from datetime import datetime, timezone
from agent.models import (
    ServiceState, RiskLevel, ApprovalStatus, IncidentStatus,
    ServiceInfo, ServiceStatus, MetricSnapshot, HealthCheckResult,
    CommandResult, LogEntry, Anomaly, Diagnosis, Action, ActionResult,
    ApprovalDecision
)

# Test ServiceInfo
s = ServiceInfo(name='mongodb', platform_id='abc123', state=ServiceState.RUNNING)
assert s.state == ServiceState.RUNNING

# Test MetricSnapshot memory_percent auto-computation
m = MetricSnapshot(
    service_name='demo-app',
    timestamp=datetime.now(timezone.utc),
    cpu_percent=45.0,
    memory_used_bytes=256 * 1024 * 1024,
    memory_limit_bytes=512 * 1024 * 1024,
)
assert m.memory_percent == 50.0, f'Expected 50.0, got {m.memory_percent}'

# Test Diagnosis confidence clamping
d = Diagnosis(summary='test', confidence=1.5)
assert d.confidence == 1.0

d2 = Diagnosis(summary='test', confidence=-0.1)
assert d2.confidence == 0.0

# Test Anomaly default detected_at
a = Anomaly(service_name='mongodb', anomaly_type='container_down', severity=RiskLevel.HIGH, message='down')
assert a.detected_at is not None

print('all model tests passed')
"
```

## Dependencies

- Step 01 (project setup with `pyproject.toml` and all packages installed)
