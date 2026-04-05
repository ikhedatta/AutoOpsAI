"""
Infrastructure provider abstract base class.

Every deployment platform (Docker Compose, Kubernetes, ECS, Nomad, …)
implements this interface.  The agent engine never calls platform-specific
APIs directly — it always goes through the provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from agent.models import (
    CommandResult,
    HealthCheckResult,
    LogEntry,
    MetricSnapshot,
    ServiceInfo,
    ServiceStatus,
)


class InfrastructureProvider(ABC):

    @abstractmethod
    async def list_services(self) -> list[ServiceInfo]:
        ...

    @abstractmethod
    async def get_service_status(self, service_name: str) -> ServiceStatus:
        ...

    @abstractmethod
    async def get_metrics(self, service_name: str) -> MetricSnapshot:
        ...

    @abstractmethod
    async def health_check(self, service_name: str) -> HealthCheckResult:
        ...

    @abstractmethod
    async def restart_service(
        self, service_name: str, timeout_seconds: int = 30
    ) -> CommandResult:
        ...

    @abstractmethod
    async def exec_command(
        self, service_name: str, command: str, timeout_seconds: int = 30
    ) -> CommandResult:
        ...

    @abstractmethod
    async def get_logs(
        self, service_name: str, lines: int = 100, since: Optional[str] = None
    ) -> list[LogEntry]:
        ...

    @abstractmethod
    async def scale_service(
        self, service_name: str, replicas: int
    ) -> CommandResult:
        ...

    @abstractmethod
    async def stop_service(self, service_name: str) -> CommandResult:
        ...

    @abstractmethod
    async def start_service(self, service_name: str) -> CommandResult:
        ...

    # -- Optional methods with default implementations -----------------------

    async def get_events(self, service_name: str, limit: int = 50) -> list[dict]:
        return []

    async def get_resource_quotas(self) -> dict:
        return {}

    async def rollback_service(
        self, service_name: str, to_version: Optional[str] = None
    ) -> CommandResult:
        return CommandResult(
            success=False, output="Rollback not supported by this provider"
        )

    def provider_name(self) -> str:
        return self.__class__.__name__
