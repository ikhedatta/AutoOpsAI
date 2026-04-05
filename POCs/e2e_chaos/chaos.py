"""
Chaos injection: programmatically inject failures into Docker containers.

Supports:
  - kill: stop a container (simulates crash)
  - pause: pause a container (simulates hang)
  - unpause: resume a paused container
  - start: start a stopped container (for recovery)
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import docker
from docker.errors import NotFound, APIError


@dataclass
class ChaosAction:
    """Record of a chaos action taken."""
    action: str
    target: str
    success: bool
    message: str
    timestamp: float


class ChaosInjector:
    """Injects failures into Docker containers."""

    def __init__(self):
        self._docker = docker.from_env()
        self.history: list[ChaosAction] = []

    def kill_container(self, name: str) -> ChaosAction:
        """Stop a container to simulate a crash."""
        try:
            container = self._docker.containers.get(name)
            container.stop(timeout=5)
            action = ChaosAction(
                action="kill", target=name, success=True,
                message=f"Container '{name}' stopped",
                timestamp=time.time(),
            )
        except NotFound:
            action = ChaosAction(
                action="kill", target=name, success=False,
                message=f"Container '{name}' not found",
                timestamp=time.time(),
            )
        except APIError as e:
            action = ChaosAction(
                action="kill", target=name, success=False,
                message=str(e), timestamp=time.time(),
            )
        self.history.append(action)
        return action

    def pause_container(self, name: str) -> ChaosAction:
        """Pause a container to simulate a hang."""
        try:
            container = self._docker.containers.get(name)
            container.pause()
            action = ChaosAction(
                action="pause", target=name, success=True,
                message=f"Container '{name}' paused",
                timestamp=time.time(),
            )
        except (NotFound, APIError) as e:
            action = ChaosAction(
                action="pause", target=name, success=False,
                message=str(e), timestamp=time.time(),
            )
        self.history.append(action)
        return action

    def unpause_container(self, name: str) -> ChaosAction:
        """Unpause a paused container."""
        try:
            container = self._docker.containers.get(name)
            container.unpause()
            action = ChaosAction(
                action="unpause", target=name, success=True,
                message=f"Container '{name}' unpaused",
                timestamp=time.time(),
            )
        except (NotFound, APIError) as e:
            action = ChaosAction(
                action="unpause", target=name, success=False,
                message=str(e), timestamp=time.time(),
            )
        self.history.append(action)
        return action

    def start_container(self, name: str) -> ChaosAction:
        """Start a stopped container (for manual recovery)."""
        try:
            container = self._docker.containers.get(name)
            container.start()
            action = ChaosAction(
                action="start", target=name, success=True,
                message=f"Container '{name}' started",
                timestamp=time.time(),
            )
        except (NotFound, APIError) as e:
            action = ChaosAction(
                action="start", target=name, success=False,
                message=str(e), timestamp=time.time(),
            )
        self.history.append(action)
        return action

    def get_container_status(self, name: str) -> str:
        """Get current status of a container."""
        try:
            container = self._docker.containers.get(name)
            return container.status
        except NotFound:
            return "not_found"
