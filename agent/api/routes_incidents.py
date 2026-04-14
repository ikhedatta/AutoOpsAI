"""
Incident endpoints — list, detail, escalate.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from agent.api.dependencies import verify_api_key
from agent.models import IncidentStatus
from agent.notifications.email_service import send_escalation_email
from agent.store import incidents as incident_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("")
async def list_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    service: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
):
    docs = await incident_store.list_incidents(
        status=status, severity=severity, service=service,
        limit=limit, skip=skip,
    )
    return [_incident_to_dict(d) for d in docs]


@router.get("/{incident_id}")
async def get_incident(incident_id: str):
    doc = await incident_store.get_incident(incident_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Incident not found")
    # Include chat history
    chat = await incident_store.get_chat_history(incident_id)
    result = _incident_to_dict(doc)
    result["chat"] = [
        {
            "role": m.role,
            "content": m.content,
            "timestamp": m.timestamp.isoformat(),
            "metadata": m.metadata,
        }
        for m in chat
    ]
    return result


@router.post("/{incident_id}/escalate", dependencies=[Depends(verify_api_key)])
async def escalate_incident(incident_id: str):
    doc = await incident_store.update_status(
        incident_id, IncidentStatus.ESCALATED, detail="Manually escalated by operator"
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Incident not found")
    await incident_store.audit_log(
        action="escalate",
        resource_type="incident",
        resource_id=incident_id,
        detail="Manual escalation",
    )

    # Send escalation email notification
    email_sent = await send_escalation_email(
        incident_id=incident_id,
        title=doc.title,
        service_name=doc.service_name,
        severity=doc.severity,
        detail="Manually escalated by operator",
    )
    if not email_sent:
        logger.warning(f"Escalation email not sent for incident {incident_id} (SMTP not configured or failed)")

    return {"status": "escalated", "incident_id": incident_id, "email_sent": email_sent}


def _incident_to_dict(doc) -> dict:
    return {
        "incident_id": doc.incident_id,
        "title": doc.title,
        "service_name": doc.service_name,
        "severity": doc.severity,
        "status": doc.status,
        "anomaly_type": doc.anomaly_type,
        "metric": doc.metric,
        "current_value": doc.current_value,
        "threshold": doc.threshold,
        "evidence": doc.evidence,
        "diagnosis": {
            "summary": doc.diagnosis_summary,
            "explanation": doc.diagnosis_explanation,
            "confidence": doc.diagnosis_confidence,
            "root_cause": doc.root_cause,
            "playbook_id": doc.playbook_id,
            "novel": doc.novel,
        },
        "proposed_actions": doc.proposed_actions,
        "rollback_plan": doc.rollback_plan,
        "approval": {
            "decision": doc.approval_decision,
            "approved_by": doc.approved_by,
            "decided_at": doc.approval_decided_at.isoformat() if doc.approval_decided_at else None,
        },
        "action_results": doc.action_results,
        "timeline": doc.timeline,
        "detected_at": doc.detected_at.isoformat(),
        "resolved_at": doc.resolved_at.isoformat() if doc.resolved_at else None,
        "updated_at": doc.updated_at.isoformat(),
    }
