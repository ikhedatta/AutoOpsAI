"""
LogQL query helper — talks to the existing Loki instance.
"""

from __future__ import annotations

import logging

import httpx

from agent.models import LogEntry

logger = logging.getLogger(__name__)


class LokiClient:

    def __init__(self, base_url: str = "http://localhost:3100"):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=10.0)

    async def query(self, logql: str, limit: int = 100) -> list[LogEntry]:
        """Run a LogQL query and return parsed log entries."""
        try:
            resp = await self._http.get(
                f"{self.base_url}/loki/api/v1/query_range",
                params={"query": logql, "limit": str(limit)},
            )
            resp.raise_for_status()
            data = resp.json()
            entries = []
            for stream in data.get("data", {}).get("result", []):
                for ts, line in stream.get("values", []):
                    entries.append(LogEntry(message=line, source="loki"))
            return entries
        except Exception:
            logger.warning("Loki query failed: %s", logql, exc_info=True)
            return []

    async def is_available(self) -> bool:
        try:
            resp = await self._http.get(f"{self.base_url}/ready")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._http.aclose()
