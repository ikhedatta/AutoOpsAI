"""
Metrics collector — async polling loop that gathers infrastructure data
and feeds it to the Agent Engine.

Integrates with:
- InfrastructureProvider (Docker stats, health checks, logs)
- PrometheusClient (PromQL queries for trend analysis, alert state)
- LokiClient (LogQL queries for log-pattern anomaly detection)
- GrafanaClient (dashboard/annotation context)
"""

from __future__ import annotations

import asyncio
import logging

from agent.collector.grafana_client import GrafanaClient
from agent.collector.loki_client import LokiClient
from agent.collector.prometheus_client import PrometheusClient
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
        prometheus: PrometheusClient | None = None,
        loki: LokiClient | None = None,
        grafana: GrafanaClient | None = None,
    ):
        self.settings = settings
        self.provider = provider
        self.engine = engine
        self.prometheus = prometheus
        self.loki = loki
        self.grafana = grafana
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

        # Log observability client status
        prom_ok = await self.prometheus.is_available() if self.prometheus else False
        loki_ok = await self.loki.is_available() if self.loki else False
        grafana_ok = await self.grafana.is_available() if self.grafana else False
        logger.info(
            "Collector started — polling every %ds | prometheus=%s loki=%s grafana=%s",
            self.settings.polling_interval_seconds,
            "ok" if prom_ok else "unavailable",
            "ok" if loki_ok else "unavailable",
            "ok" if grafana_ok else "unavailable",
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Close HTTP clients
        if self.prometheus:
            await self.prometheus.close()
        if self.loki:
            await self.loki.close()
        if self.grafana:
            await self.grafana.close()
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
        """Single collection cycle — gathers provider, Prometheus, and Loki data."""
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

        # --- Enrich with Prometheus data (trend analysis, alert state) ---
        prometheus_context: dict = {}
        if self.prometheus:
            try:
                alerts = await self.prometheus.get_alerts()
                if alerts:
                    prometheus_context["active_alerts"] = alerts
                    logger.debug("Prometheus: %d active alerts", len(alerts))
            except Exception:
                logger.debug("Prometheus alert query failed")

        # --- Enrich with Loki data (log-pattern anomalies) ---
        if self.loki:
            for svc in services:
                if svc.name in recent_logs:
                    continue  # already have logs from provider
                try:
                    entries = await self.loki.query(
                        f'{{container="{svc.name}"}}',
                        limit=30,
                        duration_minutes=5,
                    )
                    if entries:
                        recent_logs[svc.name] = [e.message for e in entries]
                except Exception:
                    logger.debug("Loki query for %s failed", svc.name)

        logger.debug(
            "Collected: %d services, %d with metrics, %d with health, %d with logs",
            len(services), len(metrics), len(health), len(recent_logs),
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
