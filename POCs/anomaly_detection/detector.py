"""
Anomaly detector: analyzes container snapshots against configurable
thresholds and emits AnomalyEvent objects.

Supports duration-aware alerts — only fires when a condition persists
across multiple collection cycles (e.g., CPU > 90% for 2+ minutes).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from .collector import ContainerSnapshot, SystemSnapshot

# Re-use the AnomalyEvent model from playbook_matching
from POCs.playbook_matching.knowledge_base import AnomalyEvent

logger = logging.getLogger("autoopsai.detector")


@dataclass
class ThresholdConfig:
    """Configuration for anomaly detection thresholds."""
    cpu_percent: float = 90.0
    cpu_duration_seconds: float = 120.0  # Must exceed for this long
    memory_percent: float = 85.0
    memory_duration_seconds: float = 60.0
    max_restart_count: int = 3
    restart_window_seconds: float = 600.0  # 10 minutes


@dataclass
class _ConditionState:
    """Tracks how long a threshold condition has been active."""
    first_seen: float = 0.0
    last_seen: float = 0.0
    consecutive_count: int = 0


# Type alias for anomaly callbacks
AnomalyCallback = Callable[[AnomalyEvent, ContainerSnapshot], None]


class AnomalyDetector:
    """
    Stateful anomaly detector that tracks threshold breaches over time.

    Call `analyze(snapshot)` each collection cycle. It returns a list of
    AnomalyEvent objects for any conditions that have persisted long enough.
    """

    def __init__(self, config: ThresholdConfig | None = None):
        self.config = config or ThresholdConfig()
        # Tracks per-container, per-condition state: key = (container_name, condition_type)
        self._states: dict[tuple[str, str], _ConditionState] = {}
        self._callbacks: list[AnomalyCallback] = []

    def on_anomaly(self, callback: AnomalyCallback):
        """Register a callback that fires when an anomaly is detected."""
        self._callbacks.append(callback)

    def analyze(self, snapshot: SystemSnapshot) -> list[AnomalyEvent]:
        """Analyze a system snapshot and return detected anomalies."""
        events: list[AnomalyEvent] = []
        now = time.time()

        for container in snapshot.containers:
            events.extend(self._check_container(container, now))

        # Clean up stale states (conditions not seen in 5 minutes)
        stale_cutoff = 300
        stale_keys = [
            key for key, state in self._states.items()
            if now - state.last_seen > stale_cutoff
        ]
        for key in stale_keys:
            del self._states[key]

        # Limit total tracked state to prevent memory leak from ephemeral containers
        max_tracked = 500
        if len(self._states) > max_tracked:
            sorted_keys = sorted(self._states, key=lambda k: self._states[k].last_seen)
            for key in sorted_keys[:len(self._states) - max_tracked]:
                del self._states[key]

        # Fire callbacks
        for event in events:
            # Find the matching container snapshot for context
            cs = next((c for c in snapshot.containers if c.name == event.container_name), None)
            for cb in self._callbacks:
                try:
                    cb(event, cs)
                except Exception:
                    logger.warning("Anomaly callback %s failed", cb.__name__, exc_info=True)

        return events

    def _check_container(self, cs: ContainerSnapshot, now: float) -> list[AnomalyEvent]:
        """Check a single container for anomalies."""
        events: list[AnomalyEvent] = []

        # Check 1: Container not running (exited, dead, etc.)
        if cs.status in ("exited", "dead"):
            events.append(AnomalyEvent(
                event_type="container_health",
                container_name=cs.name,
                status=cs.status,
            ))

        # Check 2: Container restarting
        if cs.status == "restarting":
            events.append(AnomalyEvent(
                event_type="container_health",
                container_name=cs.name,
                status="restarting",
            ))

        # Check 3: Restart loop
        if cs.restart_count > self.config.max_restart_count:
            events.append(AnomalyEvent(
                event_type="container_health",
                container_name=cs.name,
                restart_count=cs.restart_count,
            ))

        # Check 4: Unhealthy health check
        if cs.health == "unhealthy":
            events.append(AnomalyEvent(
                event_type="container_health",
                container_name=cs.name,
                status="unhealthy",
            ))

        # Check 5: High CPU (duration-aware)
        if cs.cpu_percent > self.config.cpu_percent:
            state = self._update_state(cs.name, "high_cpu", now)
            duration = state.last_seen - state.first_seen
            if duration >= self.config.cpu_duration_seconds:
                events.append(AnomalyEvent(
                    event_type="metric_threshold",
                    container_name=cs.name,
                    metric_name="container_cpu_percent",
                    metric_value=cs.cpu_percent,
                ))
        else:
            self._clear_state(cs.name, "high_cpu")

        # Check 6: High memory (duration-aware)
        if cs.memory_percent > self.config.memory_percent:
            state = self._update_state(cs.name, "high_memory", now)
            duration = state.last_seen - state.first_seen
            if duration >= self.config.memory_duration_seconds:
                events.append(AnomalyEvent(
                    event_type="metric_threshold",
                    container_name=cs.name,
                    metric_name="container_memory_percent",
                    metric_value=cs.memory_percent,
                ))
        else:
            self._clear_state(cs.name, "high_memory")

        return events

    def _update_state(self, container: str, condition: str, now: float) -> _ConditionState:
        """Update tracking state for a condition. Returns the state."""
        key = (container, condition)
        if key not in self._states:
            self._states[key] = _ConditionState(first_seen=now, last_seen=now, consecutive_count=1)
        else:
            self._states[key].last_seen = now
            self._states[key].consecutive_count += 1
        return self._states[key]

    def _clear_state(self, container: str, condition: str):
        """Clear tracking state when condition resolves."""
        key = (container, condition)
        self._states.pop(key, None)

    def get_active_conditions(self) -> dict[tuple[str, str], _ConditionState]:
        """Return currently tracked conditions (for debugging/dashboard)."""
        return dict(self._states)
