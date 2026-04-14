"""
PromQL query helper — talks to the existing Prometheus instance.

Provides instant queries, range queries, target discovery, alert state,
and metric name listing.  Used by the collector for trend analysis and
by the anomaly detector for duration/rate-based detection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class PrometheusClient:

    def __init__(self, base_url: str = "http://localhost:9090", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=timeout, verify=False)

    # ------------------------------------------------------------------
    # Instant query
    # ------------------------------------------------------------------

    async def query(self, promql: str) -> list[dict[str, Any]]:
        """Instant PromQL query — returns current metric values."""
        try:
            resp = await self._http.get(
                f"{self.base_url}/api/v1/query",
                params={"query": promql},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "success":
                logger.warning("Prometheus query error: %s", data.get("error"))
                return []
            return data.get("data", {}).get("result", [])
        except Exception:
            logger.warning("Prometheus query failed: %s", promql, exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Range query
    # ------------------------------------------------------------------

    async def query_range(
        self,
        promql: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        step: str = "60s",
        duration_minutes: int = 30,
    ) -> list[dict[str, Any]]:
        """Range PromQL query — returns time-series data over a window."""
        now = datetime.now(timezone.utc)
        if end is None:
            end = now
        if start is None:
            start = (end if isinstance(end, datetime) else now) - timedelta(minutes=duration_minutes)

        start_str = start.isoformat() if isinstance(start, datetime) else start
        end_str = end.isoformat() if isinstance(end, datetime) else end

        try:
            resp = await self._http.get(
                f"{self.base_url}/api/v1/query_range",
                params={"query": promql, "start": start_str, "end": end_str, "step": step},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "success":
                logger.warning("Prometheus range query error: %s", data.get("error"))
                return []
            return data.get("data", {}).get("result", [])
        except Exception:
            logger.warning("Prometheus range query failed: %s", promql, exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Scrape targets
    # ------------------------------------------------------------------

    async def get_targets(self) -> list[dict[str, Any]]:
        """Get all configured scrape targets and their health status."""
        try:
            resp = await self._http.get(f"{self.base_url}/api/v1/targets")
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") != "success":
                return []
            targets = []
            for t in body["data"].get("activeTargets", []):
                targets.append({
                    "job": t.get("labels", {}).get("job"),
                    "instance": t.get("labels", {}).get("instance"),
                    "health": t.get("health"),
                    "last_scrape": t.get("lastScrape"),
                    "last_error": t.get("lastError") or None,
                })
            return targets
        except Exception:
            logger.warning("Prometheus get_targets failed", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Active alerts
    # ------------------------------------------------------------------

    async def get_alerts(self) -> list[dict[str, Any]]:
        """Get all active alert rules from Prometheus."""
        try:
            resp = await self._http.get(f"{self.base_url}/api/v1/alerts")
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") != "success":
                return []
            return body["data"].get("alerts", [])
        except Exception:
            logger.warning("Prometheus get_alerts failed", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Metric name listing
    # ------------------------------------------------------------------

    async def get_metric_names(self, match: str | None = None) -> list[str]:
        """List available metric names, optionally filtered by prefix."""
        try:
            params: dict[str, str] = {}
            if match:
                params["match[]"] = match
            resp = await self._http.get(
                f"{self.base_url}/api/v1/label/__name__/values",
                params=params,
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") != "success":
                return []
            names = body.get("data", [])
            return names[:500]  # cap to avoid huge payloads
        except Exception:
            logger.warning("Prometheus get_metric_names failed", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def is_available(self) -> bool:
        try:
            resp = await self._http.get(f"{self.base_url}/-/healthy")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._http.aclose()
