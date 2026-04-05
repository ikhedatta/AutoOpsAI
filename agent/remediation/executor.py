"""
Remediation executor — executes approved actions against the infrastructure.

For each action, it:
1. Dispatches to the provider method
2. Records the result in the incident timeline
3. Runs verification after all steps
4. Triggers rollback if verification fails
"""

from __future__ import annotations

import logging
import time

from agent.models import (
    Action,
    ActionResult,
    IncidentStatus,
)
from agent.providers.base import InfrastructureProvider
from agent.store import incidents as incident_store
from agent.store.models import IncidentDoc

logger = logging.getLogger(__name__)


class RemediationExecutor:

    def __init__(self, provider: InfrastructureProvider):
        self.provider = provider

    async def execute(self, incident_id: str) -> bool:
        """
        Execute all proposed actions for an approved incident.
        Returns True if remediation succeeded.
        """
        doc = await incident_store.get_incident(incident_id)
        if not doc:
            logger.error("Incident %s not found", incident_id)
            return False

        await incident_store.update_status(
            incident_id, IncidentStatus.EXECUTING,
            detail="Starting remediation"
        )

        # Log to chat
        await incident_store.add_chat_message(
            incident_id, "agent",
            f"⚡ **Executing remediation** for {doc.service_name}\n"
            f"Steps: {len(doc.proposed_actions)}"
        )

        all_success = True
        for action_dict in doc.proposed_actions:
            action = Action(**action_dict)
            result = await self._execute_action(action)
            await incident_store.record_action_result(incident_id, result)

            if not result.success:
                all_success = False
                await incident_store.add_chat_message(
                    incident_id, "agent",
                    f"❌ **Action failed:** {action.description}\n"
                    f"Error: {result.error}"
                )
                break
            else:
                await incident_store.add_chat_message(
                    incident_id, "agent",
                    f"✅ {action.description} — completed in {result.duration_seconds:.1f}s"
                )

        # Verification
        if all_success:
            verified = await self._verify(doc)
            if verified:
                await incident_store.update_status(
                    incident_id, IncidentStatus.RESOLVED,
                    detail="Remediation successful, verification passed"
                )
                await incident_store.add_chat_message(
                    incident_id, "agent",
                    f"🎉 **Incident resolved.** Service {doc.service_name} is healthy."
                )
                return True
            else:
                # Attempt rollback
                await incident_store.add_chat_message(
                    incident_id, "agent",
                    "⚠️ **Verification failed.** Attempting rollback..."
                )
                rollback_ok = await self._rollback(doc)
                if not rollback_ok:
                    await incident_store.update_status(
                        incident_id, IncidentStatus.ESCALATED,
                        detail="Verification failed, rollback failed — escalating"
                    )
                    await incident_store.add_chat_message(
                        incident_id, "agent",
                        "🚨 **Escalation required.** Rollback also failed. "
                        "Manual intervention needed."
                    )
                else:
                    await incident_store.update_status(
                        incident_id, IncidentStatus.FAILED,
                        detail="Remediation failed, rollback succeeded"
                    )
                return False
        else:
            await incident_store.update_status(
                incident_id, IncidentStatus.FAILED,
                detail="Remediation step failed"
            )
            return False

    async def _execute_action(self, action: Action) -> ActionResult:
        """Dispatch a single action to the provider."""
        t0 = time.monotonic()
        try:
            if action.action_type == "restart_service":
                result = await self.provider.restart_service(
                    action.target, timeout_seconds=action.timeout_seconds
                )
            elif action.action_type == "exec_command":
                cmd = action.parameters.get("command", "echo ok")
                result = await self.provider.exec_command(
                    action.target, cmd, timeout_seconds=action.timeout_seconds
                )
            elif action.action_type == "scale_service":
                replicas = action.parameters.get("replicas", 1)
                result = await self.provider.scale_service(action.target, replicas)
            elif action.action_type == "collect_logs":
                lines = action.parameters.get("lines", 50)
                logs = await self.provider.get_logs(action.target, lines=lines)
                return ActionResult(
                    action_id=action.id,
                    success=True,
                    output="\n".join(e.message for e in logs[-20:]),
                    duration_seconds=round(time.monotonic() - t0, 2),
                )
            elif action.action_type == "health_check":
                hc = await self.provider.health_check(action.target)
                return ActionResult(
                    action_id=action.id,
                    success=hc.healthy,
                    output=hc.message or ("healthy" if hc.healthy else "unhealthy"),
                    duration_seconds=round(time.monotonic() - t0, 2),
                )
            elif action.action_type == "stop_service":
                result = await self.provider.stop_service(action.target)
            elif action.action_type == "start_service":
                result = await self.provider.start_service(action.target)
            elif action.action_type == "wait":
                import asyncio
                seconds = action.parameters.get("seconds", 5)
                await asyncio.sleep(seconds)
                return ActionResult(
                    action_id=action.id,
                    success=True,
                    output=f"Waited {seconds}s",
                    duration_seconds=seconds,
                )
            elif action.action_type == "escalate":
                return ActionResult(
                    action_id=action.id,
                    success=True,
                    output=f"Escalation: {action.parameters.get('message', 'Manual review required')}",
                    duration_seconds=round(time.monotonic() - t0, 2),
                )
            else:
                return ActionResult(
                    action_id=action.id,
                    success=False,
                    error=f"Unknown action type: {action.action_type}",
                    duration_seconds=round(time.monotonic() - t0, 2),
                )

            return ActionResult(
                action_id=action.id,
                success=result.success,
                output=result.output,
                error=result.error,
                duration_seconds=round(time.monotonic() - t0, 2),
            )

        except Exception as exc:
            return ActionResult(
                action_id=action.id,
                success=False,
                error=str(exc),
                duration_seconds=round(time.monotonic() - t0, 2),
            )

    async def _verify(self, doc: IncidentDoc) -> bool:
        """Post-remediation verification — check that the service is healthy."""
        try:
            await incident_store.update_status(
                doc.incident_id, IncidentStatus.VERIFYING,
                detail="Running post-remediation verification"
            )
            hc = await self.provider.health_check(doc.service_name)
            status = await self.provider.get_service_status(doc.service_name)
            return hc.healthy and status.state.value == "running"
        except Exception:
            logger.warning("Verification failed for %s", doc.service_name, exc_info=True)
            return False

    async def _rollback(self, doc: IncidentDoc) -> bool:
        """Execute rollback steps if defined."""
        if not doc.rollback_plan:
            return False
        try:
            result = await self.provider.rollback_service(doc.service_name)
            return result.success
        except Exception:
            logger.warning("Rollback failed for %s", doc.service_name, exc_info=True)
            return False
