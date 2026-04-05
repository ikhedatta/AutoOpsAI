"""
Metrics collector: polls Docker stats API and health endpoints to build
a snapshot of container health every N seconds.

Produces ContainerSnapshot objects that the detector can analyze.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import docker
from docker.errors import NotFound, APIError

logger = logging.getLogger("autoopsai.collector")


@dataclass
class ContainerSnapshot:
    """Point-in-time health snapshot of a single container."""
    name: str
    container_id: str
    status: str  # running, exited, restarting, paused, etc.
    health: str  # healthy, unhealthy, none (no healthcheck)
    cpu_percent: float
    memory_usage_mb: float
    memory_limit_mb: float
    memory_percent: float
    restart_count: int
    uptime_seconds: float
    image: str
    error: str | None = None
    collected_at: float = field(default_factory=time.time)


@dataclass
class SystemSnapshot:
    """Full system snapshot from one collection cycle."""
    containers: list[ContainerSnapshot]
    collected_at: float = field(default_factory=time.time)
    collection_duration_ms: float = 0.0


class MetricsCollector:
    """Polls Docker daemon for container metrics."""

    def __init__(self, filter_labels: dict[str, str] | None = None):
        self._client = docker.from_env()
        self._filter_labels = filter_labels or {}

    def collect(self) -> SystemSnapshot:
        """Collect a full snapshot of all containers."""
        start = time.time()
        snapshots = []

        try:
            containers = self._client.containers.list(all=True)
        except APIError as e:
            logger.warning("Docker API error during collection: %s", e)
            return SystemSnapshot(
                containers=[],
                collection_duration_ms=(time.time() - start) * 1000,
            )

        for container in containers:
            # Apply label filter if configured
            if self._filter_labels:
                labels = container.labels or {}
                if not all(labels.get(k) == v for k, v in self._filter_labels.items()):
                    continue

            snapshot = self._collect_container(container)
            snapshots.append(snapshot)

        duration = (time.time() - start) * 1000
        return SystemSnapshot(
            containers=snapshots,
            collected_at=start,
            collection_duration_ms=duration,
        )

    def _collect_container(self, container) -> ContainerSnapshot:
        """Collect metrics for a single container."""
        name = container.name
        cid = container.short_id
        status = container.status
        image = str(container.image.tags[0]) if (container.image and container.image.tags) else "unknown"

        # Health status
        health_state = container.attrs.get("State", {})
        health_info = health_state.get("Health", {})
        health = health_info.get("Status", "none") if health_info else "none"

        # Restart count
        restart_count = health_state.get("RestartCount", 0)

        # Uptime
        started_at = health_state.get("StartedAt", "")
        uptime = 0.0
        if started_at and status == "running":
            try:
                from datetime import datetime, timezone
                # Docker uses ISO format with nanoseconds
                started_str = started_at[:26] + "Z"  # Trim nanoseconds
                started_dt = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
                uptime = (datetime.now(timezone.utc) - started_dt).total_seconds()
            except (ValueError, TypeError):
                uptime = 0.0

        # CPU and memory stats (only for running containers)
        cpu_pct = 0.0
        mem_usage = 0.0
        mem_limit = 0.0
        mem_pct = 0.0
        error = None

        if status == "running":
            try:
                stats = container.stats(stream=False)

                # CPU calculation
                cpu_delta = (stats["cpu_stats"]["cpu_usage"]["total_usage"] -
                             stats["precpu_stats"]["cpu_usage"]["total_usage"])
                sys_delta = (stats["cpu_stats"]["system_cpu_usage"] -
                             stats["precpu_stats"]["system_cpu_usage"])
                num_cpus = stats["cpu_stats"].get("online_cpus", 1)
                if sys_delta > 0:
                    cpu_pct = (cpu_delta / sys_delta) * num_cpus * 100.0

                # Memory calculation
                mem_usage = stats["memory_stats"].get("usage", 0) / 1024 / 1024
                mem_limit = stats["memory_stats"].get("limit", 1) / 1024 / 1024
                if mem_limit > 0:
                    mem_pct = (mem_usage / mem_limit) * 100.0

            except (KeyError, ZeroDivisionError, APIError) as e:
                error = f"Stats collection failed: {e}"

        return ContainerSnapshot(
            name=name,
            container_id=cid,
            status=status,
            health=health,
            cpu_percent=round(cpu_pct, 2),
            memory_usage_mb=round(mem_usage, 2),
            memory_limit_mb=round(mem_limit, 2),
            memory_percent=round(mem_pct, 2),
            restart_count=restart_count,
            uptime_seconds=round(uptime, 1),
            image=image,
            error=error,
        )
