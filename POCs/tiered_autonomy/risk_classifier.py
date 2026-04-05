"""
Risk classifier: determines the risk level of a remediation action
based on playbook severity, action type, and context.

Routing:
  LOW  → auto-execute, notify after
  MEDIUM → request approval, 5-min timeout, auto-deny
  HIGH → require explicit approval, 10-min timeout, no auto-execute
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ActionPath(str, Enum):
    AUTO_EXECUTE = "auto_execute"       # Execute immediately, notify after
    REQUEST_APPROVAL = "request_approval"  # Send to approval flow
    REQUIRE_APPROVAL = "require_approval"  # Must have explicit human approval
    ESCALATE = "escalate"                # Cannot auto-fix, need human


@dataclass
class RoutingDecision:
    """The routing decision for an incident."""
    risk_level: RiskLevel
    action_path: ActionPath
    timeout_seconds: int
    auto_execute_on_timeout: bool
    reason: str


# Actions considered safe to auto-execute
SAFE_ACTIONS = {
    "redis_command",
    "collect_logs",
    "collect_diagnostics",
    "metric_check",
}

# Actions that are destructive and need approval
APPROVAL_ACTIONS = {
    "docker_restart",
    "docker_exec",
}

# Actions that are high-risk
HIGH_RISK_ACTIONS = {
    "escalate",
}

# Containers that are critical (higher risk to restart)
CRITICAL_CONTAINERS = {
    "mongodb", "postgres", "mysql", "redis",
    "nginx", "haproxy", "traefik",
}

# Default timeouts per risk level
TIMEOUTS = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 300,   # 5 minutes
    RiskLevel.HIGH: 600,     # 10 minutes
}


def classify_risk(
    playbook_severity: str,
    action_type: str,
    container_name: str,
    confidence: float = 1.0,
) -> RoutingDecision:
    """
    Classify risk and determine the routing path.

    Uses a layered approach:
      1. Start with playbook severity as baseline
      2. Escalate based on action type (restart > cache clear)
      3. Escalate based on container criticality
      4. Reduce confidence → escalate to approval
    """
    # Start with playbook severity
    base_severity = playbook_severity.upper()
    risk = RiskLevel(base_severity) if base_severity in ("LOW", "MEDIUM", "HIGH") else RiskLevel.MEDIUM

    reasons = [f"playbook_severity={base_severity}"]

    # Rule 1: escalate action always goes HIGH
    if action_type in HIGH_RISK_ACTIONS:
        risk = RiskLevel.HIGH
        reasons.append(f"action={action_type} is always HIGH risk")

    # Rule 2: destructive actions on critical containers → at least MEDIUM
    if action_type in APPROVAL_ACTIONS and container_name.lower() in CRITICAL_CONTAINERS:
        if risk == RiskLevel.LOW:
            risk = RiskLevel.MEDIUM
            reasons.append(f"escalated: {action_type} on critical container '{container_name}'")

    # Rule 3: destructive actions bump LOW → MEDIUM
    if action_type in APPROVAL_ACTIONS and risk == RiskLevel.LOW:
        risk = RiskLevel.MEDIUM
        reasons.append(f"escalated: {action_type} requires at least MEDIUM")

    # Rule 4: low confidence → bump risk
    if confidence < 0.5:
        if risk == RiskLevel.LOW:
            risk = RiskLevel.MEDIUM
        elif risk == RiskLevel.MEDIUM:
            risk = RiskLevel.HIGH
        reasons.append(f"escalated: low confidence ({confidence:.0%})")

    # Determine action path
    if risk == RiskLevel.LOW:
        path = ActionPath.AUTO_EXECUTE
    elif risk == RiskLevel.MEDIUM:
        path = ActionPath.REQUEST_APPROVAL
    else:
        path = ActionPath.REQUIRE_APPROVAL

    # Special: escalation actions always escalate
    if action_type == "escalate":
        path = ActionPath.ESCALATE

    return RoutingDecision(
        risk_level=risk,
        action_path=path,
        timeout_seconds=TIMEOUTS[risk],
        auto_execute_on_timeout=False,  # Never auto-execute on timeout
        reason="; ".join(reasons),
    )


def route_incident(
    playbook_severity: str,
    remediation_steps: list[dict],
    container_name: str,
    confidence: float = 1.0,
) -> RoutingDecision:
    """
    Route an entire incident based on its most risky remediation step.

    The overall risk is the maximum risk across all steps.
    """
    if not remediation_steps:
        return RoutingDecision(
            risk_level=RiskLevel.HIGH,
            action_path=ActionPath.ESCALATE,
            timeout_seconds=TIMEOUTS[RiskLevel.HIGH],
            auto_execute_on_timeout=False,
            reason="no remediation steps defined",
        )

    decisions = []
    for step in remediation_steps:
        action = step.get("action", "unknown")
        target = step.get("target", container_name)
        decision = classify_risk(playbook_severity, action, target, confidence)
        decisions.append(decision)

    # Overall risk = max risk across steps
    risk_order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
    highest = max(decisions, key=lambda d: risk_order[d.risk_level])

    # Collect all reasons
    all_reasons = [d.reason for d in decisions]

    return RoutingDecision(
        risk_level=highest.risk_level,
        action_path=highest.action_path,
        timeout_seconds=TIMEOUTS[highest.risk_level],
        auto_execute_on_timeout=False,
        reason=f"max of {len(decisions)} steps: {highest.reason}",
    )
