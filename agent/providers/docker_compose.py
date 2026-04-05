"""
Docker Compose infrastructure provider.

Uses the Docker SDK to interact with containers belonging to a specific
Compose project (identified by the ``com.docker.compose.project`` label).
"""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional

import docker
from docker.errors import NotFound

from agent.models import (
    CommandResult,
    HealthCheckResult,
    LogEntry,
    MetricSnapshot,
    ServiceInfo,
    ServiceState,
    ServiceStatus,
)
from agent.providers.base import InfrastructureProvider

logger = logging.getLogger(__name__)


class DockerComposeProvider(InfrastructureProvider):

    def __init__(
        self,
        project_name: str = "autoops-demo",
        compose_file: str = "docker-compose.yml",
        docker_host: str = "",
    ):
        kwargs = {}
        if docker_host:
            kwargs["base_url"] = docker_host
        try:
            self.client = docker.from_env(**kwargs)
        except docker.errors.DockerException:
            logger.warning("Docker daemon not available — provider will operate in degraded mode")
            self.client = None
        self.project_name = project_name
        self.compose_file = compose_file
        self._available = self.client is not None

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def provider_name() -> str:
        return "docker_compose"

    @property
    def available(self) -> bool:
        return self._available

    def _find_container(self, service_name: str):
        if not self.client:
            raise RuntimeError("Docker daemon is not available")
        containers = self.client.containers.list(
            all=True,
            filters={
                "label": [
                    f"com.docker.compose.project={self.project_name}",
                    f"com.docker.compose.service={service_name}",
                ],
            },
        )
        if not containers:
            raise NotFound(f"No container for service '{service_name}' in project '{self.project_name}'")
        return containers[0]

    @staticmethod
    def _map_state(status: str) -> ServiceState:
        mapping = {
            "running": ServiceState.RUNNING,
            "exited": ServiceState.STOPPED,
            "restarting": ServiceState.RESTARTING,
            "dead": ServiceState.ERROR,
            "created": ServiceState.STOPPED,
            "paused": ServiceState.STOPPED,
        }
        return mapping.get(status.lower(), ServiceState.UNKNOWN)

    # -- interface implementation --------------------------------------------

    async def list_services(self) -> list[ServiceInfo]:
        if not self.client:
            return []
        containers = self.client.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.project={self.project_name}"},
        )
        result = []
        for c in containers:
            created = c.attrs.get("Created")
            created_dt = None
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
            result.append(
                ServiceInfo(
                    name=c.labels.get("com.docker.compose.service", c.name),
                    platform_id=c.short_id,
                    image=str(c.image.tags[0]) if c.image.tags else str(c.image.id[:12]),
                    state=self._map_state(c.status),
                    labels=dict(c.labels),
                    created_at=created_dt,
                )
            )
        return result

    async def get_service_status(self, service_name: str) -> ServiceStatus:
        c = self._find_container(service_name)
        state_detail = c.attrs.get("State", {})
        started_str = state_detail.get("StartedAt", "")
        uptime = None
        if started_str and state_detail.get("Running"):
            try:
                started = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
                uptime = (datetime.now(timezone.utc) - started).total_seconds()
            except (ValueError, TypeError):
                pass
        return ServiceStatus(
            name=service_name,
            state=self._map_state(c.status),
            uptime_seconds=uptime,
            restart_count=c.attrs.get("RestartCount", 0),
            last_error=state_detail.get("Error") or None,
        )

    async def get_metrics(self, service_name: str) -> MetricSnapshot:
        c = self._find_container(service_name)
        stats = c.stats(stream=False)

        # CPU
        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
            stats["cpu_stats"].get("system_cpu_usage", 0)
            - stats["precpu_stats"].get("system_cpu_usage", 0)
        )
        n_cpus = stats["cpu_stats"].get("online_cpus", 1)
        cpu_percent = (cpu_delta / system_delta * n_cpus * 100.0) if system_delta > 0 else 0.0

        # Memory
        mem_usage = stats["memory_stats"].get("usage", 0)
        mem_limit = stats["memory_stats"].get("limit", 0)
        mem_pct = (mem_usage / mem_limit * 100.0) if mem_limit > 0 else 0.0

        # Network
        net = stats.get("networks", {})
        rx = sum(v.get("rx_bytes", 0) for v in net.values())
        tx = sum(v.get("tx_bytes", 0) for v in net.values())

        return MetricSnapshot(
            service_name=service_name,
            cpu_percent=round(cpu_percent, 2),
            memory_used_bytes=mem_usage,
            memory_limit_bytes=mem_limit or None,
            memory_percent=round(mem_pct, 2),
            network_rx_bytes=rx,
            network_tx_bytes=tx,
        )

    async def health_check(self, service_name: str) -> HealthCheckResult:
        try:
            c = self._find_container(service_name)
        except NotFound:
            return HealthCheckResult(
                service_name=service_name, healthy=False, message="Container not found"
            )
        state = c.attrs.get("State", {})
        health = state.get("Health", {})
        if health:
            status = health.get("Status", "none")
            return HealthCheckResult(
                service_name=service_name,
                healthy=(status == "healthy"),
                message=status,
            )
        return HealthCheckResult(
            service_name=service_name,
            healthy=state.get("Running", False),
            message=c.status,
        )

    async def restart_service(
        self, service_name: str, timeout_seconds: int = 30
    ) -> CommandResult:
        t0 = time.monotonic()
        try:
            c = self._find_container(service_name)
            c.restart(timeout=timeout_seconds)
            return CommandResult(
                success=True,
                output=f"Container '{service_name}' restarted",
                duration_seconds=round(time.monotonic() - t0, 2),
            )
        except Exception as exc:
            return CommandResult(
                success=False,
                error=str(exc),
                duration_seconds=round(time.monotonic() - t0, 2),
            )

    async def exec_command(
        self, service_name: str, command: str, timeout_seconds: int = 30
    ) -> CommandResult:
        t0 = time.monotonic()
        try:
            c = self._find_container(service_name)
            exit_code, output = c.exec_run(command, demux=True)
            stdout = output[0].decode() if output[0] else ""
            stderr = output[1].decode() if output[1] else ""
            return CommandResult(
                success=(exit_code == 0),
                output=stdout,
                error=stderr,
                exit_code=exit_code,
                duration_seconds=round(time.monotonic() - t0, 2),
            )
        except Exception as exc:
            return CommandResult(
                success=False,
                error=str(exc),
                duration_seconds=round(time.monotonic() - t0, 2),
            )

    async def get_logs(
        self, service_name: str, lines: int = 100, since: Optional[str] = None
    ) -> list[LogEntry]:
        c = self._find_container(service_name)
        raw = c.logs(tail=lines, since=since, timestamps=True).decode(errors="replace")
        entries = []
        for line in raw.strip().split("\n"):
            if not line:
                continue
            # Docker log format: "2024-01-01T00:00:00.000Z message..."
            parts = line.split(" ", 1)
            ts = None
            msg = line
            if len(parts) == 2:
                try:
                    ts = datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
                    msg = parts[1]
                except ValueError:
                    pass
            entries.append(LogEntry(timestamp=ts, message=msg))
        return entries

    async def scale_service(self, service_name: str, replicas: int) -> CommandResult:
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                [
                    "docker", "compose",
                    "-f", self.compose_file,
                    "-p", self.project_name,
                    "up", "-d", "--scale", f"{service_name}={replicas}",
                    "--no-recreate", service_name,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return CommandResult(
                success=(result.returncode == 0),
                output=result.stdout,
                error=result.stderr,
                exit_code=result.returncode,
                duration_seconds=round(time.monotonic() - t0, 2),
            )
        except Exception as exc:
            return CommandResult(
                success=False,
                error=str(exc),
                duration_seconds=round(time.monotonic() - t0, 2),
            )

    async def stop_service(self, service_name: str) -> CommandResult:
        t0 = time.monotonic()
        try:
            c = self._find_container(service_name)
            c.stop(timeout=30)
            return CommandResult(
                success=True,
                output=f"Container '{service_name}' stopped",
                duration_seconds=round(time.monotonic() - t0, 2),
            )
        except Exception as exc:
            return CommandResult(success=False, error=str(exc))

    async def start_service(self, service_name: str) -> CommandResult:
        t0 = time.monotonic()
        try:
            c = self._find_container(service_name)
            c.start()
            return CommandResult(
                success=True,
                output=f"Container '{service_name}' started",
                duration_seconds=round(time.monotonic() - t0, 2),
            )
        except Exception as exc:
            return CommandResult(success=False, error=str(exc))

    async def get_events(self, service_name: str, limit: int = 50) -> list[dict]:
        try:
            c = self._find_container(service_name)
            # Return recent Docker inspect attributes as a "poor-man's event" list
            state = c.attrs.get("State", {})
            return [{"type": "container_state", "data": state}]
        except NotFound:
            return []
