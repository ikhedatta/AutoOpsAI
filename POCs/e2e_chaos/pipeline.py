"""
End-to-end pipeline: wires together all POCs into a single flow.

Pipeline:  Detect → Match Playbook → Classify Risk → Route → Execute → Verify
           (POC 8)    (POC 5)          (POC 6)      (POC 7)   (POC 9)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from POCs.anomaly_detection.collector import MetricsCollector, SystemSnapshot
from POCs.anomaly_detection.detector import AnomalyDetector, ThresholdConfig
from POCs.playbook_matching.knowledge_base import KnowledgeBase, AnomalyEvent, MatchResult
from POCs.tiered_autonomy.risk_classifier import route_incident, RoutingDecision, ActionPath
from POCs.remediation_loop.executor import RemediationExecutor, RemediationResult

logger = logging.getLogger("autoopsai.pipeline")


@dataclass
class IncidentRecord:
    """Complete record of an incident through the pipeline."""
    incident_id: str
    anomaly_event: AnomalyEvent
    playbook_match: MatchResult | None = None
    routing_decision: RoutingDecision | None = None
    remediation_result: RemediationResult | None = None
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    outcome: str = ""  # resolved, escalated, denied, skipped

    @property
    def mttr_ms(self) -> float:
        if self.completed_at:
            return (self.completed_at - self.started_at) * 1000
        return 0.0


class AutoOpsPipeline:
    """
    Orchestrates the full detect → diagnose → route → fix → verify flow.

    For the E2E demo, approval is auto-granted (simulating user clicking Approve).
    """

    def __init__(self, playbooks_dir: str | Path | None = None):
        if playbooks_dir is None:
            playbooks_dir = os.getenv(
                "PLAYBOOKS_DIR",
                str(Path(__file__).parent.parent / "playbook_matching" / "playbooks"),
            )
        self.collector = MetricsCollector()
        self.detector = AnomalyDetector(config=ThresholdConfig(
            cpu_percent=80, cpu_duration_seconds=0,
            memory_percent=70, memory_duration_seconds=0,
            max_restart_count=2,
        ))
        self.knowledge_base = KnowledgeBase(playbooks_dir)
        self.executor = RemediationExecutor()
        self.incidents: list[IncidentRecord] = []
        self._incident_counter = 0

        # MongoDB persistence (optional)
        self._db_available = False
        try:
            from POCs.persistence import health_check
            self._db_available = health_check()
        except Exception:
            pass

    def detect(self) -> tuple[SystemSnapshot, list[AnomalyEvent]]:
        """Step 1: Collect metrics and detect anomalies."""
        snapshot = self.collector.collect()
        events = self.detector.analyze(snapshot)
        return snapshot, events

    def process_event(self, event: AnomalyEvent, auto_approve: bool = True) -> IncidentRecord:
        """
        Process a single anomaly event through the full pipeline.

        Steps:
          1. Match against playbook
          2. Classify risk and determine routing
          3. If auto_approve or LOW risk: execute remediation
          4. Verify outcome
        """
        self._incident_counter += 1
        incident = IncidentRecord(
            incident_id=f"INC-{self._incident_counter:03d}",
            anomaly_event=event,
        )

        # Step 1: Match playbook
        match_result = self.knowledge_base.match(event)
        incident.playbook_match = match_result

        if not match_result.matched or not match_result.entry:
            # Try LLM fallback for unknown anomalies
            try:
                from POCs.pipeline_integration import diagnose_with_llm
                description = f"{event.event_type}: container={event.container_name}, status={event.status}"
                llm_result = diagnose_with_llm(description)
                if llm_result and llm_result.get("confidence", 0) > 0.3:
                    logger.info("LLM fallback matched for %s (confidence=%.0f%%)",
                                incident.incident_id, llm_result["confidence"] * 100)
                    incident.outcome = "llm_fallback"
                    # Could build steps from LLM result, but for now just log
                else:
                    incident.outcome = "no_playbook"
            except Exception:
                logger.debug("LLM fallback unavailable", exc_info=True)
                incident.outcome = "no_playbook"
            incident.completed_at = time.time()
            self.incidents.append(incident)
            self._persist_run(incident)
            return incident

        entry = match_result.entry
        steps = entry.remediation.get("steps", [])

        # Step 2: Classify risk
        container = event.container_name or ""
        decision = route_incident(
            playbook_severity=entry.severity,
            remediation_steps=steps,
            container_name=container,
            confidence=match_result.confidence,
        )
        incident.routing_decision = decision

        # Step 3: Check if we should execute
        should_execute = False
        if decision.action_path == ActionPath.AUTO_EXECUTE:
            should_execute = True
        elif decision.action_path in (ActionPath.REQUEST_APPROVAL, ActionPath.REQUIRE_APPROVAL):
            if auto_approve:
                should_execute = True
            else:
                incident.outcome = "awaiting_approval"
                incident.completed_at = time.time()
                self.incidents.append(incident)
                return incident
        elif decision.action_path == ActionPath.ESCALATE:
            incident.outcome = "escalated"
            incident.completed_at = time.time()
            self.incidents.append(incident)
            return incident

        # Step 4: Execute remediation
        if should_execute:
            result = self.executor.execute_playbook(
                playbook_id=entry.id,
                container_name=container,
                steps=steps,
            )
            incident.remediation_result = result

            if result.verified:
                incident.outcome = "resolved"
            elif result.escalated:
                incident.outcome = "escalated"
            else:
                incident.outcome = "unverified"

        incident.completed_at = time.time()
        self.incidents.append(incident)
        self._persist_run(incident)
        return incident

    def _persist_run(self, incident: IncidentRecord) -> None:
        """Persist pipeline run to MongoDB if available."""
        if not self._db_available:
            return
        try:
            from POCs.persistence import save_pipeline_run
            from dataclasses import asdict
            run_dict = {
                "incident_id": incident.incident_id,
                "container_name": incident.anomaly_event.container_name,
                "event_type": incident.anomaly_event.event_type,
                "outcome": incident.outcome,
                "mttr_ms": incident.mttr_ms,
                "started_at": incident.started_at,
                "completed_at": incident.completed_at,
                "playbook_id": incident.playbook_match.entry.id if incident.playbook_match and incident.playbook_match.entry else None,
                "risk_level": incident.routing_decision.risk_level.value if incident.routing_decision else None,
                "action_path": incident.routing_decision.action_path.value if incident.routing_decision else None,
            }
            save_pipeline_run(run_dict)
        except Exception:
            logger.warning("Failed to persist pipeline run %s", incident.incident_id, exc_info=True)
