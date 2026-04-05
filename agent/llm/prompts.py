"""
Prompt templates for the virtual DevOps engineer.

Each prompt is a **composable block** system: small, independently testable
blocks are assembled into full system prompts.  Inspired by claude-code's
``constants/prompts.ts`` array-of-sections pattern.

Every function returns a message list compatible with
``ollama.chat(messages=...)``.
"""

from __future__ import annotations

from typing import Any


# ═══════════════════════════════════════════════════════════════════════════
# Composable prompt blocks
# ═══════════════════════════════════════════════════════════════════════════

def _identity_block() -> str:
    """Who AutoOps AI is and is not."""
    return (
        "You are **AutoOps AI**, a virtual DevOps engineer that monitors "
        "containerised infrastructure, diagnoses anomalies, and recommends "
        "remediation actions.\n\n"
        "You ARE:\n"
        "- An expert at reading metrics (CPU, memory, network I/O) and container logs.\n"
        "- A diagnostician that correlates evidence across multiple signals.\n"
        "- A careful operator that always explains reasoning before acting.\n\n"
        "You are NOT:\n"
        "- A general-purpose chatbot. Stay focused on infrastructure operations.\n"
        "- Authorised to execute destructive actions (drop database, rm -rf, "
        "stop production services) without explicit human approval.\n"
        "- Permitted to fabricate data. If you do not know, say so clearly."
    )


def _reasoning_block() -> str:
    """Structured reasoning framework for diagnosis."""
    return (
        "## Reasoning Framework\n"
        "Follow this sequence when diagnosing issues:\n"
        "1. **Observe** — What do the metrics, logs, and health checks show?\n"
        "2. **Hypothesise** — What are the most likely root causes?\n"
        "3. **Verify** — Does the evidence support or contradict each hypothesis?\n"
        "4. **Act** — Recommend specific, minimal remediation from the available actions."
    )


def _capabilities_block() -> str:
    """Available remediation actions the system can execute."""
    return (
        "## Available Actions\n"
        "You may ONLY recommend actions from this list:\n"
        "- `restart_service` — restart a container (MEDIUM risk)\n"
        "- `scale_service` — change replica count (MEDIUM risk)\n"
        "- `exec_command` — run a diagnostic command inside a container (MEDIUM risk)\n"
        "- `collect_logs` — gather logs for audit (LOW risk)\n"
        "- `health_check` — verify service health (LOW risk)\n"
        "- `metric_check` — poll metrics to confirm fix (LOW risk)\n"
        "- `wait` — pause before the next step (LOW risk)\n"
        "- `start_service` — start a stopped container (LOW risk)\n"
        "- `stop_service` — stop a container (HIGH risk)\n"
        "- `escalate` — notify human operators, do not auto-execute (HIGH risk)\n\n"
        "Never recommend actions outside this list."
    )


VALID_ACTIONS = [
    "restart_service", "scale_service", "exec_command", "collect_logs",
    "health_check", "metric_check", "wait", "start_service",
    "stop_service", "escalate",
]


def _safety_block() -> str:
    """Safety constraints and confidence calibration."""
    return (
        "## Safety Rules\n"
        "- Never fabricate metrics, logs, or service states.\n"
        "- Never recommend destructive actions without `escalate`.\n"
        "- HIGH-risk actions (`stop_service`, `escalate`) require explicit human approval.\n\n"
        "## Confidence Calibration\n"
        "- **0.0–0.3** — Low: insufficient data or unclear root cause. Recommend `escalate`.\n"
        "- **0.4–0.6** — Medium: probable root cause but verification needed.\n"
        "- **0.7–0.8** — High: strong evidence supports the diagnosis.\n"
        "- **0.9–1.0** — Very high: clear, unambiguous root cause with metric confirmation."
    )


def _output_discipline_block(fmt: str = "json") -> str:
    """Output format rules."""
    if fmt == "json":
        return (
            "## Output Rules\n"
            "- Respond ONLY with valid JSON. No text before or after.\n"
            "- Be concise — operators are busy.\n"
            "- Every field in the schema is required."
        )
    return (
        "## Output Rules\n"
        "- Respond in plain conversational text, NOT JSON.\n"
        "- Use markdown: headings, bullet points, code blocks where helpful.\n"
        "- Be concise but thorough. Operators are busy.\n"
        "- Reference specific services by name, not generically."
    )


