"""Tests for agent.collector — Prometheus client, Loki client, collector loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.collector.prometheus_client import PrometheusClient
from agent.collector.loki_client import LokiClient
from agent.models import LogEntry


# ---------------------------------------------------------------------------
# PrometheusClient
# ---------------------------------------------------------------------------


class TestPrometheusClient:
    @pytest.mark.asyncio
    async def test_query_success(self):
        client = PrometheusClient("http://localhost:9090")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": {"result": [{"metric": {"__name__": "up"}, "value": [1, "1"]}]}}

        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.query("up")
            assert len(result) == 1
            assert result[0]["metric"]["__name__"] == "up"

    @pytest.mark.asyncio
    async def test_query_failure_returns_empty(self):
        client = PrometheusClient("http://localhost:9090")
        with patch.object(client._http, "get", new_callable=AsyncMock, side_effect=Exception("connection refused")):
            result = await client.query("up")
            assert result == []

    @pytest.mark.asyncio
    async def test_query_range_success(self):
        client = PrometheusClient("http://localhost:9090")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": {"result": []}}

        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.query_range("up", "now-1h", "now")
            assert result == []

    @pytest.mark.asyncio
    async def test_query_range_failure(self):
        client = PrometheusClient("http://localhost:9090")
        with patch.object(client._http, "get", new_callable=AsyncMock, side_effect=Exception("timeout")):
            result = await client.query_range("up", "now-1h", "now")
            assert result == []

    @pytest.mark.asyncio
    async def test_is_available_true(self):
        client = PrometheusClient("http://localhost:9090")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            assert await client.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_false(self):
        client = PrometheusClient("http://localhost:9090")
        with patch.object(client._http, "get", new_callable=AsyncMock, side_effect=Exception("down")):
            assert await client.is_available() is False


# ---------------------------------------------------------------------------
# LokiClient
# ---------------------------------------------------------------------------


class TestLokiClient:
    @pytest.mark.asyncio
    async def test_query_success(self):
        client = LokiClient("http://localhost:3100")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "result": [
                    {
                        "stream": {"job": "demo"},
                        "values": [
                            ["1234567890000000000", "error: connection refused"],
                            ["1234567891000000000", "info: retrying"],
                        ],
                    }
                ]
            }
        }
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.query('{job="demo"}')
            assert len(result) == 2
            assert isinstance(result[0], LogEntry)
            assert "connection refused" in result[0].message

    @pytest.mark.asyncio
    async def test_query_failure_returns_empty(self):
        client = LokiClient("http://localhost:3100")
        with patch.object(client._http, "get", new_callable=AsyncMock, side_effect=Exception("down")):
            result = await client.query('{job="demo"}')
            assert result == []

    @pytest.mark.asyncio
    async def test_is_available_true(self):
        client = LokiClient("http://localhost:3100")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            assert await client.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_false(self):
        client = LokiClient("http://localhost:3100")
        with patch.object(client._http, "get", new_callable=AsyncMock, side_effect=Exception("down")):
            assert await client.is_available() is False


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------


class TestMetricsCollector:
    @pytest.mark.asyncio
    async def test_start_and_stop(self, settings):
        from agent.collector.collector import MetricsCollector

        mock_provider = AsyncMock()
        mock_provider.list_services = AsyncMock(return_value=[])
        mock_engine = AsyncMock()

        collector = MetricsCollector(settings, mock_provider, mock_engine)
        assert not collector.is_running

        await collector.start()
        assert collector.is_running

        await collector.stop()
        assert not collector.is_running

    @pytest.mark.asyncio
    async def test_start_idempotent(self, settings):
        from agent.collector.collector import MetricsCollector

        mock_provider = AsyncMock()
        mock_provider.list_services = AsyncMock(return_value=[])
        mock_engine = AsyncMock()

        collector = MetricsCollector(settings, mock_provider, mock_engine)
        await collector.start()
        await collector.start()  # Should not create duplicate task
        assert collector.is_running
        await collector.stop()

    @pytest.mark.asyncio
    async def test_collect_once_empty(self, settings):
        from agent.collector.collector import MetricsCollector

        mock_provider = AsyncMock()
        mock_provider.list_services = AsyncMock(return_value=[])
        mock_engine = AsyncMock()

        collector = MetricsCollector(settings, mock_provider, mock_engine)
        result = await collector.collect_once()
        assert result == {}
