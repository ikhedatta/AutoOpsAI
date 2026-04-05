"""Tests for agent.remediation.executor — action dispatching."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.models import (
    Action,
    ActionResult,
    CommandResult,
    HealthCheckResult,
    IncidentStatus,
    LogEntry,
    Severity,
)
from agent.remediation.executor import RemediationExecutor


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.restart_service = AsyncMock(return_value=CommandResult(success=True, output="restarted"))
    provider.exec_command = AsyncMock(return_value=CommandResult(success=True, output="ok", exit_code=0))
    provider.scale_service = AsyncMock(return_value=CommandResult(success=True, output="scaled"))
    provider.stop_service = AsyncMock(return_value=CommandResult(success=True, output="stopped"))
    provider.start_service = AsyncMock(return_value=CommandResult(success=True, output="started"))
    provider.get_logs = AsyncMock(return_value=[LogEntry(message="line1"), LogEntry(message="line2")])
    provider.health_check = AsyncMock(return_value=HealthCheckResult(service_name="demo", healthy=True, message="ok"))
    return provider


@pytest.fixture
def executor(mock_provider):
    return RemediationExecutor(mock_provider)


class TestActionDispatching:
    @pytest.mark.asyncio
    async def test_restart_service(self, executor, mock_provider):
        action = Action(action_type="restart_service", target="demo-app", timeout_seconds=10)
        result = await executor._execute_action(action)
        assert result.success
        mock_provider.restart_service.assert_awaited_once_with("demo-app", timeout_seconds=10)

    @pytest.mark.asyncio
    async def test_exec_command(self, executor, mock_provider):
        action = Action(
            action_type="exec_command", target="demo-app",
            parameters={"command": "ls -la"}, timeout_seconds=30,
        )
        result = await executor._execute_action(action)
        assert result.success
        mock_provider.exec_command.assert_awaited_once_with("demo-app", "ls -la", timeout_seconds=30)

    @pytest.mark.asyncio
    async def test_exec_command_default(self, executor, mock_provider):
        action = Action(action_type="exec_command", target="demo-app")
        result = await executor._execute_action(action)
        assert result.success
        # Default command is "echo ok"
        mock_provider.exec_command.assert_awaited_once_with("demo-app", "echo ok", timeout_seconds=30)

    @pytest.mark.asyncio
    async def test_scale_service(self, executor, mock_provider):
        action = Action(
            action_type="scale_service", target="demo-app",
            parameters={"replicas": 3},
        )
        result = await executor._execute_action(action)
        assert result.success
        mock_provider.scale_service.assert_awaited_once_with("demo-app", 3)

    @pytest.mark.asyncio
    async def test_collect_logs(self, executor, mock_provider):
        action = Action(
            action_type="collect_logs", target="demo-app",
            parameters={"lines": 50},
        )
        result = await executor._execute_action(action)
        assert result.success
        assert "line1" in result.output or "line2" in result.output

    @pytest.mark.asyncio
    async def test_health_check_action(self, executor, mock_provider):
        action = Action(action_type="health_check", target="demo-app")
        result = await executor._execute_action(action)
        assert result.success

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, executor, mock_provider):
        mock_provider.health_check = AsyncMock(
            return_value=HealthCheckResult(service_name="demo", healthy=False, message="unhealthy")
        )
        action = Action(action_type="health_check", target="demo-app")
        result = await executor._execute_action(action)
        assert not result.success

    @pytest.mark.asyncio
    async def test_stop_service(self, executor, mock_provider):
        action = Action(action_type="stop_service", target="demo-app")
        result = await executor._execute_action(action)
        assert result.success
        mock_provider.stop_service.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_service(self, executor, mock_provider):
        action = Action(action_type="start_service", target="demo-app")
        result = await executor._execute_action(action)
        assert result.success
        mock_provider.start_service.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_wait_action(self, executor):
        action = Action(action_type="wait", target="demo-app", parameters={"seconds": 0})
        result = await executor._execute_action(action)
        assert result.success
        assert "Waited" in result.output

    @pytest.mark.asyncio
    async def test_escalate_action(self, executor):
        action = Action(
            action_type="escalate", target="demo-app",
            parameters={"message": "Need manual review"},
        )
        result = await executor._execute_action(action)
        assert result.success
        assert "manual review" in result.output.lower()

    @pytest.mark.asyncio
    async def test_unknown_action_type(self, executor):
        action = Action(action_type="unknown_action", target="demo-app")
        result = await executor._execute_action(action)
        assert not result.success
        assert "Unknown action type" in result.error


class TestActionFailures:
    @pytest.mark.asyncio
    async def test_provider_exception(self, executor, mock_provider):
        mock_provider.restart_service = AsyncMock(side_effect=Exception("connection lost"))
        action = Action(action_type="restart_service", target="demo-app")
        result = await executor._execute_action(action)
        assert not result.success
        assert "connection lost" in result.error

    @pytest.mark.asyncio
    async def test_provider_returns_failure(self, executor, mock_provider):
        mock_provider.restart_service = AsyncMock(
            return_value=CommandResult(success=False, error="timeout")
        )
        action = Action(action_type="restart_service", target="demo-app")
        result = await executor._execute_action(action)
        assert not result.success


class TestDurationTracking:
    @pytest.mark.asyncio
    async def test_duration_recorded(self, executor, mock_provider):
        action = Action(action_type="restart_service", target="demo-app")
        result = await executor._execute_action(action)
        assert result.duration_seconds >= 0
