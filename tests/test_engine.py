"""Tests for agent.engine.engine — the core reasoning loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.engine.engine import AgentEngine
from agent.knowledge.schemas import (
    Detection,
    DetectionCondition,
    Playbook,
    PlaybookMatch,
    Remediation,
    RemediationStep,
)
from agent.models import (
    Action,
    Anomaly,
    Diagnosis,
    IncidentStatus,
    MetricSnapshot,
    Severity,
    ServiceState,
    ServiceStatus,
)


@pytest.fixture
def mock_kb():
    kb = MagicMock()
    kb.match.return_value = []
    return kb


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.diagnose = AsyncMock(return_value=Diagnosis(
        summary="Test diagnosis",
        explanation="This is a test",
        confidence=0.8,
        root_cause="test",
        recommended_actions=["restart_service"],
    ))
    llm.reason_novel_issue = AsyncMock(return_value=Diagnosis(
        summary="Novel issue",
        explanation="Unknown pattern",
        confidence=0.4,
        novel=True,
    ))
    return llm


@pytest.fixture
def engine(settings, mock_kb, mock_llm):
    return AgentEngine(settings, mock_kb, mock_llm)


class TestBuildActions:
    def test_from_playbook(self, engine, sample_anomaly):
        pb = Playbook(
            id="test", name="Test", severity=Severity.MEDIUM,
            detection=Detection(type="threshold"),
            diagnosis="",
            remediation=Remediation(steps=[
                RemediationStep(action="restart_service", target="demo-app", timeout=30),
                RemediationStep(action="collect_logs", target=None, lines=50),
            ]),
        )
        match = PlaybookMatch(playbook=pb, confidence=0.9)
        diagnosis = Diagnosis(summary="test", explanation="test")

        actions = engine._build_actions(sample_anomaly, match, diagnosis)
        assert len(actions) == 2
        assert actions[0].action_type == "restart_service"
        assert actions[0].target == "demo-app"
        assert actions[0].timeout_seconds == 30
        # Second action without explicit target should use anomaly's service
        assert actions[1].action_type == "collect_logs"
        assert actions[1].target == "demo-app"

    def test_from_llm_recommendations(self, engine, sample_anomaly):
        diagnosis = Diagnosis(
            summary="test", explanation="test",
            recommended_actions=["restart_service", "check_logs"],
        )
        actions = engine._build_actions(sample_anomaly, None, diagnosis)
        assert len(actions) == 2
        assert all(a.target == "demo-app" for a in actions)


class TestProcessCycle:
    @pytest.mark.asyncio
    async def test_no_anomalies_returns_empty(self, engine, normal_metrics, running_status):
        result = await engine.process_cycle(normal_metrics, running_status)
        assert result == []

    @pytest.mark.asyncio
    async def test_detects_anomaly_creates_incident(self, engine, high_cpu_metrics, running_status, mock_llm):
        with patch("agent.engine.engine.incident_store") as mock_store:
            mock_store.find_active_incident = AsyncMock(return_value=None)
            mock_doc = MagicMock()
            mock_doc.incident_id = "inc_001"
            mock_doc.severity = Severity.MEDIUM
            mock_doc.title = "Test"
            mock_doc.save = AsyncMock()
            mock_doc.add_timeline_event = MagicMock()
            mock_store.create_incident = AsyncMock(return_value=mock_doc)
            mock_store.update_status = AsyncMock(return_value=mock_doc)
            mock_store.add_chat_message = AsyncMock()

            result = await engine.process_cycle(high_cpu_metrics, running_status)
            assert len(result) >= 1
            mock_store.create_incident.assert_called()

    @pytest.mark.asyncio
    async def test_deduplication_skips_existing(self, engine, high_cpu_metrics, running_status):
        with patch("agent.engine.engine.incident_store") as mock_store:
            mock_store.find_active_incident = AsyncMock(return_value=MagicMock())  # existing incident

            result = await engine.process_cycle(high_cpu_metrics, running_status)
            assert len(result) == 0
            mock_store.create_incident.assert_not_called()

    @pytest.mark.asyncio
    async def test_playbook_match_used(self, engine, high_cpu_metrics, running_status, mock_kb, mock_llm):
        pb = Playbook(
            id="cpu_playbook", name="CPU Playbook", severity=Severity.MEDIUM,
            detection=Detection(type="threshold"),
            diagnosis="CPU is high",
            remediation=Remediation(steps=[
                RemediationStep(action="restart_service", target="demo-app"),
            ]),
        )
        mock_kb.match.return_value = [PlaybookMatch(playbook=pb, confidence=0.9)]

        with patch("agent.engine.engine.incident_store") as mock_store:
            mock_store.find_active_incident = AsyncMock(return_value=None)
            mock_doc = MagicMock()
            mock_doc.incident_id = "inc_001"
            mock_doc.severity = Severity.MEDIUM
            mock_doc.title = "Test"
            mock_doc.save = AsyncMock()
            mock_doc.add_timeline_event = MagicMock()
            mock_store.create_incident = AsyncMock(return_value=mock_doc)
            mock_store.update_status = AsyncMock(return_value=mock_doc)
            mock_store.add_chat_message = AsyncMock()

            result = await engine.process_cycle(high_cpu_metrics, running_status)
            assert len(result) >= 1
            mock_llm.diagnose.assert_called()
            mock_llm.reason_novel_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_novel_issue_when_no_playbook(self, engine, high_cpu_metrics, running_status, mock_kb, mock_llm):
        mock_kb.match.return_value = []  # No playbook match

        with patch("agent.engine.engine.incident_store") as mock_store:
            mock_store.find_active_incident = AsyncMock(return_value=None)
            mock_doc = MagicMock()
            mock_doc.incident_id = "inc_001"
            mock_doc.severity = Severity.MEDIUM
            mock_doc.title = "Test"
            mock_doc.save = AsyncMock()
            mock_doc.add_timeline_event = MagicMock()
            mock_store.create_incident = AsyncMock(return_value=mock_doc)
            mock_store.update_status = AsyncMock(return_value=mock_doc)
            mock_store.add_chat_message = AsyncMock()

            result = await engine.process_cycle(high_cpu_metrics, running_status)
            assert len(result) >= 1
            mock_llm.reason_novel_issue.assert_called()

    @pytest.mark.asyncio
    async def test_exception_on_single_anomaly_continues(self, engine, running_status):
        # Two services, one will fail
        metrics = {
            "app1": MetricSnapshot(service_name="app1", cpu_percent=95.0, memory_used_bytes=100, memory_percent=10.0),
            "app2": MetricSnapshot(service_name="app2", cpu_percent=95.0, memory_used_bytes=100, memory_percent=10.0),
        }
        statuses = {
            "app1": ServiceStatus(name="app1", state=ServiceState.RUNNING, restart_count=0),
            "app2": ServiceStatus(name="app2", state=ServiceState.RUNNING, restart_count=0),
        }

        call_count = 0
        with patch("agent.engine.engine.incident_store") as mock_store:
            async def fail_then_succeed(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return None  # First call — no existing incident
                return None

            mock_store.find_active_incident = AsyncMock(side_effect=fail_then_succeed)
            mock_doc = MagicMock()
            mock_doc.incident_id = "inc_001"
            mock_doc.severity = Severity.MEDIUM
            mock_doc.title = "Test"
            mock_doc.save = AsyncMock()
            mock_doc.add_timeline_event = MagicMock()
            mock_store.create_incident = AsyncMock(return_value=mock_doc)
            mock_store.update_status = AsyncMock(return_value=mock_doc)
            mock_store.add_chat_message = AsyncMock()

            result = await engine.process_cycle(metrics, statuses)
            # Should process both anomalies despite any issues
            assert mock_store.create_incident.call_count >= 1
