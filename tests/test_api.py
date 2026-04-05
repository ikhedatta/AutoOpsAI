"""Tests for agent.api — FastAPI route endpoints.

Uses FastAPI TestClient (sync) for simple endpoint testing without
requiring a real MongoDB or Ollama instance.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# We build a lightweight test app that skips the real lifespan
# ---------------------------------------------------------------------------


@pytest.fixture
def test_state():
    """Shared mutable dict for app_state overrides."""
    return {
        "provider": MagicMock(),
        "provider_type": "docker_compose",
        "knowledge_base": MagicMock(),
        "llm_client": MagicMock(),
        "ollama_available": True,
        "engine": MagicMock(),
        "ws_manager": MagicMock(),
        "approval_router": MagicMock(),
        "executor": MagicMock(),
        "collector": MagicMock(),
        "collector_running": False,
        "ws_clients": 0,
    }


@pytest.fixture
def client(test_state):
    """TestClient that uses a fresh FastAPI app with mocked app_state."""
    # Patch app_state so route modules pick up our mocks
    with patch("agent.main.app_state", test_state):
        from agent.api.routes_system import router as system_router
        from agent.api.routes_incidents import router as incidents_router
        from agent.api.routes_approval import router as approval_router
        from agent.api.routes_playbooks import router as playbooks_router
        from agent.api.routes_agent import router as agent_router
        from agent.api.routes_chat import router as chat_router

        test_app = FastAPI()
        test_app.include_router(system_router, prefix="/api/v1")
        test_app.include_router(incidents_router, prefix="/api/v1")
        test_app.include_router(approval_router, prefix="/api/v1")
        test_app.include_router(playbooks_router, prefix="/api/v1")
        test_app.include_router(agent_router, prefix="/api/v1")
        test_app.include_router(chat_router, prefix="/api/v1")

        with TestClient(test_app, raise_server_exceptions=False) as c:
            yield c


# ---------------------------------------------------------------------------
# System routes
# ---------------------------------------------------------------------------


class TestSystemRoutes:
    def test_health_endpoint(self, client):
        with patch("agent.api.routes_system.db") as mock_db:
            mock_db.health_check = AsyncMock(return_value=True)
            resp = client.get("/api/v1/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] in ("healthy", "degraded")
            assert "components" in data

    def test_health_degraded(self, client):
        with patch("agent.api.routes_system.db") as mock_db:
            mock_db.health_check = AsyncMock(return_value=False)
            resp = client.get("/api/v1/health")
            data = resp.json()
            assert data["status"] == "degraded"

    def test_status_no_collector(self, client, test_state):
        test_state["collector"] = None
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data

    def test_status_with_collector(self, client, test_state):
        mock_coll = MagicMock()
        mock_coll.collect_once = AsyncMock(return_value={
            "demo-app": {"name": "demo-app", "state": "running", "cpu_percent": 30},
        })
        test_state["collector"] = mock_coll
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Incident routes
# ---------------------------------------------------------------------------


class TestIncidentRoutes:
    def test_list_incidents_empty(self, client):
        with patch("agent.api.routes_incidents.incident_store") as mock_store:
            mock_store.list_incidents = AsyncMock(return_value=[])
            resp = client.get("/api/v1/incidents")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_get_incident_not_found(self, client):
        with patch("agent.api.routes_incidents.incident_store") as mock_store:
            mock_store.get_incident = AsyncMock(return_value=None)
            mock_store.get_chat_history = AsyncMock(return_value=[])
            resp = client.get("/api/v1/incidents/nonexistent")
            assert resp.status_code == 404

    def test_escalate_not_found(self, client):
        with patch("agent.api.routes_incidents.incident_store") as mock_store:
            mock_store.update_status = AsyncMock(return_value=None)
            resp = client.post("/api/v1/incidents/nonexistent/escalate")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Playbook routes
# ---------------------------------------------------------------------------


class TestPlaybookRoutes:
    def test_list_playbooks(self, client, test_state):
        mock_pb = MagicMock()
        mock_pb.id = "test_pb"
        mock_pb.name = "Test Playbook"
        mock_pb.severity.value = "MEDIUM"
        mock_pb.provider = None
        mock_pb.tags = ["cpu"]
        mock_pb.detection.type = "threshold"
        mock_pb.cooldown_seconds = 300

        kb = MagicMock()
        kb.playbooks = [mock_pb]
        test_state["knowledge_base"] = kb

        resp = client.get("/api/v1/playbooks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "test_pb"

    def test_get_playbook_not_found(self, client, test_state):
        kb = MagicMock()
        kb.get.return_value = None
        test_state["knowledge_base"] = kb

        resp = client.get("/api/v1/playbooks/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Agent control routes
# ---------------------------------------------------------------------------


class TestAgentRoutes:
    def test_get_config(self, client):
        resp = client.get("/api/v1/agent/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "provider_type" in data
        assert "polling_interval_seconds" in data
        assert "ollama_model" in data

    def test_start_no_collector(self, client, test_state):
        test_state["collector"] = None
        resp = client.post("/api/v1/agent/start")
        assert resp.status_code == 200
        assert resp.json()["error"] == "Collector not initialized"

    def test_stop_no_collector(self, client, test_state):
        test_state["collector"] = None
        resp = client.post("/api/v1/agent/stop")
        assert resp.status_code == 200
        assert resp.json()["error"] == "Collector not initialized"


# ---------------------------------------------------------------------------
# Chat routes
# ---------------------------------------------------------------------------


class TestChatRoutes:
    def test_get_chat_not_found(self, client):
        with patch("agent.api.routes_chat.incident_store") as mock_store:
            mock_store.get_chat_history = AsyncMock(return_value=[])
            resp = client.get("/api/v1/chat/nonexistent")
            assert resp.status_code == 404

    def test_ask_no_llm(self, client, test_state):
        test_state["llm_client"] = None
        resp = client.post("/api/v1/chat", json={"question": "hello"})
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Approval routes
# ---------------------------------------------------------------------------


class TestApprovalRoutes:
    def test_pending_approvals(self, client):
        with patch("agent.api.routes_approval.ApprovalDoc") as MockDoc:
            mock_query = MagicMock()
            mock_query.sort = MagicMock(return_value=mock_query)
            mock_query.to_list = AsyncMock(return_value=[])
            MockDoc.find = MagicMock(return_value=mock_query)

            resp = client.get("/api/v1/approval/pending")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_approve_no_router(self, client, test_state):
        test_state["approval_router"] = None
        resp = client.post(
            "/api/v1/approval/inc_001/approve",
            json={"user": "operator", "reason": "ok"},
        )
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# API key protection
# ---------------------------------------------------------------------------


class TestApiKeySecurity:
    def test_no_key_required_when_empty(self, client, test_state):
        """When API_KEY is empty, all requests pass through."""
        mock_coll = MagicMock()
        mock_coll.start = AsyncMock()
        test_state["collector"] = mock_coll
        resp = client.post("/api/v1/agent/start")
        assert resp.status_code == 200
