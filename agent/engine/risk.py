"""
Risk classification — determines the risk level of a proposed remediation.

Risk factors:
- Service criticality (database > app > cache > proxy)
- Action type (observe < restart < scale < failover)
- Blast radius (single service < cascading)
- Playbook-defined severity override
"""

from __future__ import annotations

from agent.models import Action, Anomaly, Severity

# Service criticality tiers
_CRITICAL_SERVICES = {"mongodb", "postgres", "mysql", "redis", "rabbitmq", "kafka"}
_IMPORTANT_SERVICES = {"demo-app", "api", "worker", "celery"}

# Action type risk
_ACTION_RISK = {
    "collect_logs": Severity.LOW,
    "collect_diagnostics": Severity.LOW,
    "health_check": Severity.LOW,
    "metric_check": Severity.LOW,
    "wait": Severity.LOW,
    "restart_service": Severity.MEDIUM,
    "exec_command": Severity.MEDIUM,
    "scale_service": Severity.MEDIUM,
    "stop_service": Severity.HIGH,
    "start_service": Severity.LOW,
    "escalate": Severity.HIGH,
}


def classify_risk(
    anomaly: Anomaly,
    proposed_actions: list[Action],
    playbook_severity: Severity | None = None,
) -> Severity:
    """
    Return the overall risk level for a set of proposed actions.

    If a playbook defines a severity, it acts as a floor — the classifier
    can only raise it, never lower it.
    """

    # Start with playbook severity or the anomaly's hint
    base = playbook_severity or anomaly.severity_hint

    # Evaluate each action
    highest_action_risk = Severity.LOW
    for action in proposed_actions:
        action_risk = _ACTION_RISK.get(action.action_type, Severity.MEDIUM)
        if _severity_rank(action_risk) > _severity_rank(highest_action_risk):
            highest_action_risk = action_risk

    # Service criticality bump
    svc = anomaly.service_name.lower()
    service_bump = Severity.LOW
    if any(crit in svc for crit in _CRITICAL_SERVICES):
        service_bump = Severity.HIGH
    elif any(imp in svc for imp in _IMPORTANT_SERVICES):
        service_bump = Severity.MEDIUM

    # Take the maximum
    candidates = [base, highest_action_risk, service_bump]
    return max(candidates, key=_severity_rank)


def _severity_rank(s: Severity) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(s.value, 1)
