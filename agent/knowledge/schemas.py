"""
Pydantic models that mirror the playbook YAML schema.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from agent.models import Severity


class DetectionCondition(BaseModel):
    type: str  # container_health, metric_threshold, log_pattern, health_endpoint
    service_name: Optional[str] = None
    state: Optional[str] = None
    metric: Optional[str] = None
    threshold: Optional[str] = None
    duration: Optional[str] = None
    pattern: Optional[str] = None
    rate: Optional[str] = None
    expected_status: Optional[int] = None
    actual: Optional[int] = None
    timeout: Optional[int] = None
    # compound sub-detectors
    detectors: list["DetectionCondition"] = []


class Detection(BaseModel):
    type: str
    conditions: list[DetectionCondition] = []


class RemediationStep(BaseModel):
    action: str
    target: Optional[str] = None
    command: Optional[str] = None
    timeout: Optional[int] = None
    seconds: Optional[int] = None
    replicas: Optional[int] = None
    check: Optional[str] = None
    message: Optional[str] = None
    lines: Optional[int] = None
    metric: Optional[str] = None
    expected: Optional[str] = None


class Remediation(BaseModel):
    steps: list[RemediationStep]


class Rollback(BaseModel):
    description: str = ""
    steps: list[RemediationStep] = []


class Playbook(BaseModel):
    id: str
    name: str
    severity: Severity
    detection: Detection
    diagnosis: str
    remediation: Remediation
    provider: Optional[str] = None
    tags: list[str] = []
    cooldown_seconds: int = 300
    rollback: Optional[Rollback] = None
    metadata: dict[str, Any] = {}

    # runtime attribute set by the matcher
    match_confidence: float = 0.0


class PlaybookMatch(BaseModel):
    playbook: Playbook
    confidence: float
    matched_conditions: list[str] = []
