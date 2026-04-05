"""Tests for agent.models — all transport models and enums."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.models import (
    Action,
    ActionResult,
    Anomaly,
    ApprovalDecision,
    ApprovalDecisionType,
    ApprovalRequest,
    CommandResult,
    Diagnosis,
    HealthCheckResult,
    IncidentStatus,
    LogEntry,
    MetricSnapshot,
    Severity,
    ServiceInfo,
    ServiceState,
    ServiceStatus,
    WSEvent,
)


class TestEnums:
    def test_service_state_values(self):
        assert ServiceState.RUNNING == "running"
        assert ServiceState.STOPPED == "stopped"
        assert ServiceState.RESTARTING == "restarting"
        assert ServiceState.ERROR == "error"
        assert ServiceState.UNKNOWN == "unknown"

    def test_severity_values(self):
        assert Severity.LOW == "LOW"
        assert Severity.MEDIUM == "MEDIUM"
        assert Severity.HIGH == "HIGH"

    def test_incident_status_values(self):
        assert IncidentStatus.DETECTING == "detecting"
        assert IncidentStatus.RESOLVED == "resolved"
        assert IncidentStatus.ESCALATED == "escalated"
        assert len(IncidentStatus) == 11

    def test_approval_decision_type_values(self):
        assert ApprovalDecisionType.APPROVE == "approve"
        assert ApprovalDecisionType.DENY == "deny"
        assert ApprovalDecisionType.AUTO == "auto"
        assert ApprovalDecisionType.TIMEOUT == "timeout"
        assert ApprovalDecisionType.INVESTIGATE == "investigate"


class TestServiceInfo:
    def test_basic_creation(self):
        si = ServiceInfo(
            name="demo-app",
            platform_id="abc123",
            state=ServiceState.RUNNING,
        )
        assert si.name == "demo-app"
        assert si.platform_id == "abc123"
        assert si.state == ServiceState.RUNNING
        assert si.labels == {}
        assert si.image is None

    def test_with_all_fields(self):
        now = datetime.now(timezone.utc)
        si = ServiceInfo(
            name="redis",
            platform_id="r123",
            image="redis:7",
            state=ServiceState.RUNNING,
            labels={"env": "prod"},
            created_at=now,
        )
        assert si.image == "redis:7"
        assert si.labels == {"env": "prod"}
        assert si.created_at == now


class TestServiceStatus:
    def test_running_service(self):
        ss = ServiceStatus(
            name="demo-app", state=ServiceState.RUNNING,
            uptime_seconds=3600.0, restart_count=0,
        )
        assert ss.uptime_seconds == 3600.0
        assert ss.last_error is None

    def test_errored_service(self):
        ss = ServiceStatus(
            name="demo-app", state=ServiceState.ERROR,
            restart_count=5, last_error="OOMKilled",
        )
        assert ss.restart_count == 5
        assert ss.last_error == "OOMKilled"


class TestMetricSnapshot:
    def test_defaults(self):
        m = MetricSnapshot(service_name="demo")
        assert m.cpu_percent == 0.0
        assert m.memory_used_bytes == 0
        assert m.memory_percent is None
        assert m.timestamp is not None

    def test_full_snapshot(self, sample_metric_snapshot):
        assert sample_metric_snapshot.service_name == "demo-app"
        assert sample_metric_snapshot.cpu_percent == 45.0
        assert sample_metric_snapshot.memory_percent == 47.7


class TestHealthCheckResult:
    def test_healthy(self):
        h = HealthCheckResult(service_name="demo", healthy=True, message="ok")
        assert h.healthy
        assert h.message == "ok"

    def test_unhealthy(self):
        h = HealthCheckResult(service_name="demo", healthy=False, status_code=503)
        assert not h.healthy
        assert h.status_code == 503


class TestCommandResult:
    def test_success(self):
        cr = CommandResult(success=True, output="Container restarted")
        assert cr.success
        assert cr.error == ""

    def test_failure(self):
        cr = CommandResult(success=False, error="Not found", exit_code=1)
        assert not cr.success
        assert cr.exit_code == 1


class TestLogEntry:
    def test_minimal(self):
        le = LogEntry(message="hello world")
        assert le.timestamp is None
        assert le.level is None

    def test_full(self):
        le = LogEntry(
            message="error occurred",
            level="ERROR",
            source="loki",
            timestamp=datetime.now(timezone.utc),
        )
        assert le.level == "ERROR"
        assert le.source == "loki"


class TestAnomaly:
    def test_auto_id(self):
        a = Anomaly(service_name="demo", anomaly_type="high_cpu")
        assert len(a.id) == 12  # hex[:12]
        assert a.detected_at is not None

    def test_full(self, sample_anomaly):
        assert sample_anomaly.metric == "cpu_percent"
        assert sample_anomaly.current_value == 95.0
        assert sample_anomaly.threshold == 90.0
        assert sample_anomaly.severity_hint == Severity.MEDIUM


class TestDiagnosis:
    def test_defaults(self):
        d = Diagnosis(summary="test", explanation="test explanation")
        assert d.confidence == 0.0
        assert d.root_cause is None
        assert d.recommended_actions == []
        assert not d.novel

    def test_full(self, sample_diagnosis):
        assert sample_diagnosis.confidence == 0.85
        assert len(sample_diagnosis.recommended_actions) == 1


class TestAction:
    def test_auto_id(self, sample_action):
        assert len(sample_action.id) == 12
        assert sample_action.action_type == "restart_service"
        assert sample_action.target == "demo-app"

    def test_with_parameters(self):
        a = Action(
            action_type="exec_command",
            target="demo-app",
            parameters={"command": "ls -la"},
            timeout_seconds=60,
        )
        assert a.parameters["command"] == "ls -la"


class TestActionResult:
    def test_success(self, sample_action_result):
        assert sample_action_result.success
        assert sample_action_result.duration_seconds == 2.5

    def test_failure(self):
        ar = ActionResult(
            action_id="x",
            success=False,
            error="connection refused",
            duration_seconds=0.1,
        )
        assert not ar.success
        assert ar.error == "connection refused"


class TestApprovalModels:
    def test_approval_request(self):
        ar = ApprovalRequest(
            incident_id="inc_123",
            severity=Severity.MEDIUM,
            title="High CPU",
            diagnosis_summary="CPU is high",
            proposed_actions=[],
        )
        assert ar.timeout_seconds is None
        assert ar.created_at is not None

    def test_approval_decision(self):
        ad = ApprovalDecision(
            incident_id="inc_123",
            decision=ApprovalDecisionType.APPROVE,
            decided_by="admin",
            reason="Looks good",
        )
        assert ad.decision == ApprovalDecisionType.APPROVE
        assert ad.decided_at is not None


class TestWSEvent:
    def test_creation(self):
        e = WSEvent(event_type="incident_created", data={"id": "123"})
        assert e.event_type == "incident_created"
        assert e.data == {"id": "123"}
        assert e.timestamp is not None
