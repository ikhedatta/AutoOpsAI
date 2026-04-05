"""
PromQL query helper — talks to the existing Prometheus instance.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class PrometheusClient:

    def __init__(self, base_url: str = "http://localhost:9090"):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=10.0)

    async def query(self, promql: str) -> list[dict[str, Any]]:
        """Instant PromQL query."""
        try:
            resp = await self._http.get(
                f"{self.base_url}/api/v1/query",
                params={"query": promql},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("result", [])
        except Exception:
            logger.warning("Prometheus query failed: %s", promql, exc_info=True)
            return []

    async def query_range(
        self, promql: str, start: str, end: str, step: str = "15s"
    ) -> list[dict[str, Any]]:
        """Range PromQL query."""
        try:
            resp = await self._http.get(
                f"{self.base_url}/api/v1/query_range",
                params={"query": promql, "start": start, "end": end, "step": step},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("result", [])
        except Exception:
            logger.warning("Prometheus range query failed: %s", promql, exc_info=True)
            return []

    async def is_available(self) -> bool:
        try:
            resp = await self._http.get(f"{self.base_url}/-/healthy")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._http.aclose()
