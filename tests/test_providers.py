"""Tests for agent.providers — Docker Compose provider and registry."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.config import Settings
from agent.models import ServiceState
from agent.providers.base import InfrastructureProvider
from agent.providers.docker_compose import DockerComposeProvider
from agent.providers.registry import get_provider, register_provider


# ---------------------------------------------------------------------------
# DockerComposeProvider — graceful degradation
# ---------------------------------------------------------------------------


class TestDockerComposeProviderInit:
    @patch("agent.providers.docker_compose.docker")
    def test_creates_with_docker_available(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_docker.errors.DockerException = Exception
        provider = DockerComposeProvider(project_name="test")
        assert provider.client is mock_client
        assert provider.available is True
        assert provider.project_name == "test"

    @patch("agent.providers.docker_compose.docker")
    def test_degrades_gracefully_without_docker(self, mock_docker):
        mock_docker.errors.DockerException = Exception
        mock_docker.from_env.side_effect = Exception("Docker daemon not running")
        provider = DockerComposeProvider()
        assert provider.client is None
        assert provider.available is False

    @patch("agent.providers.docker_compose.docker")
    def test_provider_name(self, mock_docker):
        mock_docker.from_env.return_value = MagicMock()
        mock_docker.errors.DockerException = Exception
        provider = DockerComposeProvider()
        assert provider.provider_name() == "docker_compose"


class TestDockerComposeProviderDegraded:
    @pytest.mark.asyncio
    async def test_list_services_empty(self):
        with patch("agent.providers.docker_compose.docker") as mock_docker:
            mock_docker.errors.DockerException = Exception
            mock_docker.from_env.side_effect = Exception("nope")
            provider = DockerComposeProvider()
            result = await provider.list_services()
            assert result == []

    @pytest.mark.asyncio
    async def test_find_container_raises_when_degraded(self):
        with patch("agent.providers.docker_compose.docker") as mock_docker:
            mock_docker.errors.DockerException = Exception
            mock_docker.from_env.side_effect = Exception("nope")
            provider = DockerComposeProvider()
            with pytest.raises(RuntimeError, match="Docker daemon is not available"):
                provider._find_container("demo-app")


class TestDockerComposeProviderOperations:
    @patch("agent.providers.docker_compose.docker")
    @pytest.mark.asyncio
    async def test_restart_service_success(self, mock_docker):
        mock_container = MagicMock()
        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_container]
        mock_docker.from_env.return_value = mock_client
        mock_docker.errors.DockerException = Exception

        provider = DockerComposeProvider(project_name="test")
        result = await provider.restart_service("demo-app", timeout_seconds=10)
        assert result.success

    @patch("agent.providers.docker_compose.docker")
    @pytest.mark.asyncio
    async def test_restart_service_failure(self, mock_docker):
        mock_container = MagicMock()
        mock_container.restart.side_effect = Exception("connection lost")
        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_container]
        mock_docker.from_env.return_value = mock_client
        mock_docker.errors.DockerException = Exception

        provider = DockerComposeProvider(project_name="test")
        result = await provider.restart_service("demo-app")
        assert not result.success
        assert "connection lost" in result.error

    @patch("agent.providers.docker_compose.docker")
    @pytest.mark.asyncio
    async def test_health_check_not_found(self, mock_docker):
        from docker.errors import NotFound
        mock_client = MagicMock()
        mock_client.containers.list.return_value = []
        mock_docker.from_env.return_value = mock_client
        mock_docker.errors.DockerException = Exception
        mock_docker.errors.NotFound = NotFound

        provider = DockerComposeProvider(project_name="test")
        # The _find_container raises NotFound when list is empty
        result = await provider.health_check("nonexistent")
        assert not result.healthy


class TestStateMapping:
    def test_all_states(self):
        assert DockerComposeProvider._map_state("running") == ServiceState.RUNNING
        assert DockerComposeProvider._map_state("exited") == ServiceState.STOPPED
        assert DockerComposeProvider._map_state("restarting") == ServiceState.RESTARTING
        assert DockerComposeProvider._map_state("dead") == ServiceState.ERROR
        assert DockerComposeProvider._map_state("created") == ServiceState.STOPPED
        assert DockerComposeProvider._map_state("paused") == ServiceState.STOPPED

    def test_unknown_state(self):
        assert DockerComposeProvider._map_state("foobar") == ServiceState.UNKNOWN

    def test_case_insensitive(self):
        assert DockerComposeProvider._map_state("Running") == ServiceState.RUNNING
        assert DockerComposeProvider._map_state("EXITED") == ServiceState.STOPPED


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    def test_get_docker_compose_provider(self):
        with patch("agent.providers.docker_compose.docker") as mock_docker:
            mock_docker.from_env.return_value = MagicMock()
            mock_docker.errors.DockerException = Exception
            settings = Settings(provider_type="docker_compose", _env_file=None)
            provider = get_provider(settings)
            assert isinstance(provider, DockerComposeProvider)

    def test_unknown_provider_raises(self):
        settings = Settings(provider_type="nonexistent", _env_file=None)
        with pytest.raises(ValueError, match="Unknown provider type"):
            get_provider(settings)

    def test_register_custom_provider(self):
        class FakeProvider(InfrastructureProvider):
            async def list_services(self): return []
            async def get_service_status(self, name): pass
            async def get_metrics(self, name): pass
            async def health_check(self, name): pass
            async def restart_service(self, name, **kw): pass
            async def exec_command(self, name, cmd, **kw): pass
            async def get_logs(self, name, **kw): return []
            async def scale_service(self, name, replicas): pass
            async def stop_service(self, name): pass
            async def start_service(self, name): pass

        register_provider("fake", FakeProvider)
        settings = Settings(provider_type="fake", _env_file=None)
        provider = get_provider(settings)
        assert isinstance(provider, FakeProvider)
