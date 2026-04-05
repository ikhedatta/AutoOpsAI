"""
Approval card data builder — generates card data for the dashboard.
"""

from __future__ import annotations

from typing import Any

from agent.models import Severity
from agent.store.models import ApprovalDoc, IncidentDoc


def build_approval_card(incident: IncidentDoc, approval: ApprovalDoc | None = None) -> dict[str, Any]:
    """Build a structured card dict for the dashboard to render."""
    severity = Severity(incident.severity)
    timeout = approval.timeout_seconds if approval else None

    return {
        "type": "approval_card",
        "incident_id": incident.incident_id,
        "severity": severity.value,
        "severity_color": {
            "LOW": "green",
            "MEDIUM": "amber",
            "HIGH": "red",
        }[severity.value],
        "title": incident.title,
        "service_name": incident.service_name,
        "detected_at": incident.detected_at.isoformat(),
        "diagnosis": {
            "summary": incident.diagnosis_summary,
            "explanation": incident.diagnosis_explanation,
            "confidence": incident.diagnosis_confidence,
            "root_cause": incident.root_cause,
        },
        "proposed_actions": incident.proposed_actions,
        "rollback_plan": incident.rollback_plan,
        "timeout_seconds": timeout,
        "status": incident.status,
        "actions_available": incident.status == "awaiting_approval",
    }


def build_resolution_card(incident: IncidentDoc) -> dict[str, Any]:
    """Build a card for a resolved incident."""
    resolution_time = None
    if incident.resolved_at and incident.detected_at:
        delta = incident.resolved_at - incident.detected_at
        resolution_time = delta.total_seconds()

    return {
        "type": "resolution_card",
        "incident_id": incident.incident_id,
        "title": incident.title,
        "service_name": incident.service_name,
        "status": incident.status,
        "approved_by": incident.approved_by,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "resolution_time_seconds": resolution_time,
        "action_results": incident.action_results,
    }
