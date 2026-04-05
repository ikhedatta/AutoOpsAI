"""Shared test fixtures for agent tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.config import Settings
from agent.models import (
    Action,
    ActionResult,
    Anomaly,
    ApprovalDecision,
    ApprovalDecisionType,
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
)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@pytest.fixture
def settings():
    """Create a Settings instance with test defaults (no .env file)."""
    return Settings(
        ollama_host="http://localhost:11434",
        ollama_model="test-model",
        ollama_fallback_model="test-fallback",
        ollama_timeout=30,
        provider_type="docker_compose",
        compose_project_name="test-project",
        compose_file="docker-compose.yml",
        polling_interval_seconds=5,
        mongodb_url="mongodb://localhost:27017/autoops_test",
        prometheus_url="http://localhost:9090",
        loki_url="http://localhost:3100",
        grafana_url="http://localhost:3000",
        approval_timeout_medium_seconds=60,
        approval_timeout_medium_default="deny",
        api_key="",
        cooldown_seconds=60,
        max_concurrent_remediations=3,
        playbooks_dir="playbooks",
        docker_host="",
    )


# ---------------------------------------------------------------------------
# Model fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_metric_snapshot():
    return MetricSnapshot(
        service_name="demo-app",
        cpu_percent=45.0,
        memory_used_bytes=512_000_000,
        memory_limit_bytes=1_073_741_824,
        memory_percent=47.7,
        network_rx_bytes=1024,
        network_tx_bytes=2048,
    )


@pytest.fixture
def high_cpu_metrics():
    return {
        "demo-app": MetricSnapshot(
            service_name="demo-app",
            cpu_percent=95.0,
            memory_used_bytes=512_000_000,
            memory_limit_bytes=1_073_741_824,
            memory_percent=47.7,
        ),
    }


@pytest.fixture
def high_memory_metrics():
    return {
        "demo-app": MetricSnapshot(
            service_name="demo-app",
            cpu_percent=30.0,
            memory_used_bytes=900_000_000,
            memory_limit_bytes=1_073_741_824,
            memory_percent=90.0,
        ),
    }


@pytest.fixture
def normal_metrics():
    return {
        "demo-app": MetricSnapshot(
            service_name="demo-app",
            cpu_percent=30.0,
            memory_used_bytes=400_000_000,
            memory_limit_bytes=1_073_741_824,
            memory_percent=37.3,
        ),
    }


@pytest.fixture
def running_status():
    return {
        "demo-app": ServiceStatus(
            name="demo-app",
            state=ServiceState.RUNNING,
            uptime_seconds=3600.0,
            restart_count=0,
        ),
    }


@pytest.fixture
def stopped_status():
    return {
        "demo-app": ServiceStatus(
            name="demo-app",
            state=ServiceState.STOPPED,
            uptime_seconds=None,
            restart_count=0,
        ),
    }


@pytest.fixture
def error_status():
    return {
        "demo-app": ServiceStatus(
            name="demo-app",
            state=ServiceState.ERROR,
            uptime_seconds=None,
            restart_count=5,
            last_error="OOMKilled",
        ),
    }


@pytest.fixture
def crash_loop_status():
    return {
        "demo-app": ServiceStatus(
            name="demo-app",
            state=ServiceState.RUNNING,
            uptime_seconds=10.0,
            restart_count=5,
        ),
    }


@pytest.fixture
def sample_anomaly():
    return Anomaly(
        service_name="demo-app",
        anomaly_type="high_cpu",
        metric="cpu_percent",
        current_value=95.0,
        threshold=90.0,
        severity_hint=Severity.MEDIUM,
        evidence="CPU at 95.0% (threshold 90.0%)",
    )


@pytest.fixture
def sample_diagnosis():
    return Diagnosis(
        summary="High CPU on demo-app",
        explanation="The demo-app service is experiencing high CPU utilization.",
        confidence=0.85,
        root_cause="Possible runaway process or traffic spike",
        recommended_actions=["restart_service"],
    )


@pytest.fixture
def sample_action():
    return Action(
        action_type="restart_service",
        target="demo-app",
        description="Restart demo-app container",
        timeout_seconds=30,
    )


@pytest.fixture
def sample_action_result():
    return ActionResult(
        action_id="test123",
        success=True,
        output="Container 'demo-app' restarted",
        duration_seconds=2.5,
    )