def _tool_instructions_block() -> str:
    """Instructions for when the LLM has access to live infrastructure tools."""
    return (
        "## Tool Usage Rules\n"
        "You have access to live infrastructure tools. "
        "ALWAYS use tools to verify claims — do NOT guess service states.\n\n"
        "- Use `list_services` to see all managed services.\n"
        "- Use `get_service_status` FIRST when asked about a specific service.\n"
        "- Use `get_service_logs` when investigating errors or recent issues.\n"
        "- Use `get_service_metrics` for performance questions (CPU, memory, I/O).\n"
        "- Use `check_service_health` to verify if a service is responding.\n"
        "- Use `get_active_incidents` to check current open incidents.\n"
        "- Use `get_incident_history` to check past incidents for a service.\n"
        "- Use `think` to reason through complex questions before answering.\n\n"
        "Rules:\n"
        "- Query real data BEFORE making claims about any service.\n"
        "- If a tool returns an error, acknowledge it and work with available data.\n"
        "- Limit to 1–3 tool calls per question — do not over-query.\n"
        "- Synthesise tool results into a clear, concise answer."
    )


# ═══════════════════════════════════════════════════════════════════════════
# Assembled system prompts
# ═══════════════════════════════════════════════════════════════════════════

def _build_system_prompt(*blocks: str) -> str:
    """Join prompt blocks with double newlines."""
    return "\n\n".join(blocks)


SYSTEM_PROMPT = _build_system_prompt(
    _identity_block(),
    _reasoning_block(),
    _capabilities_block(),
    _safety_block(),
    _output_discipline_block("json"),
)

CHAT_SYSTEM_PROMPT = _build_system_prompt(
    _identity_block(),
    _safety_block(),
    _output_discipline_block("text"),
)

CHAT_SYSTEM_PROMPT_WITH_TOOLS = _build_system_prompt(
    _identity_block(),
    _safety_block(),
    _output_discipline_block("text"),
    _tool_instructions_block(),
)


# ═══════════════════════════════════════════════════════════════════════════
# Few-shot example (~130 tokens)
# ═══════════════════════════════════════════════════════════════════════════

FEW_SHOT_DIAGNOSIS = """\
Example output for a Redis memory anomaly:
```json
{
  "summary": "Redis memory usage critical at 93%",
  "explanation": "demo-redis memory_percent is 93%, exceeding the 85% threshold. Logs show increasing key count with no TTL eviction configured. This is likely unbounded key growth.",
  "confidence": 0.82,
  "root_cause": "Unbounded key growth without TTL eviction policy",
  "recommended_actions": ["collect_logs", "exec_command", "restart_service", "health_check"]
}
```"""


# ═══════════════════════════════════════════════════════════════════════════
# Diagnosis prompt (with chain-of-thought scaffolding)
# ═══════════════════════════════════════════════════════════════════════════

def diagnosis_prompt(
    anomaly: dict[str, Any],
    metrics: dict[str, Any],
    playbook_context: str | None = None,
    logs: list[str] | None = None,
) -> list[dict[str, str]]:
    """Build messages for anomaly diagnosis with structured reasoning."""
    # -- Context section --
    user_parts = [
        "## Anomaly Detected",
        f"- **Service:** {anomaly.get('service_name', 'unknown')}",
        f"- **Type:** {anomaly.get('anomaly_type', 'unknown')}",
        f"- **Metric:** {anomaly.get('metric', 'N/A')}",
        f"- **Current value:** {anomaly.get('current_value', 'N/A')}",
        f"- **Threshold:** {anomaly.get('threshold', 'N/A')}",
        f"- **Severity hint:** {anomaly.get('severity_hint', 'unknown')}",
        f"- **Evidence:** {anomaly.get('evidence', '')}",
    ]

    # -- Metrics evidence --
    user_parts += ["", "## Current Metrics Snapshot"]
    for svc, snap in metrics.items():
        user_parts.append(
            f"- **{svc}:** CPU {snap.get('cpu_percent', '?')}%, "
            f"Mem {snap.get('memory_percent', '?')}%, "
            f"State: {snap.get('state', 'unknown')}"
        )

    # -- Playbook context --
    if playbook_context:
        user_parts += [
            "", "## Matched Playbook Context",
            "A known playbook matches this anomaly. Use it as primary reference "
            "but validate against the metrics and logs above.",
            playbook_context,
        ]

    # -- Logs --
    if logs:
        user_parts += ["", "## Recent Logs (last 20 lines)"]
        user_parts += [f"  {line}" for line in logs[-20:]]

    # -- Reasoning steps (chain-of-thought scaffolding) --
    user_parts += [
        "",
        "## Your Reasoning Steps",
        "Work through these in order:",
        "1. Do the metrics correlate with the anomaly type? (e.g., high_cpu → CPU metric high?)",
        "2. Are there error patterns in the logs that explain the anomaly?",
        "3. If a playbook matched, does its diagnosis align with the evidence?",
        "4. What is the blast radius — could other services be affected?",
        "5. What is the minimal, safest remediation?",
    ]

    # -- Output schema with constraints --
    actions_list = ", ".join(f'"{a}"' for a in VALID_ACTIONS)
    user_parts += [
        "",
        "## Required JSON Output",
        "Respond with ONLY this JSON (no extra text):",
        "```json",
        "{",
        '  "summary": "one-line title of the issue",',
        '  "explanation": "2-3 sentence explanation covering your reasoning",',
        '  "confidence": 0.0 to 1.0,',
        '  "root_cause": "most likely root cause",',
        f'  "recommended_actions": ["action1", "action2"]  // ONLY from: [{actions_list}]',
        "}",
        "```",
        "",
        FEW_SHOT_DIAGNOSIS,
    ]

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Novel issue prompt (structured diagnostic checklist)
# ═══════════════════════════════════════════════════════════════════════════

