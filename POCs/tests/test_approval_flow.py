"""Tests for the approval flow POC."""

import asyncio
import pytest

from POCs.approval_flow.approval_router import (
    ApprovalRouter,
    ApprovalRequest,
    ApprovalAction,
)


class TestApprovalRouter:
    """Test approval routing and timeout logic."""

    def setup_method(self):
        self.router = ApprovalRouter()

    @pytest.mark.asyncio
    async def test_low_risk_auto_approves(self):
        request = ApprovalRequest(
            incident_id="INC-001",
            container_name="webapp",
            severity="LOW",
            diagnosis="Low CPU spike",
            remediation_steps=[{"action": "collect_logs"}],
        )
        result = await self.router.submit(request)
        assert result == ApprovalAction.APPROVE
        assert request.resolved is True
        assert request.resolved_by == "auto (LOW risk)"

    @pytest.mark.asyncio
    async def test_medium_risk_pending(self):
        request = ApprovalRequest(
            incident_id="INC-002",
            container_name="webapp",
            severity="MEDIUM",
            diagnosis="High CPU",
            remediation_steps=[{"action": "docker_restart"}],
            timeout_seconds=5,
        )
        await self.router.submit(request)
        pending = self.router.get_pending()
        assert len(pending) == 1
        assert pending[0].incident_id == "INC-002"

    @pytest.mark.asyncio
    async def test_resolve_approve(self):
        request = ApprovalRequest(
            incident_id="INC-003",
            container_name="webapp",
            severity="HIGH",
            diagnosis="Critical failure",
            remediation_steps=[{"action": "docker_restart"}],
        )
        await self.router.submit(request)
        resolved = await self.router.resolve("INC-003", ApprovalAction.APPROVE, "admin")
        assert resolved is not None
        assert resolved.resolution == ApprovalAction.APPROVE
        assert resolved.resolved_by == "admin"

    @pytest.mark.asyncio
    async def test_resolve_deny(self):
        request = ApprovalRequest(
            incident_id="INC-004",
            container_name="webapp",
            severity="MEDIUM",
            diagnosis="Risky action",
            remediation_steps=[{"action": "docker_restart"}],
        )
        await self.router.submit(request)
        resolved = await self.router.resolve("INC-004", ApprovalAction.DENY, "admin")
        assert resolved.resolution == ApprovalAction.DENY

    @pytest.mark.asyncio
    async def test_timeout_auto_denies(self):
        request = ApprovalRequest(
            incident_id="INC-005",
            container_name="webapp",
            severity="MEDIUM",
            diagnosis="Needs quick approval",
            remediation_steps=[{"action": "docker_restart"}],
            timeout_seconds=1,  # 1 second timeout for test
        )
        await self.router.submit(request)
        await asyncio.sleep(1.5)

        # Should be auto-denied by timeout
        resolved = self.router.get_resolved()
        timeout_resolved = [r for r in resolved if r.incident_id == "INC-005"]
        assert len(timeout_resolved) == 1
        assert timeout_resolved[0].resolution == ApprovalAction.TIMEOUT

    @pytest.mark.asyncio
    async def test_callback_fired_on_resolve(self):
        received = []

        async def callback(req, action):
            received.append((req.incident_id, action))

        self.router.on_resolution(callback)

        request = ApprovalRequest(
            incident_id="INC-006",
            container_name="webapp",
            severity="LOW",
            diagnosis="Test",
            remediation_steps=[],
        )
        await self.router.submit(request)
        assert len(received) == 1
        assert received[0] == ("INC-006", ApprovalAction.APPROVE)

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_returns_none(self):
        result = await self.router.resolve("NONEXISTENT", ApprovalAction.APPROVE, "admin")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_request_pending(self):
        request = ApprovalRequest(
            incident_id="INC-007",
            container_name="webapp",
            severity="MEDIUM",
            diagnosis="Test",
            remediation_steps=[],
        )
        await self.router.submit(request)
        found = self.router.get_request("INC-007")
        assert found is not None
        assert found.incident_id == "INC-007"
