"""
Approval router — routes incidents to the right approval channel
based on risk level.

LOW  → auto-execute, notify dashboard
MEDIUM → approval card, 5-min timeout, deny-by-default
HIGH → approval card, no timeout, explicit approval required
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from agent.config import Settings
from agent.models import (
    ApprovalDecision,
    ApprovalDecisionType,
    Severity,
)
from agent.store import incidents as incident_store
from agent.store.models import ApprovalDoc, IncidentDoc

logger = logging.getLogger(__name__)


class ApprovalRouter:

    def __init__(self, settings: Settings):
        self.settings = settings
        self._timeout_tasks: dict[str, asyncio.Task] = {}
        # Callback invoked when an incident is approved (wired to executor)
        self._on_approved: Callable[[str], Awaitable[None]] | None = None
        # Callback for WebSocket broadcast
        self._on_event: Callable[[str, dict], Awaitable[None]] | None = None

    def set_on_approved(self, callback: Callable[[str], Awaitable[None]]) -> None:
        self._on_approved = callback

    def set_on_event(self, callback: Callable[[str, dict], Awaitable[None]]) -> None:
        self._on_event = callback

    async def route(self, incident: IncidentDoc) -> None:
        """Route a new incident to the appropriate approval flow."""
        severity = Severity(incident.severity)

        # Create approval record
        approval = ApprovalDoc(
            incident_id=incident.incident_id,
            severity=severity,
            title=incident.title,
            diagnosis_summary=incident.diagnosis_summary,
            proposed_actions=incident.proposed_actions,
            rollback_plan=incident.rollback_plan,
            timeout_seconds=(
                self.settings.approval_timeout_medium_seconds
                if severity == Severity.MEDIUM else None
            ),
        )
        await approval.insert()

        if severity == Severity.LOW:
            # Auto-approve
            logger.info("AUTO-APPROVE: %s (LOW risk)", incident.incident_id)
            await self.process_decision(
                incident.incident_id,
                ApprovalDecision(
                    incident_id=incident.incident_id,
                    decision=ApprovalDecisionType.AUTO,
                    decided_by="system",
                    reason="Low-risk action auto-approved",
                ),
            )
        elif severity == Severity.MEDIUM:
            logger.info("AWAITING APPROVAL: %s (MEDIUM risk, %ds timeout)",
                        incident.incident_id, self.settings.approval_timeout_medium_seconds)
            await self._emit_event("approval_requested", {
                "incident_id": incident.incident_id,
                "severity": severity.value,
                "title": incident.title,
                "timeout_seconds": self.settings.approval_timeout_medium_seconds,
            })
            # Start timeout
            self._start_timeout(incident.incident_id)
        else:
            logger.info("AWAITING APPROVAL: %s (HIGH risk, no timeout)", incident.incident_id)
            await self._emit_event("approval_requested", {
                "incident_id": incident.incident_id,
                "severity": severity.value,
                "title": incident.title,
                "timeout_seconds": None,
            })

    async def process_decision(
        self, incident_id: str, decision: ApprovalDecision
    ) -> IncidentDoc | None:
        """Process an approve/deny/investigate decision."""
        # Cancel any pending timeout
        self._cancel_timeout(incident_id)

        # Update incident
        doc = await incident_store.record_approval(incident_id, decision)
        if not doc:
            logger.warning("Incident %s not found for approval decision", incident_id)
            return None

        # Update approval record
        approval = await ApprovalDoc.find_one(
            ApprovalDoc.incident_id == incident_id,
            {"decision": None},
        )
        if approval:
            approval.decision = decision.decision.value
            approval.decided_by = decision.decided_by
            approval.decided_at = decision.decided_at
            await approval.save()

        # Audit
        await incident_store.audit_log(
            action=f"approval_{decision.decision.value}",
            resource_type="incident",
            resource_id=incident_id,
            detail=f"By {decision.decided_by}: {decision.reason or ''}",
            user_id=decision.decided_by,
        )

        # If approved, trigger remediation
        if decision.decision in (ApprovalDecisionType.APPROVE, ApprovalDecisionType.AUTO):
            await self._emit_event("incident_approved", {
                "incident_id": incident_id,
                "approved_by": decision.decided_by,
            })
            if self._on_approved:
                await self._on_approved(incident_id)
        elif decision.decision == ApprovalDecisionType.INVESTIGATE:
            await self._emit_event("investigation_requested", {
                "incident_id": incident_id,
            })
        else:
            await self._emit_event("incident_denied", {
                "incident_id": incident_id,
                "reason": decision.reason or "denied",
            })

        return doc

    # -- timeout management --------------------------------------------------

    def _start_timeout(self, incident_id: str) -> None:
        timeout = self.settings.approval_timeout_medium_seconds

        async def _timeout_handler():
            await asyncio.sleep(timeout)
            logger.info("TIMEOUT: Approval for %s expired after %ds", incident_id, timeout)
            default = self.settings.approval_timeout_medium_default
            decision_type = (
                ApprovalDecisionType.TIMEOUT
                if default == "deny"
                else ApprovalDecisionType.APPROVE
            )
            await self.process_decision(
                incident_id,
                ApprovalDecision(
                    incident_id=incident_id,
                    decision=decision_type,
                    decided_by="system",
                    reason=f"Approval timed out after {timeout}s — default: {default}",
                ),
            )

        task = asyncio.create_task(_timeout_handler())
        self._timeout_tasks[incident_id] = task

    def _cancel_timeout(self, incident_id: str) -> None:
        task = self._timeout_tasks.pop(incident_id, None)
        if task and not task.done():
            task.cancel()

    # -- event emission ------------------------------------------------------

    async def _emit_event(self, event_type: str, data: dict) -> None:
        if self._on_event:
            try:
                await self._on_event(event_type, data)
            except Exception:
                logger.warning("Failed to emit event %s", event_type, exc_info=True)

    # -- queries -------------------------------------------------------------

    @staticmethod
    async def get_pending_approvals() -> list[ApprovalDoc]:
        return await ApprovalDoc.find(
            {"decision": None},
        ).sort("-created_at").to_list()
