"""
Grafana HTTP API client.

Queries Grafana for dashboards, panels, and annotations.
Also queries Loki (via Grafana) for logs using LogQL.
Docs: https://grafana.com/docs/grafana/latest/developers/http_api/
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

DEFAULT_GRAFANA_URL = os.getenv("GRAFANA_URL", "http://localhost:3000")
DEFAULT_LOKI_URL = os.getenv("LOKI_URL", "http://localhost:3100")


@dataclass
class GrafanaResult:
    success: bool
    data: dict | list | None = None
    error: str | None = None


class GrafanaClient:
    def __init__(
        self,
        base_url: str = DEFAULT_GRAFANA_URL,
        api_key: str | None = None,
        timeout: float = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    async def health_check(self) -> bool:
        """Check if Grafana is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/health")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def list_dashboards(self, query: str | None = None) -> GrafanaResult:
        """Search for dashboards, optionally filtered by query string."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
                params = {"type": "dash-db"}
                if query:
                    params["query"] = query
                resp = await client.get(f"{self.base_url}/api/search", params=params)
                resp.raise_for_status()
                dashboards = [
                    {
                        "uid": d.get("uid"),
                        "title": d.get("title"),
                        "url": d.get("url"),
                        "tags": d.get("tags", []),
                    }
                    for d in resp.json()
                ]
                return GrafanaResult(success=True, data=dashboards)
        except Exception as e:
            return GrafanaResult(success=False, error=str(e))

    async def get_dashboard(self, uid: str) -> GrafanaResult:
        """Get full dashboard definition by UID, including all panels."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
                resp = await client.get(f"{self.base_url}/api/dashboards/uid/{uid}")
                resp.raise_for_status()
                body = resp.json()
                dashboard = body.get("dashboard", {})
                panels = []
                for p in dashboard.get("panels", []):
                    panel_info = {
                        "id": p.get("id"),
                        "title": p.get("title"),
                        "type": p.get("type"),
                    }
                    # Extract PromQL queries from panel targets
                    targets = p.get("targets", [])
                    if targets:
                        panel_info["queries"] = [
                            t.get("expr") or t.get("query", "") for t in targets
                        ]
                    panels.append(panel_info)
                return GrafanaResult(success=True, data={
                    "uid": dashboard.get("uid"),
                    "title": dashboard.get("title"),
                    "tags": dashboard.get("tags", []),
                    "panels": panels,
                })
        except Exception as e:
            return GrafanaResult(success=False, error=str(e))

    async def get_annotations(
        self, dashboard_uid: str | None = None, duration_minutes: int = 60,
    ) -> GrafanaResult:
        """Get annotations (events/alerts) from Grafana."""
        try:
            now = datetime.utcnow()
            start = now - timedelta(minutes=duration_minutes)
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
                params = {
                    "from": str(int(start.timestamp() * 1000)),
                    "to": str(int(now.timestamp() * 1000)),
                }
                if dashboard_uid:
                    params["dashboardUID"] = dashboard_uid
                resp = await client.get(f"{self.base_url}/api/annotations", params=params)
                resp.raise_for_status()
                annotations = [
                    {
                        "id": a.get("id"),
                        "text": a.get("text"),
                        "tags": a.get("tags", []),
                        "time": a.get("time"),
                        "dashboard_uid": a.get("dashboardUID"),
                    }
                    for a in resp.json()
                ]
                return GrafanaResult(success=True, data=annotations)
        except Exception as e:
            return GrafanaResult(success=False, error=str(e))

    async def get_datasources(self) -> GrafanaResult:
        """List all configured data sources in Grafana."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
                resp = await client.get(f"{self.base_url}/api/datasources")
                resp.raise_for_status()
                sources = [
                    {
                        "name": ds.get("name"),
                        "type": ds.get("type"),
                        "url": ds.get("url"),
                        "is_default": ds.get("isDefault", False),
                    }
                    for ds in resp.json()
                ]
                return GrafanaResult(success=True, data=sources)
        except Exception as e:
            return GrafanaResult(success=False, error=str(e))


class LokiClient:
    """Client for Grafana Loki log aggregation via LogQL."""

    def __init__(self, base_url: str = DEFAULT_LOKI_URL, timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/ready")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def query_logs(
        self, query: str, limit: int = 100, duration_minutes: int = 30,
    ) -> GrafanaResult:
        """
        Query logs using LogQL.

        Examples:
            {job="flask-app"} |= "error"
            {container="nginx"} | json | status >= 500
        """
        now = datetime.utcnow()
        start = now - timedelta(minutes=duration_minutes)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/loki/api/v1/query_range",
                    params={
                        "query": query,
                        "start": str(int(start.timestamp() * 1_000_000_000)),
                        "end": str(int(now.timestamp() * 1_000_000_000)),
                        "limit": limit,
                    },
                )
                resp.raise_for_status()
                body = resp.json()
                if body["status"] == "success":
                    streams = body["data"].get("result", [])
                    log_lines = []
                    for stream in streams:
                        labels = stream.get("stream", {})
                        for ts, line in stream.get("values", []):
                            log_lines.append({
                                "labels": labels,
                                "timestamp": ts,
                                "line": line,
                            })
                    return GrafanaResult(success=True, data=log_lines)
                return GrafanaResult(success=False, error=body.get("error"))
        except Exception as e:
            return GrafanaResult(success=False, error=str(e))

    async def get_label_values(self, label: str = "job") -> GrafanaResult:
        """Get all values for a log label (e.g., list all job names)."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/loki/api/v1/label/{label}/values")
                resp.raise_for_status()
                body = resp.json()
                return GrafanaResult(success=True, data=body.get("data", []))
        except Exception as e:
            return GrafanaResult(success=False, error=str(e))
