"""
Anomaly detection — evaluates metric snapshots and service statuses
against configurable thresholds and rules.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from agent.models import Anomaly, MetricSnapshot, ServiceState, ServiceStatus, Severity

logger = logging.getLogger(__name__)

# Default thresholds (overridable via config.yaml in future)
DEFAULT_THRESHOLDS = {
    "cpu_critical": 90.0,
    "cpu_warning": 75.0,
    "memory_critical": 85.0,
    "memory_warning": 70.0,
}


class AnomalyDetector:

    def __init__(self, thresholds: dict[str, float] | None = None):
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        # Cooldown tracking: service_name -> last anomaly timestamp
        self._cooldowns: dict[str, datetime] = {}

    def detect(
        self,
        metrics: dict[str, MetricSnapshot],
        statuses: dict[str, ServiceStatus],
        cooldown_seconds: int = 300,
    ) -> list[Anomaly]:
        """Run all detection rules.  Returns a list of anomalies found."""
        anomalies: list[Anomaly] = []
        now = datetime.now(timezone.utc)

        for svc_name, status in statuses.items():
            # Cooldown check
            last = self._cooldowns.get(svc_name)
            if last and (now - last).total_seconds() < cooldown_seconds:
                continue

            # 1. Service down
            if status.state in (ServiceState.STOPPED, ServiceState.ERROR):
                anomalies.append(Anomaly(
                    service_name=svc_name,
                    anomaly_type="service_down",
                    severity_hint=Severity.HIGH if status.state == ServiceState.ERROR else Severity.MEDIUM,
                    evidence=f"Service '{svc_name}' is {status.state.value}. "
                             f"Restart count: {status.restart_count}. "
                             f"Last error: {status.last_error or 'none'}",
                ))
                self._cooldowns[svc_name] = now
                continue

            # 2. Metric thresholds
            snap = metrics.get(svc_name)
            if not snap:
                continue

            # CPU
            if snap.cpu_percent >= self.thresholds["cpu_critical"]:
                anomalies.append(Anomaly(
                    service_name=svc_name,
                    anomaly_type="high_cpu",
                    metric="cpu_percent",
                    current_value=snap.cpu_percent,
                    threshold=self.thresholds["cpu_critical"],
                    severity_hint=Severity.MEDIUM,
                    evidence=f"CPU at {snap.cpu_percent:.1f}% (threshold {self.thresholds['cpu_critical']}%)",
                ))
                self._cooldowns[svc_name] = now

            # Memory
            mem_pct = snap.memory_percent or 0.0
            if mem_pct >= self.thresholds["memory_critical"]:
                anomalies.append(Anomaly(
                    service_name=svc_name,
                    anomaly_type="high_memory",
                    metric="memory_percent",
                    current_value=mem_pct,
                    threshold=self.thresholds["memory_critical"],
                    severity_hint=Severity.MEDIUM,
                    evidence=f"Memory at {mem_pct:.1f}% (threshold {self.thresholds['memory_critical']}%)",
                ))
                self._cooldowns[svc_name] = now

            # High restart count (possible crash loop)
            if status.restart_count >= 3:
                anomalies.append(Anomaly(
                    service_name=svc_name,
                    anomaly_type="crash_loop",
                    severity_hint=Severity.HIGH,
                    evidence=f"Service '{svc_name}' has restarted {status.restart_count} times",
                ))
                self._cooldowns[svc_name] = now

        if anomalies:
            logger.info("Detected %d anomalies: %s", len(anomalies), [a.service_name for a in anomalies])
        return anomalies

    def clear_cooldown(self, service_name: str) -> None:
        self._cooldowns.pop(service_name, None)
