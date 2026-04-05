"""
Integration Tests for POC Features

Tests end-to-end scenarios combining multiple POCs.
These tests run without external dependencies (no Docker, Ollama, or Teams).
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from POCs.permission_system_poc.permission_checker import PermissionChecker, RiskLevel
from POCs.timeout_management_poc.timeout_executor import TimeoutExecutor, SLATracker, ActionStatus
from POCs.audit_logging_poc.audit_log import AuditLogger, AuditAction, ErrorCategory, categorize_error
from POCs.configuration_state_poc.config_manager import get_config_manager
from POCs.incident_history_poc.incident_history import (
    IncidentHistory,
    IncidentContext,
    IncidentStatus,
    ResolvedIncident,
    SimilarIncidentMatcher,
)


# ---------------------------------------------------------------------------
# Scenario 1: LOW risk auto-execution
# ---------------------------------------------------------------------------
class TestScenario1LowRiskAutoExecution:
    """LOW risk action should be auto-allowed and logged."""

    def test_permission_allows_low_risk_safe_action(self):
        checker = PermissionChecker()
        result = checker.check_permission("redis_memory_purge", RiskLevel.LOW)
        assert result.result is True

    def test_permission_denies_unknown_action_at_high_risk(self):
        checker = PermissionChecker()
        result = checker.check_permission("drop_database", RiskLevel.HIGH)
        assert result.result is False

    @pytest.mark.asyncio
    async def test_audit_log_captures_event(self, tmp_path):
        log_file = str(tmp_path / "audit.log")
        logger = AuditLogger(log_file=log_file)

        await logger.log(
            incident_id="INC-001",
            action=AuditAction.INCIDENT_DETECTED,
            user_id="system",
            details={"symptom": "Redis memory at 95%"},
        )
        await logger.log(
            incident_id="INC-001",
            action=AuditAction.RESOLVED,
            user_id="system",
            details={"resolution_time": 1.5},
        )

        trail = logger.get_incident_trail("INC-001")
        assert len(trail) == 2
        assert trail[0].action == AuditAction.INCIDENT_DETECTED
        assert trail[1].action == AuditAction.RESOLVED

    @pytest.mark.asyncio
    async def test_timeout_executor_succeeds_within_limit(self):
        executor = TimeoutExecutor()
        result = await executor.execute_with_timeout(
            action_id="test-001",
            execute_fn=lambda: asyncio.sleep(0.05),
            timeout_seconds=5,
        )
        assert result.status == ActionStatus.SUCCESS


# ---------------------------------------------------------------------------
# Scenario 2: MEDIUM risk – permission + approval + timeout interaction
# ---------------------------------------------------------------------------
class TestScenario2MediumRiskApproval:
    """MEDIUM risk should require approval and respect timeouts."""

    def test_permission_requires_approval_for_medium(self):
        checker = PermissionChecker()
        result = checker.check_permission("docker_restart_mongodb", RiskLevel.MEDIUM)
        assert result.result is False
        assert "approval" in result.reason.lower() or "not in safe" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_timeout_triggers_on_slow_action(self):
        executor = TimeoutExecutor()
        result = await executor.execute_with_timeout(
            action_id="test-timeout",
            execute_fn=lambda: asyncio.sleep(10),
            timeout_seconds=0.1,
        )
        assert result.status == ActionStatus.TIMEOUT


# ---------------------------------------------------------------------------
# Scenario 3: Incident history – search, suggest, stats
# ---------------------------------------------------------------------------
class TestScenario3IncidentHistory:
    """Incident history should find similar incidents and suggest playbooks."""

    def _make_incident(self, incident_id, symptom, playbook_id, container=None, hours_ago=1):
        now = datetime.now()
        ctx = IncidentContext(
            incident_id=incident_id,
            detected_at=now - timedelta(hours=hours_ago, minutes=5),
            symptom=symptom,
            container=container,
        )
        return ResolvedIncident(
            incident_id=incident_id,
            context=ctx,
            playbook_id=playbook_id,
            playbook_name=f"Playbook {playbook_id}",
            remediation_steps=["restart"],
            status=IncidentStatus.RESOLVED,
            resolved_at=now - timedelta(hours=hours_ago),
            resolution_time_seconds=120,
        )

    def test_find_similar_by_symptom(self):
        history = IncidentHistory()
        history.add(self._make_incident("INC-001", "Redis connection refused", "redis_restart"))
        history.add(self._make_incident("INC-002", "MongoDB timeout", "mongo_restart"))

        results = history.find_similar("Redis connection")
        assert len(results) == 1
        assert results[0].playbook_id == "redis_restart"

    def test_find_similar_with_container_filter(self):
        history = IncidentHistory()
        history.add(self._make_incident("INC-001", "high cpu", "restart_a", container="app-1"))
        history.add(self._make_incident("INC-002", "high cpu", "restart_b", container="app-2"))

        results = history.find_similar("high cpu", container="app-1")
        assert len(results) == 1
        assert results[0].incident_id == "INC-001"

    def test_playbook_stats(self):
        history = IncidentHistory()
        history.add(self._make_incident("INC-001", "redis down", "redis_restart"))
        history.add(self._make_incident("INC-002", "redis down", "redis_restart"))

        stats = history.get_playbook_stats("redis_restart")
        assert stats["usage_count"] == 2
        assert stats["success_rate"] == 1.0

    def test_get_recent_returns_correct_window(self):
        history = IncidentHistory()
        history.add(self._make_incident("INC-recent", "error", "pb1", hours_ago=1))
        history.add(self._make_incident("INC-old", "error", "pb2", hours_ago=48))

        recent = history.get_recent(hours=24)
        assert len(recent) == 1
        assert recent[0].incident_id == "INC-recent"

    def test_matcher_suggests_playbook(self):
        history = IncidentHistory()
        history.add(self._make_incident("INC-001", "nginx 502 errors", "nginx_restart", container="nginx"))

        result = SimilarIncidentMatcher.match_and_suggest_playbook(
            current_symptom="nginx 502",
            history=history,
            container="nginx",
        )
        assert result is not None
        incident, confidence = result
        assert incident.playbook_id == "nginx_restart"
        assert confidence >= 0.8


# ---------------------------------------------------------------------------
# Scenario 4: Error categorisation
# ---------------------------------------------------------------------------
class TestScenario4ErrorCategorization:
    """Error categoriser should classify error messages correctly."""

    def test_playbook_not_found(self):
        cat = categorize_error("Playbook not found for incident")
        assert cat == ErrorCategory.PLAYBOOK_NOT_FOUND

    def test_permission_denied(self):
        cat = categorize_error("Permission denied for user admin")
        assert cat == ErrorCategory.INSUFFICIENT_PERMISSIONS

    def test_timeout(self):
        cat = categorize_error("Request timeout after 120s")
        assert cat == ErrorCategory.APPROVAL_TIMEOUT

    def test_remediation_context(self):
        cat = categorize_error("Container crashed", context={"action_type": "remediation"})
        assert cat == ErrorCategory.REMEDIATION_FAILED

    def test_unknown_fallback(self):
        cat = categorize_error("Something unexpected happened")
        assert cat == ErrorCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Cross-component: audit log stats + history export
# ---------------------------------------------------------------------------
class TestCrossComponentIntegration:
    """Test how components work together."""

    @pytest.mark.asyncio
    async def test_audit_stats_after_multiple_events(self, tmp_path):
        logger = AuditLogger(log_file=str(tmp_path / "test.log"))

        await logger.log("INC-1", AuditAction.INCIDENT_DETECTED, "system", {})
        await logger.log("INC-1", AuditAction.ACTION_EXECUTED, "system", {})
        await logger.log("INC-1", AuditAction.RESOLVED, "system", {})
        await logger.log("INC-2", AuditAction.INCIDENT_DETECTED, "system", {})
        await logger.log(
            "INC-2", AuditAction.ACTION_FAILED, "system", {},
            error="Container not found",
            error_category=ErrorCategory.REMEDIATION_FAILED,
        )

        stats = logger.get_stats()
        assert stats.total_entries == 5
        assert stats.by_action["resolved"] == 1
        assert stats.by_error_category.get("remediation_failed", 0) == 1

    def test_incident_history_export(self, tmp_path):
        history = IncidentHistory()
        ctx = IncidentContext(
            incident_id="INC-001",
            detected_at=datetime.now(),
            symptom="test",
        )
        history.add(ResolvedIncident(
            incident_id="INC-001",
            context=ctx,
            playbook_id="pb1",
            playbook_name="Test Playbook",
            remediation_steps=["step1"],
            status=IncidentStatus.RESOLVED,
            resolved_at=datetime.now(),
            resolution_time_seconds=60,
        ))

        out = str(tmp_path / "export.json")
        history.export(out)
        assert Path(out).exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
