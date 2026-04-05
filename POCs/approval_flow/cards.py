"""
Adaptive Card builder for Teams interactive approval messages.

Builds rich cards with:
  - Incident summary (diagnosis, severity, container)
  - Proposed remediation steps
  - Rollback plan
  - Approve / Deny / Investigate More buttons
  - Risk-level color coding
"""

from __future__ import annotations

from typing import Any


SEVERITY_COLORS = {
    "LOW": "good",       # Green
    "MEDIUM": "warning",  # Yellow/Orange
    "HIGH": "attention",  # Red
}

SEVERITY_EMOJI = {
    "LOW": "🟢",
    "MEDIUM": "🟡",
    "HIGH": "🔴",
}


MAX_DIAGNOSIS_CHARS = 500
MAX_ROLLBACK_CHARS = 500


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, appending '...' if shortened."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def build_approval_card(
    incident_id: str,
    container_name: str,
    severity: str,
    diagnosis: str,
    remediation_steps: list[dict],
    rollback_plan: str = "",
    confidence: float = 0.0,
) -> dict:
    """
    Build a Teams Adaptive Card for incident approval.

    Returns the card payload ready to be sent via Bot Framework.
    """
    severity = severity.upper()
    color = SEVERITY_COLORS.get(severity, "default")
    emoji = SEVERITY_EMOJI.get(severity, "⚪")

    # Truncate long fields to stay within Teams card size limits
    diagnosis = _truncate(diagnosis, MAX_DIAGNOSIS_CHARS)
    rollback_plan = _truncate(rollback_plan, MAX_ROLLBACK_CHARS)

    # Format remediation steps as numbered list
    steps_text = "\n".join(
        f"{i+1}. **{step.get('action', '?')}** → `{step.get('target', step.get('command', ''))}`"
        for i, step in enumerate(remediation_steps)
    )

    card: dict[str, Any] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            # Header with severity badge
            {
                "type": "ColumnSet",
                "columns": [
                    {
                        "type": "Column",
                        "width": "auto",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": f"{emoji} {severity} SEVERITY",
                                "weight": "bolder",
                                "size": "medium",
                                "color": color,
                            }
                        ],
                    },
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": f"Incident: {incident_id}",
                                "weight": "lighter",
                                "size": "small",
                                "horizontalAlignment": "right",
                            }
                        ],
                    },
                ],
            },
            # Container info
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Container", "value": container_name},
                    {"title": "Severity", "value": f"{emoji} {severity}"},
                    {"title": "Confidence", "value": f"{confidence:.0%}"},
                ],
            },
            # Diagnosis
            {
                "type": "TextBlock",
                "text": "**Diagnosis**",
                "spacing": "medium",
            },
            {
                "type": "TextBlock",
                "text": diagnosis,
                "wrap": True,
                "size": "small",
            },
            # Proposed remediation
            {
                "type": "TextBlock",
                "text": "**Proposed Remediation**",
                "spacing": "medium",
            },
            {
                "type": "TextBlock",
                "text": steps_text,
                "wrap": True,
                "size": "small",
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ Approve",
                "style": "positive",
                "data": {
                    "action": "approve",
                    "incident_id": incident_id,
                },
            },
            {
                "type": "Action.Submit",
                "title": "❌ Deny",
                "style": "destructive",
                "data": {
                    "action": "deny",
                    "incident_id": incident_id,
                },
            },
            {
                "type": "Action.Submit",
                "title": "🔍 Investigate More",
                "data": {
                    "action": "investigate",
                    "incident_id": incident_id,
                },
            },
        ],
    }

    # Add rollback plan if provided (insert before the actions section)
    if rollback_plan:
        card["body"].append({
            "type": "TextBlock",
            "text": "**Rollback Plan**",
            "spacing": "medium",
        })
        card["body"].append({
            "type": "TextBlock",
            "text": rollback_plan,
            "wrap": True,
            "size": "small",
            "isSubtle": True,
        })

    return card


def build_outcome_card(
    incident_id: str,
    action_taken: str,
    success: bool,
    details: str,
    duration_ms: float = 0.0,
) -> dict:
    """Build a card showing the outcome of an approval action."""
    if success:
        color = "good"
        icon = "✅"
        title = "Remediation Successful"
    else:
        color = "attention"
        icon = "❌"
        title = "Remediation Failed"

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": f"{icon} {title}",
                "weight": "bolder",
                "size": "medium",
                "color": color,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Incident", "value": incident_id},
                    {"title": "Action", "value": action_taken},
                    {"title": "Duration", "value": f"{duration_ms:.0f}ms"},
                ],
            },
            {
                "type": "TextBlock",
                "text": details,
                "wrap": True,
                "size": "small",
            },
        ],
    }


def build_timeout_card(incident_id: str, severity: str, timeout_seconds: int) -> dict:
    """Build a card indicating approval timed out."""
    action = "Auto-denied (HIGH risk)" if severity == "HIGH" else "Auto-denied (timeout)"

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": f"⏰ Approval Timed Out ({timeout_seconds}s)",
                "weight": "bolder",
                "size": "medium",
                "color": "warning",
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Incident", "value": incident_id},
                    {"title": "Action Taken", "value": action},
                ],
            },
            {
                "type": "TextBlock",
                "text": "No response was received within the timeout window. "
                        "The incident has been logged for manual review.",
                "wrap": True,
                "size": "small",
            },
        ],
    }
