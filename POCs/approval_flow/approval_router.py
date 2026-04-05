"""
Approval router: manages the lifecycle of incident approvals.

Handles:
  - Creating approval requests (with timeout)
  - Processing approve/deny/investigate callbacks
  - Timeout auto-deny behavior (configurable per severity)
  - Tracking pending/resolved incidents
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Awaitable, Any

logger = logging.getLogger("autoopsai.approval")


class ApprovalAction(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    INVESTIGATE = "investigate"
    TIMEOUT = "timeout"


@dataclass
class ApprovalRequest:
    """A pending approval request."""
    incident_id: str
    container_name: str
    severity: str
    diagnosis: str
    remediation_steps: list[dict]
    rollback_plan: str = ""
    confidence: float = 0.0
    created_at: float = field(default_factory=time.time)
    timeout_seconds: int = 300  # 5 minutes default
    resolved: bool = False
    resolution: ApprovalAction | None = None
    resolved_at: float | None = None
    resolved_by: str = ""


# Callback type: async function called when approval is resolved
ApprovalCallback = Callable[[ApprovalRequest, ApprovalAction], Awaitable[None]]


# Timeout defaults per severity
DEFAULT_TIMEOUTS = {
    "LOW": 0,       # Auto-execute, no approval needed
    "MEDIUM": 300,  # 5 minutes
    "HIGH": 600,    # 10 minutes, no auto-execute
}


class ApprovalRouter:
    """
    Manages approval requests with timeout handling.

    For LOW risk: auto-approve immediately
    For MEDIUM risk: wait for approval, auto-deny on timeout
    For HIGH risk: wait for approval, auto-deny on timeout (no auto-execute)
    """

    def __init__(self):
        self._pending: dict[str, ApprovalRequest] = {}
        self._resolved: list[ApprovalRequest] = []
        self._callbacks: list[ApprovalCallback] = []
        self._timeout_tasks: dict[str, asyncio.Task] = {}

    def on_resolution(self, callback: ApprovalCallback):
        """Register a callback for when an approval is resolved."""
        self._callbacks.append(callback)

    async def submit(self, request: ApprovalRequest) -> ApprovalAction:
        """
        Submit an approval request.

        For LOW severity: returns APPROVE immediately.
        For MEDIUM/HIGH: stores as pending and starts timeout countdown.
        """
        severity = request.severity.upper()

        # LOW risk → auto-approve
        if severity == "LOW":
            request.resolved = True
            request.resolution = ApprovalAction.APPROVE
            request.resolved_at = time.time()
            request.resolved_by = "auto (LOW risk)"
            self._resolved.append(request)
            await self._fire_callbacks(request, ApprovalAction.APPROVE)
            return ApprovalAction.APPROVE

        # MEDIUM/HIGH → store pending, start timeout
        timeout = request.timeout_seconds or DEFAULT_TIMEOUTS.get(severity, 300)
        request.timeout_seconds = timeout
        self._pending[request.incident_id] = request

        # Start timeout task
        task = asyncio.create_task(self._timeout_handler(request.incident_id, timeout))
        self._timeout_tasks[request.incident_id] = task

        # Return None-ish to indicate "waiting" — caller should await resolution
        # In practice, the caller would check back or use the callback
        return ApprovalAction.INVESTIGATE  # Placeholder: "pending"

    async def resolve(
        self,
        incident_id: str,
        action: ApprovalAction,
        resolved_by: str = "user",
    ) -> ApprovalRequest | None:
        """
        Resolve a pending approval with a user action.

        Returns the resolved request, or None if not found.
        """
        request = self._pending.pop(incident_id, None)
        if not request:
            return None

        # Cancel timeout
        task = self._timeout_tasks.pop(incident_id, None)
        if task and not task.done():
            task.cancel()

        request.resolved = True
        request.resolution = action
        request.resolved_at = time.time()
        request.resolved_by = resolved_by
        self._resolved.append(request)

        await self._fire_callbacks(request, action)
        return request

    async def _timeout_handler(self, incident_id: str, timeout: int):
        """Auto-deny after timeout expires."""
        await asyncio.sleep(timeout)

        request = self._pending.pop(incident_id, None)
        if not request:
            return  # Already resolved

        self._timeout_tasks.pop(incident_id, None)

        request.resolved = True
        request.resolution = ApprovalAction.TIMEOUT
        request.resolved_at = time.time()
        request.resolved_by = f"timeout ({timeout}s)"
        self._resolved.append(request)

        await self._fire_callbacks(request, ApprovalAction.TIMEOUT)

    async def _fire_callbacks(self, request: ApprovalRequest, action: ApprovalAction):
        for cb in self._callbacks:
            try:
                await cb(request, action)
            except Exception:
                logger.warning("Approval callback %s failed for %s", cb.__name__, request.incident_id, exc_info=True)

    def get_pending(self) -> list[ApprovalRequest]:
        return list(self._pending.values())

    def get_resolved(self) -> list[ApprovalRequest]:
        return list(self._resolved)

    def get_request(self, incident_id: str) -> ApprovalRequest | None:
        return self._pending.get(incident_id) or next(
            (r for r in self._resolved if r.incident_id == incident_id), None
        )
