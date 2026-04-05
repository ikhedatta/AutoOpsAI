"""
Prompt templates for the virtual DevOps engineer.

Each prompt is a function that accepts context and returns a message list
compatible with ``ollama.chat(messages=...)``.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# System identity
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are **AutoOps AI**, a virtual DevOps engineer.

Your job:
1. Analyse infrastructure metrics, logs, and anomalies.
2. Diagnose the root cause of issues in plain English.
3. Recommend specific remediation actions.
4. Explain your reasoning clearly so a human operator can make an informed approval decision.

Rules:
- Be concise but thorough.  Operators are busy.
- Always state your confidence level (low / medium / high).
- If you are unsure, say so — never fabricate information.
- Output valid JSON when asked for structured output.
- Never recommend destructive actions (drop database, rm -rf) without explicit escalation.
"""

# ---------------------------------------------------------------------------
# Diagnosis prompt
# ---------------------------------------------------------------------------

def diagnosis_prompt(
    anomaly: dict[str, Any],
    metrics: dict[str, Any],
    playbook_context: str | None = None,
    logs: list[str] | None = None,
) -> list[dict[str, str]]:
    """Build messages for anomaly diagnosis."""
    user_parts = [
        "## Anomaly Detected\n",
        f"- **Service:** {anomaly.get('service_name', 'unknown')}",
        f"- **Type:** {anomaly.get('anomaly_type', 'unknown')}",
        f"- **Metric:** {anomaly.get('metric', 'N/A')}",
        f"- **Current value:** {anomaly.get('current_value', 'N/A')}",
        f"- **Threshold:** {anomaly.get('threshold', 'N/A')}",
        f"- **Evidence:** {anomaly.get('evidence', '')}",
        "",
        "## Current Metrics Snapshot",
    ]
    for svc, snap in metrics.items():
        user_parts.append(
            f"- **{svc}:** CPU {snap.get('cpu_percent', '?')}%, "
            f"Mem {snap.get('memory_percent', '?')}%"
        )

    if playbook_context:
        user_parts += ["", "## Matched Playbook Context", playbook_context]

    if logs:
        user_parts += ["", "## Recent Logs (last 20 lines)"]
        user_parts += [f"  {line}" for line in logs[-20:]]

    user_parts += [
        "",
        "## Task",
        "Diagnose the root cause.  Respond in **JSON** with this schema:",
        "```json",
        '{',
        '  "summary": "one-line title of the issue",',
        '  "explanation": "2-3 sentence detailed explanation",',
        '  "confidence": 0.0 to 1.0,',
        '  "root_cause": "most likely root cause",',
        '  "recommended_actions": ["action1", "action2"]',
        '}',
        "```",
    ]

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


# ---------------------------------------------------------------------------
# Novel issue prompt (no playbook match)
# ---------------------------------------------------------------------------

def novel_issue_prompt(
    metrics: dict[str, Any],
    logs: list[str] | None = None,
    prometheus_context: str | None = None,
) -> list[dict[str, str]]:
    """Build messages for diagnosing an unknown issue."""
    user_parts = [
        "## Unknown Anomaly — No Playbook Match",
        "",
        "I have detected an anomaly but no playbook matches this pattern.",
        "Please analyse from first principles.",
        "",
        "## Current Metrics",
    ]
    for svc, snap in metrics.items():
        user_parts.append(
            f"- **{svc}:** CPU {snap.get('cpu_percent', '?')}%, "
            f"Mem {snap.get('memory_percent', '?')}%, "
            f"State: {snap.get('state', 'unknown')}"
        )

    if prometheus_context:
        user_parts += ["", "## Prometheus Trend Data", prometheus_context]

    if logs:
        user_parts += ["", "## Recent Logs"]
        user_parts += [f"  {line}" for line in logs[-30:]]

    user_parts += [
        "",
        "## Task",
        "Diagnose this issue.  Respond in **JSON**:",
        "```json",
        '{',
        '  "summary": "one-line title",',
        '  "explanation": "detailed explanation",',
        '  "confidence": 0.0 to 1.0,',
        '  "root_cause": "best guess at root cause",',
        '  "recommended_actions": ["action1", "action2"]',
        '}',
        "```",
    ]

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


# ---------------------------------------------------------------------------
# Human-readable summary
# ---------------------------------------------------------------------------

def summary_prompt(incident: dict[str, Any]) -> list[dict[str, str]]:
    """Generate a plain-English incident summary for the dashboard."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Write a concise incident summary (3-5 sentences) for the dashboard.\n\n"
                f"**Title:** {incident.get('title', 'Unknown')}\n"
                f"**Service:** {incident.get('service_name', 'unknown')}\n"
                f"**Severity:** {incident.get('severity', 'MEDIUM')}\n"
                f"**Diagnosis:** {incident.get('diagnosis_summary', 'N/A')}\n"
                f"**Root cause:** {incident.get('root_cause', 'N/A')}\n"
                f"**Status:** {incident.get('status', 'unknown')}\n\n"
                "Write in first person as AutoOps AI.  Be conversational but professional."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Interactive chat
# ---------------------------------------------------------------------------

def chat_prompt(
    question: str,
    system_state: dict[str, Any],
    incident_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build messages for interactive operator questions."""
    chat_system = (
        "You are **AutoOps AI**, a virtual DevOps engineer assistant.\n\n"
        "Rules for chat responses:\n"
        "- Respond in **plain conversational text**, NOT JSON.\n"
        "- Use markdown formatting: headings, bullet points, code blocks where helpful.\n"
        "- Be concise but thorough. Operators are busy.\n"
        "- If you are unsure, say so — never fabricate information.\n"
        "- Never recommend destructive actions without explicit warnings.\n"
    )
    context_parts = ["## Current System State"]
    for svc, info in system_state.items():
        context_parts.append(
            f"- **{svc}:** {info.get('state', 'unknown')} | "
            f"CPU {info.get('cpu_percent', '?')}% | "
            f"Mem {info.get('memory_percent', '?')}%"
        )

    if incident_context:
        context_parts += [
            "",
            "## Related Incident",
            f"- **ID:** {incident_context.get('incident_id', '')}",
            f"- **Title:** {incident_context.get('title', '')}",
            f"- **Status:** {incident_context.get('status', '')}",
            f"- **Diagnosis:** {incident_context.get('diagnosis_summary', '')}",
        ]

    context_parts += ["", "## Operator Question", question]

    return [
        {"role": "system", "content": chat_system},
        {"role": "user", "content": "\n".join(context_parts)},
    ]
