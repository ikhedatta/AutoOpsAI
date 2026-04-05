"""
Knowledge base: loads YAML playbooks and matches anomaly events to entries.

Matching strategies:
  1. container_health — match by container name + status
  2. metric_threshold — match by metric name exceeding threshold
  3. log_pattern — match by container name + log pattern
  4. Fuzzy fallback — partial keyword overlap when exact match fails
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PlaybookEntry:
    """A single playbook entry loaded from YAML."""
    id: str
    name: str
    severity: str  # LOW, MEDIUM, HIGH
    detection: dict
    diagnosis: str
    remediation: dict
    rollback: dict | None = None

    @property
    def detection_type(self) -> str:
        return self.detection.get("type", "")

    @property
    def conditions(self) -> list[dict]:
        return self.detection.get("conditions", [])


@dataclass
class MatchResult:
    """Result of matching an anomaly event against the knowledge base."""
    matched: bool
    entry: PlaybookEntry | None = None
    confidence: float = 0.0
    match_reason: str = ""


@dataclass
class AnomalyEvent:
    """
    Structured anomaly event from the detection layer.

    Fields vary by event type:
      - container_health: container_name, status, restart_count, dependent_services
      - metric_threshold: metric_name, value, container_name
      - log_pattern: container_name, pattern, rate
    """
    event_type: str  # container_health, metric_threshold, log_pattern
    container_name: str = ""
    status: str = ""
    restart_count: int = 0
    dependent_services: list[str] = field(default_factory=list)
    metric_name: str = ""
    metric_value: float = 0.0
    log_pattern: str = ""
    log_rate: str = ""
    raw_data: dict = field(default_factory=dict)


class KnowledgeBase:
    """Loads playbook YAML files and matches anomaly events against them."""

    def __init__(self, playbooks_dir: str | Path):
        self.playbooks_dir = Path(playbooks_dir)
        self.entries: list[PlaybookEntry] = []
        self._load_all()

    def _load_all(self):
        """Load all .yaml files from the playbooks directory."""
        self.entries = []
        for yaml_file in sorted(self.playbooks_dir.glob("*.yaml")):
            with open(yaml_file) as f:
                items = yaml.safe_load(f)
            if not isinstance(items, list):
                continue
            for item in items:
                entry = PlaybookEntry(
                    id=item["id"],
                    name=item["name"],
                    severity=item["severity"],
                    detection=item["detection"],
                    diagnosis=item.get("diagnosis", ""),
                    remediation=item.get("remediation", {}),
                    rollback=item.get("rollback"),
                )
                self.entries.append(entry)

    def match(self, event: AnomalyEvent) -> MatchResult:
        """
        Try to match an anomaly event to a playbook entry.

        Returns the best match, or a no-match result if nothing fits.
        """
        candidates: list[tuple[PlaybookEntry, float, str]] = []

        for entry in self.entries:
            score, reason = self._score_match(entry, event)
            if score > 0:
                candidates.append((entry, score, reason))

        if not candidates:
            return MatchResult(matched=False)

        # Pick the highest-scoring match
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_entry, best_score, best_reason = candidates[0]
        return MatchResult(
            matched=True,
            entry=best_entry,
            confidence=min(best_score, 1.0),
            match_reason=best_reason,
        )

    def _score_match(self, entry: PlaybookEntry, event: AnomalyEvent) -> tuple[float, str]:
        """Score how well an entry matches an event. Returns (score, reason)."""

        # Strategy 1: container_health match
        if entry.detection_type == "container_health" and event.event_type == "container_health":
            return self._match_container_health(entry, event)

        # Strategy 2: metric_threshold match
        if entry.detection_type == "metric_threshold" and event.event_type == "metric_threshold":
            return self._match_metric_threshold(entry, event)

        # Strategy 3: log_pattern match
        if entry.detection_type == "log_pattern" and event.event_type == "log_pattern":
            return self._match_log_pattern(entry, event)

        # Strategy 4: fuzzy keyword fallback (cross-type matching)
        return self._match_fuzzy(entry, event)

    def _match_container_health(self, entry: PlaybookEntry, event: AnomalyEvent) -> tuple[float, str]:
        score = 0.0
        reasons = []

        for cond in entry.conditions:
            # Match container name
            if "container_name" in cond and event.container_name:
                if cond["container_name"].lower() == event.container_name.lower():
                    score += 0.5
                    reasons.append(f"container={event.container_name}")

            # Match status
            if "status" in cond and event.status:
                if cond["status"].lower() == event.status.lower():
                    score += 0.3
                    reasons.append(f"status={event.status}")

            # Match restart count
            if "restart_count" in cond and event.restart_count > 0:
                threshold_str = cond["restart_count"]  # e.g., "> 3"
                if self._check_threshold(event.restart_count, threshold_str):
                    score += 0.4
                    reasons.append(f"restart_count={event.restart_count}")

            # Match dependent service
            if "dependent_service" in cond and event.dependent_services:
                if cond["dependent_service"] in event.dependent_services:
                    score += 0.2
                    reasons.append(f"dependent={cond['dependent_service']}")

        return score, "; ".join(reasons)

    def _match_metric_threshold(self, entry: PlaybookEntry, event: AnomalyEvent) -> tuple[float, str]:
        score = 0.0
        reasons = []

        for cond in entry.conditions:
            if "metric" in cond and event.metric_name:
                if cond["metric"].lower() == event.metric_name.lower():
                    score += 0.5
                    reasons.append(f"metric={event.metric_name}")

                    # Check if the value exceeds the threshold
                    if "threshold" in cond:
                        if self._check_threshold(event.metric_value, cond["threshold"]):
                            score += 0.4
                            reasons.append(f"value={event.metric_value} exceeds {cond['threshold']}")

        return score, "; ".join(reasons)

    def _match_log_pattern(self, entry: PlaybookEntry, event: AnomalyEvent) -> tuple[float, str]:
        score = 0.0
        reasons = []

        for cond in entry.conditions:
            if "container_name" in cond and event.container_name:
                if cond["container_name"].lower() == event.container_name.lower():
                    score += 0.4
                    reasons.append(f"container={event.container_name}")

            if "pattern" in cond and event.log_pattern:
                if cond["pattern"].lower() in event.log_pattern.lower():
                    score += 0.5
                    reasons.append(f"pattern='{cond['pattern']}'")

        return score, "; ".join(reasons)

    def _match_fuzzy(self, entry: PlaybookEntry, event: AnomalyEvent) -> tuple[float, str]:
        """Fuzzy keyword overlap between entry text and event data."""
        entry_text = f"{entry.name} {entry.diagnosis}".lower()
        event_keywords = set()

        if event.container_name:
            event_keywords.add(event.container_name.lower())
        if event.metric_name:
            event_keywords.update(event.metric_name.lower().replace("_", " ").split())
        if event.log_pattern:
            event_keywords.update(event.log_pattern.lower().split())
        if event.status:
            event_keywords.add(event.status.lower())

        if not event_keywords:
            return 0.0, ""

        hits = sum(1 for kw in event_keywords if kw in entry_text)
        score = (hits / len(event_keywords)) * 0.4  # Max 0.4 for fuzzy

        if score > 0.1:
            return score, f"fuzzy keyword match ({hits}/{len(event_keywords)} keywords)"
        return 0.0, ""

    @staticmethod
    def _check_threshold(value: float, threshold_str: str) -> bool:
        """Parse threshold like '> 90%' or '> 0.90' and compare."""
        threshold_str = threshold_str.strip()
        match = re.match(r"([><=!]+)\s*([\d.]+)(%)?", threshold_str)
        if not match:
            return False

        op = match.group(1)
        num = float(match.group(2))
        # If threshold is expressed as percentage (e.g., "> 90%"), keep as-is
        # The caller is responsible for consistent units

        if op == ">":
            return value > num
        elif op == ">=":
            return value >= num
        elif op == "<":
            return value < num
        elif op == "<=":
            return value <= num
        elif op == "==":
            return value == num
        return False

    def get_all_entries(self) -> list[PlaybookEntry]:
        return list(self.entries)

    def get_entry_by_id(self, entry_id: str) -> PlaybookEntry | None:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None
