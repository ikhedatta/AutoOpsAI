"""
Teams Adaptive Card builders — converts AutoOps data into
Teams-compatible Adaptive Card JSON (schema v1.4).
"""

from __future__ import annotations

from typing import Any

from agent.store.models import IncidentDoc, ApprovalDoc


_SEVERITY_COLORS = {
    "LOW": "good",       # green
    "MEDIUM": "warning",  # yellow
    "HIGH": "attention",  # red
}

_SEVERITY_EMOJI = {
    "LOW": "🟢",
    "MEDIUM": "🟡",
    "HIGH": "🔴",
}


def build_incident_alert_card(incident: IncidentDoc) -> dict[str, Any]:
    """Build an Adaptive Card for a new incident notification."""
    severity = incident.severity or "MEDIUM"
    emoji = _SEVERITY_EMOJI.get(severity, "⚪")
    color = _SEVERITY_COLORS.get(severity, "default")

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "ColumnSet",
                "columns": [
                    {
                        "type": "Column",
                        "width": "auto",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": emoji,
                                "size": "Large",
                            }
                        ],
                    },
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": f"Incident: {incident.title}",
                                "weight": "Bolder",
                                "size": "Medium",
                                "wrap": True,
                            },
                            {
                                "type": "TextBlock",
                                "text": f"**{severity}** severity | {incident.service_name or 'unknown service'}",
                                "spacing": "None",
                                "isSubtle": True,
                                "wrap": True,
                            },
                        ],
                    },
                ],
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Incident ID", "value": incident.incident_id},
                    {"title": "Service", "value": incident.service_name or "—"},
                    {"title": "Anomaly", "value": incident.anomaly_type or "—"},
                    {"title": "Status", "value": incident.status},
                    {"title": "Detected", "value": incident.detected_at.strftime("%Y-%m-%d %H:%M:%S UTC") if incident.detected_at else "—"},
                ],
            },
        ],
    }

    if incident.diagnosis_summary:
        card["body"].append({
            "type": "TextBlock",
            "text": f"**Diagnosis:** {incident.diagnosis_summary}",
            "wrap": True,
            "spacing": "Medium",
        })

    return card


def build_approval_card(incident: IncidentDoc, approval: ApprovalDoc | None = None) -> dict[str, Any]:
    """Build an interactive Adaptive Card with Approve/Deny/Investigate buttons."""
    severity = incident.severity or "MEDIUM"
    emoji = _SEVERITY_EMOJI.get(severity, "⚪")
    timeout = approval.timeout_seconds if approval else None

    body: list[dict] = [
        {
            "type": "TextBlock",
            "text": f"{emoji} Approval Required — {incident.title}",
            "weight": "Bolder",
            "size": "Medium",
            "wrap": True,
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "Incident", "value": incident.incident_id},
                {"title": "Severity", "value": severity},
                {"title": "Service", "value": incident.service_name or "—"},
            ],
        },
    ]

    if incident.diagnosis_summary:
        body.append({
            "type": "TextBlock",
            "text": f"**Diagnosis:** {incident.diagnosis_summary}",
            "wrap": True,
        })

    if incident.proposed_actions:
        actions_text = "\n".join(f"• {a}" for a in incident.proposed_actions)
        body.append({
            "type": "TextBlock",
            "text": f"**Proposed Actions:**\n{actions_text}",
            "wrap": True,
        })

    if incident.rollback_plan:
        body.append({
            "type": "TextBlock",
            "text": f"**Rollback Plan:** {incident.rollback_plan}",
            "wrap": True,
            "isSubtle": True,
        })

    if timeout:
        body.append({
            "type": "TextBlock",
            "text": f"⏱️ Auto-deny in {timeout}s if no action taken",
            "isSubtle": True,
            "spacing": "Small",
        })

    card: dict[str, Any] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
        "actions": [
            {
                "type": "Action.Execute",
                "title": "✅ Approve",
                "verb": "approve",
                "data": {
                    "action": "approve",
                    "incident_id": incident.incident_id,
                },
                "style": "positive",
            },
            {
                "type": "Action.Execute",
                "title": "❌ Deny",
                "verb": "deny",
                "data": {
                    "action": "deny",
                    "incident_id": incident.incident_id,
                },
                "style": "destructive",
            },
            {
                "type": "Action.Execute",
                "title": "🔎 Investigate",
                "verb": "investigate",
                "data": {
                    "action": "investigate",
                    "incident_id": incident.incident_id,
                },
            },
        ],
    }

    return card


def build_outcome_card(
    incident_id: str,
    action: str,
    user_name: str,
    detail: str = "",
) -> dict[str, Any]:
    """Build a card showing the result of an approval decision."""
    status_map = {
        "approve": ("✅ Approved", "good"),
        "deny": ("❌ Denied", "attention"),
        "investigate": ("🔎 Investigating", "warning"),
        "timeout": ("⏱️ Timed Out (auto-denied)", "attention"),
    }
    title, color = status_map.get(action, ("ℹ️ Updated", "default"))

    body: list[dict] = [
        {
            "type": "TextBlock",
            "text": f"{title} — {incident_id}",
            "weight": "Bolder",
            "size": "Medium",
            "color": color,
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "Decision by", "value": user_name},
            ],
        },
    ]

    if detail:
        body.append({
            "type": "TextBlock",
            "text": detail,
            "wrap": True,
        })

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
    }


def build_resolution_card(incident: IncidentDoc) -> dict[str, Any]:
    """Build a card for a resolved incident."""
    resolution_time = None
    if incident.resolved_at and incident.detected_at:
        delta = incident.resolved_at - incident.detected_at
        resolution_time = f"{delta.total_seconds():.0f}s"

    facts = [
        {"title": "Incident", "value": incident.incident_id},
        {"title": "Service", "value": incident.service_name or "—"},
        {"title": "Resolved by", "value": incident.approved_by or "system"},
    ]
    if resolution_time:
        facts.append({"title": "Resolution time", "value": resolution_time})

    body: list[dict] = [
        {
            "type": "TextBlock",
            "text": f"✅ Resolved — {incident.title}",
            "weight": "Bolder",
            "size": "Medium",
            "color": "good",
        },
        {"type": "FactSet", "facts": facts},
    ]

    if incident.action_results:
        for result in incident.action_results:
            body.append({
                "type": "TextBlock",
                "text": f"• {result}",
                "wrap": True,
                "isSubtle": True,
            })

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
    }
