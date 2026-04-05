"""Tests for agent.engine.risk — risk classification logic."""

from __future__ import annotations

import pytest

from agent.engine.risk import classify_risk, _severity_rank
from agent.models import Action, Anomaly, Severity


class TestSeverityRank:
    def test_ranks(self):
        assert _severity_rank(Severity.LOW) == 0
        assert _severity_rank(Severity.MEDIUM) == 1
        assert _severity_rank(Severity.HIGH) == 2

    def test_low_before_medium(self):
        assert _severity_rank(Severity.LOW) < _severity_rank(Severity.MEDIUM)

    def test_medium_before_high(self):
        assert _severity_rank(Severity.MEDIUM) < _severity_rank(Severity.HIGH)


class TestClassifyRiskActionTypes:
    def test_restart_is_medium(self):
        anomaly = Anomaly(service_name="demo-app", anomaly_type="high_cpu", severity_hint=Severity.LOW)
        actions = [Action(action_type="restart_service", target="demo-app")]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.MEDIUM

    def test_collect_logs_is_low(self):
        anomaly = Anomaly(service_name="metrics-exporter", anomaly_type="high_cpu", severity_hint=Severity.LOW)
        actions = [Action(action_type="collect_logs", target="metrics-exporter")]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.LOW

    def test_stop_service_is_high(self):
        anomaly = Anomaly(service_name="demo-app", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [Action(action_type="stop_service", target="demo-app")]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.HIGH

    def test_escalate_is_high(self):
        anomaly = Anomaly(service_name="demo-app", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [Action(action_type="escalate", target="demo-app")]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.HIGH

    def test_unknown_action_defaults_medium(self):
        anomaly = Anomaly(service_name="demo-app", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [Action(action_type="unknown_thing", target="demo-app")]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.MEDIUM

    def test_empty_actions(self):
        anomaly = Anomaly(service_name="demo-app", anomaly_type="issue", severity_hint=Severity.MEDIUM)
        severity = classify_risk(anomaly, [])
        assert severity == Severity.MEDIUM


class TestClassifyRiskServiceCriticality:
    def test_mongodb_is_high(self):
        anomaly = Anomaly(service_name="mongodb", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [Action(action_type="collect_logs", target="mongodb")]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.HIGH

    def test_redis_is_high(self):
        anomaly = Anomaly(service_name="redis", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [Action(action_type="collect_logs", target="redis")]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.HIGH

    def test_postgres_is_high(self):
        anomaly = Anomaly(service_name="postgres", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [Action(action_type="collect_logs", target="postgres")]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.HIGH

    def test_kafka_is_high(self):
        anomaly = Anomaly(service_name="kafka-broker", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [Action(action_type="collect_logs", target="kafka-broker")]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.HIGH

    def test_demo_app_is_medium(self):
        anomaly = Anomaly(service_name="demo-app", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [Action(action_type="collect_logs", target="demo-app")]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.MEDIUM

    def test_worker_is_medium(self):
        anomaly = Anomaly(service_name="worker", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [Action(action_type="collect_logs", target="worker")]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.MEDIUM

    def test_generic_service_stays_low(self):
        anomaly = Anomaly(service_name="metrics-exporter", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [Action(action_type="collect_logs", target="metrics-exporter")]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.LOW


class TestClassifyRiskPlaybookOverride:
    def test_playbook_severity_as_floor(self):
        anomaly = Anomaly(service_name="metrics-exporter", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [Action(action_type="collect_logs", target="metrics-exporter")]
        severity = classify_risk(anomaly, actions, playbook_severity=Severity.MEDIUM)
        assert severity == Severity.MEDIUM

    def test_playbook_severity_cannot_lower(self):
        anomaly = Anomaly(service_name="mongodb", anomaly_type="issue", severity_hint=Severity.HIGH)
        actions = [Action(action_type="restart_service", target="mongodb")]
        # Playbook says LOW, but service criticality makes it HIGH
        severity = classify_risk(anomaly, actions, playbook_severity=Severity.LOW)
        assert severity == Severity.HIGH


class TestClassifyRiskCombinations:
    def test_max_of_all_factors(self):
        # HIGH service (mongodb) + MEDIUM action (restart) + LOW playbook
        anomaly = Anomaly(service_name="mongodb", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [Action(action_type="restart_service", target="mongodb")]
        severity = classify_risk(anomaly, actions, playbook_severity=Severity.LOW)
        assert severity == Severity.HIGH

    def test_multiple_actions_takes_highest(self):
        anomaly = Anomaly(service_name="demo", anomaly_type="issue", severity_hint=Severity.LOW)
        actions = [
            Action(action_type="collect_logs", target="demo"),  # LOW
            Action(action_type="restart_service", target="demo"),  # MEDIUM
            Action(action_type="stop_service", target="demo"),  # HIGH
        ]
        severity = classify_risk(anomaly, actions)
        assert severity == Severity.HIGH
