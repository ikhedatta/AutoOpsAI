"""
Knowledge base — loads playbook YAML files, matches anomalies to playbooks.

Supports hot-reload: call ``reload()`` or let the file watcher trigger it.
"""

from __future__ import annotations

import logging
import operator
import re
from pathlib import Path
from typing import Optional

import yaml

from agent.knowledge.schemas import (
    Detection,
    DetectionCondition,
    Playbook,
    PlaybookMatch,
    Remediation,
    RemediationStep,
    Rollback,
)
from agent.models import (
    HealthCheckResult,
    MetricSnapshot,
    Severity,
    ServiceStatus,
)

logger = logging.getLogger(__name__)

# threshold comparators
_OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
}


class KnowledgeBase:

    def __init__(self, playbooks_dir: str | Path = "playbooks"):
        self.playbooks_dir = Path(playbooks_dir)
        self._playbooks: dict[str, Playbook] = {}
        self.reload()

    # -- loading -------------------------------------------------------------

    def reload(self) -> int:
        """(Re)load all YAML playbooks from disk.  Returns count loaded."""
        self._playbooks.clear()
        if not self.playbooks_dir.exists():
            logger.warning("Playbooks directory does not exist: %s", self.playbooks_dir)
            return 0

        count = 0
        for path in sorted(self.playbooks_dir.rglob("*.yaml")):
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if not data or "id" not in data:
                    continue
                pb = self._parse_playbook(data)
                self._playbooks[pb.id] = pb
                count += 1
            except Exception:
                logger.warning("Failed to load playbook %s", path, exc_info=True)
        logger.info("Loaded %d playbooks from %s", count, self.playbooks_dir)
        return count

    @staticmethod
    def _parse_playbook(data: dict) -> Playbook:
        detection_raw = data.get("detection", {})
        detection = Detection(
            type=detection_raw.get("type", ""),
            conditions=[
                DetectionCondition(**c)
                for c in detection_raw.get("conditions", [])
            ],
        )
        remediation_raw = data.get("remediation", {})
        remediation = Remediation(
            steps=[RemediationStep(**s) for s in remediation_raw.get("steps", [])]
        )
        rollback_raw = data.get("rollback")
        rollback = None
        if rollback_raw:
            rollback = Rollback(
                description=rollback_raw.get("description", ""),
                steps=[RemediationStep(**s) for s in rollback_raw.get("steps", [])],
            )
        return Playbook(
            id=data["id"],
            name=data.get("name", data["id"]),
            severity=Severity(data.get("severity", "MEDIUM")),
            detection=detection,
            diagnosis=data.get("diagnosis", ""),
            remediation=remediation,
            provider=data.get("provider"),
            tags=data.get("tags", []),
            cooldown_seconds=data.get("cooldown_seconds", 300),
            rollback=rollback,
            metadata=data.get("metadata", {}),
        )

    # -- access --------------------------------------------------------------

    @property
    def playbooks(self) -> list[Playbook]:
        return list(self._playbooks.values())

    def get(self, playbook_id: str) -> Optional[Playbook]:
        return self._playbooks.get(playbook_id)

    # -- matching ------------------------------------------------------------

    def match(
        self,
        metrics: dict[str, MetricSnapshot],
        statuses: dict[str, ServiceStatus],
        health: dict[str, HealthCheckResult] | None = None,
        provider_name: str | None = None,
    ) -> list[PlaybookMatch]:
        """
        Evaluate all playbooks against the current infrastructure state.
        Returns ranked matches (best-fit first).
        """
        matches: list[PlaybookMatch] = []
        for pb in self._playbooks.values():
            # Skip provider-scoped playbooks that don't apply
            if pb.provider and provider_name and pb.provider != provider_name:
                continue

            confidence, matched = self._evaluate_detection(
                pb.detection, metrics, statuses, health or {}
            )
            if confidence > 0:
                matches.append(
                    PlaybookMatch(
                        playbook=pb,
                        confidence=confidence,
                        matched_conditions=matched,
                    )
                )

        matches.sort(key=lambda m: m.confidence, reverse=True)
        return matches

    def _evaluate_detection(
        self,
        detection: Detection,
        metrics: dict[str, MetricSnapshot],
        statuses: dict[str, ServiceStatus],
        health: dict[str, HealthCheckResult],
    ) -> tuple[float, list[str]]:
        """Return (confidence 0-1, list of matched condition descriptions)."""
        if not detection.conditions:
            return 0.0, []

        matched: list[str] = []
        total = len(detection.conditions)

        for cond in detection.conditions:
            if detection.type == "compound" and cond.detectors:
                # Nested compound: all sub-detectors must match
                sub_det = Detection(type="compound", conditions=cond.detectors)
                sub_conf, sub_matched = self._evaluate_detection(
                    sub_det, metrics, statuses, health
                )
                if sub_conf > 0:
                    matched.extend(sub_matched)
                continue

            if self._evaluate_condition(cond, metrics, statuses, health):
                matched.append(self._describe_condition(cond))

        if not matched:
            return 0.0, []

        confidence = len(matched) / total
        return round(confidence, 2), matched

    def _evaluate_condition(
        self,
        cond: DetectionCondition,
        metrics: dict[str, MetricSnapshot],
        statuses: dict[str, ServiceStatus],
        health: dict[str, HealthCheckResult],
    ) -> bool:
        ctype = cond.type

        if ctype == "container_health":
            svc = cond.service_name
            if not svc or svc not in statuses:
                return False
            return statuses[svc].state.value == cond.state

        if ctype == "metric_threshold":
            return self._check_threshold(cond, metrics)

        if ctype == "health_endpoint":
            svc = cond.service_name
            if not svc:
                return False
            hc = health.get(svc)
            if not hc:
                return False
            if cond.expected_status and hc.status_code != cond.expected_status:
                return True  # expected 200, got something else
            return not hc.healthy

        if ctype == "log_pattern":
            # Log pattern matching is handled at the collector level
            # Here we just check if the condition's service is in trouble
            return False

        return False

    def _check_threshold(
        self, cond: DetectionCondition, metrics: dict[str, MetricSnapshot]
    ) -> bool:
        if not cond.metric or not cond.threshold:
            return False

        # Find the right metric field across all services
        for svc_name, snap in metrics.items():
            metric_map = {
                "cpu_percent": snap.cpu_percent,
                "memory_percent": snap.memory_percent or 0.0,
                "memory_used_bytes": snap.memory_used_bytes,
                "network_rx_bytes": snap.network_rx_bytes,
                "network_tx_bytes": snap.network_tx_bytes,
            }
            value = metric_map.get(cond.metric)
            if value is None:
                continue

            # Parse threshold string like "> 90"
            op_str, threshold_val = self._parse_threshold(cond.threshold)
            if op_str and op_str in _OPS:
                if _OPS[op_str](value, threshold_val):
                    return True
        return False

    @staticmethod
    def _parse_threshold(threshold_str: str) -> tuple[str, float]:
        m = re.match(r"([><=!]+)\s*(\d+\.?\d*)", threshold_str.strip())
        if m:
            return m.group(1), float(m.group(2))
        try:
            return ">", float(threshold_str)
        except ValueError:
            return "", 0.0

    @staticmethod
    def _describe_condition(cond: DetectionCondition) -> str:
        if cond.type == "container_health":
            return f"{cond.service_name} state == {cond.state}"
        if cond.type == "metric_threshold":
            return f"{cond.metric} {cond.threshold}"
        if cond.type == "health_endpoint":
            return f"{cond.service_name} health check failing"
        if cond.type == "log_pattern":
            return f"log pattern '{cond.pattern}' on {cond.service_name}"
        return f"{cond.type}: {cond.service_name or 'unknown'}"
