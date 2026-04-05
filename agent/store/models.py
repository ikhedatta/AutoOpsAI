"""
Beanie document models for MongoDB persistence.

Each class maps to a MongoDB collection.  Beanie handles serialisation,
validation, and query building on top of Motor (async driver).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from beanie import Document, Indexed
from pydantic import Field

from agent.models import (
    IncidentStatus,
    Severity,
)


# ---------------------------------------------------------------------------
# Incident
# ---------------------------------------------------------------------------

class IncidentDoc(Document):
    incident_id: Indexed(str, unique=True)  # type: ignore[valid-type]
    title: str
    service_name: Indexed(str)  # type: ignore[valid-type]
    severity: Severity
    status: Indexed(str) = IncidentStatus.DETECTING.value  # type: ignore[valid-type]

    # Detection
    anomaly_type: str = ""
    metric: Optional[str] = None
    current_value: Optional[float] = None
    threshold: Optional[float] = None
    evidence: str = ""

    # Diagnosis
    diagnosis_summary: str = ""
    diagnosis_explanation: str = ""
    diagnosis_confidence: float = 0.0
    root_cause: Optional[str] = None
    playbook_id: Optional[str] = None
    novel: bool = False

    # Actions
    proposed_actions: list[dict[str, Any]] = []
    rollback_plan: Optional[str] = None

    # Approval
    approval_decision: Optional[str] = None
    approved_by: Optional[str] = None
    approval_decided_at: Optional[datetime] = None

    # Execution
    action_results: list[dict[str, Any]] = []

    # Timeline
    timeline: list[dict[str, Any]] = []

    # Timestamps
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "incidents"

    def add_timeline_event(self, event_type: str, detail: str, actor: str = "agent") -> None:
        self.timeline.append({
            "event": event_type,
            "detail": detail,
            "actor": actor,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.updated_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Approval record
# ---------------------------------------------------------------------------

class ApprovalDoc(Document):
    incident_id: Indexed(str)  # type: ignore[valid-type]
    severity: Severity
    title: str
    diagnosis_summary: str = ""
    proposed_actions: list[dict[str, Any]] = []
    rollback_plan: Optional[str] = None
    timeout_seconds: Optional[int] = None

    decision: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "approvals"


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class AuditLogDoc(Document):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: str = "system"
    action: Indexed(str)  # type: ignore[valid-type]
    resource_type: str = ""
    resource_id: str = ""
    detail: str = ""
    ip_address: Optional[str] = None

    class Settings:
        name = "audit_log"


# ---------------------------------------------------------------------------
# Chat message (per-incident conversation log)
# ---------------------------------------------------------------------------

class ChatMessageDoc(Document):
    incident_id: Indexed(str)  # type: ignore[valid-type]
    role: str  # "agent" | "user" | "system"
    content: str
    metadata: dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "chat_messages"


# ---------------------------------------------------------------------------
# Registry for Beanie init
# ---------------------------------------------------------------------------

ALL_DOCUMENTS = [IncidentDoc, ApprovalDoc, AuditLogDoc, ChatMessageDoc]
