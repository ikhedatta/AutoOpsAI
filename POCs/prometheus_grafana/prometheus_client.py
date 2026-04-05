"""
Prometheus HTTP API client.

Queries Prometheus for metrics using PromQL.
Docs: https://prometheus.io/docs/prometheus/latest/querying/api/
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

DEFAULT_PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")


@dataclass
class PrometheusResult:
    success: bool
    data: dict | list | None = None
    error: str | None = None


class PrometheusClient:
    def __init__(self, base_url: str = DEFAULT_PROMETHEUS_URL, timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def health_check(self) -> bool:
        """Check if Prometheus is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/-/healthy")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def instant_query(self, query: str) -> PrometheusResult:
        """Execute an instant PromQL query (current value)."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/query",
                    params={"query": query},
                )
                resp.raise_for_status()
                body = resp.json()
                if body["status"] == "success":
                    return PrometheusResult(success=True, data=body["data"])
                return PrometheusResult(success=False, error=body.get("error", "Unknown error"))
        except Exception as e:
            return PrometheusResult(success=False, error=str(e))

    async def range_query(
        self, query: str, start: datetime | None = None, end: datetime | None = None,
        step: str = "60s", duration_minutes: int = 30,
    ) -> PrometheusResult:
        """Execute a range PromQL query (time series over a window)."""
        now = datetime.utcnow()
        end = end or now
        start = start or (end - timedelta(minutes=duration_minutes))

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/query_range",
                    params={
                        "query": query,
                        "start": start.isoformat() + "Z",
                        "end": end.isoformat() + "Z",
                        "step": step,
                    },
                )
                resp.raise_for_status()
                body = resp.json()
                if body["status"] == "success":
                    return PrometheusResult(success=True, data=body["data"])
                return PrometheusResult(success=False, error=body.get("error", "Unknown error"))
        except Exception as e:
            return PrometheusResult(success=False, error=str(e))

    async def get_targets(self) -> PrometheusResult:
        """Get all configured scrape targets and their health."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/api/v1/targets")
                resp.raise_for_status()
                body = resp.json()
                if body["status"] == "success":
                    targets = []
                    for t in body["data"].get("activeTargets", []):
                        targets.append({
                            "job": t.get("labels", {}).get("job"),
                            "instance": t.get("labels", {}).get("instance"),
                            "health": t.get("health"),
                            "last_scrape": t.get("lastScrape"),
                            "last_error": t.get("lastError") or None,
                        })
                    return PrometheusResult(success=True, data=targets)
                return PrometheusResult(success=False, error=body.get("error"))
        except Exception as e:
            return PrometheusResult(success=False, error=str(e))

    async def get_alerts(self) -> PrometheusResult:
        """Get all active alerts from Prometheus."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/api/v1/alerts")
                resp.raise_for_status()
                body = resp.json()
                if body["status"] == "success":
                    return PrometheusResult(success=True, data=body["data"].get("alerts", []))
                return PrometheusResult(success=False, error=body.get("error"))
        except Exception as e:
            return PrometheusResult(success=False, error=str(e))

    async def get_metric_names(self, match: str | None = None) -> PrometheusResult:
        """List available metric names, optionally filtered by a prefix/pattern."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                params = {}
                if match:
                    params["match[]"] = f'{match}'
                resp = await client.get(f"{self.base_url}/api/v1/label/__name__/values", params=params)
                resp.raise_for_status()
                body = resp.json()
                if body["status"] == "success":
                    names = body["data"]
                    if match:
                        names = [n for n in names if match.lower() in n.lower()]
                    return PrometheusResult(success=True, data=names[:100])  # cap at 100
                return PrometheusResult(success=False, error=body.get("error"))
        except Exception as e:
            return PrometheusResult(success=False, error=str(e))
