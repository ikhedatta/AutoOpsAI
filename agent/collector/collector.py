"""
Metrics collector — async polling loop that gathers infrastructure data
and feeds it to the Agent Engine.
"""

from __future__ import annotations

import asyncio
import logging

from agent.config import Settings
from agent.engine.engine import AgentEngine
from agent.models import HealthCheckResult, MetricSnapshot, ServiceStatus
from agent.providers.base import InfrastructureProvider

logger = logging.getLogger(__name__)


class MetricsCollector:

    def __init__(
        self,
        settings: Settings,
        provider: InfrastructureProvider,
        engine: AgentEngine,
    ):
        self.settings = settings
        self.provider = provider
        self.engine = engine
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Collector started — polling every %ds",
            self.settings.polling_interval_seconds,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Collector stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._collect_and_process()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("Collector cycle failed", exc_info=True)
            await asyncio.sleep(self.settings.polling_interval_seconds)

    async def _collect_and_process(self) -> None:
        """Single collection cycle."""
        services = await self.provider.list_services()
        if not services:
            logger.debug("No services discovered")
            return

        metrics: dict[str, MetricSnapshot] = {}
        statuses: dict[str, ServiceStatus] = {}
        health: dict[str, HealthCheckResult] = {}
        recent_logs: dict[str, list[str]] = {}

        for svc in services:
            try:
                statuses[svc.name] = await self.provider.get_service_status(svc.name)
            except Exception:
                logger.debug("Could not get status for %s", svc.name)
                continue

            # Only fetch metrics for running services
            if statuses[svc.name].state.value == "running":
                try:
                    metrics[svc.name] = await self.provider.get_metrics(svc.name)
                except Exception:
                    logger.debug("Could not get metrics for %s", svc.name)

                try:
                    health[svc.name] = await self.provider.health_check(svc.name)
                except Exception:
                    logger.debug("Could not get health for %s", svc.name)
            else:
                # Down service — collect last logs for diagnosis
                try:
                    logs = await self.provider.get_logs(svc.name, lines=30)
                    recent_logs[svc.name] = [e.message for e in logs]
                except Exception:
                    pass

        logger.debug(
            "Collected: %d services, %d with metrics, %d with health",
            len(services), len(metrics), len(health),
        )

        # Feed to engine
        await self.engine.process_cycle(metrics, statuses, health, recent_logs)

    async def collect_once(self) -> dict:
        """Manual one-shot collection — used by the API for /status."""
        services = await self.provider.list_services()
        result = {}
        for svc in services:
            entry: dict = {"name": svc.name, "state": svc.state.value}
            try:
                status = await self.provider.get_service_status(svc.name)
                entry["uptime_seconds"] = status.uptime_seconds
                entry["restart_count"] = status.restart_count
            except Exception:
                pass
            if svc.state.value == "running":
                try:
                    m = await self.provider.get_metrics(svc.name)
                    entry["cpu_percent"] = m.cpu_percent
                    entry["memory_percent"] = m.memory_percent
                    entry["memory_used_bytes"] = m.memory_used_bytes
                except Exception:
                    pass
                try:
                    hc = await self.provider.health_check(svc.name)
                    entry["healthy"] = hc.healthy
                except Exception:
                    pass
            result[svc.name] = entry
        return result
