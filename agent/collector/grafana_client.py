"""
Grafana HTTP API client — talks to the existing Grafana instance.

Provides dashboard discovery, panel/query extraction, annotation retrieval,
and datasource listing.  Used by the agent for context enrichment and by
API routes to expose observability data to the dashboard.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GrafanaClient:

    def __init__(
        self,
        base_url: str = "http://localhost:3000",
        username: str = "",
        password: str = "",
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Use basic auth when credentials are provided
        self._auth = httpx.BasicAuth(username, password) if username else None
        self._http = httpx.AsyncClient(
            timeout=timeout,
            auth=self._auth,
            headers={"Content-Type": "application/json"},
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def is_available(self) -> bool:
        try:
            resp = await self._http.get(f"{self.base_url}/api/health")
            return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Dashboards
    # ------------------------------------------------------------------

    async def list_dashboards(self, query: str | None = None) -> list[dict[str, Any]]:
        """Search for dashboards, optionally filtered by query string."""
        try:
            params: dict[str, str] = {"type": "dash-db"}
            if query:
                params["query"] = query
            resp = await self._http.get(
                f"{self.base_url}/api/search", params=params
            )
            resp.raise_for_status()
            return [
                {
                    "uid": d.get("uid"),
                    "title": d.get("title"),
                    "url": d.get("url"),
                    "tags": d.get("tags", []),
                }
                for d in resp.json()
            ]
        except Exception:
            logger.warning("Grafana list_dashboards failed", exc_info=True)
            return []

    async def get_dashboard(self, uid: str) -> dict[str, Any] | None:
        """Get full dashboard definition by UID, including panels and their queries."""
        try:
            resp = await self._http.get(
                f"{self.base_url}/api/dashboards/uid/{uid}"
            )
            resp.raise_for_status()
            body = resp.json()
            dashboard = body.get("dashboard", {})
            panels = []
            for p in dashboard.get("panels", []):
                panel_info: dict[str, Any] = {
                    "id": p.get("id"),
                    "title": p.get("title"),
                    "type": p.get("type"),
                }
                targets = p.get("targets", [])
                if targets:
                    panel_info["queries"] = [
                        t.get("expr") or t.get("query", "") for t in targets
                    ]
                panels.append(panel_info)
            return {
                "uid": dashboard.get("uid"),
                "title": dashboard.get("title"),
                "tags": dashboard.get("tags", []),
                "panels": panels,
            }
        except Exception:
            logger.warning("Grafana get_dashboard(%s) failed", uid, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Annotations (alert events)
    # ------------------------------------------------------------------

    async def get_annotations(
        self,
        dashboard_uid: str | None = None,
        duration_minutes: int = 60,
    ) -> list[dict[str, Any]]:
        """Get annotations (events/alerts) from Grafana."""
        try:
            now = datetime.now(timezone.utc)
            start = now - timedelta(minutes=duration_minutes)
            params: dict[str, str] = {
                "from": str(int(start.timestamp() * 1000)),
                "to": str(int(now.timestamp() * 1000)),
            }
            if dashboard_uid:
                params["dashboardUID"] = dashboard_uid
            resp = await self._http.get(
                f"{self.base_url}/api/annotations", params=params
            )
            resp.raise_for_status()
            return [
                {
                    "id": a.get("id"),
                    "text": a.get("text"),
                    "tags": a.get("tags", []),
                    "time": a.get("time"),
                    "dashboard_uid": a.get("dashboardUID"),
                }
                for a in resp.json()
            ]
        except Exception:
            logger.warning("Grafana get_annotations failed", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Datasources
    # ------------------------------------------------------------------

    async def get_datasources(self) -> list[dict[str, Any]]:
        """List all configured data sources in Grafana."""
        try:
            resp = await self._http.get(f"{self.base_url}/api/datasources")
            resp.raise_for_status()
            return [
                {
                    "name": ds.get("name"),
                    "type": ds.get("type"),
                    "url": ds.get("url"),
                    "is_default": ds.get("isDefault", False),
                }
                for ds in resp.json()
            ]
        except Exception:
            logger.warning("Grafana get_datasources failed", exc_info=True)
            return []

    async def close(self) -> None:
        await self._http.aclose()
