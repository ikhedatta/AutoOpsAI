"""Tests for agent.collector — Prometheus client, Loki client, Grafana client, collector loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.collector.prometheus_client import PrometheusClient
from agent.collector.loki_client import LokiClient
from agent.collector.grafana_client import GrafanaClient
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
        mock_resp.json.return_value = {"status": "success", "data": {"result": [{"metric": {"__name__": "up"}, "value": [1, "1"]}]}}

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
        mock_resp.json.return_value = {"status": "success", "data": {"result": []}}

        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.query_range("up", duration_minutes=30)
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
# PrometheusClient — new methods
# ---------------------------------------------------------------------------


class TestPrometheusClientExtended:
    @pytest.mark.asyncio
    async def test_get_targets(self):
        client = PrometheusClient("http://localhost:9090")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "data": {
                "activeTargets": [
                    {"labels": {"job": "node", "instance": "localhost:9100"}, "health": "up",
                     "lastScrape": "2026-04-08T09:00:00Z", "lastError": ""},
                ]
            },
        }
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            targets = await client.get_targets()
            assert len(targets) == 1
            assert targets[0]["job"] == "node"
            assert targets[0]["health"] == "up"

    @pytest.mark.asyncio
    async def test_get_alerts_empty(self):
        client = PrometheusClient("http://localhost:9090")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"status": "success", "data": {"alerts": []}}
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            alerts = await client.get_alerts()
            assert alerts == []

    @pytest.mark.asyncio
    async def test_get_metric_names(self):
        client = PrometheusClient("http://localhost:9090")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"status": "success", "data": ["up", "node_cpu_seconds_total"]}
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            names = await client.get_metric_names()
            assert "up" in names


# ---------------------------------------------------------------------------
# LokiClient — new methods
# ---------------------------------------------------------------------------


class TestLokiClientExtended:
    @pytest.mark.asyncio
    async def test_get_labels(self):
        client = LokiClient("http://localhost:3100")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": ["container", "job", "host"]}
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            labels = await client.get_labels()
            assert "container" in labels

    @pytest.mark.asyncio
    async def test_get_label_values(self):
        client = LokiClient("http://localhost:3100")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": ["grafana", "loki", "prometheus"]}
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            values = await client.get_label_values("container")
            assert "grafana" in values

    @pytest.mark.asyncio
    async def test_query_raw(self):
        client = LokiClient("http://localhost:3100")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": {"result": [{"stream": {"container": "nginx"}, "values": [["123", "line1"]]}]}
        }
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            streams = await client.query_raw('{container="nginx"}')
            assert len(streams) == 1


# ---------------------------------------------------------------------------
# GrafanaClient
# ---------------------------------------------------------------------------


class TestGrafanaClient:
    @pytest.mark.asyncio
    async def test_is_available_true(self):
        client = GrafanaClient("http://localhost:3000")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            assert await client.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_false(self):
        client = GrafanaClient("http://localhost:3000")
        with patch.object(client._http, "get", new_callable=AsyncMock, side_effect=Exception("down")):
            assert await client.is_available() is False

    @pytest.mark.asyncio
    async def test_list_dashboards(self):
        client = GrafanaClient("http://localhost:3000")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"uid": "abc", "title": "My Dashboard", "url": "/d/abc/my-dashboard", "tags": ["test"]},
        ]
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            dashboards = await client.list_dashboards()
            assert len(dashboards) == 1
            assert dashboards[0]["uid"] == "abc"

    @pytest.mark.asyncio
    async def test_get_dashboard(self):
        client = GrafanaClient("http://localhost:3000")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "dashboard": {
                "uid": "abc",
                "title": "My Dashboard",
                "tags": [],
                "panels": [
                    {"id": 1, "title": "CPU", "type": "timeseries", "targets": [{"expr": "node_cpu_seconds_total"}]},
                ],
            }
        }
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_dashboard("abc")
            assert result is not None
            assert result["uid"] == "abc"
            assert len(result["panels"]) == 1
            assert result["panels"][0]["queries"] == ["node_cpu_seconds_total"]

    @pytest.mark.asyncio
    async def test_get_datasources(self):
        client = GrafanaClient("http://localhost:3000")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"name": "Prometheus", "type": "prometheus", "url": "http://prom:9090", "isDefault": True},
        ]
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            sources = await client.get_datasources()
            assert len(sources) == 1
            assert sources[0]["name"] == "Prometheus"
            assert sources[0]["is_default"] is True

    @pytest.mark.asyncio
    async def test_get_annotations_empty(self):
        client = GrafanaClient("http://localhost:3000")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = []
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            annotations = await client.get_annotations()
            assert annotations == []


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
