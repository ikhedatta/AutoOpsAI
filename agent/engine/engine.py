"""
Agent Engine — the core reasoning loop of the virtual DevOps engineer.

Each ``process_cycle`` call:
1. Detects anomalies from current metrics / statuses
2. Deduplicates against active incidents
3. Matches playbooks
4. Calls the LLM for diagnosis
5. Classifies risk
6. Creates an incident in MongoDB
7. Routes to the approval system

The engine is intentionally *stateless per cycle* — all persistent state
lives in MongoDB.
"""

from __future__ import annotations

import logging

from agent.config import Settings
from agent.engine.anomaly import AnomalyDetector
from agent.engine.risk import classify_risk
from agent.knowledge.knowledge_base import KnowledgeBase
from agent.knowledge.schemas import PlaybookMatch
from agent.llm.client import LLMClient
from agent.models import (
    Action,
    Anomaly,
    Diagnosis,
    HealthCheckResult,
    IncidentStatus,
    MetricSnapshot,
    Severity,
    ServiceStatus,
)
from agent.store import incidents as incident_store
from agent.store.models import IncidentDoc

logger = logging.getLogger(__name__)


class AgentEngine:

    def __init__(
        self,
        settings: Settings,
        knowledge_base: KnowledgeBase,
        llm_client: LLMClient,
    ):
        self.settings = settings
        self.kb = knowledge_base
        self.llm = llm_client
        self.detector = AnomalyDetector()

    async def process_cycle(
        self,
        metrics: dict[str, MetricSnapshot],
        statuses: dict[str, ServiceStatus],
        health: dict[str, HealthCheckResult] | None = None,
        recent_logs: dict[str, list[str]] | None = None,
    ) -> list[IncidentDoc]:
        """
        Run one full reasoning cycle.  Returns newly created incidents.
        """
        # 1. Detect anomalies
        anomalies = self.detector.detect(
            metrics, statuses, cooldown_seconds=self.settings.cooldown_seconds
        )
        if not anomalies:
            return []

        created: list[IncidentDoc] = []
        for anomaly in anomalies:
            try:
                doc = await self._process_anomaly(
                    anomaly, metrics, statuses, health, recent_logs
                )
                if doc:
                    created.append(doc)
            except Exception:
                logger.error("Failed to process anomaly for %s", anomaly.service_name, exc_info=True)

        return created

    async def _process_anomaly(
        self,
        anomaly: Anomaly,
        metrics: dict[str, MetricSnapshot],
        statuses: dict[str, ServiceStatus],
        health: dict[str, HealthCheckResult] | None,
        recent_logs: dict[str, list[str]] | None,
    ) -> IncidentDoc | None:
        # 2. Deduplication — skip if there's an active incident for same service+type
        existing = await incident_store.find_active_incident(
            anomaly.service_name, anomaly.anomaly_type
        )
        if existing:
            logger.debug("Active incident %s already exists for %s/%s — skipping",
                         existing.incident_id, anomaly.service_name, anomaly.anomaly_type)
            return None

        # 3. Match playbooks
        matches = self.kb.match(
            metrics, statuses, health,
            provider_name=self.settings.provider_type,
        )
        best_match: PlaybookMatch | None = matches[0] if matches else None

        # 4. LLM diagnosis
        metric_dicts = {k: v.model_dump() for k, v in metrics.items()}
        svc_logs = (recent_logs or {}).get(anomaly.service_name)
        log_lines = [e if isinstance(e, str) else str(e) for e in (svc_logs or [])]

        if best_match:
            diagnosis = await self.llm.diagnose(
                anomaly=anomaly.model_dump(),
                metrics=metric_dicts,
                playbook_context=best_match.playbook.diagnosis,
                logs=log_lines,
            )
            diagnosis.playbook_id = best_match.playbook.id
        else:
            diagnosis = await self.llm.reason_novel_issue(
                metrics=metric_dicts,
                logs=log_lines,
            )

        # 5. Build proposed actions
        proposed_actions = self._build_actions(anomaly, best_match, diagnosis)

        # 6. Classify risk
        playbook_severity = best_match.playbook.severity if best_match else None
        severity = classify_risk(anomaly, proposed_actions, playbook_severity)

        # 7. Create incident
        doc = await incident_store.create_incident(
            anomaly=anomaly,
            diagnosis=diagnosis,
            proposed_actions=proposed_actions,
            severity=severity,
        )

        # Set rollback plan
        if best_match and best_match.playbook.rollback:
            doc.rollback_plan = best_match.playbook.rollback.description
            await doc.save()

        # 8. Route to approval (status update)
        if severity == Severity.LOW:
            await incident_store.update_status(
                doc.incident_id, IncidentStatus.APPROVED,
                detail="AUTO: Low-risk action auto-approved"
            )
            doc.add_timeline_event("auto_approved", "Low-risk — auto-executing")
            await doc.save()
        else:
            await incident_store.update_status(
                doc.incident_id, IncidentStatus.AWAITING_APPROVAL,
                detail=f"Awaiting {'explicit' if severity == Severity.HIGH else 'timed'} approval"
            )

        # Log the agent's reasoning as a chat message
        await incident_store.add_chat_message(
            doc.incident_id, "agent",
            f"🔍 **Anomaly detected on {anomaly.service_name}**\n\n"
            f"{diagnosis.explanation}\n\n"
            f"**Confidence:** {diagnosis.confidence:.0%}\n"
            f"**Risk level:** {severity.value}\n"
            f"**Proposed action:** {', '.join(a.description for a in proposed_actions)}"
        )

        return doc

    def _build_actions(
        self,
        anomaly: Anomaly,
        match: PlaybookMatch | None,
        diagnosis: Diagnosis,
    ) -> list[Action]:
        """Convert playbook steps or LLM recommendations into Action objects."""
        actions: list[Action] = []

        if match:
            for step in match.playbook.remediation.steps:
                target = step.target or anomaly.service_name
                actions.append(Action(
                    action_type=step.action,
                    target=target,
                    parameters={
                        k: v for k, v in step.model_dump().items()
                        if v is not None and k not in ("action", "target")
                    },
                    description=f"{step.action} on {target}",
                    timeout_seconds=step.timeout or 30,
                ))
        else:
            # Fall back to LLM recommendations
            for rec in diagnosis.recommended_actions:
                action_type = "restart_service"
                if "scale" in rec.lower():
                    action_type = "scale_service"
                elif "log" in rec.lower():
                    action_type = "collect_logs"
                elif "exec" in rec.lower() or "command" in rec.lower():
                    action_type = "exec_command"
                actions.append(Action(
                    action_type=action_type,
                    target=anomaly.service_name,
                    description=rec,
                ))

        # Always prepend log collection for audit trail
        if not any(a.action_type == "collect_logs" for a in actions):
            actions.insert(0, Action(
                action_type="collect_logs",
                target=anomaly.service_name,
                description=f"Collect logs from {anomaly.service_name} before remediation",
                parameters={"lines": 50},
            ))

        return actions