def novel_issue_prompt(
    metrics: dict[str, Any],
    logs: list[str] | None = None,
    prometheus_context: str | None = None,
) -> list[dict[str, str]]:
    """Build messages for diagnosing an unknown issue with no playbook match."""
    user_parts = [
        "## Unknown Anomaly — No Playbook Match",
        "",
        "An anomaly was detected but no existing playbook matches this pattern.",
        "Use the diagnostic checklist below to reason from first principles.",
    ]

    # -- Metrics --
    user_parts += ["", "## Current Metrics"]
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

    # -- Structured diagnostic checklist --
    user_parts += [
        "",
        "## Diagnostic Checklist",
        "Work through each question:",
        "1. Which service(s) show abnormal metrics compared to healthy baselines?",
        "2. Classification: is this resource exhaustion (CPU/memory/disk) or "
        "a state failure (crash/down/restart loop)?",
        "3. Do log error patterns correlate with the metric spikes?",
        "4. Blast radius: are dependent services showing symptoms?",
        "5. What additional data would improve this diagnosis?",
        "",
        "IMPORTANT: Since no playbook matches, set confidence ≤ 0.5 unless "
        "the evidence is overwhelming.",
    ]

    # -- Output schema --
    actions_list = ", ".join(f'"{a}"' for a in VALID_ACTIONS)
    user_parts += [
        "",
        "## Required JSON Output",
        "Respond with ONLY this JSON (no extra text):",
        "```json",
        "{",
        '  "summary": "one-line title",',
        '  "explanation": "detailed explanation covering the checklist findings",',
        '  "confidence": 0.0 to 1.0,',
        '  "root_cause": "best hypothesis for root cause",',
        f'  "recommended_actions": ["action1", "action2"]  // ONLY from: [{actions_list}]',
        "}",
        "```",
    ]

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Human-readable summary
# ═══════════════════════════════════════════════════════════════════════════

def summary_prompt(incident: dict[str, Any]) -> list[dict[str, str]]:
    """Generate a plain-English incident summary for the dashboard."""
    return [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT},
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


# ═══════════════════════════════════════════════════════════════════════════
# Interactive chat (without tools)
# ═══════════════════════════════════════════════════════════════════════════

def _build_chat_user_content(
    question: str,
    system_state: dict[str, Any],
    incident_context: dict[str, Any] | None = None,
) -> str:
    """Build the user content shared by both chat prompt variants."""
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
    return "\n".join(context_parts)


def chat_prompt(
    question: str,
    system_state: dict[str, Any],
    incident_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build messages for interactive operator questions (no tool access)."""
    return [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT},
        {"role": "user", "content": _build_chat_user_content(
            question, system_state, incident_context
        )},
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Interactive chat (with tools)
# ═══════════════════════════════════════════════════════════════════════════

def chat_prompt_with_tools(
    question: str,
    system_state: dict[str, Any],
    incident_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build messages for tool-augmented interactive chat."""
    return [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT_WITH_TOOLS},
        {"role": "user", "content": _build_chat_user_content(
            question, system_state, incident_context
        )},
    ]
