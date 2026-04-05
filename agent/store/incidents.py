"""
Incident CRUD operations.

All writes go through here — the engine and API never talk to MongoDB
directly.  This keeps the persistence logic in one place.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from agent.models import (
    Action,
    ActionResult,
    Anomaly,
    ApprovalDecision,
    ApprovalDecisionType,
    Diagnosis,
    IncidentStatus,
    Severity,
)
from agent.store.models import AuditLogDoc, ChatMessageDoc, IncidentDoc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

async def create_incident(
    anomaly: Anomaly,
    diagnosis: Diagnosis,
    proposed_actions: list[Action],
    severity: Severity,
) -> IncidentDoc:
    incident_id = f"inc_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
    doc = IncidentDoc(
        incident_id=incident_id,
        title=diagnosis.summary or f"Anomaly on {anomaly.service_name}",
        service_name=anomaly.service_name,
        severity=severity,
        status=IncidentStatus.DETECTING.value,
        anomaly_type=anomaly.anomaly_type,
        metric=anomaly.metric,
        current_value=anomaly.current_value,
        threshold=anomaly.threshold,
        evidence=anomaly.evidence,
        diagnosis_summary=diagnosis.summary,
        diagnosis_explanation=diagnosis.explanation,
        diagnosis_confidence=diagnosis.confidence,
        root_cause=diagnosis.root_cause,
        playbook_id=diagnosis.playbook_id,
        novel=diagnosis.novel,
        proposed_actions=[a.model_dump() for a in proposed_actions],
        rollback_plan=None,
    )
    doc.add_timeline_event("detected", f"Anomaly detected: {anomaly.evidence}")
    doc.add_timeline_event("diagnosed", f"Diagnosis: {diagnosis.summary}")
    await doc.insert()
    logger.info("Incident created: %s — %s", incident_id, doc.title)
    return doc


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def get_incident(incident_id: str) -> Optional[IncidentDoc]:
    return await IncidentDoc.find_one(IncidentDoc.incident_id == incident_id)


async def list_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    service: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
) -> list[IncidentDoc]:
    query: dict = {}
    if status:
        query["status"] = status
    if severity:
        query["severity"] = severity
    if service:
        query["service_name"] = service
    return (
        await IncidentDoc.find(query)
        .sort("-detected_at")
        .skip(skip)
        .limit(limit)
        .to_list()
    )


async def find_active_incident(service_name: str, anomaly_type: str) -> Optional[IncidentDoc]:
    """Find an existing non-resolved incident for the same service+issue."""
    return await IncidentDoc.find_one(
        {
            "service_name": service_name,
            "anomaly_type": anomaly_type,
            "status": {"$nin": [
                IncidentStatus.RESOLVED.value,
                IncidentStatus.FAILED.value,
                IncidentStatus.DENIED.value,
                IncidentStatus.DENIED_TIMEOUT.value,
            ]},
        }
    )


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

async def update_status(incident_id: str, status: IncidentStatus, detail: str = "") -> Optional[IncidentDoc]:
    doc = await get_incident(incident_id)
    if not doc:
        return None
    doc.status = status.value
    doc.updated_at = datetime.now(timezone.utc)
    if status == IncidentStatus.RESOLVED:
        doc.resolved_at = datetime.now(timezone.utc)
    doc.add_timeline_event("status_change", f"{status.value}: {detail}")
    await doc.save()
    return doc


async def record_approval(incident_id: str, decision: ApprovalDecision) -> Optional[IncidentDoc]:
    doc = await get_incident(incident_id)
    if not doc:
        return None
    doc.approval_decision = decision.decision.value
    doc.approved_by = decision.decided_by
    doc.approval_decided_at = decision.decided_at
    if decision.decision == ApprovalDecisionType.APPROVE:
        doc.status = IncidentStatus.APPROVED.value
    elif decision.decision in (ApprovalDecisionType.DENY, ApprovalDecisionType.TIMEOUT):
        doc.status = IncidentStatus.DENIED.value if decision.decision == ApprovalDecisionType.DENY else IncidentStatus.DENIED_TIMEOUT.value
    doc.add_timeline_event(
        "approval",
        f"{decision.decision.value} by {decision.decided_by}: {decision.reason or ''}",
        actor=decision.decided_by,
    )
    await doc.save()
    return doc


async def record_action_result(incident_id: str, result: ActionResult) -> Optional[IncidentDoc]:
    doc = await get_incident(incident_id)
    if not doc:
        return None
    doc.action_results.append(result.model_dump())
    doc.add_timeline_event(
        "action_executed",
        f"Action {result.action_id}: {'success' if result.success else 'failed'} — {result.output or result.error}",
    )
    await doc.save()
    return doc


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

async def audit_log(
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    detail: str = "",
    user_id: str = "system",
) -> None:
    await AuditLogDoc(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        user_id=user_id,
    ).insert()


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

async def add_chat_message(incident_id: str, role: str, content: str, metadata: dict | None = None) -> None:
    await ChatMessageDoc(
        incident_id=incident_id,
        role=role,
        content=content,
        metadata=metadata or {},
    ).insert()


async def get_chat_history(incident_id: str) -> list[ChatMessageDoc]:
    return (
        await ChatMessageDoc.find(ChatMessageDoc.incident_id == incident_id)
        .sort("timestamp")
        .to_list()
    )
