"""Tests for agent.approval — card builder and approval routing logic."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.approval.card_builder import build_approval_card, build_resolution_card
from agent.models import (
    ApprovalDecision,
    ApprovalDecisionType,
    IncidentStatus,
    Severity,
)


# ---------------------------------------------------------------------------
# Helpers — mock IncidentDoc and ApprovalDoc
# ---------------------------------------------------------------------------


def _make_incident(
    incident_id="inc_test_001",
    severity=Severity.MEDIUM,
    status="awaiting_approval",
):
    doc = MagicMock()
    doc.incident_id = incident_id
    doc.title = "High CPU on demo-app"
    doc.service_name = "demo-app"
    doc.severity = severity
    doc.status = status
    doc.detected_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    doc.diagnosis_summary = "CPU is above 90%"
    doc.diagnosis_explanation = "The service has high CPU utilisation"
    doc.diagnosis_confidence = 0.85
    doc.root_cause = "Traffic spike"
    doc.proposed_actions = [{"action_type": "restart_service", "target": "demo-app"}]
    doc.rollback_plan = "Restart did not help, collect logs"
    doc.action_results = []
    doc.approved_by = None
    doc.resolved_at = None
    return doc


def _make_approval(timeout_seconds=300):
    appr = MagicMock()
    appr.timeout_seconds = timeout_seconds
    return appr


# ---------------------------------------------------------------------------
# Card builder
# ---------------------------------------------------------------------------


class TestBuildApprovalCard:
    def test_basic_card(self):
        doc = _make_incident()
        appr = _make_approval()
        card = build_approval_card(doc, appr)
        assert card["type"] == "approval_card"
        assert card["incident_id"] == "inc_test_001"
        assert card["severity"] == "MEDIUM"
        assert card["severity_color"] == "amber"
        assert card["service_name"] == "demo-app"
        assert card["timeout_seconds"] == 300
        assert card["actions_available"] is True

    def test_low_severity_card(self):
        doc = _make_incident(severity=Severity.LOW)
        card = build_approval_card(doc, None)
        assert card["severity"] == "LOW"
        assert card["severity_color"] == "green"
        assert card["timeout_seconds"] is None

    def test_high_severity_card(self):
        doc = _make_incident(severity=Severity.HIGH, status="awaiting_approval")
        appr = _make_approval(timeout_seconds=None)
        card = build_approval_card(doc, appr)
        assert card["severity"] == "HIGH"
        assert card["severity_color"] == "red"
        assert card["timeout_seconds"] is None
        assert card["actions_available"] is True

    def test_resolved_not_actionable(self):
        doc = _make_incident(status="resolved")
        card = build_approval_card(doc, None)
        assert card["actions_available"] is False


class TestBuildResolutionCard:
    def test_resolution_with_time(self):
        doc = _make_incident(status="resolved")
        doc.resolved_at = datetime(2025, 1, 1, 0, 5, 0, tzinfo=timezone.utc)
        card = build_resolution_card(doc)
        assert card["type"] == "resolution_card"
        assert card["status"] == "resolved"
        assert card["resolution_time_seconds"] == 300.0

    def test_resolution_without_time(self):
        doc = _make_incident(status="resolved")
        doc.resolved_at = None
        card = build_resolution_card(doc)
        assert card["resolution_time_seconds"] is None


# ---------------------------------------------------------------------------
# Approval Router
# ---------------------------------------------------------------------------

class TestApprovalRouterRouting:
    @pytest.mark.asyncio
    async def test_low_risk_auto_approves(self, settings):
        from agent.approval.router import ApprovalRouter

        with patch("agent.approval.router.ApprovalDoc") as MockApprovalDoc, \
             patch("agent.approval.router.incident_store") as mock_store:

            mock_approval = AsyncMock()
            MockApprovalDoc.return_value = mock_approval
            MockApprovalDoc.find_one = AsyncMock(return_value=mock_approval)
            mock_approval.insert = AsyncMock()
            mock_approval.save = AsyncMock()

            mock_store.record_approval = AsyncMock(return_value=MagicMock())
            mock_store.audit_log = AsyncMock()

            incident = MagicMock()
            incident.incident_id = "inc_001"
            incident.severity = Severity.LOW.value
            incident.title = "Low risk"
            incident.diagnosis_summary = "test"
            incident.proposed_actions = []
            incident.rollback_plan = None

            on_approved = AsyncMock()
            router = ApprovalRouter(settings)
            router.set_on_approved(on_approved)

            await router.route(incident)

            # Should auto-approve and call on_approved
            mock_store.record_approval.assert_called_once()
            on_approved.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_medium_risk_starts_timeout(self, settings):
        from agent.approval.router import ApprovalRouter

        with patch("agent.approval.router.ApprovalDoc") as MockApprovalDoc:
            mock_approval = AsyncMock()
            MockApprovalDoc.return_value = mock_approval
            mock_approval.insert = AsyncMock()

            incident = MagicMock()
            incident.incident_id = "inc_002"
            incident.severity = Severity.MEDIUM.value
            incident.title = "Medium risk"
            incident.diagnosis_summary = "test"
            incident.proposed_actions = []
            incident.rollback_plan = None

            router = ApprovalRouter(settings)
            router._emit_event = AsyncMock()
            await router.route(incident)

            # Should start timeout
            assert "inc_002" in router._timeout_tasks
            # Clean up
            router._cancel_timeout("inc_002")

    @pytest.mark.asyncio
    async def test_high_risk_no_timeout(self, settings):
        from agent.approval.router import ApprovalRouter

        with patch("agent.approval.router.ApprovalDoc") as MockApprovalDoc:
            mock_approval = AsyncMock()
            MockApprovalDoc.return_value = mock_approval
            mock_approval.insert = AsyncMock()

            incident = MagicMock()
            incident.incident_id = "inc_003"
            incident.severity = Severity.HIGH.value
            incident.title = "High risk"
            incident.diagnosis_summary = "test"
            incident.proposed_actions = []
            incident.rollback_plan = None

            router = ApprovalRouter(settings)
            router._emit_event = AsyncMock()
            await router.route(incident)

            # Should NOT have a timeout
            assert "inc_003" not in router._timeout_tasks


class TestApprovalRouterTimeoutManagement:
    def test_cancel_nonexistent(self, settings):
        from agent.approval.router import ApprovalRouter
        router = ApprovalRouter(settings)
        # Should not raise
        router._cancel_timeout("nonexistent")

    def test_cancel_existing(self, settings):
        from agent.approval.router import ApprovalRouter
        import asyncio

        router = ApprovalRouter(settings)
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.done.return_value = False
        router._timeout_tasks["inc_001"] = mock_task
        router._cancel_timeout("inc_001")
        mock_task.cancel.assert_called_once()
        assert "inc_001" not in router._timeout_tasks

    def test_cancel_already_done(self, settings):
        from agent.approval.router import ApprovalRouter
        import asyncio

        router = ApprovalRouter(settings)
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.done.return_value = True
        router._timeout_tasks["inc_001"] = mock_task
        router._cancel_timeout("inc_001")
        mock_task.cancel.assert_not_called()
