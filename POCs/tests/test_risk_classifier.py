"""Tests for the risk classifier (tiered autonomy)."""

from POCs.tiered_autonomy.risk_classifier import (
    classify_risk,
    route_incident,
    RiskLevel,
    ActionPath,
    RoutingDecision,
)


class TestClassifyRisk:
    """Test individual action risk classification."""

    def test_safe_action_low_severity(self):
        decision = classify_risk("LOW", "collect_logs", "webapp")
        assert decision.risk_level == RiskLevel.LOW
        assert decision.action_path == ActionPath.AUTO_EXECUTE

    def test_destructive_action_bumps_to_medium(self):
        decision = classify_risk("LOW", "docker_restart", "webapp")
        assert decision.risk_level == RiskLevel.MEDIUM
        assert decision.action_path == ActionPath.REQUEST_APPROVAL

    def test_critical_container_escalates(self):
        decision = classify_risk("LOW", "docker_restart", "mongodb")
        assert decision.risk_level == RiskLevel.MEDIUM

    def test_escalate_action_always_high(self):
        decision = classify_risk("LOW", "escalate", "webapp")
        assert decision.risk_level == RiskLevel.HIGH
        assert decision.action_path == ActionPath.ESCALATE

    def test_low_confidence_escalates(self):
        decision = classify_risk("LOW", "collect_logs", "webapp", confidence=0.3)
        assert decision.risk_level == RiskLevel.MEDIUM

    def test_high_severity_preserved(self):
        decision = classify_risk("HIGH", "collect_logs", "webapp")
        assert decision.risk_level == RiskLevel.HIGH
        assert decision.action_path == ActionPath.REQUIRE_APPROVAL

    def test_medium_severity_approved(self):
        decision = classify_risk("MEDIUM", "collect_logs", "webapp")
        assert decision.risk_level == RiskLevel.MEDIUM
        assert decision.action_path == ActionPath.REQUEST_APPROVAL

    def test_timeout_values(self):
        low = classify_risk("LOW", "collect_logs", "webapp")
        assert low.timeout_seconds == 0
        med = classify_risk("MEDIUM", "collect_logs", "webapp")
        assert med.timeout_seconds == 300
        high = classify_risk("HIGH", "collect_logs", "webapp")
        assert high.timeout_seconds == 600

    def test_auto_execute_on_timeout_always_false(self):
        decision = classify_risk("LOW", "collect_logs", "webapp")
        assert decision.auto_execute_on_timeout is False


class TestRouteIncident:
    """Test multi-step incident routing."""

    def test_empty_steps_escalates(self):
        decision = route_incident("LOW", [], "webapp")
        assert decision.risk_level == RiskLevel.HIGH
        assert decision.action_path == ActionPath.ESCALATE

    def test_all_safe_steps_auto_execute(self):
        steps = [
            {"action": "collect_logs", "target": "webapp"},
            {"action": "metric_check", "metric": "cpu"},
        ]
        decision = route_incident("LOW", steps, "webapp")
        assert decision.risk_level == RiskLevel.LOW
        assert decision.action_path == ActionPath.AUTO_EXECUTE

    def test_mixed_steps_takes_max_risk(self):
        steps = [
            {"action": "collect_logs", "target": "webapp"},
            {"action": "docker_restart", "target": "webapp"},
        ]
        decision = route_incident("LOW", steps, "webapp")
        assert decision.risk_level == RiskLevel.MEDIUM

    def test_escalate_step_overrides_all(self):
        steps = [
            {"action": "collect_logs", "target": "webapp"},
            {"action": "escalate", "message": "Manual review"},
        ]
        decision = route_incident("LOW", steps, "webapp")
        assert decision.risk_level == RiskLevel.HIGH
        assert decision.action_path == ActionPath.ESCALATE
