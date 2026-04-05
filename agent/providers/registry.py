"""
Provider factory — create the right InfrastructureProvider from config.
"""

from __future__ import annotations

from agent.config import Settings
from agent.providers.base import InfrastructureProvider


_REGISTRY: dict[str, type[InfrastructureProvider]] = {}


def register_provider(name: str, cls: type[InfrastructureProvider]) -> None:
    _REGISTRY[name] = cls


def get_provider(settings: Settings) -> InfrastructureProvider:
    ptype = settings.provider_type.lower()

    if ptype in _REGISTRY:
        return _REGISTRY[ptype]()

    if ptype == "docker_compose":
        from agent.providers.docker_compose import DockerComposeProvider

        return DockerComposeProvider(
            project_name=settings.compose_project_name,
            compose_file=settings.compose_file,
            docker_host=settings.docker_host,
        )

    raise ValueError(f"Unknown provider type: {settings.provider_type}")
